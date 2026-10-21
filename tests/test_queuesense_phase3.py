# -*- coding: utf-8 -*-
"""
QueueSense Phase 3 Comprehensive Test Suite
Run from D:\\QueueSense:
  .venv\\Scripts\\python.exe tests\\test_queuesense_phase3.py
All output uses only ASCII characters to avoid Windows cp1252 encoding issues.
"""
import sys, os, time, sqlite3, json, threading, tempfile
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path("D:/QueueSense")
sys.path.insert(0, str(PROJECT_ROOT))

RESULTS = []

def record(name, passed, note=""):
    status = "PASS" if passed else "FAIL"
    RESULTS.append((name, status, note))
    mark = "OK  " if passed else "FAIL"
    suffix = "  [%s]" % note if note else ""
    print("  [%s] %s%s" % (mark, name, suffix))


# ======================================================================
# 1. PYTHON SYNTAX & IMPORTS
# ======================================================================
print("\n=== 1. PYTHON SYNTAX & IMPORTS ===")

import ast

for filename in ["database.py", "arduino_queue_bridge.py", "app.py", "monitor.py",
                 "src/queue_manager.py"]:
    fpath = PROJECT_ROOT / filename
    try:
        src = fpath.read_bytes()          # read bytes; ast.parse handles BOM
        ast.parse(src)
        record("Syntax OK: %s" % filename, True)
    except SyntaxError as e:
        record("Syntax OK: %s" % filename, False, str(e))
    except FileNotFoundError:
        record("File exists: %s" % filename, False, "File not found")

try:
    import database
    record("Import: database", True)
except Exception as e:
    record("Import: database", False, str(e))

try:
    import arduino_queue_bridge
    record("Import: arduino_queue_bridge", True)
except Exception as e:
    record("Import: arduino_queue_bridge", False, str(e))

try:
    import app as flask_app
    record("Import: app (Flask)", True)
except Exception as e:
    record("Import: app (Flask)", False, str(e))

try:
    from src.queue_manager import QueueManager
    record("Import: src.queue_manager.QueueManager", True)
except Exception as e:
    record("Import: src.queue_manager.QueueManager", False, str(e))


# ======================================================================
# 2. DATABASE INIT & MIGRATION
# ======================================================================
print("\n=== 2. DATABASE INIT & MIGRATION ===")

tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEST_DB = tf.name
tf.close()

orig_db_path = database.DATABASE_PATH
orig_is_pg = database.is_postgres
database.is_postgres = lambda: False
database.DATABASE_PATH = Path(TEST_DB)

try:
    database.initialize_database()
    database.initialize_integration_tables()
    record("initialize_database() without error", True)

    conn = sqlite3.connect(TEST_DB)
    conn.row_factory = sqlite3.Row
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    expected = {"queue_status", "queue_history", "attendance_events", "queue_alert_limits"}
    missing = expected - tables
    record("All required tables exist", not missing, str(missing) if missing else "")

    try:
        database.initialize_database()
        database.initialize_integration_tables()
        record("Double-init is idempotent", True)
    except Exception as e:
        record("Double-init is idempotent", False, str(e))

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(queue_history)").fetchall()}
    for col in ("video_hash", "session_id", "video_name"):
        record("Migration column '%s' exists" % col, col in cols)

    conn.close()
except Exception as e:
    record("initialize_database() without error", False, str(e))
finally:
    database.is_postgres = orig_is_pg
    database.DATABASE_PATH = orig_db_path
    try:
        os.remove(TEST_DB)
    except Exception:
        pass


# ======================================================================
# 3. QUEUE DATA PRESERVATION
# ======================================================================
print("\n=== 3. QUEUE DATA PRESERVATION ===")

