import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]

FILE_EXPECTATIONS = {
    REPO_DIR / "frontend" / "index.html": [
        "BridgeSpace Smart Dashboard",
    ],
    REPO_DIR / "frontend" / "src" / "App.jsx": [
        "AI-Powered Community Sports Hub",
        "Autonomous Operations Dashboard",
        "COM1002 Group 5 | HSUHK",
    ],
    REPO_DIR / "frontend" / "src" / "components" / "CalledAlert.jsx": [
        "AUTOMATIC NEXT CALL",
        "Please proceed to Zone",
        "Entry window: 15 minutes after the call is shown.",
    ],
    REPO_DIR / "frontend" / "src" / "components" / "SessionPanel.jsx": [
        "SESSION TIMERS",
        "All zones are currently open and waiting for the next session.",
        "Extensions:",
    ],
    REPO_DIR / "smartgate" / "kiosk.py": [
        "BridgeSpace SmartGate",
        "Scan Face to Continue",
        "First-Time Registration",
        "Session Started",
    ],
}

BROKEN_TOKENS = ("冒聼", "莽", "鈩", "馃", "脗")


class UserFacingCopyTests(unittest.TestCase):
    def test_key_files_contain_clean_anchor_copy(self):
        for file_path, expected_strings in FILE_EXPECTATIONS.items():
            text = file_path.read_text(encoding="utf-8")
            for expected in expected_strings:
                with self.subTest(file=file_path.name, expected=expected):
                    self.assertIn(expected, text)

    def test_key_files_do_not_contain_known_mojibake_tokens(self):
        for file_path in FILE_EXPECTATIONS:
            text = file_path.read_text(encoding="utf-8")
            for token in BROKEN_TOKENS:
                with self.subTest(file=file_path.name, token=token):
                    self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
