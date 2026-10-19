import cv2
import torch
import numpy as np
import time
import hashlib
import uuid

from pathlib import Path
from ultralytics import YOLO

from src.queue_manager import QueueManager
from database import save_queue_statistics, reset_queue_status


# ============================================
# QUEUESENSE CONFIGURATION
# ============================================

BASE_DIR = Path(__file__).resolve().parent
VIDEO_FOLDER = BASE_DIR / "videos"
MODEL_NAME = "yolo26n.pt"
LIVE_FRAME_PATH = BASE_DIR / "static" / "live_frame.jpg"

LIVE_FRAME_PATH.parent.mkdir(parents=True, exist_ok=True)
LIVE_FRAME_PATH.unlink(missing_ok=True)

# Seconds between current-status DB writes (does not affect history snapshots).
STATUS_SAVE_INTERVAL = 2.0
# Seconds between historical snapshot DB writes.
HISTORY_SAVE_INTERVAL = 5.0


def calculate_video_hash(video_path):
    """Return a SHA-256 fingerprint of the video file contents."""
    sha256 = hashlib.sha256()
    with open(video_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def detect_available_cameras(max_index=5):
    """Scan camera indices 0..max_index-1 and return working ones."""
    available = []
    for index in range(max_index):
        try:
            cap_test = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if cap_test.isOpened():
                ok, _ = cap_test.read()
                if ok:
                    available.append(index)
            cap_test.release()
        except Exception:
            pass
    return available


# ============================================
# STEP 1: SELECT INPUT SOURCE
# ============================================

print("\n====================================")
print("             QUEUESENSE")
print("      Smart Queue Intelligence")
print("====================================")
print("1. Prerecorded video  (from videos folder)")
print("2. Laptop built-in camera")
print("3. External USB webcam")
print("\nAll three sources use the same ROI, tracking, entry/exit,")
print("waiting-time, database, and dashboard pipeline.")
source_choice = input("\nChoose input source (1/2/3): ").strip()

session_id = uuid.uuid4().hex
source_is_camera = False

if source_choice == "1":
    video_files = sorted(
        f for f in VIDEO_FOLDER.glob("*")
        if f.suffix.lower() in [".mp4", ".avi", ".mov", ".mkv", ".webm"]
    )
    if not video_files:
        raise SystemExit(f"No videos found in {VIDEO_FOLDER}. Add a video file and try again.")

    print("\nAvailable videos:")
    for i, v in enumerate(video_files, start=1):
        print(f"  {i}. {v.name}")

    choice = input("Select video number: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(video_files)):
        raise SystemExit("Invalid video selection.")

    video_path = video_files[int(choice) - 1].resolve()
    print("\nCalculating video fingerprint...")
    video_hash = calculate_video_hash(video_path)
    video_name = video_path.name
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {video_path}")
    print(f"Selected video: {video_name}")

elif source_choice == "2":
    camera_text = input("Laptop camera index [0]: ").strip()
    camera_index = int(camera_text) if camera_text.isdigit() else 0
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise SystemExit(
            f"Could not open laptop camera {camera_index}. "
            "Close other applications using the camera and try again."
        )
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    video_name = f"Laptop Camera ({camera_index})"
    video_hash = hashlib.sha256(
        f"queuesense-laptop-camera-index:{camera_index}".encode("utf-8")
    ).hexdigest()
    source_is_camera = True
    print(f"Using laptop built-in camera: index {camera_index}")

elif source_choice == "3":
    print("\nScanning for available cameras (this may take a few seconds)...")
    available_cameras = detect_available_cameras(max_index=5)

    if not available_cameras:
        raise SystemExit(
            "No cameras detected at indices 0-4.\n"
            "  - Make sure the USB webcam is connected and powered on.\n"
            "  - Close other apps that may be using the camera.\n"
            "  - Try reconnecting the webcam and running again."
        )

    print("\nAvailable cameras detected:")
    for idx in available_cameras:
        hint = " (likely built-in)" if idx == 0 else ""
        print(f"  {idx}. Camera index {idx}{hint}")

    if len(available_cameras) == 1:
        camera_index = available_cameras[0]
        print(f"\nOnly one camera found. Using camera index {camera_index}.")
    else:
        camera_text = input(f"\nSelect camera index for USB webcam {available_cameras}: ").strip()
        if camera_text.isdigit() and int(camera_text) in available_cameras:
            camera_index = int(camera_text)
        else:
            raise SystemExit(f"Invalid selection. Choose from: {available_cameras}")

    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        cap.release()
        raise SystemExit(
            f"Could not open USB webcam at index {camera_index}.\n"
            "  - Disconnect and reconnect the webcam.\n"
            "  - Close other applications using it.\n"
            "  - Try a different USB port."
        )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    video_name = f"USB Webcam (index {camera_index})"
    video_hash = hashlib.sha256(
        f"queuesense-usb-webcam-index:{camera_index}".encode("utf-8")
    ).hexdigest()
    source_is_camera = True
    print(f"Using external USB webcam: index {camera_index}")

else:
    raise SystemExit("Invalid choice. Please enter 1, 2, or 3.")

print(f"\nSource      : {video_name}")
print(f"Fingerprint : {video_hash[:16]}...")
print(f"Session ID  : {session_id}")


# ============================================
# STEP 2: READ FIRST FRAME FOR ROI PREVIEW
# ============================================

success, first_frame = cap.read()
if not success:
    cap.release()
    raise SystemExit("Could not read a frame from the selected source.")

height, width = first_frame.shape[:2]
print(f"\nInput resolution: {width} x {height}")


# ============================================
# STEP 3: SELECT NUMBER OF QUEUES
# ============================================

print("\nHow many queues do you want to monitor?")
print("  1. One queue")
print("  2. Two queues")
print("  3. Three queues")

queue_input = input("Enter choice (1/2/3): ").strip()

if queue_input not in ("1", "2", "3"):
    cap.release()
    raise SystemExit("Please choose 1, 2, or 3.")

num_queues = int(queue_input)


# ============================================
# STEP 4: DRAW QUEUE ROI REGIONS
# ============================================

queue_names = []
queue_polygons = []
drawing_points = []
mouse_position = None
polygon_closed = False

frame_height, frame_width = first_frame.shape[:2]
MAX_DISPLAY_WIDTH = 1200
MAX_DISPLAY_HEIGHT = 800
scale = min(MAX_DISPLAY_WIDTH / frame_width, MAX_DISPLAY_HEIGHT / frame_height, 1.0)
display_width = int(frame_width * scale)
display_height = int(frame_height * scale)


def mouse_callback(event, x, y, flags, param):
    global drawing_points, mouse_position, polygon_closed
    ox = max(0, min(int(x / scale), frame_width - 1))
    oy = max(0, min(int(y / scale), frame_height - 1))
    mouse_position = (ox, oy)
    if event == cv2.EVENT_LBUTTONDOWN:
        if len(drawing_points) >= 3 and not polygon_closed:
            fx, fy = drawing_points[0]
            dist = ((x - int(fx * scale)) ** 2 + (y - int(fy * scale)) ** 2) ** 0.5
            if dist <= 18:
                polygon_closed = True
                return
        if not polygon_closed:
            drawing_points.append((ox, oy))
    elif event == cv2.EVENT_RBUTTONDOWN:
        if drawing_points and not polygon_closed:
            drawing_points.pop()


cv2.namedWindow("Draw Queue ROI", cv2.WINDOW_AUTOSIZE)
cv2.setMouseCallback("Draw Queue ROI", mouse_callback)

print("\n========================================")
print("       QUEUESENSE ROI DRAWING")
print("========================================")
print("LEFT CLICK  : Add a corner point")
print("NEAR FIRST  : Close the polygon")
print("RIGHT CLICK : Undo last corner  (or press Z)")
print("C / R       : Clear and redraw")
print("ENTER       : Confirm polygon")
print("Q           : Cancel")
print("========================================")

for queue_index in range(num_queues):
    queue_name = input(
        f"\nName for Queue {queue_index + 1} (e.g. Student / Faculty / Scholar): "
    ).strip() or f"Queue {queue_index + 1}"

    drawing_points = []
    mouse_position = None
    polygon_closed = False

    while True:
        display = first_frame.copy()

        for idx, poly in enumerate(queue_polygons):
            cv2.polylines(display, [poly], True, (0, 255, 0), 3)
            center = np.mean(poly, axis=0).astype(int)
            cv2.putText(display, queue_names[idx], tuple(center),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        if drawing_points:
            pts = np.array(drawing_points, dtype=np.int32)
            for i in range(len(drawing_points) - 1):
                cv2.line(display, drawing_points[i], drawing_points[i + 1], (0, 0, 255), 2)
            if polygon_closed and len(drawing_points) >= 3:
                cv2.line(display, drawing_points[-1], drawing_points[0], (0, 255, 255), 2)
                ov = display.copy()
                cv2.fillPoly(ov, [pts], (0, 180, 0))
                display = cv2.addWeighted(ov, 0.25, display, 0.75, 0)
                cv2.polylines(display, [pts], True, (0, 255, 0), 3)
            for i, pt in enumerate(drawing_points):
                color = (0, 255, 255) if i == 0 else (0, 0, 255)
                cv2.circle(display, pt, 6, color, -1)
                cv2.putText(display, str(i + 1), (pt[0] + 8, pt[1] - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            if mouse_position and not polygon_closed:
                cv2.line(display, drawing_points[-1], mouse_position, (255, 255, 0), 2)
                if len(drawing_points) >= 3:
                    cv2.line(display, mouse_position, drawing_points[0], (100, 255, 255), 1)

        instructions = [
            f"Drawing: {queue_name}  |  Corners: {len(drawing_points)}",
            "POLYGON CLOSED — Press ENTER to confirm" if polygon_closed
            else "Click corners; click near first corner to close",
            "Right-click/Z: Undo  |  C: Clear  |  Q: Cancel"
        ]
        y_pos = 30
        for line in instructions:
            cv2.putText(display, line, (15, y_pos),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 0), 2)
            y_pos += 28

        preview = cv2.resize(display, (display_width, display_height), interpolation=cv2.INTER_AREA)
        cv2.imshow("Draw Queue ROI", preview)

        key = cv2.waitKey(20) & 0xFF
        if key in (10, 13):
            if len(drawing_points) < 3:
                print("Need at least 3 corners.")
                continue
            if not polygon_closed:
                print("Close the polygon first (click near the first corner).")
                continue
            queue_polygons.append(np.array(drawing_points, dtype=np.int32))
            queue_names.append(queue_name)
            print(f"ROI saved for: {queue_name}")
            break
        elif key == ord("z"):
            if drawing_points and not polygon_closed:
                drawing_points.pop()
        elif key in (ord("c"), ord("r")):
            drawing_points = []
            polygon_closed = False
        elif key == ord("q"):
            cv2.destroyAllWindows()
            cap.release()
            raise SystemExit("ROI drawing cancelled.")

cv2.destroyWindow("Draw Queue ROI")
print("\nAll queue ROIs confirmed.")


# ============================================
# STEP 5: CHECK GPU
# ============================================

if torch.cuda.is_available():
    device = 0
    print(f"\nUsing GPU: {torch.cuda.get_device_name(0)}")
else:
    device = "cpu"
    print("\nCUDA unavailable. Using CPU.")


# ============================================
# STEP 6: LOAD YOLO MODEL
# ============================================

print("\nLoading YOLO model...")
model = YOLO(MODEL_NAME)


# ============================================
# STEP 7: INITIALISE QUEUE MANAGER
# ============================================

if not source_is_camera:
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

queue_manager = QueueManager(
    queue_names=queue_names,
    confirmation_seconds=2.5,
    exit_confirmation_seconds=1.5,
    lost_track_timeout=5.0
)

print("\nQueue monitoring started. Press Q in the monitoring window to stop.")
if source_is_camera:
    print("Live camera monitoring is active.")

last_status_save = time.monotonic() - STATUS_SAVE_INTERVAL
last_history_save = time.monotonic()


# ============================================
# STEP 8: MONITOR QUEUES
# ============================================

try:
    while True:
        success, frame = cap.read()
        if not success:
            print("Camera frame could not be read; stopping." if source_is_camera else "Video ended.")
            break

        now = time.monotonic()

        results = model.track(
            source=frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=[0],
            conf=0.20,
            iou=0.5,
            imgsz=480,
            device=device,
            verbose=False
        )

        result = results[0]
        output = frame.copy()
        visible_track_ids = set()

        if result.boxes is not None and len(result.boxes) > 0:
            boxes = result.boxes.xyxy.cpu().numpy()
            track_ids = (
                result.boxes.id.int().cpu().tolist()
                if result.boxes.id is not None
                else [None] * len(boxes)
            )

            for box, track_id in zip(boxes, track_ids):
                x1, y1, x2, y2 = box
                bw = float(x2 - x1)
                bh = float(y2 - y1)
                if bw < 8 or bh < 18:
                    continue
                if bw / max(bh, 1.0) > 2.5:
                    continue

                px = int((x1 + x2) / 2)
                anchors = [
                    (px, int(y2)),
                    (px, int(y1 + 0.75 * bh)),
                    (px, int(y1 + 0.50 * bh)),
                ]
                detected_queue = None
                for q_idx, polygon in enumerate(queue_polygons):
                    if any(
                        cv2.pointPolygonTest(polygon, (float(ax), float(ay)), False) >= 0
                        for ax, ay in anchors
                    ):
                        detected_queue = queue_names[q_idx]
                        break

                if track_id is None:
                    if detected_queue is not None:
                        bx1, by1, bx2, by2 = map(int, (x1, y1, x2, y2))
                        cv2.rectangle(output, (bx1, by1), (bx2, by2), (0, 255, 255), 2)
                        cv2.putText(output, "Person (tracking...)", (bx1, max(by1 - 10, 20)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2, cv2.LINE_AA)
                    continue

                visible_track_ids.add(track_id)
                queue_manager.update(track_id=track_id, detected_queue=detected_queue, now=now)
                confirmed_queue = queue_manager.current_queue.get(track_id)

                if detected_queue is not None:
                    bx1, by1, bx2, by2 = map(int, (x1, y1, x2, y2))
                    is_confirmed = confirmed_queue == detected_queue
                    color = (255, 0, 0) if is_confirmed else (0, 255, 0)
                    cv2.rectangle(output, (bx1, by1), (bx2, by2), color, 2)
                    label = (
                        f"ID:{track_id} | {confirmed_queue}"
                        if is_confirmed
                        else f"ID:{track_id} | {detected_queue} (confirming)"
                    )
                    cv2.putText(output, label, (bx1, max(by1 - 10, 20)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2, cv2.LINE_AA)

        queue_manager.cleanup(visible_track_ids=visible_track_ids, now=now)
        statistics = queue_manager.get_statistics(now=now)

        if now - last_status_save >= STATUS_SAVE_INTERVAL:
            save_queue_statistics(statistics, video_hash=video_hash,
                                  session_id=session_id, video_name=video_name)
            last_status_save = now

        if now - last_history_save >= HISTORY_SAVE_INTERVAL:
            save_queue_statistics(statistics, save_history=True,
                                  video_hash=video_hash, session_id=session_id,
                                  video_name=video_name)
            last_history_save = now

        for idx, polygon in enumerate(queue_polygons):
            cv2.polylines(output, [polygon], True, (0, 255, 0), 3)
            center = np.mean(polygon, axis=0).astype(int)
            cv2.putText(output, queue_names[idx], tuple(center),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        y_pos = 35
        for qn in queue_names:
            s = statistics[qn]
            text = (f"{qn}: {s['occupancy']} people"
                    f" | In:{s['entries']} Out:{s['exits']}"
                    f" | Elapsed:{s['average_wait_seconds']:.1f}s")
            cv2.putText(output, text, (20, y_pos),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 255), 2)
            y_pos += 26

        total_occ = sum(s["occupancy"] for s in statistics.values())
        cv2.putText(output, f"Total queue occupancy: {total_occ}",
                    (20, y_pos + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 0), 2)

        encoded_ok, encoded_frame = cv2.imencode(".jpg", output, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if encoded_ok:
            tmp_path = LIVE_FRAME_PATH.with_suffix(".tmp.jpg")
            tmp_path.write_bytes(encoded_frame.tobytes())
            for attempt in range(10):
                try:
                    tmp_path.replace(LIVE_FRAME_PATH)
                    break
                except PermissionError:
                    if attempt == 9:
                        print("Warning: Could not update the dashboard frame.")
                    else:
                        time.sleep(0.1)

        cv2.namedWindow("QueueSense - Queue Monitoring", cv2.WINDOW_NORMAL)
        cv2.imshow("QueueSense - Queue Monitoring", output)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

finally:
    cap.release()
    cv2.destroyAllWindows()
    reset_queue_status()
    print("\nQueueSense stopped successfully.")
