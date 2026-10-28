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
