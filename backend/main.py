"""
BridgeSpace Backend API - v2.1 Multi-Sport Edition
FastAPI server with fully unmanned operation:
  - SessionManager: tracks per-user time, expiry, warnings
  - AutoQueue: SmartCount-driven automatic queue advancement
  - SmartControl: IoT device management (lights, hoops, gates)
  - AlertEngine: Telegram + phone alerts for anomalies

v2.1: Each zone is multi-functional. Sport mode can be switched,
      which changes the number of courts and session duration.
"""

import os
from pathlib import Path

# Load .env file if present (before any module imports that read env vars)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3, json, asyncio, uuid, hashlib, base64, io, pickle
from datetime import datetime
from contextlib import asynccontextmanager

import cv2
import numpy as np

# --- Import autonomous modules -----------------------------------------------

from session_manager import SessionManager
from auto_queue import OccupancyWatcher
from smart_control import SmartControl
from alert_engine import AlertEngine
from zone_catalog import (
    normalize_zone_catalog, SPORT_CONFIG, ZONE_TOTAL_UNITS, UNIT_AREA_SQM,
    validate_allocation, alloc_to_courts, alloc_units_used, alloc_equipment_set,
    ALLOC_PRESETS, DEFAULT_ZONES,
)

# --- Database ----------------------------------------------------------------

