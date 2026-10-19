import cv2
import time

def scan_cameras(max_index=5):
    print(f"Scanning camera indices 0 through {max_index - 1}...")
    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok and frame is not None:
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                found.append((i, w, h))
            cap.release()
    return found

def main():
    print("=" * 45)
    print("   QueueSense - USB Webcam Diagnostic Tool")
    print("=" * 45)
    
    cameras = scan_cameras(max_index=5)
    
    if not cameras:
        print("\n[!] No cameras detected on indices 0-4.")
        print("    Suggestions:")
        print("    1. Plug in your USB webcam securely.")
        print("    2. Make sure Windows privacy settings allow camera access.")
        print("    3. Close any application (Zoom, Teams, Skype, Chrome) that may be locking the webcam.")
        return

    print("\nDetected Cameras:")
    for idx, w, h in cameras:
        tag = " (Default / Laptop)" if idx == 0 else " (External / USB Webcam)"
        print(f"  [{idx}] Index {idx} - Resolution: {w}x{h}{tag}")

    choice_str = input(f"\nEnter camera index to test [default: {cameras[0][0]}]: ").strip()
    if not choice_str:
        chosen_idx = cameras[0][0]
    elif choice_str.isdigit() and int(choice_str) in [c[0] for c in cameras]:
        chosen_idx = int(choice_str)
    else:
        print("Invalid selection. Exiting.")
        return

    print(f"\nOpening Camera {chosen_idx}...")
    cap = cv2.VideoCapture(chosen_idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(chosen_idx)

    if not cap.isOpened():
        print(f"[!] Failed to open camera {chosen_idx}.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Stream running at {actual_w}x{actual_h}. Press 'Q' to exit.")

    fps_count = 0
    start_time = time.time()
    fps = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame.")
            break

        fps_count += 1
        elapsed = time.time() - start_time
        if elapsed >= 1.0:
            fps = fps_count / elapsed
            fps_count = 0
            start_time = time.time()

        cv2.putText(
            frame,
            f"QueueSense Camera Diagnostic | Index: {chosen_idx} | FPS: {fps:.1f}",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2
        )
        cv2.putText(
            frame,
            "Press 'Q' to exit",
            (20, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 200, 255),
            2
        )

        cv2.imshow("QueueSense - Camera Test", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("Camera test completed.")

if __name__ == "__main__":
    main()
