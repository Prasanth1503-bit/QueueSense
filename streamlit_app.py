"""
QueueSense – Smart Queue Intelligence System
Streamlit Cloud & Local Real-Time Dashboard
Utilizes native Streamlit Fragments (@st.fragment) for fluid, zero-flicker, real-time live video and attendance updates.
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
    is_postgres,
    get_live_frame,
    get_hardware_status,
    save_attendance_event,
    normalize_queue_name
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

# Custom Styling (Dark Neon Aesthetics + Total Dimming Suppression)
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
        background: rgba(18, 24, 38, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 18px 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
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
    
    /* Complete suppression of all dimming, fading, and flashing in Streamlit */
    .stApp,
    .main,
    header,
    [data-testid="stApp"],
    [data-testid="stMain"],
    [data-testid="stMainBlockContainer"],
    [data-testid="stAppViewBlockContainer"],
    [data-testid="stAppViewContainer"],
    div[data-testid="stAppViewContainer"] > section:first-child,
    .stApp[data-test-script-state="running"],
    .stApp[data-test-script-state="running"] [data-testid="stMainBlockContainer"],
    .stApp[data-test-script-state="running"] .main,
    .stApp[data-test-script-state="running"] header,
    [data-test-script-state="running"] {
        opacity: 1 !important;
        filter: none !important;
        transition: none !important;
        animation: none !important;
    }
    
    [data-test-script-state="running"] * {
        opacity: 1 !important;
        filter: none !important;
        transition: none !important;
    }
    
    /* Hide running widget spinner to stop visual blinking */
    div[data-testid="stStatusWidget"],
    .stStatusWidget {
        display: none !important;
        visibility: hidden !important;
    }
</style>
""", unsafe_allow_html=True)

BASE_DIR = Path(__file__).resolve().parent
LIVE_FRAME_PATH = BASE_DIR / "static" / "live_frame.jpg"
SERVICE_SECONDS_PER_PERSON = int(os.getenv("SERVICE_SECONDS_PER_PERSON", 25))

# Auto-start hardware bridge if running locally on a system with serial
if bridge and not bridge.connected and not bridge.thread:
    try:
        bridge.start()
    except Exception:
        pass

# Sidebar controls & Info
with st.sidebar:
    st.markdown("### ⚡ QueueSense System")
    db_info = get_db_info()
    if db_info.get("is_cloud"):
        st.markdown(f'<div class="db-pill-cloud">☁️ Supabase Cloud DB Connected</div>', unsafe_allow_html=True)
        st.caption(f"Target: `{db_info['target']}`")
    elif db_info.get("error"):
        st.markdown(f'<div class="db-pill-local" style="border-color: #ef4444; color: #f87171;">⚠️ Cloud Auth Error</div>', unsafe_allow_html=True)
        st.caption("Password auth failed. Check Tab '☁️ Supabase Cloud Settings'.")
    else:
        st.markdown(f'<div class="db-pill-local">📁 Local SQLite Database</div>', unsafe_allow_html=True)
        st.caption("Add `DATABASE_URL` in secrets to switch to Supabase PostgreSQL.")

    st.markdown("---")
    st.markdown("### 🟢 Live Engine")
    st.success("Active · Real-time auto-refreshing")
    st.caption("Zero-flicker updates powered by Streamlit Fragments.")

    st.markdown("---")
    
    # Hardware Status
    st.markdown("### 🔌 Hardware Bridge")
    hw = get_hardware_status()
    if bridge and bridge.connected:
        st.success(f"🟢 Arduino Online ({bridge.port_name})")
        if bridge.alert_active:
            st.error("🚨 BUZZER ACTIVE (Over limit)")
        else:
            st.info("Buzzer Idle · Capacity Guard Active")
    elif hw.get("is_online"):
        port_label = hw.get("port") or "COM"
        st.success(f"🟢 Arduino Online ({port_label})")
        st.caption("⚡ Linked via Local PC Hardware Bridge")
        if hw.get("alert_active"):
            st.error("🚨 BUZZER ACTIVE (Over limit)")
        else:
            st.info("Buzzer Idle · Capacity Guard Active")
    elif bridge:
        st.warning("⚪ Arduino Offline")
        st.caption("Plug Arduino into local PC USB and run `run_dashboard.bat`.")
    else:
        st.info("⚪ Hardware Bridge Inactive")
        st.caption("Run `run_dashboard.bat` locally to link physical Arduino buzzer & RFID.")

    st.markdown("---")
    st.caption("QueueSense v2.0 · Fluid Cloud Edition")

