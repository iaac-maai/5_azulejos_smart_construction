"""Tile symmetry for Azulejos: '+' quadrants, 'X' triangles, '*' both (8-fold).

All coordinates are tile coordinates (u, v) from 0 to 1, with (0, 0) at the
tile's top-left and v pointing down, as saved in out/sketch.json.

  '+'  mirror across the vertical and horizontal centre lines (4 quadrants)
  'X'  mirror across the two diagonals (4 triangles)
  '*'  both: 8 mirrored sections, like a classic azulejo rosette
  rotate=True  each section gets a turned copy instead of a mirrored one
               ('+' and 'X' -> 4 turns of 90 degrees, '*' -> 8 turns of 45)

Choosing the symmetry by gesture: the artisan draws two straight strokes over
the tile. Horizontal + vertical = '+', two diagonals = 'X', all four = '*'.
"""
import math

import numpy as np

NAMES = {
    "none": "no symmetry",
    "+": "+ quadrants",
    "X": "X triangles",
    "*": "* 8-fold",
}

MIN_STROKE = 0.3      # a choice stroke must span at least 30% of the tile side
STRAIGHTNESS = 0.2    # max sideways wobble / length; bigger = too curvy to count


def matrices(sym, rotate=False):
    """2x2 matrices that map one section onto every section (centred coords)."""
    if sym in (None, "none"):
        return [np.eye(2)]
    if rotate:
        n = 8 if sym == "*" else 4
        return [np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
                for a in (2 * math.pi * k / n for k in range(n))]
    flip_x = np.diag([-1.0, 1.0])
    flip_y = np.diag([1.0, -1.0])
    swap = np.array([[0.0, 1.0], [1.0, 0.0]])          # mirror across u = v
    anti = np.array([[0.0, -1.0], [-1.0, 0.0]])        # mirror across u = 1 - v
    half = -np.eye(2)                                  # 180 degree turn
    if sym == "+":
        return [np.eye(2), flip_x, flip_y, half]
    if sym == "X":
        return [np.eye(2), swap, anti, half]
    if sym == "*":
        quad = [np.eye(2), flip_x, flip_y, half]
        return quad + [swap @ m for m in quad]
    raise ValueError(f"unknown symmetry {sym!r}")


def split_inside(points, eps=1e-6):
    """Cut a stroke into the pieces that lie inside the tile."""
    pieces, current = [], []
    for p in points:
        if -eps <= p[0] <= 1 + eps and -eps <= p[1] <= 1 + eps:
            current.append([float(p[0]), float(p[1])])
        else:
            if len(current) > 1:
                pieces.append(current)
            current = []
    if len(current) > 1:
        pieces.append(current)
    return pieces


def expand_with_sources(strokes, sym, rotate=False):
    """Every stroke copied into every section, plus which original each copy came from."""
    out, sources = [], []
    mats = matrices(sym, rotate)
    for index, stroke in enumerate(strokes):
        if len(stroke) < 2:
            continue
        centred = np.asarray(stroke, dtype=float) - 0.5
        for m in mats:
            pieces = split_inside(centred @ m.T + 0.5)
            out.extend(pieces)
            sources.extend([index] * len(pieces))
    return out, sources


def expand(strokes, sym, rotate=False):
    """Every stroke copied into every section of the tile."""
    return expand_with_sources(strokes, sym, rotate)[0]


def transform_strokes(strokes, scale=1.0, degrees=0.0):
    """Scale and turn strokes about the tile centre (pieces outside are trimmed later)."""
    a = np.radians(degrees)
    m = scale * np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    return [((np.asarray(s, dtype=float) - 0.5) @ m.T + 0.5).tolist() for s in strokes]


def distance_to_line(p, line):
    """Shortest distance from point p to a polyline."""
    a, b = line[:-1], line[1:]
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0, 1)
    closest = a + ab * t[:, None]
    return float(np.min(np.linalg.norm(closest - p, axis=1)))


def nearest_stroke(point, strokes, sym, rotate=False, max_distance=0.08):
    """Index of the original stroke whose line (or any copy) passes nearest the point."""
    copies, sources = expand_with_sources(strokes, sym, rotate)
    best, best_d = None, max_distance
    p = np.asarray(point, dtype=float)
    for copy, source in zip(copies, sources):
        d = distance_to_line(p, np.asarray(copy))
        if d < best_d:
            best, best_d = source, d
    return best


def axes(sym):
    """Mirror lines to show on the tile, as (start, end) pairs."""
    lines = []
    if sym in ("+", "*"):
        lines += [[[0.5, 0.0], [0.5, 1.0]], [[0.0, 0.5], [1.0, 0.5]]]
    if sym in ("X", "*"):
        lines += [[[0.0, 0.0], [1.0, 1.0]], [[1.0, 0.0], [0.0, 1.0]]]
    return lines


def stroke_direction(points):
    """'-', '|', '/', '\\' for a long straight stroke, else None."""
    pts = np.asarray(points, dtype=float)
    if len(pts) < 3:
        return None
    centred = pts - pts.mean(axis=0)
    _, s, vt = np.linalg.svd(centred, full_matrices=False)
    main = vt[0]
    along = centred @ main
    length = along.max() - along.min()
    spread = np.abs(centred @ vt[1]).max() if len(s) > 1 else 0.0
    if length < MIN_STROKE or spread / length > STRAIGHTNESS:
        return None
    # v points down in tile coordinates, so flip it to get the angle people see
    angle = math.degrees(math.atan2(-main[1], main[0])) % 180
    if angle < 22.5 or angle >= 157.5:
        return "-"
    if angle < 67.5:
        return "/"
    if angle < 112.5:
        return "|"
    return "\\"


def classify(strokes):
    """'+', 'X', '*' or None from the choice strokes drawn so far."""
    dirs = {stroke_direction(s) for s in strokes}
    plus = {"-", "|"} <= dirs
    cross = {"/", "\\"} <= dirs
    if plus and cross:
        return "*"
    if plus:
        return "+"
    if cross:
        return "X"
    return None
