"""
SmartControl — IoT device controller for BridgeSpace zones.

Every zone is a "multi-function sports box" — each of the ten zones is
physically equipped with:
  - light (on/off/flash)
  - gate  (open/lock)
  - hoop  (deploy/retract)   — for basketball
  - net   (setup/remove)     — for badminton / pickleball / volleyball
  - table (setup/fold)       — for table tennis

All five devices exist in every zone, so commands are always accepted;
the zone's current sport allocation only influences which are in use,
not which are controllable.

In production: sends MQTT commands to Raspberry Pi actuators.
In demo/exhibition: logs actions + broadcasts state to frontend.
"""

import asyncio
import json
from datetime import datetime
from typing import Optional

from zone_catalog import DEFAULT_ZONES, SPORT_CONFIG


EQUIPMENT_LABELS = {
    "hoop":  {"zh": "籃框",  "deploy": "部署", "retract": "收起"},
    "net":   {"zh": "球網",  "setup": "架設",  "remove": "收起"},
    "table": {"zh": "球台",  "setup": "擺設",  "fold": "收起"},
}


class SmartControl:
    """Controls physical devices in each zone — all zones have all devices."""

    def __init__(self, get_db, broadcast, mqtt_client=None):
        self.get_db = get_db
        self.broadcast = broadcast
        self.mqtt = mqtt_client
        self.state = {}
        self._init_state()

    def _init_state(self):
        for zone in DEFAULT_ZONES:
            zid = zone["id"]
            # Every zone has every device at rest.
            self.state[zid] = {
                "light": "off",
                "gate":  "locked",
                "hoop":  "retracted",
                "net":   "removed",
                "table": "fold",
            }

    def update_zone_equipment(self, zone_id: str, allocation: list):
        """Ensure state row exists. Devices are always controllable —
        allocation no longer disables any device (multifunction box)."""
        if zone_id not in self.state:
            self.state[zone_id] = {
                "light": "off",
                "gate":  "locked",
                "hoop":  "retracted",
                "net":   "removed",
                "table": "fold",
            }
            return
        # Backfill any missing keys for zones created at runtime.
        defaults = {"light": "off", "gate": "locked", "hoop": "retracted",
                    "net": "removed", "table": "fold"}
        for k, v in defaults.items():
            if self.state[zone_id].get(k) in (None, "n/a"):
                self.state[zone_id][k] = v

    # ── Light control ────────────────────────────────────────────────────────

    async def lights_on(self, zone_id: str):
        self.state.setdefault(zone_id, {})["light"] = "on"
        await self._send_command(zone_id, "light", "on")
        await self._log(zone_id, "light", "on", "system")

    async def lights_off(self, zone_id: str):
        self.state.setdefault(zone_id, {})["light"] = "off"
        await self._send_command(zone_id, "light", "off")
        await self._log(zone_id, "light", "off", "session_expire")

    async def lights_flash(self, zone_id: str):
        self.state.setdefault(zone_id, {})["light"] = "flash"
        await self._send_command(zone_id, "light", "flash")
        await self._log(zone_id, "light", "flash", "session_warning")

    # ── Equipment control ───────────────────────────────────────────────────

    async def equipment_deploy(self, zone_id: str):
        """Deploy all equipment in the zone (hoop down, net up, table set)."""
        self.state.setdefault(zone_id, {})
        mapping = {"hoop": "deployed", "net": "setup", "table": "setup"}
        for eq, rest in mapping.items():
            self.state[zone_id][eq] = rest
            await self._send_command(zone_id, eq, "deploy")
            await self._log(zone_id, eq, "deploy", "new_session")

    async def equipment_retract(self, zone_id: str):
        """Retract / fold all equipment in the zone."""
        self.state.setdefault(zone_id, {})
        mapping = {"hoop": "retracted", "net": "removed", "table": "fold"}
        for eq, rest in mapping.items():
            self.state[zone_id][eq] = rest
            await self._send_command(zone_id, eq, "retract")
            await self._log(zone_id, eq, "retract", "session_expire")

    # Individual hoop / net / table commands — so every device is controllable.
    async def hoop_deploy(self, zone_id: str):
        self.state.setdefault(zone_id, {})["hoop"] = "deployed"
        await self._send_command(zone_id, "hoop", "deploy")
        await self._log(zone_id, "hoop", "deploy", "manual")

    async def hoop_retract(self, zone_id: str):
        self.state.setdefault(zone_id, {})["hoop"] = "retracted"
        await self._send_command(zone_id, "hoop", "retract")
        await self._log(zone_id, "hoop", "retract", "manual")

    async def net_setup(self, zone_id: str):
        self.state.setdefault(zone_id, {})["net"] = "setup"
        await self._send_command(zone_id, "net", "setup")
        await self._log(zone_id, "net", "setup", "manual")

    async def net_remove(self, zone_id: str):
        self.state.setdefault(zone_id, {})["net"] = "removed"
        await self._send_command(zone_id, "net", "remove")
        await self._log(zone_id, "net", "remove", "manual")

    async def table_setup(self, zone_id: str):
        self.state.setdefault(zone_id, {})["table"] = "setup"
        await self._send_command(zone_id, "table", "setup")
        await self._log(zone_id, "table", "setup", "manual")

    async def table_fold(self, zone_id: str):
        self.state.setdefault(zone_id, {})["table"] = "fold"
        await self._send_command(zone_id, "table", "fold")
        await self._log(zone_id, "table", "fold", "manual")

    # ── Gate control ────────────────────────────────────────────────────────

    async def gate_open(self, zone_id: str):
        self.state.setdefault(zone_id, {})["gate"] = "open"
        await self._send_command(zone_id, "gate", "open")

    async def gate_lock(self, zone_id: str):
        self.state.setdefault(zone_id, {})["gate"] = "locked"
        await self._send_command(zone_id, "gate", "lock")

    # ── Zone lifecycle shortcuts ────────────────────────────────────────────

    async def zone_reset(self, zone_id: str):
        await self.lights_on(zone_id)
        await self.equipment_deploy(zone_id)
        await self.gate_open(zone_id)
        await self._broadcast_state()

    async def zone_shutdown(self, zone_id: str):
        await self.lights_off(zone_id)
        await self.equipment_retract(zone_id)
        await self.gate_lock(zone_id)
        await self._broadcast_state()

    # ── Get state ───────────────────────────────────────────────────────────

    def get_all_states(self) -> dict:
        return self.state

    # ── Internal ────────────────────────────────────────────────────────────

    async def _send_command(self, zone_id, device, action):
        topic = f"bridgespace/{zone_id}/{device}"
        print(f"[SmartControl] {topic} → {action}")
        if self.mqtt:
            try:
                self.mqtt.publish(topic, action)
            except Exception as e:
                print(f"[SmartControl] MQTT error: {e}")
        await self._broadcast_state()

    async def _log(self, zone_id, device_type, action, triggered_by):
        try:
            conn = self.get_db()
            conn.execute(
                """INSERT INTO device_log
                   (zone_id, device_type, action, triggered_by, ts)
                   VALUES (?,?,?,?,?)""",
                (zone_id, device_type, action, triggered_by,
                 datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[SmartControl] Log error: {e}")

    async def _broadcast_state(self):
        await self.broadcast({"type": "devices", "state": self.state})
