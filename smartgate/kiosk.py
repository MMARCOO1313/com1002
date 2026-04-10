"""
SmartGate — Face Recognition Kiosk
On-site self-service terminal for walk-in registration and queue joining.
Uses DeepFace (FaceNet) as primary backend — compatible with M2 and Windows.
MediaPipe provides real-time face detection overlay on the camera feed.

Run (normal):  python kiosk.py --api http://localhost:8000
Run (demo):    python kiosk.py --demo --api http://localhost:8000
"""

import cv2
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import numpy as np
import requests
import json
import os
import pickle
import time
from pathlib import Path
from PIL import Image, ImageTk

# ─── Face recognition backend ────────────────────────────────────────────────
# DeepFace wraps FaceNet/ArcFace with a clean API and works on Apple Silicon
# without the dlib/cmake architecture issues.  pip install deepface
try:
    from deepface import DeepFace
    FACE_LIB    = "deepface"
    DEEPFACE_MODEL   = "Facenet"    # 128-d embeddings; fast, accurate, small
    DEEPFACE_BACKEND = "opencv"     # fast detector, good M2 support
    print("[SmartGate] Using DeepFace (FaceNet + OpenCV detector) for face recognition")
except ImportError:
    FACE_LIB    = None
    DEEPFACE_MODEL   = None
    DEEPFACE_BACKEND = None
    print("[SmartGate] DeepFace not found — run: pip install deepface")

# MediaPipe: real-time bounding-box overlay only (does NOT store embeddings)
try:
    import mediapipe as mp
    mp_face_detection = mp.solutions.face_detection
    MEDIAPIPE_OK = True
except (ImportError, AttributeError):
    MEDIAPIPE_OK = False
    print("[SmartGate] MediaPipe face overlay disabled (API not available)")
    print("[SmartGate] MediaPipe not found — face overlay disabled")

# ─── Config ──────────────────────────────────────────────────────────────────

import argparse as _ap
_parser = _ap.ArgumentParser(add_help=False)
_parser.add_argument("--api",  default=os.environ.get("BRIDGESPACE_API", "http://localhost:8000"))
_parser.add_argument("--demo", action="store_true", help="Demo mode: no camera required")
_parser.add_argument("--cam",  default="0", help="Camera index or video path")
_args, _ = _parser.parse_known_args()

API_URL      = _args.api
DEMO_MODE    = _args.demo
FACE_DB_PATH = Path(__file__).parent / "face_db"
FACE_DB_PATH.mkdir(exist_ok=True)
ENCODING_FILE = FACE_DB_PATH / "encodings.pkl"

ZONES = [
    ("A", "羽毛球 / 籃球區"),
    ("B", "匹克球 / 乒乓球區"),
    ("C", "社區休閒區"),
    ("D", "新興運動區"),
]

# ─── Face database ───────────────────────────────────────────────────────────

class FaceDB:
    """Stores {face_id: encoding} mapping in a local pickle file."""

    def __init__(self):
        self.data: dict = {}   # face_id -> encoding (128-d np array)
        self._load()

    def _load(self):
        if ENCODING_FILE.exists():
            with open(ENCODING_FILE, "rb") as f:
                self.data = pickle.load(f)
        print(f"[FaceDB] Loaded {len(self.data)} face(s)")

    def _save(self):
        with open(ENCODING_FILE, "wb") as f:
            pickle.dump(self.data, f)

    def add(self, face_id: str, encoding: np.ndarray):
        self.data[face_id] = encoding
        self._save()

    def match(self, encoding: np.ndarray, tolerance: float = 0.40) -> str | None:
        """Returns face_id of best match, or None if no close enough match.
        Uses cosine distance (works with FaceNet 128-d or any embedding size).
        tolerance=0.40 means ~cos-similarity ≥ 0.60 — tuned for FaceNet.
        """
        if not self.data:
            return None
        known_ids  = list(self.data.keys())
        known_encs = np.array(list(self.data.values()), dtype=np.float32)

        # Normalise to unit vectors then dot-product → cosine similarity
        enc_norm     = encoding / (np.linalg.norm(encoding) + 1e-8)
        norms        = np.linalg.norm(known_encs, axis=1, keepdims=True) + 1e-8
        known_norm   = known_encs / norms
        similarities = known_norm @ enc_norm          # shape (N,)
        best_idx     = int(np.argmax(similarities))
        best_dist    = 1.0 - float(similarities[best_idx])   # cosine distance

        if best_dist <= tolerance:
            return known_ids[best_idx]
        return None


face_db = FaceDB()

# ─── Camera thread ───────────────────────────────────────────────────────────

