"""Lens calibration with a printed checkerboard, saved per camera height."""
import json
import os

import cv2
import numpy as np

BOARD_INNER = (9, 6)      # inner corners (print tools/make_markers.py -> checkerboard.png)
SQUARE_MM = 25.0
FRAMES_NEEDED = 15


def find_board(gray):
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE + cv2.CALIB_CB_FAST_CHECK
    scale = 1.0
    small = gray
    if gray.shape[1] > 1600:                     # search on a smaller copy, refine on the full image
        scale = 1600.0 / gray.shape[1]
        small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, corners = cv2.findChessboardCorners(small, BOARD_INNER, flags)
    if not ok:
        return None
    corners = corners / scale
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.001)
    return cv2.cornerSubPix(gray, corners.astype(np.float32), (11, 11), (-1, -1), crit)


def board_points():
    objp = np.zeros((BOARD_INNER[0] * BOARD_INNER[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:BOARD_INNER[0], 0:BOARD_INNER[1]].T.reshape(-1, 2) * SQUARE_MM
    return objp


class CalibrationSession:
    def __init__(self):
        self.img_points = []
        self.size = None

    def add(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        corners = find_board(gray)
        if corners is None:
            return False
        self.size = (gray.shape[1], gray.shape[0])
        self.img_points.append(corners)
        return True

    @property
    def count(self):
        return len(self.img_points)

    def solve(self):
        objp = board_points()
        rms, K, dist, _, _ = cv2.calibrateCamera([objp] * self.count, self.img_points, self.size, None, None)
        return {"K": K.tolist(), "dist": dist.flatten().tolist(), "rms": float(rms), "size": list(self.size)}


class CalibrationStore:
    """calibration.json: {"300": {"K":..., "dist":..., "rms":..., "size":[w,h]}, ...} keyed by camera height in mm."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def get(self, z_mm, frame_size=None):
        c = self.data.get(str(int(z_mm)))
        if c and frame_size and list(frame_size) != list(c.get("size", [])):
            return None                          # calibrated at another resolution: not valid
        return c

    def put(self, z_mm, calib):
        self.data[str(int(z_mm))] = calib
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)
