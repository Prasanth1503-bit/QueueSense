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


KNOWN_VIDEO_MAP = {
    "58a9318f429fbe0db31841804568342d6872ad898bdb5a7615c01f5eb45cf165": "video1.mp4",
    "753176dd33e141d4b96214983f2f2253950f483c70802ff1ddd9021b4c43f377": "video2.mp4",
    "be712a55bfceced560e4af43048eebdaa8a8f5ec4b68d2eb1fdcfac9378b44b0": "video3.mp4",
    "bf935c608781228dca9123dd7cf4a7ac447ad479a1978c2c08b67133383fa56e": "video4.mp4",
    "01212527f8d3c6f983e42d07ea1e738e4978a448485d5a96313d177b50cdc485": "video5.mp4",
    "fbafb399bc83ab60a2c8b19217cc164a3ac43ed7eb7961af02c35391fb4d7dd0": "video6.mp4",
    "771b447877d2d149fc47be59023768b01b0dd22ccef83a3e5538592c7dc19ecb": "video7.mp4",
    "2df6b883623d615388f377892585ea0530e1be2afb8def6db1c3d86b3ef9ed21": "Laptop Camera",
    "87b1810ef2d149290492e928a99568cda21c9b575bc8f68a4e4e9fb25289388d": "Laptop Camera (1)",
    "4d15f7c1fd5bef1fd404c3102179db7fcebee8ec605dbef9e58cad71935a47c0": "USB Webcam",
    "d9423b63ea3e845453202e4e86653428f9a3f2001b1183c24f4aa074872b38cd": "Android Phone Camera",
}


def resolve_video_display_name(video_hash, video_name=None):
    if video_name and str(video_name).strip() and not str(video_name).strip().lower().startswith(("video ", "unknown")):
        return str(video_name).strip()
    if video_hash and video_hash in KNOWN_VIDEO_MAP:
        return KNOWN_VIDEO_MAP[video_hash]
    if video_hash and "camera" in str(video_hash):
        return "Laptop Camera" if "0" in str(video_hash) else "USB Webcam"
    if video_name and str(video_name).strip():
        return str(video_name).strip()
    return "Laptop Camera" if not video_hash else f"Video Session ({video_hash[:8]})"


def save_queue_statistics(statistics, save_history=False, video_hash=None, session_id=None, video_name=None):
    """Update current status and optionally append history with video identity."""
    if not isinstance(statistics, dict):
        raise TypeError("statistics must be a dictionary")
    timestamp = current_timestamp()
    resolved_video_name = resolve_video_display_name(video_hash, video_name)
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
                     video_hash, session_id, resolved_video_name))


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
    results = [dict(row) for row in rows]
    for r in results:
        r["video_name"] = resolve_video_display_name(r.get("video_hash"), r.get("video_name"))
    return results


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


def get_historical_videos(hours=None):
    with get_connection() as connection:
        if hours is not None:
            cutoff = get_cutoff_timestamp(hours)
            rows = connection.execute("""SELECT video_hash,
                MAX(video_name) AS video_name,
                MIN(recorded_at) AS first_recorded_at, MAX(recorded_at) AS last_recorded_at,
                COUNT(*) AS samples, COUNT(DISTINCT queue_name) AS queue_count
                FROM queue_history WHERE recorded_at >= ? AND video_hash IS NOT NULL
                GROUP BY video_hash ORDER BY last_recorded_at DESC""", (cutoff,)).fetchall()
        else:
            rows = connection.execute("""SELECT video_hash,
                MAX(video_name) AS video_name,
                MIN(recorded_at) AS first_recorded_at, MAX(recorded_at) AS last_recorded_at,
                COUNT(*) AS samples, COUNT(DISTINCT queue_name) AS queue_count
                FROM queue_history WHERE video_hash IS NOT NULL
                GROUP BY video_hash ORDER BY last_recorded_at DESC""").fetchall()

    results = []
    for row in rows:
        d = dict(row)
        d["video_name"] = resolve_video_display_name(d["video_hash"], d.get("video_name"))
        results.append(d)
    return results


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


