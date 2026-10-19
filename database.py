import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

DATABASE_PATH = Path(__file__).resolve().parent / "queuesense.db"


def get_connection():
    connection = sqlite3.connect(str(DATABASE_PATH), timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def current_timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get_cutoff_timestamp(hours):
    hours = max(1, min(int(hours), 24 * 365))
    return (datetime.now().astimezone() - timedelta(hours=hours)).isoformat(timespec="seconds")


def initialize_database():
    """Create missing tables and safely migrate columns without deleting data."""
    with get_connection() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS queue_status (
            queue_name TEXT PRIMARY KEY,
            occupancy INTEGER NOT NULL DEFAULT 0,
            total_entries INTEGER NOT NULL DEFAULT 0,
            total_exits INTEGER NOT NULL DEFAULT 0,
            average_wait_seconds REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS queue_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_name TEXT NOT NULL,
            occupancy INTEGER NOT NULL,
            total_entries INTEGER NOT NULL,
            total_exits INTEGER NOT NULL,
            average_wait_seconds REAL NOT NULL,
            recorded_at TEXT NOT NULL
        )""")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(queue_history)").fetchall()}
        for name, sql_type in (("video_hash", "TEXT"), ("session_id", "TEXT"), ("video_name", "TEXT")):
            if name not in columns:
                connection.execute(f"ALTER TABLE queue_history ADD COLUMN {name} {sql_type}")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_queue_history_recorded_at ON queue_history(recorded_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_queue_history_name_time ON queue_history(queue_name, recorded_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_queue_history_video_queue ON queue_history(video_hash, queue_name)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_queue_history_session ON queue_history(session_id)")


def save_queue_statistics(statistics, save_history=False, video_hash=None, session_id=None, video_name=None):
    """Update current status and optionally append history with video identity."""
    if not isinstance(statistics, dict):
        raise TypeError("statistics must be a dictionary")
    timestamp = current_timestamp()
    with get_connection() as connection:
        for queue_name, values in statistics.items():
            occupancy = max(0, int(values.get("occupancy", 0) or 0))
            entries = max(0, int(values.get("entries", 0) or 0))
            exits = max(0, int(values.get("exits", 0) or 0))
            average_wait = max(0.0, float(values.get("average_wait_seconds", 0) or 0))
            connection.execute("""INSERT INTO queue_status
                (queue_name, occupancy, total_entries, total_exits, average_wait_seconds, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(queue_name) DO UPDATE SET
                    occupancy=excluded.occupancy,
                    total_entries=excluded.total_entries,
                    total_exits=excluded.total_exits,
                    average_wait_seconds=excluded.average_wait_seconds,
                    updated_at=excluded.updated_at""",
                (queue_name, occupancy, entries, exits, average_wait, timestamp))
            if save_history:
                connection.execute("""INSERT INTO queue_history
                    (queue_name, occupancy, total_entries, total_exits, average_wait_seconds,
                     recorded_at, video_hash, session_id, video_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (queue_name, occupancy, entries, exits, average_wait, timestamp,
                     video_hash, session_id, video_name))


def get_queue_statistics():
    with get_connection() as connection:
        rows = connection.execute("""SELECT queue_name, occupancy, total_entries, total_exits,
            average_wait_seconds, updated_at FROM queue_status ORDER BY queue_name""").fetchall()
    return {row["queue_name"]: {"occupancy": row["occupancy"], "entries": row["total_entries"],
            "exits": row["total_exits"], "average_wait_seconds": row["average_wait_seconds"],
            "updated_at": row["updated_at"]} for row in rows}


def get_queue_history(queue_name=None, hours=24, limit=1000, video_hash=None, session_id=None):
    cutoff = get_cutoff_timestamp(hours)
    limit = max(1, min(int(limit), 10000))
    conditions, params = ["recorded_at >= ?"], [cutoff]
    for field, value in (("queue_name", queue_name), ("video_hash", video_hash), ("session_id", session_id)):
        if value:
            conditions.append(f"{field} = ?")
            params.append(value)
    params.append(limit)
    query = f"""SELECT id, queue_name, occupancy, total_entries, total_exits,
        average_wait_seconds, recorded_at, video_hash, session_id, video_name
        FROM queue_history WHERE {' AND '.join(conditions)} ORDER BY recorded_at ASC, id ASC LIMIT ?"""
    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_queue_history_summary(hours=24, video_hash=None, session_id=None):
    conditions, params = ["recorded_at >= ?"], [get_cutoff_timestamp(hours)]
    for field, value in (("video_hash", video_hash), ("session_id", session_id)):
        if value:
            conditions.append(f"{field} = ?")
            params.append(value)
    query = f"""SELECT queue_name, MAX(occupancy) AS peak_occupancy,
        AVG(occupancy) AS average_occupancy, COUNT(*) AS samples
        FROM queue_history WHERE {' AND '.join(conditions)} GROUP BY queue_name ORDER BY queue_name"""
    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return {row["queue_name"]: {"peak_occupancy": int(row["peak_occupancy"] or 0),
        "average_occupancy": round(float(row["average_occupancy"] or 0), 2),
        "samples": int(row["samples"])} for row in rows}


def get_historical_videos(hours=24):
    cutoff = get_cutoff_timestamp(hours)
    with get_connection() as connection:
        rows = connection.execute("""SELECT video_hash,
            COALESCE(MAX(video_name), 'Unknown video') AS video_name,
            MIN(recorded_at) AS first_recorded_at, MAX(recorded_at) AS last_recorded_at,
            COUNT(*) AS samples, COUNT(DISTINCT queue_name) AS queue_count
            FROM queue_history WHERE recorded_at >= ? AND video_hash IS NOT NULL
            GROUP BY video_hash ORDER BY last_recorded_at DESC""", (cutoff,)).fetchall()
    return [dict(row) for row in rows]


def get_historical_queue_names(video_hash=None, hours=24):
    cutoff = get_cutoff_timestamp(hours)
    with get_connection() as connection:
        if video_hash:
            rows = connection.execute("""SELECT DISTINCT queue_name FROM queue_history
                WHERE recorded_at >= ? AND video_hash = ? ORDER BY queue_name""", (cutoff, video_hash)).fetchall()
        else:
            rows = connection.execute("""SELECT DISTINCT queue_name FROM queue_history
                WHERE recorded_at >= ? ORDER BY queue_name""", (cutoff,)).fetchall()
    return [row["queue_name"] for row in rows]


def reset_queue_status():
    """Clear only current status; retain historical records."""
    with get_connection() as connection:
        connection.execute("DELETE FROM queue_status")


initialize_database()
