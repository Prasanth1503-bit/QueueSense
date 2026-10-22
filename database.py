import os
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

try:
    import psycopg2
    import psycopg2.pool
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass


def get_postgres_url():
    """Dynamically resolve the PostgreSQL / Supabase URL from env or Streamlit secrets."""
    url = (
        os.getenv("DATABASE_URL")
        or os.getenv("SUPABASE_DB_URL")
        or os.getenv("POSTGRES_URL")
        or ""
    ).strip()
    if not url:
        try:
            import streamlit as _st
            try:
                if "DATABASE_URL" in _st.secrets:
                    url = str(_st.secrets["DATABASE_URL"]).strip()
                elif "SUPABASE_DB_URL" in _st.secrets:
                    url = str(_st.secrets["SUPABASE_DB_URL"]).strip()
            except Exception:
                pass
        except Exception:
            pass
    return url


_custom_db = os.getenv("QUEUESENSE_DB_PATH") or os.getenv("DATABASE_PATH")
DATABASE_PATH = Path(_custom_db) if _custom_db else (Path(__file__).resolve().parent / "queuesense.db")
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)


_last_pg_error = None
_pg_pool = None
import threading
_pool_lock = threading.Lock()


def is_postgres():
    if os.getenv("USE_SQLITE", "").lower() in ("1", "true", "yes"):
        return False
    url = get_postgres_url()
    return bool(psycopg2 and url and url.startswith(("postgres://", "postgresql://")))


def get_pg_pool():
    global _pg_pool, _last_pg_error
    if not is_postgres():
        return None
    url = get_postgres_url()
    if not url:
        return None
    if _pg_pool is None:
        with _pool_lock:
            if _pg_pool is None:
                try:
                    _pg_pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=url, connect_timeout=3)
                    _last_pg_error = None
                except Exception as exc:
                    _last_pg_error = str(exc)
                    return None
    return _pg_pool


def get_db_info():
    global _last_pg_error
    if is_postgres():
        if _last_pg_error:
            return {
                "engine": "PostgreSQL (Connection Error)",
                "target": "Supabase Cloud",
                "is_cloud": False,
                "error": _last_pg_error
            }
        url = get_postgres_url()
        target = url.split("@")[-1] if "@" in url else "Supabase"
        return {"engine": "PostgreSQL (Supabase Cloud)", "target": target, "is_cloud": True, "error": None}
    return {"engine": "SQLite (Local File)", "target": str(DATABASE_PATH.name), "is_cloud": False, "error": None}



class PostgresCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor
        self._last_id = None
        if cursor.description:
            try:
                row = cursor.fetchone()
                if row and "id" in row:
                    self._last_id = row["id"]
                # Rewind if possible or cache for fetchone
                self._cached_row = row
            except Exception:
                self._cached_row = None
        else:
            self._cached_row = None

    @property
    def lastrowid(self):
        return self._last_id

    def fetchall(self):
        if self._cached_row is not None:
            remaining = self.cursor.fetchall()
            rows = [self._cached_row] + remaining
            self._cached_row = None
            return rows
        return self.cursor.fetchall()

    def fetchone(self):
        if self._cached_row is not None:
            row = self._cached_row
            self._cached_row = None
            return row
        return self.cursor.fetchone()


class DBConnectionContext:
    def __init__(self, raw_conn, is_pg, pool=None):
        self.raw = raw_conn
        self.is_pg = is_pg
        self.pool = pool

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.raw.commit()
            else:
                self.raw.rollback()
        except Exception:
            pass
        finally:
            if self.pool is not None:
                try:
                    self.pool.putconn(self.raw)
                except Exception:
                    try:
                        self.raw.close()
                    except Exception:
                        pass
            else:
                try:
                    self.raw.close()
                except Exception:
                    pass

    def execute(self, query, params=None):
        if self.is_pg:
            pg_query = query.replace("?", "%s")
            cur = self.raw.cursor(cursor_factory=RealDictCursor)
            cur.execute(pg_query, params or ())
            return PostgresCursorWrapper(cur)
        else:
            if params is None:
                return self.raw.execute(query)
            return self.raw.execute(query, params)


