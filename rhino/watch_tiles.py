# -*- coding: utf-8 -*-
"""Rajola live link: every confirmed gesture appears in Rhino automatically.

Run this once inside Rhino (_-RunPythonScript, or Rhino 8 ScriptEditor).
It checks out/frame.json twice a second; whenever frame_square.py saves a new
confirmed square, the tile is drawn (see draw_tile.py).
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

try:
    from importlib import reload  # Rhino 8 (Python 3)
except ImportError:
    pass  # Rhino 7 (IronPython 2.7) has reload built in
reload(draw_tile)

try:
    from Eto.Forms import UITimer
except ImportError:
    import clr
    clr.AddReference("Eto")
    from Eto.Forms import UITimer

KEY = "rajola_watch"
PATH = os.path.join(draw_tile.repo_root(), "out", "frame.json")


def mtime():
    return os.path.getmtime(PATH) if os.path.exists(PATH) else None


def tick(sender, e):
    state = sc.sticky.get(KEY)
    if not state:
        return
    m = mtime()
    if m is None or m == state["mtime"]:
        return
    time.sleep(0.2)  # let frame_square.py finish writing the file
    state["mtime"] = m
    sc.doc = Rhino.RhinoDoc.ActiveDoc
    try:
        with open(PATH) as f:
            data = json.load(f)
        _, s, unit = draw_tile.draw_tile(data)
        sc.doc.Views.Redraw()
        Rhino.RhinoApp.WriteLine("Rajola: new tile {:.1f} {}".format(s, unit))
    except Exception as ex:
        Rhino.RhinoApp.WriteLine("Rajola: could not draw tile: {}".format(ex))


if KEY in sc.sticky:
    sc.sticky[KEY]["timer"].Stop()
    del sc.sticky[KEY]
    print("Rajola: stopped watching")
else:
    timer = UITimer()
    timer.Interval = 0.5
    timer.Elapsed += tick
    sc.sticky[KEY] = {"timer": timer, "mtime": mtime()}
    timer.Start()
    print("Rajola: watching {} - frame a square to add a tile".format(PATH))