# Top Header Banner
col_head1, col_head2 = st.columns([3, 1])
with col_head1:
    st.markdown('<div class="brand-title">QueueSense Intelligence</div>', unsafe_allow_html=True)
    st.markdown('<div class="brand-sub">Real-Time Queue Monitoring, RFID Attendance & Hardware Alarm Controls</div>', unsafe_allow_html=True)
with col_head2:
    st.caption(f"Status: 🟢 Live · Auto-sync active")
    if st.button("🔄 Refresh All Data", use_container_width=True):
        st.rerun()

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
# TAB 1: OVERVIEW (Isolated 1.0s Fragment — Real-Time Live Metrics)
# ==============================================================================
@st.fragment(run_every=1.0)
def render_overview_fragment():
    queues = get_queue_statistics(max_age_seconds=5)
    limits = get_queue_alert_limits()
    attendance_summary = get_attendance_summary()

    total_waiting = sum(int(q.get("occupancy", 0) or 0) for q in queues.values())
    active_count = len(queues)

    shortest_queue = None
    shortest_wait = None
    lower_limits = {str(k).strip().lower(): v for k, v in limits.items()}

    for name, stats in queues.items():
        occ = max(0, int(stats.get("occupancy", 0) or 0))
        wait = occ * SERVICE_SECONDS_PER_PERSON
        stats["estimated_wait_seconds"] = wait

        clean = str(name).strip().lower()
        norm = normalize_queue_name(name)
        limit_info = limits.get(name) or limits.get(norm) or lower_limits.get(clean) or lower_limits.get(norm)
        limit_val = int(limit_info.get("limit_people", 3)) if limit_info else 3
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

    # Sync bridge if local
    if bridge:
        try:
            bridge.update_hardware_alerts(queues)
        except Exception:
            pass

    # Metric KPI cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-label">Queue Occupancy</div>
            <div class="metric-num" style="color: #38bdf8;">{total_waiting}</div>
            <small style="color: #64748b;">People waiting in queues</small>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-label">Active Queues</div>
            <div class="metric-num" style="color: #c084fc;">{active_count}</div>
            <small style="color: #64748b;">Monitored camera zones</small>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-label">RFID Card Scans</div>
            <div class="metric-num" style="color: #34d399;">{attendance_summary.get('total_events', 0)}</div>
            <small style="color: #64748b;">{attendance_summary.get('total_entries', 0)} IN · {attendance_summary.get('total_exits', 0)} OUT</small>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-label">Unique Students</div>
            <div class="metric-num" style="color: #fb923c;">{attendance_summary.get('unique_students', 0)}</div>
            <small style="color: #64748b;">Verified attendance IDs</small>
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

    st.markdown("<br>", unsafe_allow_html=True)
    
    # Quick glance at latest attendance
    st.markdown("### 🪪 Recent RFID Attendance Activity")
    recent_events = get_attendance_events(limit=5)
    if recent_events:
        rec_display = []
        for ev in recent_events:
            rec_display.append({
                "Timestamp": ev.get("event_time", "") or "—",
                "Student Name": ev.get("student_name") or "Unknown",
                "Roll Number": ev.get("roll_number") or "—",
                "Card UID": ev.get("card_uid") or "—",
                "Action": ev.get("event_type") or "—"
            })
        st.dataframe(pd.DataFrame(rec_display), use_container_width=True, hide_index=True)
    else:
        st.caption("No RFID cards scanned yet. Scan card on RFID reader to see live entries and exits.")

with tab_overview:
    render_overview_fragment()


