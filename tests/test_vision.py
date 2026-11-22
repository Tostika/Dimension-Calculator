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
    # the A3 sheet on the base while the app expects A4: it must switch by itself
    from app.config import BASE_SHEETS
    a3 = Scene(settings=S(BASE_SHEETS["A3"]))
    st2 = S(BASE_SHEETS["A4"])
    switched = []
    st2.use_sheet = lambda name: (switched.append(name), st2.update(BASE_SHEETS[name]))
    f3 = a3.render(item_h=7.8, cam_h=400.0)
    bm = measure.build_base_map(f3, st2, None)
    res = measure.measure_outline(f3, None, bm, height_mm=7.8, fallback_camera_height_mm=400.0)
    print(f"[A3 sheet, app set to A4] switched to {switched} L={res['length']:.2f} W={res['width']:.2f}")
    ok &= switched == ["A3"] and abs(res["length"] - 147.6) < 0.8 and abs(res["width"] - 71.5) < 0.8
    # base printed at 97 %, card printed at 93 %, slightly wrong lens correction: after the zero
    # check the height must still come out right (the outline keeps the base sheet's scale)
    for base_f, card_f in ((0.97, 1.0), (1.0, 0.93), (0.97, 0.93)):
        world = S({"marker_size_mm": 30 * base_f,
                   "base_marker_centers_mm": {k: [v[0] * base_f, v[1] * base_f] for k, v in BASE_SHEETS["A3"]["base_marker_centers_mm"].items()},
                   "plate_marker_size_mm": DEFAULTS["plate_marker_size_mm"] * card_f,
                   "plate_marker_centers_mm": {k: [v[0] * card_f, v[1] * card_f] for k, v in DEFAULTS["plate_marker_centers_mm"].items()}})
        scw = Scene(settings=world)
        app = S(BASE_SHEETS["A3"])
        cal = {"K": scw.K.tolist(), "dist": [-0.03, 0, 0, 0, 0], "rms": 0.0, "size": [scw.W, scw.H]}
        bm0 = measure.build_base_map(scw.render(with_item=False, cam_h=400.0), app, cal)
        app["plate_zero_scale"] = measure.zero_scale(scw.render(with_item=False, with_plate=True, cam_h=400.0), bm0, app, 400.0)
        fp = scw.render(item_h=0.8, item=(85.6, 53.98), with_plate=True, cam_h=400.0)
        bm = measure.build_base_map(scw.render(item_h=0.8, item=(85.6, 53.98), cam_h=400.0), app, cal)
        h = measure.measure_height(fp, bm, app, 400.0)
        print(f"[base {base_f:.0%}, card {card_f:.0%}, lens off, after zero check] H={h:.2f} (true 0.80)")
        ok &= abs(h - 0.8) < 0.5
    print("PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
