"""
BridgeSpace SmartGate v2.0
Self-service kiosk for registration, queue joining, zone entry, and session extension.
"""

import argparse
import os
import pickle
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import requests
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import messagebox, ttk

from face_matching import (
    MEDIAPIPE_OK,
    detect_single_face,
    encode_face_crop,
    match_face_signature,
    mp_face_detection,
)


API_URL = os.environ.get("BRIDGESPACE_API", "http://localhost:8000")
FACE_DB_PATH = Path(__file__).parent / "face_db"
FACE_DB_PATH.mkdir(exist_ok=True)
ENCODING_FILE = FACE_DB_PATH / "encodings.pkl"
USE_LEGACY_FACE_RECOGNITION = os.environ.get("SMARTGATE_USE_LEGACY_FACE_RECOGNITION") == "1"

try:
    import face_recognition

    FACE_LIB_AVAILABLE = True
except ImportError:
    face_recognition = None
    FACE_LIB_AVAILABLE = False


ZONES = [
    ("A", "Badminton / Basketball"),
    ("B", "Pickleball / Table Tennis"),
    ("C", "Community Leisure"),
    ("D", "Emerging Sports"),
]


class FaceDB:
    """Stores local face samples for kiosk-side recognition."""

    def __init__(self):
        self.data = {}
        self._load()

    def _load(self):
        if ENCODING_FILE.exists():
            with open(ENCODING_FILE, "rb") as file:
                raw = pickle.load(file)
            self.data = {
                face_id: self._coerce_entry(entry)
                for face_id, entry in raw.items()
            }
        print(f"[FaceDB] Loaded {len(self.data)} face sample(s)")

    def _save(self):
        with open(ENCODING_FILE, "wb") as file:
            pickle.dump(self.data, file)

    def _coerce_entry(self, entry):
        if isinstance(entry, dict) and "encoding" in entry:
            return {
                "algorithm": entry.get("algorithm", "face_signature"),
                "encoding": np.asarray(entry["encoding"], dtype=np.float32),
            }
        return {
            "algorithm": "legacy_face_recognition",
            "encoding": np.asarray(entry, dtype=np.float32),
        }

    def add(self, face_id, encoding, algorithm):
        self.data[face_id] = {
            "algorithm": algorithm,
            "encoding": np.asarray(encoding, dtype=np.float32),
        }
        self._save()

    def match(self, encoding, algorithm, tolerance=None):
        compatible = {
            face_id: entry["encoding"]
            for face_id, entry in self.data.items()
            if entry["algorithm"] == algorithm
        }
        if not compatible:
            return None

        if algorithm == "legacy_face_recognition" and FACE_LIB_AVAILABLE:
            known_ids = list(compatible.keys())
            distances = face_recognition.face_distance(list(compatible.values()), encoding)
            best_idx = int(np.argmin(distances))
            threshold = tolerance if tolerance is not None else 0.50
            if float(distances[best_idx]) <= threshold:
                return known_ids[best_idx]
            return None

        threshold = tolerance if tolerance is not None else 0.55
        return match_face_signature(compatible, encoding, tolerance=threshold)


face_db = FaceDB()


class CameraThread(threading.Thread):
    def __init__(self, cam_idx=0):
        super().__init__(daemon=True)
        self.cam_idx = cam_idx
        self.frame = None
        self.running = True
        self._lock = threading.Lock()

    def run(self):
        cap = cv2.VideoCapture(self.cam_idx)
        while self.running:
            ret, frame = cap.read()
            if ret:
                with self._lock:
                    self.frame = frame.copy()
            time.sleep(0.03)
        cap.release()

    def get_frame(self):
        with self._lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.running = False


