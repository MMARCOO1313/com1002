"""
SmartCount — Real-time AI People Counter
Uses YOLOv8n with Apple MPS (M1/M2) acceleration.
Pushes live occupancy counts to the BridgeSpace backend.

Run:  python detect.py --zone A --api http://localhost:8000
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
parser.add_argument("--cam",    default=0, type=int,           help="Camera index (default 0 = built-in)")
parser.add_argument("--show",   action="store_true",           help="Show detection window")
parser.add_argument("--demo",   action="store_true",           help="Demo mode: use sample video")
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


def run():
    model = YOLO(MODEL_NAME)

    # Use MPS on M1/M2 for hardware acceleration
    import torch
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[SmartCount] Using device: {device}")
    model.to(device)

    cap = cv2.VideoCapture(args.cam)
    if not cap.isOpened():
        print("[SmartCount] ERROR: Cannot open camera")
        return

    count_buffer = deque(maxlen=SMOOTH_WINDOW)
    last_push = time.time()
    last_count = 0

    print(f"[SmartCount] Zone {args.zone} — monitoring started. Press Q to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
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
