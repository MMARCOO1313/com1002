"""
Zone catalog — multi-functional zone definitions for BridgeSpace.

Each zone has a TYPE that determines which sports it can host.
Switching sport changes the number of courts and session duration.

Zone types:
  court → Zones A, B — 2 half-court basketball OR 1 full-court volleyball
  multi → Zones C, D, E — 2 badminton OR 2 pickleball OR 4 table tennis
"""

# ── Sport configuration per zone type ────────────────────────────────────

SPORT_CONFIG = {
    "court": {
        "籃球": {"en": "Basketball", "courts": 2, "duration": 2700, "unit": "半場"},
        "排球": {"en": "Volleyball", "courts": 1, "duration": 2700, "unit": "全場"},
    },
    "multi": {
        "羽毛球": {"en": "Badminton",     "courts": 2, "duration": 2700, "unit": "場"},
        "乒乓球": {"en": "Table Tennis",   "courts": 4, "duration": 1800, "unit": "台"},
        "匹克球": {"en": "Pickleball",     "courts": 2, "duration": 1800, "unit": "場"},
    },
}

# ── Default zone definitions ─────────────────────────────────────────────

DEFAULT_ZONES = [
    {"id": "A", "name_zh": "球場區 1", "name_en": "Court Zone 1",
     "zone_type": "court", "default_sport": "籃球", "capacity": 12},
    {"id": "B", "name_zh": "球場區 2", "name_en": "Court Zone 2",
     "zone_type": "court", "default_sport": "排球", "capacity": 12},
    {"id": "C", "name_zh": "多功能區 1", "name_en": "Multi-Zone 1",
     "zone_type": "multi", "default_sport": "羽毛球", "capacity": 20},
    {"id": "D", "name_zh": "多功能區 2", "name_en": "Multi-Zone 2",
     "zone_type": "multi", "default_sport": "乒乓球", "capacity": 20},
    {"id": "E", "name_zh": "多功能區 3", "name_en": "Multi-Zone 3",
     "zone_type": "multi", "default_sport": "匹克球", "capacity": 16},
]


def _sport_info(zone_type: str, sport: str) -> dict:
    """Look up sport configuration for a zone type."""
    return SPORT_CONFIG.get(zone_type, {}).get(sport, {"courts": 1, "duration": 2700})


def normalize_zone_catalog(conn) -> int:
    """Idempotent: create/update zones to match DEFAULT_ZONES."""
    rows = conn.execute("SELECT * FROM zones").fetchall()
    existing = {row["id"]: dict(row) for row in rows}
    changed = 0

    for zone in DEFAULT_ZONES:
        zid = zone["id"]
        sport = zone["default_sport"]
        info = _sport_info(zone["zone_type"], sport)
        current = existing.get(zid)

        if current is None:
            conn.execute(
                """INSERT INTO zones
                   (id, name_zh, name_en, zone_type, current_sport,
                    capacity, courts, session_duration)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (zid, zone["name_zh"], zone["name_en"],
                 zone["zone_type"], sport,
                 zone["capacity"], info["courts"], info["duration"]),
            )
            changed += 1
        else:
            updates = {}
            if current.get("name_zh") != zone["name_zh"]:
                updates["name_zh"] = zone["name_zh"]
            if current.get("name_en") != zone["name_en"]:
                updates["name_en"] = zone["name_en"]
            if current.get("zone_type") != zone["zone_type"]:
                updates["zone_type"] = zone["zone_type"]
            if current.get("capacity") != zone["capacity"]:
                updates["capacity"] = zone["capacity"]
            # Only set default sport if zone_type changed or sport is missing
            if not current.get("current_sport") or current.get("zone_type") != zone["zone_type"]:
                updates["current_sport"] = sport
                updates["courts"] = info["courts"]
                updates["session_duration"] = info["duration"]

            if updates:
                set_clause = ", ".join(f"{k}=?" for k in updates)
                conn.execute(
                    f"UPDATE zones SET {set_clause} WHERE id=?",
                    (*updates.values(), zid),
                )
                changed += 1

    return changed