def capture_face_sample(frame):
    if USE_LEGACY_FACE_RECOGNITION and FACE_LIB_AVAILABLE:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb, model="hog")
        if not locations:
            return None, None, "No face detected. Please look directly at the camera."
        if len(locations) > 1:
            return None, None, "Multiple faces detected. Please scan one person at a time."

        encodings = face_recognition.face_encodings(rgb, locations)
        if not encodings:
            return None, None, "Face encoding failed. Please scan again."
        return encodings[0], "legacy_face_recognition", None

    crop, error = detect_single_face(frame)
    if error:
        return None, None, error
    return encode_face_crop(crop), "face_signature", None


def api_register(name, phone, face_id):
    response = requests.post(
        f"{API_URL}/users/register",
        json={"name": name, "phone": phone, "face_id": face_id},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def api_get_user_by_face(face_id):
    try:
        response = requests.get(f"{API_URL}/users/by-face/{face_id}", timeout=5)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def api_join_queue(user_id, zone_id):
    response = requests.post(
        f"{API_URL}/queue/join",
        json={"user_id": user_id, "zone_id": zone_id},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def api_get_zones():
    try:
        response = requests.get(f"{API_URL}/zones", timeout=3)
        response.raise_for_status()
        return response.json()
    except Exception:
        return []


def api_session_enter(face_id, zone_id, queue_id=None):
    response = requests.post(
        f"{API_URL}/session/enter",
        json={"face_id": face_id, "zone_id": zone_id, "queue_id": queue_id},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def api_session_extend(session_id):
    response = requests.post(
        f"{API_URL}/session/extend",
        json={"session_id": session_id},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def api_get_active_sessions():
    try:
        response = requests.get(f"{API_URL}/sessions/active", timeout=3)
        response.raise_for_status()
        return response.json()
    except Exception:
        return []


class BridgeSpaceKiosk(tk.Tk):
    BG = "#0F172A"
    CARD = "#1E293B"
    BLUE = "#3B82F6"
    GREEN = "#22C55E"
    RED = "#EF4444"
    AMBER = "#F59E0B"
    WHITE = "#F1F5F9"
    GRAY = "#64748B"
    FONT_TITLE = ("Segoe UI", 28, "bold")
    FONT_LARGE = ("Segoe UI", 20)
    FONT_MEDIUM = ("Segoe UI", 16)
    FONT_SMALL = ("Segoe UI", 12)

    def __init__(self):
        super().__init__()
        self.title("BridgeSpace SmartGate")
        self.configure(bg=self.BG)
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda event: self.attributes("-fullscreen", False))

        self.cam = CameraThread(0)
        self.cam.start()

        self._state = "home"
        self._current_user = None
        self._active_session = None
        self._session_timer_id = None

        self._build_ui()
        self._refresh_cam()

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.cam_label = tk.Label(self, bg=self.BG)
        self.cam_label.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")

        self.panel = tk.Frame(self, bg=self.BG)
        self.panel.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        self._show_home()

    def _clear_panel(self):
        for widget in self.panel.winfo_children():
            widget.destroy()

    def _btn(self, parent, text, command, color=None):
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=self.FONT_LARGE,
            fg=self.WHITE,
            bg=color or self.BLUE,
            activebackground=color or self.BLUE,
            relief="flat",
            cursor="hand2",
            padx=20,
            pady=14,
        )

    def _show_home(self):
        self._state = "home"
        self._current_user = None
        self._clear_panel()
        panel = self.panel

        tk.Label(panel, text="BridgeSpace SmartGate", font=self.FONT_TITLE, fg=self.WHITE, bg=self.BG).pack(pady=(48, 8))
        tk.Label(panel, text="Live kiosk for face scan, registration, and zone entry.", font=self.FONT_LARGE, fg=self.GRAY, bg=self.BG).pack(pady=(0, 28))

        zones = api_get_zones()
        if zones:
            for zone in zones:
                pct = int(zone["current_count"] / max(zone["capacity"], 1) * 100)
                color = self.GREEN if pct < 70 else self.AMBER if pct < 90 else self.RED
                row = tk.Frame(panel, bg=self.CARD)
                row.pack(fill="x", padx=10, pady=4)
                tk.Label(
                    row,
                    text=zone.get("name_en") or zone.get("name_zh") or zone["id"],
                    font=self.FONT_SMALL,
                    fg=self.WHITE,
                    bg=self.CARD,
                    anchor="w",
                ).pack(side="left", padx=12, pady=8)
                tk.Label(
                    row,
                    text=f'{zone["current_count"]}/{zone["capacity"]} ({pct}%)',
                    font=self.FONT_SMALL,
                    fg=color,
                    bg=self.CARD,
                ).pack(side="right", padx=12)

        self._btn(panel, "Scan Face to Continue", self._start_scan, color=self.BLUE).pack(fill="x", padx=10, pady=(28, 8))
        self._btn(panel, "First-Time Registration", self._show_register_prompt, color=self.GRAY).pack(fill="x", padx=10, pady=8)

    def _start_scan(self):
        self._state = "scanning"
        self._clear_panel()
        panel = self.panel

        tk.Label(panel, text="Scan Face to Continue", font=self.FONT_TITLE, fg=self.WHITE, bg=self.BG).pack(pady=(60, 10))
        tk.Label(panel, text="Look straight at the camera and stay within 40 to 60 cm.", font=self.FONT_LARGE, fg=self.GRAY, bg=self.BG, justify="center").pack(pady=20)

        self.scan_status = tk.Label(panel, text="Waiting for scan...", font=self.FONT_LARGE, fg=self.AMBER, bg=self.BG)
        self.scan_status.pack(pady=30)

        self._btn(panel, "Back", self._show_home, color=self.GRAY).pack(pady=20)
        self.after(1500, self._do_face_scan)

    def _do_face_scan(self):
        frame = self.cam.get_frame()
        if frame is None:
            self.scan_status.config(text="Camera is not ready. Please try again.", fg=self.RED)
            self.after(2000, self._show_home)
            return

        encoding, algorithm, error = capture_face_sample(frame)
        if error:
            self.scan_status.config(text=error, fg=self.RED)
            self.after(2500, self._start_scan)
            return

        face_id = face_db.match(encoding, algorithm)
        if face_id:
            user = api_get_user_by_face(face_id)
            if user:
                self._current_user = user
                self.scan_status.config(text=f"Scan successful: {user['name']}", fg=self.GREEN)
                active = api_get_active_sessions()
                existing_session = next((session for session in active if session.get("user_id") == user["id"]), None)
                if existing_session:
                    self.after(1200, lambda: self._show_session_started(existing_session["zone_id"], existing_session))
                else:
                    self.after(1200, self._show_zone_select)
                return

        self.scan_status.config(text="Face not found. Please register first.", fg=self.AMBER)
        self.after(1500, self._show_register_prompt)

    def _show_register_prompt(self):
        self._state = "register_form"
        self._clear_panel()
        panel = self.panel

        tk.Label(panel, text="First-Time Registration", font=self.FONT_TITLE, fg=self.WHITE, bg=self.BG).pack(pady=(40, 20))
        tk.Label(panel, text="Enter your details. A fresh face scan will be captured when you submit.", font=self.FONT_MEDIUM, fg=self.GRAY, bg=self.BG, justify="center").pack(pady=(0, 20))

        form = tk.Frame(panel, bg=self.BG)
        form.pack(fill="x", padx=20)

        tk.Label(form, text="Name", font=self.FONT_MEDIUM, fg=self.WHITE, bg=self.BG, anchor="w").pack(fill="x")
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var, font=self.FONT_MEDIUM).pack(fill="x", pady=(4, 16))

        tk.Label(form, text="Phone", font=self.FONT_MEDIUM, fg=self.WHITE, bg=self.BG, anchor="w").pack(fill="x")
        self.phone_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.phone_var, font=self.FONT_MEDIUM).pack(fill="x", pady=(4, 16))

        self.reg_status = tk.Label(panel, text="", font=self.FONT_MEDIUM, fg=self.RED, bg=self.BG)
        self.reg_status.pack(pady=10)

        self._btn(panel, "Capture Face and Register", self._submit_registration, color=self.GREEN).pack(fill="x", padx=20, pady=8)
        self._btn(panel, "Back", self._show_home, color=self.GRAY).pack(fill="x", padx=20)

    def _submit_registration(self):
        name = self.name_var.get().strip()
        phone = self.phone_var.get().strip()

        if not name or not phone:
            self.reg_status.config(text="Please fill in every field.", fg=self.RED)
            return
        if len(phone) < 8:
            self.reg_status.config(text="Please enter a valid phone number.", fg=self.RED)
            return

        self.reg_status.config(text="Capturing face sample...", fg=self.AMBER)
        self.after(800, lambda: self._capture_and_register(name, phone))

    def _capture_and_register(self, name, phone):
        frame = self.cam.get_frame()
        if frame is None:
            self.reg_status.config(text="Camera is not ready.", fg=self.RED)
            return

        encoding, algorithm, error = capture_face_sample(frame)
        if error:
            self.reg_status.config(text=error, fg=self.RED)
            return

        if face_db.match(encoding, algorithm, tolerance=0.45):
            self.reg_status.config(text="This face is already registered. Please scan instead.", fg=self.AMBER)
            self.after(1800, self._show_home)
            return

        face_id = str(uuid.uuid4())[:12]
        try:
            result = api_register(name, phone, face_id)
            face_db.add(face_id, encoding, algorithm)
            self._current_user = {
                "id": result["user_id"],
                "name": name,
                "phone": phone,
                "face_id": face_id,
            }
            self.reg_status.config(text=f"Registration complete: {name}", fg=self.GREEN)
            self.after(1200, self._show_zone_select)
        except Exception as exc:
            self.reg_status.config(text=f"Registration failed: {exc}", fg=self.RED)

    def _show_zone_select(self):
        self._state = "queue_select"
        self._clear_panel()
        panel = self.panel
        user_name = self._current_user.get("name", "Guest")

        tk.Label(panel, text=f"Welcome, {user_name}", font=self.FONT_TITLE, fg=self.GREEN, bg=self.BG).pack(pady=(40, 6))
        tk.Label(panel, text="Choose the zone you want to use today.", font=self.FONT_LARGE, fg=self.GRAY, bg=self.BG).pack(pady=(0, 30))

        zones = api_get_zones()
        zone_map = {zone["id"]: zone for zone in zones}

        for zone_id, zone_label in ZONES:
            zone = zone_map.get(zone_id, {})
            count = zone.get("current_count", 0)
            capacity = zone.get("capacity", 30)
            status = zone.get("status", "open")

            if status == "full":
                button_state = "disabled"
                button_color = self.GRAY
                label = f"{zone_label}\nFull ({count}/{capacity})"
            elif status == "busy":
                button_state = "normal"
                button_color = self.AMBER
                label = f"{zone_label}\nBusy ({count}/{capacity})"
            else:
                button_state = "normal"
                button_color = self.BLUE
                label = f"{zone_label}\nOpen ({count}/{capacity})"

            tk.Button(
                panel,
                text=label,
                command=lambda selected=zone_id: self._join_queue(selected),
                font=self.FONT_MEDIUM,
                fg=self.WHITE,
                bg=button_color,
                activebackground=button_color,
                relief="flat",
                cursor="hand2",
                padx=20,
                pady=16,
                state=button_state,
                justify="center",
            ).pack(fill="x", padx=10, pady=6)

        self._btn(panel, "Back to Home", self._show_home, color=self.GRAY).pack(pady=20)

    def _join_queue(self, zone_id):
        try:
            result = api_join_queue(self._current_user["id"], zone_id)
            if result.get("walk_in"):
                session = api_session_enter(self._current_user["face_id"], zone_id)
                self._show_session_started(zone_id, session)
            else:
                self._show_confirmed(zone_id, result["queue_num"], walk_in=False)
        except requests.exceptions.HTTPError as exc:
            if exc.response.status_code == 400:
                messagebox.showwarning("BridgeSpace", "This user is already waiting for that zone.")
            else:
                messagebox.showerror("BridgeSpace", str(exc))
        except Exception as exc:
            messagebox.showerror("BridgeSpace", str(exc))

    def _show_confirmed(self, zone_id, queue_num, walk_in=False):
        self._state = "confirmed"
        self._clear_panel()
        panel = self.panel
        zone_label = dict(ZONES).get(zone_id, zone_id)

        if walk_in:
            tk.Label(panel, text="Walk-In Approved", font=self.FONT_TITLE, fg=self.GREEN, bg=self.BG).pack(pady=(50, 8))
            tk.Label(panel, text=f"Proceed directly to {zone_label}.", font=self.FONT_LARGE, fg=self.WHITE, bg=self.BG).pack(pady=(0, 16))
            tk.Label(panel, text="Your session timer has already started.", font=self.FONT_MEDIUM, fg=self.GRAY, bg=self.BG).pack(pady=(0, 20))
        else:
            tk.Label(panel, text="Queue Joined", font=self.FONT_TITLE, fg=self.GREEN, bg=self.BG).pack(pady=(50, 8))
            card = tk.Frame(panel, bg=self.CARD)
            card.pack(fill="x", padx=20, pady=20)
            tk.Label(card, text=f"Zone: {zone_label}", font=self.FONT_LARGE, fg=self.WHITE, bg=self.CARD).pack(pady=(16, 6))
            tk.Label(card, text="Queue Number", font=self.FONT_MEDIUM, fg=self.GRAY, bg=self.CARD).pack()
            tk.Label(card, text=str(queue_num), font=("Segoe UI", 64, "bold"), fg=self.AMBER, bg=self.CARD).pack(pady=10)
            tk.Label(card, text="Watch the dashboard. Once called, enter within 15 minutes.", font=self.FONT_MEDIUM, fg=self.GRAY, bg=self.CARD, justify="center").pack(pady=(0, 16))

        self._btn(panel, "Done", self._show_home, color=self.BLUE).pack(fill="x", padx=20, pady=10)

    def _show_session_started(self, zone_id, session_info):
        self._state = "session_active"
        if self._session_timer_id is not None:
            self.after_cancel(self._session_timer_id)
            self._session_timer_id = None

        remaining_seconds = self._resolve_remaining_seconds(session_info)
        self._active_session = {
            "session_id": session_info.get("session_id") or session_info.get("id"),
            "zone_id": zone_id,
            "user_id": self._current_user["id"],
            "face_id": self._current_user.get("face_id"),
            "remaining_seconds": remaining_seconds,
            "extensions": session_info.get("extensions", session_info.get("extended", 0)),
            "max_extensions": 2,
            "start_time": time.time(),
        }

        self._clear_panel()
        panel = self.panel
        zone_label = dict(ZONES).get(zone_id, zone_id)

        tk.Label(panel, text="Session Started", font=self.FONT_TITLE, fg=self.GREEN, bg=self.BG).pack(pady=(30, 4))
        tk.Label(panel, text=f"Zone: {zone_label}", font=self.FONT_LARGE, fg=self.WHITE, bg=self.BG).pack(pady=(0, 20))

        timer_card = tk.Frame(panel, bg=self.CARD)
        timer_card.pack(fill="x", padx=20, pady=10)
        tk.Label(timer_card, text="Remaining Time", font=self.FONT_MEDIUM, fg=self.GRAY, bg=self.CARD).pack(pady=(16, 4))
        self.session_timer_lbl = tk.Label(timer_card, text="--:--", font=("Consolas", 56, "bold"), fg=self.GREEN, bg=self.CARD)
        self.session_timer_lbl.pack(pady=10)
        tk.Label(
            timer_card,
            text=f"Extensions used: {self._active_session['extensions']}/{self._active_session['max_extensions']}",
            font=self.FONT_SMALL,
            fg=self.GRAY,
            bg=self.CARD,
        ).pack(pady=(0, 16))

        self.extend_btn = self._btn(panel, "Extend Session", self._extend_session, color=self.AMBER)
        self.extend_btn.pack(fill="x", padx=20, pady=(16, 8))
        if self._active_session["extensions"] >= self._active_session["max_extensions"]:
            self.extend_btn.config(state="disabled", text="No Extensions Remaining")

        tk.Label(
            panel,
            text="The system will warn before expiry and lock the zone if the session expires.",
            font=self.FONT_SMALL,
            fg=self.GRAY,
            bg=self.BG,
            justify="center",
        ).pack(pady=(8, 4))

        self._btn(panel, "Back to Home", self._show_home, color=self.GRAY).pack(fill="x", padx=20, pady=8)
        self._tick_session_timer()

    def _resolve_remaining_seconds(self, session_info):
        if session_info.get("remaining_seconds") is not None:
            return max(0, int(session_info["remaining_seconds"]))
        if session_info.get("expires_at"):
            return max(0, int((datetime.fromisoformat(session_info["expires_at"]) - datetime.now()).total_seconds()))
        return max(60, int(session_info.get("duration_min", 45) * 60))

    def _tick_session_timer(self):
        if self._state != "session_active" or not self._active_session:
            return

        elapsed = time.time() - self._active_session["start_time"]
        remaining = self._active_session["remaining_seconds"] - elapsed
        if remaining <= 0:
            self.session_timer_lbl.config(text="00:00", fg=self.RED)
            return

        if remaining <= 300:
            self.session_timer_lbl.config(fg=self.RED)
        elif remaining <= 600:
            self.session_timer_lbl.config(fg=self.AMBER)
        else:
            self.session_timer_lbl.config(fg=self.GREEN)

        minutes = int(remaining) // 60
        seconds = int(remaining) % 60
        self.session_timer_lbl.config(text=f"{minutes:02d}:{seconds:02d}")
        self._session_timer_id = self.after(1000, self._tick_session_timer)

    def _extend_session(self):
        if not self._active_session or not self._active_session.get("session_id"):
            messagebox.showwarning("BridgeSpace", "There is no active session to extend.")
            return

        try:
            result = api_session_extend(self._active_session["session_id"])
            self._show_session_started(self._active_session["zone_id"], result | {"session_id": self._active_session["session_id"]})
        except requests.exceptions.HTTPError as exc:
            if exc.response.status_code == 400:
                detail = exc.response.json().get("detail", "Unable to extend the session.")
                messagebox.showwarning("BridgeSpace", detail)
            else:
                messagebox.showerror("BridgeSpace", str(exc))
        except Exception as exc:
            messagebox.showerror("BridgeSpace", str(exc))

    def _refresh_cam(self):
        frame = self.cam.get_frame()
        if frame is not None:
            display_frame = frame.copy()

            if MEDIAPIPE_OK and self._state in ("scanning", "register_form"):
                rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
                with mp_face_detection.FaceDetection(min_detection_confidence=0.6) as detector:
                    results = detector.process(rgb)
                for detection in results.detections or []:
                    rel = detection.location_data.relative_bounding_box
                    x = int(rel.xmin * display_frame.shape[1])
                    y = int(rel.ymin * display_frame.shape[0])
                    w = int(rel.width * display_frame.shape[1])
                    h = int(rel.height * display_frame.shape[0])
                    cv2.rectangle(display_frame, (x, y), (x + w, y + h), (34, 197, 94), 3)

            rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            width, height = image.size
            target_width = 560
            image = image.resize((target_width, int(height * target_width / width)), Image.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self.cam_label.config(image=photo)
            self.cam_label.image = photo

        self.after(33, self._refresh_cam)

    def on_close(self):
        self.cam.stop()
        self.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    API_URL = args.api

    app = BridgeSpaceKiosk()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