# ==============================================================================
# TAB 2: LIVE CAMERA FEED (Direct 30 FPS Stream + Cloud Synced Mode)
# ==============================================================================
@st.fragment(run_every=0.8)
def render_cloud_camera_fragment():
    col_v1, col_v2 = st.columns([3, 1])

    cloud_bytes = None
    cloud_ts = None
    with col_v1:
        frame_rendered = False
        # 1. Try reading local file bytes directly
        if LIVE_FRAME_PATH.exists():
            try:
                local_bytes = LIVE_FRAME_PATH.read_bytes()
                if len(local_bytes) > 10 and local_bytes.startswith(b"\xff\xd8"):
                    mtime = os.path.getmtime(LIVE_FRAME_PATH)
                    st.image(local_bytes, caption=f"Local Frame Buffer · {datetime.fromtimestamp(mtime).strftime('%H:%M:%S')}", use_container_width=True)
                    frame_rendered = True
            except Exception:
                pass

        # 2. Fall back to cloud frame from Supabase
        if not frame_rendered:
            cloud_bytes, cloud_ts = get_live_frame()
            if cloud_bytes and len(cloud_bytes) > 10:
                try:
                    st.image(cloud_bytes, caption=f"Cloud YOLO Live Stream · Synced ({cloud_ts})", use_container_width=True)
                    frame_rendered = True
                except Exception:
                    pass

        if not frame_rendered:
            st.markdown("""
            <div style="background: #111b2b; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; height: 350px; display: flex; flex-direction: column; justify-content: center; align-items: center; color: #94a3b8;">
                <div style="font-size: 3rem; margin-bottom: 10px;">📹</div>
                <strong style="color: #cbd5e1; font-size: 1.1rem;">Waiting for Video Frames</strong>
                <p style="font-size: 0.9rem; margin-top: 6px;">Start <code>monitor.py</code> locally to stream live YOLO person detection.</p>
            </div>
            """, unsafe_allow_html=True)

    with col_v2:
        st.markdown("#### Stream Diagnostics")
        has_local = LIVE_FRAME_PATH.exists()
        if cloud_bytes is None and not has_local:
            cloud_bytes, cloud_ts = get_live_frame()
        has_cloud = bool(cloud_bytes)
        status_label = "🟢 Receiving (Local)" if has_local else ("🟢 Receiving (Cloud Sync)" if has_cloud else "⚪ Waiting for Stream")
        st.markdown(f"**Status:** {status_label}")
        if cloud_ts:
            st.markdown(f"**Cloud Timestamp:** `{cloud_ts}`")
        st.markdown("""
        **Detection Legend:**
        - 🟩 Green Box: Tracked Person
        - 🟦 Blue Polygon: Monitored Queue Zone
        - 🟥 Red Highlight: Over-Capacity Queue
        """)
        st.caption("⚡ Cloud fragment auto-refreshing at 0.8s")