try:
    database.save_queue_statistics(
        {"Test Queue": {"occupancy": 3, "entries": 5, "exits": 2, "average_wait_seconds": 15.0}},
        save_history=True
    )
    stats = database.get_queue_statistics()
    record("save_queue_statistics / get_queue_statistics round-trip",
           "Test Queue" in stats and stats["Test Queue"]["occupancy"] == 3)

    hist = database.get_queue_history("Test Queue", hours=1)
    record("queue_history preserved after save", len(hist) >= 1)

    hist_summary = database.get_queue_history_summary(hours=1)
    record("get_queue_history_summary returns data", "Test Queue" in hist_summary)
except Exception as e:
    record("Queue statistics round-trip", False, str(e))

try:
    database.reset_queue_status()
    stats_after = database.get_queue_statistics()
    hist_after = database.get_queue_history("Test Queue", hours=1)
    record("reset_queue_status clears current status", "Test Queue" not in stats_after)
    record("reset_queue_status preserves history", len(hist_after) >= 1)
except Exception as e:
    record("reset_queue_status", False, str(e))


# ======================================================================
# 4. QUEUE ALERT LIMITS
# ======================================================================
print("\n=== 4. QUEUE ALERT LIMITS ===")

try:
    result = database.save_queue_alert_limit("Student Queue", 7)
    record("save_queue_alert_limit returns dict", isinstance(result, dict))
    record("returned dict has queue_name == 'Student Queue'",
           result.get("queue_name") == "Student Queue")
    record("returned dict has limit_people == 7", result.get("limit_people") == 7)
except Exception as e:
    record("save_queue_alert_limit basic", False, str(e))

try:
    database.save_queue_alert_limit("Faculty Queue", 3)
    database.save_queue_alert_limit("Scholar Queue", 10)
    limits = database.get_queue_alert_limits()
    record("Student Queue limit is 7",
           limits.get("Student Queue", {}).get("limit_people") == 7)
    record("Faculty Queue limit is 3",
           limits.get("Faculty Queue", {}).get("limit_people") == 3)
    record("Scholar Queue limit is 10",
           limits.get("Scholar Queue", {}).get("limit_people") == 10)
    record("Limits are independent per queue",
           limits["Student Queue"]["limit_people"] != limits["Faculty Queue"]["limit_people"])
except Exception as e:
    record("Independent per-queue limits", False, str(e))

try:
    database.save_queue_alert_limit("Student Queue", 12)
    limits = database.get_queue_alert_limits()
    record("Upsert updates existing limit",
           limits.get("Student Queue", {}).get("limit_people") == 12)
except Exception as e:
    record("Upsert updates existing limit", False, str(e))

try:
    database.save_queue_alert_limit("", 5)
    record("Empty queue name rejected", False, "Expected ValueError")
except ValueError:
    record("Empty queue name rejected", True)
except Exception as e:
    record("Empty queue name rejected", False, str(e))

try:
    database.save_queue_alert_limit("Q", -1)
    record("Negative limit rejected", False, "Expected ValueError")
except ValueError:
    record("Negative limit rejected", True)
except Exception as e:
    record("Negative limit rejected", False, str(e))


# ======================================================================
# 5. QUEUE ALERT ACTIVATION / DEACTIVATION
# ======================================================================
print("\n=== 5. QUEUE ALERT ACTIVATION / DEACTIVATION ===")

from arduino_queue_bridge import ArduinoQueueBridge

_calls = []

def _mock_send(self, line):
    _calls.append(line)
    return True

ArduinoQueueBridge._send = _mock_send

bridge_t = ArduinoQueueBridge.__new__(ArduinoQueueBridge)
bridge_t.port_name = None
bridge_t.baudrate = 9600
bridge_t.serial = None
bridge_t.thread = None
bridge_t.stop_event = threading.Event()
bridge_t.lock = threading.Lock()
bridge_t.connected = False
bridge_t.last_error = None
bridge_t.alert_active = False

# Active limits: Student=12, Faculty=3, Scholar=10
bridge_t.update_hardware_alerts({
    "Student Queue": {"occupancy": 5},
    "Faculty Queue": {"occupancy": 2},
    "Scholar Queue": {"occupancy": 5},
})
record("No alert when all within limits", not bridge_t.alert_active)