DB_PATH = Path(__file__).parent / "bridgespace.db"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id        TEXT PRIMARY KEY,
            name      TEXT NOT NULL,
            phone     TEXT NOT NULL,
            face_id   TEXT UNIQUE,
            created   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS zones (
            id              TEXT PRIMARY KEY,
            name_zh         TEXT NOT NULL,
            name_en         TEXT NOT NULL,
            zone_type       TEXT DEFAULT 'multi',
            current_sport   TEXT DEFAULT '',
            capacity        INTEGER NOT NULL,
            courts          INTEGER DEFAULT 1,
            current_count   INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'open',
            session_duration INTEGER DEFAULT 2700,
            allocation      TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS queue (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            zone_id     TEXT NOT NULL,
            queue_num   INTEGER NOT NULL,
            status      TEXT DEFAULT 'waiting',
            joined_at   TEXT NOT NULL,
            called_at   TEXT,
            entered_at  TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (zone_id) REFERENCES zones(id)
        );

        CREATE TABLE IF NOT EXISTS occupancy_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id   TEXT NOT NULL,
            count     INTEGER NOT NULL,
            ts        TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            zone_id     TEXT NOT NULL,
            court_num   INTEGER DEFAULT 1,
            queue_id    TEXT,
            started_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            extended    INTEGER DEFAULT 0,
            ended_at    TEXT,
            status      TEXT DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS device_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id       TEXT NOT NULL,
            device_type   TEXT NOT NULL,
            action        TEXT NOT NULL,
            triggered_by  TEXT NOT NULL,
            ts            TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id      TEXT,
            alert_type   TEXT NOT NULL,
            severity     TEXT NOT NULL,
            message      TEXT NOT NULL,
            notified_via TEXT,
            resolved     INTEGER DEFAULT 0,
            ts           TEXT NOT NULL
        );
    """)

    # Schema migration for existing databases
    for stmt in [
        "ALTER TABLE zones ADD COLUMN zone_type TEXT DEFAULT 'multi'",
        "ALTER TABLE zones ADD COLUMN current_sport TEXT DEFAULT ''",
        "ALTER TABLE zones ADD COLUMN courts INTEGER DEFAULT 1",
        "ALTER TABLE sessions ADD COLUMN court_num INTEGER DEFAULT 1",
        "ALTER TABLE zones ADD COLUMN allocation TEXT DEFAULT '[]'",
    ]:
        try:
            conn.execute(stmt)
        except Exception:
            pass

    normalize_zone_catalog(conn)
    conn.commit()
    conn.close()


init_db()

# --- WebSocket manager -------------------------------------------------------


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(json.dumps(data, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self.active:
                self.active.remove(ws)


manager = ConnectionManager()

# --- Initialize autonomous modules -------------------------------------------

alert_engine = AlertEngine(get_db, manager.broadcast)
smart_control = SmartControl(get_db, manager.broadcast)
session_mgr = SessionManager(get_db, manager.broadcast, smart_control, alert_engine)
occ_watcher = OccupancyWatcher(get_db, manager.broadcast, session_mgr, smart_control, alert_engine)

# --- Background tasks --------------------------------------------------------


async def autonomous_loop():
    """Main autonomous loop - runs every 10 seconds."""
    await asyncio.sleep(3)
    print("[Autonomous] Background loop started")
    while True:
        try:
            await session_mgr.check_expiry()
            await session_mgr.check_noshows()
        except Exception as e:
            print(f"[Autonomous] Loop error: {e}")
        await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(autonomous_loop())
    yield
    task.cancel()


# --- FastAPI app -------------------------------------------------------------

app = FastAPI(title="BridgeSpace API", version="2.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Models ------------------------------------------------------------------


class RegisterUser(BaseModel):
    name: str
    phone: str
    face_id: Optional[str] = None


class JoinQueue(BaseModel):
    user_id: str
    zone_id: str


class OccupancyUpdate(BaseModel):
    zone_id: str
    count: int


class EnterZone(BaseModel):
    face_id: str
    zone_id: str
    queue_id: Optional[str] = None


class ExtendSession(BaseModel):
    session_id: str


class SwitchSport(BaseModel):
    sport: str


# --- Users -------------------------------------------------------------------

@app.post("/users/register")
def register_user(data: RegisterUser):
    conn = get_db()
    user_id = str(uuid.uuid4())[:8].upper()
    try:
        conn.execute(
            "INSERT INTO users (id, name, phone, face_id, created) VALUES (?,?,?,?,?)",
            (user_id, data.name, data.phone, data.face_id, datetime.now().isoformat()),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(400, "Face already registered")
    conn.close()
    return {"user_id": user_id, "message": "User registered successfully"}


@app.get("/users/by-face/{face_id}")
def get_user_by_face(face_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE face_id=?", (face_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Face not found")
    return dict(row)


# --- Zones & Occupancy -------------------------------------------------------

@app.get("/zones")
def get_zones():
    conn = get_db()
    rows = conn.execute("SELECT * FROM zones").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        # Parse allocation JSON
        try:
            d["allocation"] = json.loads(d.get("allocation") or "[]")
        except Exception:
            d["allocation"] = []
        result.append(d)
    return result


@app.post("/zones/occupancy")
async def update_occupancy(data: OccupancyUpdate):
    """Called by SmartCount every second - triggers autonomous loop."""
    conn = get_db()
    zone = conn.execute("SELECT * FROM zones WHERE id=?", (data.zone_id,)).fetchone()
    if not zone:
        conn.close()
        raise HTTPException(404, "Zone not found")

    status = "open"
    if data.count >= zone["capacity"]:
        status = "full"
    elif data.count >= zone["capacity"] * 0.85:
        status = "busy"

    conn.execute(
        "UPDATE zones SET current_count=?, status=? WHERE id=?",
        (data.count, status, data.zone_id),
    )
    conn.execute(
        "INSERT INTO occupancy_log (zone_id, count, ts) VALUES (?,?,?)",
        (data.zone_id, data.count, datetime.now().isoformat()),
    )
    conn.commit()

    all_zones = [dict(r) for r in conn.execute("SELECT * FROM zones").fetchall()]
    conn.close()
    await manager.broadcast({"type": "occupancy", "zones": all_zones})

    # Trigger OccupancyWatcher - autonomous departure detection + auto-queue
    await occ_watcher.on_occupancy_update(data.zone_id, data.count)

    return {"status": status, "count": data.count}


# --- Sport switching ---------------------------------------------------------

@app.post("/zones/{zone_id}/switch-sport")
async def switch_sport(zone_id: str, data: SwitchSport):
    """Switch the active sport mode for a zone. Changes court count & duration."""
    conn = get_db()
    zone = conn.execute("SELECT * FROM zones WHERE id=?", (zone_id,)).fetchone()
    if not zone:
        conn.close()
        raise HTTPException(404, "Zone not found")

    zone_type = zone["zone_type"]
    config = SPORT_CONFIG.get(zone_type)
    if not config:
        conn.close()
        raise HTTPException(400, f"Unknown zone type: {zone_type}")

    sport_info = config.get(data.sport)
    if not sport_info:
        available = ", ".join(config.keys())
        conn.close()
        raise HTTPException(400, f"'{data.sport}' not available. Options: {available}")

    # Check no active sessions or in-progress queue entries
    active = conn.execute(
        "SELECT COUNT(*) as c FROM sessions WHERE zone_id=? AND status IN ('active','warning','expired','overstay')",
        (zone_id,),
    ).fetchone()["c"]
    in_queue = conn.execute(
        "SELECT COUNT(*) as c FROM queue WHERE zone_id=? AND status IN ('waiting','called','entered')",
        (zone_id,),
    ).fetchone()["c"]
    if active > 0 or in_queue > 0:
        conn.close()
        raise HTTPException(400, f"Cannot switch sport: {active} active session(s), {in_queue} queue entries. Wait for all to finish.")

    conn.execute(
        "UPDATE zones SET current_sport=?, courts=?, session_duration=? WHERE id=?",
        (data.sport, sport_info["courts"], sport_info["duration"], zone_id),
    )
    conn.commit()

    all_zones = [dict(r) for r in conn.execute("SELECT * FROM zones").fetchall()]
    conn.close()
    await manager.broadcast({"type": "occupancy", "zones": all_zones})

    return {"ok": True, "sport": data.sport, "courts": sport_info["courts"], "duration": sport_info["duration"]}


# --- Zone allocation (unit-based) --------------------------------------------

class AllocateRequest(BaseModel):
    allocation: list  # [{"sport": "乒乓球", "count": 2}, {"sport": "羽毛球", "count": 1}]

@app.post("/zones/{zone_id}/allocate")
async def allocate_zone(zone_id: str, data: AllocateRequest):
    """Set a zone's sport allocation (mixed sports OK, max 4 units)."""
    ok, msg = validate_allocation(data.allocation)
    if not ok:
        raise HTTPException(400, msg)

    conn = get_db()
    zone = conn.execute("SELECT * FROM zones WHERE id=?", (zone_id,)).fetchone()
    if not zone:
        conn.close()
        raise HTTPException(404, "Zone not found")

    # Block if active sessions or queue
    active = conn.execute(
        "SELECT COUNT(*) as c FROM sessions WHERE zone_id=? AND status IN ('active','warning','expired','overstay')",
        (zone_id,),
    ).fetchone()["c"]
    in_queue = conn.execute(
        "SELECT COUNT(*) as c FROM queue WHERE zone_id=? AND status IN ('waiting','called','entered')",
        (zone_id,),
    ).fetchone()["c"]
    if active > 0 or in_queue > 0:
        conn.close()
        raise HTTPException(400, f"有 {active} 個活躍場次和 {in_queue} 個排隊中，無法更改配置")

    courts = alloc_to_courts(data.allocation)
    first_sport = data.allocation[0]["sport"] if data.allocation else ""
    duration = SPORT_CONFIG[first_sport]["duration"] if first_sport else 2700
    alloc_json = json.dumps(data.allocation, ensure_ascii=False)

    conn.execute(
        "UPDATE zones SET allocation=?, courts=?, current_sport=?, session_duration=? WHERE id=?",
        (alloc_json, courts, first_sport, duration, zone_id),
    )
    conn.commit()

    # Update SmartControl equipment
    smart_control.update_zone_equipment(zone_id, data.allocation)

    all_zones = [dict(r) for r in conn.execute("SELECT * FROM zones").fetchall()]
    conn.close()
    await manager.broadcast({"type": "occupancy", "zones": all_zones})

    return {"ok": True, "allocation": data.allocation, "courts": courts, "units_used": alloc_units_used(data.allocation)}