with tab_video:
    st.markdown("### 📹 Live Camera & YOLO Tracking Feed")
    stream_choice = st.radio(
        "Playback Mode",
        ["⚡ Direct 30 FPS Stream (Zero Lag · Recommended)", "☁️ Database Synced Feed (Cloud Mode)"],
        horizontal=True,
        key="stream_playback_mode"
    )
    if "Direct" in stream_choice:
        import streamlit.components.v1 as components
        components.html("""
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8">
        <style>
          * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
          body { background: transparent; overflow: hidden; }
          .video-container {
            position: relative;
            width: 100%;
            aspect-ratio: 16 / 9;
            max-height: 480px;
            background: #080d18;
            border: 1px solid rgba(140, 163, 197, 0.2);
            border-radius: 12px;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
          }
          #stream-img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
          }
          .hud-badge {
            position: absolute;
            top: 14px;
            left: 14px;
            padding: 6px 14px;
            background: rgba(15, 23, 42, 0.75);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 20px;
            color: #e2e8f0;
            font-size: 12px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
            pointer-events: none;
            z-index: 10;
          }
          .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #22c55e;
            box-shadow: 0 0 8px #22c55e;
            animation: pulse 2s infinite;
          }
          .dot.yellow { background: #eab308; box-shadow: 0 0 8px #eab308; }
          .dot.red { background: #ef4444; box-shadow: 0 0 8px #ef4444; }
          @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(0.9); }
          }
          .hud-controls {
            position: absolute;
            top: 14px;
            right: 14px;
            display: flex;
            gap: 8px;
            z-index: 10;
          }
          .btn-icon {
            background: rgba(15, 23, 42, 0.75);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #cbd5e1;
            border-radius: 8px;
            padding: 6px 10px;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
          }
          .btn-icon:hover { background: rgba(30, 41, 59, 0.9); color: #fff; }
          #standby-card {
            display: none;
            text-align: center;
            color: #94a3b8;
            padding: 30px;
            max-width: 440px;
          }
          #standby-card h4 { color: #f1f5f9; font-size: 1.15rem; margin-bottom: 8px; }
          #standby-card p { font-size: 0.88rem; line-height: 1.5; margin-bottom: 14px; }
          #standby-card code { background: rgba(255,255,255,0.08); padding: 3px 6px; border-radius: 4px; color: #38bdf8; }
        </style>
        </head>
        <body>
        <div class="video-container" id="player-container">
          <div class="hud-badge" id="hud-badge">
            <span class="dot" id="hud-dot"></span>
            <span id="hud-text">Connecting to Live Stream…</span>
          </div>
          <div class="hud-controls">
            <button class="btn-icon" onclick="toggleFullscreen()" title="Fullscreen">⛶ Fullscreen</button>
            <button class="btn-icon" onclick="forceReconnect()" title="Reconnect">↻ Reconnect</button>
          </div>
          <img id="stream-img" alt="Live YOLO Queue Monitor">
          <div id="standby-card">
            <div style="font-size: 2.5rem; margin-bottom: 12px;">📹</div>
            <h4>Live Stream Standby</h4>
            <p>Waiting for live frames. Start <code>monitor.py</code> locally to begin real-time YOLO person detection & queue tracking.</p>
            <button class="btn-icon" onclick="forceReconnect()">Retry Connection</button>
          </div>
        </div>

        <script>
          const host = window.location.hostname || "localhost";
          const mjpegUrl = "http://" + host + ":5000/video_feed";
          const staticUrl = "/app/static/live_frame.jpg";
          const img = document.getElementById("stream-img");
          const dot = document.getElementById("hud-dot");
          const text = document.getElementById("hud-text");
          const standby = document.getElementById("standby-card");

          let mode = "mjpeg"; // "mjpeg" or "static_poll"
          let pollTimer = null;
          let connectionTimeout = null;

          function setStatus(status, label) {
            if (status === "live") {
              dot.className = "dot";
              text.textContent = label || "30 FPS Direct Live Feed";
              img.style.display = "block";
              standby.style.display = "none";
            } else if (status === "poll") {
              dot.className = "dot yellow";
              text.textContent = label || "⚡ Local Fast Buffer (25 FPS)";
              img.style.display = "block";
              standby.style.display = "none";
            } else {
              dot.className = "dot red";
              text.textContent = label || "Stream Standby";
              img.style.display = "none";
              standby.style.display = "block";
            }
          }

          function startMjpeg() {
            mode = "mjpeg";
            if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
            img.src = mjpegUrl + "?t=" + Date.now();
            setStatus("live", "Connecting to 30 FPS Stream…");

            clearTimeout(connectionTimeout);
            connectionTimeout = setTimeout(() => {
              if (mode === "mjpeg" && (!img.complete || img.naturalWidth === 0)) {
                startStaticPoll();
              }
            }, 3000);
          }

          img.onload = () => {
            clearTimeout(connectionTimeout);
            if (mode === "mjpeg") {
              setStatus("live", "30 FPS Direct Live Feed");
            }
          };

          img.onerror = () => {
            clearTimeout(connectionTimeout);
            if (mode === "mjpeg") {
              startStaticPoll();
            } else {
              setStatus("error", "Waiting for monitor.py");
            }
          };

          function startStaticPoll() {
            mode = "static_poll";
            clearTimeout(connectionTimeout);
            if (pollTimer) clearInterval(pollTimer);

            let isFetching = false;
            const fetchNext = () => {
              if (isFetching) return;
              isFetching = true;
              const testImg = new Image();
              testImg.onload = () => {
                img.src = testImg.src;
                setStatus("poll", "⚡ Local Fast Buffer (25 FPS)");
                isFetching = false;
              };
              testImg.onerror = () => {
                isFetching = false;
                setStatus("error", "Waiting for monitor.py");
              };
              testImg.src = staticUrl + "?t=" + Date.now();
            };

            fetchNext();
            pollTimer = setInterval(fetchNext, 40); // 25 FPS
          }

          function forceReconnect() {
            startMjpeg();
          }

          function toggleFullscreen() {
            const el = document.getElementById("player-container");
            if (!document.fullscreenElement) {
              if (el.requestFullscreen) el.requestFullscreen();
              else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
            } else {
              if (document.exitFullscreen) document.exitFullscreen();
            }
          }

          // Start stream
          startMjpeg();
        </script>
        </body>
        </html>
        """, height=480)
        st.caption("⚡ Direct 30 FPS hardware-accelerated video stream with intelligent auto-failover.")
    else:
        render_cloud_camera_fragment()


