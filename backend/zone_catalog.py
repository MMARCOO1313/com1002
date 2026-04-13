"""
Zone catalog — unit-based multi-functional zone system for BridgeSpace.

Every zone has **4 units** of space.  Each sport consumes a fixed number
of units, and a zone can host **mixed** sports simultaneously as long as
the total does not exceed 4 units.

Unit cost table (defined by real court-size ratios):
  乒乓球   1 unit   (≈ 7m × 3.5m = 24.5 ㎡)
  羽毛球   2 units  (≈ 13.4m × 6.1m)
  匹克球   2 units  (≈ 13.4m × 6.1m)
  籃球     4 units  (≈ 28m × 15m full court)
  排球     4 units  (≈ 24m × 15m with runoff)

Area calculation (10 zones × 4 units × 24.5 ㎡):
  Raw court area   = 10 × 98 = 980 ㎡
  With circulation (30 %)     ≈ 1,274 ㎡
  Bridge total     = 288 m × 14 m = 4,032 ㎡
  Utilisation      ≈ 31.6 %
"""

# ── Sport configuration ─────────────────────────────────────────────────────

ZONE_TOTAL_UNITS = 4           # every zone = 4 units of space
UNIT_AREA_SQM    = 24.5        # 1 unit ≈ 24.5 ㎡

SPORT_CONFIG = {
    "乒乓球": {
        "en": "Table Tennis", "icon": "🏓", "unit_cost": 1,
        "duration": 1800, "unit_name": "台",
        "equipment": ["table"],
    },
    "羽毛球": {
        "en": "Badminton", "icon": "🏸", "unit_cost": 2,
        "duration": 2700, "unit_name": "場",
        "equipment": ["net"],
    },
    "匹克球": {
        "en": "Pickleball", "icon": "🏓", "unit_cost": 2,
        "duration": 1800, "unit_name": "場",
        "equipment": ["net"],
    },
    "籃球": {
        "en": "Basketball", "icon": "🏀", "unit_cost": 4,
        "duration": 2700, "unit_name": "全場",
        "equipment": ["hoop"],
    },
    "排球": {
        "en": "Volleyball", "icon": "🏐", "unit_cost": 4,
        "duration": 2700, "unit_name": "全場",
        "equipment": ["net"],
    },
}

# ── Default zone definitions (10 zones) ─────────────────────────────────────

DEFAULT_ZONES = [
    {"id": "A",  "name_zh": "場地 A",  "name_en": "Zone A",  "capacity": 20,
     "default_alloc": [{"sport": "籃球", "count": 1}]},
    {"id": "B",  "name_zh": "場地 B",  "name_en": "Zone B",  "capacity": 20,
     "default_alloc": [{"sport": "排球", "count": 1}]},
    {"id": "C",  "name_zh": "場地 C",  "name_en": "Zone C",  "capacity": 16,
     "default_alloc": [{"sport": "羽毛球", "count": 2}]},
    {"id": "D",  "name_zh": "場地 D",  "name_en": "Zone D",  "capacity": 16,
     "default_alloc": [{"sport": "乒乓球", "count": 4}]},
    {"id": "E",  "name_zh": "場地 E",  "name_en": "Zone E",  "capacity": 16,
     "default_alloc": [{"sport": "匹克球", "count": 2}]},
    {"id": "F",  "name_zh": "場地 F",  "name_en": "Zone F",  "capacity": 16,
     "default_alloc": [{"sport": "羽毛球", "count": 1}, {"sport": "乒乓球", "count": 2}]},
    {"id": "G",  "name_zh": "場地 G",  "name_en": "Zone G",  "capacity": 16,
     "default_alloc": [{"sport": "乒乓球", "count": 4}]},
    {"id": "H",  "name_zh": "場地 H",  "name_en": "Zone H",  "capacity": 20,
     "default_alloc": [{"sport": "籃球", "count": 1}]},
    {"id": "I",  "name_zh": "場地 I",  "name_en": "Zone I",  "capacity": 16,
     "default_alloc": [{"sport": "匹克球", "count": 1}, {"sport": "乒乓球", "count": 2}]},
    {"id": "J",  "name_zh": "場地 J",  "name_en": "Zone J",  "capacity": 16,
     "default_alloc": [{"sport": "羽毛球", "count": 2}]},
]

