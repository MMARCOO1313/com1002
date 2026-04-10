# BridgeSpace — 橋底智能社區運動中心

> COM1002 Cyber Technology and Society — Group 5, Topic 1  
> The Hang Seng University of Hong Kong · Final Exhibition: 18 April 2026

Transform idle space under Sha Lek Highway (沙瀝公路), Sha Tin into an AI-powered community sports hub.  
**No advance booking** — walk-in only, preventing court scalping (炒場). Physically present = fair queue.

---

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│  SmartGate (kiosk.py)      SmartQueue Display (React)   │
│  Face recognition check-in  Live occupancy + queue board │
│                                                          │
│  SmartCount (detect.py)    Backend API (main.py)         │
│  YOLOv8 people counting     FastAPI + SQLite             │
└─────────────────────────────────────────────────────────┘
         All run on ONE MacBook M2
```

| Sub-system | File | Description |
|---|---|---|
| **SmartCount** | `smartcount/detect.py` | YOLOv8n real-time people counting via webcam → API |
| **SmartGate**  | `smartgate/kiosk.py`   | Face recognition kiosk — register & join queue on-site |
| **Backend API**| `backend/main.py`      | FastAPI REST + WebSocket, SQLite database |
| **Display**    | `frontend/`            | React PWA — occupancy board + queue number display |

---

## Quick Start (MacBook M2)

```bash
# 1. Clone and setup (run once)
git clone https://github.com/MMARCOO1313/com1002.git
cd com1002
bash setup_mac.sh

# 2. Activate Python environment
source .venv/bin/activate

# 3. Start all 4 components (4 terminal tabs)
cd backend  && python main.py          # Tab 1 — API on :8000
cd smartcount && python detect.py --zone A --show   # Tab 2 — People counter
cd smartgate && python kiosk.py        # Tab 3 — Face kiosk
cd frontend && npm run dev             # Tab 4 — Display on :3000
```

Open `http://localhost:3000` in Chrome fullscreen (F11) for the queue display board.

---

## Deployment (Vercel + Railway)

### Backend → Railway
1. Create a new Railway project
2. Connect this GitHub repo, set **Root Directory** to `backend`
3. Add start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Copy the Railway URL (e.g. `https://bridgespace-api.railway.app`)

### Frontend → Vercel
1. Connect this repo to Vercel, set **Root Directory** to `frontend`
2. Add environment variables:
   - `VITE_API_URL` = `https://bridgespace-api.railway.app`
   - `VITE_API_WS`  = `wss://bridgespace-api.railway.app/ws`
3. Deploy — Vercel will auto-build with `npm run build`

---

## AI Features

### SmartCount (YOLOv8)
- Model: YOLOv8n (nano) with Apple MPS acceleration
- Detects `person` class with 0.45 confidence threshold
- Rolling 10-frame average to smooth flickering counts
- Pushes count to API every second via REST

### SmartGate (face_recognition + MediaPipe)
- 128-dimensional face encoding stored locally (not photos)
- Cosine distance matching with 0.5 tolerance threshold
- First visit: capture face → register name + phone → store encoding
- Return visit: face matched in <1 second → auto-join queue
- One person = one queue position (anti-scalping enforcement)

### Anti-炒場 Design
- Zero online booking — must be physically present at kiosk
- Face recognition prevents one person holding multiple spots
- No-show auto-cancellation if person doesn't enter within 15 min
- Walk-in allowed when zone is below 50% capacity (no queue needed)

---

## Project Info

- **Course**: COM1002 Cyber Technology and Society
- **Group**: Group 5
- **Topic**: Topic 1 — Understanding Community Needs
- **Site**: Under Sha Lek Highway (沙瀝公路), Sha Tin — 288m × 14m × 5m
- **Exhibition**: 18 April 2026, 14:00–17:00, Venue D201
