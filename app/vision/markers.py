"""ArUco markers. Base markers 0-3 sit on the base corners; markers 4-7 are on the height card.
Dictionary: 4x4_50 (print them with tools/make_markers.py)."""
import cv2
import numpy as np

DICT = cv2.aruco.DICT_4X4_50
BASE_IDS = (0, 1, 2, 3)
PLATE_IDS = (4, 5, 6, 7)

_dictionary = cv2.aruco.getPredefinedDictionary(DICT)
_params = cv2.aruco.DetectorParameters()
_params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
_detector = cv2.aruco.ArucoDetector(_dictionary, _params)


def detect(gray):
    """Returns {id: 4x2 float32 corners (TL, TR, BR, BL) in pixels}."""
    corners, ids, _ = _detector.detectMarkers(gray)
    found = {}
    if ids is not None:
        for c, i in zip(corners, ids.flatten()):
            found[int(i)] = c.reshape(4, 2).astype(np.float32)
    return found


def square_corners_mm(center, size):
    """Corners (TL, TR, BR, BL) of a marker of side `size` centred at `center`, y pointing down."""
    cx, cy = center
    h = size / 2.0
    return np.array([[cx - h, cy - h], [cx + h, cy - h], [cx + h, cy + h], [cx - h, cy + h]], np.float32)


def undistort_px(points, calib):
    """Remove lens distortion from pixel points. `calib` = {"K": 3x3, "dist": list} or None."""
    pts = np.asarray(points, np.float32).reshape(-1, 1, 2)
    if not calib:
        return pts.reshape(-1, 2)
    K = np.asarray(calib["K"], np.float64)
    dist = np.asarray(calib["dist"], np.float64)
    return cv2.undistortPoints(pts, K, dist, P=K).reshape(-1, 2)


class BaseMap:
    """Maps camera pixels to millimetres on the base plane, from markers 0-3."""

    def __init__(self, found, centers_mm, marker_size_mm, calib=None):
        missing = [i for i in BASE_IDS if i not in found]
        if missing:
            raise LookupError(missing)
        img_pts, base_pts = [], []
        for i in BASE_IDS:
            img_pts.append(undistort_px(found[i], calib))
            base_pts.append(square_corners_mm(centers_mm[str(i)], marker_size_mm))
        self.img_pts = np.vstack(img_pts).astype(np.float32)
        self.base_pts = np.vstack(base_pts).astype(np.float32)
        self.H, _ = cv2.findHomography(self.img_pts, self.base_pts, 0)
        self.H_inv = np.linalg.inv(self.H)
        # how well the saved marker layout fits what the camera sees (mm). Large = the markers are
        # not where the settings say (e.g. a different sheet), and every measurement would be wrong.
        mapped = cv2.perspectiveTransform(self.img_pts.reshape(-1, 1, 2), self.H).reshape(-1, 2)
        self.layout_error_mm = float(np.mean(np.linalg.norm(mapped - self.base_pts, axis=1)))
        self.calib = calib
        self.found = found
        sides = []
        for i in BASE_IDS:
            c = found[i]
            sides += [np.linalg.norm(c[k] - c[(k + 1) % 4]) for k in range(4)]
        self.mm_per_px = marker_size_mm / float(np.mean(sides))
        self.camera_center_mm = None   # point on the base right under the camera
        self.camera_height_mm = None   # lens height above the base
        self.R = self.t = None
        if calib:
            self._solve_pose()

    def _solve_pose(self):
        K = np.asarray(self.calib["K"], np.float64)
        obj = np.hstack([self.base_pts, np.zeros((len(self.base_pts), 1), np.float32)]).astype(np.float64)
        ok, rvec, tvec = cv2.solvePnP(obj, self.img_pts.astype(np.float64), K, None, flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            return
        R, _ = cv2.Rodrigues(rvec)
        C = (-R.T @ tvec).flatten()           # camera centre in base coordinates (z is negative: above)
        self.R, self.t = R, tvec
        self.camera_center_mm = (float(C[0]), float(C[1]))
        self.camera_height_mm = float(abs(C[2]))

    def to_mm(self, px_points):
        pts = undistort_px(px_points, self.calib).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, self.H).reshape(-1, 2)

    def to_px(self, mm_points):
        """Base mm to (undistorted) pixels, for drawing overlays."""
        pts = np.asarray(mm_points, np.float32).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, self.H_inv).reshape(-1, 2)

    def region_px(self):
        """Polygon (pixels) of the area between the four markers, for searching the item."""
        centers = np.array([self.found[i].mean(axis=0) for i in BASE_IDS], np.float32)
        hull = cv2.convexHull(centers)
        return hull.reshape(-1, 2)


def learn_layout(detections, marker_size_mm, calib=None):
    """Works out where markers 1-3 are relative to marker 0, from what the camera sees.
    `detections` is a list of detect() results (several frames, all 4 markers visible).
    Marker 0's own square (known size) defines millimetres and directions on the base plane;
    the other centres are mapped into it and averaged over the frames.
    Returns ({"0": [0, 0], "1": [x, y], ...}, spread_mm)."""
    ref = square_corners_mm((0.0, 0.0), marker_size_mm)
    per_id = {i: [] for i in BASE_IDS}
    for found in detections:
        if any(i not in found for i in BASE_IDS):
            continue
        H, _ = cv2.findHomography(undistort_px(found[0], calib), ref, 0)
        for i in BASE_IDS:
            c = undistort_px(found[i], calib).reshape(-1, 1, 2)
            per_id[i].append(cv2.perspectiveTransform(c, H).reshape(-1, 2).mean(axis=0))
    if not per_id[0]:
        raise LookupError("markers")
    centers, spread = {}, 0.0
    for i in BASE_IDS:
        arr = np.array(per_id[i])
        med = np.median(arr, axis=0)
        centers[i] = med
        spread = max(spread, float(np.max(np.linalg.norm(arr - med, axis=1))))
    return {str(i): [round(float(centers[i][0]), 2), round(float(centers[i][1]), 2)] for i in BASE_IDS}, spread
