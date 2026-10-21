# QueueSense – Smart Queue Intelligence System

## Overview
QueueSense monitors physical queues using a YOLO-powered camera feed, tracks
occupancy in real time, stores history in SQLite, and integrates with an Arduino
Uno for RFID attendance and buzzer alerts.

---

## Project Structure

```
D:\QueueSense\
│
├── streamlit_app.py           # Streamlit Cloud & local intelligence dashboard
├── run_dashboard.bat          # One-click Windows launcher for Streamlit dashboard
├── database.py                # Dual DB connector (Supabase PostgreSQL + SQLite)
├── supabase_schema.sql        # Supabase PostgreSQL cloud database schema
├── monitor.py                 # YOLO + ByteTrack vision monitor (run separately)
├── arduino_queue_bridge.py    # USB serial owner: buzzer control + RFID parsing
├── app.py                     # Flask web server & REST API
│
├── DEPLOYMENT.md              # Streamlit Cloud & Supabase deployment guide
├── .env.example               # Environment variables configuration template
├── requirements.txt           # Python dependencies
│
├── arduino\
│   └── QueueSense_RFID.ino    # Arduino Uno firmware (RC522 RFID + 16x2 I2C LCD + Buzzer + LED)
│
├── src\
│   └── queue_manager.py       # Queue occupancy / entry / exit logic
│
├── tests\
│   ├── test_queuesense_phase3.py  # Full Phase 3 test suite (99 tests)
│   ├── test_queuesense_phase5.py  # Full Phase 5 hardware integration test suite (65 tests)
│   ├── test_usb_webcam.py         # Camera diagnostic tool
│   └── test_video.py              # Video playback test
│
├── templates\
│   └── index.html             # Dashboard HTML (RFID section, alert limits, live feed)
│
├── static\
│   ├── style.css              # Dashboard CSS (Arduino/RFID additions)
│   └── live_frame.jpg         # Written by monitor.py, read by dashboard
│
├── videos\                    # Video sample files
└── yolo26n.pt                 # YOLO model weights
```

---

## Database Tables

| Table | Purpose |
|---|---|
| `queue_status` | Current occupancy for each monitored queue |
| `queue_history` | Historical snapshots (preserved across restarts) |
| `queue_alert_limits` | Per-queue buzzer trigger thresholds |
| `attendance_events` | RFID scan records (separate from queue data) |

---

## Installation

### Step 1 – Install Python dependencies

```powershell
cd D:\QueueSense
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

For GPU acceleration (CUDA 12.8):
```powershell
.\.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

### Step 2 – Verify imports

```powershell
.\.venv\Scripts\python.exe -c "import database; import arduino_queue_bridge; import app; print('All imports OK')"
```

### Step 3 – Run the integration test suites

```powershell
# Phase 3 core test suite (99 tests)
.\.venv\Scripts\python.exe tests\test_queuesense_phase3.py

# Phase 5 Arduino & hardware protocol test suite (65 tests)
.\.venv\Scripts\python.exe tests\test_queuesense_phase5.py
```

Expected output: `Total: 164  Passed: 164  Failed: 0`

---

## Running the System

**Start your dashboard (Streamlit or Flask) FIRST, then run the monitor in a second window.**

### Window 1 – Streamlit Dashboard

**Launch Dashboard (Recommended):**
```powershell
cd D:\QueueSense
.\run_dashboard.bat
# or: .\.venv\Scripts\streamlit.exe run streamlit_app.py
```
Open **http://localhost:8501** in your browser.

