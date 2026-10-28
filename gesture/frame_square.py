"""Gesture 01: frame a square with two hands -> tile outline.

Webcam + MediaPipe Hand Landmarker. Each hand makes an L-shape with thumb
(landmark 4) and index finger (landmark 8). The two L corners are opposite
corners of the square. Hold still for 1 second to confirm; the square is
saved to out/frame.json. If the printed ArUco marker (make_marker.py) is in
view, sizes are converted from pixels to millimetres.

Run:  python gesture/frame_square.py      (press q to quit)
"""
import json
import math
import time
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "hand_landmarker.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")
OUT = ROOT / "out" / "frame.json"

MARKER_MM = 50.0          # printed size of the ArUco marker
HOLD_SECONDS = 1.0        # how long the frame must stay still to confirm
STILL_PX = 12             # max corner movement (pixels) that counts as "still"
L_ANGLE_RANGE = (50, 130)  # thumb/index angle accepted as an L-shape (degrees)

BLUE = (156, 42, 27)      # cobalt, BGR
INK = (58, 24, 22)


def ensure_model():
    if not MODEL.exists():
        MODEL.parent.mkdir(parents=True, exist_ok=True)
        print("Downloading hand landmarker model...")
        urllib.request.urlretrieve(MODEL_URL, MODEL)


def to_px(lm, w, h):
    return np.array([lm.x * w, lm.y * h])


def l_corner(hand, w, h):
    """Return (corner, angle) for one hand's L-shape, or None."""
    thumb_tip, index_tip = to_px(hand[4], w, h), to_px(hand[8], w, h)
    # corner of the L: between thumb base (2) and index base (5)
    corner = (to_px(hand[2], w, h) + to_px(hand[5], w, h)) / 2
    a, b = thumb_tip - corner, index_tip - corner
    cos = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-6)
    angle = math.degrees(math.acos(np.clip(cos, -1, 1)))
    if L_ANGLE_RANGE[0] <= angle <= L_ANGLE_RANGE[1]:
        return corner, angle
    return None


def square_from_diagonal(p1, p2):
    """Four corners of the square whose diagonal is p1 -> p2."""
    c = (p1 + p2) / 2
    half = (p2 - p1) / 2
    perp = np.array([-half[1], half[0]])
    return np.array([p1, c + perp, p2, c - perp])


def mm_per_px(frame, detector):
    """Scale from the ArUco marker if visible, else None."""
    if detector is None:
        return None
    corners, ids, _ = detector.detectMarkers(frame)
    if ids is None or len(corners) == 0:
        return None
    pts = corners[0][0]
    side_px = np.mean([np.linalg.norm(pts[i] - pts[(i + 1) % 4]) for i in range(4)])
    return MARKER_MM / side_px


def main():
    ensure_model()
    options = vision.HandLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
    )
    try:
        aruco = cv2.aruco.ArucoDetector(
            cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))
    except AttributeError:
        aruco = None
        print("ArUco not available in this OpenCV build; sizes stay in pixels.")

    cap = cv2.VideoCapture(0)
    still_since, last = None, None
    t0 = time.time()
    with vision.HandLandmarker.create_from_options(options) as landmarker:
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(image, int((time.time() - t0) * 1000))

            for hand in result.hand_landmarks:
                for i, lm in enumerate(hand):
                    p = tuple(to_px(lm, w, h).astype(int))
                    cv2.circle(frame, p, 7 if i in (4, 8) else 3,
                               BLUE if i in (4, 8) else INK, -1)

            status = "Show two hands, each making an L"
            corners = [l_corner(hd, w, h) for hd in result.hand_landmarks]
            corners = [c for c in corners if c]
            if len(corners) == 2:
                p1, p2 = corners[0][0], corners[1][0]
                square = square_from_diagonal(p1, p2)
                cv2.polylines(frame, [square.astype(np.int32)], True, BLUE, 3)
                side_px = float(np.linalg.norm(p2 - p1) / math.sqrt(2))
                scale = mm_per_px(frame, aruco)
                size = f"{side_px * scale:.0f} mm" if scale else f"{side_px:.0f} px"

                moved = last is None or np.max(np.abs(np.r_[p1, p2] - last)) > STILL_PX
                if moved:
                    still_since = time.time()
                last = np.r_[p1, p2]
                held = time.time() - still_since
                status = f"Tile {size} - hold still {max(0, HOLD_SECONDS - held):.1f}s"
                if held >= HOLD_SECONDS:
                    OUT.parent.mkdir(exist_ok=True)
                    OUT.write_text(json.dumps({
                        "corners_px": square.round(1).tolist(),
                        "side_px": round(side_px, 1),
                        "side_mm": round(side_px * scale, 1) if scale else None,
                        "angle_deg": round(math.degrees(math.atan2(*(square[1] - square[0])[::-1])), 1),
                    }, indent=2))
                    status = f"CONFIRMED: tile {size} -> saved out/frame.json"
            else:
                still_since, last = None, None

            cv2.putText(frame, status, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, BLUE, 2)
            cv2.imshow("Rajola - gesture 01", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