# ==============================================================================
# TAB 3: RFID ATTENDANCE (Isolated 1.0s Fragment — Instant Real-Time Updates)
# ==============================================================================
@st.fragment(run_every=1.0)
def render_attendance_fragment():
    st.markdown("### 🪪 Student RFID Attendance Records")
    
    attendance_summary = get_attendance_summary()

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

    with st.expander("🧪 Test / Simulate Student RFID Card Tap (No Hardware Needed)"):
        st.markdown("Test instant attendance logging into Supabase Cloud & Local Database:")
        sc1, sc2, sc3 = st.columns([2, 1, 1])
        with sc1:
            test_student = st.selectbox(
                "Select Registered Student Card",
                [
                    ("7b8bf206", "24BCE8221", "G.Prasanth Paul"),
                    ("c1a9f868", "24BCE8253", "G.Prem Sasank"),
                    ("d1157768", "24BCA7344", "T.Mani Sankar"),
                    ("c1784968", "24BCE8263", "D.Dinesh"),
                    ("c189f968", "24BCA7285", "Pardha"),
                    ("d1b3d568", "24BES7016", "G.Aditya"),
                ],
                format_func=lambda s: f"{s[2]} ({s[1]}) — UID: {s[0]}",
                key="test_student_picker"
            )
        with sc2:
            test_action = st.radio("Event Action", ["ENTRY", "EXIT"], horizontal=True, key="test_action_radio")
        with sc3:
            st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
            if st.button("📲 Tap Card", type="primary", use_container_width=True, key="btn_tap_card"):
                uid, roll, sname = test_student
                try:
                    save_attendance_event(uid, roll, sname, test_action)
                    st.success(f"Recorded {test_action} for {sname}!")
                except Exception as ex:
                    st.error(f"Error saving attendance: {ex}")
    
    # Search box
    search_query = st.text_input("🔍 Search by Student Name, Roll Number, or Card UID:", "", placeholder="Type name, roll, or card UID...", key="attendance_search_input")
    
    # Attendance events table
    events = get_attendance_events(limit=150, search=search_query)
    if events:
        df_events = pd.DataFrame(events)
        df_display = df_events[["id", "event_time", "student_name", "roll_number", "card_uid", "event_type"]].copy()
        df_display.columns = ["ID", "Timestamp", "Student Name", "Roll Number", "Card UID", "Event"]
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.info("No attendance events found.")

with tab_attendance:
    render_attendance_fragment()


