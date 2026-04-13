# BridgeSpace — 橋底智能社區運動中心

> COM1002 Cyber Technology and Society — Group 5, Topic 1  
> The Hang Seng University of Hong Kong · Final Exhibition: 18 April 2026

Transform idle space under Sha Lek Highway (沙瀝公路), Sha Tin into an AI-powered community sports hub.  
**No advance booking** — walk-in only, preventing court scalping (炒場). Physically present = fair queue.

---

## Quick Start 快速啟動

```bash
# 1. Start Backend API
cd backend
pip install -r requirements.txt
python main.py
# → API on http://localhost:8000

# 2. Open Dashboard
# Open dashboard.html in Chrome
# → Full management system UI
```

That's it! The dashboard connects to the backend automatically and displays real-time zone data.

---

## System Architecture 系統架構

```
┌─────────────────────────────────────────────────────────┐
│                 dashboard.html (Frontend)                │
│  Single-file HTML — 主控大廳 / SmartGate / SmartCount    │
│  / SmartControl / AlertEngine — 5 integrated pages       │
│                        │                                 │
│              REST API + WebSocket                        │
│                        ▼                                 │
│              backend/main.py (FastAPI)                   │
│     ┌──────────┬──────────┬───────────┬──────────┐      │
│     │ Zone     │ Session  │ Smart     │ Alert    │      │
│     │ Catalog  │ Manager  │ Control   │ Engine   │      │
│     │ 多功能場 │ 場次管理 │ IoT設備   │ 警報系統 │      │
│     └──────────┴──────────┴───────────┴──────────┘      │
│                        │                                 │
│              SQLite (bridgespace.db)                     │
└─────────────────────────────────────────────────────────┘
```

---

## Dashboard Pages 功能頁面

### 1. 主控大廳 (Main Dashboard)
The home page showing a complete overview of the facility:
- **Top stats**: Total courts (11), current headcount, active sessions, alert count
- **Zone cards** (A–E): Each shows current sport, court availability (green/yellow/red), session duration
- **Demo Control Panel**: Switch each zone's sport mode in real-time — see courts update dynamically
- **Active Sessions**: Live countdown timers for all active sessions
- **Queue List**: Current waiting queue with position numbers

### 2. SmartGate 智能閘門
Face recognition kiosk simulation for walk-in check-in:
- **3-step flow**: Face Scan → Registration → Zone Selection → Session Start
- **Court grid**: Shows individual court status (free/occupied) per zone
- **Walk-in detection**: Auto-assigns to a free court when available
- **Queue join**: Adds to queue when zone is full
- **Session timer**: Countdown display with extension button (max 2x)

### 3. SmartCount 智能計數
YOLOv8-based people detection and counting:
- **Per-zone headcount**: Push occupancy data to trigger autonomous actions
- **Departure detection**: 3-tick stable confirmation to prevent false triggers
- **Capacity monitoring**: Visual progress bars per zone

### 4. SmartControl 智能控制
IoT device management for each zone:
- **Lights** (💡): On/Off/Flash — auto-controlled by session status
- **Basketball Hoops** (🏀): Deploy/Retract — zone-specific
- **Gates** (🚪): Open/Close — auto-triggered by queue calls
- Device action log with timestamps

### 5. AlertEngine 警報引擎
Incident detection and notification system:
- **Alert log**: All incidents with severity levels and timestamps
- **Telegram integration**: Auto-sends messages for session overstay, overcapacity
- **Twilio integration**: Phone calls for critical incidents (10+ min overstay)
- Alert types: overstay, overcapacity, no-show, device fault

---

## Multi-Functional Zone System 多功能場地系統

Every zone supports multiple sports. Switching sport mode dynamically changes the court count and session duration:

| Zone Type | Zones | Available Sports | Court Config |
|---|---|---|---|
| **球場 (Court)** | A, B | 🏀 籃球 Basketball / 🏐 排球 Volleyball | 籃球: 2 半場 / 排球: 1 全場 |
| **多功能 (Multi)** | C, D, E | 🏸 羽毛球 Badminton / 🏓 乒乓球 Table Tennis / 🏓 匹克球 Pickleball | 羽毛球: 2場 / 乒乓球: 4台 / 匹克球: 2場 |

**Sport Config** (defined in `backend/zone_catalog.py`):

