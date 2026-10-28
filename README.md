# 5_ullada_smart_construction
Bo De Roeck, Sanjana Kiran, Sneha Sachin Shenoy

## Setup: hand tracking with MediaPipe

MediaPipe (Google, open source, Apache 2.0) is installed as a Python package, not copied into this repo.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python gesture/make_marker.py      # print out/marker_50mm.png at 100% scale
python gesture/frame_square.py     # gesture 01: frame a square with two hands (q to quit)
```

The first run downloads the hand landmarker model into `models/`. Confirmed squares are saved to `out/frame.json`, in millimetres when the marker is in view.

## Gesture → Rhino

1. Open Rhino and run `rhino/watch_tiles.py` once (`_-RunPythonScript`, or Rhino 8 ScriptEditor → Run).
2. In Terminal, run `python gesture/frame_square.py` and frame a square with both hands.
3. Each confirmed square appears in Rhino as a 12 mm tile, with its pre-firing clay outline (12% shrinkage example) and a size label.

Run `watch_tiles.py` again to stop. `rhino/draw_tile.py` draws the latest `out/frame.json` once, without watching.

## Gesture 02: sketch the design in the air

```bash
python gesture/air_sketch.py
```

Draw inside the tile square from gesture 01: **index finger only** draws, **index + middle** moves without drawing. Keys: `s` save, `u` undo, `c` clear, `q` quit. Saving writes `out/sketch.json` and `out/sketch.png`; with `rhino/watch_tiles.py` running, the sketch appears on the latest tile in Rhino (layer "Rajola sketch").

Air-canvas idea inspired by [skmelwani/air-canvas-ai](https://github.com/skmelwani/air-canvas-ai) (no licence, so this is our own implementation).