# ==============================================================================
# TAB 4: HARDWARE ALERTS
# ==============================================================================
@st.fragment(run_every=2.0)
def render_limits_fragment():
    current_limits = get_queue_alert_limits()
    all_queue_names = ["student", "faculty", "scholar"]

    # Active synchronized limit indicators
    l_cols = st.columns(3)
    for idx, q_name in enumerate(all_queue_names):
        existing = current_limits.get(q_name, {})
        val = existing.get("limit_people", 3)
        with l_cols[idx]:
            st.markdown(f"""
            <div style="background: rgba(15,23,42,0.6); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 14px; text-align: center;">
                <div style="font-size: 0.85rem; color: #94a3b8; text-transform: uppercase; font-weight: 700;">{q_name.upper()}</div>
                <div style="font-size: 2.2rem; font-weight: 800; color: #38bdf8; margin: 4px 0;">{val}</div>
                <small style="color: #64748b;">Current Active Limit</small>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    with st.form("alert_limits_form"):
        st.markdown("##### ⚙️ Update Capacity Thresholds")
        updated_values = {}
        form_cols = st.columns(3)
        for idx, q_name in enumerate(all_queue_names):
            existing = current_limits.get(q_name, {})
            current_val = existing.get("limit_people", 3)
            with form_cols[idx]:
                updated_values[q_name] = st.number_input(
                    f"Max capacity: '{q_name}'",
                    min_value=1,
                    max_value=100,
                    value=int(current_val),
                    step=1,
                    key=f"limit_input_{q_name}"
                )
        submit_limits = st.form_submit_button("💾 Save Alert Limits (Sync to Flask & Hardware)", use_container_width=True)
        if submit_limits:
            for q_name, val in updated_values.items():
                save_queue_alert_limit(q_name, val)
            st.success("Queue alert limits saved and synchronized to Flask & Arduino!")
            time.sleep(0.5)
            st.rerun()

with tab_limits:
    st.markdown("### 🔔 Hardware Buzzer & Queue Limits")
    st.markdown("Configure max capacity per queue. When occupancy exceeds these limits, the Arduino buzzer triggers.")
    render_limits_fragment()

    st.markdown("---")
    st.markdown("#### Physical Hardware Setup Guide")
    st.markdown("""
    - **Arduino Pin 2**: Connect Active Buzzer (+)
    - **Arduino Pin 3**: Connect Status LED (+)
    - **Arduino Pin 10, 9, 11, 12, 13**: Connect RC522 RFID Reader
    - **I2C SDA/SCL**: Connect 16x2 LCD Display (0x27)
    """)


# ==============================================================================
# TAB 5: ANALYTICS & HISTORY
# ==============================================================================
with tab_history:
    st.markdown("### 📈 Persistent Historical Queue Analytics")
    
    col_f1, col_f2 = st.columns([1, 1])
    with col_f1:
        hours_filter = st.selectbox("Time Window", [24, 72, 168, 720], format_func=lambda h: f"Last {h} hours ({round(h/24)} days)")
    with col_f2:
        queue_filter = st.selectbox("Filter by Queue", ["All Queues", "student", "faculty", "scholar"])

    q_name_arg = None if queue_filter == "All Queues" else queue_filter
    hist_records = get_queue_history(queue_name=q_name_arg, hours=hours_filter, limit=500)
    summary_data = get_queue_history_summary(hours=hours_filter)

    if summary_data:
        st.markdown("#### Period Peak & Average Occupancies")
        sum_cols = st.columns(len(summary_data))
        for idx, (qn, s) in enumerate(summary_data.items()):
            with sum_cols[idx]:
                st.markdown(f"""
                <div class="metric-box">
                    <div class="metric-label">{qn}</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: #38bdf8;">Peak: {s['peak_occupancy']}</div>
                    <small style="color: #94a3b8;">Average: {s['average_occupancy']} people</small>
                </div>
                """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    if hist_records:
        df_hist = pd.DataFrame(hist_records)
        st.markdown("#### Historical Occupancy Over Time")
        chart_data = df_hist.pivot_table(index="recorded_at", columns="queue_name", values="occupancy", aggfunc="mean").fillna(0)
        st.line_chart(chart_data)
        st.markdown("#### Raw Historical Snapshots")
        st.dataframe(df_hist[["recorded_at", "video_name", "queue_name", "occupancy", "total_entries", "total_exits", "session_id"]], use_container_width=True, hide_index=True)
    else:
        st.info("No historical snapshots found in this time range.")


# ==============================================================================
# TAB 6: SUPABASE CLOUD SETTINGS
# ==============================================================================
with tab_supabase:
    st.markdown("### ☁️ Supabase Cloud PostgreSQL Settings")
    
    db_info = get_db_info()
    st.markdown(f"**Current Engine:** `{db_info['engine']}`")
    st.markdown(f"**Target Host:** `{db_info['target']}`")
    st.markdown(f"**Cloud Status:** `{'Connected (Active)' if db_info['is_cloud'] else 'Local Fallback'}`")
    
    if db_info.get("error"):
        st.error(f"❌ Connection Error: {db_info['error']}")

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
    
    if st.button("🧪 Test Current Database Connection"):
        try:
            stats = get_queue_statistics()
            summary = get_attendance_summary()
            st.success(f" Database connection verified! Found {len(stats)} active queues and {summary['total_events']} attendance records.")
        except Exception as err:
            st.error(f"❌ Connection failed: {err}")
