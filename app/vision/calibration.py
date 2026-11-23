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
    """Collects checkerboard views and works out how the lens bends the picture.

    With the camera fixed above the base, the board can only lie (almost) flat. Flat views
    show the BENDING well but cannot tell how strongly the lens zooms; a free calculation then
    guesses the zoom wildly wrong. So the zoom (focal length) is worked out first from the base
    markers and the camera height (focal_from_base) and kept fixed; only the bending is fitted.
    Like the team's calibrate_lens.py: views are added by themselves when the board is in a new
    place, the corners of the picture must be covered, and bad views are dropped."""

    GRID = 3                                     # coverage is checked in a 3 x 3 grid

    def __init__(self, focal_px=None):
        self.img_points = []
        self.size = None
        self.focal_px = focal_px

    def add(self, frame_bgr, only_new=False):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        corners = find_board(gray)
        if corners is None:
            return False
        self.size = (gray.shape[1], gray.shape[0])
        if only_new and not self.is_new_view(corners):
            return False
        self.img_points.append(corners)
        return True

    def is_new_view(self, c):
        """New if the board centre moved more than 8 % of the picture or it was turned."""
        p = c.reshape(-1, 2)
        cen = p.mean(0)
        d = p[BOARD_INNER[0] - 1] - p[0]
        ang = np.degrees(np.arctan2(d[1], d[0]))
        for v in self.img_points:
            q = v.reshape(-1, 2)
            dv = q[BOARD_INNER[0] - 1] - q[0]
            av = np.degrees(np.arctan2(dv[1], dv[0]))
            turn = abs((ang - av + 180) % 360 - 180)
            if np.linalg.norm(cen - q.mean(0)) < 0.08 * max(self.size) and turn < 10:
                return False
        return True

    @property
    def count(self):
        return len(self.img_points)

    def missing_corners(self):
        """Corners of the picture no board has covered yet: subset of ["tl", "tr", "bl", "br"]."""
        if not self.size:
            return ["tl", "tr", "bl", "br"]
        w, h = self.size
        s = 16
        m = np.zeros((h // s + 1, w // s + 1), np.uint8)
        for c in self.img_points:
            hull = cv2.convexHull((c.reshape(-1, 2) / s).astype(np.int32))
            cv2.fillConvexPoly(m, hull, 1)
        gh, gw = m.shape[0] // self.GRID, m.shape[1] // self.GRID
        cells = {"tl": m[:gh, :gw], "tr": m[:gh, -gw:], "bl": m[-gh:, :gw], "br": m[-gh:, -gw:]}
        return [k for k, cell in cells.items() if cell.mean() < 0.25]

    def _solve(self, views):
        objp = board_points()
        w, h = self.size
        if self.focal_px:
            K0 = np.array([[self.focal_px, 0, w / 2.0], [0, self.focal_px, h / 2.0], [0, 0, 1]], np.float64)
            flags = (cv2.CALIB_USE_INTRINSIC_GUESS | cv2.CALIB_FIX_FOCAL_LENGTH | cv2.CALIB_FIX_PRINCIPAL_POINT
                     | cv2.CALIB_FIX_ASPECT_RATIO | cv2.CALIB_FIX_K3 | cv2.CALIB_ZERO_TANGENT_DIST)
        else:
            K0, flags = None, cv2.CALIB_FIX_K3
        rms, K, dist, rv, tv = cv2.calibrateCamera([objp] * len(views), views, self.size, K0, None, flags=flags)
        errs = []
        for v, r, t in zip(views, rv, tv):
            p, _ = cv2.projectPoints(objp, r, t, K, dist)
            errs.append(float(np.sqrt(np.mean(np.sum((p.reshape(-1, 2) - v.reshape(-1, 2)) ** 2, axis=1)))))
        return rms, K, dist, np.array(errs)

    def solve(self):
        views = list(self.img_points)
        rms, K, dist, errs = self._solve(views)
        keep = errs < max(3 * float(np.median(errs)), 0.5)          # blurry / moved views
        if keep.sum() >= 8 and not keep.all():
            views = [v for v, k in zip(views, keep) if k]
            rms, K, dist, errs = self._solve(views)
        return {"K": K.tolist(), "dist": dist.flatten().tolist(), "rms": float(rms), "size": list(self.size),
                "views": len(views), "fixed_focal": bool(self.focal_px)}


def focal_from_base(base_map, size, camera_height_mm):
    """The lens zoom in pixels, from how many pixels a millimetre of the base takes in the
    middle of the picture and the camera height: f = H / (mm per pixel)."""
    cx, cy = size[0] / 2.0, size[1] / 2.0
    p = base_map.to_mm(np.array([[cx, cy], [cx + 100, cy], [cx, cy + 100]], np.float32))
    mm_per_px = (np.linalg.norm(p[1] - p[0]) + np.linalg.norm(p[2] - p[0])) / 200.0
    return float(camera_height_mm / mm_per_px)


class CalibrationStore:
    """calibration.json: {"lens": {"K":..., "dist":..., "rms":..., "size":[w,h], "focus":...}}.
    One lens calibration is enough for the whole 30-40 cm range (focus is locked)."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def lens(self, frame_size=None):
        c = self.data.get("lens")
        if c and frame_size and list(frame_size) != list(c.get("size", [])):
            return None                          # calibrated at another resolution: not valid
        return c

    def set_lens(self, calib):
        self.data["lens"] = calib
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)


def scaled(calib, factor):
    """The same lens calibration for a resized image (e.g. the small preview)."""
    if not calib:
        return None
    K = np.asarray(calib["K"], np.float64).copy()
    K[0, :] *= factor
    K[1, :] *= factor
    return {"K": K.tolist(), "dist": calib["dist"]}
