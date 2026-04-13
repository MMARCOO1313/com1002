"""
AlertEngine — Automated notification system for BridgeSpace.
Sends Telegram messages for warnings, and can trigger phone calls
for critical situations (overstay > 10 min, emergencies).

Requires: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars.
Optional: TWILIO_SID, TWILIO_TOKEN, ADMIN_PHONE for phone calls.
"""

import os
import asyncio
import httpx
from datetime import datetime
from typing import Optional


# ─── Configuration ───────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Twilio (optional — for phone calls)
TWILIO_SID = os.environ.get("TWILIO_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM", "")
ADMIN_PHONE = os.environ.get("ADMIN_PHONE", "")

# Twilio WhatsApp (for overstay notifications)
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")  # Twilio sandbox default
ADMIN_WHATSAPP = os.environ.get("ADMIN_WHATSAPP", "whatsapp:+85251009606")


class AlertEngine:
    def __init__(self, get_db, broadcast):
        self.get_db = get_db
        self.broadcast = broadcast
        self._overstay_notified = set()  # track (session_zone) to avoid spam

    # ── Telegram ─────────────────────────────────────────────────────────────

    async def send_telegram(self, message: str, severity: str = "info"):
        prefix = {"info": "[INFO]", "warning": "[WARN]", "critical": "[CRIT]"}.get(severity, "[INFO]")
        full_msg = f"{prefix} BridgeSpace Alert\n\n{message}\n\nTime: {datetime.now().strftime('%H:%M:%S')}"

        print(f"[AlertEngine] Telegram ({severity}): {message}")

        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            print("[AlertEngine] Telegram not configured — skipping")
            await self._log_alert(None, "telegram_skip", severity, message)
            # Still broadcast to frontend
            await self.broadcast({
                "type": "alert",
                "severity": severity,
                "message": message,
                "time": datetime.now().isoformat(),
            })
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": full_msg,
                    "parse_mode": "HTML",
                })
                if resp.status_code != 200:
                    print(f"[AlertEngine] Telegram API error: {resp.text}")
        except Exception as e:
            print(f"[AlertEngine] Telegram send failed: {e}")

        # Also broadcast alert to frontend dashboard
        await self.broadcast({
            "type": "alert",
            "severity": severity,
            "message": message,
            "time": datetime.now().isoformat(),
        })

    # ── WhatsApp (Twilio) ─────────────────────────────────────────────────

    async def send_whatsapp(self, message: str, severity: str = "warning"):
        prefix = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(severity, "ℹ️")
        full_msg = (
            f"{prefix} *BridgeSpace Alert*\n\n"
            f"{message}\n\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        print(f"[AlertEngine] WhatsApp ({severity}): {message}")

        if not all([TWILIO_SID, TWILIO_TOKEN, ADMIN_WHATSAPP]):
            print("[AlertEngine] Twilio WhatsApp not configured — simulating")
            await self.broadcast({
                "type": "alert",
                "severity": severity,
                "message": f"[WhatsApp SIMULATED] {message}",
                "time": datetime.now().isoformat(),
            })
            await self._log_alert(None, "whatsapp_skip", severity, f"[simulated] {message}")
            return {"ok": True, "simulated": True, "message": "WhatsApp 未配置 — 已模擬發送"}

        url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, auth=(TWILIO_SID, TWILIO_TOKEN), data={
                    "From": TWILIO_WHATSAPP_FROM,
                    "To": ADMIN_WHATSAPP,
                    "Body": full_msg,
                })
                resp_data = resp.json()
                if resp.status_code in (200, 201):
                    print(f"[AlertEngine] WhatsApp sent: SID={resp_data.get('sid','?')}")
                else:
                    print(f"[AlertEngine] WhatsApp API error: {resp.text}")
                    return {"ok": False, "message": f"Twilio error: {resp_data.get('message', resp.text)}"}
        except Exception as e:
            print(f"[AlertEngine] WhatsApp send failed: {e}")
            return {"ok": False, "message": str(e)}

        # Also broadcast alert to frontend dashboard
        await self.broadcast({
            "type": "alert",
            "severity": severity,
            "message": f"[WhatsApp已發送] {message}",
            "time": datetime.now().isoformat(),
        })
        await self._log_alert(None, "whatsapp", severity, message)
        return {"ok": True, "simulated": False, "message": "WhatsApp 訊息已成功發送"}

    # ── Phone call (Twilio) ──────────────────────────────────────────────────

    async def make_phone_call(self, message: str):
        print(f"[AlertEngine] PHONE CALL: {message}")

        if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, ADMIN_PHONE]):
            print("[AlertEngine] Twilio not configured — skipping phone call")
            await self.send_telegram(
                f"[PHONE CALL SIMULATED]\n{message}", "critical")
            return

        url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Calls.json"
        twiml = f'<Response><Say language="zh-HK">{message}</Say></Response>'
        try:
            async with httpx.AsyncClient() as client:
                await client.post(url, auth=(TWILIO_SID, TWILIO_TOKEN), data={
                    "To": ADMIN_PHONE,
                    "From": TWILIO_FROM,
                    "Twiml": twiml,
                })
        except Exception as e:
            print(f"[AlertEngine] Phone call failed: {e}")

    # ── Specific alert types ─────────────────────────────────────────────────

    async def alert_overstay(self, zone_id: str, user_name: str, minutes: int):
        key = f"{zone_id}_{minutes//5}"  # dedupe per 5-min window
        if key in self._overstay_notified:
            return
        self._overstay_notified.add(key)

        msg = (f"Zone {zone_id} - user {user_name} has overstayed by {minutes} minute(s).\n"
               f"Lights have been turned off and equipment has been retracted.")

        await self.send_telegram(
            msg.replace(user_name, f"<b>{user_name}</b>"),
            "warning"
        )
        # Also send WhatsApp to admin
        await self.send_whatsapp(
            f"Zone {zone_id} 超時警告\n"
            f"用戶：{user_name}\n"
            f"超時：{minutes} 分鐘\n"
            f"燈光已關閉，器材已收起。請跟進。",
            "warning"
        )
        await self._log_alert(zone_id, "overstay", "warning",
                              f"{user_name} overstay {minutes}min")

    async def alert_overstay_critical(self, zone_id: str, minutes: int):
        key = f"{zone_id}_phone"
        if key in self._overstay_notified:
            return
        self._overstay_notified.add(key)
        await self.make_phone_call(
            f"BridgeSpace emergency notification. Zone {zone_id} user has overstayed by {minutes} minutes. Please investigate immediately.")
        await self._log_alert(zone_id, "overstay", "critical",
                              f"Phone call triggered: {minutes}min overstay")

    async def alert_overcapacity(self, zone_id: str, count: int, capacity: int):
        await self.send_telegram(
            f"Zone {zone_id} is over capacity.\n"
            f"Detected <b>{count}</b> people while the limit is {capacity}.",
            "critical"
        )
        await self._log_alert(zone_id, "overcapacity", "critical",
                              f"{count}/{capacity}")

    async def alert_device_fault(self, zone_id: str, device: str, error: str):
        await self.send_telegram(
            f"Zone {zone_id} device fault detected.\n"
            f"Device: {device}\nError: {error}",
            "critical"
        )
        await self._log_alert(zone_id, "device_fault", "critical",
                              f"{device}: {error}")

    # ── Log to database ──────────────────────────────────────────────────────

    async def _log_alert(self, zone_id, alert_type, severity, message):
        try:
            conn = self.get_db()
            conn.execute(
                """INSERT INTO alerts
                   (zone_id, alert_type, severity, message, ts)
                   VALUES (?,?,?,?,?)""",
                (zone_id, alert_type, severity, message,
                 datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[AlertEngine] DB log error: {e}")
