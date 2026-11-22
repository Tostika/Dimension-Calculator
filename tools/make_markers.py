"""Makes the print sheets as PDFs at exact physical size. The app's defaults (app/config.py)
describe exactly these sheets, so nothing has to be measured or learned after printing.

Print every PDF at 100 % / "Actual size" (never "Fit to page"), then check the 100 mm line
on each sheet with a ruler.

  python tools/make_markers.py            -> files in ./print
    base_A4.pdf          the base: markers 0-3, 20 mm, centres 250 x 140 mm apart (A4 landscape, 30 cm+)
    base_A3.pdf          the bigger base: markers 0-3, 30 mm, centres 300 x 190 mm apart (A3 landscape, about 33 cm+)
    height_card_A4.pdf   the 100 x 70 mm height card, markers 4-7, 26 mm (cut out, glue on a flat plate)
    checkerboard_A4.pdf  9 x 6 inner corners, 25 mm squares, for lens calibration
"""
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import BASE_SHEETS, DEFAULTS  # noqa: E402
from app.vision.calibration import BOARD_INNER, SQUARE_MM  # noqa: E402

DPI = 300
PX_PER_MM = DPI / 25.4
D = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
FONT = cv2.FONT_HERSHEY_SIMPLEX


def mm(v):
    return int(round(v * PX_PER_MM))


def sheet(w_mm, h_mm):
    return np.full((mm(h_mm), mm(w_mm)), 255, np.uint8)


def put_marker(img, mid, center_mm, size_mm):
    s = mm(size_mm)
    m = cv2.aruco.generateImageMarker(D, mid, s)
    x0, y0 = mm(center_mm[0]) - s // 2, mm(center_mm[1]) - s // 2
    img[y0:y0 + s, x0:x0 + s] = m


def text(img, s, x_mm, y_mm, scale=1.1, thick=2, color=0):
    cv2.putText(img, s, (mm(x_mm), mm(y_mm)), FONT, scale, color, thick, cv2.LINE_AA)


def ruler(img, x_mm, y_mm):
    """A 100 mm line with ticks every 10 mm: measure it after printing."""
    cv2.line(img, (mm(x_mm), mm(y_mm)), (mm(x_mm + 100), mm(y_mm)), 0, 3)
    for k in range(11):
        h = 4 if k % 5 == 0 else 2.5
        cv2.line(img, (mm(x_mm + 10 * k), mm(y_mm - h)), (mm(x_mm + 10 * k), mm(y_mm)), 0, 3)
    text(img, "must measure exactly 100 mm", x_mm + 104, y_mm, 0.9, 2)


def save_pdf(img, path):
    Image.fromarray(img).convert("L").save(path, "PDF", resolution=DPI)
    print("wrote", path)


def base_sheet(out, name):
    """A4: the camera (C960 4K at its widest, 66 deg) sees about 34 x 19 cm at 30 cm, so these
    markers (27 x 16 cm outside to outside) fit from 30 cm up. A3: bigger area, needs about 33 cm+."""
    size = BASE_SHEETS[name]["marker_size_mm"]
    centers = BASE_SHEETS[name]["base_marker_centers_mm"]
    xs = [c[0] for c in centers.values()]
    ys = [c[1] for c in centers.values()]
    W, H = (297.0, 210.0) if name == "A4" else (420.0, 297.0)
    ox = (W - (max(xs) - min(xs))) / 2 - min(xs)        # layout centred on the page
    oy = (H - (max(ys) - min(ys))) / 2 - min(ys)
    img = sheet(W, H)
    for i, c in centers.items():
        cx, cy = c[0] + ox, c[1] + oy
        put_marker(img, int(i), (cx, cy), size)
        # ID label just above the top markers and just below the bottom ones
        ly = cy - size / 2 - 2.5 if c[1] == min(ys) else cy + size / 2 + 5.5
        text(img, f"ID {i}", cx - 4.5, ly, 0.8, 2, 90)
    text(img, "Base. Put the item between the four markers. Keep all four markers uncovered.", 40, 9, 0.85, 2, 60)
    text(img, "Markers %.0f mm, centres %.0f x %.0f mm apart (the app's default layout). Print at 100 %%."
         % (size, max(xs) - min(xs), max(ys) - min(ys)), 40, 15, 0.85, 2, 60)
    ruler(img, 98, H - 8)
    save_pdf(img, os.path.join(out, f"base_{name}.pdf"))


def card_a4(out):
    img = sheet(210, 297)
    cx, cy = 105.0, 90.0
    cv2.rectangle(img, (mm(cx - 50), mm(cy - 35)), (mm(cx + 50), mm(cy + 35)), 150, 2)   # cut line (grey)
    ps = DEFAULTS["plate_marker_size_mm"]
    for i, c in DEFAULTS["plate_marker_centers_mm"].items():
        put_marker(img, int(i), (cx + c[0], cy + c[1]), ps)
    text(img, "Height card, 100 x 70 mm, markers %.0f mm (IDs 4-7)." % ps, 12, 20, 1.0, 2)
    text(img, "Cut on the grey line. Glue it flat on a rigid plate (e.g. 3D printed, 2 mm).", 12, 140, 0.95, 2)
    text(img, "Enter the total thickness (paper + plate) in the app: Calibration > Height card.", 12, 148, 0.95, 2)
    ruler(img, 12, 170)
    save_pdf(img, os.path.join(out, "height_card_A4.pdf"))


def checkerboard_a4(out):
    cols, rows = BOARD_INNER[0] + 1, BOARD_INNER[1] + 1
    img = sheet(297, 210)
    x0 = (297 - cols * SQUARE_MM) / 2
    y0 = 14.0
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                cv2.rectangle(img, (mm(x0 + c * SQUARE_MM), mm(y0 + r * SQUARE_MM)),
                              (mm(x0 + (c + 1) * SQUARE_MM) - 1, mm(y0 + (r + 1) * SQUARE_MM) - 1), 0, -1)
    text(img, "Lens calibration board: %d x %d inner corners, squares %.0f mm. Keep it flat (glue on cardboard)."
         % (BOARD_INNER[0], BOARD_INNER[1], SQUARE_MM), 12, y0 + rows * SQUARE_MM + 9, 0.9, 2)
    ruler(img, 12, 202)
    save_pdf(img, os.path.join(out, "checkerboard_A4.pdf"))


def main(out="print"):
    os.makedirs(out, exist_ok=True)
    for old in ("base_markers_A4.png", "height_card_A4.png", "checkerboard_A4.png"):
        p = os.path.join(out, old)
        if os.path.exists(p):
            os.remove(p)
    base_sheet(out, "A4")
    base_sheet(out, "A3")
    card_a4(out)
    checkerboard_a4(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "print")