# ── Pre-set allocation templates ────────────────────────────────────────────

ALLOC_PRESETS = {
    "全籃球":       [{"sport": "籃球", "count": 1}],
    "全排球":       [{"sport": "排球", "count": 1}],
    "全羽毛球":     [{"sport": "羽毛球", "count": 2}],
    "全乒乓球":     [{"sport": "乒乓球", "count": 4}],
    "全匹克球":     [{"sport": "匹克球", "count": 2}],
    "羽毛球+乒乓球": [{"sport": "羽毛球", "count": 1}, {"sport": "乒乓球", "count": 2}],
    "匹克球+乒乓球": [{"sport": "匹克球", "count": 1}, {"sport": "乒乓球", "count": 2}],
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def validate_allocation(alloc: list[dict]) -> tuple[bool, str]:
    """Check that an allocation list fits within ZONE_TOTAL_UNITS."""
    total = 0
    for item in alloc:
        sport = item.get("sport")
        count = item.get("count", 0)
        if sport not in SPORT_CONFIG:
            return False, f"未知運動: {sport}"
        if count < 0:
            return False, f"數量不可為負: {sport}"
        total += SPORT_CONFIG[sport]["unit_cost"] * count
    if total > ZONE_TOTAL_UNITS:
        return False, f"超出空間限制: 需要 {total} 單位，最多 {ZONE_TOTAL_UNITS} 單位"
    return True, "OK"


def alloc_to_courts(alloc: list[dict]) -> int:
    """Total number of individual courts/tables from an allocation."""
    return sum(a.get("count", 0) for a in alloc)


def alloc_units_used(alloc: list[dict]) -> int:
    """Total units consumed by an allocation."""
    return sum(SPORT_CONFIG[a["sport"]]["unit_cost"] * a["count"] for a in alloc)


def alloc_equipment_set(alloc: list[dict]) -> set:
    """Set of equipment types needed for an allocation."""
    equip = set()
    for a in alloc:
        cfg = SPORT_CONFIG.get(a["sport"], {})
        for e in cfg.get("equipment", []):
            if a["count"] > 0:
                equip.add(e)
    return equip


# ── Database normalisation ──────────────────────────────────────────────────

def normalize_zone_catalog(conn) -> int:
    """Idempotent: create/update zones to match DEFAULT_ZONES."""
    import json as _json
    rows = conn.execute("SELECT * FROM zones").fetchall()
    existing = {row["id"]: dict(row) for row in rows}
    changed = 0

    for zone in DEFAULT_ZONES:
        zid = zone["id"]
        alloc = zone["default_alloc"]
        courts = alloc_to_courts(alloc)
        # Use the first sport's duration as zone default
        first_sport = alloc[0]["sport"]
        duration = SPORT_CONFIG[first_sport]["duration"]
        alloc_json = _json.dumps(alloc, ensure_ascii=False)

        current = existing.get(zid)
        if current is None:
            conn.execute(
                """INSERT INTO zones
                   (id, name_zh, name_en, zone_type, current_sport,
                    capacity, courts, session_duration, allocation)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (zid, zone["name_zh"], zone["name_en"],
                 "multi", first_sport,
                 zone["capacity"], courts, duration, alloc_json),
            )
            changed += 1
        else:
            # Only update metadata, preserve runtime state
            updates = {}
            if current.get("name_zh") != zone["name_zh"]:
                updates["name_zh"] = zone["name_zh"]
            if current.get("name_en") != zone["name_en"]:
                updates["name_en"] = zone["name_en"]
            if not current.get("allocation"):
                updates["allocation"] = alloc_json
                updates["courts"] = courts
                updates["current_sport"] = first_sport
                updates["session_duration"] = duration
            if updates:
                set_clause = ", ".join(f"{k}=?" for k in updates)
                conn.execute(
                    f"UPDATE zones SET {set_clause} WHERE id=?",
                    (*updates.values(), zid),
                )
                changed += 1

    return changed
