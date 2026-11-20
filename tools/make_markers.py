"""Makes the printable sheets at true size (300 DPI). Print them at 100 % scale, "actual size",
never "fit to page", then check one marker with a ruler.

  python tools/make_markers.py            -> files in ./print
    base_markers_A4.png  the four base markers: cut on the frame (keep the white border)
                         and glue them on the matte base sheet
    height_card_A4.png   the 100 x 70 mm height card (markers 4-7)
    checkerboard_A4.png  9 x 6 inner corners, 25 mm squares, for lens calibration
"""
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import DEFAULTS  # noqa: E402
from app.vision.calibration import BOARD_INNER, SQUARE_MM  # noqa: E402

DPI = 300
PX_PER_MM = DPI / 25.4
D = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def mm(v):
    return int(round(v * PX_PER_MM))


def sheet(w_mm, h_mm):
    return np.full((mm(h_mm), mm(w_mm)), 255, np.uint8)


def put_marker(img, mid, center_mm, size_mm, label=True):
    s = mm(size_mm)
    m = cv2.aruco.generateImageMarker(D, mid, s)
    x0, y0 = mm(center_mm[0]) - s // 2, mm(center_mm[1]) - s // 2
    img[y0:y0 + s, x0:x0 + s] = m
    if label:
        cv2.putText(img, f"ID {mid}", (x0, y0 + s + mm(5)), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2, cv2.LINE_AA)


def save(img, path):
    Image.fromarray(img).save(path, dpi=(DPI, DPI))
    print("wrote", path)


def main(out="print"):
    os.makedirs(out, exist_ok=True)
    size = DEFAULTS["marker_size_mm"]
    centers = DEFAULTS["base_marker_centers_mm"]

    a4 = sheet(210, 297)
    for n, i in enumerate(sorted(centers, key=int)):
        c = (55 + (n % 2) * 100, 60 + (n // 2) * 110)
        put_marker(a4, int(i), c, size)
        e = size / 2 + 8                     # 8 mm white border: the camera needs it to see the marker
        cv2.rectangle(a4, (mm(c[0] - e), mm(c[1] - e)), (mm(c[0] + e), mm(c[1] + e)), 160, 1)
    xs = sorted({c[0] for c in centers.values()})
    ys = sorted({c[1] for c in centers.values()})
    note = "Glue so that centre-to-centre is %.0f mm across and %.0f mm down." % (xs[-1] - xs[0], ys[-1] - ys[0])
    cv2.putText(a4, note, (mm(10), mm(280)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2, cv2.LINE_AA)
    save(a4, os.path.join(out, "base_markers_A4.png"))

    card = sheet(210, 297)
    cx, cy = 105.0, 100.0
    cv2.rectangle(card, (mm(cx - 50), mm(cy - 35)), (mm(cx + 50), mm(cy + 35)), 0, 2)   # cut line
    ps = DEFAULTS["plate_marker_size_mm"]
    for i, c in DEFAULTS["plate_marker_centers_mm"].items():
        put_marker(card, int(i), (cx + c[0], cy + c[1]), ps, label=False)
    cv2.putText(card, "Height card 100 x 70 mm. Cut on the line, glue on a flat 3D-printed plate.",
                (mm(10), mm(160)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2, cv2.LINE_AA)
    save(card, os.path.join(out, "height_card_A4.png"))

    cols, rows = BOARD_INNER[0] + 1, BOARD_INNER[1] + 1
    board = sheet(297, 210)
    x0 = (297 - cols * SQUARE_MM) / 2
    y0 = (210 - rows * SQUARE_MM) / 2
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                cv2.rectangle(board, (mm(x0 + c * SQUARE_MM), mm(y0 + r * SQUARE_MM)),
                              (mm(x0 + (c + 1) * SQUARE_MM) - 1, mm(y0 + (r + 1) * SQUARE_MM) - 1), 0, -1)
    save(board, os.path.join(out, "checkerboard_A4.png"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "print")
