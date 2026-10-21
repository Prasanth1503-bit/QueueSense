import os
import time
from pathlib import Path
from flask import Flask, render_template, jsonify, Response, request

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from database import (get_queue_statistics, get_attendance_events, get_attendance_summary,
                      get_queue_alert_limits, save_queue_alert_limit,
                      get_queue_history, get_queue_history_summary,
                      get_historical_videos, get_historical_queue_names,
                      get_live_frame, get_hardware_status)
from arduino_queue_bridge import bridge

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
LIVE_FRAME_PATH = BASE_DIR / "static" / "live_frame.jpg"
SERVICE_SECONDS_PER_PERSON = int(os.getenv("SERVICE_SECONDS_PER_PERSON", 25))


@app.route("/")
def dashboard():
    return render_template("index.html")


@app.route("/api/stats")
def get_stats():
    queues = get_queue_statistics()
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

    bridge.update_hardware_alerts(queues)
    return jsonify({
        "queues": queues,
        "recommended_queue": shortest,
        "recommended_wait_seconds": shortest_wait,
        "monitoring": bool(queues),
        "alert_limits": limits,
        "arduino": bridge.status()
    })


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
    return jsonify({
        "events": get_attendance_events(limit, request.args.get("search")),
        "summary": get_attendance_summary()
    })


@app.route("/api/alert-limits", methods=["GET", "POST"])
def alert_limits():
    if request.method == "GET":
        limits = get_queue_alert_limits()
        for queue_name in get_queue_statistics():
            if queue_name not in limits:
                limits[queue_name] = save_queue_alert_limit(queue_name, 5)
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


def generate_video_stream():
    last_mtime = None
    last_cloud_ts = None
    # Yield initial frame immediately upon client connection if it exists
    if LIVE_FRAME_PATH.exists():
        try:
            with open(LIVE_FRAME_PATH, "rb") as f:
                initial_frame = f.read()
            if len(initial_frame) > 4 and initial_frame.startswith(b"\xff\xd8"):
                last_mtime = LIVE_FRAME_PATH.stat().st_mtime_ns
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(initial_frame)).encode() + b"\r\n"
                    b"Cache-Control: no-cache\r\n\r\n"
                    + initial_frame + b"\r\n"
                )
        except Exception:
            pass

    while True:
        try:
            if LIVE_FRAME_PATH.exists():
                mtime = LIVE_FRAME_PATH.stat().st_mtime_ns
                if mtime != last_mtime:
                    with open(LIVE_FRAME_PATH, "rb") as f:
                        frame = f.read()
                    if len(frame) > 4 and frame.startswith(b"\xff\xd8"):
                        last_mtime = mtime
                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(frame)).encode() + b"\r\n"
                            b"Cache-Control: no-cache\r\n\r\n"
                            + frame + b"\r\n"
                        )
            else:
                # Cloud frame fallback
                c_frame, c_ts = get_live_frame()
                if c_frame and c_ts != last_cloud_ts:
                    last_cloud_ts = c_ts
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(c_frame)).encode() + b"\r\n"
                        b"Cache-Control: no-cache\r\n\r\n"
                        + c_frame + b"\r\n"
                    )
                time.sleep(0.5)
        except (FileNotFoundError, PermissionError, OSError):
            pass
        except Exception as e:
            print("Video stream error:", e)
        time.sleep(0.03)


@app.route("/video_feed")
def video_feed():
    return Response(
        generate_video_stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@app.route("/api/live-frame")
def api_live_frame():
    try:
        if LIVE_FRAME_PATH.exists():
            with open(LIVE_FRAME_PATH, "rb") as f:
                frame = f.read()
            if len(frame) > 4 and frame.startswith(b"\xff\xd8"):
                return Response(
                    frame,
                    mimetype="image/jpeg",
                    headers={
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache"
                    }
                )
        else:
            c_frame, _ = get_live_frame()
            if c_frame:
                return Response(
                    c_frame,
                    mimetype="image/jpeg",
                    headers={
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache"
                    }
                )
    except Exception:
        pass
    return ("", 204)


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

