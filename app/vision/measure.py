"""Measuring: item outline (length, width) and height from the marker card."""
import math

import cv2
import numpy as np

from ..config import BASE_SHEETS
from . import outline
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
    err_mm = bm.layout_error_mm
    # not the saved layout: maybe the other printed sheet (A3 / A4) is on the base
    name = match_sheet(found, calib)
    if name is not None:
        sh = settings.sheet_values(name) if hasattr(settings, "sheet_values") else BASE_SHEETS[name]
        other = BaseMap(found, sh["base_marker_centers_mm"], sh["marker_size_mm"], calib)
        if other.layout_error_mm <= layout_limit(sh["marker_size_mm"]):
            if hasattr(settings, "use_sheet"):
                settings.use_sheet(name)
            return other
    raise layout_problem(found, settings, calib, err_mm)


def layout_problem(found, settings, calib, err_mm):
    """Why the markers don't fit: a lens calibration that is poor near the edges of the picture
    (it makes the fit worse than no correction at all), or markers that really are elsewhere."""
    if calib:
        try:
            raw = BaseMap(found, settings.get("base_marker_centers_mm"), settings.get("marker_size_mm"), None)
            if raw.layout_error_mm < err_mm:
                return MeasureError("err_lens_edges", mm=f"{err_mm:.1f}")
        except LookupError:
            pass
    return MeasureError("err_layout_mm", mm=f"{err_mm:.1f}")


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


def simplify(points_mm, tol_mm=0.3):
    approx = cv2.approxPolyDP(points_mm.reshape(-1, 1, 2).astype(np.float32), tol_mm, True)
    return approx.reshape(-1, 2)


def measure_outline(frame_on, frame_off, base_map, height_mm=None, fallback_camera_height_mm=300.0):
    """Length, width and outline of the item, with the edge finder of the team's measure.py
    (straight top view, paper model, sub-pixel edge snapping)."""
    img = light_only(frame_on, frame_off) if frame_off is not None else frame_on
    corners = base_map.base_pts.reshape(-1, 4, 2)
    centers = {str(i): corners[k].mean(axis=0).tolist() for k, i in enumerate(BASE_IDS)}
    size = float(np.mean(np.linalg.norm(corners[:, 1] - corners[:, 0], axis=1)))
    top, (x0, y0), usable = outline.top_view(img, base_map, centers, size)
    try:
        out_px, _, _ = outline.find_item(top, usable)
    except outline.NoItem:
        raise MeasureError("err_no_item")
    pts_mm = out_px / outline.PX_PER_MM + np.array([x0, y0], np.float32)
    pts_mm = correct_for_height(pts_mm, base_map, height_mm, fallback_camera_height_mm)
    (_, _), (a, b), _ = outline.orient_rect(pts_mm)
    length, width = max(a, b), min(a, b)
    if not (np.isfinite(length) and np.isfinite(width)) or length > 1000:
        raise MeasureError("err_layout")
    contour_px = outline.mm_to_camera_px(out_px / outline.PX_PER_MM + np.array([x0, y0]), base_map)
    return {"contour_px": contour_px.astype(np.float32), "outline_mm": simplify(pts_mm),
            "length": float(length), "width": float(width)}


def _plate(frame_bgr, settings):
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    found = detect(gray)
    ids = [i for i in PLATE_IDS if i in found]
    if len(ids) < 2:
        raise MeasureError("err_no_plate")
    centers = settings.get("plate_marker_centers_mm")
    size = settings.get("plate_marker_size_mm")
    obj = np.vstack([square_corners_mm(centers[str(i)], size) for i in ids])
    return found, ids, obj


def plate_scale(frame_bgr, base_map, settings):
    """How much bigger the card looks on the base plane than its real size (k = H / (H - top))."""
    found, ids, obj = _plate(frame_bgr, settings)
    app = base_map.to_mm(np.vstack([found[i] for i in ids]))
    d_true, d_app = [], []
    for a in range(len(obj)):
        for b in range(a + 1, len(obj)):
            d_true.append(np.linalg.norm(obj[a] - obj[b]))
            d_app.append(np.linalg.norm(app[a] - app[b]))
    return float(np.median(np.array(d_app) / np.array(d_true)))


def zero_scale(frame_bgr, base_map, settings, fallback_camera_height_mm=300.0):
    """With the card lying on the empty base: the extra enlargement that is not height
    (lens correction near the middle, the card or the sheet printed off size). 1.0 = none.
    Saved as plate_zero_scale and used for heights only: it cannot tell a card printed small
    from a base printed big, so it must not touch the outline size."""
    k = plate_scale(frame_bgr, base_map, settings)
    H = base_map.camera_height_mm or fallback_camera_height_mm
    t = float(settings.get("plate_thickness_mm"))
    return k * (H - t) / H


def measure_height(frame_bgr, base_map, settings, fallback_camera_height_mm=300.0, clamp=True):
    """Height of the top of the item, from the marker card lying on it.
    After the zero check: from how much bigger the card looks than on the empty base (this
    cancels lens and printing errors). Before it: from the card's 3D pose with lens calibration,
    or from its size without. The pose is always used to check that the card lies flat."""
    found, ids, obj = _plate(frame_bgr, settings)
    img = np.vstack([undistort_px(found[i], base_map.calib) for i in ids])
    thickness = float(settings.get("plate_thickness_mm"))
    H = base_map.camera_height_mm or fallback_camera_height_mm
    top = None

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
        top = -float(p_base[2])                 # camera side is negative z: above the base = positive

    c = settings.get("plate_zero_scale")
    if c or top is None:
        # card corners mapped onto the base plane look enlarged by k = c * H / (H - top)
        k = plate_scale(frame_bgr, base_map, settings)
        top = H * (1.0 - float(c or 1.0) / k)
    h = top - thickness
    return max(0.0, h) if clamp else h

