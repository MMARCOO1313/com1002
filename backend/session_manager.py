"""
SessionManager — Autonomous session lifecycle for BridgeSpace.

v2.2 booking rules (uniform across all sports):
  - Every session is exactly SESSION_DURATION (1 hour).
  - One active session per user. No concurrent bookings.
  - Each user gets MAX_DAILY_MINUTES (120 min = 2 hours) per calendar day.
  - An extension adds EXTEND_ADD_SECONDS (1 hour) and can only be requested
    in the final EXTEND_WINDOW (last 10 min). MAX_EXTENSIONS = 1, so the
    upper bound of a single session is 2 hours — exactly the daily quota.
"""

import asyncio
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Optional

# ── Uniform booking window ────────────────────────────────────────────────
SESSION_DURATION    = 60 * 60       # 1 hour — fixed for every sport
EXTEND_ADD_SECONDS  = 60 * 60       # +1 hour per extension
EXTEND_WINDOW       = 10 * 60       # extension only allowed in final 10 min
MAX_EXTENSIONS      = 1             # one extension per session
MAX_DAILY_MINUTES   = 120           # 2 hours per user per calendar day

# Kept for backwards-compat, but now == EXTEND_WINDOW (both = 10 min)
WARNING_BEFORE      = EXTEND_WINDOW
OVERSTAY_WARN       = 5 * 60        # Telegram after 5 min overstay
OVERSTAY_CRIT       = 10 * 60       # phone call after 10 min overstay
NOSHOW_TIMEOUT      = 15 * 60       # auto-skip if not entered within 15 min

# Legacy name kept so other modules that import it don't break
DEFAULT_DURATION    = SESSION_DURATION


