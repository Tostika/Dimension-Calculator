"""Synthetic test: renders the base, an item and the height card through a virtual pinhole
camera (real perspective), then checks that size and height come back right.
Run from the project folder:  python -m tests.test_vision"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import DEFAULTS  # noqa: E402
from app.vision import measure  # noqa: E402
from app.vision.synthetic import Scene  # noqa: E402


class S(dict):
    def get(self, k, d=None):
        return super().get(k, DEFAULTS.get(k, d))


def check(scene, st, calib, item, h_true, center, label, tol=0.6, cam_h=300.0):
    fp = scene.render(item_h=h_true, item=item, item_center=center, with_plate=True, cam_h=cam_h)
    fi = scene.render(item_h=h_true, item=item, item_center=center, cam_h=cam_h)
    bm = measure.build_base_map(fi, st, calib)
    h = measure.measure_height(fp, bm, st, fallback_camera_height_mm=cam_h)
    res = measure.measure_outline(fi, None, bm, height_mm=h, fallback_camera_height_mm=cam_h)
    print(f"[{label}] L={res['length']:.2f} W={res['width']:.2f} H={h:.2f}   "
          f"(true {item[0]:.2f} x {item[1]:.2f} x {h_true:.2f})")
    return abs(res["length"] - item[0]) < tol and abs(res["width"] - item[1]) < tol and abs(h - h_true) < tol


def run():
    st = S()
    sc = Scene()
    calib = {"K": sc.K.tolist(), "dist": [0, 0, 0, 0, 0], "rms": 0.0, "size": [sc.W, sc.H]}
    ok = True
    ok &= check(sc, st, None, (147.6, 71.5), 7.8, (125, 70), "phone, no lens calibration, 30 cm")
    ok &= check(sc, st, calib, (147.6, 71.5), 7.8, (125, 70), "phone, with lens calibration, 30 cm")
    ok &= check(sc, st, calib, (85.6, 53.98), 0.8, (95, 85), "bank card, off centre")
    ok &= check(sc, st, calib, (125.0, 90.0), 24.5, (125, 70), "thick book", tol=0.8)
    ok &= check(sc, st, calib, (147.6, 71.5), 7.8, (125, 70), "phone, 40 cm", cam_h=400.0)
    # LED on/off: room light present in both frames must not change the result
    fi = sc.render(item_h=7.8)
    off = sc.render(item_h=7.8, light=0.35, noise_seed=2)
    bm = measure.build_base_map(fi, st, calib)
    res = measure.measure_outline(fi, off, bm, height_mm=7.8)
    print(f"[LED on minus off] L={res['length']:.2f} W={res['width']:.2f}")
    ok &= abs(res["length"] - 147.6) < 0.8 and abs(res["width"] - 71.5) < 0.8
    print("PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
