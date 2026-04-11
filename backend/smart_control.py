"""
SmartControl — IoT device controller for BridgeSpace zones.
Controls lighting (on/off/flash), equipment (basketball hoops retract/deploy),
and gate access per zone.

In production: sends MQTT commands to Raspberry Pi actuators.
In demo/exhibition: logs actions + broadcasts state to frontend for visual simulation.
"""

import asyncio
import json
from datetime import datetime
from typing import Optional


# Zone equipment configuration
ZONE_DEVICES = {
    "A": {"light": True, "hoop": True,  "gate": True},   # Basketball has hoops
    "B": {"light": True, "hoop": False, "gate": True},
    "C": {"light": True, "hoop": False, "gate": True},
    "D": {"light": True, "hoop": True,  "gate": True},   # Emerging sports
}


class SmartControl:
    """Controls physical devices in each zone."""

    def __init__(self, get_db, broadcast, mqtt_client=None):
        self.get_db = get_db
        self.broadcast = broadcast
        self.mqtt = mqtt_client  # None = simulation mode
        self.state = {}  # zone_id → {light: str, hoop: str, gate: str}
        self._init_state()

    def _init_state(self):
        for zone_id, devices in ZONE_DEVICES.items():
            self.state[zone_id] = {
                "light": "off",
                "hoop": "deployed" if devices.get("hoop") else "n/a",
                "gate": "locked",
            }

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
        """Flash lights as warning — 5 min before session expiry."""
        self.state.setdefault(zone_id, {})["light"] = "flash"
        await self._send_command(zone_id, "light", "flash")
        await self._log(zone_id, "light", "flash", "session_warning")

    # ── Equipment control ───────────────────────────────────────────────────

    async def equipment_retract(self, zone_id: str):
        """Retract basketball hoops / stow equipment when session expires."""
        devices = ZONE_DEVICES.get(zone_id, {})
        if not devices.get("hoop"):
            return
        self.state.setdefault(zone_id, {})["hoop"] = "retracted"
        await self._send_command(zone_id, "hoop", "retract")
        await self._log(zone_id, "hoop", "retract", "session_expire")

    async def equipment_deploy(self, zone_id: str):
        """Deploy equipment for new session."""
        devices = ZONE_DEVICES.get(zone_id, {})
        if not devices.get("hoop"):
            return
        self.state.setdefault(zone_id, {})["hoop"] = "deployed"
        await self._send_command(zone_id, "hoop", "deploy")
        await self._log(zone_id, "hoop", "deploy", "new_session")

    # ── Gate control ────────────────────────────────────────────────────────

    async def gate_open(self, zone_id: str):
        self.state.setdefault(zone_id, {})["gate"] = "open"
        await self._send_command(zone_id, "gate", "open")

    async def gate_lock(self, zone_id: str):
        self.state.setdefault(zone_id, {})["gate"] = "locked"
        await self._send_command(zone_id, "gate", "lock")

    # ── Zone lifecycle shortcuts ────────────────────────────────────────────

    async def zone_reset(self, zone_id: str):
        """Full reset: lights on, equipment ready, gate open."""
        await self.lights_on(zone_id)
        await self.equipment_deploy(zone_id)
        await self.gate_open(zone_id)
        await self._broadcast_state()

    async def zone_shutdown(self, zone_id: str):
        """Shutdown: lights off, equipment stow, gate lock."""
        await self.lights_off(zone_id)
        await self.equipment_retract(zone_id)
        await self.gate_lock(zone_id)
        await self._broadcast_state()

    # ── Get state ───────────────────────────────────────────────────────────

    def get_all_states(self) -> dict:
        return self.state

    # ── Internal ────────────────────────────────────────────────────────────

    async def _send_command(self, zone_id: str, device: str, action: str):
        """Send command to physical device via MQTT or simulate."""
        topic = f"bridgespace/{zone_id}/{device}"
        print(f"[SmartControl] {topic} → {action}")
        if self.mqtt:
            try:
                self.mqtt.publish(topic, action)
            except Exception as e:
                print(f"[SmartControl] MQTT error: {e}")
        # Always broadcast to frontend for visual simulation
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
        await self.broadcast({
            "type": "devices",
            "state": self.state,
        })
