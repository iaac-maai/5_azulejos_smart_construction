# Azulejos — gesture and voice to tile design
Bo De Roeck, Sanjana Kiran, Sneha Sachin Shenoy

## Setup: hand tracking with MediaPipe

MediaPipe (Google, open source, Apache 2.0) is installed as a Python package, not copied into this repo.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-ai.txt   # optional, for voice step 2
python gesture/make_marker.py      # print out/marker_50mm.png at 100% scale
python gesture/frame_square.py     # gesture 01: frame a square with two hands (q to quit)
```

The first run downloads the hand landmarker model into `models/`. Confirmed squares are saved to `out/frame.json`, in millimetres when the marker is in view.

## Gesture → Rhino

1. Open Rhino and run `rhino/watch_tiles.py` once (`_-RunPythonScript`, or Rhino 8 ScriptEditor → Run).
2. In Terminal, run `python gesture/frame_square.py` and frame a square with both hands.
3. Each confirmed square appears in Rhino as a 12 mm tile, with its pre-firing clay outline (12% shrinkage example) and a size label.

Run `watch_tiles.py` again to stop. `rhino/draw_tile.py` draws the latest `out/frame.json` once, without watching.

## Gesture 02: choose a symmetry, then sketch the design in the air

```bash
python gesture/air_sketch.py
```

**1. Choose the symmetry** by drawing two straight strokes over the tile with your index finger:

| Draw | Symmetry |
|---|---|
| + (horizontal and vertical) | mirror across the 4 quadrants |
| X (both diagonals) | mirror across the 4 triangles |
| + and X (a star) | 8-fold, like an azulejo rosette |

Then show an **open palm** for 1 second (or press Enter). Keys instead: `p` = +, `x` = X, `8` = 8-fold, `0` = none.

**2. Draw.** One, two or three fingers held together (starting from the index) draw a thin, medium or thick line. Spreading those fingers moves without drawing. Everything you draw is copied live into the other sections. Keys: `r` switch mirror/rotation, `g` choose the symmetry again, `s` save, `u` undo, `c` clear, `q` quit.

Saving writes `out/sketch.json` and `out/sketch.png`; with `rhino/watch_tiles.py` running, the full pattern appears on the latest tile in Rhino (layer "Azulejos sketch"), with the mirror lines on "Azulejos symmetry guides". See `docs/symmetry_modes.png` for every mode.

Air-canvas idea inspired by [skmelwani/air-canvas-ai](https://github.com/skmelwani/air-canvas-ai) (no licence, so this is our own implementation). Symmetry options follow Procreate's drawing guides.

## Voice: say "azul", then a command

While it listens, the bar at the bottom of the camera window shows **LISTENING**, then what it heard and what it did. The pen lifts as soon as "azul" is heard, so you can point with any finger.

Voice starts with `python gesture/air_sketch.py` (add `--no-voice` to switch it off). The first run downloads the offline speech model (~40 MB) into `models/`. Allow microphone access for Terminal when macOS asks.

| Say "azul, …" | What happens |
|---|---|
| "mirror quadrants" / "triangles" / "eight fold" / "no symmetry" | choose the symmetry |
| "rotate" / "mirror" | turned or mirrored copies |
| "undo" / "clear" / "save" | same as the keys; save sends to Rhino |
| "cobalt", "manganese", "copper", "antimony", "ochre", "black" (or blue, purple, green, yellow, orange) | pen glaze for new lines |
| "change colour" | pen moves to the next glaze; "change the colour of this" recolours the line you point at |
| "make this green" while pointing | recolour the line you point at |
| "delete this" while pointing | remove that line |
| "a bit bigger", "much smaller", "two centimetres bigger" | scale the motif, relative to its real size |
| "turn it a little clockwise", "quarter turn" | rotate the motif |
| "tile two hundred millimetres" | change the tile size (new tile in Rhino on save) |
| "how big is it?" | Azulejos answers out loud |

How it works (`gesture/voice.py`):
1. **Fixed commands** (`voice_commands.py`): offline word matching with Vosk, instant.
2. **Free phrasing** (`voice_ai.py`): anything else is re-transcribed with Whisper and turned into a command by a language model: Claude if `ANTHROPIC_API_KEY` is set, otherwise a local [Ollama](https://ollama.com) model if it is running. Vague amounts ("a bit") are converted to numbers from the motif's real size; unclear requests get a spoken question back.
3. **Speech + pointing**: "this" / "that" picks the line under your fingertip at the moment the word was spoken.

Test the microphone and commands without the camera: `python gesture/voice.py`, or `python gesture/voice.py --text "azulejos a bit bigger"`.

To use Claude: `export ANTHROPIC_API_KEY=...` in the same terminal before running.
