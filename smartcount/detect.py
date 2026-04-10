"""
SmartCount — Real-time AI People Counter
Uses YOLOv8n with MPS (M1/M2) or CPU on Windows.
Pushes live occupancy counts to the BridgeSpace backend.

Run (webcam):   python detect.py --zone A --show
Run (video):    python detect.py --zone A --cam path/to/video.mp4 --show
Run (demo):     python detect.py --zone A --demo --show
"""

import cv2
import argparse
import time
import requests
import threading
from collections import deque
from ultralytics import YOLO

# ─── Config ──────────────────────────────────────────────────────────────────

MODEL_NAME = "yolov8n.pt"   # nano = fastest; switch to yolov8s.pt for better accuracy
PUSH_INTERVAL = 1.0         # seconds between API pushes
SMOOTH_WINDOW = 10          # frames for rolling-average count (reduces flicker)
CONF_THRESHOLD = 0.45
PERSON_CLASS = 0

# ─── Argument parsing ─────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="BridgeSpace SmartCount")
parser.add_argument("--zone",   default="A",                   help="Zone ID (A/B/C/D)")
parser.add_argument("--api",    default="http://localhost:8000", help="Backend API URL")
parser.add_argument("--cam",    default="0",                   help="Camera index (0) or path to video file")
parser.add_argument("--show",   action="store_true",           help="Show detection window")
parser.add_argument("--demo",   action="store_true",           help="Demo mode: auto-simulate people count")
args = parser.parse_args()


def push_count(count: int):
    """Push occupancy count to backend (non-blocking)."""
    try:
        requests.post(
            f"{args.api}/zones/occupancy",
            json={"zone_id": args.zone, "count": count},
            timeout=2
        )
    except Exception as e:
        print(f"[SmartCount] API push failed: {e}")


def run_demo():
    """Demo mode: simulate people count with a sine-wave pattern (no camera needed)."""
    import math, random
    print(f"[SmartCount] DEMO MODE — Zone {args.zone}: simulating occupancy changes")
    last_push = time.time()
    t = 0
    while True:
        # Simulate realistic crowd flow: sine wave with noise
        base = 12 + 10 * math.sin(t / 30)
        count = max(0, int(base + random.uniform(-2, 2)))
        if args.show:
            frame = _make_demo_frame(count)
            cv2.imshow(f"SmartCount — Zone {args.zone} [DEMO]", frame)
            if cv2.waitKey(33) & 0xFF == ord("q"):
                break
        now = time.time()
        if now - last_push >= PUSH_INTERVAL:
            push_count(count)
            print(f"[SmartCount] Zone {args.zone}: {count} people (demo)")
            last_push = now
        time.sleep(0.1)
        t += 1
    cv2.destroyAllWindows()


def _make_demo_frame(count: int):
    """Generate a synthetic frame showing stick-figure crowd."""
    h, w = 480, 640
    frame = __import__("numpy").zeros((h, w, 3), dtype=__import__("numpy").uint8)
    frame[:] = (20, 20, 40)
    cv2.putText(frame, f"SmartCount DEMO - Zone {args.zone}",
                (20, 40), cv2.FONT_HERSHEY_DUPLEX, 0.8, (0, 230, 120), 2)
    cv2.putText(frame, f"People detected: {count}",
                (20, 90), cv2.FONT_HERSHEY_DUPLEX, 1.2, (255, 200, 0), 2)
    # Draw simple circles representing people
    import random, math
    random.seed(count * 7)
    for i in range(count):
        x = random.randint(60, w - 60)
        y = random.randint(140, h - 60)
        cv2.circle(frame, (x, y), 18, (0, 180, 255), -1)
        cv2.circle(frame, (x, y - 28), 10, (200, 160, 100), -1)
    return frame


def run():
    if args.demo:
        run_demo()
        return

    model = YOLO(MODEL_NAME)

    # Use MPS on M1/M2, CUDA on Windows GPU, else CPU
    import torch
    if torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"
    print(f"[SmartCount] Using device: {device}")
    model.to(device)

    # Support both camera index (int) and video file path (str)
    cam_src = int(args.cam) if args.cam.isdigit() else args.cam
    cap = cv2.VideoCapture(cam_src)
    if not cap.isOpened():
        print(f"[SmartCount] ERROR: Cannot open source '{args.cam}'")
        print("Tip: use --demo for no-camera demo, or --cam path/to/video.mp4")
        return

    count_buffer = deque(maxlen=SMOOTH_WINDOW)
    last_push = time.time()
    last_count = 0

    print(f"[SmartCount] Zone {args.zone} — monitoring started. Press Q to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            # Loop video file when it ends
            if isinstance(cam_src, str):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            break

        # ── Run YOLOv8 detection ──────────────────────────────────────────
        results = model(frame, classes=[PERSON_CLASS], conf=CONF_THRESHOLD,
                        verbose=False, device=device)

        raw_count = 0
        annotated = frame.copy()

        for r in results:
            boxes = r.boxes
            raw_count = len(boxes)
            if args.show:
                # Draw bounding boxes
                for box in boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 200, 100), 2)
                    cv2.putText(annotated, f"{conf:.2f}", (x1, y1 - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 100), 1)

        # ── Rolling average to smooth count ──────────────────────────────
        count_buffer.append(raw_count)
        smooth_count = round(sum(count_buffer) / len(count_buffer))

        # ── Display overlay ───────────────────────────────────────────────
        if args.show:
            overlay_h, overlay_w = 100, 280
            cv2.rectangle(annotated, (10, 10), (10 + overlay_w, 10 + overlay_h),
                          (20, 20, 20), -1)
            cv2.putText(annotated, f"Zone {args.zone}  People: {smooth_count}",
                        (20, 45), cv2.FONT_HERSHEY_DUPLEX, 0.9, (0, 230, 120), 2)
            cv2.putText(annotated, f"Raw: {raw_count}  FPS: {cap.get(cv2.CAP_PROP_FPS):.0f}",
                        (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (160, 160, 160), 1)
            cv2.imshow(f"SmartCount — Zone {args.zone}", annotated)

        # ── Push to API ───────────────────────────────────────────────────
        now = time.time()
        if now - last_push >= PUSH_INTERVAL and smooth_count != last_count:
            threading.Thread(target=push_count, args=(smooth_count,), daemon=True).start()
            last_count = smooth_count
            last_push = now
            print(f"[SmartCount] Zone {args.zone}: {smooth_count} people")

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("[SmartCount] Stopped.")


if __name__ == "__main__":
    run()
