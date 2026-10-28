# -*- coding: utf-8 -*-
"""Rajola, gesture 02 -> Rhino: draw the air sketch onto the latest tile.

Reads out/sketch.json (from gesture/air_sketch.py) and draws each stroke as a
curve on the top face of the most recent tile (layer "Rajola sketch").
Saving a new sketch replaces the previous sketch on that tile.
If no tile exists yet, one is drawn first from out/frame.json.

Run inside Rhino (_-RunPythonScript or ScriptEditor), or let
rhino/watch_tiles.py run it automatically whenever you save a sketch.
"""
import json
import os
import sys

import rhinoscriptsyntax as rs

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)
import draw_tile  # noqa: E402

SKETCH_LAYER = "Rajola sketch"
MAX_POINTS = 80     # simplify long strokes so curves stay smooth


def latest_tile_box():
    """Bounding box of the most recent (rightmost) tile, or None."""
    if not rs.IsLayer(draw_tile.TILE_LAYER):
        return None
    ids = rs.ObjectsByLayer(draw_tile.TILE_LAYER)
    if not ids:
        return None
    boxes = [rs.BoundingBox(i) for i in ids]
    return max(boxes, key=lambda b: max(p[0] for p in b))


def clear_old_sketch(x0, x1):
    if not rs.IsLayer(SKETCH_LAYER):
        return
    old = []
    for obj in rs.ObjectsByLayer(SKETCH_LAYER) or []:
        box = rs.BoundingBox(obj)
        if box and x0 - 1 <= min(p[0] for p in box) and max(p[0] for p in box) <= x1 + 1:
            old.append(obj)
    if old:
        rs.DeleteObjects(old)


def simplify(points):
    clean = [points[0]]
    for p in points[1:]:
        if p != clean[-1]:
            clean.append(p)
    step = max(1, len(clean) // MAX_POINTS)
    simple = clean[::step]
    if simple[-1] != clean[-1]:
        simple.append(clean[-1])
    return simple


def draw_sketch(data):
    box = latest_tile_box()
    if box is None:
        frame = os.path.join(draw_tile.repo_root(), "out", "frame.json")
        with open(frame) as f:
            draw_tile.draw_tile(json.load(f))
        box = latest_tile_box()
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    zs = [p[2] for p in box]
    ox, oy, top = min(xs), min(ys), max(zs)
    side = max(xs) - ox

    draw_tile.ensure_layer(SKETCH_LAYER, draw_tile.COBALT)
    clear_old_sketch(ox, ox + side)
    count = 0
    for stroke in data.get("strokes_uv", []):
        pts = simplify([(ox + u * side, oy + (1.0 - v) * side, top) for u, v in stroke])
        if len(pts) < 2:
            continue
        curve = rs.AddInterpCurve(pts) if len(pts) >= 4 else rs.AddPolyline(pts)
        if curve:
            rs.ObjectLayer(curve, SKETCH_LAYER)
            count += 1
    return count


def run():
    path = os.path.join(draw_tile.repo_root(), "out", "sketch.json")
    if not os.path.exists(path):
        print("Rajola: no out/sketch.json yet - run gesture/air_sketch.py and press s")
        return
    with open(path) as f:
        n = draw_sketch(json.load(f))
    print("Rajola: drew {} sketch strokes on the tile".format(n))


if __name__ == "__main__":
    run()
