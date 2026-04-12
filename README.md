# BridgeSpace â æ©åºæºè½ç¤¾åéåä¸­å¿

> COM1002 Cyber Technology and Society â Group 5, Topic 1  
> The Hang Seng University of Hong Kong Â· Final Exhibition: 18 April 2026

Transform idle space under Sha Lek Highway (æ²çå¬è·¯), Sha Tin into an AI-powered community sports hub.  
**No advance booking** â walk-in only, preventing court scalping (çå ´). Physically present = fair queue.

---

## v2.0 â Autonomous Management System èªä¸»ç®¡çç³»çµ±

BridgeSpace v2.0 is a **fully unmanned** sports facility management system. The entire operational loop â from detecting who's inside, managing timed sessions, shutting down equipment when time expires, auto-calling the next person in queue, and alerting administrators for incidents â runs without any staff intervention.

### Autonomous Loop Architecture

```
    ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
    â                   AUTONOMOUS LOOP (10s cycle)                â
    â                                                              â
    â   âââââââââââ    ââââââââââââ    âââââââââââ    ââââââââââ â
    â   â  SENSE  ââââââ  DECIDE  ââââââ   ACT   ââââââ NOTIFY â â
    â   âSmartCountâ   âSession   â    âSmart    â    âAlert   â â
    â   âYOLOv8n  â   âManager + â    âControl  â    âEngine  â â
    â   âoccupancyâ   âOccupancy â    âlights/  â    âTelegramâ â
    â   âdetectionâ   âWatcher   â    âequipmentâ    â/Twilio â â
    â   âââââââââââ   ââââââââââââ    âââââââââââ   ââââââââââ  â
    â        â                                           â        â
    â        âââââââââââââââââââââââââââââââââââââââââââââ        â
    ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
```

---

## System Overview

```
ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
â  SmartGate (kiosk.py)         SmartQueue Display (React)         â
â  Face recognition check-in     Live occupancy + queue + sessions â
â  Session timer + extend                                          â
â                                                                  â
â  SmartCount (detect.py)       Backend API (main.py v2.0)         â
â  YOLOv8 people counting        FastAPI + SQLite + Autonomous     â
â                                                                  â
â  SessionManager               AutoQueue (OccupancyWatcher)       â
â  Timed sessions per zone       Auto-detect departure, call next  â
â                                                                  â
â  SmartControl                 AlertEngine                        â
â  IoT lights/hoops/gates        Telegram + Twilio phone calls     â
ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
         All run on ONE MacBook M2 (or any Linux/Mac server)
```

| Sub-system | File | Description |
|---|---|---|
| **SmartCount** | `smartcount/detect.py` | YOLOv8n real-time people counting via webcam â API |
| **SmartGate** | `smartgate/kiosk.py` | Face recognition kiosk â register, join queue, session timer, extend |
| **Backend API** | `backend/main.py` | FastAPI REST + WebSocket, SQLite, autonomous loop integration |
| **SessionManager** | `backend/session_manager.py` | Timed session lifecycle: active â warning â expired â overstay |
| **OccupancyWatcher** | `backend/auto_queue.py` | Departure detection + auto queue advancement |
| **SmartControl** | `backend/smart_control.py` | IoT device controller (lights, basketball hoops, gates) |
| **AlertEngine** | `backend/alert_engine.py` | Telegram messages + Twilio phone calls for incidents |
| **Display** | `frontend/` | React PWA â occupancy, queue, session timers, device status, alerts |

---

## Quick Start (MacBook M2)

```bash
# 1. Clone and setup (run once)
git clone https://github.com/MMARCOO1313/com1002.git
cd com1002
bash setup_mac.sh

# 2. Activate Python environment
source .venv/bin/activate

# 3. Install backend dependencies
cd backend && pip install -r requirements.txt

# 4. Start all components (4 terminal tabs)
cd backend  && python main.py                       # Tab 1 â API on :8000
cd smartcount && python detect.py --zone A --show    # Tab 2 â People counter
cd smartgate && python kiosk.py                      # Tab 3 â Face kiosk
cd frontend && npm install && npm run dev            # Tab 4 â Display on :3000
```

