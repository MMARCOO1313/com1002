from __future__ import annotations

import cv2
import numpy as np

try:
    import mediapipe as mp

    mp_face_detection = mp.solutions.face_detection
    MEDIAPIPE_OK = True
except (ImportError, AttributeError):
    mp_face_detection = None
    MEDIAPIPE_OK = False


HAAR_CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)


def detect_single_face(frame: np.ndarray) -> tuple[np.ndarray | None, str | None]:
    boxes = _detect_boxes_with_mediapipe(frame)
    if not boxes:
        boxes = _detect_boxes_with_haar(frame)

    if not boxes:
        return None, "No face detected. Please look directly at the camera."
    if len(boxes) > 1:
        return None, "Multiple faces detected. Please scan one person at a time."

    x, y, w, h = boxes[0]
    crop = frame[y : y + h, x : x + w]
    if crop.size == 0:
        return None, "Face crop failed. Please scan again."
    return crop, None


def encode_face_crop(crop: np.ndarray) -> np.ndarray:
    if crop.ndim == 3:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    else:
        gray = crop.copy()

    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    resized = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    pixels = resized.astype(np.float32).reshape(-1) / 255.0

    hist = cv2.calcHist([gray], [0], None, [64], [0, 256]).astype(np.float32).reshape(-1)
    hist_sum = float(hist.sum()) or 1.0
    hist /= hist_sum

    vector = np.concatenate([pixels, hist])
    norm = float(np.linalg.norm(vector)) or 1.0
    return vector / norm


def face_distance(known_signatures: list[np.ndarray], signature: np.ndarray) -> np.ndarray:
    if not known_signatures:
        return np.array([], dtype=np.float32)
    known = np.vstack([np.asarray(item, dtype=np.float32) for item in known_signatures])
    candidate = np.asarray(signature, dtype=np.float32)
    return np.linalg.norm(known - candidate, axis=1)


def match_face_signature(
    known_signatures: dict[str, np.ndarray], signature: np.ndarray, tolerance: float = 0.55
) -> str | None:
    if not known_signatures:
        return None

    known_ids = list(known_signatures.keys())
    distances = face_distance(list(known_signatures.values()), signature)
    if distances.size == 0:
        return None

    best_idx = int(np.argmin(distances))
    if float(distances[best_idx]) <= tolerance:
        return known_ids[best_idx]
    return None


def _detect_boxes_with_mediapipe(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    if not MEDIAPIPE_OK:
        return []

    height, width = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    with mp_face_detection.FaceDetection(min_detection_confidence=0.6) as detector:
        results = detector.process(rgb)

    boxes = []
    for detection in results.detections or []:
        rel = detection.location_data.relative_bounding_box
        x = max(0, int(rel.xmin * width))
        y = max(0, int(rel.ymin * height))
        w = min(width - x, int(rel.width * width))
        h = min(height - y, int(rel.height * height))
        if w > 0 and h > 0:
            boxes.append((x, y, w, h))
    return boxes


def _detect_boxes_with_haar(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    detections = HAAR_CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
    return [tuple(int(value) for value in detection) for detection in detections]
