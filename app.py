import os
import time
import threading
from pathlib import Path
from flask import Flask, render_template, jsonify, Response, request

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from database import (get_queue_statistics, get_attendance_events, get_attendance_summary,
                      get_attendance_payload,
                      get_queue_alert_limits, save_queue_alert_limit,
                      get_queue_history, get_queue_history_summary,
                      get_historical_videos, get_historical_queue_names,
                      get_live_frame, get_hardware_status, save_attendance_event,
                      is_postgres)
from arduino_queue_bridge import bridge

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
LIVE_FRAME_PATH = BASE_DIR / "static" / "live_frame.jpg"
SERVICE_SECONDS_PER_PERSON = int(os.getenv("SERVICE_SECONDS_PER_PERSON", 25))


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


_live_occupancy_lock = threading.Lock()
_live_occupancy = {
    "queues": {},
    "timestamp": 0.0,
    "video_name": None
}


@app.route("/")
def dashboard():
    return render_template("index.html")


@app.route("/api/stats")
def get_stats():
    now_m = time.monotonic()
    live_q = None
    with _live_occupancy_lock:
        if now_m - _live_occupancy["timestamp"] < 4.0 and _live_occupancy["queues"]:
            live_q = {k: dict(v) for k, v in _live_occupancy["queues"].items()}

    if live_q is not None:
        queues = live_q
    else:
        queues = get_queue_statistics(max_age_seconds=8)
    shortest = None
    shortest_wait = None
    limits = get_queue_alert_limits()
    lower_limits = {str(k).strip().lower(): v for k, v in limits.items()}

    for name, stats in queues.items():
        occ = max(0, int(stats.get("occupancy", 0) or 0))
        wait = occ * SERVICE_SECONDS_PER_PERSON
        stats["estimated_wait_seconds"] = wait

        clean = str(name).strip().lower()
        limit_info = limits.get(name) or lower_limits.get(clean)
        if not limit_info:
            for lk, lv in lower_limits.items():
                if clean in lk or lk in clean:
                    limit_info = lv
                    break

        limit_val = int(limit_info.get("limit_people", 5)) if limit_info else 5
        stats["alert_limit"] = limit_val
        stats["alert_active"] = occ > limit_val

        # 3-color status: RED (exceeds limit), YELLOW (near limit), GREEN (normal)
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
            shortest = name

    if not queues:
        bridge.set_buzzer(False)
    else:
        bridge.update_hardware_alerts(queues)
    return jsonify({
        "queues": queues,
        "recommended_queue": shortest,
        "recommended_wait_seconds": shortest_wait,
        "monitoring": bool(queues),
        "alert_limits": limits,
        "arduino": bridge.status(),
        "attendance_summary": get_attendance_summary()
    })


