"""
QueueSense – Manual Offline-to-Cloud Sync Tool
Pushes all local SQLite data (attendance scans, alert limits, history) to Supabase Cloud PostgreSQL.
Run this whenever you connect to fast internet after running offline at college!
"""

import os
import sys
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import database

def sync_data():
    print("=" * 60)
    print("  QueueSense - Local SQLite to Supabase Cloud Sync")
    print("=" * 60)

    if not database.DATABASE_PATH.exists():
        print(f"[-] No local database found at: {database.DATABASE_PATH}")
        return

    url = database.get_postgres_url()
    if not url:
        print("[-] Error: No DATABASE_URL found in .env or environment.")
        return

    print(f"[*] Local database: {database.DATABASE_PATH}")
    print("[*] Connecting to Supabase Cloud PostgreSQL...")

    try:
        with database.get_connection() as cloud_conn:
            if not cloud_conn.is_pg:
                print("[-] Could not establish PostgreSQL connection to Supabase.")
                print(f"    Error: {database._last_pg_error or 'Unknown error'}")
                return

            with sqlite3.connect(str(database.DATABASE_PATH)) as local_conn:
                local_conn.row_factory = sqlite3.Row

                # 1. Sync RFID Attendance Events
                print("\n[1/3] Syncing RFID Attendance Events...")
                has_att = local_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attendance_events'").fetchone()
                att_synced = 0
                if has_att:
                    local_events = local_conn.execute("SELECT card_uid, roll_number, student_name, event_type, event_time FROM attendance_events ORDER BY id").fetchall()
                    cloud_events = cloud_conn.execute("SELECT card_uid, event_time FROM attendance_events").fetchall()
                    existing_set = {(r["card_uid"], r["event_time"]) for r in cloud_events}

                    for ev in local_events:
                        if (ev["card_uid"], ev["event_time"]) not in existing_set:
                            cloud_conn.execute(
                                """INSERT INTO attendance_events (card_uid, roll_number, student_name, event_type, event_time)
                                   VALUES (?, ?, ?, ?, ?)""",
                                (ev["card_uid"], ev["roll_number"], ev["student_name"], ev["event_type"], ev["event_time"])
                            )
                            att_synced += 1

                print(f"      -> Successfully uploaded {att_synced} new attendance scans to Supabase.")

                # 2. Sync Queue Alert Limits
                print("\n[2/3] Syncing Hardware Alert Thresholds...")
                has_lim = local_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='queue_alert_limits'").fetchone()
                lim_synced = 0
                if has_lim:
                    local_limits = local_conn.execute("SELECT queue_name, limit_people, updated_at FROM queue_alert_limits").fetchall()
                    for lim in local_limits:
                        cloud_conn.execute(
                            """INSERT INTO queue_alert_limits (queue_name, limit_people, updated_at)
                               VALUES (?, ?, ?)
                               ON CONFLICT (queue_name) DO UPDATE SET limit_people = excluded.limit_people, updated_at = excluded.updated_at""",
                            (lim["queue_name"], lim["limit_people"], lim["updated_at"])
                        )
                        lim_synced += 1
                print(f"      -> Synchronized {lim_synced} alert limits to Supabase.")

                # 3. Sync Historical Queue Occupancy
                print("\n[3/3] Syncing Queue History Snapshots...")
                has_hist = local_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='queue_history'").fetchone()
                hist_synced = 0
                if has_hist:
                    local_hist = local_conn.execute(
                        """SELECT queue_name, occupancy, total_entries, total_exits, average_wait_seconds,
                                  recorded_at, video_hash, session_id, video_name FROM queue_history ORDER BY id"""
                    ).fetchall()
                    cloud_hist = cloud_conn.execute("SELECT queue_name, recorded_at FROM queue_history").fetchall()
                    cloud_hist_set = {(r["queue_name"], r["recorded_at"]) for r in cloud_hist}

                    for h in local_hist:
                        if (h["queue_name"], h["recorded_at"]) not in cloud_hist_set:
                            cloud_conn.execute(
                                """INSERT INTO queue_history
                                   (queue_name, occupancy, total_entries, total_exits, average_wait_seconds,
                                    recorded_at, video_hash, session_id, video_name)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (h["queue_name"], h["occupancy"], h["total_entries"], h["total_exits"],
                                 h["average_wait_seconds"], h["recorded_at"], h["video_hash"],
                                 h["session_id"], h["video_name"])
                            )
                            hist_synced += 1
                print(f"      -> Successfully uploaded {hist_synced} new historical records to Supabase.")

        print("\n" + "=" * 60)
        print("  Sync Complete! All offline college data is now in Supabase.")
        print("=" * 60)

    except Exception as e:
        print(f"\n[-] Sync failed: {e}")

if __name__ == "__main__":
    sync_data()
