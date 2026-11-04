# -*- coding: utf-8 -*-
"""Azulejos, gesture 02 -> Rhino: draw the air sketch onto the latest tile.

Reads out/sketch.json (from gesture/air_sketch.py) and draws the full pattern
(every mirrored or rotated copy) as curves on the top face of the most recent
tile (layer "Azulejos sketch"), plus the + / X mirror lines on a separate layer
("Azulejos symmetry guides") that you can switch off. Each curve gets the
glaze colour it was drawn or voiced in (cobalt, copper, manganese ...).
Each curve also gets a print width from the number of fingers that drew it;
Rhino only shows print widths on screen with PrintDisplay turned on.
Saving a new sketch replaces the previous sketch on that tile.
Every drawn sketch is then exported to out/pdf/ as a PDF of that tile, seen from
the Top view, and the PDF opens.
If no tile exists yet, one is drawn first from out/frame.json.

Run inside Rhino (_-RunPythonScript or ScriptEditor), or let
rhino/watch_tiles.py run it automatically whenever you save a sketch.
"""
import json
import os
import subprocess
import sys
import time

import Rhino
import rhinoscriptsyntax as rs
import System

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE in sys.path:
    sys.path.remove(HERE)
sys.path.insert(0, HERE)
# Rhino keeps modules between runs: drop a draw_tile left by another copy of the repo
_loaded = sys.modules.get("draw_tile")
if _loaded is not None and os.path.dirname(_loaded.__file__) != HERE:
    del sys.modules["draw_tile"]
import draw_tile  # noqa: E402

SKETCH_LAYER = "Azulejos sketch"
GUIDE_LAYER = "Azulejos symmetry guides"
OLD_LAYERS = ["Rajola sketch", "Rajola symmetry guides"]   # from before the rename
GUIDE_COLOR = (150, 160, 205)
MAX_POINTS = 80     # simplify long strokes so curves stay smooth
PRINT_WIDTH_MM = {1: 0.35, 2: 0.7, 3: 1.4}  # by finger count
PDF_PAGE_MM = (210, 297)   # A4 portrait
PDF_DPI = 300
PDF_MARGIN = 0.1           # space around the tile, as a fraction of its side (fits the wet outline)
PDF_LABEL_MM = 30.0        # extra space below the tile for the size label


def latest_tile_box():
    """Bounding box of the most recent (rightmost) tile, or None."""
    ids = draw_tile.tile_ids()
    if not ids:
        return None
    boxes = [rs.BoundingBox(i) for i in ids]
    return max(boxes, key=lambda b: max(p[0] for p in b))


def clear_old_sketch(x0, x1):
    old = []
    layers = [name for name in [SKETCH_LAYER, GUIDE_LAYER] + OLD_LAYERS if rs.IsLayer(name)]
    objects = [obj for name in layers for obj in (rs.ObjectsByLayer(name) or [])]
    for obj in objects:
        box = rs.BoundingBox(obj)
        if box and x0 - 1 <= min(p[0] for p in box) and max(p[0] for p in box) <= x1 + 1:
            old.append(obj)
    if old:
        rs.DeleteObjects(old)


def hex_to_rgb(colour):
    h = colour.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


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


def export_pdf(box, path):
    """Write one page of the Top view, cropped to the tile in this bounding box."""
    doc = Rhino.RhinoDoc.ActiveDoc
    view = doc.Views.Find("Top", False)
    if view is None:
        raise RuntimeError("this model has no viewport named Top")
    size = System.Drawing.Size(int(PDF_PAGE_MM[0] / 25.4 * PDF_DPI), int(PDF_PAGE_MM[1] / 25.4 * PDF_DPI))
    settings = Rhino.Display.ViewCaptureSettings(view, size, PDF_DPI)
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    margin = PDF_MARGIN * (max(xs) - min(xs))
    settings.SetWindowRect(Rhino.Geometry.Point3d(min(xs) - margin, min(ys) - margin - PDF_LABEL_MM, 0),
                           Rhino.Geometry.Point3d(max(xs) + margin, max(ys) + margin, 0))
    settings.SetModelScaleToFit(False)
    settings.DrawBackground = False
    settings.DrawGrid = False
    settings.DrawAxis = False
    settings.UsePrintWidths = True
    # glazes are set as display colours; the default print colour comes from the layer
    settings.OutputColor = Rhino.Display.ViewCaptureSettings.ColorMode.DisplayColor
    pdf = Rhino.FileIO.FilePdf.Create()
    pdf.AddPage(settings)
    pdf.Write(path)
    return path


def export_and_open_pdf(box):
    """PDF of the finished tile. A failure here must not undo a sketch that was drawn."""
    folder = os.path.join(draw_tile.repo_root(), "out", "pdf")
    path = os.path.join(folder, "sketch_{}.pdf".format(time.strftime("%Y%m%d_%H%M%S")))
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
        export_pdf(box, path)
        subprocess.Popen(["open", path])
        Rhino.RhinoApp.WriteLine("Azulejos: PDF exported and opened: " + path)
    except Exception as ex:
        Rhino.RhinoApp.WriteLine("Azulejos: could not export the PDF: {}".format(ex))


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
    draw_tile.ensure_layer(GUIDE_LAYER, GUIDE_COLOR)
    clear_old_sketch(ox, ox + side)

    def to_tile(u, v):
        return (ox + u * side, oy + (1.0 - v) * side, top)

    for start, end in data.get("axes_uv", []):
        line = rs.AddLine(to_tile(*start), to_tile(*end))
        if line:
            rs.ObjectLayer(line, GUIDE_LAYER)

    # the full mirrored pattern if present; older sketches only have strokes_uv
    strokes = data.get("strokes_all_uv") or data.get("strokes_uv", [])
    glazes = data.get("strokes_all_glaze") or []
    palette = data.get("glaze_palette") or {}
    fingers = data.get("strokes_all_fingers") or []   # older sketches draw thin
    count = 0
    for k, stroke in enumerate(strokes):
        pts = simplify([to_tile(u, v) for u, v in stroke])
        if len(pts) < 2:
            continue
        curve = rs.AddInterpCurve(pts) if len(pts) >= 4 else rs.AddPolyline(pts)
        if curve:
            rs.ObjectLayer(curve, SKETCH_LAYER)
            colour = palette.get(glazes[k]) if k < len(glazes) else None
            if colour:
                rs.ObjectColor(curve, hex_to_rgb(colour))
            rs.ObjectPrintWidth(curve, PRINT_WIDTH_MM[fingers[k] if k < len(fingers) else 1])
            count += 1
    if count:
        export_and_open_pdf(box)
    return count


def run():
    path = os.path.join(draw_tile.repo_root(), "out", "sketch.json")
    if not os.path.exists(path):
        print("Azulejos: no out/sketch.json yet - run gesture/air_sketch.py and press s")
        return
    with open(path) as f:
        data = json.load(f)
    n = draw_sketch(data)
    print("Azulejos: drew {} curves on the tile ({} {})".format(
        n, data.get("symmetry", "none"), data.get("mode", "mirror")))


if __name__ == "__main__":
    run()
