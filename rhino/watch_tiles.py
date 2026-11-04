# -*- coding: utf-8 -*-
"""Azulejos live link: gestures appear in Rhino automatically.

Run this once inside Rhino (_-RunPythonScript, or Rhino 8 ScriptEditor).
It checks the out/ folder twice a second:
  - out/frame.json changes  (gesture 01 confirmed)  -> a new tile is drawn
  - out/sketch.json changes (gesture 02 saved)      -> the sketch is drawn on the latest tile
Run it again to stop watching. It prints the folder it watches: that must be
the out/ folder of the copy of the repo you run the gesture scripts from.

The drawing scripts (draw_tile.py, draw_sketch.py) are reloaded on every
update, so code changes in the repo are picked up without restarting.
"""
import json
import os
import sys
import time

import Rhino
import scriptcontext as sc

# Rhino keeps modules and sys.path between script runs, so another copy of this
# repo run earlier in the session would otherwise be used instead of this one.
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE in sys.path:
    sys.path.remove(HERE)
sys.path.insert(0, HERE)
sys.modules.pop("draw_tile", None)
sys.modules.pop("draw_sketch", None)
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

KEY = "azulejos_watch"
OLD_KEYS = ["rajola_watch"]   # watcher from before the rename
OUT = os.path.join(os.path.dirname(HERE), "out")
WATCHED = {
    "frame": os.path.join(OUT, "frame.json"),
    "sketch": os.path.join(OUT, "sketch.json"),
}


def mtime(path):
    return os.path.getmtime(path) if os.path.exists(path) else None


def handle(name, data):
    # always use the latest version of the drawing scripts from the repo
    reload(draw_tile)
    reload(draw_sketch)
    if name == "frame":
        _, s, unit = draw_tile.draw_tile(data)
        return "new tile {:.1f} {}".format(s, unit)
    n = draw_sketch.draw_sketch(data)
    return "sketch drawn: {} curves ({} {})".format(
        n, data.get("symmetry", "none"), data.get("mode", "mirror"))


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
            Rhino.RhinoApp.WriteLine("Azulejos: " + msg)
        except Exception as ex:
            Rhino.RhinoApp.WriteLine("Azulejos: could not update from {}: {}".format(name, ex))


for old in OLD_KEYS:
    if old in sc.sticky:
        sc.sticky[old]["timer"].Stop()
        del sc.sticky[old]

running = sc.sticky.pop(KEY, None)
if running:
    running["timer"].Stop()
if running and running.get("out") == OUT:
    print("Azulejos: stopped watching")
else:   # not running, or watching another copy of the repo: switch to this one
    timer = UITimer()
    timer.Interval = 0.5
    timer.Elapsed += tick
    state = {"timer": timer, "out": OUT}
    for name, path in WATCHED.items():
        state[name] = mtime(path)
    sc.sticky[KEY] = state
    timer.Start()
    print("Azulejos: watching {} - frame a square, then sketch".format(OUT))
