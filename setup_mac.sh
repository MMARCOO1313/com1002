#!/bin/bash
# BridgeSpace — MacBook M2 Setup Script
# Run once after cloning the repo: bash setup_mac.sh

set -e
echo "======================================================"
echo "  BridgeSpace Setup for MacBook (Apple Silicon / M2)"
echo "======================================================"

# ── Check Homebrew ─────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  echo "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# ── Python 3.11 ────────────────────────────────────────────────────────────
if ! command -v python3.11 &>/dev/null; then
  echo "Installing Python 3.11..."
  brew install python@3.11
fi

# ── cmake (needed by some packages; harmless if already installed) ──────────
brew install cmake || true

# ── Node.js ────────────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
  echo "Installing Node.js..."
  brew install node
fi

# ── Backend deps ───────────────────────────────────────────────────────────
echo ""
echo "Installing backend dependencies..."
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

# ── SmartCount deps ────────────────────────────────────────────────────────
echo ""
echo "Installing SmartCount dependencies (PyTorch + YOLOv8)..."
# Install PyTorch for Apple Silicon
pip install torch torchvision torchaudio
pip install -r smartcount/requirements.txt

# ── SmartGate deps ─────────────────────────────────────────────────────────
echo ""
echo "Installing SmartGate dependencies (DeepFace + MediaPipe)..."
# DeepFace: no cmake/dlib required — works natively on Apple Silicon
pip install -r smartgate/requirements.txt
echo "  Note: DeepFace will download FaceNet model weights (~90 MB) on first run."

# ── Frontend deps ──────────────────────────────────────────────────────────
echo ""
echo "Installing frontend dependencies..."
cd frontend && npm install && cd ..

echo ""
echo "======================================================"
echo "  Setup complete!"
echo ""
echo "  To start BridgeSpace locally, open 4 terminal tabs:"
echo ""
echo "  Tab 1 — Backend API:"
echo "    source .venv/bin/activate"
echo "    cd backend && python main.py"
echo ""
echo "  Tab 2 — SmartCount (people counter):"
echo "    source .venv/bin/activate"
echo "    cd smartcount && python detect.py --zone A --show"
echo ""
echo "  Tab 3 — SmartGate (face kiosk):"
echo "    source .venv/bin/activate"
echo "    cd smartgate && python kiosk.py"
echo ""
echo "  Tab 4 — Frontend display:"
echo "    cd frontend && npm run dev"
echo "    Open: http://localhost:3000"
echo "======================================================"
