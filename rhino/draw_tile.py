# -*- coding: utf-8 -*-
"""Rajola, gesture 01 -> Rhino: draw the confirmed tile from out/frame.json.

Run inside Rhino (7 or 8):  command  _-RunPythonScript  and pick this file,
or open it in Rhino 8's ScriptEditor and press Run.

Each run adds one tile, placed to the right of earlier ones, so a series of
test gestures stays visible side by side:
  - layer "Rajola tiles":    the fired tile (side from the gesture, 12 mm thick)
  - layer "Rajola wet size": the clay outline before firing (12% shrinkage)
  - layer "Rajola labels":   a dot with the measured size
"""
import json
import os

import rhinoscriptsyntax as rs

THICKNESS_MM = 12.0     # tile thickness
SHRINKAGE = 0.12        # example clay shrinkage, wet -> fired (replace with workshop test data)
GAP_MM = 60.0           # space between tiles from successive gestures
KEEP_ROTATION = False   # True: keep the hands' rotation; False: axis-aligned tile

TILE_LAYER = "Rajola tiles"
WET_LAYER = "Rajola wet size"
LABEL_LAYER = "Rajola labels"
COBALT = (27, 42, 156)
GREY = (120, 120, 130)


def repo_root():
    try:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        return None


def frame_path():
    root = repo_root()
    if root:
        path = os.path.join(root, "out", "frame.json")
        if os.path.exists(path):
            return path
    return rs.OpenFileName("Select out/frame.json", "JSON (*.json)|*.json||")


def ensure_layer(name, color):
    if not rs.IsLayer(name):
        rs.AddLayer(name, color)
    return name


def next_origin():
    ids = rs.ObjectsByLayer(TILE_LAYER) if rs.IsLayer(TILE_LAYER) else None
    if not ids:
        return 0.0, 0.0
    box = rs.BoundingBox(ids)
    return max(p[0] for p in box) + GAP_MM, 0.0


def draw_tile(data):
    side = data.get("side_mm")
    unit = "mm"
    if not side:
        side = data["side_px"]
        unit = "px (no marker)"
    s = float(side)
    t = THICKNESS_MM

    ensure_layer(TILE_LAYER, COBALT)
    ensure_layer(WET_LAYER, GREY)
    ensure_layer(LABEL_LAYER, COBALT)
    ox, oy = next_origin()

    corners = [(ox, oy, 0), (ox + s, oy, 0), (ox + s, oy + s, 0), (ox, oy + s, 0),
               (ox, oy, t), (ox + s, oy, t), (ox + s, oy + s, t), (ox, oy + s, t)]
    tile = rs.AddBox(corners)
    rs.ObjectLayer(tile, TILE_LAYER)
    rs.ObjectName(tile, "tile {:.1f} {}".format(s, unit))

    wet = s / (1.0 - SHRINKAGE)
    off = (wet - s) / 2.0
    plane = rs.MovePlane(rs.WorldXYPlane(), (ox - off, oy - off, 0))
    outline = rs.AddRectangle(plane, wet, wet)
    rs.ObjectLayer(outline, WET_LAYER)

    dot = rs.AddTextDot("{:.1f} {}".format(s, unit), (ox + s / 2.0, oy - off - 20.0, 0))
    rs.ObjectLayer(dot, LABEL_LAYER)

    if KEEP_ROTATION and data.get("angle_deg") is not None:
        # image y points down, Rhino y points up, so the angle flips sign
        rs.RotateObjects([tile, outline], (ox + s / 2.0, oy + s / 2.0, 0), -float(data["angle_deg"]))
    return tile, s, unit


def run():
    path = frame_path()
    if not path:
        print("Rajola: no frame.json selected")
        return
    with open(path) as f:
        data = json.load(f)
    _, s, unit = draw_tile(data)
    rs.ZoomExtents()
    print("Rajola: drew a {:.1f} {} tile from {}".format(s, unit, path))


if __name__ == "__main__":
    run()