@app.get("/zone-config")
def get_zone_config():
    """Return sport config, unit costs, presets for frontend."""
    return {
        "total_units": ZONE_TOTAL_UNITS,
        "unit_area_sqm": UNIT_AREA_SQM,
        "sports": SPORT_CONFIG,
        "presets": ALLOC_PRESETS,
        "zone_count": len(DEFAULT_ZONES),
        "total_area_sqm": len(DEFAULT_ZONES) * ZONE_TOTAL_UNITS * UNIT_AREA_SQM,
        "total_area_with_circulation": round(len(DEFAULT_ZONES) * ZONE_TOTAL_UNITS * UNIT_AREA_SQM * 1.3),
    }


# --- Queue -------------------------------------------------------------------

@app.post("/queue/join")
async def join_queue(data: JoinQueue):
    # Enforce booking rules up-front: no double-booking / quota
    ok, msg, _ = session_mgr.check_booking_quota(data.user_id)
    if not ok:
        raise HTTPException(400, msg)

    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM queue WHERE user_id=? AND zone_id=? AND status IN ('waiting','called')",
        (data.user_id, data.zone_id),
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(400, "User is already waiting or has already been called for this zone")

    # Check walk-in: if any court is free and no queue, allow direct entry
    zone = conn.execute("SELECT * FROM zones WHERE id=?", (data.zone_id,)).fetchone()
    waiting_count = conn.execute(
        "SELECT COUNT(*) as c FROM queue WHERE zone_id=? AND status='waiting'",
        (data.zone_id,),
    ).fetchone()["c"]

    active_sessions = conn.execute(
        "SELECT COUNT(*) as c FROM sessions WHERE zone_id=? AND status IN ('active','warning','expired','overstay')",
        (data.zone_id,),
    ).fetchone()["c"]
    total_courts = zone["courts"] if zone else 1

    if zone and waiting_count == 0 and active_sessions < total_courts:
        conn.close()
        return {
            "walk_in": True,
            "message": f"有空閒球場，可直接入場。({total_courts - active_sessions}/{total_courts} 場空閒)",
            "queue_num": 0,
        }

    last = conn.execute(
        "SELECT MAX(queue_num) as m FROM queue WHERE zone_id=?",
        (data.zone_id,),
    ).fetchone()
    next_num = (last["m"] or 0) + 1

    entry_id = str(uuid.uuid4())[:8].upper()
    conn.execute(
        "INSERT INTO queue (id, user_id, zone_id, queue_num, joined_at) VALUES (?,?,?,?,?)",
        (entry_id, data.user_id, data.zone_id, next_num, datetime.now().isoformat()),
    )
    conn.commit()

    queue_data = _get_queue_snapshot(conn)
    conn.close()
    await manager.broadcast({"type": "queue", "data": queue_data})

    return {"queue_id": entry_id, "queue_num": next_num, "message": f"Queue number assigned: {next_num}"}


@app.post("/queue/call-next/{zone_id}")
async def call_next(zone_id: str):
    """Manual fallback - staff can still call next if needed."""
    conn = get_db()
    next_person = conn.execute(
        "SELECT * FROM queue WHERE zone_id=? AND status='waiting' ORDER BY queue_num ASC LIMIT 1",
        (zone_id,),
    ).fetchone()
    if not next_person:
        conn.close()
        return {"message": "No one is waiting in this zone"}
    conn.execute(
        "UPDATE queue SET status='called', called_at=? WHERE id=?",
        (datetime.now().isoformat(), next_person["id"]),
    )
    conn.commit()

    user = conn.execute("SELECT * FROM users WHERE id=?", (next_person["user_id"],)).fetchone()
    queue_data = _get_queue_snapshot(conn)
    conn.close()
    await manager.broadcast(
        {
            "type": "called",
            "zone_id": zone_id,
            "queue_num": next_person["queue_num"],
            "user_name": user["name"] if user else "Guest",
            "queue": queue_data,
            "auto": False,
        }
    )
    return {"called": next_person["queue_num"]}


