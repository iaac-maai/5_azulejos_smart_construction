"""Create a printable ArUco marker (ID 0, DICT_4X4_50) for real-world scale.

Print out/marker_50mm.png at 100% scale, measure it, and set MARKER_MM in
frame_square.py to the printed size (default 50 mm).
"""
from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "out" / "marker_50mm.png"
DPI = 300
SIDE_MM = 50

side_px = round(SIDE_MM / 25.4 * DPI)
marker = cv2.aruco.generateImageMarker(
    cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), 0, side_px)
margin = side_px // 5
page = np.full((side_px + 2 * margin, side_px + 2 * margin), 255, np.uint8)
page[margin:margin + side_px, margin:margin + side_px] = marker
OUT.parent.mkdir(exist_ok=True)
cv2.imwrite(str(OUT), page)
print(f"Saved {OUT} ({SIDE_MM} mm at {DPI} dpi)")
