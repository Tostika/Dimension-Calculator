"""Measuring: item outline (length, width) and height from the marker card."""
import math

import cv2
import numpy as np

from ..config import BASE_SHEETS
from .markers import BASE_IDS, PLATE_IDS, BaseMap, detect, square_corners_mm, undistort_px


class MeasureError(Exception):
    """`key` is a text key in i18n.py, `params` fills its {placeholders}."""

    def __init__(self, key, **args):
        super().__init__(key)
        self.key = key
        self.params = args


def build_base_map(frame_bgr, settings, calib):
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    found = detect(gray)
    try:
        bm = BaseMap(found, settings.get("base_marker_centers_mm"), settings.get("marker_size_mm"), calib)
    except LookupError:
        raise MeasureError("err_no_markers")
    if bm.layout_error_mm <= layout_limit(settings.get("marker_size_mm")):
        return bm
    # not the saved layout: maybe the other printed sheet (A3 / A4) is on the base
    name = match_sheet(found, calib)
    if name is not None:
        sh = BASE_SHEETS[name]
        bm = BaseMap(found, sh["base_marker_centers_mm"], sh["marker_size_mm"], calib)
        if bm.layout_error_mm <= layout_limit(sh["marker_size_mm"]):
            if hasattr(settings, "use_sheet"):
                settings.use_sheet(name)
            return bm
    raise MeasureError("err_layout")


def layout_limit(marker_size_mm):
    return max(1.5, 0.05 * float(marker_size_mm))


def size_ratio(found, calib, centers_mm, marker_size_mm):
    """Marker size the camera sees, in the units of a layout, divided by the layout's marker size.
    About 1.0 for the sheet that is really on the base; the A3 and A4 sheets give 0.8 / 1.25
    when mixed up (their markers are 30/300 and 20/250 of the spacing). Lens distortion barely
    changes this, so it works before lens calibration too."""
    ids = [i for i in BASE_IDS if i in found]
    if len(ids) < 4:
        return None
    img_c = np.float32([undistort_px(found[i], calib).mean(axis=0) for i in ids])
    obj_c = np.float32([centers_mm[str(i)] for i in ids])
    Hm = cv2.getPerspectiveTransform(img_c, obj_c)
    sides = []
    for i in ids:
        q = cv2.perspectiveTransform(undistort_px(found[i], calib).reshape(-1, 1, 2).astype(np.float32), Hm).reshape(-1, 2)
        sides += [np.linalg.norm(q[k] - q[(k + 1) % 4]) for k in range(4)]
    return float(np.mean(sides)) / float(marker_size_mm)


def match_sheet(found, calib):
    """Name of the printed base sheet the camera sees ("A3" / "A4"), or None."""
    best = None
    for name, sh in BASE_SHEETS.items():
        r = size_ratio(found, calib, sh["base_marker_centers_mm"], sh["marker_size_mm"])
        if r is None:
            return None
        if abs(r - 1.0) < 0.1 and (best is None or abs(r - 1.0) < best[1]):
            best = (name, abs(r - 1.0))
    return best[0] if best else None


def light_only(frame_on, frame_off):
    """LED-on minus LED-off: keeps only the light from our LEDs, so room light and its shadows drop out."""
    diff = cv2.subtract(frame_on, frame_off)
    peak = float(np.percentile(diff, 99.5)) or 1.0
    return cv2.convertScaleAbs(diff, alpha=min(4.0, 230.0 / peak))