*(For full Streamlit Cloud deployment & Supabase setup, see [DEPLOYMENT.md](file:///d:/QueueSense/DEPLOYMENT.md))*




### Window 2 – Queue monitor (YOLO + video)

```powershell
cd D:\QueueSense
.\.venv\Scripts\python.exe monitor.py
```

Follow the on-screen prompts to select a video and draw ROI polygons.

---

## Arduino Hardware Integration

### Arduino Firmware Location
The Arduino sketch is located at [`arduino/QueueSense_RFID.ino`](file:///D:/QueueSense/arduino/QueueSense_RFID.ino).

### Pin Wiring

| Component | Pin | Arduino Uno Connection |
|---|---|---|
| **RC522 RFID** | VCC | **3.3V** (Do NOT connect to 5V!) |
| | RST | Pin 9 |
| | GND | GND |
| | MISO | Pin 12 |
| | MOSI | Pin 11 |
| | SCK | Pin 13 |
| | SDA (SS) | Pin 10 |
| **I2C 16x2 LCD** | VCC | 5V |
| | GND | GND |
| | SDA | A4 (or dedicated SDA pin) |
| | SCL | A5 (or dedicated SCL pin) |
| | *Address* | Default `0x27` (or `0x3F`). Adjust contrast potentiometer if blank. |
| **Buzzer** | (+) | Pin 2 (Active buzzer) |
| | (-) | GND |
| **LED** | Anode (+) | Pin 3 (through 220–330Ω resistor) |
| | Cathode (-) | GND |

### Required Arduino Libraries (Install via Arduino IDE Library Manager)
1. **MFRC522** by GithubCommunity
2. **LiquidCrystal_I2C** by Frank de Brabander

### Confirmed Serial Protocol (9600 Baud)

#### Arduino → Python:
- `QUEUESENSE_READY` — sent once when Arduino completes `setup()`
- `RFID,<uid>,<roll>,<name>,ENTRY` — known registered student scanned (entering)
- `RFID,<uid>,<roll>,<name>,EXIT` — known registered student scanned (exiting)
- `RFID,<uid>,,Unknown,UNKNOWN` — unregistered card scanned

#### Python → Arduino:
- `BUZZER,ON` — sent when any queue occupancy exceeds its alert threshold
- `BUZZER,OFF` — sent when all queues return within acceptable limits

---

## Pre-configured Students List in Firmware

| UID (Hex) | Roll Number | Student Name |
|---|---|---|
| `7b8bf206` | 24BCE8221 | G.Prasanth Paul |
| `c1a9f868` | 24BCE8253 | G.Prem Sasank |
| `d1157768` | 24BCA7344 | T.Mani Sankar |
| `c1784968` | 24BCE8263 | D.Dinesh |
| `c189f968` | 24BCA7285 | Pardha |
| `d1b3d568` | 24BES7016 | G.Aditya |

---

## Step-by-Step Physical Hardware Testing

1. **Flash the Arduino:**
   - Open Arduino IDE.
   - Open [`arduino/QueueSense_RFID.ino`](file:///D:/QueueSense/arduino/QueueSense_RFID.ino).
   - Select Board: `Arduino Uno`, select your COM port.
   - Click **Upload**.
   - After upload, the 16x2 LCD should display:
     ```
     QueueSense RFID
     Scan your card
     ```

2. **Start the Flask Web App:**
   - Run `.\.venv\Scripts\python.exe app.py`.
   - The console will display:
     ```
     [Arduino] Connected on COMx
     [Arduino] QueueSense firmware ready.
     ```
   - In the web dashboard at `http://127.0.0.1:5000`, the top-right tag under Hardware Alerts will show:
     `Connected · COMx`

3. **Test Card Scans (RFID Attendance):**
   - Tap any registered card (e.g., G.Prasanth Paul `7b8bf206`):
     - Short beep (120ms) and LED blink.
     - LCD displays:
       ```
       G.Prasanth Paul
       24BCE8221 IN
       ```
     - Python logs: `[RFID] G.Prasanth Paul (24BCE8221) ENTRY`
     - Flask web dashboard updates within 5s showing entry in the Student Attendance table.
   - Tap the same card again after 2 seconds:
     - Short beep and LED blink.
     - LCD displays:
       ```
       G.Prasanth Paul
       24BCE8221 OUT
       ```
     - Python logs: `[RFID] G.Prasanth Paul (24BCE8221) EXIT`
   - Tap an unregistered card:
     - Long beep (500ms).
     - LCD displays:
       ```
       Unknown card
       <uid>
       ```
     - Python logs: `[RFID] Unknown (unknown card) UNKNOWN`

4. **Test Queue Alarm:**
   - In the dashboard, lower the alert limit for a queue (e.g. set to `2` people).
   - When YOLO detects > 2 people in that queue:
     - Python sends `BUZZER,ON`.
     - Buzzer sounds continuously.
     - LCD displays:
       ```
       QUEUE LIMIT ALERT
       Please wait...
       ```
     - Dashboard tag shows `Connected · COMx · ALARM ON`.
   - When queue occupancy drops back to 2 or fewer:
     - Python sends `BUZZER,OFF`.
     - Buzzer turns off immediately.
     - LCD resets to `QueueSense RFID / Scan your card`.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Dashboard |
| GET | `/api/stats` | Queue occupancy, estimated waits, alert limits, Arduino status |
| GET | `/api/attendance` | RFID attendance events + summary (searchable via `?search=...`) |
| GET | `/api/alert-limits` | Current per-queue alert limits |
| POST | `/api/alert-limits` | Update a queue's alert limit |
| POST | `/api/queue-occupancy` | Monitor → Flask occupancy push |
| GET | `/api/arduino/status` | Arduino connection status and alert state |
| GET | `/video_feed` | MJPEG live video stream |

---

## Summary of All Changes

| File | Change |
|---|---|
| `arduino/QueueSense_RFID.ino` | **Created** — Full Arduino sketch with RC522 RFID, 16x2 I2C LCD, active buzzer, status LED, 1500ms debounce, and 6 student records. |
| `arduino_queue_bridge.py` | **Updated** — Complete bidirectional serial owner: handles `QUEUESENSE_READY`, parses 5-part RFID CSV (including unknown cards with empty roll), controls buzzer state machine, logs attendance to SQLite. |
| `app.py` | **Fixed & Updated** — Removed duplicated content. Fully exposes `bridge.status()` (including `arduino_ready`) via `/api/stats` and `/api/arduino/status`. |
| `templates/index.html` | **Cleaned & Verified** — Removed stray separator at line 1, removed duplicate CSS include, verified real-time dashboard updates. |
| `tests/test_queuesense_phase3.py` | **Created** — 99 unit/integration tests for database, API, queue manager, and error handling. |
| `tests/test_queuesense_phase5.py` | **Created** — 65 integration tests for Arduino sketch, registered student list, serial handshake, unknown cards, buzzer dispatch, and Flask API. |
| `requirements.txt` | **Updated** — Added `pyserial>=3.5`. |
| `README.md` | **Updated** — Complete documentation with wiring diagram, serial protocol, student table, and testing instructions. |