Open `http://localhost:3000` in Chrome fullscreen (F11) for the dashboard.

### Optional: Enable Alerts

Set environment variables before starting the backend:

```bash
# Telegram alerts
export TELEGRAM_BOT_TOKEN="your-bot-token"
export TELEGRAM_CHAT_ID="your-chat-id"

# Phone call alerts (critical incidents only)
export TWILIO_SID="your-twilio-sid"
export TWILIO_TOKEN="your-twilio-auth-token"
export TWILIO_FROM="+1234567890"
export ADMIN_PHONE="+85291234567"
```

---

## Autonomous Operation Flow

### 1. User Arrives â SmartGate Registration

```
User walks to kiosk â Camera detects face
   âââ First visit: Enter name + phone â capture face encoding â stored locally
   âââ Return visit: Face matched in <1s â auto-identify

User selects zone (A/B/C/D)
   âââ Zone < 50% capacity: Walk-in! Gate opens, session starts immediately
   âââ Zone busy: Join queue, get number, wait for auto-call
```

### 2. Queue Management â Fully Automatic

```
Previous user leaves zone (detected by SmartCount)
   â OccupancyWatcher confirms departure (3 stable ticks)
   â SessionManager ends the leaving user's session
   â SmartControl resets zone (lights on, equipment deployed)
   â AutoQueue calls next person in queue
   â Frontend displays "ð¤ èªåå«è" with user's name
   â User has 15 minutes to enter (no-show = auto-cancelled)
```

### 3. Session Timer â Graduated Enforcement

```
Session starts (zone-specific duration):
   Zone A (ç¾½æ¯ç/ç±ç): 45 min
   Zone B (å¹åç/ä¹ä¹ç): 30 min
   Zone C (ç¤¾åä¼éå): Unlimited
   Zone D (æ°èéåå): 45 min

Timeline:
   [Start] ââââââââââ [Warning 5min] ââ [Expired] ââ [Overstay 5min] ââ [Critical 10min]
      â                     â                â               â                   â
   Lights ON           Lights flash     Lights OFF      Telegram msg       Phone call
   Equipment ON        Warning alert    Hoops retract   to admin           to admin
                       on dashboard     Gate locks
```

### 4. User Can Extend Session

```
At kiosk â Scan face â See session timer
   â Press "çºæ (åå  15 åé)"
   â Max 2 extensions allowed
   â Blocked if queue has waiting users for that zone
```

### 5. Incident Detection â Auto-Alert Admin

| Incident | Detection | Response |
|---|---|---|
| Session expired, user still inside | SmartCount > 0 after timeout | Telegram message to admin |
| Overstay > 10 minutes | Session timer critical | Phone call to admin via Twilio |
| Overcapacity | SmartCount > zone capacity | Telegram alert with zone + count |
| No-show after queue call | 15min timeout, no session entry | Auto-cancel, call next in queue |
| Device fault | SmartControl command failure | Telegram alert with device details |

---

## API Endpoints

### Core Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/zones` | List all zones with occupancy |
| `POST` | `/zones/occupancy` | Push SmartCount data (triggers autonomous watcher) |
| `POST` | `/users/register` | Register new user with face_id |
| `GET` | `/users/by-face/{face_id}` | Look up user by face encoding ID |
| `POST` | `/queue/join` | Join queue (returns `walk_in: true` if direct entry) |
| `POST` | `/queue/call-next` | Manual call next (backup, auto-queue handles this) |

### Autonomous Endpoints (v2.0)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/session/enter` | Start a timed session for user in zone |
| `POST` | `/session/extend` | Extend session (+15 min, max 2x) |
| `GET` | `/sessions/active` | All active sessions with remaining time |
| `GET` | `/devices` | Current IoT device states per zone |
| `GET` | `/alerts` | Recent alert log |
| `WebSocket` | `/ws` | Live updates: zones, queue, sessions, devices, alerts |

---

## AI Features

