import cv2
import torch
from pathlib import Path
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "yolo26n.pt"
VIDEO_PATH = BASE_DIR / "videos" / "video1.mp4"

def main():
    # 1. Check GPU availability
    if torch.cuda.is_available():
        device = 0
        print("GPU:", torch.cuda.get_device_name(0))
    else:
        device = "cpu"
        print("CUDA unavailable. Using CPU.")

    # 2. Load the YOLO model
    print(f"Loading YOLO model from {MODEL_PATH}...")
    model = YOLO(str(MODEL_PATH))

    # 3. Open the video file
    video_to_open = VIDEO_PATH
    if not video_to_open.exists():
        videos = list((BASE_DIR / "videos").glob("*.mp4"))
        if videos:
            video_to_open = videos[0]
        else:
            print(f"Error: No video found in {BASE_DIR / 'videos'}")
            return

    cap = cv2.VideoCapture(str(video_to_open))
    if not cap.isOpened():
        print(f"Error: Could not open video: {video_to_open}")
        return

    print(f"Video opened: {video_to_open.name}")
    print("Press Q to exit.")

    # 4. Process video frames
    while True:
        success, frame = cap.read()
        if not success:
            print("Video finished.")
            break

        results = model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=[0],
            conf=0.35,
            device=device,
            verbose=False
        )

        annotated_frame = results[0].plot()
        person_count = len(results[0].boxes)

        cv2.putText(
            annotated_frame,
            f"People detected: {person_count}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2
        )

        cv2.imshow("QueueSense - Person Detection Test", annotated_frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("QueueSense video test completed.")

if __name__ == "__main__":
    main()
