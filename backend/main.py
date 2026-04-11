"""
BridgeSpace Backend API â v2.0 Autonomous Edition
FastAPI server with fully unmanned operation:
  - SessionManager: tracks per-user time, expiry, warnings
  - AutoQueue: SmartCount-driven automatic queue advancement
  - SmartControl: IoT device management (lights, hoops, gates)
  - AlertEngine: Telegram + phone alerts for anomalies

All modules form a closed Sense â Decide â Act loop.
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3, json, asyncio, uuid
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

# âââ Import autonomous modules âââââââââââââââââââââââââââââââââââââââââââââââ

from session_manager import SessionManager
from auto_queue import OccupancyWatcher
from smart_control import SmartControl
from alert_engine import AlertEngine

# âââ Database ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

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
            capacity        INTEGER NOT NULL,
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

    # Seed zones if empty
    cursor = conn.execute("SELECT COUNT(*) FROM zones")
    if cursor.fetchone()[0] == 0:
        zones = [
            ("A", "ç¾½æ¯ç / ç±çå", "Badminton / Basketball", 30, 2700),
            ("B", "å¹åç / ä¹ä¹çå", "Pickleball / Table Tennis", 25, 1800),
            ("C", "ç¤¾åä¼éå", "Community Leisure", 40, 0),
            ("D", "æ°èéåå", "Emerging Sports", 25, 2700),
        ]
        conn.executemany(
            "INSERT INTO zones (id, name_zh, name_en, capacity, session_duration) VALUES (?,?,?,?,?)",
            zones
        )
    conn.commit()
    conn.close()

init_db()

# âââ WebSocket manager âââââââââââââââââââââââââââââââââââââââââââââââââââââââ

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

# âââ Initialize autonomous modules âââââââââââââââââââââââââââââââââââââââââââ

alert_engine = AlertEngine(get_db, manager.broadcast)
smart_control = SmartControl(get_db, manager.broadcast)
session_mgr = SessionManager(get_db, manager.broadcast, smart_control, alert_engine)
occ_watcher = OccupancyWatcher(get_db, manager.broadcast, session_mgr, smart_control, alert_engine)

# âââ Background tasks ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

async def autonomous_loop():
    """Main autonomous loop â runs every 10 seconds."""
    await asyncio.sleep(3)  # wait for startup
    print("[Autonomous] Background loop started â")
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

# âââ FastAPI app âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

app = FastAPI(title="BridgeSpace API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# âââ Models ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

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

# âââ Users âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@app.post("/users/register")
def register_user(data: RegisterUser):
    conn = get_db()
    user_id = str(uuid.uuid4())[:8].upper()
    try:
        conn.execute(
            "INSERT INTO users (id, name, phone, face_id, created) VALUES (?,?,?,?,?)",
            (user_id, data.name, data.phone, data.face_id, datetime.now().isoformat())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(400, "Face already registered")
    conn.close()
    return {"user_id": user_id, "message": "å·²æåç»è¨"}

@app.get("/users/by-face/{face_id}")
def get_user_by_face(face_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE face_id=?", (face_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "æªæ¾å°ç¨æ¶")
    return dict(row)

# âââ Zones & Occupancy âââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@app.get("/zones")
def get_zones():
    conn = get_db()
    rows = conn.execute("SELECT * FROM zones").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/zones/occupancy")
async def update_occupancy(data: OccupancyUpdate):
    """Called by SmartCount every second â triggers autonomous loop."""
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
        (data.count, status, data.zone_id)
    )
    conn.execute(
        "INSERT INTO occupancy_log (zone_id, count, ts) VALUES (?,?,?)",
        (data.zone_id, data.count, datetime.now().isoformat())
    )
    conn.commit()

    all_zones = [dict(r) for r in conn.execute("SELECT * FROM zones").fetchall()]
    conn.close()
    await manager.broadcast({"type": "occupancy", "zones": all_zones})

    # ð Trigger OccupancyWatcher â autonomous departure detection + auto-queue
    await occ_watcher.on_occupancy_update(data.zone_id, data.count)

    return {"status": status, "count": data.count}

# âââ Queue âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@app.post("/queue/join")
async def join_queue(data: JoinQueue):
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM queue WHERE user_id=? AND zone_id=? AND status IN ('waiting','called')",
        (data.user_id, data.zone_id)
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(400, "æ¨å·²å¨æ­¤ååæé")

    # Check walk-in: if < 50% capacity and no queue, allow direct entry
    zone = conn.execute("SELECT * FROM zones WHERE id=?", (data.zone_id,)).fetchone()
    waiting_count = conn.execute(
        "SELECT COUNT(*) as c FROM queue WHERE zone_id=? AND status='waiting'",
        (data.zone_id,)
    ).fetchone()["c"]

    if zone and waiting_count == 0 and zone["current_count"] < zone["capacity"] * 0.5:
        conn.close()
        return {
            "walk_in": True,
            "message": "å ´å°ç©ºéï¼å¯ç´æ¥å¥å ´ï¼è«å° SmartGate æèé²å¥",
            "queue_num": 0,
        }

    last = conn.execute(
        "SELECT MAX(queue_num) as m FROM queue WHERE zone_id=?",
        (data.zone_id,)
    ).fetchone()
    next_num = (last["m"] or 0) + 1

    entry_id = str(uuid.uuid4())[:8].upper()
    conn.execute(
        "INSERT INTO queue (id, user_id, zone_id, queue_num, joined_at) VALUES (?,?,?,?,?)",
        (entry_id, data.user_id, data.zone_id, next_num, datetime.now().isoformat())
    )
    conn.commit()

    queue_data = _get_queue_snapshot(conn)
    conn.close()
    await manager.broadcast({"type": "queue", "data": queue_data})

    return {"queue_id": entry_id, "queue_num": next_num, "message": f"æéèç¢¼ï¼{next_num}"}

@app.post("/queue/call-next/{zone_id}")
async def call_next(zone_id: str):
    """Manual fallback â staff can still call next if needed."""
    conn = get_db()
    next_person = conn.execute(
        "SELECT * FROM queue WHERE zone_id=? AND status='waiting' ORDER BY queue_num ASC LIMIT 1",
        (zone_id,)
    ).fetchone()
    if not next_person:
        conn.close()
        return {"message": "éä¼å·²ç©º"}
    conn.execute(
        "UPDATE queue SET status='called', called_at=? WHERE id=?",
        (datetime.now().isoformat(), next_person["id"])
    )
    conn.commit()

    user = conn.execute("SELECT * FROM users WHERE id=?", (next_person["user_id"],)).fetchone()
    queue_data = _get_queue_snapshot(conn)
    conn.close()
    await manager.broadcast({
        "type": "called",
        "zone_id": zone_id,
        "queue_num": next_person["queue_num"],
        "user_name": user["name"] if user else "ç¨æ¶",
        "queue": queue_data,
        "auto": False,
    })
    return {"called": next_person["queue_num"]}

@app.get("/queue/{zone_id}")
def get_queue(zone_id: str):
    conn = get_db()
    rows = conn.execute(
        """SELECT q.*, u.name FROM queue q
           LEFT JOIN users u ON q.user_id = u.id
           WHERE q.zone_id=? AND q.status IN ('waiting','called')
           ORDER BY q.queue_num ASC""",
        (zone_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# âââ ð Sessions ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@app.post("/session/enter")
async def enter_zone(data: EnterZone):
    """User scans face at zone entrance â starts a timed session."""
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE face_id=?", (data.face_id,)).fetchone()
    if not user:
        conn.close()
        raise HTTPException(404, "æªè­å¥ç¨æ¶ï¼è«åç»è¨")

    # Find their called queue entry
    queue_entry = conn.execute(
        """SELECT * FROM queue
           WHERE user_id=? AND zone_id=? AND status='called'
           ORDER BY called_at DESC LIMIT 1""",
        (user["id"], data.zone_id)
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

# âââ ð Device status âââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@app.get("/devices")
def get_device_states():
    return smart_control.get_all_states()

# âââ ð Alerts ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@app.get("/alerts")
def get_alerts(limit: int = 20):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# âââ WebSocket âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

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

    await ws.send_text(json.dumps({
        "type": "init",
        "zones": zones,
        "queue": queue,
        "sessions": sessions,
        "devices": smart_control.get_all_states(),
    }, default=str))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)

# âââ Helpers âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

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
        "version": "2.0.0-autonomous",
        "status": "running",
        "modules": ["SessionManager", "AutoQueue", "SmartControl", "AlertEngine"],
        "time": datetime.now().isoformat(),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