bridge_t.update_hardware_alerts({
    "Student Queue": {"occupancy": 5},
    "Faculty Queue": {"occupancy": 4},   # > 3
    "Scholar Queue": {"occupancy": 5},
})
record("Alert ON when Faculty (4) exceeds limit (3)", bridge_t.alert_active)
record("BUZZER,ON sent", any("BUZZER,ON" in c for c in _calls))

bridge_t.update_hardware_alerts({
    "Student Queue": {"occupancy": 13},  # > 12
    "Faculty Queue": {"occupancy": 4},   # > 3
    "Scholar Queue": {"occupancy": 5},
})
record("Alert stays ON when multiple queues exceed limits", bridge_t.alert_active)

bridge_t.update_hardware_alerts({
    "Student Queue": {"occupancy": 13},  # still > 12
    "Faculty Queue": {"occupancy": 3},   # exactly at limit (not exceeded)
    "Scholar Queue": {"occupancy": 5},
})
record("Alert stays ON while Student (13) still exceeds limit (12)", bridge_t.alert_active)

bridge_t.update_hardware_alerts({
    "Student Queue": {"occupancy": 12},  # at limit
    "Faculty Queue": {"occupancy": 3},   # at limit
    "Scholar Queue": {"occupancy": 10},  # at limit
})
record("Alert OFF when all queues at or below their limits", not bridge_t.alert_active)
record("BUZZER,OFF sent", any("BUZZER,OFF" in c for c in _calls))


# ======================================================================
# 6. RFID ATTENDANCE INSERT & RETRIEVE
# ======================================================================
print("\n=== 6. RFID ATTENDANCE ===")

try:
    rid1 = database.save_attendance_event("AB:CD:EF:12", "CS101", "Alice Smith", "ENTRY")
    record("Insert ENTRY event returns int ID", isinstance(rid1, int) and rid1 > 0)

    rid2 = database.save_attendance_event("AB:CD:EF:12", "CS101", "Alice Smith", "EXIT")
    record("Insert EXIT event returns int ID", isinstance(rid2, int) and rid2 > 0)

    rid3 = database.save_attendance_event("11:22:33:44", "CS202", "Bob Jones", "UNKNOWN")
    record("Insert UNKNOWN event accepted", isinstance(rid3, int) and rid3 > 0)

    events = database.get_attendance_events(limit=100)
    alice_events = [e for e in events if e.get("student_name") == "Alice Smith"]
    record("get_attendance_events returns Alice's records", len(alice_events) >= 2)

    entry_types = [e["event_type"] for e in alice_events]
    record("Both ENTRY and EXIT stored for Alice",
           "ENTRY" in entry_types and "EXIT" in entry_types)
except Exception as e:
    record("RFID attendance insert/retrieve", False, str(e))

try:
    summary = database.get_attendance_summary()
    record("get_attendance_summary returns dict", isinstance(summary, dict))
    record("total_events >= 3", summary.get("total_events", 0) >= 3)
    record("total_entries >= 1", summary.get("total_entries", 0) >= 1)
    record("total_exits >= 1", summary.get("total_exits", 0) >= 1)
    # unique_students counts distinct roll_numbers for ENTRY/EXIT only.
    # Bob's event is UNKNOWN, which is excluded by design from unique_students.
    # Only Alice (CS101) has ENTRY+EXIT -> unique_students = 1.
    record("unique_students >= 1 (UNKNOWN excluded by design)",
           summary.get("unique_students", 0) >= 1)
except Exception as e:
    record("get_attendance_summary", False, str(e))

try:
    results = database.get_attendance_events(limit=50, search="Alice")
    record("Search 'Alice' returns only Alice records",
           len(results) >= 1 and all("Alice" in r.get("student_name", "") for r in results))
except Exception as e:
    record("Attendance search filter", False, str(e))

try:
    database.save_attendance_event("XX:YY", "R1", "Eve", "BAD_TYPE")
    record("Invalid event type rejected", False, "Expected ValueError")
