# -*- coding: utf-8 -*-
"""Rajola live link: gestures appear in Rhino automatically.

Run this once inside Rhino (_-RunPythonScript, or Rhino 8 ScriptEditor).
It checks the out/ folder twice a second:
  - out/frame.json changes  (gesture 01 confirmed)  -> a new tile is drawn
  - out/sketch.json changes (gesture 02 saved)      -> the sketch is drawn on the latest tile
Run it again to stop watching.
"""
import json
import os
import sys
import time

import Rhino
import scriptcontext as sc

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)
import draw_tile  # noqa: E402
import draw_sketch  # noqa: E402

try:
    from importlib import reload  # Rhino 8 (Python 3)
except ImportError:
    pass  # Rhino 7 (IronPython 2.7) has reload built in
reload(draw_tile)
reload(draw_sketch)

try:
    from Eto.Forms import UITimer
except ImportError:
    import clr
    clr.AddReference("Eto")
    from Eto.Forms import UITimer

KEY = "rajola_watch"
OUT = os.path.join(draw_tile.repo_root(), "out")
WATCHED = {
    "frame": os.path.join(OUT, "frame.json"),
    "sketch": os.path.join(OUT, "sketch.json"),
}


def mtime(path):
    return os.path.getmtime(path) if os.path.exists(path) else None


def handle(name, data):
    if name == "frame":
        _, s, unit = draw_tile.draw_tile(data)
        return "new tile {:.1f} {}".format(s, unit)
    n = draw_sketch.draw_sketch(data)
    return "sketch with {} strokes drawn on the tile".format(n)


def tick(sender, e):
    state = sc.sticky.get(KEY)
    if not state:
        return
    for name, path in WATCHED.items():
        m = mtime(path)
        if m is None or m == state[name]:
            continue
        time.sleep(0.2)  # let the camera script finish writing the file
        state[name] = m
        sc.doc = Rhino.RhinoDoc.ActiveDoc
        try:
            with open(path) as f:
                msg = handle(name, json.load(f))
            sc.doc.Views.Redraw()
            Rhino.RhinoApp.WriteLine("Rajola: " + msg)
        except Exception as ex:
            Rhino.RhinoApp.WriteLine("Rajola: could not update from {}: {}".format(name, ex))


if KEY in sc.sticky:
    sc.sticky[KEY]["timer"].Stop()
    del sc.sticky[KEY]
    print("Rajola: stopped watching")
else:
    timer = UITimer()
    timer.Interval = 0.5
    timer.Elapsed += tick
    state = {"timer": timer}
    for name, path in WATCHED.items():
        state[name] = mtime(path)
    sc.sticky[KEY] = state
    timer.Start()
    print("Rajola: watching {} - frame a square, then sketch".format(OUT))