def find_item_contour(frame_bgr, base_map):
    """Segments the item against the base sheet. Returns the outer contour in pixels."""
    h, w = frame_bgr.shape[:2]
    region = np.zeros((h, w), np.uint8)
    cv2.fillPoly(region, [base_map.region_px().astype(np.int32)], 255)
    for c in base_map.found.values():            # cut the markers out, with a margin
        cc = c.mean(axis=0)
        grown = (c - cc) * 1.35 + cc
        cv2.fillPoly(region, [grown.astype(np.int32)], 0)

    lab = cv2.cvtColor(cv2.GaussianBlur(frame_bgr, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    base_color = np.median(lab[region > 0], axis=0)
    d = lab - base_color
    d[..., 0] *= 0.5                               # brightness counts less: soft shadows change it most
    dist = np.sqrt((d ** 2).sum(axis=2))
    dist[region == 0] = 0
    dist8 = cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    vals = dist8[region > 0].reshape(-1, 1)
    thr, _ = cv2.threshold(vals, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = np.where((dist8 > max(thr, 25)) & (region > 0), 255, 0).astype(np.uint8)

    k = max(3, int(round(1.0 / base_map.mm_per_px)) | 1)   # about 1 mm
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3 * k, 3 * k)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    min_area_px = 300.0 / (base_map.mm_per_px ** 2)     # ignore anything smaller than 3 cm²
    contours = [c for c in contours if cv2.contourArea(c) > min_area_px]
    if not contours:
        raise MeasureError("err_no_item")
    return max(contours, key=cv2.contourArea).reshape(-1, 2).astype(np.float32)


def correct_for_height(points_mm, base_map, height_mm, fallback_camera_height_mm):
    """The top edge of an item sits closer to the camera, so it looks bigger. Shrink it back."""
    if not height_mm:
        return points_mm
    H = base_map.camera_height_mm or fallback_camera_height_mm
    if base_map.camera_center_mm is not None:
        c = np.array(base_map.camera_center_mm, np.float32)
    else:
        c = points_mm.mean(axis=0)
    k = (H - height_mm) / H
    return c + (points_mm - c) * k


def size_from_outline(points_mm):
    (_, _), (a, b), _ = cv2.minAreaRect(points_mm.astype(np.float32))
    return max(a, b), min(a, b)


def simplify(points_mm, tol_mm=0.3):
    approx = cv2.approxPolyDP(points_mm.reshape(-1, 1, 2).astype(np.float32), tol_mm, True)
    return approx.reshape(-1, 2)


def measure_outline(frame_on, frame_off, base_map, height_mm=None, fallback_camera_height_mm=300.0):
    img = light_only(frame_on, frame_off) if frame_off is not None else frame_on
    contour_px = find_item_contour(img, base_map)
    pts_mm = base_map.to_mm(contour_px)
    pts_mm = correct_for_height(pts_mm, base_map, height_mm, fallback_camera_height_mm)
    length, width = size_from_outline(pts_mm)
    if not (np.isfinite(length) and np.isfinite(width)) or length > 1000:
        raise MeasureError("err_layout")
    return {"contour_px": contour_px, "outline_mm": simplify(pts_mm), "length": float(length), "width": float(width)}


def measure_height(frame_bgr, base_map, settings, fallback_camera_height_mm=300.0, clamp=True):
    """Height of the top of the item, from the marker card lying on it.
    With lens calibration: full 3D pose of the card (also checks tilt).
    Without: from how much bigger the card looks than its real size."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    found = detect(gray)
    ids = [i for i in PLATE_IDS if i in found]
    if len(ids) < 2:
        raise MeasureError("err_no_plate")
    centers = settings.get("plate_marker_centers_mm")
    size = settings.get("plate_marker_size_mm")
    obj = np.vstack([square_corners_mm(centers[str(i)], size) for i in ids])
    img = np.vstack([undistort_px(found[i], base_map.calib) for i in ids])
    thickness = float(settings.get("plate_thickness_mm"))

    if base_map.calib and base_map.R is not None:
        K = np.asarray(base_map.calib["K"], np.float64)
        obj3 = np.hstack([obj, np.zeros((len(obj), 1), np.float32)]).astype(np.float64)
        ok, rvec, tvec = cv2.solvePnP(obj3, img.astype(np.float64), K, None)
        if not ok:
            raise MeasureError("err_no_plate")
        Rp, _ = cv2.Rodrigues(rvec)
        # card centre and normal, moved into base coordinates
        p_cam = tvec.flatten()
        p_base = base_map.R.T @ (p_cam - base_map.t.flatten())
        n_base = base_map.R.T @ Rp[:, 2]
        tilt = math.degrees(math.acos(min(1.0, abs(float(n_base[2])))))
        if tilt > 3.0:
            raise MeasureError("err_tilt", deg=f"{tilt:.1f}")
        top = abs(float(p_base[2]))
    else:
        # card corners mapped onto the base plane look enlarged by k = H / (H - top)
        app = base_map.to_mm(np.vstack([found[i] for i in ids]))
        d_true, d_app = [], []
        for a in range(len(obj)):
            for b in range(a + 1, len(obj)):
                d_true.append(np.linalg.norm(obj[a] - obj[b]))
                d_app.append(np.linalg.norm(app[a] - app[b]))
        k = float(np.median(np.array(d_app) / np.array(d_true)))
        H = base_map.camera_height_mm or fallback_camera_height_mm
        top = H * (1.0 - 1.0 / k)
    h = top - thickness
    return max(0.0, h) if clamp else h
