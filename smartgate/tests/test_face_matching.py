import sys
import unittest
from pathlib import Path

import numpy as np


SMARTGATE_DIR = Path(__file__).resolve().parents[1]
if str(SMARTGATE_DIR) not in sys.path:
    sys.path.insert(0, str(SMARTGATE_DIR))

try:
    import face_matching
except ModuleNotFoundError as exc:
    face_matching = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class FaceMatchingTests(unittest.TestCase):
    def require_module(self):
        if face_matching is None:
            self.fail(f"Expected smartgate face_matching module: {IMPORT_ERROR}")

    def test_encode_face_crop_returns_normalized_signature(self):
        self.require_module()

        crop = np.tile(np.arange(96, dtype=np.uint8), (96, 1))
        crop = np.stack([crop, crop, crop], axis=-1)
        signature = face_matching.encode_face_crop(crop)

        self.assertEqual(signature.shape, (128,))
        self.assertAlmostEqual(float(np.linalg.norm(signature)), 1.0, places=5)

    def test_match_face_signature_works_without_face_recognition(self):
        self.require_module()

        base = np.full((96, 96, 3), 90, dtype=np.uint8)
        similar = np.full((96, 96, 3), 94, dtype=np.uint8)
        different = np.full((96, 96, 3), 10, dtype=np.uint8)

        known = {
            "FACE-001": face_matching.encode_face_crop(base),
        }

        self.assertEqual(
            face_matching.match_face_signature(
                known,
                face_matching.encode_face_crop(similar),
                tolerance=0.55,
            ),
            "FACE-001",
        )
        self.assertIsNone(
            face_matching.match_face_signature(
                known,
                face_matching.encode_face_crop(different),
                tolerance=0.55,
            )
        )


if __name__ == "__main__":
    unittest.main()
