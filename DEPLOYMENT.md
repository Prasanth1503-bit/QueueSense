# QueueSense – Streamlit & Supabase Cloud Deployment Guide

This guide details how to deploy the QueueSense Dashboard to **Streamlit Community Cloud** and connect your cloud database with **Supabase PostgreSQL**.

---

## 1. Overview Architecture

```
┌────────────────────────┐         ┌─────────────────────────────────┐
│ Local Machine / Edge   │         │ Cloud (Streamlit + Supabase)    │
│                        │         │                                 │
│  [YOLO Camera Monitor] ├────────►│  [Supabase PostgreSQL Cloud]    │
│      monitor.py        │  Writes │         (Queue History &        │
│                        │   Data  │          Attendance DB)         │
│  [Arduino Uno + RFID]  ├────────►│                ▲                │
│   QueueSense_RFID.ino  │         │                │ Reads/Writes   │
└────────────────────────┘         │  [Streamlit Cloud Dashboard]    │
                                   │       streamlit_app.py          │
                                   └─────────────────────────────────┘
```

Both the local YOLO monitor and the Streamlit dashboard communicate via the shared **Supabase PostgreSQL Cloud Database** using the standard `DATABASE_URL`.

---

## 2. Setting Up Supabase PostgreSQL Cloud

1. **Create Project**:
   - Go to [https://supabase.com](https://supabase.com) and create a free project.

2. **Run the Database Schema**:
   - Open your project on Supabase and navigate to the **SQL Editor** tab.
   - Open [supabase_schema.sql](file:///d:/QueueSense/supabase_schema.sql) in this repository, copy its content, and paste it into the Supabase SQL Editor.
   - Click **Run**. This creates:
     - `queue_status` (Live queue occupancy)
     - `queue_history` (Historical snapshots)
     - `queue_alert_limits` (Threshold limits)
     - `attendance_events` (RFID student scans)

3. **Obtain Connection String**:
   - In Supabase, go to **Project Settings** -> **Database**.
   - Under **Connection String**, select **URI** (or Transaction Pooler on port `6543`).
   - Copy the URI:
     ```
     postgresql://postgres.[YOUR-PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres
     ```

---

## 3. Deploying to Streamlit Community Cloud

1. **Push your code to GitHub**:
   - Commit and push your changes to your GitHub repository:
     ```bash
     git add .
     git commit -m "Add Streamlit dashboard and Supabase integration"
     git push origin main
     ```

2. **Create New Streamlit App**:
   - Go to [https://share.streamlit.io/](https://share.streamlit.io/)
   - Click **New app**.
   - Select your repository, branch (`main`), and set the main file path to:
     ```
     streamlit_app.py
     ```

3. **Configure Secrets (Supabase Credentials)**:
   - Click **Advanced Settings** -> **Secrets**.
   - Add your Supabase PostgreSQL connection string:
     ```toml
     DATABASE_URL = "postgresql://postgres.[YOUR-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres"
     ```
   - Click **Save**.

4. **Deploy**:
   - Click **Deploy!**
   - Streamlit Cloud will install dependencies from `requirements.txt` and launch your dashboard with a public URL (e.g., `https://queuesense.streamlit.app`).

---

## 4. Running Streamlit Locally

To test or run the Streamlit dashboard on your local machine:

### Windows:
Double-click `run_dashboard.bat` or run:
```powershell
.\.venv\Scripts\streamlit.exe run streamlit_app.py
```

### Linux / macOS:
```bash
streamlit run streamlit_app.py
```

Open `http://localhost:8501` in your browser.

---

## 5. Local `.env` Configuration

To connect your local computer vision monitor (`monitor.py`) or local dashboard to Supabase:
Create a `.env` file in the project root:
```bash
DATABASE_URL=postgresql://postgres.[YOUR-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres
```
When `DATABASE_URL` is set, `database.py` automatically routes all reads and writes to Supabase PostgreSQL. If left empty, it falls back to the local `queuesense.db` SQLite database.

---

## 6. Running the Hardware & Vision Components

1. **Flash Arduino Uno**:
   - Upload `arduino/QueueSense_RFID.ino` using the Arduino IDE.
2. **Start Monitor**:
   ```powershell
   .\.venv\Scripts\python.exe monitor.py
   ```
   Select your camera or video. Detections will update Supabase / database in real time and reflect instantly on the Streamlit dashboard!