class SessionManager:
    def __init__(self, get_db, broadcast, smart_control=None, alert_engine=None):
        self.get_db = get_db
        self.broadcast = broadcast
        self.ctrl = smart_control
        self.alert = alert_engine

    # ── Quota helpers ─────────────────────────────────────────────────────

    def get_user_daily_minutes(self, user_id: str) -> int:
        """Sum of planned session minutes today for this user.

        Counts every non-cancelled session started today using
        (expires_at − started_at). Extensions naturally raise expires_at,
        so extending bumps the reported total.
        """
        conn = self.get_db()
        today = datetime.now().date().isoformat()
        rows = conn.execute(
            """SELECT started_at, expires_at, status FROM sessions
               WHERE user_id=? AND date(started_at)=?
                 AND status != 'cancelled'""",
            (user_id, today),
        ).fetchall()
        conn.close()
        total = 0.0
        for r in rows:
            try:
                start = datetime.fromisoformat(r["started_at"])
                end   = datetime.fromisoformat(r["expires_at"])
                total += max(0.0, (end - start).total_seconds() / 60.0)
            except Exception:
                pass
        return int(round(total))

    def get_user_active_session(self, user_id: str):
        """Return the user's current active session row (dict) or None."""
        conn = self.get_db()
        row = conn.execute(
            """SELECT * FROM sessions
               WHERE user_id=? AND status IN ('active','warning','expired','overstay')
               ORDER BY started_at DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def user_has_booking_today(self, user_id: str) -> bool:
        """True if this user has started any session today that isn't cancelled.
        Used to enforce the "one booking per person per day" rule — to get a
        second hour you must extend the existing session, not book anew.
        """
        conn = self.get_db()
        today = datetime.now().date().isoformat()
        row = conn.execute(
            """SELECT COUNT(*) AS c FROM sessions
               WHERE user_id=? AND date(started_at)=?
                 AND status != 'cancelled'""",
            (user_id, today),
        ).fetchone()
        conn.close()
        return (row["c"] or 0) > 0

    def check_booking_quota(self, user_id: str, extra_minutes: int = None):
        """Return (ok: bool, message: str, remaining_minutes: int).

        Blocks a NEW booking if any of these is true:
          1. user already has an active session (one at a time);
          2. user has already used their one-per-day booking slot today
             (even if that earlier session has ended);
          3. adding `extra_minutes` would exceed MAX_DAILY_MINUTES.

        Rules 1 and 2 together enforce: "每人每日只可預約一次".
        Extensions do not go through this function — see extend_session.
        """
        if extra_minutes is None:
            extra_minutes = SESSION_DURATION // 60

        active = self.get_user_active_session(user_id)
        if active:
            return (
                False,
                f"你已有進行中場次（Zone {active['zone_id']} "
                f"第 {active['court_num']} 場） — 一次只能預約一個場地。",
                max(0, MAX_DAILY_MINUTES - self.get_user_daily_minutes(user_id)),
            )

        if self.user_has_booking_today(user_id):
            used = self.get_user_daily_minutes(user_id)
            return (
                False,
                "你今日已預約過一次場次 — 每人每日只可預約一次，"
                "要多打一小時請於場次最後 10 分鐘選擇延長。",
                max(0, MAX_DAILY_MINUTES - used),
            )

        used = self.get_user_daily_minutes(user_id)
        remain = max(0, MAX_DAILY_MINUTES - used)
        if used + extra_minutes > MAX_DAILY_MINUTES:
            return (
                False,
                f"今日預約額度只剩 {remain} 分鐘，不足以開新場次（{extra_minutes} 分鐘）。",
                remain,
            )
        return (True, "", remain)

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
                            queue_id: Optional[str] = None,
                            enforce_quota: bool = True) -> dict:
        """Start a 1-hour session.

        Returns {"ok": True, "session_id", ...} on success,
        or {"ok": False, "quota_blocked": True, "message": ...} on quota fail.
        `enforce_quota=False` is used by demo/book which has synthetic users.
        """
        if enforce_quota:
            ok, msg, remain = self.check_booking_quota(user_id)
            if not ok:
                return {
                    "ok": False,
                    "quota_blocked": True,
                    "session_id": None,
                    "message": msg,
                    "remaining_minutes": remain,
                }

        conn = self.get_db()
        court_num = self._next_free_court(conn, zone_id)

        now = datetime.now()
        expires = now + timedelta(seconds=SESSION_DURATION)
        sid = "S-" + str(uuid.uuid4())[:8].upper()

        conn.execute(
            """INSERT INTO sessions
               (id, user_id, zone_id, court_num, queue_id, started_at, expires_at, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sid, user_id, zone_id, court_num, queue_id,
             now.isoformat(), expires.isoformat(), "active")
        )
        if queue_id:
            conn.execute(
                "UPDATE queue SET status='entered', entered_at=? WHERE id=?",
                (now.isoformat(), queue_id)
            )
        conn.commit()
        conn.close()

        if self.ctrl:
            await self.ctrl.zone_reset(zone_id)

        await self._broadcast_sessions()
        return {
            "ok": True,
            "session_id": sid,
            "court_num": court_num,
            "expires_at": expires.isoformat(),
            "duration_min": SESSION_DURATION // 60,
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
            return {"ok": False, "message": "找不到該場次"}

        # ① only one extension per session
        if s["extended"] >= MAX_EXTENSIONS:
            conn.close()
            return {"ok": False,
                    "message": "每個場次只可延長一次，今日額度已用滿。"}

        # ② must be in the last EXTEND_WINDOW of the session
        now = datetime.now()
        try:
            expires = datetime.fromisoformat(s["expires_at"])
        except Exception:
            conn.close()
            return {"ok": False, "message": "場次時間資料異常"}

        time_left = (expires - now).total_seconds()
        if time_left > EXTEND_WINDOW:
            conn.close()
            mins = int(time_left // 60)
            return {"ok": False,
                    "message": f"還有 {mins} 分鐘 — 要在最後 "
                               f"{EXTEND_WINDOW // 60} 分鐘內才可申請延長。",
                    "too_early": True,
                    "time_left_seconds": int(time_left)}

        if time_left < -60:
            conn.close()
            return {"ok": False, "message": "場次已結束，無法再延長。"}

        # ③ daily quota check for the extra hour
        add_min = EXTEND_ADD_SECONDS // 60
        used = self.get_user_daily_minutes(s["user_id"])
        if used + add_min > MAX_DAILY_MINUTES:
            remain = max(0, MAX_DAILY_MINUTES - used)
            conn.close()
            return {"ok": False,
                    "message": f"今日預約額度只剩 {remain} 分鐘，"
                               f"不足以延長 {add_min} 分鐘。"}

        # ④ respect the queue — can't extend when people are waiting
        waiting = conn.execute(
            "SELECT COUNT(*) as c FROM queue WHERE zone_id=? AND status='waiting'",
            (s["zone_id"],)
        ).fetchone()["c"]
        if waiting > 0:
            conn.close()
            return {"ok": False,
                    "message": f"有 {waiting} 人正在輪候此區，為公平起見不能延長。"}

        new_expires = expires + timedelta(seconds=EXTEND_ADD_SECONDS)
        conn.execute(
            "UPDATE sessions SET expires_at=?, extended=extended+1, status='active' "
            "WHERE id=?",
            (new_expires.isoformat(), session_id),
        )
        conn.commit()
        conn.close()

        if self.ctrl:
            await self.ctrl.zone_reset(s["zone_id"])

        await self._broadcast_sessions()
        return {
            "ok": True,
            "new_expires": new_expires.isoformat(),
            "extensions_remaining": MAX_EXTENSIONS - s["extended"] - 1,
            "message": f"已延長 {add_min} 分鐘，現時場次至 "
                       f"{new_expires.strftime('%H:%M')}。",
        }

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