# ===== Arduino/RFID integration tables and functions =====
def initialize_integration_tables():
    with get_connection() as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS attendance_events (id INTEGER PRIMARY KEY AUTOINCREMENT, card_uid TEXT NOT NULL, roll_number TEXT, student_name TEXT, event_type TEXT NOT NULL, event_time TEXT NOT NULL)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_attendance_events_time ON attendance_events(event_time)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_attendance_events_roll ON attendance_events(roll_number)")
        connection.execute("CREATE TABLE IF NOT EXISTS queue_alert_limits (queue_name TEXT PRIMARY KEY, limit_people INTEGER NOT NULL DEFAULT 5, updated_at TEXT NOT NULL)")
        for name, limit_value in (("student", 3), ("faculty", 3), ("scholar", 3)):
            connection.execute("INSERT OR IGNORE INTO queue_alert_limits(queue_name,limit_people,updated_at) VALUES(?,?,?)", (name,limit_value,current_timestamp()))

def save_attendance_event(card_uid, roll_number, student_name, event_type, event_time=None):
    uid=str(card_uid).strip().lower(); event_type=str(event_type).strip().upper()
    if not uid: raise ValueError("Card UID cannot be empty")
    if event_type not in ("ENTRY","EXIT","UNKNOWN"): raise ValueError("Invalid attendance event type")
    with get_connection() as connection:
        cur=connection.execute("INSERT INTO attendance_events(card_uid,roll_number,student_name,event_type,event_time) VALUES(?,?,?,?,?)", (uid,str(roll_number or "").strip(),str(student_name or "").strip(),event_type,event_time or current_timestamp()))
        return cur.lastrowid

def get_attendance_events(limit=200, search=None):
    limit=max(1,min(int(limit),5000)); query="SELECT id,card_uid,roll_number,student_name,event_type,event_time FROM attendance_events"; params=[]
    if search and str(search).strip():
        term="%"+str(search).strip()+"%"; query += " WHERE student_name LIKE ? OR roll_number LIKE ? OR card_uid LIKE ? OR event_type LIKE ?"; params.extend([term]*4)
    query += " ORDER BY id DESC LIMIT ?"; params.append(limit)
    with get_connection() as connection: rows=connection.execute(query,params).fetchall()
    return [dict(row) for row in rows]

def get_attendance_summary():
    with get_connection() as connection:
        total=connection.execute("SELECT COUNT(*) n FROM attendance_events").fetchone()["n"]
        entries=connection.execute("SELECT COUNT(*) n FROM attendance_events WHERE event_type='ENTRY'").fetchone()["n"]
        exits=connection.execute("SELECT COUNT(*) n FROM attendance_events WHERE event_type='EXIT'").fetchone()["n"]
        students=connection.execute("SELECT COUNT(DISTINCT roll_number) n FROM attendance_events WHERE roll_number IS NOT NULL AND roll_number!='' AND event_type IN ('ENTRY','EXIT')").fetchone()["n"]
    return {"total_events":total,"total_entries":entries,"total_exits":exits,"unique_students":students}

def get_queue_alert_limits():
    with get_connection() as connection: rows=connection.execute("SELECT queue_name,limit_people,updated_at FROM queue_alert_limits ORDER BY queue_name").fetchall()
    return {r["queue_name"]:{"limit_people":r["limit_people"],"updated_at":r["updated_at"]} for r in rows}

def save_queue_alert_limit(queue_name, limit_people):
    name=str(queue_name).strip(); limit_value=int(limit_people)
    if not name: raise ValueError("Queue name cannot be empty")
    if limit_value<0: raise ValueError("Limit cannot be negative")
    stamp=current_timestamp()
    with get_connection() as connection:
        connection.execute("INSERT INTO queue_alert_limits(queue_name,limit_people,updated_at) VALUES(?,?,?) ON CONFLICT(queue_name) DO UPDATE SET limit_people=excluded.limit_people,updated_at=excluded.updated_at",(name,limit_value,stamp))
    return {"queue_name":name,"limit_people":limit_value,"updated_at":stamp}

initialize_integration_tables()
