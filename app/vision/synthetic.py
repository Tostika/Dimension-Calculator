"""Synthetic scene renderer: the base, its markers, an item and the height card, seen through a
virtual pinhole camera with real perspective. Used only by the tests, never shown in the app."""
import cv2
import numpy as np

from ..config import DEFAULTS

_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


class Scene:
    def __init__(self, width=3840, height=2160, fx=None, tex_px_per_mm=8, settings=None):
        self.W, self.H = width, height
        fx = fx or 3392.0 * width / 3840.0          # C960 4K at its widest view (66 deg diagonal)
        self.K = np.array([[fx, 0, width / 2], [0, fx, height / 2], [0, 0, 1]], np.float64)
        self.TEX = tex_px_per_mm
        self.get = (settings.get if settings is not None else DEFAULTS.get)

    def _P(self, cam_xy, cam_h):
        R = np.eye(3)
        t = -R @ np.array([cam_xy[0], cam_xy[1], -cam_h])
        return self.K @ np.hstack([R, t.reshape(3, 1)])

    def _hom(self, M, z, origin):
        A = np.array([[1 / self.TEX, 0, origin[0]], [0, 1 / self.TEX, origin[1]], [0, 0, 1]], np.float64)
        P = M[:, [0, 1, 3]] + np.outer(M[:, 2], [0, 0, z])
        return P @ A

    def _paste(self, frame, tex, Hm):
        warped = cv2.warpPerspective(tex, Hm, (self.W, self.H), flags=cv2.INTER_LINEAR)
        mask = cv2.warpPerspective(np.full(tex.shape[:2], 255, np.uint8), Hm, (self.W, self.H), flags=cv2.INTER_NEAREST)
        frame[mask > 0] = warped[mask > 0]

    def render(self, item_h=7.8, item=(147.6, 71.5), item_center=None, with_item=True, with_plate=False,
               cam_xy=None, cam_h=300.0, light=1.0, noise_seed=1):
        T = self.TEX
        cs = list(self.get("base_marker_centers_mm").values())
        mid = (sum(c[0] for c in cs) / len(cs), sum(c[1] for c in cs) / len(cs))
        cam_xy = cam_xy or mid
        item_center = item_center or mid
        M = self._P(cam_xy, cam_h)
        frame = np.full((self.H, self.W, 3), 40, np.uint8)
        base = np.zeros((280 * T, 380 * T, 3), np.uint8)
        base[:] = (80, 140, 60)                                   # matte green sheet
        self._paste(frame, base, self._hom(M, 0, (-40, -40)))
        ms = self.get("marker_size_mm")
        for i, c in self.get("base_marker_centers_mm").items():
            s = int(ms * T)
            q = int(s * 0.27)
            img = cv2.copyMakeBorder(cv2.aruco.generateImageMarker(_DICT, int(i), s), q, q, q, q,
                                     cv2.BORDER_CONSTANT, value=255)
            self._paste(frame, cv2.cvtColor(img, cv2.COLOR_GRAY2BGR),
                        self._hom(M, 0, (c[0] - ms / 2 - q / T, c[1] - ms / 2 - q / T)))
        if with_item:
            L, Wd = item
            ph = np.zeros((int(round(Wd * T)), int(round(L * T)), 3), np.uint8)
            ph[:] = (30, 30, 32)
            self._paste(frame, ph, self._hom(M, -item_h, (item_center[0] - L / 2, item_center[1] - Wd / 2)))
        if with_plate:
            top = (item_h if with_item else 0.0) + self.get("plate_thickness_mm")
            card = np.full((70 * T, 100 * T, 3), 255, np.uint8)
            ps = self.get("plate_marker_size_mm")
            for i, c in self.get("plate_marker_centers_mm").items():
                m = cv2.cvtColor(cv2.aruco.generateImageMarker(_DICT, int(i), int(ps * T)), cv2.COLOR_GRAY2BGR)
                x0, y0 = int((c[0] + 50 - ps / 2) * T), int((c[1] + 35 - ps / 2) * T)
                card[y0:y0 + m.shape[0], x0:x0 + m.shape[1]] = m
            self._paste(frame, card, self._hom(M, -top, (item_center[0] - 50, item_center[1] - 35)))
        f = frame.astype(np.float32) * light
        if noise_seed is not None:
            f += np.random.default_rng(noise_seed).normal(0, 2, frame.shape)
        return np.clip(f, 0, 255).astype(np.uint8)