@app.route("/api/attendance/simulate", methods=["POST"])
def simulate_attendance():
    data = request.get_json(silent=True) or {}
    card_uid = str(data.get("card_uid", "7b8bf206")).strip()
    roll = str(data.get("roll_number", "24BCE8221")).strip()
    name = str(data.get("student_name", "G.Prasanth Paul")).strip()
    event = str(data.get("event_type", "ENTRY")).strip().upper()
    try:
        event_id = save_attendance_event(card_uid, roll, name, event)
        return jsonify({"success": True, "id": event_id, "summary": get_attendance_summary()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400



@app.route("/api/history")
def api_history():
    try:
        hours = max(1, min(int(request.args.get("hours", 24)), 8760))
        limit = max(1, min(int(request.args.get("limit", 1000)), 10000))
    except ValueError:
        return jsonify({"error": "hours and limit must be integers"}), 400

    records = get_queue_history(
        queue_name=request.args.get("queue") or None,
        hours=hours,
        limit=limit,
        video_hash=request.args.get("video_hash") or None,
        session_id=request.args.get("session_id") or None
    )
    return jsonify({"history": records})


@app.route("/api/history/summary")
def api_history_summary():
    try:
        hours = max(1, min(int(request.args.get("hours", 24)), 8760))
    except ValueError:
        return jsonify({"error": "hours must be an integer"}), 400

    summary = get_queue_history_summary(
        hours=hours,
        video_hash=request.args.get("video_hash") or None,
        session_id=request.args.get("session_id") or None
    )
    return jsonify({"summary": summary})


@app.route("/api/history/videos")
def api_history_videos():
    raw_hours = request.args.get("hours")
    if raw_hours and raw_hours.lower() not in ("all", "0", ""):
        try:
            hours = max(1, min(int(raw_hours), 8760))
        except ValueError:
            return jsonify({"error": "hours must be an integer"}), 400
    else:
        hours = None

    videos = get_historical_videos(hours=hours)
    return jsonify({"videos": videos})


@app.route("/api/history/queues")
def api_history_queues():
    try:
        hours = max(1, min(int(request.args.get("hours", 24)), 8760))
    except ValueError:
        return jsonify({"error": "hours must be an integer"}), 400

    queues = get_historical_queue_names(
        video_hash=request.args.get("video_hash") or None,
        hours=hours
    )
    return jsonify({"queues": queues})


@app.route("/api/attendance")
def attendance():
    try:
        limit = int(request.args.get("limit", 200))
    except ValueError:
        limit = 200
    events, summary = get_attendance_payload(limit, request.args.get("search"))
    return jsonify({
        "events": events,
        "summary": summary
    })


@app.route("/api/alert-limits", methods=["GET", "POST"])
def alert_limits():
    if request.method == "GET":
        limits = get_queue_alert_limits()
        return jsonify({"limits": limits})
    data = request.get_json(silent=True) or {}
    try:
        saved = save_queue_alert_limit(data.get("queue_name", ""), data.get("limit_people"))
        return jsonify({"success": True, "limit": saved})
    except (TypeError, ValueError) as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/queue-occupancy", methods=["POST"])
def receive_queue_occupancy():
    data = request.get_json(silent=True) or {}
    queues = data.get("queues", {})
    if not isinstance(queues, dict):
        return jsonify({"success": False, "error": "queues must be an object"}), 400
    with _live_occupancy_lock:
        _live_occupancy["queues"] = queues
        _live_occupancy["timestamp"] = time.monotonic()
        _live_occupancy["video_name"] = data.get("video_name")
    bridge.update_hardware_alerts(queues)
    return jsonify({"success": True, "arduino": bridge.status()})


@app.route("/api/arduino/status")
def arduino_status():
    st = bridge.status()
    if not st.get("connected"):
        cloud_st = get_hardware_status()
        if cloud_st.get("is_online"):
            return jsonify(cloud_st)
    return jsonify(st)


def create_standby_frame():
    try:
        import cv2
        import numpy as np
        img = np.zeros((480, 854, 3), dtype=np.uint8)
        img[:] = (23, 15, 11)
        cv2.rectangle(img, (12, 12), (842, 468), (45, 35, 25), 1)
        cv2.putText(img, "QueueSense AI Monitor", (240, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 230, 255), 2)
        cv2.putText(img, "Waiting for video frames - Start monitor.py", (200, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (140, 160, 180), 1)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            return buf.tobytes()
    except Exception:
        pass
    return b""


import threading
from shared_frame import read_live_frame

_latest_frame_data = {
    "bytes": None,
    "mtime": 0,
    "timestamp": 0.0
}
_frame_lock = threading.Lock()


@app.route("/api/frame-push", methods=["POST"])
def receive_frame_push():
    """Accept real-time in-memory frame push from remote monitor.py (fallback)."""
    f_bytes = request.get_data()
    if f_bytes and len(f_bytes) > 10 and f_bytes.startswith(b"\xff\xd8"):
        now_sec = time.time()
        with _frame_lock:
            _latest_frame_data["bytes"] = f_bytes
            _latest_frame_data["mtime"] = int(now_sec * 1000000)
            _latest_frame_data["timestamp"] = now_sec
    return "", 204


def _frame_reader_loop():
    """Background fallback reader for cloud/disk frames when shared RAM buffer is idle."""
    last_mtime = 0
    standby = create_standby_frame()
    while True:
        try:
            # If shared memory has live frames (< 4s old), skip disk/cloud polling entirely
            shm_live = read_live_frame(max_age_seconds=4.0)
            if shm_live is not None:
                time.sleep(0.5)
                continue

            now_sec = time.time()
            with _frame_lock:
                ram_age = now_sec - _latest_frame_data["timestamp"]
            if ram_age > 1.5:
                if LIVE_FRAME_PATH.exists():
                    try:
                        stat = LIVE_FRAME_PATH.stat()
                        mtime = stat.st_mtime_ns
                        file_age = now_sec - stat.st_mtime
                    except (FileNotFoundError, PermissionError):
                        mtime = None
                        file_age = 999.0

                    if file_age <= 4.0:
                        if mtime is not None and mtime != last_mtime:
                            try:
                                with open(LIVE_FRAME_PATH, "rb") as f:
                                    data = f.read()
                                if data and len(data) > 4 and data.startswith(b"\xff\xd8"):
                                    last_mtime = mtime
                                    with _frame_lock:
                                        _latest_frame_data["bytes"] = data
                                        _latest_frame_data["mtime"] = mtime
                                        _latest_frame_data["timestamp"] = now_sec
                            except (PermissionError, OSError):
                                pass
                    else:
                        with _frame_lock:
                            _latest_frame_data["bytes"] = standby
                            _latest_frame_data["mtime"] = 0
                else:
                    if is_postgres():
                        c_bytes, _ = get_live_frame()
                        if c_bytes:
                            with _frame_lock:
                                _latest_frame_data["bytes"] = c_bytes
                                _latest_frame_data["mtime"] = int(now_sec * 1000)
                                _latest_frame_data["timestamp"] = now_sec
                        else:
                            with _frame_lock:
                                _latest_frame_data["bytes"] = standby
                                _latest_frame_data["mtime"] = 0
                    else:
                        with _frame_lock:
                            _latest_frame_data["bytes"] = standby
                            _latest_frame_data["mtime"] = 0
        except Exception:
            pass
        time.sleep(0.1)


threading.Thread(target=_frame_reader_loop, daemon=True).start()


def generate_video_stream():
    client_last_id = -1
    standby_bytes = create_standby_frame()
    last_yield_time = 0.0

    while True:
        try:
            now = time.time()
            # 1. Ultra-fast shared memory RAM buffer (30 FPS, < 0.01ms, zero lock)
            shm_res = read_live_frame(min_frame_id=client_last_id, max_age_seconds=4.0)
            if shm_res is not None:
                fid, ts, frame_bytes = shm_res
                client_last_id = fid
                last_yield_time = now
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame_bytes)).encode() + b"\r\n\r\n"
                    + frame_bytes + b"\r\n"
                )
                time.sleep(0.01)
                continue

            # 2. Check in-memory fallback (from disk/push) only if shared memory is not active
            with _frame_lock:
                fb = _latest_frame_data["bytes"]
                mid = _latest_frame_data["mtime"]
                ftime = _latest_frame_data["timestamp"]
            if fb and mid != 0 and mid != client_last_id and (now - ftime) < 4.0:
                client_last_id = mid
                last_yield_time = now
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(fb)).encode() + b"\r\n\r\n"
                    + fb + b"\r\n"
                )
                time.sleep(0.01)
                continue

            # 3. Only if feed is completely idle for > 3.0s, yield standby frame periodically
            if (now - last_yield_time) > 3.0:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(standby_bytes)).encode() + b"\r\n\r\n"
                    + standby_bytes + b"\r\n"
                )
                last_yield_time = now

        except (GeneratorExit, StopIteration):
            break
        except Exception:
            break
        time.sleep(0.01)