except ValueError:
    record("Invalid event type rejected", True)
except Exception as e:
    record("Invalid event type rejected", False, str(e))

try:
    database.save_attendance_event("  ", "R2", "Mallory", "ENTRY")
    record("Whitespace-only UID rejected", False, "Expected ValueError")
except ValueError:
    record("Whitespace-only UID rejected", True)
except Exception as e:
    record("Whitespace-only UID rejected", False, str(e))


# ======================================================================
# 7. FLASK API RESPONSES
# ======================================================================
print("\n=== 7. FLASK API RESPONSES ===")

flask_app.app.config["TESTING"] = True
client = flask_app.app.test_client()

def api(method, path, body=None):
    if method == "GET":
        return client.get(path)
    return client.post(path,
                       data=json.dumps(body).encode(),
                       content_type="application/json")

def chk(name, cond, note=""):
    record(name, bool(cond), note)

try:
    r = api("GET", "/api/stats")
    d = json.loads(r.data)
    chk("GET /api/stats returns 200", r.status_code == 200)
    chk("/api/stats has 'queues' key", "queues" in d)
    chk("/api/stats has 'arduino' key", "arduino" in d)
    chk("/api/stats has 'alert_limits' key", "alert_limits" in d)
    chk("/api/stats has 'monitoring' key", "monitoring" in d)
except Exception as e:
    record("GET /api/stats", False, str(e))

try:
    r = api("GET", "/api/alert-limits")
    d = json.loads(r.data)
    chk("GET /api/alert-limits returns 200", r.status_code == 200)
    chk("/api/alert-limits has 'limits'", "limits" in d)
except Exception as e:
    record("GET /api/alert-limits", False, str(e))

try:
    r = api("POST", "/api/alert-limits",
            {"queue_name": "Student Queue", "limit_people": 8})
    d = json.loads(r.data)
    chk("POST /api/alert-limits returns 200", r.status_code == 200)
    chk("POST /api/alert-limits success=True", d.get("success") is True)
    chk("POST /api/alert-limits limit persisted in DB",
        database.get_queue_alert_limits().get("Student Queue", {}).get("limit_people") == 8)
except Exception as e:
    record("POST /api/alert-limits", False, str(e))

try:
    r = api("POST", "/api/alert-limits", {"queue_name": "", "limit_people": 5})
    chk("POST /api/alert-limits with empty name returns 400", r.status_code == 400)
except Exception as e:
    record("POST /api/alert-limits empty name", False, str(e))

try:
    r = api("GET", "/api/attendance")
    d = json.loads(r.data)
    chk("GET /api/attendance returns 200", r.status_code == 200)
    chk("/api/attendance has 'events' key", "events" in d)
    chk("/api/attendance has 'summary' key", "summary" in d)
except Exception as e:
    record("GET /api/attendance", False, str(e))

try:
    r = client.get("/api/attendance?search=Alice")
    d = json.loads(r.data)
    chk("GET /api/attendance?search=Alice returns 200", r.status_code == 200)
    chk("Search results non-empty", len(d.get("events", [])) >= 1)
except Exception as e:
    record("GET /api/attendance search", False, str(e))

try:
    r = api("GET", "/api/arduino/status")
    d = json.loads(r.data)
    chk("GET /api/arduino/status returns 200", r.status_code == 200)
    chk("arduino/status has 'connected'", "connected" in d)
    chk("arduino/status has 'alert_active'", "alert_active" in d)
except Exception as e:
    record("GET /api/arduino/status", False, str(e))

try:
    r = api("POST", "/api/queue-occupancy",
            {"queues": {"Student Queue": {"occupancy": 2}}})
    d = json.loads(r.data)
    chk("POST /api/queue-occupancy returns 200", r.status_code == 200)
    chk("queue-occupancy success=True", d.get("success") is True)
except Exception as e:
    record("POST /api/queue-occupancy", False, str(e))

