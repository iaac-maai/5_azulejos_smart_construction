"""Gesture 02 (air version): choose a symmetry, then sketch the tile's design.

Draws inside the tile square framed in gesture 01 (out/frame.json). If there
is no frame yet, a square in the middle of the camera view is used.

Step 1 - choose the symmetry by drawing it over the tile (index finger):
  two straight strokes, horizontal + vertical   -> +  mirror across quadrants
  two straight strokes along the diagonals      -> X  mirror across triangles
  both (+ and X, a star)                        -> *  8-fold, like a rosette
  then show an OPEN PALM for 1 second (or press Enter) to start drawing.
  Keys instead of gestures: p = +, x = X, 8 = *, 0 = no symmetry.

Step 2 - draw. Every stroke is copied live into the other sections.
  index finger only                  -> draw a thin line
  index + middle, held together      -> draw a medium line
  index + middle + ring, together    -> draw a thick line
  those fingers spread apart         -> move without drawing (pen up)
  anything else / no hand            -> pen up
Keys:  r mirror/rotate   g choose symmetry again   s save   u undo
       c clear   q quit

Voice (say "azul" first; see voice.py), for example:
  "change colour"  "make this bigger"  "delete this"  "make this green"
  "mirror quadrants"  "eight fold"  "rotate"  "undo"  "clear"  "save"
  "cobalt" (pen colour)  "a bit bigger"  "tile two hundred millimetres"
While "this" is being said, the line under your fingertip is the one changed.
The pen lifts as soon as "azul" is heard, so pointing never draws. The bar at
the bottom shows LISTENING, then what was heard and what it did.
Run with --no-voice to switch voice off.

Saving writes out/sketch.json (strokes, glazes, finger counts, symmetry and
every mirrored copy) and out/sketch.png. rhino/watch_tiles.py picks the JSON up and draws the
full, coloured pattern onto the tile in Rhino.

The air-canvas idea is inspired by github.com/skmelwani/air-canvas-ai; that
repo has no licence, so this is our own implementation, adapted to tiles.
Symmetry options follow Procreate's drawing guides (quadrant, radial,
rotational).

Run:  python gesture/air_sketch.py
"""
import json
import queue
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

import symmetry
import voice_commands as vc
from frame_square import BLUE, INK, MODEL, ensure_model, to_px

ROOT = Path(__file__).resolve().parent.parent
FRAME = ROOT / "out" / "frame.json"
OUT_JSON = ROOT / "out" / "sketch.json"
OUT_PNG = ROOT / "out" / "sketch.png"

SMOOTH = 0.5          # 0..1, lower = smoother but laggier fingertip
MIN_STEP = 0.004      # minimum movement (fraction of tile side) to add a point
CHOOSE_MARGIN = 0.15  # choice strokes may run this far past the tile edge
PALM_SECONDS = 1.0    # hold an open palm this long to confirm the symmetry
PNG_SIZE = 800
TOGETHER = 1.5        # fingers touch if tips are closer than this many knuckle gaps
HOLD_FRAMES = 3       # a gesture must last this long to count, so flicker can't break a stroke
LINE_PX = {1: 4, 2: 9, 3: 15}         # line thickness by finger count, camera view
PNG_LINE_PX = {1: 6, 2: 14, 3: 24}    # same, for sketch.png
VOICE_SECONDS = 6.0   # how long the last heard command stays on screen
POINT_WINDOW = 0.5    # look this many seconds either side of "this" for a line to point at

GUIDE = (205, 160, 150)   # light cobalt for mirror lines, BGR

UNIT = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
# (tip, middle joint) landmark pairs; a finger is "up" when its tip is above the joint
FINGERS = {"index": (8, 6), "middle": (12, 10), "ring": (16, 14), "pinky": (20, 18)}
KNUCKLES = {"index": 5, "middle": 9, "ring": 13}


def bgr(hex_colour):
    h = hex_colour.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


GLAZE_BGR = {name: bgr(hx) for name, hx in vc.GLAZES.items()}


def fingers_up(hand):
    return {name: hand[tip].y < hand[pip].y for name, (tip, pip) in FINGERS.items()}


