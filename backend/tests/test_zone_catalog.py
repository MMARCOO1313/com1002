import sqlite3
import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    import zone_catalog
except ModuleNotFoundError as exc:
    zone_catalog = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


EXPECTED_ZONES = [
    {
        "id": "A",
        "name_zh": "羽毛球 / 籃球區",
        "name_en": "Badminton / Basketball",
        "capacity": 30,
        "session_duration": 2700,
    },
    {
        "id": "B",
        "name_zh": "匹克球 / 乒乓球區",
        "name_en": "Pickleball / Table Tennis",
        "capacity": 25,
        "session_duration": 1800,
    },
    {
        "id": "C",
        "name_zh": "社區休閒區",
        "name_en": "Community Leisure",
        "capacity": 40,
        "session_duration": 0,
    },
    {
        "id": "D",
        "name_zh": "新興運動區",
        "name_en": "Emerging Sports",
        "capacity": 25,
        "session_duration": 2700,
    },
]

GARBLED_ROWS = [
    ("A", "莽戮陆忙炉聸莽聬聝 / 莽卤聝莽聬聝氓聧聙", "Badminton / Basketball", 30, 2700),
    ("B", "氓聦鹿氓聟聥莽聬聝 / 盲鹿聮盲鹿聯莽聬聝氓聧聙", "Pickleball / Table Tennis", 25, 1800),
    ("C", "莽陇戮氓聧聙盲录聭茅聳聮氓聧聙", "Community Leisure", 40, 0),
    ("D", "忙聳掳猫聢聢茅聛聥氓聥聲氓聧聙", "Emerging Sports", 25, 2700),
]


def create_zone_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE zones (
            id TEXT PRIMARY KEY,
            name_zh TEXT NOT NULL,
            name_en TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            current_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'open',
            session_duration INTEGER DEFAULT 2700
        );
        """
    )


class ZoneCatalogTests(unittest.TestCase):
    def require_module(self):
        if zone_catalog is None:
            self.fail(f"Expected backend zone_catalog module: {IMPORT_ERROR}")

    def test_default_zones_match_v2_catalog(self):
        self.require_module()
        self.assertEqual(zone_catalog.DEFAULT_ZONES, EXPECTED_ZONES)

    def test_normalize_zone_catalog_repairs_existing_rows(self):
        self.require_module()

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        create_zone_table(conn)
        conn.executemany(
            """
            INSERT INTO zones (id, name_zh, name_en, capacity, session_duration)
            VALUES (?, ?, ?, ?, ?)
            """,
            GARBLED_ROWS,
        )

        changed = zone_catalog.normalize_zone_catalog(conn)
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, name_zh, name_en, capacity, session_duration
                FROM zones
                ORDER BY id
                """
            ).fetchall()
        ]

        self.assertGreaterEqual(changed, 1)
        self.assertEqual(rows, EXPECTED_ZONES)


if __name__ == "__main__":
    unittest.main()