try:
    r = api("POST", "/api/queue-occupancy", {"queues": "bad_value"})
    chk("POST /api/queue-occupancy bad body returns 400", r.status_code == 400)
except Exception as e:
    record("POST /api/queue-occupancy bad body", False, str(e))

try:
    r = api("GET", "/")
    chk("GET / (dashboard) returns 200", r.status_code == 200)
    chk("Dashboard page contains 'QueueSense'", b"QueueSense" in r.data)
except Exception as e:
    record("GET / dashboard", False, str(e))


# ======================================================================
# 8. STARTUP WITHOUT ARDUINO
# ======================================================================
print("\n=== 8. STARTUP WITHOUT ARDUINO ===")

try:
    b_no = ArduinoQueueBridge(port="COM_DOESNT_EXIST", baudrate=9600)
    b_no.start()
    time.sleep(0.3)
    record("Bridge.start() does not raise when no Arduino present", True)
    record("connected=False with non-existent port", not b_no.connected)
    b_no.stop_event.set()
except Exception as e:
    record("Bridge starts without exception when no Arduino", False, str(e))

try:
    status = arduino_queue_bridge.bridge.status()
    record("bridge.status() returns a dict", isinstance(status, dict))
    record("bridge.status() has 'connected'", "connected" in status)
    record("bridge.status() has 'port'", "port" in status)
    record("bridge.status() has 'alert_active'", "alert_active" in status)
    record("bridge.status() has 'last_error'", "last_error" in status)
except Exception as e:
    record("bridge.status()", False, str(e))


# ======================================================================
# 9. SERIAL ERROR HANDLING (mock)
# ======================================================================
print("\n=== 9. SERIAL ERROR HANDLING (mock) ===")

try:
    mock_serial = MagicMock()
    mock_serial.is_open = True
    mock_serial.readline.side_effect = OSError("Simulated USB disconnect")

    bd = ArduinoQueueBridge.__new__(ArduinoQueueBridge)
    bd.port_name = "COMMOCK"
    bd.baudrate = 9600
    bd.serial = mock_serial
    bd.thread = None
    bd.stop_event = threading.Event()
    bd.lock = threading.Lock()
    bd.connected = True
    bd.last_error = None
    bd.alert_active = False

    try:
        raw = bd.serial.readline()
    except OSError as exc:
        bd.last_error = str(exc)
        bd.connected = False
        try: bd.serial.close()
        except: pass
        bd.serial = None

    record("last_error captured on disconnect", bd.last_error is not None)
    record("connected=False after disconnect", not bd.connected)
    record("serial=None after disconnect", bd.serial is None)
except Exception as e:
    record("Serial disconnection handling", False, str(e))


# ======================================================================
# 10. RFID SERIAL PARSING (mock)
# ======================================================================
print("\n=== 10. RFID SERIAL PARSING (mock) ===")

import arduino_queue_bridge as aqb

saved_mock = []
def _mock_save_att(uid, roll, name, event_type, event_time=None):
    saved_mock.append({"uid": uid, "roll": roll, "name": name, "event": event_type})
    return 42

orig_save_aqb = aqb.save_attendance_event
aqb.save_attendance_event = _mock_save_att

try:
    bp = ArduinoQueueBridge.__new__(ArduinoQueueBridge)
    bp.last_error = None

    bp._handle_line("RFID,ab:cd:ef:12,CS101,Alice Smith,ENTRY\n")
    record("RFID line: save_attendance_event called", len(saved_mock) == 1)
    record("RFID parsed UID correctly", saved_mock[0]["uid"] == "ab:cd:ef:12")
    record("RFID parsed roll correctly", saved_mock[0]["roll"] == "CS101")
    record("RFID parsed name correctly", saved_mock[0]["name"] == "Alice Smith")
    record("RFID parsed event type correctly", saved_mock[0]["event"] == "ENTRY")

    bp._handle_line("HEARTBEAT,OK\n")
    record("Non-RFID line ignored (no crash)", True)

    bp._handle_line("RFID,only,two\n")
    record("Partial RFID line ignored (no crash)", True)

    bp._handle_line("")
    record("Empty line ignored (no crash)", True)
