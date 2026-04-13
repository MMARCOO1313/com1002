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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3, json, asyncio, uuid
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

# --- Import autonomous modules -----------------------------------------------

from session_manager import SessionManager
from auto_queue import OccupancyWatcher
from smart_control import SmartControl
from alert_engine import AlertEngine
from zone_catalog import normalize_zone_catalog, SPORT_CONFIG

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
            session_duration INTEGER DEFAULT 2700
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
    return [dict(r) for r in rows]


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


# --- Queue -------------------------------------------------------------------

@app.post("/queue/join")
async def join_queue(data: JoinQueue):
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
                await smart_control.equipment_deploy(zone_id)
            elif action == "retract":
                await smart_control.equipment_retract(zone_id)
            else:
                raise HTTPException(400, f"Unknown hoop action: {action}")
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


@app.get("/")
def root():
    return {
        "service": "BridgeSpace API",
        "version": "2.1.0-multisport",
        "status": "running",
        "modules": ["SessionManager", "AutoQueue", "SmartControl", "AlertEngine"],
        "time": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
