"""
SessionManager — Autonomous session lifecycle for BridgeSpace.
Tracks per-user time slots **per court**, handles expiry warnings,
overstay escalation, and coordinates with SmartControl + AlertEngine.

v2.1: Sessions now bind to a specific court_num within each zone.
"""

import asyncio
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Optional

# ─── Default duration fallback (seconds) ───────────────────────────────────
# Actual duration is read from the zones table (changes when sport mode switches).
DEFAULT_DURATION = 2700  # 45 min fallback

WARNING_BEFORE  = 5 * 60    # flash lights 5 min before expiry
OVERSTAY_WARN   = 5 * 60    # Telegram after 5 min overstay
OVERSTAY_CRIT   = 10 * 60   # phone call after 10 min overstay
MAX_EXTENSIONS  = 2          # max 2 extensions per session
NOSHOW_TIMEOUT  = 15 * 60   # auto-skip if not entered within 15 min


class SessionManager:
    def __init__(self, get_db, broadcast, smart_control=None, alert_engine=None):
        self.get_db = get_db
        self.broadcast = broadcast
        self.ctrl = smart_control
        self.alert = alert_engine

    # ── Find next free court in a zone ────────────────────────────────────

    def _next_free_court(self, conn, zone_id: str) -> int:
        """Return the lowest court number without an active session."""
        zone = conn.execute(
            "SELECT courts FROM zones WHERE id=?", (zone_id,)
        ).fetchone()
        total = zone["courts"] if zone else 1

        occupied = conn.execute(
            """SELECT court_num FROM sessions
               WHERE zone_id=? AND status IN ('active','warning','expired','overstay')""",
            (zone_id,)
        ).fetchall()
        occupied_nums = {r["court_num"] for r in occupied}

        for i in range(1, total + 1):
            if i not in occupied_nums:
                return i
        return 1  # fallback (shouldn't happen if caller checked availability)

    # ── Start a new session when user enters zone ──────────────────────────

    async def start_session(self, user_id: str, zone_id: str,
                            queue_id: Optional[str] = None) -> dict:
        conn = self.get_db()
        zone = conn.execute(
            "SELECT session_duration FROM zones WHERE id=?", (zone_id,)
        ).fetchone()
        duration = zone["session_duration"] if zone else DEFAULT_DURATION

        if duration == 0:
            conn.close()
            return {"session_id": None, "message": "This zone does not enforce a session timer."}

        court_num = self._next_free_court(conn, zone_id)

        now = datetime.now()
        expires = now + timedelta(seconds=duration)
        sid = "S-" + str(uuid.uuid4())[:8].upper()

        conn.execute(
            """INSERT INTO sessions
               (id, user_id, zone_id, court_num, queue_id, started_at, expires_at, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sid, user_id, zone_id, court_num, queue_id,
             now.isoformat(), expires.isoformat(), "active")
        )
        # Mark queue entry as 'entered'
        if queue_id:
            conn.execute(
                "UPDATE queue SET status='entered', entered_at=? WHERE id=?",
                (now.isoformat(), queue_id)
            )
        conn.commit()
        conn.close()

        # Turn on lights / deploy equipment
        if self.ctrl:
            await self.ctrl.zone_reset(zone_id)

        await self._broadcast_sessions()
        return {
            "session_id": sid,
            "court_num": court_num,
            "expires_at": expires.isoformat(),
            "duration_min": duration // 60,
        }

    # ── Periodic expiry checker (runs every 10s) ─────────────────────────

    async def check_expiry(self):
        conn = self.get_db()
        now = datetime.now()
        sessions = conn.execute(
            "SELECT * FROM sessions WHERE status IN ('active','warning','expired')"
        ).fetchall()

        for s in sessions:
            sid = s["id"]
            zone = s["zone_id"]
            expires = datetime.fromisoformat(s["expires_at"])
            status = s["status"]
            time_left = (expires - now).total_seconds()
            time_over = -time_left  # positive when overstaying

            # ── Phase 1: Warning (5 min before expiry) ─────────────────────
            if status == "active" and 0 < time_left <= WARNING_BEFORE:
                conn.execute(
                    "UPDATE sessions SET status='warning' WHERE id=?", (sid,))
                conn.commit()
                if self.ctrl:
                    await self.ctrl.lights_flash(zone)
                await self._broadcast_sessions()

            # ── Phase 2: Expired ─────────────────────────────────────────
            elif status in ("active", "warning") and time_left <= 0:
                conn.execute(
                    "UPDATE sessions SET status='expired' WHERE id=?", (sid,))
                conn.commit()
                if self.ctrl:
                    await self.ctrl.lights_off(zone)
                    await self.ctrl.equipment_retract(zone)
                await self._broadcast_sessions()

            # ── Phase 3: Overstay warning (5 min over) ───────────────────
            elif status == "expired" and time_over >= OVERSTAY_WARN:
                conn.execute(
                    "UPDATE sessions SET status='overstay' WHERE id=?", (sid,))
                conn.commit()
                if self.alert:
                    user = conn.execute(
                        "SELECT name FROM users WHERE id=?",
                        (s["user_id"],)).fetchone()
                    name = user["name"] if user else "Unknown"
                    await self.alert.alert_overstay(
                        zone, name, int(time_over // 60))
                await self._broadcast_sessions()

            # ── Phase 4: Overstay critical (10 min over) → phone ────────
            elif status == "overstay" and time_over >= OVERSTAY_CRIT:
                if self.alert:
                    await self.alert.alert_overstay_critical(
                        zone, int(time_over // 60))

        conn.close()

    # ── Extend session ─────────────────────────────────────────────────────

    async def extend_session(self, session_id: str) -> dict:
        conn = self.get_db()
        s = conn.execute(
            "SELECT * FROM sessions WHERE id=?", (session_id,)
        ).fetchone()

        if not s:
            conn.close()
            return {"ok": False, "message": "Session not found"}

        if s["extended"] >= MAX_EXTENSIONS:
            conn.close()
            return {"ok": False, "message": f"Maximum number of extensions reached ({MAX_EXTENSIONS})"}

        # Check if anyone is waiting in queue
        waiting = conn.execute(
            "SELECT COUNT(*) as c FROM queue WHERE zone_id=? AND status='waiting'",
            (s["zone_id"],)
        ).fetchone()["c"]

        if waiting > 0:
            conn.close()
            return {"ok": False, "message": f"Cannot extend while {waiting} people are waiting in the queue"}

        zone = conn.execute(
            "SELECT session_duration FROM zones WHERE id=?", (s["zone_id"],)
        ).fetchone()
        duration = zone["session_duration"] if zone else DEFAULT_DURATION
        new_expires = datetime.fromisoformat(s["expires_at"]) + timedelta(seconds=duration)

        conn.execute(
            "UPDATE sessions SET expires_at=?, extended=extended+1, status='active' WHERE id=?",
            (new_expires.isoformat(), session_id)
        )
        conn.commit()
        conn.close()

        if self.ctrl:
            await self.ctrl.zone_reset(s["zone_id"])

        await self._broadcast_sessions()
        return {"ok": True, "new_expires": new_expires.isoformat(),
                "extensions_remaining": MAX_EXTENSIONS - s["extended"] - 1}

    # ── End session (called by OccupancyWatcher on departure) ───────────

    async def end_session(self, zone_id: str) -> Optional[str]:
        """End the oldest active/expired/overstay session in a zone.
        Returns session_id if ended, None if no active session."""
        conn = self.get_db()
        s = conn.execute(
            """SELECT * FROM sessions
               WHERE zone_id=? AND status IN ('active','warning','expired','overstay')
               ORDER BY started_at ASC LIMIT 1""",
            (zone_id,)
        ).fetchone()

        if not s:
            conn.close()
            return None

        conn.execute(
            "UPDATE sessions SET status='ended', ended_at=? WHERE id=?",
            (datetime.now().isoformat(), s["id"])
        )
        conn.commit()
        conn.close()

        await self._broadcast_sessions()
        return s["id"]

    # ── No-show checker ────────────────────────────────────────────────────

    async def check_noshows(self):
        """Expire 'called' queue entries that haven't entered within NOSHOW_TIMEOUT."""
        conn = self.get_db()
        now = datetime.now()
        called = conn.execute(
            "SELECT * FROM queue WHERE status='called'"
        ).fetchall()

        for q in called:
            called_at = datetime.fromisoformat(q["called_at"])
            if (now - called_at).total_seconds() > NOSHOW_TIMEOUT:
                conn.execute(
                    "UPDATE queue SET status='expired' WHERE id=?", (q["id"],))
                conn.commit()
                if self.alert:
                    await self.alert.send_telegram(
                        f"ℹ️ Queue {q['queue_num']} (Zone {q['zone_id']}) "
                        f"no-show — auto-skipped after 15 min", "info")
        conn.close()

    # ── Helpers ────────────────────────────────────────────────────────────

    async def get_active_sessions(self) -> list:
        conn = self.get_db()
        rows = conn.execute(
            """SELECT s.*, u.name FROM sessions s
               LEFT JOIN users u ON s.user_id = u.id
               WHERE s.status IN ('active','warning','expired','overstay')
               ORDER BY s.zone_id, s.court_num, s.started_at"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    async def _broadcast_sessions(self):
        sessions = await self.get_active_sessions()
        await self.broadcast({"type": "sessions", "data": sessions})