class CameraThread(threading.Thread):
    def __init__(self, cam_src=0):
        super().__init__(daemon=True)
        self.cam_src = cam_src
        self.frame   = None
        self.running = True
        self._lock   = threading.Lock()
        # Demo mode: generate synthetic frame with a smiley face
        self._demo   = DEMO_MODE or (isinstance(cam_src, str) and cam_src == "demo")

    def run(self):
        if self._demo:
            self._run_demo()
            return
        src = int(self.cam_src) if str(self.cam_src).isdigit() else self.cam_src
        cap = cv2.VideoCapture(src)
        while self.running:
            ret, frame = cap.read()
            if ret:
                with self._lock:
                    self.frame = frame.copy()
            else:
                # Loop video file
                if not str(self.cam_src).isdigit():
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            time.sleep(0.03)
        cap.release()

    def _run_demo(self):
        """Generate a synthetic camera frame (smiley + label) for demo."""
        import math
        t = 0
        while self.running:
            h, w = 480, 640
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            frame[:] = (30, 25, 20)
            # Animate a simple face circle
            cx, cy = w // 2, h // 2
            r = 90
            cv2.circle(frame, (cx, cy), r, (200, 160, 100), -1)
            # Eyes
            ex = int(cx - 30 + 5 * math.sin(t / 10))
            cv2.circle(frame, (ex, cy - 25), 10, (40, 40, 40), -1)
            cv2.circle(frame, (cx + 30, cy - 25), 10, (40, 40, 40), -1)
            # Mouth arc
            cv2.ellipse(frame, (cx, cy + 20), (35, 20), 0, 0, 180, (40, 40, 40), 3)
            cv2.putText(frame, "DEMO — No Camera", (w//2 - 130, h - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 200, 255), 2)
            with self._lock:
                self.frame = frame.copy()
            time.sleep(0.05)
            t += 1

    def get_frame(self):
        with self._lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.running = False


def capture_face_encoding(frame: np.ndarray):
    """Extract FaceNet 128-d embedding from a BGR frame using DeepFace.
    Returns (np.ndarray, None) on success, or (None, error_message) on failure.
    """
    if FACE_LIB != "deepface":
        return None, "DeepFace 未安裝，請執行：pip install deepface"

    try:
        # DeepFace.represent() accepts a BGR numpy array directly
        results = DeepFace.represent(
            img_path        = frame,
            model_name      = DEEPFACE_MODEL,
            enforce_detection = True,
            detector_backend = DEEPFACE_BACKEND,
        )
        if not results:
            return None, "未偵測到人臉，請正面面向鏡頭"
        if len(results) > 1:
            return None, "偵測到多於一張人臉，請確保只有您在鏡頭前"

        embedding = np.array(results[0]["embedding"], dtype=np.float32)
        return embedding, None

    except ValueError as e:
        msg = str(e)
        if "Face could not be detected" in msg or "No face" in msg:
            return None, "未偵測到人臉，請正面面向鏡頭"
        return None, f"人臉偵測失敗：{msg[:60]}"
    except Exception as e:
        return None, f"識別錯誤：{str(e)[:60]}"

# ─── API helpers ─────────────────────────────────────────────────────────────

def api_register(name: str, phone: str, face_id: str) -> dict:
    r = requests.post(f"{API_URL}/users/register",
                      json={"name": name, "phone": phone, "face_id": face_id},
                      timeout=5)
    r.raise_for_status()
    return r.json()

def api_get_user_by_face(face_id: str) -> dict | None:
    try:
        r = requests.get(f"{API_URL}/users/by-face/{face_id}", timeout=5)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def api_join_queue(user_id: str, zone_id: str) -> dict:
    r = requests.post(f"{API_URL}/queue/join",
                      json={"user_id": user_id, "zone_id": zone_id},
                      timeout=5)
    r.raise_for_status()
    return r.json()

def api_get_zones() -> list:
    try:
        r = requests.get(f"{API_URL}/zones", timeout=3)
        return r.json()
    except Exception:
        return []

# ─── Kiosk UI ────────────────────────────────────────────────────────────────

class BridgeSpaceKiosk(tk.Tk):
    """Full-screen touch-friendly kiosk application."""

    BG    = "#0F172A"
    CARD  = "#1E293B"
    BLUE  = "#3B82F6"
    GREEN = "#22C55E"
    RED   = "#EF4444"
    AMBER = "#F59E0B"
    WHITE = "#F1F5F9"
    GRAY  = "#64748B"
    # Cross-platform font: PingFang TC on macOS, Microsoft JhengHei on Windows
    import platform as _plat
    _CJK = "Microsoft JhengHei" if _plat.system() == "Windows" else "PingFang TC"
    FONT_TITLE  = (_CJK, 32, "bold")
    FONT_LARGE  = (_CJK, 24)
    FONT_MEDIUM = (_CJK, 18)
    FONT_SMALL  = (_CJK, 14)

    def __init__(self):
        super().__init__()
        self.title("BridgeSpace 智能入場系統")
        self.configure(bg=self.BG)
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        cam_src = "demo" if DEMO_MODE else (_args.cam if not str(_args.cam).isdigit() else int(_args.cam))
        self.cam = CameraThread(cam_src)
        self.cam.start()

        self._state = "home"       # home / scanning / register_form / queue_select / confirmed
        self._current_user = None
        self._pending_encoding = None
        self._pending_face_id = None

        self._build_ui()
        self._refresh_cam()

    # ── UI builders ──────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Left: camera feed
        self.cam_label = tk.Label(self, bg=self.BG)
        self.cam_label.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")

        # Right: interaction panel
        self.panel = tk.Frame(self, bg=self.BG)
        self.panel.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        self._show_home()

    def _clear_panel(self):
        for w in self.panel.winfo_children():
            w.destroy()

    def _lbl(self, parent, text, font=None, color=None, **kwargs):
        return tk.Label(parent, text=text,
                        font=font or self.FONT_MEDIUM,
                        fg=color or self.WHITE, bg=self.BG,
                        wraplength=500, justify="left", **kwargs)

    def _btn(self, parent, text, cmd, color=None, **kwargs):
        color = color or self.BLUE
        return tk.Button(parent, text=text, command=cmd,
                         font=self.FONT_LARGE, fg=self.WHITE,
                         bg=color, activebackground=color,
                         relief="flat", cursor="hand2",
                         padx=20, pady=14, **kwargs)

    # ── Home screen ──────────────────────────────────────────────────────────

    def _show_home(self):
        self._state = "home"
        self._current_user = None
        self._clear_panel()
        p = self.panel

        tk.Label(p, text="🏃", font=("Arial", 60), bg=self.BG).pack(pady=(40, 10))
        tk.Label(p, text="BridgeSpace", font=("PingFang TC", 38, "bold"),
                 fg=self.WHITE, bg=self.BG).pack()
        tk.Label(p, text="橋底智能社區運動中心", font=self.FONT_LARGE,
                 fg=self.GRAY, bg=self.BG).pack(pady=(0, 40))

        # Show zone occupancy
        zones = api_get_zones()
        if zones:
            for z in zones:
                pct = int(z["current_count"] / max(z["capacity"], 1) * 100)
                color = self.GREEN if pct < 70 else (self.AMBER if pct < 90 else self.RED)
                row = tk.Frame(p, bg=self.CARD)
                row.pack(fill="x", padx=10, pady=4)
                tk.Label(row, text=z["name_zh"], font=self.FONT_SMALL,
                         fg=self.WHITE, bg=self.CARD, anchor="w").pack(side="left", padx=12, pady=8)
                tk.Label(row, text=f"{z['current_count']}/{z['capacity']} ({pct}%)",
                         font=self.FONT_SMALL, fg=color, bg=self.CARD).pack(side="right", padx=12)

        self._btn(p, "📷  掃描人臉 入場排隊", self._start_scan,
                  color=self.BLUE).pack(fill="x", padx=10, pady=(30, 8))
        self._btn(p, "✏️  首次登記", self._show_register_prompt,
                  color=self.GRAY).pack(fill="x", padx=10, pady=8)

    # ── Face scan ────────────────────────────────────────────────────────────

    def _start_scan(self):
        self._state = "scanning"
        self._clear_panel()
        p = self.panel

        tk.Label(p, text="人臉掃描", font=self.FONT_TITLE,
                 fg=self.WHITE, bg=self.BG).pack(pady=(60, 10))
        tk.Label(p, text="請正面面向左方鏡頭\n保持 40–60 cm 距離",
                 font=self.FONT_LARGE, fg=self.GRAY, bg=self.BG,
                 justify="center").pack(pady=20)

        self.scan_status = tk.Label(p, text="等待掃描中…", font=self.FONT_LARGE,
                                    fg=self.AMBER, bg=self.BG)
        self.scan_status.pack(pady=30)

        self._btn(p, "← 返回", self._show_home, color=self.GRAY).pack(pady=20)

        # Trigger scan after 1.5s
        self.after(1500, self._do_face_scan)

    def _do_face_scan(self):
        frame = self.cam.get_frame()
        if frame is None:
            self.scan_status.config(text="鏡頭未就緒，請稍後再試", fg=self.RED)
            self.after(2000, self._show_home)
            return

        encoding, err = capture_face_encoding(frame)
        if err:
            self.scan_status.config(text=err, fg=self.RED)
            self.after(2500, self._start_scan)
            return

        # Try to match against existing faces
        face_id = face_db.match(encoding)
        if face_id:
            user = api_get_user_by_face(face_id)
            if user:
                self._current_user = user
                self.scan_status.config(text=f"✅  識別成功：{user['name']}", fg=self.GREEN)
                self.after(1200, self._show_zone_select)
                return

        # No match — offer to register
        self._pending_encoding = encoding
        self._pending_face_id = None
        self.scan_status.config(text="未找到您的記錄，請先登記", fg=self.AMBER)
        self.after(1500, self._show_register_prompt)

    # ── Register ─────────────────────────────────────────────────────────────

    def _show_register_prompt(self):
        self._state = "register_form"
        self._clear_panel()
        p = self.panel

        tk.Label(p, text="首次登記", font=self.FONT_TITLE,
                 fg=self.WHITE, bg=self.BG).pack(pady=(40, 20))
        tk.Label(p, text="請輸入您的資料。登記後下次到訪\n直接掃臉即可，無需重新輸入。",
                 font=self.FONT_MEDIUM, fg=self.GRAY, bg=self.BG,
                 justify="center").pack(pady=(0, 20))

        frm = tk.Frame(p, bg=self.BG)
        frm.pack(fill="x", padx=20)

        tk.Label(frm, text="姓名", font=self.FONT_MEDIUM, fg=self.WHITE, bg=self.BG,
                 anchor="w").pack(fill="x")
        self.name_var = tk.StringVar()
        name_entry = ttk.Entry(frm, textvariable=self.name_var, font=self.FONT_MEDIUM)
        name_entry.pack(fill="x", pady=(4, 16))

        tk.Label(frm, text="電話號碼", font=self.FONT_MEDIUM, fg=self.WHITE, bg=self.BG,
                 anchor="w").pack(fill="x")
        self.phone_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.phone_var, font=self.FONT_MEDIUM).pack(fill="x", pady=(4, 16))

        self.reg_status = tk.Label(p, text="", font=self.FONT_MEDIUM,
                                   fg=self.RED, bg=self.BG)
        self.reg_status.pack(pady=10)

        self._btn(p, "📷  拍攝人臉並提交", self._submit_registration,
                  color=self.GREEN).pack(fill="x", padx=20, pady=8)
        self._btn(p, "← 返回", self._show_home, color=self.GRAY).pack(fill="x", padx=20)

    def _submit_registration(self):
        name = self.name_var.get().strip()
        phone = self.phone_var.get().strip()

        if not name or not phone:
            self.reg_status.config(text="請填寫所有欄位")
            return
        if len(phone) < 8:
            self.reg_status.config(text="請輸入有效電話號碼")
            return

        self.reg_status.config(text="正在拍攝人臉…", fg=self.AMBER)
        self.after(800, lambda: self._capture_and_register(name, phone))

    def _capture_and_register(self, name: str, phone: str):
        frame = self.cam.get_frame()
        if frame is None:
            self.reg_status.config(text="鏡頭未就緒", fg=self.RED)
            return

        encoding, err = capture_face_encoding(frame)
        if err:
            self.reg_status.config(text=err, fg=self.RED)
            return

        # Check not already in DB
        if face_db.match(encoding, tolerance=0.45):
            self.reg_status.config(text="此人臉已登記，請掃臉入場", fg=self.AMBER)
            self.after(2000, self._show_home)
            return

        import uuid
        face_id = str(uuid.uuid4())[:12]
        try:
            result = api_register(name, phone, face_id)
            face_db.add(face_id, encoding)
            self._current_user = {"id": result["user_id"], "name": name, "phone": phone}
            self._pending_encoding = None
            self.reg_status.config(text=f"✅ 登記成功！歡迎 {name}", fg=self.GREEN)
            self.after(1200, self._show_zone_select)
        except Exception as e:
            self.reg_status.config(text=f"登記失敗：{e}", fg=self.RED)

    # ── Zone selection ───────────────────────────────────────────────────────

    def _show_zone_select(self):
        self._state = "queue_select"
        self._clear_panel()
        p = self.panel
        name = self._current_user.get("name", "用戶")

        tk.Label(p, text=f"歡迎，{name}！", font=self.FONT_TITLE,
                 fg=self.GREEN, bg=self.BG).pack(pady=(40, 6))
        tk.Label(p, text="請選擇您想使用的區域排隊",
                 font=self.FONT_LARGE, fg=self.GRAY, bg=self.BG).pack(pady=(0, 30))

        zones = api_get_zones()
        zone_map = {z["id"]: z for z in zones}

        for zone_id, zone_name in ZONES:
            z = zone_map.get(zone_id, {})
            count = z.get("current_count", 0)
            cap   = z.get("capacity", 30)
            pct   = int(count / max(cap, 1) * 100)
            status = z.get("status", "open")

            if status == "full":
                state = "disabled"
                label = f"{zone_name}\n🔴 已滿 ({count}/{cap})"
                bg = self.GRAY
            elif status == "busy":
                state = "normal"
                label = f"{zone_name}\n🟡 繁忙 ({count}/{cap})"
                bg = self.AMBER
            else:
                state = "normal"
                label = f"{zone_name}\n🟢 空閒 ({count}/{cap})"
                bg = self.BLUE

            tk.Button(p, text=label, command=lambda zid=zone_id: self._join_queue(zid),
                      font=self.FONT_MEDIUM, fg=self.WHITE, bg=bg,
                      activebackground=bg, relief="flat", cursor="hand2",
                      padx=20, pady=16, state=state,
                      justify="center").pack(fill="x", padx=10, pady=6)

        self._btn(p, "← 返回首頁", self._show_home, color=self.GRAY).pack(pady=20)

    def _join_queue(self, zone_id: str):
        try:
            result = api_join_queue(self._current_user["id"], zone_id)
            self._show_confirmed(zone_id, result["queue_num"])
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                messagebox.showwarning("提示", "您已在此區域排隊，請等候叫號")
            else:
                messagebox.showerror("錯誤", str(e))
        except Exception as e:
            messagebox.showerror("錯誤", str(e))

    # ── Confirmed screen ─────────────────────────────────────────────────────

    def _show_confirmed(self, zone_id: str, queue_num: int):
        self._state = "confirmed"
        self._clear_panel()
        p = self.panel

        zone_name = dict(ZONES).get(zone_id, zone_id)

        tk.Label(p, text="✅", font=("Arial", 72), bg=self.BG).pack(pady=(50, 0))
        tk.Label(p, text="已加入排隊！", font=self.FONT_TITLE,
                 fg=self.GREEN, bg=self.BG).pack(pady=10)

        card = tk.Frame(p, bg=self.CARD)
        card.pack(fill="x", padx=20, pady=20)
        tk.Label(card, text=f"區域：{zone_name}", font=self.FONT_LARGE,
                 fg=self.WHITE, bg=self.CARD).pack(pady=(16, 6))
        tk.Label(card, text=f"您的號碼", font=self.FONT_MEDIUM,
                 fg=self.GRAY, bg=self.CARD).pack()
        tk.Label(card, text=str(queue_num), font=("PingFang TC", 80, "bold"),
                 fg=self.AMBER, bg=self.CARD).pack(pady=10)
        tk.Label(card, text="請留意顯示屏上的叫號\n請勿離開設施範圍", font=self.FONT_MEDIUM,
                 fg=self.GRAY, bg=self.CARD, justify="center").pack(pady=(0, 16))

        self._btn(p, "完成，返回首頁", lambda: self.after(0, self._show_home),
                  color=self.BLUE).pack(fill="x", padx=20, pady=10)

    # ── Camera refresh ───────────────────────────────────────────────────────

    def _refresh_cam(self):
        frame = self.cam.get_frame()
        if frame is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            # Resize to fit panel (~600px wide)
            w, h = img.size
            target_w = 560
            img = img.resize((target_w, int(h * target_w / w)), Image.LANCZOS)

            # Draw face detection overlay
            if MEDIAPIPE_OK and self._state in ("scanning", "register_form"):
                img_arr = np.array(img)
                with mp_face_detection.FaceDetection(min_detection_confidence=0.6) as fd:
                    results = fd.process(img_arr)
                    if results.detections:
                        for det in results.detections:
                            bb = det.location_data.relative_bounding_box
                            x = int(bb.xmin * target_w)
                            y = int(bb.ymin * img.size[1])
                            w2 = int(bb.width * target_w)
                            h2 = int(bb.height * img.size[1])
                            cv2.rectangle(img_arr, (x, y), (x + w2, y + h2), (34, 197, 94), 3)
                img = Image.fromarray(img_arr)

            photo = ImageTk.PhotoImage(img)
            self.cam_label.config(image=photo)
            self.cam_label.image = photo

        self.after(33, self._refresh_cam)   # ~30fps

    def on_close(self):
        self.cam.stop()
        self.destroy()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = BridgeSpaceKiosk()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
