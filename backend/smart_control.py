"""
SmartControl — Dynamic IoT device controller for BridgeSpace zones.

Devices are determined by each zone's current sport allocation:
  - All zones:  light (on/off/flash), gate (open/lock)
  - 籃球:       hoop  (deploy/retract)
  - 羽毛球/匹克球/排球: net (setup/remove)
  - 乒乓球:     table (setup/fold)

In production: sends MQTT commands to Raspberry Pi actuators.
In demo/exhibition: logs actions + broadcasts state to frontend.
"""

import asyncio
import json
from datetime import datetime
from typing import Optional

from zone_catalog import DEFAULT_ZONES, SPORT_CONFIG


# Equipment types mapped from sport config
EQUIPMENT_LABELS = {
    "hoop":  {"zh": "籃框",  "deploy": "部署", "retract": "收起"},
    "net":   {"zh": "球網",  "setup": "架設",  "remove": "收起"},
    "table": {"zh": "球台",  "setup": "擺設",  "fold": "收起"},
}


class SmartControl:
    """Controls physical devices in each zone — dynamic per allocation."""

    def __init__(self, get_db, broadcast, mqtt_client=None):
        self.get_db = get_db
        self.broadcast = broadcast
        self.mqtt = mqtt_client
        self.state = {}
        self._init_state()

    def _init_state(self):
        for zone in DEFAULT_ZONES:
            zid = zone["id"]
            self.state[zid] = {
                "light": "off",
                "gate": "locked",
                "hoop": "n/a",
                "net": "n/a",
                "table": "n/a",
            }
            # Set equipment from default allocation
            for alloc_item in zone.get("default_alloc", []):
                sport = alloc_item["sport"]
                cfg = SPORT_CONFIG.get(sport, {})
                for equip in cfg.get("equipment", []):
                    self.state[zid][equip] = "retracted" if equip == "hoop" else "removed"

    def update_zone_equipment(self, zone_id: str, allocation: list):
        """Reconfigure equipment when zone allocation changes."""
        if zone_id not in self.state:
            self.state[zone_id] = {"light": "off", "gate": "locked"}
        # Reset all equipment to n/a
        for eq in ("hoop", "net", "table"):
            self.state[zone_id][eq] = "n/a"
        # Enable equipment for allocated sports
        for alloc_item in allocation:
            sport = alloc_item.get("sport", "")
            count = alloc_item.get("count", 0)
            if count <= 0:
                continue
            cfg = SPORT_CONFIG.get(sport, {})
            for equip in cfg.get("equipment", []):
                if equip == "hoop":
                    self.state[zone_id][equip] = "retracted"
                else:
                    self.state[zone_id][equip] = "removed"

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
        """Deploy all equipment in the zone."""
        st = self.state.get(zone_id, {})
        for eq in ("hoop", "net", "table"):
            if st.get(eq) not in ("n/a", None):
                st[eq] = "deployed" if eq == "hoop" else "setup"
                await self._send_command(zone_id, eq, "deploy")
                await self._log(zone_id, eq, "deploy", "new_session")

    async def equipment_retract(self, zone_id: str):
        """Retract/fold all equipment in the zone."""
        st = self.state.get(zone_id, {})
        for eq in ("hoop", "net", "table"):
            if st.get(eq) not in ("n/a", None):
                st[eq] = "retracted" if eq == "hoop" else "removed"
                await self._send_command(zone_id, eq, "retract")
                await self._log(zone_id, eq, "retract", "session_expire")

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
