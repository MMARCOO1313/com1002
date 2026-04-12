DEFAULT_ZONES = [
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


def seed_default_zones(conn) -> int:
    conn.executemany(
        """
        INSERT INTO zones (id, name_zh, name_en, capacity, session_duration)
        VALUES (:id, :name_zh, :name_en, :capacity, :session_duration)
        """,
        DEFAULT_ZONES,
    )
    return len(DEFAULT_ZONES)


def normalize_zone_catalog(conn) -> int:
    rows = conn.execute(
        """
        SELECT id, name_zh, name_en, capacity, session_duration
        FROM zones
        """
    ).fetchall()
    existing = {row["id"]: dict(row) for row in rows}
    changed = 0

    for zone in DEFAULT_ZONES:
        current = existing.get(zone["id"])
        if current is None:
            conn.execute(
                """
                INSERT INTO zones (id, name_zh, name_en, capacity, session_duration)
                VALUES (:id, :name_zh, :name_en, :capacity, :session_duration)
                """,
                zone,
            )
            changed += 1
            continue

        if any(current[key] != zone[key] for key in ("name_zh", "name_en", "capacity", "session_duration")):
            conn.execute(
                """
                UPDATE zones
                SET name_zh=:name_zh,
                    name_en=:name_en,
                    capacity=:capacity,
                    session_duration=:session_duration
                WHERE id=:id
                """,
                zone,
            )
            changed += 1

    return changed
