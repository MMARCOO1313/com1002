"""
AutoQueue + OccupancyWatcher — Autonomous queue advancement.
Monitors SmartCount data, detects departures, and auto-calls next in line.
Closes the Sense → Decide → Act loop for fully unmanned operation.
"""

import asyncio
from datetime import datetime
from typing import Optional


STABLE_TICKS_REQUIRED = 3   # confirm departure after 3 consecutive lower readings
WALKIN_THRESHOLD = 0.5      # allow walk-in when < 50% capacity


class OccupancyWatcher:
    """Watches for occupancy drops and triggers auto-queue advancement."""

    def __init__(self, get_db, broadcast, session_manager=None,
                 smart_control=None, alert_engine=None):
        self.get_db = get_db
        self.broadcast = broadcast
        self.sm = session_manager
        self.ctrl = smart_control
        self.alert = alert_engine
        self.prev_counts = {}     # zone_id → last confirmed count
        self.drop_ticks = {}      # zone_id → consecutive ticks with lower count
        self.drop_target = {}     # zone_id → the lower count we're tracking

    async def on_occupancy_update(self, zone_id: str, new_count: int):
        """Called every time SmartCount pushes a new reading."""
        old = self.prev_counts.get(zone_id, new_count)

        # ── Overcapacity alert ──────────────────────────────────────────────
        conn = self.get_db()
        zone = conn.execute(
            "SELECT capacity FROM zones WHERE id=?", (zone_id,)
        ).fetchone()
        conn.close()

        if zone and new_count > zone["capacity"]:
            if self.alert:
                await self.alert.alert_overcapacity(
                    zone_id, new_count, zone["capacity"])

        # ── Departure detection ──────────────────────────────────────────────
        if new_count < old:
            target = self.drop_target.get(zone_id, new_count)
            if new_count <= target:
                self.drop_ticks[zone_id] = self.drop_ticks.get(zone_id, 0) + 1
                self.drop_target[zone_id] = new_count
            else:
                # Count went back up — false alarm
                self.drop_ticks[zone_id] = 0
                self.drop_target.pop(zone_id, None)

            if self.drop_ticks.get(zone_id, 0) >= STABLE_TICKS_REQUIRED:
                # Confirmed departure
                departed_count = old - new_count
                await self._handle_departure(zone_id, departed_count)
                self.drop_ticks[zone_id] = 0
                self.drop_target.pop(zone_id, None)

        elif new_count >= old:
            # Count stable or rising — reset departure tracking
            self.drop_ticks[zone_id] = 0
            self.drop_target.pop(zone_id, None)

        self.prev_counts[zone_id] = new_count

    async def _handle_departure(self, zone_id: str, departed_count: int):
        """Someone left: end session → reset zone → auto-call next."""

        # 1. End the active session
        if self.sm:
            ended = await self.sm.end_session(zone_id)
            if ended:
                print(f"[AutoQueue] Session ended in Zone {zone_id}")

        # 2. Reset zone equipment (lights on, equipment deploy)
        if self.ctrl:
            await self.ctrl.zone_reset(zone_id)

        # 3. Auto-call next person in queue
        await self._auto_call_next(zone_id)

    async def _auto_call_next(self, zone_id: str):
        """Automatically call the next waiting person for this zone."""
        conn = self.get_db()
        next_person = conn.execute(
            """SELECT * FROM queue
               WHERE zone_id=? AND status='waiting'
               ORDER BY queue_num ASC LIMIT 1""",
            (zone_id,)
        ).fetchone()

        if not next_person:
            print(f"[AutoQueue] Zone {zone_id}: queue empty, open for walk-in")
            conn.close()
            return

        # Mark as called
        conn.execute(
            "UPDATE queue SET status='called', called_at=? WHERE id=?",
            (datetime.now().isoformat(), next_person["id"])
        )
        conn.commit()

        user = conn.execute(
            "SELECT * FROM users WHERE id=?",
            (next_person["user_id"],)
        ).fetchone()

        # Get updated queue snapshot
        queue_data = self._get_queue_snapshot(conn)
        conn.close()

        user_name = user["name"] if user else "用戶"
        print(f"[AutoQueue] Zone {zone_id}: auto-called #{next_person['queue_num']} ({user_name})")

        # Broadcast to all screens
        await self.broadcast({
            "type": "called",
            "zone_id": zone_id,
            "queue_num": next_person["queue_num"],
            "user_name": user_name,
            "queue": queue_data,
            "auto": True,  # flag: this was automatic, not manual
        })

    def _get_queue_snapshot(self, conn):
        rows = conn.execute(
            """SELECT q.zone_id, q.queue_num, q.status, u.name
               FROM queue q LEFT JOIN users u ON q.user_id=u.id
               WHERE q.status IN ('waiting','called')
               ORDER BY q.zone_id, q.queue_num"""
        ).fetchall()
        return [dict(r) for r in rows]