def get_connection():
    global _last_pg_error
    if is_postgres():
        pool = get_pg_pool()
        if pool is not None:
            try:
                raw_conn = pool.getconn()
                if getattr(raw_conn, "closed", 0) != 0:
                    try:
                        pool.putconn(raw_conn, close=True)
                    except Exception:
                        pass
                    raw_conn = pool.getconn()
                _last_pg_error = None
                return DBConnectionContext(raw_conn, is_pg=True, pool=pool)
            except Exception as exc:
                _last_pg_error = str(exc)
        else:
            try:
                conn = psycopg2.connect(get_postgres_url(), connect_timeout=3)
                _last_pg_error = None
                return DBConnectionContext(conn, is_pg=True, pool=None)
            except Exception as exc:
                _last_pg_error = str(exc)

    conn = sqlite3.connect(str(DATABASE_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return DBConnectionContext(conn, is_pg=False, pool=None)



def current_timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get_cutoff_timestamp(hours):
    hours = max(1, min(int(hours), 24 * 365))
    return (datetime.now().astimezone() - timedelta(hours=hours)).isoformat(timespec="seconds")


def initialize_database():
    """Create missing tables and safely migrate columns without deleting data."""
    with get_connection() as connection:
        if is_postgres():
            connection.execute("""CREATE TABLE IF NOT EXISTS queue_status (
                queue_name TEXT PRIMARY KEY,
                occupancy INTEGER NOT NULL DEFAULT 0,
                total_entries INTEGER NOT NULL DEFAULT 0,
                total_exits INTEGER NOT NULL DEFAULT 0,
                average_wait_seconds REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS queue_history (
                id BIGSERIAL PRIMARY KEY,
                queue_name TEXT NOT NULL,
                occupancy INTEGER NOT NULL,
                total_entries INTEGER NOT NULL,
                total_exits INTEGER NOT NULL,
                average_wait_seconds REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                video_hash TEXT,
                session_id TEXT,
                video_name TEXT
            )""")
            cols_cur = connection.execute(
                "SELECT column_name AS name FROM information_schema.columns WHERE table_name = 'queue_history'"
            )
            columns = {row["name"] for row in cols_cur.fetchall()}
            for name, sql_type in (("video_hash", "TEXT"), ("session_id", "TEXT"), ("video_name", "TEXT")):
                if name not in columns:
                    connection.execute(f"ALTER TABLE queue_history ADD COLUMN {name} {sql_type}")
        else:
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
        connection.execute("""CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")


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
        if statistics:
            placeholders = ",".join(["?"] * len(statistics))
            connection.execute(f"DELETE FROM queue_status WHERE queue_name NOT IN ({placeholders})", tuple(statistics.keys()))
        else:
            connection.execute("DELETE FROM queue_status")

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

    # Dual persistence: also write to local SQLite so local Flask/Streamlit dashboards stay in 100% sync
    if is_postgres() and DATABASE_PATH.exists():
        try:
            with sqlite3.connect(str(DATABASE_PATH), timeout=5) as lconn:
                if statistics:
                    placeholders = ",".join(["?"] * len(statistics))
                    lconn.execute(f"DELETE FROM queue_status WHERE queue_name NOT IN ({placeholders})", tuple(statistics.keys()))
                else:
                    lconn.execute("DELETE FROM queue_status")
                for queue_name, values in statistics.items():
                    occupancy = max(0, int(values.get("occupancy", 0) or 0))
                    entries = max(0, int(values.get("entries", 0) or 0))
                    exits = max(0, int(values.get("exits", 0) or 0))
                    average_wait = max(0.0, float(values.get("average_wait_seconds", 0) or 0))
                    lconn.execute("""INSERT INTO queue_status
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
                        lconn.execute("""INSERT INTO queue_history
                            (queue_name, occupancy, total_entries, total_exits, average_wait_seconds,
                             recorded_at, video_hash, session_id, video_name)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (queue_name, occupancy, entries, exits, average_wait, timestamp,
                             video_hash, session_id, resolved_video_name))
                lconn.commit()
        except Exception:
            pass


def get_queue_statistics(max_age_seconds=20):
    # Fast path for local environment: read from local SQLite if fresh records exist (<1ms response)
    if is_postgres() and DATABASE_PATH.exists():
        try:
            with sqlite3.connect(str(DATABASE_PATH), timeout=2) as lconn:
                lconn.row_factory = sqlite3.Row
                lrows = lconn.execute("""SELECT queue_name, occupancy, total_entries, total_exits,
                    average_wait_seconds, updated_at FROM queue_status ORDER BY queue_name""").fetchall()
            if lrows:
                now_dt = datetime.now().astimezone()
                lres = {}
                is_fresh = True
                for row in lrows:
                    upd = row["updated_at"]
                    if max_age_seconds is not None and upd:
                        try:
                            dt = datetime.fromisoformat(upd)
                            if (now_dt - dt).total_seconds() > max_age_seconds:
                                is_fresh = False
                                break
                        except Exception:
                            pass
                    lres[row["queue_name"]] = {
                        "occupancy": row["occupancy"],
                        "entries": row["total_entries"],
                        "exits": row["total_exits"],
                        "average_wait_seconds": row["average_wait_seconds"],
                        "updated_at": row["updated_at"]
                    }
                if is_fresh and lres:
                    return lres
        except Exception:
            pass

    with get_connection() as connection:
        rows = connection.execute("""SELECT queue_name, occupancy, total_entries, total_exits,
            average_wait_seconds, updated_at FROM queue_status ORDER BY queue_name""").fetchall()
    now_dt = datetime.now().astimezone()
    res = {}
    for row in rows:
        upd = row["updated_at"]
        if max_age_seconds is not None and upd:
            try:
                dt = datetime.fromisoformat(upd)
                if (now_dt - dt).total_seconds() > max_age_seconds:
                    continue
            except Exception:
                pass
        res[row["queue_name"]] = {
            "occupancy": row["occupancy"],
            "entries": row["total_entries"],
            "exits": row["total_exits"],
            "average_wait_seconds": row["average_wait_seconds"],
            "updated_at": row["updated_at"]
        }
    return res


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
    if is_postgres() and DATABASE_PATH.exists():
        try:
            with sqlite3.connect(str(DATABASE_PATH), timeout=5) as lconn:
                lconn.execute("DELETE FROM queue_status")
                lconn.commit()
        except Exception:
            pass


try:
    initialize_database()
except Exception as _e:
    _last_pg_error = str(_e)


# ===== Arduino/RFID integration tables and functions =====
def initialize_integration_tables():
    with get_connection() as connection:
        if is_postgres():
            connection.execute("""CREATE TABLE IF NOT EXISTS attendance_events (
                id BIGSERIAL PRIMARY KEY,
                card_uid TEXT NOT NULL,
                roll_number TEXT,
                student_name TEXT,
                event_type TEXT NOT NULL,
                event_time TEXT NOT NULL
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_attendance_events_time ON attendance_events(event_time)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_attendance_events_roll ON attendance_events(roll_number)")
            connection.execute("""CREATE TABLE IF NOT EXISTS queue_alert_limits (
                queue_name TEXT PRIMARY KEY,
                limit_people INTEGER NOT NULL DEFAULT 5,
                updated_at TEXT NOT NULL
            )""")
            for name, limit_value in (("student", 3), ("faculty", 3), ("scholar", 3)):
                connection.execute("""INSERT INTO queue_alert_limits(queue_name,limit_people,updated_at)
                    VALUES(?,?,?) ON CONFLICT(queue_name) DO NOTHING""", (name, limit_value, current_timestamp()))
            try:
                connection.execute("DELETE FROM queue_alert_limits WHERE LOWER(queue_name) IN ('student queue', 'faculty queue', 'scholar queue')")
            except Exception:
                pass
            
            # Auto-sync offline SQLite records into Supabase so no scans are lost
            try:
                if DATABASE_PATH.exists():
                    with sqlite3.connect(str(DATABASE_PATH), timeout=5) as lconn:
                        lconn.row_factory = sqlite3.Row
                        has_tab = lconn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attendance_events'").fetchone()
                        if has_tab:
                            l_rows = lconn.execute("SELECT card_uid, roll_number, student_name, event_type, event_time FROM attendance_events").fetchall()
                            if l_rows:
                                c_existing = connection.execute("SELECT event_time, card_uid FROM attendance_events").fetchall()
                                c_set = {(r["event_time"], r["card_uid"]) for r in c_existing}
                                for lr in l_rows:
                                    if (lr["event_time"], lr["card_uid"]) not in c_set:
                                        connection.execute(
                                            "INSERT INTO attendance_events (card_uid, roll_number, student_name, event_type, event_time) VALUES (?, ?, ?, ?, ?)",
                                            (lr["card_uid"], lr["roll_number"], lr["student_name"], lr["event_type"], lr["event_time"])
                                        )
            except Exception:
                pass
        else:
            connection.execute("""CREATE TABLE IF NOT EXISTS attendance_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_uid TEXT NOT NULL,
                roll_number TEXT,
                student_name TEXT,
                event_type TEXT NOT NULL,
                event_time TEXT NOT NULL
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_attendance_events_time ON attendance_events(event_time)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_attendance_events_roll ON attendance_events(roll_number)")
            connection.execute("""CREATE TABLE IF NOT EXISTS queue_alert_limits (
                queue_name TEXT PRIMARY KEY,
                limit_people INTEGER NOT NULL DEFAULT 5,
                updated_at TEXT NOT NULL
            )""")
            for name, limit_value in (("student", 3), ("faculty", 3), ("scholar", 3)):
                connection.execute("""INSERT INTO queue_alert_limits(queue_name,limit_people,updated_at)
                    VALUES(?,?,?) ON CONFLICT(queue_name) DO NOTHING""", (name, limit_value, current_timestamp()))
            try:
                connection.execute("DELETE FROM queue_alert_limits WHERE LOWER(queue_name) IN ('student queue', 'faculty queue', 'scholar queue')")
            except Exception:
                pass


_attendance_cache = {
    "summary": None,
    "summary_ts": 0.0,
    "events": None,
    "events_ts": 0.0,
}


def invalidate_attendance_cache():
    _attendance_cache["summary_ts"] = 0.0
    _attendance_cache["events_ts"] = 0.0


def save_attendance_event(card_uid, roll_number, student_name, event_type, event_time=None):
    uid = str(card_uid).strip().lower()
    event_type = str(event_type).strip().upper()
    if not uid:
        raise ValueError("Card UID cannot be empty")
    if event_type not in ("ENTRY", "EXIT", "UNKNOWN"):
        raise ValueError("Invalid attendance event type")
    stamp = event_time or current_timestamp()
    invalidate_attendance_cache()
    with get_connection() as connection:
        if is_postgres():
            cur = connection.execute(
                "INSERT INTO attendance_events(card_uid,roll_number,student_name,event_type,event_time) VALUES(?,?,?,?,?) RETURNING id",
                (uid, str(roll_number or "").strip(), str(student_name or "").strip(), event_type, stamp)
            )
            # Backup locally in SQLite as well
            try:
                if DATABASE_PATH.exists():
                    with sqlite3.connect(str(DATABASE_PATH), timeout=5) as lconn:
                        lconn.execute(
                            "INSERT INTO attendance_events(card_uid,roll_number,student_name,event_type,event_time) VALUES(?,?,?,?,?)",
                            (uid, str(roll_number or "").strip(), str(student_name or "").strip(), event_type, stamp)
                        )
            except Exception:
                pass
            return cur.lastrowid
        else:
            cur = connection.execute(
                "INSERT INTO attendance_events(card_uid,roll_number,student_name,event_type,event_time) VALUES(?,?,?,?,?)",
                (uid, str(roll_number or "").strip(), str(student_name or "").strip(), event_type, stamp)
            )
            return cur.lastrowid


def get_attendance_payload(limit=200, search=None):
    """Fetch attendance events and summary in a single database round-trip."""
    now_m = time.monotonic()
    if not search and limit == 200 and (now_m - _attendance_cache["events_ts"] < 0.5) and _attendance_cache["events"] is not None and _attendance_cache["summary"] is not None:
        return _attendance_cache["events"], _attendance_cache["summary"]

    limit = max(1, min(int(limit), 5000))
    query = "SELECT id,card_uid,roll_number,student_name,event_type,event_time FROM attendance_events"
    params = []
    if search and str(search).strip():
        term = "%" + str(search).strip() + "%"
        query += " WHERE student_name LIKE ? OR roll_number LIKE ? OR card_uid LIKE ? OR event_type LIKE ?"
        params.extend([term] * 4)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()
        events = [dict(row) for row in rows]

        row = connection.execute("""
            SELECT 
                COUNT(*) AS total_events,
                COUNT(CASE WHEN event_type = 'ENTRY' THEN 1 END) AS total_entries,
                COUNT(CASE WHEN event_type = 'EXIT' THEN 1 END) AS total_exits,
                COUNT(DISTINCT CASE WHEN roll_number IS NOT NULL AND roll_number != '' AND event_type IN ('ENTRY', 'EXIT') THEN roll_number END) AS unique_students
            FROM attendance_events
        """).fetchone()

    if row:
        d = dict(row)
        summary = {
            "total_events": int(d.get("total_events", 0) or 0),
            "total_entries": int(d.get("total_entries", 0) or 0),
            "total_exits": int(d.get("total_exits", 0) or 0),
            "unique_students": int(d.get("unique_students", 0) or 0)
        }
    else:
        summary = {"total_events": 0, "total_entries": 0, "total_exits": 0, "unique_students": 0}

    if not search and limit == 200:
        _attendance_cache["events"] = events
        _attendance_cache["summary"] = summary
        _attendance_cache["events_ts"] = now_m
        _attendance_cache["summary_ts"] = now_m

    return events, summary


def get_attendance_events(limit=200, search=None):
    events, _ = get_attendance_payload(limit=limit, search=search)
    return events


def get_attendance_summary():
    _, summary = get_attendance_payload(limit=200, search=None)
    return summary


_limits_cache = {"data": None, "ts": 0.0}


def normalize_queue_name(name):
    clean = str(name).strip().lower()
    for standard in ("student", "faculty", "scholar"):
        if standard in clean:
            return standard
    return clean


def canonical_queue_name(name):
    clean = str(name).strip()
    lower = clean.lower()
    if "student" in lower:
        return "student"
    if "faculty" in lower:
        return "faculty"
    if "scholar" in lower:
        return "scholar"
    return lower


class NormalizedLimitsDict(dict):
    """Dictionary of queue limits that maps aliases (e.g. 'Student Queue' -> 'student')."""
    def _find_key(self, key):
        if dict.__contains__(self, key):
            return key
        canon = canonical_queue_name(key)
        if dict.__contains__(self, canon):
            return canon
        for k in dict.keys(self):
            if canonical_queue_name(k) == canon:
                return k
        return None

    def __getitem__(self, key):
        found = self._find_key(key)
        if found is not None:
            return dict.__getitem__(self, found)
        raise KeyError(key)

    def get(self, key, default=None):
        found = self._find_key(key)
        if found is not None:
            return dict.__getitem__(self, found)
        return default

    def __contains__(self, key):
        return self._find_key(key) is not None


def get_queue_alert_limits():
    global _limits_cache
    now_m = time.monotonic()
    if now_m - _limits_cache["ts"] < 1.0 and _limits_cache["data"] is not None:
        return _limits_cache["data"]

    with get_connection() as connection:
        rows = connection.execute("SELECT queue_name,limit_people,updated_at FROM queue_alert_limits ORDER BY queue_name").fetchall()

    # Deduplicate rows by canonical name so only 'student', 'faculty', 'scholar' appear
    limits = {}
    for r in rows:
        cname = canonical_queue_name(r["queue_name"])
        if cname not in limits:
            limits[cname] = {"limit_people": r["limit_people"], "updated_at": r["updated_at"]}

    # Ensure canonical default queues are always available in exact desired order
    canonical_order = ["student", "faculty", "scholar"]
    for default_name in canonical_order:
        if default_name not in limits:
            limits[default_name] = {"limit_people": 3, "updated_at": current_timestamp()}

    ordered_limits = {k: limits[k] for k in canonical_order if k in limits}
    for k, v in limits.items():
        if k not in ordered_limits:
            ordered_limits[k] = v

    result = NormalizedLimitsDict(ordered_limits)
    _limits_cache["data"] = result
    _limits_cache["ts"] = now_m
    return result


def save_queue_alert_limit(queue_name, limit_people):
    global _limits_cache
    raw_name = str(queue_name).strip()
    limit_value = int(limit_people)
    if not raw_name:
        raise ValueError("Queue name cannot be empty")
    if limit_value < 0:
        raise ValueError("Limit cannot be negative")
    stamp = current_timestamp()
    canon_name = canonical_queue_name(raw_name)
    _limits_cache["ts"] = 0.0  # Invalidate cache

    with get_connection() as connection:
        connection.execute(
            """INSERT INTO queue_alert_limits(queue_name,limit_people,updated_at) VALUES(?,?,?)
            ON CONFLICT(queue_name) DO UPDATE SET limit_people=excluded.limit_people,updated_at=excluded.updated_at""",
            (canon_name, limit_value, stamp)
        )
        # Purge any legacy 'Student Queue' row so only the canonical name exists
        if raw_name != canon_name:
            try:
                connection.execute("DELETE FROM queue_alert_limits WHERE queue_name = ?", (raw_name,))
            except Exception:
                pass
        for variant in (f"{canon_name} queue", f"{canon_name.title()} Queue", f"{canon_name.capitalize()} Queue"):
            if variant != canon_name:
                try:
                    connection.execute("DELETE FROM queue_alert_limits WHERE LOWER(queue_name) = LOWER(?)", (variant,))
                except Exception:
                    pass

    # Local SQLite backup persistence if using Postgres
    if is_postgres() and DATABASE_PATH.exists():
        try:
            with sqlite3.connect(str(DATABASE_PATH), timeout=5) as lconn:
                lconn.execute(
                    """INSERT INTO queue_alert_limits(queue_name,limit_people,updated_at) VALUES(?,?,?)
                    ON CONFLICT(queue_name) DO UPDATE SET limit_people=excluded.limit_people,updated_at=excluded.updated_at""",
                    (canon_name, limit_value, stamp)
                )
                if raw_name != canon_name:
                    lconn.execute("DELETE FROM queue_alert_limits WHERE queue_name = ?", (raw_name,))
                for variant in (f"{canon_name} queue", f"{canon_name.title()} Queue", f"{canon_name.capitalize()} Queue"):
                    if variant != canon_name:
                        lconn.execute("DELETE FROM queue_alert_limits WHERE LOWER(queue_name) = LOWER(?)", (variant,))
                lconn.commit()
        except Exception:
            pass

    return {"queue_name": raw_name, "limit_people": limit_value, "updated_at": stamp}


try:
    initialize_integration_tables()
except Exception as _e:
    _last_pg_error = str(_e)


def set_system_state(key, value):
    stamp = current_timestamp()
    with get_connection() as connection:
        connection.execute("""INSERT INTO system_state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, str(value), stamp))
    return stamp


def get_system_state(key, max_age_seconds=None):
    try:
        with get_connection() as connection:
            row = connection.execute("SELECT key, value, updated_at FROM system_state WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        val = row["value"]
        upd = row["updated_at"]
        if max_age_seconds is not None:
            try:
                ts = datetime.fromisoformat(upd)
                now = datetime.now().astimezone()
                if (now - ts).total_seconds() > max_age_seconds:
                    return None
            except Exception:
                pass
        return {"key": key, "value": val, "updated_at": upd}
    except Exception:
        return None


def update_live_frame(frame_bytes):
    """Save latest video frame thumbnail (JPEG bytes encoded to base64) to database for cloud preview."""
    import base64
    b64_str = base64.b64encode(frame_bytes).decode("ascii")
    set_system_state("live_frame", b64_str)


_live_frame_cache = {"bytes": None, "updated_at": None, "ts": 0.0}


def get_live_frame():
    """Retrieve the latest live frame from system_state, returning (frame_bytes, updated_at) or (None, None)."""
    global _live_frame_cache
    now_m = time.monotonic()
    if now_m - _live_frame_cache["ts"] < 0.3 and _live_frame_cache["bytes"] is not None:
        return _live_frame_cache["bytes"], _live_frame_cache["updated_at"]

    import base64
    st = get_system_state("live_frame")
    if not st:
        return None, None
    try:
        raw = base64.b64decode(st["value"])
        _live_frame_cache = {"bytes": raw, "updated_at": st["updated_at"], "ts": now_m}
        return raw, st["updated_at"]
    except Exception:
        return None, None


def update_hardware_status(status_dict):
    """Store local Arduino / bridge status into database so cloud dashboards can see it."""
    import json
    set_system_state("hardware_status", json.dumps(status_dict))


def get_hardware_status():
    """Fetch hardware status from database with heartbeat liveness check."""
    import json
    st = get_system_state("hardware_status")
    if not st:
        return {"connected": False, "is_online": False, "port": None, "alert_active": False}
    try:
        data = json.loads(st["value"])
        ts = datetime.fromisoformat(st["updated_at"])
        is_fresh = (datetime.now().astimezone() - ts).total_seconds() <= 15
        data["is_online"] = is_fresh and bool(data.get("connected", False))
        data["last_seen"] = st["updated_at"]
        return data
    except Exception:
        return {"connected": False, "is_online": False, "port": None, "alert_active": False}