@app.get("/queue/{zone_id}")
def get_queue(zone_id: str):
    conn = get_db()
    rows = conn.execute(
        """SELECT q.*, u.name FROM queue q
           LEFT JOIN users u ON q.user_id = u.id
           WHERE q.zone_id=? AND q.status IN ('waiting','called')
           ORDER BY q.queue_num ASC""",
        (zone_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Sessions ----------------------------------------------------------------

@app.post("/session/enter")
async def enter_zone(data: EnterZone):
    """User scans face at zone entrance - starts a timed session."""
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE face_id=?", (data.face_id,)).fetchone()
    if not user:
        conn.close()
        raise HTTPException(404, "Face is not registered")

    # Find their called queue entry
    queue_entry = conn.execute(
        """SELECT * FROM queue
           WHERE user_id=? AND zone_id=? AND status='called'
           ORDER BY called_at DESC LIMIT 1""",
        (user["id"], data.zone_id),
    ).fetchone()
    conn.close()

    queue_id = queue_entry["id"] if queue_entry else data.queue_id
    result = await session_mgr.start_session(user["id"], data.zone_id, queue_id)
    if not result.get("ok", True):
        raise HTTPException(400, result.get("message", "無法開始場次"))
    return result


@app.post("/session/extend")
async def extend_session(data: ExtendSession):
    """User requests more time at the kiosk."""
    result = await session_mgr.extend_session(data.session_id)
    if not result["ok"]:
        raise HTTPException(400, result["message"])
    return result


@app.get("/sessions/active")
async def get_active_sessions():
    """Get all active sessions with countdown info."""
    sessions = await session_mgr.get_active_sessions()
    now = datetime.now()
    for s in sessions:
        expires = datetime.fromisoformat(s["expires_at"])
        s["remaining_seconds"] = max(0, int((expires - now).total_seconds()))
    return sessions


# --- Device status -----------------------------------------------------------

@app.get("/devices")
def get_device_states():
    return smart_control.get_all_states()


class DeviceCommand(BaseModel):
    action: str


@app.post("/devices/{zone_id}/{device}/command")
async def device_command(zone_id: str, device: str, cmd: DeviceCommand):
    """Send a command to a specific device in a zone."""
    action = cmd.action
    try:
        if device == "light":
            if action == "on":
                await smart_control.lights_on(zone_id)
            elif action == "off":
                await smart_control.lights_off(zone_id)
            elif action == "flash":
                await smart_control.lights_flash(zone_id)
            else:
                raise HTTPException(400, f"Unknown light action: {action}")
        elif device == "hoop":
            if action == "deploy":
                await smart_control.hoop_deploy(zone_id)
            elif action == "retract":
                await smart_control.hoop_retract(zone_id)
            else:
                raise HTTPException(400, f"Unknown hoop action: {action}")
        elif device == "net":
            if action == "setup":
                await smart_control.net_setup(zone_id)
            elif action == "remove":
                await smart_control.net_remove(zone_id)
            else:
                raise HTTPException(400, f"Unknown net action: {action}")
        elif device == "table":
            if action == "setup":
                await smart_control.table_setup(zone_id)
            elif action == "fold":
                await smart_control.table_fold(zone_id)
            else:
                raise HTTPException(400, f"Unknown table action: {action}")
        elif device == "gate":
            if action == "open":
                await smart_control.gate_open(zone_id)
            elif action == "lock":
                await smart_control.gate_lock(zone_id)
            else:
                raise HTTPException(400, f"Unknown gate action: {action}")
        else:
            raise HTTPException(400, f"Unknown device: {device}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "zone_id": zone_id, "device": device, "action": action}


# --- Demo endpoints (exhibition only) ----------------------------------------

class DemoBookRequest(BaseModel):
    zone_id: str
    court_num: int = 0  # 0 = auto-assign

@app.post("/demo/book")
async def demo_book_court(data: DemoBookRequest):
    """DEMO: Instantly book a court without queue flow."""
    conn = get_db()
    zone = conn.execute("SELECT * FROM zones WHERE id=?", (data.zone_id,)).fetchone()
    if not zone:
        conn.close()
        raise HTTPException(404, "Zone not found")

    total_courts = zone["courts"] or 1
    active = conn.execute(
        "SELECT court_num FROM sessions WHERE zone_id=? AND status IN ('active','warning','expired','overstay')",
        (data.zone_id,),
    ).fetchall()
    occupied = {r["court_num"] for r in active}

    if data.court_num > 0:
        if data.court_num in occupied:
            conn.close()
            raise HTTPException(400, f"Court {data.court_num} already occupied")
        court = data.court_num
    else:
        court = None
        for c in range(1, total_courts + 1):
            if c not in occupied:
                court = c
                break
        if court is None:
            conn.close()
            raise HTTPException(400, "All courts occupied")

    # Create demo user + session — fresh synthetic id each call so we
    # never trip the daily quota that real users are bound by.
    demo_id = f"DEMO-{uuid.uuid4().hex[:6].upper()}"
    face_id = f"demo_{data.zone_id}_{court}_{uuid.uuid4().hex[:6]}"
    try:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, name, phone, face_id, created) VALUES (?,?,?,?,?)",
            (demo_id, f"Demo {data.zone_id}-{court}", "0000", face_id, datetime.now().isoformat()),
        )
    except Exception:
        pass

    # Demo sessions match the production 1-hour window so the UI stays consistent.
    from session_manager import SESSION_DURATION
    duration = SESSION_DURATION

    sid = str(uuid.uuid4())[:8].upper()
    now = datetime.now()
    from datetime import timedelta
    expires = now + timedelta(seconds=duration)
    conn.execute(
        "INSERT INTO sessions (id, user_id, zone_id, court_num, started_at, expires_at, status) VALUES (?,?,?,?,?,?,?)",
        (sid, demo_id, data.zone_id, court, now.isoformat(), expires.isoformat(), "active"),
    )
    conn.commit()

    conn.close()

    return {"ok": True, "session_id": sid, "court_num": court}


@app.post("/demo/unbook/{zone_id}")
async def demo_unbook_zone(zone_id: str, court_num: int = 0):
    """DEMO: Force-end session(s) in a zone. court_num=0 means all."""
    conn = get_db()
    now = datetime.now().isoformat()
    if court_num > 0:
        conn.execute(
            "UPDATE sessions SET status='ended', ended_at=? WHERE zone_id=? AND court_num=? AND status IN ('active','warning','expired','overstay')",
            (now, zone_id, court_num),
        )
    else:
        conn.execute(
            "UPDATE sessions SET status='ended', ended_at=? WHERE zone_id=? AND status IN ('active','warning','expired','overstay')",
            (now, zone_id),
        )
    # Also clear queue for the zone
    conn.execute(
        "DELETE FROM queue WHERE zone_id=? AND status IN ('waiting','called')",
        (zone_id,),
    )
    conn.commit()
    conn.close()

    return {"ok": True, "zone_id": zone_id}


@app.post("/demo/reset-all")
async def demo_reset_all():
    """DEMO: End all sessions, clear all queues, reset all devices."""
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute("UPDATE sessions SET status='ended', ended_at=? WHERE status IN ('active','warning','expired','overstay')", (now,))
    conn.execute("DELETE FROM queue WHERE status IN ('waiting','called')")
    conn.execute("UPDATE zones SET current_count=0, status='open'")
    conn.commit()
    conn.close()

    return {"ok": True, "message": "All sessions ended, queues cleared"}


# --- Alerts ------------------------------------------------------------------

class WhatsAppTest(BaseModel):
    zone_id: str
    user_name: str = "Demo User"
    minutes: int = 5


@app.post("/alerts/test-whatsapp")
async def test_whatsapp(data: WhatsAppTest):
    """Demo endpoint: trigger a WhatsApp overstay notification."""
    result = await alert_engine.send_whatsapp(
        f"[DEMO] Zone {data.zone_id} 超時警告\n"
        f"用戶：{data.user_name}\n"
        f"超時：{data.minutes} 分鐘\n"
        f"燈光已關閉，器材已收起。請即處理。",
        "warning"
    )
    return result


@app.get("/alerts")
def get_alerts(limit: int = 20):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- WebSocket ---------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    conn = get_db()
    zones = [dict(r) for r in conn.execute("SELECT * FROM zones").fetchall()]
    queue = _get_queue_snapshot(conn)
    conn.close()

    sessions = await session_mgr.get_active_sessions()
    now = datetime.now()
    for s in sessions:
        expires = datetime.fromisoformat(s["expires_at"])
        s["remaining_seconds"] = max(0, int((expires - now).total_seconds()))

    await ws.send_text(
        json.dumps(
            {
                "type": "init",
                "zones": zones,
                "queue": queue,
                "sessions": sessions,
                "devices": smart_control.get_all_states(),
            },
            default=str,
        )
    )
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


# --- Helpers -----------------------------------------------------------------


def _get_queue_snapshot(conn):
    rows = conn.execute(
        """SELECT q.zone_id, q.queue_num, q.status, u.name
           FROM queue q LEFT JOIN users u ON q.user_id=u.id
           WHERE q.status IN ('waiting','called')
           ORDER BY q.zone_id, q.queue_num"""
    ).fetchall()
    return [dict(r) for r in rows]


_MODEL_DIR = Path(__file__).parent / "models"
_MODEL_DIR.mkdir(exist_ok=True)

# --- SmartGate face recognition (YuNet + SFace) -----------------------------
#
# Uses OpenCV's built-in deep-learning face pipeline:
#   1. YuNet   — lightweight face detector (ONNX, 227 KB)
#   2. SFace   — 128-d face embedding model (ONNX, 37 MB)
#
# Each registered user's 128-d embedding is stored in face_db/encodings.pkl.
# On scan, the new embedding is compared against ALL stored embeddings using
# cosine similarity.  Threshold 0.363 (OpenCV recommended for SFace cosine).
# --------------------------------------------------------------------------

FACE_DB_DIR = Path(__file__).parent / "face_db"
FACE_DB_DIR.mkdir(exist_ok=True)
FACE_ENCODINGS_FILE = FACE_DB_DIR / "encodings.pkl"

_YUNET_PATH = str(_MODEL_DIR / "face_detection_yunet_2023mar.onnx")
_SFACE_PATH = str(_MODEL_DIR / "face_recognition_sface_2021dec.onnx")

# ── Thresholds ──────────────────────────────────────────────────────────────
# SFace L2 norm distance:  identical ≈ 0.0,  same person < 1.05,  different > 1.2
# We use L2 (more discriminative than cosine for SFace on webcam images).
_L2_MATCH_THRESHOLD = 1.05   # must be BELOW this to count as same person

# Initialise models
_face_detector = None
_face_recognizer = None

def _init_face_models():
    global _face_detector, _face_recognizer
    if Path(_YUNET_PATH).exists():
        _face_detector = cv2.FaceDetectorYN.create(
            _YUNET_PATH, "", (320, 320),
            score_threshold=0.75,   # higher = fewer false positives
            nms_threshold=0.3,
            top_k=5000,
        )
        print("[SmartGate] YuNet face detector loaded")
    else:
        print("[SmartGate] WARNING: YuNet model not found")

    if Path(_SFACE_PATH).exists():
        _face_recognizer = cv2.FaceRecognizerSF.create(_SFACE_PATH, "")
        print("[SmartGate] SFace face recognizer loaded (L2 threshold:", _L2_MATCH_THRESHOLD, ")")
    else:
        print("[SmartGate] WARNING: SFace model not found")

_init_face_models()


# ── Face DB — always read from disk to avoid stale cache ────────────────────

def _load_face_db() -> dict:
    """Load {face_id: 128-d np.ndarray} from pickle. Called on every request."""
    if FACE_ENCODINGS_FILE.exists():
        try:
            with open(FACE_ENCODINGS_FILE, "rb") as f:
                return pickle.load(f)
        except Exception:
            return {}
    return {}

def _save_face_db(db: dict):
    with open(FACE_ENCODINGS_FILE, "wb") as f:
        pickle.dump(db, f)


class FaceScanRequest(BaseModel):
    image: str

class FaceSaveRequest(BaseModel):
    face_id: str
    image: str


def _decode_image(b64: str) -> np.ndarray:
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    raw = base64.b64decode(b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _detect_face(img: np.ndarray):
    """Detect the largest face. Returns (face_row, bbox_dict) or (None, None)."""
    if _face_detector is None:
        return None, None
    h, w = img.shape[:2]
    _face_detector.setInputSize((w, h))
    _, faces = _face_detector.detect(img)
    if faces is None or len(faces) == 0:
        return None, None
    best = max(faces, key=lambda f: f[2] * f[3])
    x, y, fw, fh = int(best[0]), int(best[1]), int(best[2]), int(best[3])
    return best, {"left": x, "top": y, "right": x + fw, "bottom": y + fh}


def _get_embedding(img: np.ndarray, face_obj) -> np.ndarray:
    """Extract L2-normalised 128-d embedding via SFace."""
    if _face_recognizer is None:
        return None
    aligned = _face_recognizer.alignCrop(img, face_obj)
    embedding = _face_recognizer.feature(aligned)            # (1, 128)
    # L2-normalise so comparison is meaningful
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm
    return embedding


def _match_embedding(embedding: np.ndarray):
    """
    Compare embedding against ALL stored faces using L2 distance.
    Returns (face_id, l2_distance) or (None, best_distance).
    """
    face_db = _load_face_db()          # ← always fresh from disk
    if not face_db:
        return None, 999.0

    best_id = None
    best_dist = 999.0
    log_lines = []

    for fid, stored_emb in face_db.items():
        # Normalise stored embedding too (in case old data wasn't normalised)
        s_norm = np.linalg.norm(stored_emb)
        if s_norm > 0:
            stored_normed = stored_emb / s_norm
        else:
            stored_normed = stored_emb

        dist = float(np.linalg.norm(embedding - stored_normed))
        log_lines.append(f"    vs {fid}: L2={dist:.4f}")
        if dist < best_dist:
            best_dist = dist
            best_id = fid

    # Log all comparisons for debugging
    print(f"[SmartGate] Match results (threshold={_L2_MATCH_THRESHOLD}):")
    for line in log_lines:
        print(line)
    print(f"  → Best: {best_id} @ L2={best_dist:.4f} → {'MATCH' if best_dist < _L2_MATCH_THRESHOLD else 'NO MATCH'}")

    if best_dist < _L2_MATCH_THRESHOLD:
        return best_id, best_dist
    return None, best_dist


@app.post("/smartgate/scan")
def smartgate_scan(data: FaceScanRequest):
    """Detect face, extract 128-d embedding, match against known faces."""
    img = _decode_image(data.image)
    if img is None:
        return {"ok": False, "error": "無法解碼圖片"}

    if _face_detector is None or _face_recognizer is None:
        return {"ok": False, "error": "人臉模型未載入，請檢查 models/ 資料夾"}

    face_obj, bbox = _detect_face(img)
    if face_obj is None:
        return {"detected": False, "message": "未偵測到人臉，請正面面向鏡頭"}

    embedding = _get_embedding(img, face_obj)
    if embedding is None:
        return {"ok": False, "error": "無法提取人臉特徵"}

    matched_id, dist = _match_embedding(embedding)

    if matched_id:
        conn = get_db()
        row = conn.execute("SELECT * FROM users WHERE face_id=?", (matched_id,)).fetchone()
        conn.close()
        similarity = max(0.0, 1.0 - dist / 2.0)   # map L2 0..2 → 1..0
        return {
            "ok": True,
            "detected": True,
            "matched": row is not None,
            "face_id": matched_id,
            "face_location": bbox,
            "score": round(dist, 4),
            "message": f"識別成功 (相似度: {similarity:.0%})",
        }
    else:
        new_id = uuid.uuid4().hex[:12]
        return {
            "ok": True,
            "detected": True,
            "matched": False,
            "face_id": new_id,
            "face_location": bbox,
            "score": round(dist, 4),
            "message": "新用戶",
        }


@app.post("/smartgate/save_face")
def smartgate_save_face(data: FaceSaveRequest):
    """Save L2-normalised 128-d face embedding."""
    img = _decode_image(data.image)
    if img is None:
        return {"ok": False, "error": "無法解碼圖片"}

    if _face_detector is None or _face_recognizer is None:
        return {"ok": False, "error": "人臉模型未載入"}

    face_obj, bbox = _detect_face(img)
    if face_obj is None:
        return {"ok": False, "error": "圖片中未偵測到人臉"}

    embedding = _get_embedding(img, face_obj)
    if embedding is None:
        return {"ok": False, "error": "無法提取人臉特徵"}

    face_db = _load_face_db()          # fresh from disk
    face_db[data.face_id] = embedding
    _save_face_db(face_db)
    print(f"[SmartGate] Saved embedding for {data.face_id}, norm={float(np.linalg.norm(embedding)):.4f}, total faces={len(face_db)}")

    return {"ok": True, "face_id": data.face_id, "message": f"人臉已保存（128維特徵向量）"}


# --- SmartGate: sport-first smart matching ----------------------------------

class SportMatchRequest(BaseModel):
    user_id: str
    sport: str


def _load_zones_with_counts(conn):
    """Load zones with active-session and waiting-queue counts."""
    zones = [dict(r) for r in conn.execute("SELECT * FROM zones").fetchall()]
    for z in zones:
        try:
            z["allocation"] = json.loads(z.get("allocation") or "[]")
        except Exception:
            z["allocation"] = []
        z["_sessions"] = conn.execute(
            "SELECT COUNT(*) as c FROM sessions WHERE zone_id=? "
            "AND status IN ('active','warning','expired','overstay')",
            (z["id"],),
        ).fetchone()["c"]
        z["_queue"] = conn.execute(
            "SELECT COUNT(*) as c FROM queue WHERE zone_id=? "
            "AND status IN ('waiting','called')",
            (z["id"],),
        ).fetchone()["c"]
    return zones


def _zone_has_sport(zone, sport):
    return any(a.get("sport") == sport and a.get("count", 0) > 0
               for a in (zone.get("allocation") or []))


@app.get("/smartgate/user/{user_id}")
def smartgate_user_detail(user_id: str):
    """Return user profile + today's booking quota + any active session.

    Used by the wizard after face scan / registration to decide which view
    to show next (welcome / existing-session / quota-exhausted).
    """
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "User not found")
    user = dict(row)

    active = session_mgr.get_user_active_session(user_id)
    used = session_mgr.get_user_daily_minutes(user_id)
    # Import the constant lazily so any value changes propagate.
    from session_manager import (MAX_DAILY_MINUTES, SESSION_DURATION,
                                 EXTEND_WINDOW, MAX_EXTENSIONS)
    remain = max(0, MAX_DAILY_MINUTES - used)

    # If there's an active session, compute remaining time for UI.
    active_out = None
    if active:
        try:
            expires = datetime.fromisoformat(active["expires_at"])
            time_left = max(0, int((expires - datetime.now()).total_seconds()))
        except Exception:
            time_left = 0
        active_out = {
            "session_id": active["id"],
            "zone_id": active["zone_id"],
            "court_num": active["court_num"],
            "expires_at": active["expires_at"],
            "remaining_seconds": time_left,
            "extended": active.get("extended", 0),
            "can_extend": (
                active.get("extended", 0) < MAX_EXTENSIONS
                and time_left <= EXTEND_WINDOW
                and (used + EXTEND_WINDOW // 60) <= MAX_DAILY_MINUTES
            ),
            "extend_unlocks_in_seconds": max(0, time_left - EXTEND_WINDOW),
        }

    return {
        **user,
        "quota": {
            "max_minutes": MAX_DAILY_MINUTES,
            "used_minutes": used,
            "remaining_minutes": remain,
            "session_length_minutes": SESSION_DURATION // 60,
            "extend_window_minutes": EXTEND_WINDOW // 60,
            "max_extensions": MAX_EXTENSIONS,
            "can_book_new": active is None and remain >= SESSION_DURATION // 60,
        },
        "active_session": active_out,
    }


@app.get("/smartgate/available-sports")
def smartgate_available_sports():
    """Return each sport's current availability across the hub.

    For every sport:
      - walk_in_free: courts immediately playable (configured + free)
      - queue_depth:  people waiting in zones configured for this sport
      - reconfigurable: true if not directly playable but an empty zone can
                        be reconfigured on-the-fly for this sport
    """
    conn = get_db()
    zones = _load_zones_with_counts(conn)
    conn.close()

    empty_zones = [z for z in zones if z["_sessions"] == 0 and z["_queue"] == 0]

    result = []
    for sport, cfg in SPORT_CONFIG.items():
        walk_in_free = 0
        queue_depth = 0
        configured = []
        for z in zones:
            if not _zone_has_sport(z, sport):
                continue
            configured.append(z["id"])
            courts = z.get("courts") or 0
            walk_in_free += max(0, courts - z["_sessions"])
            queue_depth += z["_queue"]

        reconfigurable = (
            walk_in_free == 0
            and len(empty_zones) > 0
            and f"全{sport}" in ALLOC_PRESETS
        )

        # availability verdict, easy for UI
        if walk_in_free > 0:
            verdict = "ready"
        elif reconfigurable:
            verdict = "reconfigurable"
        else:
            verdict = "queue_only"

        result.append({
            "sport": sport,
            "icon": cfg.get("icon", ""),
            "en": cfg.get("en", ""),
            "duration_min": cfg.get("duration", 2700) // 60,
            "walk_in_free": walk_in_free,
            "queue_depth": queue_depth,
            "configured_zones": configured,
            "reconfigurable": reconfigurable,
            "empty_zones_available": len(empty_zones),
            "verdict": verdict,
        })

    return {"sports": result, "empty_zones": [z["id"] for z in empty_zones]}


@app.post("/smartgate/match-sport")
async def smartgate_match_sport(data: SportMatchRequest):
    """Smart-match a user to a zone for a given sport.

    Three-tier fallback:
      1. Walk-in at a configured zone with a free court (pick least-busy).
      2. Auto-reconfigure an empty zone and walk in.
      3. Queue at the configured zone with the shortest queue.
    """
    sport = data.sport
    if sport not in SPORT_CONFIG:
        raise HTTPException(400, f"Unknown sport: {sport}")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (data.user_id,)).fetchone()
    if not user:
        conn.close()
        raise HTTPException(404, "User not found")

    # ── Booking rules (v2.2): 1 session at a time, 2 h daily quota ─────
    # If user already has a session, surface that session as the outcome
    # instead of booking a new one.
    active = session_mgr.get_user_active_session(user["id"])
    if active:
        conn.close()
        try:
            expires = datetime.fromisoformat(active["expires_at"])
            remaining = max(0, int((expires - datetime.now()).total_seconds()))
        except Exception:
            remaining = 0
        from session_manager import (SESSION_DURATION, EXTEND_WINDOW,
                                     MAX_EXTENSIONS, MAX_DAILY_MINUTES)
        used = session_mgr.get_user_daily_minutes(user["id"])
        return {
            "outcome": "already_in_session",
            "zone_id": active["zone_id"],
            "court_num": active["court_num"],
            "session_id": active["id"],
            "expires_at": active["expires_at"],
            "remaining_seconds": remaining,
            "duration_min": SESSION_DURATION // 60,
            "sport": data.sport,
            "extended": active.get("extended", 0),
            "can_extend": (
                active.get("extended", 0) < MAX_EXTENSIONS
                and remaining <= EXTEND_WINDOW
                and used + EXTEND_WINDOW // 60 <= MAX_DAILY_MINUTES
            ),
            "extend_unlocks_in_seconds": max(0, remaining - EXTEND_WINDOW),
            "message": "你已有進行中場次，每次只能預約一個 —— 下方即是目前場次狀態。",
        }

    # Daily quota check
    ok, msg, remain = session_mgr.check_booking_quota(user["id"])
    if not ok:
        conn.close()
        raise HTTPException(400, msg)

    zones = _load_zones_with_counts(conn)

    # ── Tier 1: direct walk-in at a configured zone ─────────────────────
    candidates = []
    for z in zones:
        if not _zone_has_sport(z, sport):
            continue
        if z["_queue"] > 0:
            continue  # don't jump the queue
        courts = z.get("courts") or 0
        free = courts - z["_sessions"]
        if free > 0:
            candidates.append((z, free))

    if candidates:
        candidates.sort(key=lambda x: -x[1])  # most free first
        chosen = candidates[0][0]
        conn.close()
        result = await session_mgr.start_session(user["id"], chosen["id"], None)
        result.update({
            "outcome": "walk_in",
            "zone_id": chosen["id"],
            "zone_name_zh": chosen.get("name_zh", ""),
            "sport": sport,
            "auto_reconfigured": False,
        })
        return result

    # ── Tier 2: auto-reconfigure an empty zone ──────────────────────────
    preset = ALLOC_PRESETS.get(f"全{sport}")
    if preset:
        empty = [z for z in zones if z["_sessions"] == 0 and z["_queue"] == 0]
        if empty:
            # pick the first empty zone (deterministic, user-friendly)
            target = empty[0]
            courts = alloc_to_courts(preset)
            duration = SPORT_CONFIG[sport]["duration"]
            alloc_json = json.dumps(preset, ensure_ascii=False)
            conn.execute(
                "UPDATE zones SET allocation=?, courts=?, current_sport=?, session_duration=? "
                "WHERE id=?",
                (alloc_json, courts, sport, duration, target["id"]),
            )
            conn.commit()
            smart_control.update_zone_equipment(target["id"], preset)

            all_zones = [dict(r) for r in conn.execute("SELECT * FROM zones").fetchall()]
            conn.close()
            await manager.broadcast({"type": "occupancy", "zones": all_zones})

            result = await session_mgr.start_session(user["id"], target["id"], None)
            result.update({
                "outcome": "reconfigured",
                "zone_id": target["id"],
                "zone_name_zh": target.get("name_zh", ""),
                "sport": sport,
                "auto_reconfigured": True,
            })
            return result

    # ── Tier 3: queue at the least-loaded configured zone ───────────────
    configured = [z for z in zones if _zone_has_sport(z, sport)]
    if not configured:
        conn.close()
        raise HTTPException(
            400,
            f"目前無場地配置 {sport}，且無空閒場地可即時重配。請稍後再試。",
        )

    configured.sort(key=lambda z: (z["_queue"], z["_sessions"]))
    chosen = configured[0]

    # already in queue? reject
    existing = conn.execute(
        "SELECT * FROM queue WHERE user_id=? AND zone_id=? "
        "AND status IN ('waiting','called')",
        (user["id"], chosen["id"]),
    ).fetchone()
    if existing:
        conn.close()
        return {
            "outcome": "already_queued",
            "zone_id": chosen["id"],
            "zone_name_zh": chosen.get("name_zh", ""),
            "sport": sport,
            "queue_num": existing["queue_num"],
            "message": "你已在此區輪候中",
        }

    last = conn.execute(
        "SELECT MAX(queue_num) as m FROM queue WHERE zone_id=?",
        (chosen["id"],),
    ).fetchone()
    next_num = (last["m"] or 0) + 1
    entry_id = str(uuid.uuid4())[:8].upper()
    conn.execute(
        "INSERT INTO queue (id, user_id, zone_id, queue_num, joined_at) VALUES (?,?,?,?,?)",
        (entry_id, user["id"], chosen["id"], next_num,
         datetime.now().isoformat()),
    )
    conn.commit()
    queue_data = _get_queue_snapshot(conn)
    conn.close()
    await manager.broadcast({"type": "queue", "data": queue_data})

    return {
        "outcome": "queued",
        "zone_id": chosen["id"],
        "zone_name_zh": chosen.get("name_zh", ""),
        "sport": sport,
        "queue_id": entry_id,
        "queue_num": next_num,
        "message": f"{sport} 暫時滿座，已為你登記至 Zone {chosen['id']}，輪候號 {next_num}。",
    }


# --- SmartCount people detection (for dashboard) ----------------------------

class FrameRequest(BaseModel):
    image: str  # base64 data-URL or raw base64

# Try to load MobileNet-SSD for person detection (best accuracy available without YOLO weights)
_person_net = None
_person_net_type = None

def _init_person_detector():
    """Initialize person detector. Try MobileNet-SSD (DNN) first, fall back to HOG."""
    global _person_net, _person_net_type

    # Option 1: MobileNet-SSD via OpenCV DNN (if model files downloaded)
    proto = _MODEL_DIR / "MobileNetSSD_deploy.prototxt"
    model = _MODEL_DIR / "MobileNetSSD_deploy.caffemodel"
    if proto.exists() and model.exists():
        _person_net = cv2.dnn.readNetFromCaffe(str(proto), str(model))
        _person_net_type = "mobilenet-ssd"
        print("[SmartCount] Using MobileNet-SSD person detector")
        return

    # Option 2: HOG people detector (built-in, no downloads needed)
    _person_net = cv2.HOGDescriptor()
    _person_net.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    _person_net_type = "hog"
    print("[SmartCount] Using HOG people detector (built-in)")

_init_person_detector()

# MobileNet-SSD class labels (PASCAL VOC)
_MN_CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle",
    "bus", "car", "cat", "chair", "cow", "diningtable", "dog",
    "horse", "motorbike", "person", "pottedplant", "sheep", "sofa",
    "train", "tvmonitor"
]
_PERSON_IDX = 15  # "person" class index


