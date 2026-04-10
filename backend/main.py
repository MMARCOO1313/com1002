"""
BridgeSpace Backend API
FastAPI server — handles queue, occupancy, and face registration data.
Runs locally on MacBook. Also deployable to Railway (free tier).
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import sqlite3, json, asyncio, time, uuid
from datetime import datetime
from pathlib import Path

app = FastAPI(title="BridgeSpace API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(__file__).parent / "bridgespace.db"

# ─── Database setup ──────────────────────────────────────────────────────────

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
            face_id   TEXT UNIQUE,           -- filename of stored face encoding
            created   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS zones (
            id           TEXT PRIMARY KEY,   -- e.g. 'A', 'B', 'C'
            name_zh      TEXT NOT NULL,
            name_en      TEXT NOT NULL,
            capacity     INTEGER NOT NULL,
            current_count INTEGER DEFAULT 0,
            status       TEXT DEFAULT 'open' -- open / full / closed
        );

        CREATE TABLE IF NOT EXISTS queue (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            zone_id     TEXT NOT NULL,
            queue_num   INTEGER NOT NULL,
            status      TEXT DEFAULT 'waiting',  -- waiting / called / entered / expired
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
    """)

    # Seed zones if empty
    cursor = conn.execute("SELECT COUNT(*) FROM zones")
    if cursor.fetchone()[0] == 0:
        zones = [
            ("A", "羽毛球 / 籃球區", "Badminton / Basketball", 30),
            ("B", "匹克球 / 乒乓球區", "Pickleball / Table Tennis", 25),
            ("C", "社區休閒區", "Community Leisure", 40),
            ("D", "新興運動區", "Emerging Sports", 25),
        ]
        conn.executemany(
            "INSERT INTO zones (id, name_zh, name_en, capacity) VALUES (?,?,?,?)",
            zones
        )
    conn.commit()
    conn.close()

init_db()

# ─── WebSocket connection manager ────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

manager = ConnectionManager()

# ─── Models ──────────────────────────────────────────────────────────────────

class RegisterUser(BaseModel):
    name: str
    phone: str
    face_id: Optional[str] = None   # filename of face encoding

class JoinQueue(BaseModel):
    user_id: str
    zone_id: str

class OccupancyUpdate(BaseModel):
    zone_id: str
    count: int

class FaceCheckIn(BaseModel):
    face_id: str     # matched face encoding filename
    zone_id: str

# ─── Users ───────────────────────────────────────────────────────────────────

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
    return {"user_id": user_id, "message": "已成功登記"}

@app.get("/users/by-face/{face_id}")
def get_user_by_face(face_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE face_id=?", (face_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "未找到用戶")
    return dict(row)

# ─── Zones & Occupancy ───────────────────────────────────────────────────────

@app.get("/zones")
def get_zones():
    conn = get_db()
    rows = conn.execute("SELECT * FROM zones").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/zones/occupancy")
async def update_occupancy(data: OccupancyUpdate):
    """Called by SmartCount every second to push live count."""
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

    # Broadcast to all connected display screens
    all_zones = [dict(r) for r in conn.execute("SELECT * FROM zones").fetchall()]
    conn.close()
    await manager.broadcast({"type": "occupancy", "zones": all_zones})

    return {"status": status, "count": data.count}

# ─── Queue ───────────────────────────────────────────────────────────────────

@app.post("/queue/join")
async def join_queue(data: JoinQueue):
    conn = get_db()

    # Check user not already in queue for this zone
    existing = conn.execute(
        "SELECT * FROM queue WHERE user_id=? AND zone_id=? AND status IN ('waiting','called')",
        (data.user_id, data.zone_id)
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(400, "您已在此區域排隊")

    # Get next queue number
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

    # Broadcast updated queue
    queue_data = _get_queue_snapshot(conn)
    conn.close()
    await manager.broadcast({"type": "queue", "data": queue_data})

    return {"queue_id": entry_id, "queue_num": next_num, "message": f"排隊號碼：{next_num}"}

@app.post("/queue/call-next/{zone_id}")
async def call_next(zone_id: str):
    """Staff presses this to call the next person in line."""
    conn = get_db()
    next_person = conn.execute(
        "SELECT * FROM queue WHERE zone_id=? AND status IN ('waiting','called') ORDER BY queue_num ASC LIMIT 1",
        (zone_id,)
    ).fetchone()
    if not next_person:
        conn.close()
        return {"message": "隊伍已空"}
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
        "user_name": user["name"] if user else "用戶",
        "queue": queue_data
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

def _get_queue_snapshot(conn):
    rows = conn.execute(
        """SELECT q.zone_id, q.queue_num, q.status, u.name
           FROM queue q LEFT JOIN users u ON q.user_id=u.id
           WHERE q.status IN ('waiting','called')
           ORDER BY q.zone_id, q.queue_num"""
    ).fetchall()
    return [dict(r) for r in rows]

# ─── WebSocket (real-time display) ───────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    # Send current state immediately on connect
    conn = get_db()
    zones = [dict(r) for r in conn.execute("SELECT * FROM zones").fetchall()]
    queue = _get_queue_snapshot(conn)
    conn.close()
    await ws.send_text(json.dumps({"type": "init", "zones": zones, "queue": queue}))
    try:
        while True:
            await ws.receive_text()   # keep alive
    except WebSocketDisconnect:
        manager.disconnect(ws)

# ─── Health check ────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"service": "BridgeSpace API", "status": "running", "time": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
