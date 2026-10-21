"""
QueueSense Database Reset Script
Safely purges runtime tables in both Supabase PostgreSQL and local SQLite,
and re-seeds default alert limits for canonical queues ('student', 'faculty', 'scholar').
"""

import sys
import sqlite3
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import database

def purge_all():
    print("Purging QueueSense databases for a clean fresh start...")
    ts = database.current_timestamp()

    # 1. Supabase PostgreSQL (if configured)
    if database.is_postgres():
        print("-> Cleaning Supabase Cloud PostgreSQL...")
        try:
            with database.get_connection() as conn:
                conn.execute("TRUNCATE TABLE attendance_events, queue_history, queue_status;")
                conn.execute("DELETE FROM system_state;")
                conn.execute("DELETE FROM queue_alert_limits WHERE queue_name NOT IN ('student', 'faculty', 'scholar');")
                for q in ["student", "faculty", "scholar"]:
                    conn.execute(
                        "INSERT INTO queue_alert_limits (queue_name, limit_people, updated_at) "
                        "VALUES (?, 3, ?) ON CONFLICT (queue_name) DO UPDATE SET limit_people = 3, updated_at = ?;",
                        (q, ts, ts)
                    )
            print("   [OK] Supabase Cloud PostgreSQL reset complete.")
        except Exception as e:
            print(f"   [Error] Supabase reset error: {e}")

    # 2. Local SQLite
    db_path = BASE_DIR / "queuesense.db"
    print(f"-> Cleaning Local SQLite ({db_path.name})...")
    try:
        with sqlite3.connect(str(db_path), timeout=10) as lconn:
            lconn.execute("DELETE FROM attendance_events;")
            lconn.execute("DELETE FROM queue_history;")
            lconn.execute("DELETE FROM queue_status;")
            try:
                lconn.execute("DELETE FROM system_state;")
            except Exception:
                pass
            lconn.execute("DELETE FROM queue_alert_limits WHERE queue_name NOT IN ('student', 'faculty', 'scholar');")
            for q in ["student", "faculty", "scholar"]:
                lconn.execute(
                    "INSERT INTO queue_alert_limits (queue_name, limit_people, updated_at) "
                    "VALUES (?, 3, ?) ON CONFLICT (queue_name) DO UPDATE SET limit_people = 3, updated_at = ?;",
                    (q, ts, ts)
                )
            lconn.commit()
        print("   [OK] Local SQLite reset complete.")
    except Exception as e:
        print(f"   [Error] SQLite reset error: {e}")

    # 3. Clean temporary frame files
    for f in [BASE_DIR / "static" / "live_frame.jpg", BASE_DIR / "static" / "live_frame.tmp.jpg"]:
        try:
            if f.exists():
                f.unlink(missing_ok=True)
                print(f"   [OK] Removed {f.name}")
        except Exception:
            pass

    print("\nDatabase reset complete! Fresh start ready.")

if __name__ == "__main__":
    purge_all()