def _detect_people_mobilenet(img: np.ndarray, conf_thresh: float = 0.45):
    """Detect people using MobileNet-SSD."""
    h, w = img.shape[:2]
    blob = cv2.dnn.blobFromImage(img, 0.007843, (300, 300), 127.5)
    _person_net.setInput(blob)
    detections = _person_net.forward()

    boxes = []
    for i in range(detections.shape[2]):
        class_id = int(detections[0, 0, i, 1])
        confidence = float(detections[0, 0, i, 2])
        if class_id == _PERSON_IDX and confidence > conf_thresh:
            x1 = max(0, int(detections[0, 0, i, 3] * w))
            y1 = max(0, int(detections[0, 0, i, 4] * h))
            x2 = min(w, int(detections[0, 0, i, 5] * w))
            y2 = min(h, int(detections[0, 0, i, 6] * h))
            boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "conf": round(confidence, 3)})
    return boxes


def _detect_people_hog(img: np.ndarray):
    """Detect people using HOG + SVM (fallback)."""
    # Resize for speed
    scale = 1.0
    max_dim = 640
    h, w = img.shape[:2]
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)))

    rects, weights = _person_net.detectMultiScale(
        img, winStride=(4, 4), padding=(8, 8), scale=1.05
    )

    boxes = []
    for (x, y, bw, bh), weight in zip(rects, weights):
        conf = min(float(weight), 1.0)
        if conf < 0.3:
            continue
        boxes.append({
            "x1": int(x / scale), "y1": int(y / scale),
            "x2": int((x + bw) / scale), "y2": int((y + bh) / scale),
            "conf": round(conf, 3),
        })

    # Non-maximum suppression
    if len(boxes) > 1:
        boxes = _nms(boxes, 0.4)

    return boxes