@app.route("/video_feed")
def video_feed():
    return Response(
        generate_video_stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Access-Control-Allow-Origin": "*",
            "X-Accel-Buffering": "no"
        }
    )


@app.route("/api/live-frame")
def api_live_frame():
    shm_res = read_live_frame(max_age_seconds=2.5)
    if shm_res is not None:
        frame_bytes = shm_res[2]
    else:
        with _frame_lock:
            frame_bytes = _latest_frame_data["bytes"]
        if not frame_bytes and LIVE_FRAME_PATH.exists():
            try:
                data = LIVE_FRAME_PATH.read_bytes()
                if len(data) > 10 and data.startswith(b"\xff\xd8"):
                    frame_bytes = data
            except Exception:
                pass
        if not frame_bytes:
            frame_bytes = create_standby_frame()

    return Response(
        frame_bytes,
        mimetype="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Access-Control-Allow-Origin": "*"
        }
    )


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "service": "QueueSense",
        "timestamp": time.time(),
        "arduino": bridge.status()
    }), 200


def init_hardware_bridge():
    """Start hardware bridge if enabled by environment settings."""
    if os.getenv("ENABLE_ARDUINO", "true").lower() in ("true", "1", "yes"):
        bridge.start()


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true")
    init_hardware_bridge()
    try:
        app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)
    finally:
        bridge.close()

