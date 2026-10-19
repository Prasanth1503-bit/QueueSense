# QueueSense – Smart Queue Intelligence System

QueueSense is an AI-powered computer vision system designed to monitor, track, analyze, and optimize physical queues in real time. It detects individuals, tracks their movement across user-defined polygon Regions of Interest (ROIs), calculates wait times, triggers overcrowding alerts, and provides a sleek live analytics dashboard.

---

## 🚀 Key Features

- **Multi-Source Vision Pipeline**:
  - Prerecorded video files (`.mp4`, `.avi`, `.mov`, `.mkv`, `.webm` from `videos/` folder)
  - Built-in laptop camera
  - External USB webcam with automated camera index scanning (0–4)
- **Computer Vision & Tracking**:
  - Person detection powered by YOLO (nano model, class 0)
  - Multi-object tracking with **ByteTrack** for persistent track IDs
  - Multi-anchor polygon containment test for accurate queue assignment
- **Queue Analytics & Metrics**:
  - Live occupancy count per queue
  - Entry and exit event detection with time confirmation
  - Elapsed and estimated waiting time calculations (25s baseline / person)
  - Optimal queue recommendation banner
- **Persistent Storage & History**:
  - SQLite database (`queuesense.db`) with current status and historical snapshots
  - Video fingerprinting (SHA-256) and unique session tracking
  - Throttled database writes for high performance and low disk latency
- **Modern Web Dashboard**:
  - Dark glassmorphism UI with responsive multi-column queue cards
  - Real-time MJPEG live stream with sub-second latency
  - Interactive multi-line history charts with Chart.js
  - Overcrowding visual badge and Web Audio API alerts
  - Session and video historical record filters

---

## 📁 Project Structure

```
QueueSense/
├── app.py                  # Flask dashboard server & REST API (PORT 5000)
├── database.py             # SQLite helper (schema, status & history operations)
├── monitor.py              # Main monitoring script (YOLO + ByteTrack + ROI + DB)
├── requirements.txt        # Python package dependencies
├── README.md               # Project documentation & run guide
├── yolo26n.pt              # YOLO model weights
├── queuesense.db           # SQLite database
├── src/
│   └── queue_manager.py    # QueueManager logic (occupancy, entry/exit, timers)
├── templates/
│   └── index.html          # Dashboard HTML template (single-page app)
├── static/
│   ├── style.css           # Dashboard CSS design system
│   └── live_frame.jpg      # Live camera frame shared buffer
├── videos/                 # Prerecorded sample video files
└── tests/
    ├── test_video.py       # Diagnostic script for YOLO & ByteTrack verification
    └── test_usb_webcam.py  # Diagnostic tool to scan and test connected cameras
```

---

## 🛠️ Setup & Installation

### 1. Prerequisites
- Python 3.10+
- (Optional) NVIDIA GPU with CUDA 12.8 support for hardware-accelerated inference

### 2. Activate Virtual Environment
```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```
> **Note for CUDA GPU acceleration**:
> If you have a supported NVIDIA GPU, install PyTorch with CUDA:
> ```bash
> pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
> ```

---

## 🚦 How to Run the Project

QueueSense runs in two decoupled processes for high reliability and responsiveness:

### Step 1: Start the Dashboard Server (Terminal 1)
```powershell
python app.py
```
- Starts the Flask server at **`http://127.0.0.1:5000`**.
- Open your browser and navigate to `http://127.0.0.1:5000`.

### Step 2: Start QueueSense Monitor (Terminal 2)
```powershell
python monitor.py
```

1. **Select Input Source**:
   - `1`: Prerecorded video (select from listed files in `videos/`)
   - `2`: Laptop built-in camera
   - `3`: External USB webcam (automatically scans and lists available cameras)
2. **Select Number of Queues**:
   - Choose 1, 2, or 3 queues to monitor.
3. **Draw Polygon ROIs** on the first video frame:
   - **Left Click**: Add a corner point.
   - **Near First Point**: Close the polygon.
   - **Right Click / Z**: Undo last corner point.
   - **C / R**: Clear and redraw current polygon.
   - **Enter**: Confirm the closed polygon.
   - **Q**: Cancel.
4. **Monitoring Runs**:
   - Live OpenCV window displays tracking boxes, IDs, and occupancy statistics.
   - Live stream updates on the dashboard at `http://127.0.0.1:5000`.
   - Press **`Q`** in the OpenCV window to stop monitoring cleanly.

---

## 🔍 Diagnostic & Testing Tools

QueueSense includes diagnostic utilities in the `tests/` folder:

1. **Test USB Webcam / Connected Cameras**:
   ```powershell
   python tests/test_usb_webcam.py
   ```
   Scans camera indices 0 to 4, displays detected resolutions, and opens a test stream with FPS counter.

2. **Test YOLO Person Detection & ByteTrack**:
   ```powershell
   python tests/test_video.py
   ```
   Verifies that YOLO and ByteTrack operate properly on sample video files.

---

## 🌐 REST API Endpoints

The Flask server (`app.py`) provides the following endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/` | `GET` | Main QueueSense live dashboard |
| `/video_feed` | `GET` | MJPEG video stream of the live monitoring frame |
| `/api/stats` | `GET` | Current queue statistics, wait times, and recommended queue |
| `/api/history` | `GET` | Historical records with optional query params (`video_hash`, `session_id`, `queue_name`, `limit`) |
| `/api/history/summary` | `GET` | Aggregated statistics (total entries, exits, avg wait) |
| `/api/history/videos` | `GET` | Distinct recorded video sources |
| `/api/history/sessions` | `GET` | Sessions recorded for a specific video |

---

## 🎓 College Presentation Demo Flow

1. **Show Architecture**: Highlight the decoupled architecture (YOLO + ByteTrack CV engine writing to shared buffer & SQLite, Flask serving async API and MJPEG stream).
2. **Run Diagnostics**: Run `python tests/test_usb_webcam.py` to demonstrate hardware detection.
3. **Start Dashboard**: Show `app.py` running and initial empty / waiting state on browser.
4. **Launch Monitor**: Run `python monitor.py`, choose video or webcam, draw 2 polygon queues (e.g. "Counter A" and "Counter B").
5. **Demonstrate Real-Time Features**:
   - People entering queue -> Occupancy counter increments.
   - Tracking confirmation period prevents false triggers from passers-by.
   - Recommended queue dynamically highlights shortest line.
   - Trigger overcrowding alert by lowering threshold limit in UI settings.
   - View historical charts plotting occupancy trends over time.