def _nms(boxes: list, iou_thresh: float) -> list:
    """Simple NMS to remove duplicate detections."""
    if not boxes:
        return boxes
    sorted_boxes = sorted(boxes, key=lambda b: b["conf"], reverse=True)
    keep = []
    for b in sorted_boxes:
        discard = False
        for k in keep:
            iou = _compute_iou(b, k)
            if iou > iou_thresh:
                discard = True
                break
        if not discard:
            keep.append(b)
    return keep


def _compute_iou(a: dict, b: dict) -> float:
    x1 = max(a["x1"], b["x1"])
    y1 = max(a["y1"], b["y1"])
    x2 = min(a["x2"], b["x2"])
    y2 = min(a["y2"], b["y2"])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"])
    area_b = (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0


@app.post("/smartcount/frame")
def smartcount_frame(data: FrameRequest):
    """Detect people in a camera frame and return count + bounding boxes."""
    img = _decode_image(data.image)
    if img is None:
        return {"count": 0, "boxes": [], "error": "無法解碼圖片"}

    h, w = img.shape[:2]

    if _person_net_type == "mobilenet-ssd":
        boxes = _detect_people_mobilenet(img)
    else:
        boxes = _detect_people_hog(img)

    return {
        "count": len(boxes),
        "boxes": boxes,
        "img_w": w,
        "img_h": h,
        "detector": _person_net_type,
    }


@app.get("/")
def root():
    return {
        "service": "BridgeSpace API",
        "version": "2.2.0-dashboard",
        "status": "running",
        "modules": ["SessionManager", "AutoQueue", "SmartControl", "AlertEngine", "SmartGate", "SmartCount"],
        "time": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
