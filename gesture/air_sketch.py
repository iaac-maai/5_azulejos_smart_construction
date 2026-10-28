"""Gesture 02 (air version): sketch the tile's design with your index finger.

Draws inside the tile square framed in gesture 01 (out/frame.json). If there
is no frame yet, a square in the middle of the camera view is used.

Gestures (one hand):
  index finger only          -> draw
  index + middle finger      -> move without drawing (pen up)
  anything else / no hand    -> pen up
Keys:  s save   u undo last stroke   c clear   q quit

Saving writes out/sketch.json (strokes in tile coordinates) and
out/sketch.png (the drawing on a white tile). rhino/watch_tiles.py picks the
JSON up and draws the strokes onto the tile in Rhino.

The air-canvas idea is inspired by github.com/skmelwani/air-canvas-ai; that
repo has no licence, so this is our own implementation, adapted to tiles.

Run:  python gesture/air_sketch.py
"""
import json
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

from frame_square import BLUE, INK, MODEL, ensure_model, to_px

ROOT = Path(__file__).resolve().parent.parent
FRAME = ROOT / "out" / "frame.json"
OUT_JSON = ROOT / "out" / "sketch.json"
OUT_PNG = ROOT / "out" / "sketch.png"

SMOOTH = 0.5          # 0..1, lower = smoother but laggier fingertip
MIN_STEP = 0.004      # minimum movement (fraction of tile side) to add a point
PNG_SIZE = 800

UNIT = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
# (tip, middle joint) landmark pairs; a finger is "up" when its tip is above the joint
FINGERS = {"index": (8, 6), "middle": (12, 10), "ring": (16, 14), "pinky": (20, 18)}


def fingers_up(hand):
    return {name: hand[tip].y < hand[pip].y for name, (tip, pip) in FINGERS.items()}


def pen_mode(hand):
    up = fingers_up(hand)
    others = up["ring"] or up["pinky"]
    if up["index"] and not up["middle"] and not others:
        return "draw"
    if up["index"] and up["middle"] and not others:
        return "hover"
    return "up"


def order_corners(pts):
    """Sort 4 corners as top-left, top-right, bottom-right, bottom-left (image coords)."""
    pts = np.asarray(pts, dtype=np.float32)
    c = pts.mean(axis=0)
    pts = pts[np.argsort(np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0]))]
    return np.roll(pts, -int(np.argmin(pts.sum(axis=1))), axis=0)


def load_tile(w, h):
    """Tile corners in the camera image and its size in mm (or None)."""
    if FRAME.exists():
        data = json.loads(FRAME.read_text())
        return order_corners(data["corners_px"]), data.get("side_mm")
    s = 0.6 * min(w, h)
    x0, y0 = (w - s) / 2, (h - s) / 2
    return order_corners([[x0, y0], [x0 + s, y0], [x0 + s, y0 + s], [x0, y0 + s]]), None


def transform(matrix, pts):
    pts = np.float32(pts).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, matrix).reshape(-1, 2)


def save(strokes, side_mm):
    """Write sketch.json (u, v from the tile's top-left; mm with y up for Rhino) and sketch.png."""
    strokes = [s for s in strokes if len(s) > 1]
    OUT_JSON.parent.mkdir(exist_ok=True)
    data = {
        "tile_side_mm": side_mm,
        "strokes_uv": [[[round(u, 4), round(v, 4)] for u, v in s] for s in strokes],
    }
    if side_mm:
        data["strokes_mm"] = [[[round(u * side_mm, 1), round((1 - v) * side_mm, 1)] for u, v in s]
                              for s in strokes]
    OUT_JSON.write_text(json.dumps(data, indent=2))

    img = np.full((PNG_SIZE, PNG_SIZE, 3), (224, 234, 239), np.uint8)  # warm paper, BGR
    for s in strokes:
        cv2.polylines(img, [(np.array(s) * PNG_SIZE).astype(np.int32)], False, BLUE, 6, cv2.LINE_AA)
    cv2.rectangle(img, (0, 0), (PNG_SIZE - 1, PNG_SIZE - 1), BLUE, 3)
    cv2.imwrite(str(OUT_PNG), img)
    return len(strokes)


def main():
    ensure_model()
    options = vision.HandLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
    )
    cap = cv2.VideoCapture(0)
    ok, frame = cap.read()
    if not ok:
        raise SystemExit("No camera image - check camera permission for Terminal.")
    h, w = frame.shape[:2]
    corners, side_mm = load_tile(w, h)
    to_uv = cv2.getPerspectiveTransform(corners, UNIT)
    to_img = cv2.getPerspectiveTransform(UNIT, corners)

    strokes, current, tip = [], None, None
    message, message_until = "", 0.0
    t0 = time.time()
    with vision.HandLandmarker.create_from_options(options) as landmarker:
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(image, int((time.time() - t0) * 1000))

            mode = "up"
            if result.hand_landmarks:
                hand = result.hand_landmarks[0]
                mode = pen_mode(hand)
                raw = to_px(hand[8], w, h)
                tip = raw if tip is None else SMOOTH * raw + (1 - SMOOTH) * tip
            else:
                tip = None

            uv = transform(to_uv, [tip])[0] if tip is not None else None
            inside = uv is not None and bool(np.all(uv >= 0) and np.all(uv <= 1))
            if mode == "draw" and inside:
                if current is None:
                    current = []
                    strokes.append(current)
                if not current or np.linalg.norm(np.array(current[-1]) - uv) > MIN_STEP:
                    current.append([float(uv[0]), float(uv[1])])
            else:
                current = None

            cv2.polylines(frame, [corners.astype(np.int32)], True, BLUE, 2)
            for s in strokes:
                if len(s) > 1:
                    cv2.polylines(frame, [transform(to_img, s).astype(np.int32)], False, BLUE, 4, cv2.LINE_AA)
            if tip is not None:
                p = tuple(tip.astype(int))
                if mode == "draw":
                    cv2.circle(frame, p, 10, BLUE, -1)
                else:
                    cv2.circle(frame, p, 8, INK, 2)

            label = {"draw": "DRAWING", "hover": "MOVING - pen up", "up": "PEN UP"}[mode]
            size = f"{side_mm:.0f} mm tile" if side_mm else "tile (no mm)"
            cv2.putText(frame, f"{label} | {size} | strokes {len([s for s in strokes if len(s) > 1])}",
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, BLUE, 2)
            cv2.putText(frame, "index = draw   index+middle = move   s save  u undo  c clear  q quit",
                        (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, BLUE, 2)
            if time.time() < message_until:
                cv2.putText(frame, message, (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.9, BLUE, 2)
            cv2.imshow("Rajola - gesture 02 air sketch", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("c"):
                strokes, current = [], None
            if key == ord("u") and strokes:
                strokes.pop()
                current = None
            if key == ord("s"):
                n = save(strokes, side_mm)
                message, message_until = f"SAVED {n} strokes -> out/sketch.json + sketch.png", time.time() + 2
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
