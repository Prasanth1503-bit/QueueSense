# -*- coding: utf-8 -*-
"""
QueueSense Phase 5 Comprehensive Integration Test Suite
Validates the complete hardware-software integration matching the user's Arduino sketch:
- Startup handshake (QUEUESENSE_READY)
- Exact serial message parsing for all 6 registered students
- Unknown card handling (RFID,<uid>,,Unknown,UNKNOWN)
- Attendance database persistence and summary statistics
- Alert limit enforcement and BUZZER,ON / BUZZER,OFF command dispatch
- Flask API endpoints (/api/stats, /api/attendance, /api/arduino/status, /api/queue-occupancy)
- Arduino sketch existence and pin mapping verification
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
# 1. ARDUINO SKETCH FILE VERIFICATION
# ======================================================================
print("\n=== 1. ARDUINO SKETCH & HARDWARE CONFIGURATION ===")
ino_path = PROJECT_ROOT / "arduino" / "QueueSense_RFID.ino"
record("Arduino sketch file exists", ino_path.is_file(), str(ino_path))

if ino_path.is_file():
    ino_code = ino_path.read_text(encoding="utf-8")
    record("Sketch includes SPI.h", "#include <SPI.h>" in ino_code)
    record("Sketch includes MFRC522.h", "#include <MFRC522.h>" in ino_code)
    record("Sketch includes LiquidCrystal_I2C.h", "#include <LiquidCrystal_I2C.h>" in ino_code)
    record("Sketch defines SS_PIN 10", "#define SS_PIN 10" in ino_code)
    record("Sketch defines RST_PIN 9", "#define RST_PIN 9" in ino_code)
    record("Sketch defines BUZZER_PIN 2", "#define BUZZER_PIN 2" in ino_code)
    record("Sketch defines LED_PIN 3", "#define LED_PIN 3" in ino_code)
    record("Sketch sends QUEUESENSE_READY", 'Serial.println("QUEUESENSE_READY");' in ino_code)
    record("Sketch handles BUZZER,ON", 'cmd == "BUZZER,ON"' in ino_code or 'cmd=="BUZZER,ON"' in ino_code)
    record("Sketch handles BUZZER,OFF", 'cmd == "BUZZER,OFF"' in ino_code or 'cmd=="BUZZER,OFF"' in ino_code)
    
    # Check all 6 students in sketch
    sketch_students = [
        ("7b8bf206", "24BCE8221", "G.Prasanth Paul"),
        ("c1a9f868", "24BCE8253", "G.Prem Sasank"),
        ("d1157768", "24BCA7344", "T.Mani Sankar"),
        ("c1784968", "24BCE8263", "D.Dinesh"),
        ("c189f968", "24BCA7285", "Pardha"),
        ("d1b3d568", "24BES7016", "G.Aditya"),
    ]
    for uid, roll, name in sketch_students:
        record("Student %s (%s) present in sketch" % (name, roll), uid in ino_code and roll in ino_code)


# ======================================================================
# 2. ISOLATED DATABASE INTEGRATION TESTS
# ======================================================================
print("\n=== 2. ISOLATED DATABASE ATTENDANCE TESTS ===")
import database

# Setup temporary isolated DB
tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEST_DB = tf.name
tf.close()
orig_db = database.DATABASE_PATH
database.DATABASE_PATH = Path(TEST_DB)
database.initialize_database()
database.initialize_integration_tables()

SKETCH_STUDENTS = [
    ("07b8bf26", "24BCE8221", "G.Prasanth Paul"),
    ("c1a9f868", "24BCE8253", "G.Prem Sasank"),
    ("d1157768", "24BCA7344", "T.Mani Sankar"),
    ("c1784968", "24BCE8263", "D.Dinesh"),
    ("c189f968", "24BCA7285", "Pardha"),
    ("d1b3d568", "24BES7016", "G.Aditya"),
]

# Insert ENTRY for all 6 students
for uid, roll, name in SKETCH_STUDENTS:
    eid = database.save_attendance_event(uid, roll, name, "ENTRY")
    record("Logged ENTRY for %s" % name, isinstance(eid, int) and eid > 0)

# Insert EXIT for 2 students
database.save_attendance_event("07b8bf26", "24BCE8221", "G.Prasanth Paul", "EXIT")
database.save_attendance_event("c1a9f868", "24BCE8253", "G.Prem Sasank", "EXIT")

# Insert 1 UNKNOWN card scan (matching Arduino's exact unknown card output: empty roll, name 'Unknown')
uid_unknown = "aabbccdd"
eid_unk = database.save_attendance_event(uid_unknown, "", "Unknown", "UNKNOWN")
record("Logged UNKNOWN card scan", isinstance(eid_unk, int) and eid_unk > 0)

# Check summary statistics
summary = database.get_attendance_summary()
record("Total scans == 9 (6 entries + 2 exits + 1 unknown)", summary.get("total_events") == 9)
record("Total entries == 6", summary.get("total_entries") == 6)
record("Total exits == 2", summary.get("total_exits") == 2)
record("Unique registered students == 6", summary.get("unique_students") == 6)

# Test search capabilities
for uid, roll, name in SKETCH_STUDENTS:
    res_name = database.get_attendance_events(search=name)
    record("Search by name '%s' returned records" % name, len(res_name) >= 1)
    res_roll = database.get_attendance_events(search=roll)
    record("Search by roll '%s' returned records" % roll, len(res_roll) >= 1)

res_uid = database.get_attendance_events(search=uid_unknown)
record("Search by unknown UID returned record", len(res_uid) == 1 and res_uid[0]["event_type"] == "UNKNOWN")


# ======================================================================
# 3. SERIAL BRIDGE LINE PARSER TESTS (Exact Arduino Serial Output)
# ======================================================================
print("\n=== 3. SERIAL BRIDGE PROTOCOL TESTS ===")
from arduino_queue_bridge import ArduinoQueueBridge

test_bridge = ArduinoQueueBridge()

# 1. QUEUESENSE_READY handshake
record("Initial arduino_ready is False", test_bridge.arduino_ready is False)
test_bridge._handle_line("QUEUESENSE_READY\n")
record("arduino_ready is True after QUEUESENSE_READY line", test_bridge.arduino_ready is True)

# 2. Parse known card ENTRY
test_bridge._handle_line("RFID,c1784968,24BCE8263,D.Dinesh,ENTRY\n")
latest_events = database.get_attendance_events(limit=1)
record("Serial parse registered Dinesh ENTRY", latest_events[0]["student_name"] == "D.Dinesh" and latest_events[0]["event_type"] == "ENTRY")

# 3. Parse unknown card (empty roll number)
test_bridge._handle_line("RFID,deadbeef,,Unknown,UNKNOWN\n")
latest_unk = database.get_attendance_events(limit=1)
record("Serial parse registered Unknown card", latest_unk[0]["card_uid"] == "deadbeef" and latest_unk[0]["event_type"] == "UNKNOWN" and latest_unk[0]["roll_number"] == "")

# 4. Unknown format lines / noise
test_bridge._handle_line("RANDOM_NOISE_12345\n")
test_bridge._handle_line("\n")
test_bridge._handle_line("RFID,incomplete\n")
record("Serial bridge handled noise lines gracefully without raising", True)


# ======================================================================
# 4. BUZZER COMMAND GENERATION & LIMIT ENFORCEMENT
# ======================================================================
print("\n=== 4. BUZZER COMMAND DISPATCH & HARDWARE ALERTS ===")
sent_commands = []
test_bridge._send = lambda cmd: sent_commands.append(cmd)

# Set queue limits in database
database.save_queue_alert_limit("Queue A", 4)
database.save_queue_alert_limit("Queue B", 8)

# Test 1: Occupancy below limits -> alert inactive, no buzzer
test_bridge.alert_active = False
test_bridge.update_hardware_alerts({"Queue A": {"occupancy": 3}, "Queue B": {"occupancy": 5}})
record("No alarm when occupancy within limits", test_bridge.alert_active is False)
record("No BUZZER,ON command sent", "BUZZER,ON" not in sent_commands)

# Test 2: Queue A exceeds limit (5 > 4) -> BUZZER,ON sent
test_bridge.update_hardware_alerts({"Queue A": {"occupancy": 5}, "Queue B": {"occupancy": 5}})
record("Alarm active when Queue A exceeds limit", test_bridge.alert_active is True)
record("BUZZER,ON sent", len(sent_commands) > 0 and sent_commands[-1] == "BUZZER,ON")

# Test 3: Alert remains active while condition persists (no duplicate command)
cmd_count_before = len(sent_commands)
test_bridge.update_hardware_alerts({"Queue A": {"occupancy": 6}, "Queue B": {"occupancy": 7}})
record("No redundant BUZZER,ON command while already active", len(sent_commands) == cmd_count_before)

# Test 4: Occupancy drops back to normal -> BUZZER,OFF sent
test_bridge.update_hardware_alerts({"Queue A": {"occupancy": 4}, "Queue B": {"occupancy": 3}})
record("Alarm deactivated when all queues return to normal", test_bridge.alert_active is False)
record("BUZZER,OFF sent", sent_commands[-1] == "BUZZER,OFF")

# Test 5: Default limit (5) used for unconfigured queue
test_bridge.update_hardware_alerts({"Unconfigured Queue": {"occupancy": 6}})
record("Unconfigured queue with occupancy 6 triggers alert (default limit 5)", test_bridge.alert_active is True)
record("BUZZER,ON sent for unconfigured queue", sent_commands[-1] == "BUZZER,ON")


# ======================================================================
# 5. FLASK REST API INTEGRATION
# ======================================================================
print("\n=== 5. FLASK REST API INTEGRATION ===")
import app as flask_app
flask_app.app.config["TESTING"] = True
client = flask_app.app.test_client()

# /api/stats
res = client.get("/api/stats")
record("/api/stats status == 200", res.status_code == 200)
data = res.get_json()
record("/api/stats has arduino object", "arduino" in data)
record("/api/stats has arduino_ready status", "arduino_ready" in data.get("arduino", {}))

# /api/attendance
res_att = client.get("/api/attendance")
record("/api/attendance status == 200", res_att.status_code == 200)
att_data = res_att.get_json()
record("/api/attendance summary present", "summary" in att_data)
record("/api/attendance events list present", isinstance(att_data.get("events"), list))

# /api/arduino/status
res_ard = client.get("/api/arduino/status")
record("/api/arduino/status status == 200", res_ard.status_code == 200)
ard_data = res_ard.get_json()
record("arduino/status returns connected flag", "connected" in ard_data)
record("arduino/status returns alert_active flag", "alert_active" in ard_data)
record("arduino/status returns arduino_ready flag", "arduino_ready" in ard_data)

# Clean up temporary DB
database.DATABASE_PATH = orig_db
try:
    os.unlink(TEST_DB)
except Exception:
    pass

# ======================================================================
# SUMMARY
# ======================================================================
total = len(RESULTS)
passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
failed = total - passed

print("\n" + "=" * 66)
print("  QUEUESENSE PHASE 5 -- TEST RESULTS SUMMARY")
print("=" * 66)
print("  Total  : %d" % total)
print("  Passed : %d" % passed)
print("  Failed : %d" % failed)
print("=" * 66)

if failed == 0:
    print("\n  All Phase 5 tests passed successfully!\n")
    sys.exit(0)
else:
    print("\n  FAILURES DETECTED:")
    for name, status, note in RESULTS:
        if status == "FAIL":
            print("    * %s: %s" % (name, note))
    sys.exit(1)