def together(hand, a, b, w, h):
    """True if two fingers touch. a, b are FINGERS names; the gap is scaled by the
    knuckle gap so it doesn't depend on how far the hand is from the camera."""
    tips = np.linalg.norm(to_px(hand[FINGERS[a][0]], w, h) - to_px(hand[FINGERS[b][0]], w, h))
    knuckles = np.linalg.norm(to_px(hand[KNUCKLES[a]], w, h) - to_px(hand[KNUCKLES[b]], w, h))
    return tips < TOGETHER * knuckles


def pen_mode(hand, w, h):
    """Return (mode, fingers): mode is draw / hover / palm / up, fingers is 1-3 when drawing."""
    up = fingers_up(hand)
    if all(up.values()):
        return "palm", 0
    if not up["index"] or up["pinky"]:
        return "up", 0
    if not up["middle"]:
        return ("up", 0) if up["ring"] else ("draw", 1)
    if not together(hand, "index", "middle", w, h):
        return "hover", 0
    if not up["ring"]:
        return "draw", 2
    return ("draw", 3) if together(hand, "middle", "ring", w, h) else ("hover", 0)


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


def save(strokes, glazes, widths, side_mm, sym, rotate, size_changed=False):
    """Write sketch.json and sketch.png with the full mirrored, coloured pattern."""
    keep = [i for i, s in enumerate(strokes) if len(s) > 1]
    strokes = [strokes[i] for i in keep]
    glazes = [glazes[i] for i in keep]
    widths = [widths[i] for i in keep]
    pattern, sources = symmetry.expand_with_sources(strokes, sym, rotate)
    OUT_JSON.parent.mkdir(exist_ok=True)
    if size_changed and side_mm and FRAME.exists():
        # a spoken tile size: update the frame first so Rhino draws the new tile
        frame = json.loads(FRAME.read_text())
        frame["side_mm"] = round(float(side_mm), 1)
        FRAME.write_text(json.dumps(frame, indent=2))
        time.sleep(0.6)   # let the Rhino watcher draw the tile before the sketch
    data = {
        "tile_side_mm": side_mm,
        "symmetry": sym or "none",
        "mode": "rotate" if rotate else "mirror",
        "strokes_uv": [[[round(u, 4), round(v, 4)] for u, v in s] for s in strokes],
        "glazes": glazes,
        "fingers": widths,
        "strokes_all_uv": [[[round(u, 4), round(v, 4)] for u, v in s] for s in pattern],
        "strokes_all_glaze": [glazes[i] for i in sources],
        "strokes_all_fingers": [widths[i] for i in sources],
        "glaze_palette": vc.GLAZES,
        "axes_uv": symmetry.axes(sym),
    }
    if side_mm:
        data["strokes_mm"] = [[[round(u * side_mm, 1), round((1 - v) * side_mm, 1)] for u, v in s]
                              for s in pattern]
    OUT_JSON.write_text(json.dumps(data, indent=2))

    img = np.full((PNG_SIZE, PNG_SIZE, 3), (224, 234, 239), np.uint8)  # warm paper, BGR
    for a, b in symmetry.axes(sym):
        cv2.line(img, tuple((np.array(a) * PNG_SIZE).astype(int)),
                 tuple((np.array(b) * PNG_SIZE).astype(int)), GUIDE, 1, cv2.LINE_AA)
    for s, source in zip(pattern, sources):
        cv2.polylines(img, [(np.array(s) * PNG_SIZE).astype(np.int32)], False,
                      GLAZE_BGR[glazes[source]], PNG_LINE_PX[widths[source]], cv2.LINE_AA)
    cv2.rectangle(img, (0, 0), (PNG_SIZE - 1, PNG_SIZE - 1), BLUE, 3)
    cv2.imwrite(str(OUT_PNG), img)
    return len(strokes), len(pattern)


def draw_lines(frame, to_img, lines, color, width):
    for s in lines:
        if len(s) > 1:
            cv2.polylines(frame, [transform(to_img, s).astype(np.int32)], False, color, width, cv2.LINE_AA)


def motif_size_mm(strokes, sym, rotate, side_mm):
    """Width of the whole mirrored pattern in mm (for 'a bit bigger' etc.)."""
    pattern = symmetry.expand(strokes, sym, rotate)
    if not pattern or not side_mm:
        return None
    pts = np.vstack([np.asarray(s) for s in pattern])
    return float(max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1])) * side_mm)


