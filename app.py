from flask import Flask, render_template, jsonify, Response, request
from pathlib import Path
from datetime import datetime, timedelta
import time

from database import (
    get_queue_statistics,
    get_queue_history,
    get_queue_history_summary,
    get_historical_videos,
    get_historical_queue_names
)

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
LIVE_FRAME_PATH = BASE_DIR / "static" / "live_frame.jpg"

SERVICE_SECONDS_PER_PERSON = 25


# =========================================================
# HOME PAGE
# =========================================================

@app.route("/")
def index():
    return render_template("index.html")


# =========================================================
# LIVE QUEUE STATISTICS
# =========================================================

@app.route("/api/stats")
def api_stats():
    queues = get_queue_statistics()

    for stats in queues.values():
        occupancy = max(
            0,
            int(stats.get("occupancy", 0) or 0)
        )

        stats["estimated_wait_seconds"] = (
            occupancy * SERVICE_SECONDS_PER_PERSON
        )

    recommended_queue = (
        min(
            queues,
            key=lambda name: queues[name].get("occupancy", 0)
        )
        if queues
        else None
    )

    recommended_wait_seconds = (
        queues[recommended_queue]["estimated_wait_seconds"]
        if recommended_queue
        else None
    )

    # Monitoring is active only if a queue was updated within the last 30 seconds.
    monitoring_active = False
    if queues:
        now_dt = datetime.now().astimezone()
        threshold = now_dt - timedelta(seconds=30)
        for stats in queues.values():
            updated_at = stats.get("updated_at")
            if updated_at:
                try:
                    dt = datetime.fromisoformat(updated_at)
                    if dt.tzinfo is None:
                        dt = dt.astimezone()
                    if dt >= threshold:
                        monitoring_active = True
                        break
                except (ValueError, TypeError):
                    pass

    return jsonify({
        "queues": queues,
        "recommended_queue": recommended_queue,
        "recommended_wait_seconds": recommended_wait_seconds,
        "monitoring": monitoring_active
    })


# =========================================================
# QUEUE HISTORY
# =========================================================

@app.route("/api/history")
def api_history():
    try:
        hours = max(
            1,
            min(int(request.args.get("hours", 24)), 8760)
        )

        limit = max(
            1,
            min(int(request.args.get("limit", 1000)), 10000)
        )

    except ValueError:
        return jsonify({
            "error": "hours and limit must be integers"
        }), 400

    records = get_queue_history(
        queue_name=request.args.get("queue") or None,
        hours=hours,
        limit=limit,
        video_hash=request.args.get("video_hash") or None,
        session_id=request.args.get("session_id") or None
    )

    return jsonify({
        "history": records
    })


# =========================================================
# HISTORY SUMMARY
# =========================================================

@app.route("/api/history/summary")
def api_history_summary():
    try:
        hours = max(
            1,
            min(int(request.args.get("hours", 24)), 8760)
        )

    except ValueError:
        return jsonify({
            "error": "hours must be an integer"
        }), 400

    summary = get_queue_history_summary(
        hours=hours,
        video_hash=request.args.get("video_hash") or None,
        session_id=request.args.get("session_id") or None
    )

    return jsonify({
        "summary": summary
    })


# =========================================================
# HISTORICAL VIDEOS
# =========================================================

@app.route("/api/history/videos")
def api_history_videos():
    try:
        hours = max(
            1,
            min(int(request.args.get("hours", 24)), 8760)
        )

    except ValueError:
        return jsonify({
            "error": "hours must be an integer"
        }), 400

    videos = get_historical_videos(hours=hours)

    return jsonify({
        "videos": videos
    })


# =========================================================
# HISTORICAL QUEUE NAMES
# =========================================================

@app.route("/api/history/queues")
def api_history_queues():
    try:
        hours = max(
            1,
            min(int(request.args.get("hours", 24)), 8760)
        )

    except ValueError:
        return jsonify({
            "error": "hours must be an integer"
        }), 400

    queues = get_historical_queue_names(
        video_hash=request.args.get("video_hash") or None,
        hours=hours
    )

    return jsonify({
        "queues": queues
    })


# =========================================================
# OPTIMIZED LIVE VIDEO STREAM
# =========================================================

def generate_video_stream():
    last_mtime = None

    while True:
        try:
            # Wait if the live frame does not exist yet.
            if not LIVE_FRAME_PATH.exists():
                time.sleep(0.02)
                continue

            # Check whether a new frame has been produced.
            current_mtime = LIVE_FRAME_PATH.stat().st_mtime_ns

            # Avoid repeatedly sending the same frame.
            if current_mtime == last_mtime:
                time.sleep(0.01)
                continue

            # Read the latest JPEG frame.
            frame = LIVE_FRAME_PATH.read_bytes()

            # Verify that the frame is a valid JPEG.
            if (
                len(frame) > 4
                and frame.startswith(b"\xff\xd8")
                and frame.endswith(b"\xff\xd9")
            ):
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: "
                    + str(len(frame)).encode()
                    + b"\r\n"
                    b"Cache-Control: no-cache\r\n\r\n"
                    + frame
                    + b"\r\n"
                )

                last_mtime = current_mtime

        except (FileNotFoundError, PermissionError):
            # The monitoring process may be updating the image.
            time.sleep(0.01)

        except OSError as error:
            print("Video stream error:", error)
            time.sleep(0.02)


# =========================================================
# VIDEO FEED ROUTE
# =========================================================

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


# =========================================================
# RUN FLASK APPLICATION
# =========================================================

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True
    )