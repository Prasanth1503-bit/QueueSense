"""
QueueSense – Smart Queue Intelligence System
Streamlit Cloud & Local Dashboard
"""

import os
import time
from datetime import datetime
from pathlib import Path
import pandas as pd
import streamlit as st

# Import database functions
from database import (
    get_queue_statistics,
    get_attendance_events,
    get_attendance_summary,
    get_queue_alert_limits,
    save_queue_alert_limit,
    get_queue_history,
    get_queue_history_summary,
    get_db_info,
    is_postgres
)

# Optional hardware bridge import (if running on a machine with serial)
try:
    from arduino_queue_bridge import bridge
except ImportError:
    bridge = None

# Configure page
st.set_page_config(
    page_title="QueueSense | Smart Queue Intelligence",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling (Dark Neon Aesthetics)
st.markdown("""
<style>
    /* Global styling */
    .main {
        background-color: #0b0f19;
    }
    
    /* Header Gradient */
    .brand-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(135deg, #00f2fe 0%, #4facfe 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .brand-sub {
        color: #94a3b8;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }
    
    /* Metric Cards */
    .metric-box {
        background: rgba(18, 24, 38, 0.8);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 18px 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        backdrop-filter: blur(10px);
    }
    .metric-label {
        font-size: 0.82rem;
        font-weight: 600;
        text-transform: uppercase;
        color: #94a3b8;
        letter-spacing: 0.5px;
    }
    .metric-num {
        font-size: 2.1rem;
        font-weight: 800;
        color: #f8fafc;
        margin: 4px 0;
    }
    
    /* Recommendation Card */
    .rec-card {
        background: linear-gradient(135deg, rgba(6, 182, 212, 0.15) 0%, rgba(59, 130, 246, 0.15) 100%);
        border: 1px solid rgba(6, 182, 212, 0.35);
        border-radius: 14px;
        padding: 20px 24px;
        margin-bottom: 24px;
    }
    
    /* Queue Status Cards */
    .queue-card-green {
        background: rgba(16, 185, 129, 0.06);
        border: 1px solid rgba(16, 185, 129, 0.3);
        border-radius: 12px;
        padding: 16px;
    }
    .queue-card-yellow {
        background: rgba(245, 158, 11, 0.06);
        border: 1px solid rgba(245, 158, 11, 0.3);
        border-radius: 12px;
        padding: 16px;
    }
    .queue-card-red {
        background: rgba(239, 68, 68, 0.08);
        border: 1px solid rgba(239, 68, 68, 0.35);
        border-radius: 12px;
        padding: 16px;
    }
    
    /* Badges */
    .badge-normal {
        background-color: #065f46;
        color: #34d399;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 700;
    }
    .badge-warning {
        background-color: #78350f;
        color: #fbbf24;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 700;
    }
    .badge-danger {
        background-color: #7f1d1d;
        color: #f87171;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 700;
    }
    
    /* Supabase Cloud Pill */
    .db-pill-cloud {
        background: rgba(16, 185, 129, 0.15);
        border: 1px solid #10b981;
        color: #10b981;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        display: inline-block;
    }
    .db-pill-local {
        background: rgba(148, 163, 184, 0.15);
        border: 1px solid #94a3b8;
        color: #cbd5e1;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        display: inline-block;
    }
</style>
""", unsafe_allow_html=True)

# Path to live frame
BASE_DIR = Path(__file__).resolve().parent
LIVE_FRAME_PATH = BASE_DIR / "static" / "live_frame.jpg"
SERVICE_SECONDS_PER_PERSON = int(os.getenv("SERVICE_SECONDS_PER_PERSON", 25))

# Sidebar controls & Info
with st.sidebar:
    st.markdown("### ⚡ QueueSense System")
    db_info = get_db_info()
    if db_info["is_cloud"]:
        st.markdown(f'<div class="db-pill-cloud">☁️ Supabase Cloud DB Connected</div>', unsafe_allow_html=True)
        st.caption(f"Target: `{db_info['target']}`")
    else:
        st.markdown(f'<div class="db-pill-local">📁 Local SQLite Database</div>', unsafe_allow_html=True)
        st.caption("Add `DATABASE_URL` in secrets to switch to Supabase PostgreSQL.")

    st.markdown("---")
    
    # Auto-refresh option
    auto_refresh = st.checkbox("Auto-refresh data", value=True)
    refresh_rate = st.slider("Refresh interval (seconds)", min_value=1, max_value=30, value=3)
    
    st.markdown("---")
    
    # Hardware Status
    st.markdown("### 🔌 Hardware Bridge")
    if bridge and bridge.connected:
        st.success(f"Arduino Online ({bridge.port_name})")
        if bridge.alert_active:
            st.error("🚨 BUZZER ACTIVE (Over limit)")
        else:
            st.info("Buzzer Idle")
    elif bridge:
        st.warning("Arduino Not Detected")
        st.caption("Waiting for USB connection on COM / serial port.")
    else:
        st.info("Cloud Mode (No hardware attached)")

    st.markdown("---")
    st.caption("QueueSense v2.0 · Streamlit & Supabase Edition")

# Top Header Banner
col_head1, col_head2 = st.columns([3, 1])
with col_head1:
    st.markdown('<div class="brand-title">QueueSense Intelligence</div>', unsafe_allow_html=True)
    st.markdown('<div class="brand-sub">Real-Time Queue Monitoring, RFID Attendance & Hardware Alarm Controls</div>', unsafe_allow_html=True)
with col_head2:
    st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")
    if st.button("🔄 Manual Refresh"):
        st.rerun()

# Fetch latest data
queues = get_queue_statistics()
limits = get_queue_alert_limits()
attendance_summary = get_attendance_summary()

# Calculate totals
total_waiting = sum(int(q.get("occupancy", 0) or 0) for q in queues.values())
total_entries = sum(int(q.get("entries", 0) or 0) for q in queues.values())
total_exits = sum(int(q.get("exits", 0) or 0) for q in queues.values())
active_count = len(queues)

# Find shortest queue recommendation
shortest_queue = None
shortest_wait = None
lower_limits = {str(k).strip().lower(): v for k, v in limits.items()}

for name, stats in queues.items():
    occ = max(0, int(stats.get("occupancy", 0) or 0))
    wait = occ * SERVICE_SECONDS_PER_PERSON
    stats["estimated_wait_seconds"] = wait
    
    clean = str(name).strip().lower()
    limit_info = limits.get(name) or lower_limits.get(clean)
    limit_val = int(limit_info.get("limit_people", 5)) if limit_info else 5
    stats["alert_limit"] = limit_val
    stats["alert_active"] = occ > limit_val
    
    if occ > limit_val:
        stats["status_color"] = "red"
        stats["status_text"] = "OVER LIMIT"
    elif occ >= max(1, limit_val - 1) and occ > 0:
        stats["status_color"] = "yellow"
        stats["status_text"] = "NEAR LIMIT"
    else:
        stats["status_color"] = "green"
        stats["status_text"] = "NORMAL"

    if shortest_wait is None or wait < shortest_wait:
        shortest_wait = wait
        shortest_queue = name

# Synchronize hardware alerts if local bridge running
if bridge:
    try:
        bridge.update_hardware_alerts(queues)
    except Exception:
        pass

# Navigation Tabs
tab_overview, tab_video, tab_attendance, tab_limits, tab_history, tab_supabase = st.tabs([
    "📊 Queue Overview",
    "📹 Live Camera Feed",
    "🪪 RFID Attendance",
    "🔔 Hardware Alert Limits",
    "📈 Analytics & History",
    "☁️ Supabase Cloud Settings"
])

# ==============================================================================
# TAB 1: OVERVIEW
# ==============================================================================
with tab_overview:
    # Metric KPI cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-label">People Waiting</div>
            <div class="metric-num" style="color: #38bdf8;">{total_waiting}</div>
            <small style="color: #64748b;">Across all active queues</small>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-label">Confirmed Entries</div>
            <div class="metric-num" style="color: #34d399;">{total_entries}</div>
            <small style="color: #64748b;">Session total</small>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-label">Confirmed Exits</div>
            <div class="metric-num" style="color: #fb923c;">{total_exits}</div>
            <small style="color: #64748b;">Session total</small>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-label">Active Queues</div>
            <div class="metric-num" style="color: #c084fc;">{active_count}</div>
            <small style="color: #64748b;">Monitored zones</small>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Recommendation Banner
    if shortest_queue:
        wait_min = round(shortest_wait / 60, 1)
        st.markdown(f"""
        <div class="rec-card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span style="font-size: 0.8rem; font-weight: 700; color: #38bdf8; text-transform: uppercase;">Smart Recommendation</span>
                    <h3 style="margin: 4px 0; color: #f8fafc;">Recommended: {shortest_queue}</h3>
                    <p style="margin: 0; color: #94a3b8;">This queue has the shortest estimated service wait time right now.</p>
                </div>
                <div style="text-align: right;">
                    <span style="font-size: 0.8rem; color: #94a3b8;">Estimated wait</span>
                    <div style="font-size: 1.8rem; font-weight: 800; color: #34d399;">{shortest_wait}s <small style="font-size: 0.9rem; color: #94a3b8;">({wait_min} min)</small></div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("ℹ️ Waiting for queue occupancy data. Start `monitor.py` to begin computer vision detection.")

    # Queue Details Grid
    st.markdown("### Queue Breakdown & Occupancy")
    if queues:
        q_cols = st.columns(min(len(queues), 3))
        for idx, (q_name, q_data) in enumerate(queues.items()):
            col_target = q_cols[idx % 3]
            with col_target:
                occ = q_data.get("occupancy", 0)
                lim = q_data.get("alert_limit", 5)
                color = q_data.get("status_color", "green")
                badge_class = "badge-normal" if color == "green" else ("badge-warning" if color == "yellow" else "badge-danger")
                card_class = f"queue-card-{color}"

                st.markdown(f"""
                <div class="{card_class}">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <strong style="font-size: 1.1rem; color: #f8fafc;">{q_name}</strong>
                        <span class="{badge_class}">{q_data.get('status_text', 'NORMAL')}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; gap: 8px; margin: 10px 0;">
                        <span style="font-size: 2.5rem; font-weight: 800; color: #f8fafc;">{occ}</span>
                        <span style="color: #94a3b8;">/ limit: {lim}</span>
                    </div>
                    <div style="font-size: 0.85rem; color: #94a3b8; line-height: 1.6;">
                        <div>⏱️ Est. Wait: <strong>{q_data.get('estimated_wait_seconds', 0)}s</strong></div>
                        <div>↙ Entries: <strong>{q_data.get('entries', 0)}</strong> · ↗ Exits: <strong>{q_data.get('exits', 0)}</strong></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                # Progress bar
                ratio = min(1.0, max(0.0, occ / max(1, lim)))
                st.progress(ratio)
    else:
        st.markdown("""
        <div style="background: rgba(255,255,255,0.03); border: 1px dashed rgba(255,255,255,0.15); border-radius: 12px; padding: 30px; text-align: center; color: #94a3b8;">
            <div style="font-size: 2rem; margin-bottom: 10px;">☷</div>
            <strong>No Active Queues Detected</strong>
            <p style="margin-top: 5px; font-size: 0.9rem;">Run <code>monitor.py</code> locally with a camera or video to feed real-time YOLO detections to this dashboard.</p>
        </div>
        """, unsafe_allow_html=True)

# ==============================================================================
# TAB 2: LIVE CAMERA FEED
# ==============================================================================
with tab_video:
    st.markdown("### Live Camera & YOLO Tracking Feed")
    col_v1, col_v2 = st.columns([3, 1])
    with col_v1:
        if LIVE_FRAME_PATH.exists():
            try:
                mtime = os.path.getmtime(LIVE_FRAME_PATH)
                st.image(str(LIVE_FRAME_PATH), caption=f"Live Feed · Last update {datetime.fromtimestamp(mtime).strftime('%H:%M:%S')}", use_container_width=True)
            except Exception as e:
                st.warning(f"Could not read frame: {e}")
        else:
            st.markdown("""
            <div style="background: #1e293b; border-radius: 12px; height: 350px; display: flex; flex-direction: column; justify-content: center; align-items: center; color: #94a3b8;">
                <div style="font-size: 3rem; margin-bottom: 10px;">📹</div>
                <strong>Waiting for Video Frames</strong>
                <p style="font-size: 0.9rem; margin-top: 6px;">Start <code>monitor.py</code> to see annotated live YOLO person detection.</p>
            </div>
            """, unsafe_allow_html=True)
    with col_v2:
        st.markdown("#### Stream Diagnostics")
        st.markdown(f"**Frame Path:** `{LIVE_FRAME_PATH.name}`")
        st.markdown(f"**Status:** {'🟢 Receiving' if LIVE_FRAME_PATH.exists() else '⚪ Waiting'}")
        st.markdown("""
        **Detection Legend:**
        - 🟩 Green Box: Tracked Person
        - 🟦 Blue Polygon: Monitored Queue Zone
        - 🟥 Red Highlight: Over-Capacity Queue
        """)
        if st.button("Capture Instant Snapshot"):
            st.rerun()

# ==============================================================================
# TAB 3: RFID ATTENDANCE
# ==============================================================================
with tab_attendance:
    st.markdown("### 🪪 Student RFID Attendance Records")
    
    # Attendance KPIs
    ak1, ak2, ak3, ak4 = st.columns(4)
    with ak1:
        st.metric("Total Card Scans", attendance_summary.get("total_events", 0))
    with ak2:
        st.metric("Total Entries (IN)", attendance_summary.get("total_entries", 0))
    with ak3:
        st.metric("Total Exits (OUT)", attendance_summary.get("total_exits", 0))
    with ak4:
        st.metric("Unique Students", attendance_summary.get("unique_students", 0))

    st.markdown("<br>", unsafe_allow_html=True)
    
    # Search box
    search_query = st.text_input("🔍 Search by Student Name, Roll Number, or Card UID:", "")
    
    # Attendance events table
    events = get_attendance_events(limit=150, search=search_query)
    if events:
        df_events = pd.DataFrame(events)
        df_display = df_events[["id", "event_time", "student_name", "roll_number", "card_uid", "event_type"]].copy()
        df_display.columns = ["ID", "Timestamp", "Student Name", "Roll Number", "Card UID", "Event"]
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.info("No attendance events matching search criteria found.")

# ==============================================================================
# TAB 4: HARDWARE ALERTS
# ==============================================================================
with tab_limits:
    st.markdown("### 🔔 Hardware Buzzer & Queue Limits")
    st.markdown("Configure max capacity per queue. When occupancy exceeds these limits, the Arduino buzzer triggers.")

    current_limits = get_queue_alert_limits()
    all_queue_names = sorted(list(set(list(queues.keys()) + list(current_limits.keys()) + ["student", "faculty", "scholar"])))

    with st.form("alert_limits_form"):
        updated_values = {}
        for q_name in all_queue_names:
            existing_limit = current_limits.get(q_name, {}).get("limit_people", 3)
            val = st.number_input(f"Max capacity for '{q_name}' queue:", min_value=1, max_value=100, value=int(existing_limit), step=1)
            updated_values[q_name] = val
        
        submitted = st.form_submit_button("💾 Save Alert Limits to Database", type="primary")
        if submitted:
            for q_name, new_val in updated_values.items():
                save_queue_alert_limit(q_name, new_val)
            st.success("✅ Queue limits saved successfully to database!")
            time.sleep(1)
            st.rerun()

# ==============================================================================
# TAB 5: ANALYTICS & HISTORY
# ==============================================================================
with tab_history:
    st.markdown("### 📈 Historical Queue Analytics")
    
    time_filter = st.selectbox("Select Time Range:", [
        ("Last 1 Hour", 1),
        ("Last 6 Hours", 6),
        ("Last 24 Hours", 24),
        ("Last 7 Days (168 Hours)", 168)
    ], format_func=lambda x: x[0])
    
    hours_selected = time_filter[1]
    history_records = get_queue_history(hours=hours_selected, limit=1000)
    history_summary = get_queue_history_summary(hours=hours_selected)
    
    if history_summary:
        st.markdown("#### Queue Occupancy Summary")
        df_sum = pd.DataFrame.from_dict(history_summary, orient="index").reset_index()
        df_sum.columns = ["Queue Name", "Peak Occupancy", "Average Occupancy", "Total Samples"]
        st.dataframe(df_sum, use_container_width=True, hide_index=True)

    if history_records:
        st.markdown("#### Occupancy Trends Over Time")
        df_hist = pd.DataFrame(history_records)
        df_hist["recorded_at"] = pd.to_datetime(df_hist["recorded_at"])
        
        chart_data = df_hist.pivot_table(index="recorded_at", columns="queue_name", values="occupancy", aggfunc="mean").ffill().fillna(0)
        st.line_chart(chart_data, use_container_width=True)
    else:
        st.info(f"No historical records found for the past {hours_selected} hours.")

# ==============================================================================
# TAB 6: SUPABASE CLOUD DATABASE SETTINGS
# ==============================================================================
with tab_supabase:
    st.markdown("### ☁️ Supabase Cloud Database Configuration")
    db_status = get_db_info()
    
    if db_status["is_cloud"]:
        st.success(f" Connected to Supabase Cloud PostgreSQL: `{db_status['target']}`")
    else:
        st.warning(" Currently using Local SQLite (`queuesense.db`).")
        if hasattr(st, "secrets") and len(st.secrets) > 0:
            st.info(f"Detected secrets keys in Streamlit: `{list(st.secrets.keys())}`")
            if "DATABASE_URL" in st.secrets:
                val = str(st.secrets["DATABASE_URL"]).strip()
                if "[" in val or "]" in val:
                    st.error("⚠️ Detected square brackets `[` or `]` in your password! Please edit Secrets and remove the brackets.")
                elif not val.startswith(("postgres://", "postgresql://")):
                    st.error(f"⚠️ DATABASE_URL must start with `postgresql://` (current value starts with `{val[:12]}...`)")
                else:
                    st.info("DATABASE_URL found. Testing connection...")
            else:
                st.error("⚠️ `DATABASE_URL` key not found in secrets. Please make sure the key name is exactly `DATABASE_URL = \"...\"`.")
        else:
            st.info("ℹ️ No secrets detected yet. Go to App Settings -> Secrets to add your `DATABASE_URL`.")

    st.markdown("""
    #### 🚀 How to Connect Supabase Cloud PostgreSQL to Streamlit:
    
    1. **Create a Free Project on Supabase**:
       - Go to [https://supabase.com](https://supabase.com) and create a project.
    
    2. **Run the Database Schema**:
       - Open your Supabase Dashboard -> **SQL Editor**.
       - Copy and run the SQL code from [`supabase_schema.sql`](file:///d:/QueueSense/supabase_schema.sql).
    
    3. **Get your Connection String**:
       - In Supabase, go to **Project Settings** -> **Database**.
       - Under **Connection String**, select **URI** (or Transaction Pooler on port 6543).
       - Copy the URI: `postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres`
    
    4. **Add to Streamlit Secrets (for Streamlit Cloud Deployment)**:
       - In your Streamlit Cloud app settings, add under **Secrets**:
       ```toml
       DATABASE_URL = "postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres"
       ```
    
    5. **Or Add to Local `.env` file**:
       ```bash
       DATABASE_URL=postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
       ```
    """)
    
    # Test connection button
    if st.button("🧪 Test Current Database Connection"):
        try:
            stats = get_queue_statistics()
            summary = get_attendance_summary()
            st.success(f" Database connection verified! Found {len(stats)} active queues and {summary['total_events']} attendance records.")
        except Exception as err:
            st.error(f"❌ Connection failed: {err}")

# Auto-refresh loop
if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