def start_voice():
    if "--no-voice" in sys.argv:
        return None
    try:
        from voice import VoiceListener
    except ImportError as error:
        print(f"Azulejos voice off: {error}")
        return None
    return VoiceListener


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

    phase = "choose"                  # "choose" the symmetry, then "draw"
    sym, rotate, detected = None, False, None
    choice_strokes = []
    strokes, glazes, widths, current, tip = [], [], [], None, None
    pen, candidate, held = ("up", 0), ("up", 0), 0
    voice_line, voice_until, said_at = "", 0.0, 0.0
    pen_glaze = "cobalt"
    size_changed = False
    tip_history = deque(maxlen=300)   # (time, uv) of the fingertip, for "this"
    palm_since = None
    message, message_until = "", 0.0
    t0 = time.time()

    def say(text, seconds=3.0, out_loud=True):
        nonlocal message, message_until
        message, message_until = text, time.time() + seconds
        if out_loud:
            vc.speak(text)

    def start_drawing(choice):
        nonlocal phase, sym, current
        phase, sym, current = "draw", choice, None
        say(f"Symmetry: {symmetry.NAMES[sym]} - start drawing", 2.5, out_loud=False)

    def context():
        return {
            "phase": phase,
            "tile_mm": round(side_mm, 1) if side_mm else None,
            "symmetry": sym or "not chosen",
            "mode": "rotate" if rotate else "mirror",
            "strokes": len([s for s in strokes if len(s) > 1]),
            "pen_glaze": pen_glaze,
            "glazes_used": sorted(set(glazes)),
            "motif_mm": round(motif_size_mm(strokes, sym, rotate, side_mm) or 0, 1),
        }

    def pointed_stroke(command):
        """Original stroke under the fingertip when 'this' was said."""
        moment = command.pointed_at or command.created
        # closest moment first; pointing and word timing are never exact
        near = sorted((item for item in tip_history if abs(item[0] - moment) <= POINT_WINDOW),
                      key=lambda item: abs(item[0] - moment))
        for _, uv in near:
            index = symmetry.nearest_stroke(uv, strokes, sym, rotate)
            if index is not None:
                return index
        return None

    def apply(command):
        """Carry out one voice command; returns what Azulejos says back."""
        nonlocal sym, rotate, strokes, glazes, widths, current, pen_glaze, side_mm, size_changed
        i = command.intent
        action = i.get("action")
        target = i.get("target", "all")
        if action == "set_symmetry":
            if phase == "choose":
                start_drawing(i["symmetry"])
            else:
                sym = i["symmetry"]
            return f"Symmetry: {symmetry.NAMES[i['symmetry']]}"
        if phase == "choose" and action not in ("query", "unknown"):
            return "First choose a symmetry: say mirror quadrants, triangles or eight fold"
        if action == "set_mode":
            rotate = i.get("mode") == "rotate"
            return "Rotating copies" if rotate else "Mirroring copies"
        if action == "undo":
            if strokes:
                strokes.pop()
                glazes.pop()
                widths.pop()
                current = None
                return "Undone"
            return "Nothing to undo"
        if action == "clear":
            strokes, glazes, widths, current = [], [], [], None
            return "Cleared"
        if action == "save":
            n, total = save(strokes, glazes, widths, side_mm, sym, rotate, size_changed)
            size_changed = False
            return f"Saved {n} lines, {total} with copies, sent to Rhino"
        if action in ("glaze", "delete", "scale_motif", "rotate_motif") and target in ("this", "last"):
            if target == "last":
                index = len(strokes) - 1 if strokes else None
            else:
                index = pointed_stroke(command)
            if index is None:
                return ("Point at a line while you say this"
                        if target == "this" else "There is no line yet")
            indices = [index]
        else:
            indices = list(range(len(strokes)))
        if action == "glaze":
            if target == "pen":
                pen_glaze = vc.next_glaze(pen_glaze) if i["glaze"] == "next" else i["glaze"]
                return f"Pen colour {pen_glaze}"
            if not indices:
                return "There is no line yet"
            glaze = vc.next_glaze(glazes[indices[0]]) if i["glaze"] == "next" else i["glaze"]
            for k in indices:
                glazes[k] = glaze
            return f"{glaze.capitalize()} on {'this line' if len(indices) == 1 else 'everything'}"
        if action == "delete":
            for k in sorted(indices, reverse=True):
                del strokes[k], glazes[k], widths[k]
            current = None
            return "Deleted"
        if action == "scale_motif":
            factor = vc.resolve_scale(i, motif_size_mm(strokes, sym, rotate, side_mm))
            for k in indices:
                strokes[k] = symmetry.transform_strokes([strokes[k]], scale=factor)[0]
            current = None
            return f"{'Bigger' if factor > 1 else 'Smaller'} by {abs(factor - 1) * 100:.0f} percent"
        if action == "rotate_motif":
            degrees = vc.resolve_degrees(i)
            for k in indices:
                strokes[k] = symmetry.transform_strokes([strokes[k]], degrees=degrees)[0]
            current = None
            return f"Turned {abs(degrees):.0f} degrees"
        if action == "set_tile_size":
            side_mm, size_changed = float(i["millimetres"]), True
            return f"Tile set to {side_mm:.0f} millimetres; it changes in Rhino when you save"
        if action == "query":
            q = i.get("question", "size")
            if q == "size":
                return f"The tile is {side_mm:.0f} millimetres" if side_mm else "The tile has no size in millimetres yet"
            if q == "symmetry":
                return f"{symmetry.NAMES.get(sym, 'no symmetry chosen')}, {'rotating' if rotate else 'mirroring'}"
            if q == "glaze":
                return f"The pen is {pen_glaze}"
            return f"{len(strokes)} lines"
        return i.get("clarify") or f"Sorry, I did not understand: {command.heard}"

    Listener = start_voice()
    listener = Listener(context_fn=context) if Listener else None
    if listener:
        listener.start()

    with vision.HandLandmarker.create_from_options(options) as landmarker:
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            now = time.time()
            result = landmarker.detect_for_video(image, int((now - t0) * 1000))

            if result.hand_landmarks:
                hand = result.hand_landmarks[0]
                seen = pen_mode(hand, w, h)
                held = held + 1 if seen == candidate else 1
                candidate = seen
                if held >= HOLD_FRAMES:
                    pen = candidate
                raw = to_px(hand[8], w, h)
                tip = raw if tip is None else SMOOTH * raw + (1 - SMOOTH) * tip
            else:
                tip = None
                pen, candidate, held = ("up", 0), ("up", 0), 0
            mode, fingers = pen
            # after "azul" the finger is pointing, not drawing
            listening = bool(listener) and now < listener.awake_until
            if listening and mode == "draw":
                mode = "hover"

            uv = transform(to_uv, [tip])[0] if tip is not None else None
            if uv is not None:
                tip_history.append((now, uv.copy()))
            margin = CHOOSE_MARGIN if phase == "choose" else 0.0
            inside = uv is not None and bool(np.all(uv >= -margin) and np.all(uv <= 1 + margin))

            if mode == "draw" and inside:
                resized = phase == "draw" and current is not None and widths[-1] != fingers
                if current is None or resized:
                    # a change of width mid-line starts where the last stroke ended, so no gap
                    current = [current[-1]] if resized else []
                    if phase == "choose":
                        choice_strokes.append(current)
                    else:
                        strokes.append(current)
                        glazes.append(pen_glaze)
                        widths.append(fingers)
                if not current or np.linalg.norm(np.array(current[-1]) - uv) > MIN_STEP:
                    current.append([float(uv[0]), float(uv[1])])
            else:
                if current is not None and phase == "choose":
                    detected = symmetry.classify(choice_strokes)
                current = None

            # open palm held for a second confirms the detected symmetry
            if phase == "choose" and mode == "palm" and detected:
                palm_since = palm_since or now
                if now - palm_since >= PALM_SECONDS:
                    start_drawing(detected)
                    palm_since = None
            else:
                palm_since = None

            # shown straight away, in case the AI step takes a moment to reply
            if listener and listener.said_at > said_at:
                said_at = listener.said_at
                voice_line, voice_until = f"HEARD: '{listener.said}'", now + VOICE_SECONDS
            # voice commands that arrived since the last frame
            while listener:
                try:
                    command = listener.commands.get_nowait()
                except queue.Empty:
                    break
                reply = apply(command)
                voice_line, voice_until = f"HEARD: '{command.heard}' -> {reply}", now + VOICE_SECONDS
                vc.speak(reply)

            # --- drawing on the camera image
            cv2.polylines(frame, [corners.astype(np.int32)], True, BLUE, 2)
            if phase == "choose":
                draw_lines(frame, to_img, choice_strokes, INK, 3)
                if detected:
                    draw_lines(frame, to_img, symmetry.axes(detected), BLUE, 2)
            else:
                draw_lines(frame, to_img, symmetry.axes(sym), GUIDE, 1)
                pattern, sources = symmetry.expand_with_sources(strokes, sym, rotate)
                for s, source in zip(pattern, sources):
                    draw_lines(frame, to_img, [s], GLAZE_BGR[glazes[source]], LINE_PX[widths[source]])
                for s, glaze, width in zip(strokes, glazes, widths):
                    draw_lines(frame, to_img, [s], GLAZE_BGR[glaze], LINE_PX[width] + 2)
            if tip is not None:
                p = tuple(tip.astype(int))
                if mode == "draw":
                    cv2.circle(frame, p, 6 + LINE_PX[fingers] // 2, GLAZE_BGR[pen_glaze], -1)
                else:
                    cv2.circle(frame, p, 8, INK, 2)

            if phase == "choose":
                if detected:
                    hold = f" {max(0.0, PALM_SECONDS - (now - palm_since)):.1f}s" if palm_since else ""
                    top = f"Detected {symmetry.NAMES[detected]} - open palm{hold} or Enter to start"
                    if detected != "*":
                        top += " | draw the other cross too for 8-fold"
                elif len(choice_strokes) >= 4:
                    top = "Not recognised - press c and draw two straight strokes"
                else:
                    top = "Choose symmetry: draw + (quadrants) or X (triangles) over the tile"
                bottom = "keys: p = +   x = X   8 = 8-fold   0 = none   c clear   q quit"
            else:
                label = {"draw": f"DRAWING {fingers} finger{'s' if fingers > 1 else ''}",
                         "hover": "PEN UP / POINTING"}.get(mode, "PEN UP")
                size = f"{side_mm:.0f} mm" if side_mm else "no mm"
                kind = "rotate" if rotate else "mirror"
                top = (f"{label} | {symmetry.NAMES[sym]}, {kind} | {pen_glaze} | {size} | "
                       f"lines {len([s for s in strokes if len(s) > 1])}")
                bottom = "1/2/3 fingers together = line width  spread = pen up  r mirror/rotate  g symmetry  s save  u undo  c clear  q quit"
            cv2.putText(frame, top, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, BLUE, 2)
            cv2.putText(frame, bottom, (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, BLUE, 2)
            if listener:
                if listening:
                    words = vc.find_wake(listener.partial)[1].replace("[unk]", "").strip()
                    mic = f"LISTENING...  {words}"
                elif now < voice_until:
                    mic = voice_line
                else:
                    mic = listener.status
                # a solid bar, so the text stays readable over the camera image
                cv2.rectangle(frame, (0, h - 78), (w, h - 42), BLUE if listening else INK, -1)
                cv2.putText(frame, mic, (20, h - 52), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
            if now < message_until:
                cv2.putText(frame, message, (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, BLUE, 2)
            cv2.imshow("Azulejos - gesture 02 air sketch", frame)

            # --- keys
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if phase == "choose":
                if key in (13, 10, 32) and detected:      # Enter or space
                    start_drawing(detected)
                elif key in (ord("p"), ord("+"), ord("=")):
                    start_drawing("+")
                elif key == ord("x"):
                    start_drawing("X")
                elif key == ord("8"):
                    start_drawing("*")
                elif key == ord("0"):
                    start_drawing("none")
                elif key == ord("c"):
                    choice_strokes, detected, current = [], None, None
            else:
                if key == ord("r"):
                    rotate = not rotate
                    say("Rotation: each section is a turned copy" if rotate
                        else "Mirror: each section is a reflection", 2, out_loud=False)
                if key == ord("g"):
                    phase, choice_strokes, detected, current = "choose", [], None, None
                if key == ord("c"):
                    strokes, glazes, widths, current = [], [], [], None
                if key == ord("u") and strokes:
                    strokes.pop()
                    glazes.pop()
                    widths.pop()
                    current = None
                if key == ord("s"):
                    n, total = save(strokes, glazes, widths, side_mm, sym, rotate, size_changed)
                    size_changed = False
                    say(f"SAVED {n} lines ({total} with copies) -> out/sketch.json", 2.5, out_loud=False)
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
