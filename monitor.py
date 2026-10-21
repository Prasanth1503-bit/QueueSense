import cv2
import torch
import numpy as np
import time
import hashlib
import uuid

from pathlib import Path
from ultralytics import YOLO

from src.queue_manager import QueueManager
from database import save_queue_statistics, reset_queue_status, update_live_frame
import json
import urllib.request
import urllib.error
import threading
import queue

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

# Asynchronous non-blocking sender for Flask occupancy push
occupancy_queue = queue.Queue(maxsize=2)


def async_occupancy_worker():
    while True:
        try:
            payload = occupancy_queue.get()
            if payload is None:
                break
            request = urllib.request.Request(
                "http://127.0.0.1:5000/api/queue-occupancy",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(request, timeout=0.8) as response:
                response.read()
        except Exception:
            pass


threading.Thread(target=async_occupancy_worker, daemon=True).start()


# Asynchronous non-blocking worker for database writes (prevents remote cloud DB lag on video loop)
db_sync_queue = queue.Queue(maxsize=1)


def async_db_worker():
    while True:
        try:
            item = db_sync_queue.get()
            if item is None:
                break
            stats, save_hist, v_hash, s_id, v_name = item
            save_queue_statistics(
                stats,
                save_history=save_hist,
                video_hash=v_hash,
                session_id=s_id,
                video_name=v_name
            )
        except Exception:
            pass


threading.Thread(target=async_db_worker, daemon=True).start()


# Asynchronous non-blocking worker for local disk frame writing (runs fast at 25-30 FPS)
frame_sync_queue = queue.Queue(maxsize=1)
cloud_frame_queue = queue.Queue(maxsize=1)


def async_frame_worker():
    last_cloud_dispatch = 0.0
    while True:
        try:
            frame_img = frame_sync_queue.get()
            if frame_img is None:
                break
            h, w = frame_img.shape[:2]
            if w > 960:
                dash_scale = 960 / w
                dash_frame = cv2.resize(frame_img, (960, int(h * dash_scale)), interpolation=cv2.INTER_AREA)
            else:
                dash_frame = frame_img

            encoded_ok, encoded_frame = cv2.imencode(
                ".jpg",
                dash_frame,
                [cv2.IMWRITE_JPEG_QUALITY, 75]
            )

            if encoded_ok:
                frame_bytes = encoded_frame.tobytes()
                # Fast direct write to avoid Windows file rename locking
                try:
                    with open(LIVE_FRAME_PATH, "wb") as f:
                        f.write(frame_bytes)
                except (PermissionError, OSError):
                    pass

                # Dispatch to separate cloud worker (every 0.5s, non-blocking)
                now_c = time.monotonic()
                if now_c - last_cloud_dispatch >= 0.5:
                    last_cloud_dispatch = now_c
                    if w > 540:
                        c_scale = 540 / w
                        c_frame = cv2.resize(frame_img, (540, int(h * c_scale)), interpolation=cv2.INTER_AREA)
                    else:
                        c_frame = frame_img
                    c_ok, c_enc = cv2.imencode(".jpg", c_frame, [cv2.IMWRITE_JPEG_QUALITY, 55])
                    if c_ok:
                        c_bytes = c_enc.tobytes()
                        if not cloud_frame_queue.empty():
                            try:
                                cloud_frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                        try:
                            cloud_frame_queue.put_nowait(c_bytes)
                        except queue.Full:
                            pass
        except Exception:
            pass


def async_cloud_worker():
    """Independent background worker for Supabase cloud frame uploads — never slows down local video."""
    while True:
        try:
            c_bytes = cloud_frame_queue.get()
            if c_bytes is None:
                break
            try:
                update_live_frame(c_bytes)
            except Exception:
                pass
        except Exception:
            pass


threading.Thread(target=async_frame_worker, daemon=True).start()
threading.Thread(target=async_cloud_worker, daemon=True).start()


# ============================================
# QUEUESENSE CONFIGURATION
# ============================================

BASE_DIR = Path(__file__).resolve().parent

VIDEO_FOLDER = BASE_DIR / "videos"

MODEL_NAME = "yolo26n.pt"

LIVE_FRAME_PATH = (
    BASE_DIR / "static" / "live_frame.jpg"
)

LIVE_FRAME_PATH.parent.mkdir(
    parents=True,
    exist_ok=True
)

LIVE_FRAME_PATH.unlink(missing_ok=True)


def calculate_video_hash(video_path):
    """Return a SHA-256 fingerprint of the video file contents."""
    sha256 = hashlib.sha256()

    with open(video_path, "rb") as video_file:
        for chunk in iter(lambda: video_file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def detect_available_cameras(max_index=5):
    """Scan camera indices 0..max_index-1 and return working ones."""
    available = []
    for index in range(max_index):
        try:
            cap_test = cv2.VideoCapture(index, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(index)
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
print("4. Enter custom video path or stream URL")
print("\nAll input sources use the same ROI, YOLO tracking, entry/exit,")
print("waiting-time, database, and dashboard pipeline.")

source_choice = input("\nChoose input source (1/2/3/4) [default 1]: ").strip()
if not source_choice:
    source_choice = "1"

session_id = uuid.uuid4().hex
is_live_camera = False

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

    choice = input(f"Select video number (1-{len(video_files)}) [default 1]: ").strip()
    if not choice:
        choice = "1"
    if not choice.isdigit() or not (1 <= int(choice) <= len(video_files)):
        raise SystemExit("Invalid video selection.")

    video_path = video_files[int(choice) - 1].resolve()
    print("\nCalculating video fingerprint...")
    video_hash = calculate_video_hash(str(video_path))
    video_name = video_path.name
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {video_path}")
    print(f"Selected video: {video_name}")

elif source_choice == "2":
    camera_text = input("Laptop camera index [0]: ").strip()
    camera_index = int(camera_text) if camera_text.isdigit() else 0
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(camera_index)
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
    video_name = "Laptop Camera"
    video_hash = hashlib.sha256(
        f"queuesense-laptop-camera-index:{camera_index}".encode("utf-8")
    ).hexdigest()
    is_live_camera = True
    print(f"Using laptop built-in camera: index {camera_index}")

elif source_choice == "3":
    print("\nScanning for available cameras (this may take a few seconds)...")
    available_cameras = detect_available_cameras(max_index=5)

    if not available_cameras:
        print("Warning: No cameras auto-detected. Attempting fallback to index 1...")
        available_cameras = [1]

    print("\nAvailable cameras detected:")
    for idx in available_cameras:
        hint = " (built-in webcam)" if idx == 0 else " (external webcam)"
        print(f"  {idx}. Camera index {idx}{hint}")

    if len(available_cameras) == 1:
        camera_index = available_cameras[0]
        print(f"\nUsing camera index {camera_index}.")
    else:
        camera_text = input(f"\nSelect camera index for USB webcam {available_cameras} [default {available_cameras[-1]}]: ").strip()
        if not camera_text:
            camera_index = available_cameras[-1]
        elif camera_text.isdigit() and int(camera_text) in available_cameras:
            camera_index = int(camera_text)
        else:
            camera_index = int(camera_text) if camera_text.isdigit() else 1

    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise SystemExit(
            f"Could not open USB webcam at index {camera_index}.\n"
            "  - Disconnect and reconnect the webcam.\n"
            "  - Close other applications using it.\n"
            "  - Try a different USB port."
        )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    video_name = "USB Webcam"
    video_hash = hashlib.sha256(
        f"queuesense-usb-webcam-index:{camera_index}".encode("utf-8")
    ).hexdigest()
    is_live_camera = True
    print(f"Using external USB webcam: index {camera_index}")

elif source_choice == "4":
    custom_path = input("Enter video file path, camera index (e.g. 0), or RTSP/HTTP URL: ").strip().strip('"')
    if not custom_path:
        raise SystemExit("No path or URL entered.")

    if custom_path.isdigit():
        cam_idx = int(custom_path)
        cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(cam_idx)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(cam_idx)
        if not cap.isOpened():
            raise SystemExit(f"Could not open camera {cam_idx}.")
        video_name = "Laptop Camera" if cam_idx == 0 else f"USB Webcam (Camera {cam_idx})"
        video_hash = hashlib.sha256(f"queuesense-laptop-camera-index:{cam_idx}".encode("utf-8")).hexdigest()
        is_live_camera = True
    elif custom_path.startswith(("http://", "https://", "rtsp://")):
        cap = cv2.VideoCapture(custom_path)
        if not cap.isOpened():
            raise SystemExit(f"Could not open stream: {custom_path}")
        video_name = "Live Stream Camera"
        video_hash = hashlib.sha256(custom_path.encode("utf-8")).hexdigest()
        is_live_camera = True
    else:
        file_path = Path(custom_path).expanduser().resolve()
        if not file_path.is_file():
            raise SystemExit(f"Video file does not exist: {file_path}")
        video_path = file_path
        print("\nCalculating video fingerprint...")
        video_hash = calculate_video_hash(str(video_path))
        video_name = video_path.name
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise SystemExit(f"Could not open video: {video_path}")

else:
    raise SystemExit("Invalid choice. Please enter 1, 2, 3, or 4.")

print(f"\n====================================")
print(f"Source Name : {video_name}")
print(f"Fingerprint : {video_hash[:16]}...")
print(f"Session ID  : {session_id[:8]}...")
print(f"====================================")

# ============================================
# STEP 2: OPEN VIDEO / CAMERA FIRST FRAME
# ============================================

success, first_frame = cap.read()

if not success:
    cap.release()
    raise SystemExit(
        "Could not read the first frame from the selected video or camera."
    )

height, width = first_frame.shape[:2]

print(
    f"\nVideo resolution: {width} x {height}"
)


# ============================================
# STEP 3: SELECT NUMBER OF QUEUES
# ============================================

print("\nHow many queues do you want to monitor?")
print("1. One queue")
print("2. Two queues")
print("3. Three queues")

queue_input = input("Enter choice: ").strip()

if queue_input not in ("1", "2", "3"):

    cap.release()

    raise SystemExit(
        "Please choose 1, 2, or 3."
    )

num_queues = int(queue_input)

# ============================================
# STEP 4: DRAW QUEUE REGIONS (IMPROVED)
# ============================================

queue_names = []
queue_polygons = []

drawing_points = []
mouse_position = None
polygon_closed = False

# Original video dimensions
frame_height, frame_width = first_frame.shape[:2]

# Resize preview to fit the screen while preserving aspect ratio.
MAX_DISPLAY_WIDTH = 1200
MAX_DISPLAY_HEIGHT = 800

scale = min(
    MAX_DISPLAY_WIDTH / frame_width,
    MAX_DISPLAY_HEIGHT / frame_height,
    1.0
)

display_width = int(frame_width * scale)
display_height = int(frame_height * scale)


def mouse_callback(event, x, y, flags, param):
    """
    Draw polygon using mouse clicks.

    Left-click:
        Add a point.
        Click near the first point to close the polygon.

    Right-click:
        Undo the last point.
    """

    global drawing_points
    global mouse_position
    global polygon_closed

    # Convert preview coordinates to original video coordinates.
    original_x = int(x / scale)
    original_y = int(y / scale)

    original_x = max(0, min(original_x, frame_width - 1))
    original_y = max(0, min(original_y, frame_height - 1))

    mouse_position = (original_x, original_y)

    if event == cv2.EVENT_LBUTTONDOWN:

        # If at least three points exist, click near the first
        # point to close the polygon.
        if len(drawing_points) >= 3 and not polygon_closed:

            first_x, first_y = drawing_points[0]

            distance = (
                ((x - int(first_x * scale)) ** 2)
                + ((y - int(first_y * scale)) ** 2)
            ) ** 0.5

            if distance <= 18:
                polygon_closed = True
                return

        if not polygon_closed:
            drawing_points.append((original_x, original_y))

    elif event == cv2.EVENT_RBUTTONDOWN:

        # Undo the last point.
        if drawing_points and not polygon_closed:
            drawing_points.pop()


cv2.namedWindow(
    "Draw Queue ROI",
    cv2.WINDOW_NORMAL
)

cv2.resizeWindow(
    "Draw Queue ROI",
    display_width,
    display_height
)

cv2.setMouseCallback(
    "Draw Queue ROI",
    mouse_callback
)

print("\n========================================")
print("       QUEUESENSE ROI DRAWING")
print("========================================")
print("LEFT CLICK  : Add a corner")
print("CLICK FIRST : Close polygon")
print("RIGHT CLICK : Undo last corner")
print("Z           : Undo last corner")
print("C           : Clear current polygon")
print("R           : Redraw current polygon")
print("ENTER       : Confirm polygon")
print("Q           : Cancel")
print("========================================")


default_queue_names = ["student", "faculty", "scholar"]

for queue_index in range(num_queues):

    suggested = default_queue_names[queue_index] if queue_index < len(default_queue_names) else f"queue_{queue_index + 1}"
    queue_name = input(
        f"\nEnter name for Queue {queue_index + 1} (press Enter for '{suggested}'): "
    ).strip()

    if not queue_name:
        queue_name = suggested

    drawing_points = []
    mouse_position = None
    polygon_closed = False

    while True:

        # Start with the original video frame.
        display = first_frame.copy()

        # Draw previously completed queues.
        for index, polygon in enumerate(queue_polygons):

            cv2.polylines(
                display,
                [polygon],
                True,
                (0, 255, 0),
                3
            )

            center = np.mean(
                polygon,
                axis=0
            ).astype(int)

            cv2.putText(
                display,
                queue_names[index],
                tuple(center),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )

        # Draw the current polygon points and connecting lines.
        if len(drawing_points) > 0:

            points_array = np.array(
                drawing_points,
                dtype=np.int32
            )

            # Draw connecting lines.
            for i in range(len(drawing_points) - 1):

                cv2.line(
                    display,
                    drawing_points[i],
                    drawing_points[i + 1],
                    (0, 0, 255),
                    2
                )

            # Draw the closing edge after the polygon is closed.
            if polygon_closed and len(drawing_points) >= 3:

                cv2.line(
                    display,
                    drawing_points[-1],
                    drawing_points[0],
                    (0, 255, 255),
                    2
                )

            # Draw corner points.
            for i, point in enumerate(drawing_points):

                color = (
                    (0, 255, 255)
                    if i == 0
                    else (0, 0, 255)
                )

                cv2.circle(
                    display,
                    point,
                    6,
                    color,
                    -1
                )

                # Label each corner.
                cv2.putText(
                    display,
                    str(i + 1),
                    (point[0] + 8, point[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 0),
                    2
                )

            # Live preview from the last point to the mouse.
            if (
                mouse_position is not None
                and not polygon_closed
            ):

                cv2.line(
                    display,
                    drawing_points[-1],
                    mouse_position,
                    (255, 255, 0),
                    2
                )

                # Show the potential closing edge.
                if len(drawing_points) >= 3:

                    cv2.line(
                        display,
                        mouse_position,
                        drawing_points[0],
                        (100, 255, 255),
                        1
                    )

            # Fill the polygon lightly after closing it.
            if polygon_closed and len(drawing_points) >= 3:

                overlay = display.copy()

                cv2.fillPoly(
                    overlay,
                    [points_array],
                    (0, 180, 0)
                )

                display = cv2.addWeighted(
                    overlay,
                    0.25,
                    display,
                    0.75,
                    0
                )

                cv2.polylines(
                    display,
                    [points_array],
                    True,
                    (0, 255, 0),
                    3
                )

        # Instructions on screen.
        instructions = [
            f"Queue: {queue_name}",
            f"Corners: {len(drawing_points)}",
            (
                "POLYGON CLOSED - Press ENTER to confirm"
                if polygon_closed
                else "Click corners; click near first corner to close"
            ),
            "Right-click/Z: Undo | C: Clear | R: Redraw | Q: Quit"
        ]

        y_position = 30

        for instruction in instructions:

            cv2.putText(
                display,
                instruction,
                (15, y_position),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 0),
                2
            )

            y_position += 30

        # Resize the preview consistently.
        preview = cv2.resize(
            display,
            (display_width, display_height),
            interpolation=cv2.INTER_AREA
        )

        cv2.imshow(
            "Draw Queue ROI",
            preview
        )

        key = cv2.waitKey(20) & 0xFF

        # ENTER confirms the polygon.
        if key in (10, 13):

            if len(drawing_points) < 3:

                print(
                    "Error: A polygon needs at least 3 corners."
                )

                continue

            if not polygon_closed:

                print(
                    "Please close the polygon first by clicking "
                    "near its first corner."
                )

                continue

            polygon = np.array(
                drawing_points,
                dtype=np.int32
            )

            queue_polygons.append(polygon)
            queue_names.append(queue_name)

            print(
                f"ROI saved successfully for {queue_name}"
            )

            break

        # Undo last corner using Z.
        elif key == ord("z"):

            if drawing_points and not polygon_closed:
                drawing_points.pop()

        # Clear the polygon.
        elif key == ord("c"):

            drawing_points = []
            polygon_closed = False

        # Redraw from scratch.
        elif key == ord("r"):

            drawing_points = []
            polygon_closed = False

        # Cancel ROI drawing.
        elif key == ord("q"):

            cv2.destroyAllWindows()
            cap.release()

            raise SystemExit(
                "ROI drawing cancelled."
            )

cv2.destroyWindow("Draw Queue ROI")

print("\nAll queue regions have been saved.")
# ============================================
# STEP 5: CHECK GPU
# ============================================

if torch.cuda.is_available():

    device = 0

    print(
        "\nUsing GPU:",
        torch.cuda.get_device_name(0)
    )

else:

    device = "cpu"

    print(
        "\nCUDA unavailable. Using CPU."
    )


# ============================================
# STEP 6: LOAD YOLO MODEL
# ============================================

print("\nLoading YOLO model...")

model = YOLO(MODEL_NAME)


# ============================================
# STEP 7: INITIALIZE QUEUE MANAGER
# ============================================

if not is_live_camera:
    cap.set(
        cv2.CAP_PROP_POS_FRAMES,
        0
    )

queue_manager = QueueManager(
    queue_names=queue_names,
    confirmation_seconds=2.5,          # Must remain in ROI before counting entry
    exit_confirmation_seconds=1.5,      # Must remain outside before counting exit
    lost_track_timeout=5.0               # Tolerate short tracking interruptions
)

# Clear any lingering queues from previous sessions so only current queues are active
try:
    reset_queue_status()
except Exception:
    pass

print("\nQueue monitoring started.")

print(
    "Press Q in the video window to stop."
)

STATUS_SAVE_INTERVAL = 0.5
HISTORY_SAVE_INTERVAL = 5.0

last_status_save = time.monotonic() - STATUS_SAVE_INTERVAL
last_history_save = time.monotonic()
last_occupancy_push = 0
last_dashboard_frame_time = 0

native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
if native_fps <= 0 or native_fps > 120:
    native_fps = 30.0
target_frame_interval = 1.0 / native_fps


# ============================================
# STEP 8: MONITOR QUEUES
# ============================================

WINDOW_NAME = "QueueSense - Queue Monitoring"
cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
monitor_scale = min(1100 / frame_width, 700 / frame_height, 1.0)
win_width = int(frame_width * monitor_scale)
win_height = int(frame_height * monitor_scale)
cv2.resizeWindow(WINDOW_NAME, win_width, win_height)

try:

    while True:

        frame_start = time.monotonic()

        success, frame = cap.read()

        if not success:
            if not is_live_camera:
                # Continuous loop for video demonstration
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                success, frame = cap.read()
                if not success:
                    print("Video stream ended.")
                    break
            else:
                time.sleep(0.05)
                success, frame = cap.read()
                if not success:
                    print("Camera stream temporarily unavailable, retrying...")
                    time.sleep(0.1)
                    continue

        now = time.monotonic()

        # Detect and track people using YOLO + ByteTrack (optimized 480px for high-FPS performance).
        results = model.track(
            source=frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=[0],
            conf=0.25,
            iou=0.45,
            imgsz=480,
            device=device,
            verbose=False
        )

        result = results[0]

        # Start with the original frame, without any YOLO boxes or IDs.
        output = frame.copy()

        visible_track_ids = set()

        if (
            result.boxes is not None
            and len(result.boxes) > 0
        ):

            boxes = (
                result.boxes.xyxy.cpu().numpy()
            )

            if result.boxes.id is not None:

                track_ids = (
                    result.boxes.id
                    .int()
                    .cpu()
                    .tolist()
                )

            else:

                track_ids = [
                    None
                ] * len(boxes)

            for box, track_id in zip(boxes, track_ids):

                if track_id is None:
                    continue

                x1, y1, x2, y2 = box
                box_width = float(x2 - x1)
                box_height = float(y2 - y1)

                # Reject tiny/very wide detections that are often partial-body
                # false positives. Tune these thresholds for your camera view.
                if box_width < 15 or box_height < 25:
                    continue
                if box_width / max(box_height, 1.0) > 2.0:
                    continue

                # Include every valid tracked person, even outside queue ROIs.
                visible_track_ids.add(track_id)

                # Multi-point testing to reliably detect people inside the queue:
                # Tests feet, lower body, center torso, and upper body.
                # If ANY of these key points falls within the queue polygon, the person is in the queue!
                cx = float((x1 + x2) / 2)
                test_points = [
                    (cx, float(y2)),                      # Feet
                    (cx, float(y2 - 10)),                 # Ankles
                    (cx, float(y1 + box_height * 0.75)),  # Lower body
                    (cx, float((y1 + y2) / 2)),           # Center torso
                    (cx, float(y1 + box_height * 0.25)),  # Upper torso
                ]
                detected_queue = None

                for queue_index, polygon in enumerate(queue_polygons):
                    for px, py in test_points:
                        if cv2.pointPolygonTest(polygon, (px, py), False) >= 0:
                            detected_queue = queue_names[queue_index]
                            break
                    if detected_queue is not None:
                        break

                queue_manager.update(
                    track_id=track_id,
                    detected_queue=detected_queue,
                    now=now
                )

                # Draw clear bounding boxes for detected people based on queue status:
                confirmed_queue = queue_manager.current_queue.get(track_id)
                bx1, by1, bx2, by2 = map(int, (x1, y1, x2, y2))

                if detected_queue is not None and confirmed_queue == detected_queue:
                    # Confirmed in queue: Bright Green box
                    color = (0, 220, 80)
                    label = f"ID: {track_id} | {confirmed_queue}"
                    cv2.rectangle(output, (bx1, by1), (bx2, by2), color, 2)
                    cv2.putText(output, label, (bx1, max(by1 - 8, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
                elif detected_queue is not None:
                    # Inside ROI, confirming membership: Gold / Yellow box
                    color = (0, 215, 255)
                    label = f"ID: {track_id} entering..."
                    cv2.rectangle(output, (bx1, by1), (bx2, by2), color, 2)
                    cv2.putText(output, label, (bx1, max(by1 - 8, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
                else:
                    # Outside queue ROI: Clean subtle blue box
                    color = (255, 180, 50)  # BGR Cyan/Blue
                    label = f"ID: {track_id}"
                    cv2.rectangle(output, (bx1, by1), (bx2, by2), color, 1)
                    cv2.putText(output, label, (bx1, max(by1 - 6, 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

        # Clean up tracking IDs that disappeared.
        queue_manager.cleanup(
            visible_track_ids=visible_track_ids,
            now=now
        )

        statistics = (
            queue_manager.get_statistics(
                now=now
            )
        )

        # Send live occupancy to the Flask process asynchronously without stalling video playback.
        if now - last_occupancy_push >= 0.25:
            last_occupancy_push = now
            payload = json.dumps({"queues": statistics, "video_name": video_name}).encode("utf-8")
            if not occupancy_queue.empty():
                try:
                    occupancy_queue.get_nowait()
                except queue.Empty:
                    pass
            try:
                occupancy_queue.put_nowait(payload)
            except queue.Full:
                pass

        # Enqueue statistics for background DB saving without stalling OpenCV video loop.
        if now - last_status_save >= STATUS_SAVE_INTERVAL:
            last_status_save = now
            if not db_sync_queue.empty():
                try:
                    db_sync_queue.get_nowait()
                except queue.Empty:
                    pass
            try:
                db_sync_queue.put_nowait((
                    statistics.copy(),
                    False,
                    video_hash,
                    session_id,
                    video_name
                ))
            except queue.Full:
                pass

        # Enqueue historical snapshots every 5 seconds.
        if now - last_history_save >= HISTORY_SAVE_INTERVAL:
            last_history_save = now
            if not db_sync_queue.empty():
                try:
                    db_sync_queue.get_nowait()
                except queue.Empty:
                    pass
            try:
                db_sync_queue.put_nowait((
                    statistics.copy(),
                    True,
                    video_hash,
                    session_id,
                    video_name
                ))
            except queue.Full:
                pass

        # Draw queue polygons and labels.
        for index, polygon in enumerate(
            queue_polygons
        ):

            cv2.polylines(
                output,
                [polygon],
                True,
                (0, 255, 0),
                3
            )

            center = np.mean(
                polygon,
                axis=0
            ).astype(int)

            cv2.putText(
                output,
                queue_names[index],
                tuple(center),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )

        # Display individual queue statistics.
        y_position = 35

        for queue_name in queue_names:

            stats = statistics[queue_name]

            average_wait = (
                stats["average_wait_seconds"]
            )

            text = (
                f"{queue_name}: "
                f"{stats['occupancy']} people"
                f" | In: {stats['entries']}"
                f" | Out: {stats['exits']}"
                f" | Avg elapsed: {average_wait:.1f}s"
            )

            cv2.putText(
                output,
                text,
                (20, y_position),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                2
            )

            y_position += 30

        # Display total occupancy on the video only.
        total_occupancy = sum(
            stats["occupancy"]
            for stats in statistics.values()
        )

        cv2.putText(
            output,
            f"Total queue occupancy: {total_occupancy}",
            (20, y_position + 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 0),
            2
        )

        # Dispatch the frame to the background worker (smooth 25 FPS cap, zero disk/network stalls on video loop).
        now_ts = time.monotonic()
        if now_ts - last_dashboard_frame_time >= 0.04:
            last_dashboard_frame_time = now_ts
            if not frame_sync_queue.empty():
                try:
                    frame_sync_queue.get_nowait()
                except queue.Empty:
                    pass
            try:
                frame_sync_queue.put_nowait(output.copy())
            except queue.Full:
                pass

        # Display the OpenCV monitoring window fitted to screen without zooming.
        if monitor_scale < 1.0:
            screen_output = cv2.resize(output, (win_width, win_height), interpolation=cv2.INTER_AREA)
        else:
            screen_output = output

        cv2.imshow(
            WINDOW_NAME,
            screen_output
        )

        frame_duration = time.monotonic() - frame_start
        if not is_live_camera:
            wait_time = max(1, int((target_frame_interval - frame_duration) * 1000))
        else:
            wait_time = 1

        if cv2.waitKey(wait_time) & 0xFF == ord("q"):

            break

finally:

    cap.release()

    cv2.destroyAllWindows()

    # Clear current queue status when monitoring stops.
    reset_queue_status()

    print(
        "\nQueueSense stopped successfully."
    )