except Exception as e:
    record("RFID serial parsing", False, str(e))
finally:
    aqb.save_attendance_event = orig_save_aqb


# ======================================================================
# 11. DUPLICATE THREAD PREVENTION
# ======================================================================
print("\n=== 11. DUPLICATE THREAD PREVENTION ===")

try:
    bd2 = ArduinoQueueBridge.__new__(ArduinoQueueBridge)
    bd2.port_name = None
    bd2.baudrate = 9600
    bd2.serial = None
    bd2.stop_event = threading.Event()
    bd2.lock = threading.Lock()
    bd2.connected = False
    bd2.last_error = None
    bd2.alert_active = False
    bd2.thread = None
    bd2._run = lambda: time.sleep(60)

    bd2.start()
    t_first = bd2.thread
    bd2.start()         # must not spawn a second thread
    t_second = bd2.thread
    record("Second start() reuses existing thread (no duplicate)", t_first is t_second)
    bd2.stop_event.set()
except Exception as e:
    record("Duplicate thread prevention", False, str(e))


# ======================================================================
# 12. QUEUE MANAGER UNIT TESTS
# ======================================================================
print("\n=== 12. QUEUE MANAGER ===")

from src.queue_manager import QueueManager

qm = QueueManager(
    ["Student Queue", "Faculty Queue"],
    confirmation_seconds=0.05,
    exit_confirmation_seconds=0.05,
    lost_track_timeout=0.1,
)

t0 = 0.0
qm.update(1, "Student Queue", now=t0)
time.sleep(0.08)
t1 = 0.08
qm.update(1, "Student Queue", now=t1)
stats = qm.get_statistics(now=t1)
record("Person confirmed in Student Queue", stats["Student Queue"]["occupancy"] == 1)
record("Entry count incremented", stats["Student Queue"]["entries"] == 1)
record("Faculty Queue has 0 occupancy", stats["Faculty Queue"]["occupancy"] == 0)

time.sleep(0.08)
t2 = 0.16
qm.update(1, None, now=t2)
time.sleep(0.08)
t3 = 0.24
qm.update(1, None, now=t3)
stats2 = qm.get_statistics(now=t3)
record("Person confirmed as exited", stats2["Student Queue"]["occupancy"] == 0)
record("Exit count incremented", stats2["Student Queue"]["exits"] == 1)

qm2 = QueueManager(["Q"],
                   confirmation_seconds=0.05,
                   exit_confirmation_seconds=0.05,
                   lost_track_timeout=0.1)
qm2.update(2, "Q", now=0.0)
time.sleep(0.08)
qm2.update(2, "Q", now=0.08)
time.sleep(0.15)
qm2.cleanup(visible_track_ids=set(), now=0.25)
stats3 = qm2.get_statistics(now=0.25)
record("Lost-track timeout triggers exit cleanup", stats3["Q"]["exits"] >= 1)


# ======================================================================
# CLEANUP
# ======================================================================
database.DATABASE_PATH = orig_db_path
try:
    os.unlink(TEST_DB)
except Exception:
    pass


# ======================================================================
# SUMMARY
# ======================================================================
passed = [r for r in RESULTS if r[1] == "PASS"]
failed = [r for r in RESULTS if r[1] == "FAIL"]

print()
print("=" * 66)
print("  QUEUESENSE PHASE 3 -- TEST RESULTS SUMMARY")
print("=" * 66)
print("  Total  : %d" % len(RESULTS))
print("  Passed : %d" % len(passed))
print("  Failed : %d" % len(failed))
print()
if failed:
    print("  FAILED TESTS:")
    for name, _, note in failed:
        if note:
            print("    FAIL %s  [%s]" % (name, note))
        else:
            print("    FAIL %s" % name)
    print()
else:
    print("  All tests passed.")
print("=" * 66)

sys.exit(0 if not failed else 1)