```python
SPORT_CONFIG = {
    "court": {
        "籃球": {"en": "Basketball", "courts": 2, "duration": 2700, "unit": "半場"},
        "排球": {"en": "Volleyball", "courts": 1, "duration": 2700, "unit": "全場"},
    },
    "multi": {
        "羽毛球": {"en": "Badminton",   "courts": 2, "duration": 2700, "unit": "場"},
        "乒乓球": {"en": "Table Tennis", "courts": 4, "duration": 1800, "unit": "台"},
        "匹克球": {"en": "Pickleball",   "courts": 2, "duration": 1800, "unit": "場"},
    },
}
```

**Switch rules**:
- Switch is blocked if any active sessions or queue entries exist in that zone
- Court count and session duration update instantly
- Sessions are tracked per-court (`court_num` in database)

---

## Autonomous Operation 自主運行

The backend runs a 10-second autonomous loop that handles everything without staff:

```
Session starts (duration depends on sport):
   籃球/排球/羽毛球: 45 min
   乒乓球/匹克球: 30 min

Timeline:
   [Start] ── [Warning 5min] ── [Expired] ── [Overstay 5min] ── [Critical 10min]
      │             │                │               │                   │
   Lights ON    Lights flash     Lights OFF     Telegram msg       Phone call
   Equipment ON  Warning alert   Equipment off   to admin           to admin
```

**Queue auto-advancement**:
- SmartCount detects departure → SessionManager ends session → SmartControl resets zone → AutoQueue calls next person → 15-min entry window (no-show = auto-cancel)

---

## API Endpoints

### Core

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/zones` | List all zones with current sport, courts, occupancy |
| `POST` | `/zones/occupancy` | Push SmartCount headcount data |
| `POST` | `/zones/{zone_id}/switch-sport` | Switch zone sport mode `{"sport": "排球"}` |
| `POST` | `/users/register` | Register new user `{"name", "phone", "face_id"}` |
| `GET` | `/users/by-face/{face_id}` | Look up user by face encoding ID |
| `POST` | `/queue/join` | Join queue (returns `walk_in: true` if direct entry) |

### Sessions

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/session/enter` | Start timed session `{"face_id", "zone_id"}` |
| `POST` | `/session/extend` | Extend session `{"session_id"}` (+1 period, max 2x) |
| `GET` | `/sessions/active` | All active sessions with remaining time |

### IoT & Alerts

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/devices` | Current IoT device states per zone |
| `POST` | `/devices/{zone_id}/{device}/command` | Send device command |
| `GET` | `/alerts` | Recent alert log |
| `WebSocket` | `/ws` | Live updates: zones, queue, sessions, devices, alerts |

---

## Anti-炒場 Design 防炒場設計

- Zero online booking — must be physically present
- Face recognition prevents one person holding multiple spots
- No-show auto-cancellation after 15 minutes
- Walk-in allowed when zone has free courts
- Time-limited sessions prevent indefinite occupation

---

## Project Structure 項目結構

```
bridgespace-v2-clone/
├── dashboard.html           # Single-file dashboard UI (主控大廳 + SmartGate + SmartCount + SmartControl + AlertEngine)
├── backend/
│   ├── main.py              # FastAPI — autonomous loop + sport switching + WebSocket
│   ├── zone_catalog.py      # SPORT_CONFIG + DEFAULT_ZONES + DB normalizer
│   ├── session_manager.py   # Timed session lifecycle (per-court tracking)
│   ├── auto_queue.py        # OccupancyWatcher + auto queue advancement
│   ├── smart_control.py     # IoT device controller (lights/hoops/gates)
│   ├── alert_engine.py      # Telegram + Twilio alert system
│   └── requirements.txt
├── smartgate/
│   ├── kiosk_v2.py          # Face recognition fullscreen kiosk (optional, needs camera)
│   ├── kiosk.py             # Legacy kiosk (v1)
│   └── face_db/             # Local face encoding storage
├── smartcount/
│   └── detect.py            # YOLOv8n people detection
├── docs/
├── tests/
└── README.md
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Frontend | Single-file HTML + vanilla JS (no build step) |
| Backend | Python FastAPI + SQLite |
| Real-time | WebSocket (live zone/session/device updates) |
| Face Recognition | face_recognition + MediaPipe (kiosk only) |
| People Counting | YOLOv8n (smartcount only) |
| IoT Control | Simulation mode (MQTT-ready for production) |
| Alerts | Telegram Bot API + Twilio Voice |

---

## Project Info

- **Course**: COM1002 Cyber Technology and Society
- **Group**: Group 5
- **Topic**: Topic 1 — Understanding Community Needs
- **Site**: Under Sha Lek Highway (沙瀝公路), Sha Tin — 288m × 14m × 5m
- **Exhibition**: 18 April 2026, 14:00–17:00, Venue D201