### SmartCount (YOLOv8)
- Model: YOLOv8n (nano) with Apple MPS acceleration
- Detects `person` class with 0.45 confidence threshold
- Rolling 10-frame average to smooth flickering counts
- Pushes count to API every second via REST
- Departure detection: OccupancyWatcher uses 3-tick stable confirmation to prevent false triggers

### SmartGate (face_recognition + MediaPipe)
- 128-dimensional face encoding stored locally (not photos â privacy-preserving)
- Cosine distance matching with 0.5 tolerance threshold
- First visit: capture face â register name + phone â store encoding
- Return visit: face matched in <1 second â auto-join queue or view session timer
- Session extension available directly at kiosk terminal

### SmartControl (IoT Device Management)
- Per-zone device configuration: lights, basketball hoops, gates
- Simulation mode for demo (no hardware required)
- MQTT integration ready for production hardware
- All device actions logged to database with timestamps

### Anti-çå ´ Design
- Zero online booking â must be physically present at kiosk
- Face recognition prevents one person holding multiple spots
- No-show auto-cancellation if person doesn't enter within 15 min
- Walk-in allowed when zone is below 50% capacity (no queue needed)
- Time-limited sessions prevent indefinite occupation

---

## Frontend Dashboard

The React dashboard (`http://localhost:3000`) shows:

- **Occupancy Board**: Live headcount per zone with capacity bars (green/yellow/red)
- **Session Panel**: Active session countdown timers with color-coded status
- **Device Panel**: 2Ã2 grid showing IoT device states (ð¡ lights, ð hoops, ðª gates)
- **Queue Board**: Current queue with auto-called entries marked "ð¤ èªåå«è"
- **Alert Banner**: Real-time incident alerts with severity coloring

All data updates live via WebSocket â no page refresh needed.

---

## Deployment (Vercel + Railway)

### Backend â Railway
1. Create a new Railway project
2. Connect this GitHub repo, set **Root Directory** to `backend`
3. Add start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Set environment variables for Telegram/Twilio alerts
5. Copy the Railway URL (e.g. `https://bridgespace-api.railway.app`)

### Frontend â Vercel
1. Connect this repo to Vercel, set **Root Directory** to `frontend`
2. Add environment variables:
   - `VITE_API_URL` = `https://bridgespace-api.railway.app`
   - `VITE_API_WS`  = `wss://bridgespace-api.railway.app/ws`
3. Deploy â Vercel will auto-build with `npm run build`

---

## Project Structure

```
bridgespace-code-clean/
âââ backend/
â   âââ main.py              # FastAPI v2.0 â autonomous loop integration
â   âââ session_manager.py   # Timed session lifecycle manager
â   âââ auto_queue.py        # OccupancyWatcher + auto queue advancement
â   âââ smart_control.py     # IoT device controller (lights/hoops/gates)
â   âââ alert_engine.py      # Telegram + Twilio alert system
â   âââ requirements.txt     # Python dependencies
âââ frontend/
â   âââ src/
â   â   âââ App.jsx          # Main dashboard with WebSocket
â   â   âââ components/
â   â       âââ OccupancyBoard.jsx   # Zone occupancy display
â   â       âââ QueueBoard.jsx       # Queue list display
â   â       âââ CalledAlert.jsx      # Queue call notification
â   â       âââ SessionPanel.jsx     # Session countdown timers
â   â       âââ DevicePanel.jsx      # IoT device status grid
â   â       âââ AlertBanner.jsx      # Real-time alert banner
â   âââ package.json
âââ smartcount/
â   âââ detect.py            # YOLOv8n people detection
âââ smartgate/
â   âââ kiosk.py             # Face recognition kiosk v2.0
â   âââ face_db/             # Local face encoding storage
âââ README.md
```

---

## Project Info

- **Course**: COM1002 Cyber Technology and Society
- **Group**: Group 5
- **Topic**: Topic 1 â Understanding Community Needs
- **Site**: Under Sha Lek Highway (æ²çå¬è·¯), Sha Tin â 288m Ã 14m Ã 5m
- **Exhibition**: 18 April 2026, 14:00â17:00, Venue D201
