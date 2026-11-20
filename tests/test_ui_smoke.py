"""Builds the whole UI against a stub Qt and runs the main paths (both languages, both
layouts, every theme, custom colours, a saved item in the library).
Run:  python -m tests.test_ui_smoke"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import qt_stub  # noqa: E402

qt_stub.install()

from app import theme  # noqa: E402
from app.config import Settings  # noqa: E402
from app.storage import Library  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.vision.calibration import CalibrationStore  # noqa: E402


def run():
    d = tempfile.mkdtemp()
    s = Settings(os.path.join(d, "settings.json"))
    s.set("export_folder", os.path.join(d, "exports"))
    lib = Library(os.path.join(d, "lib.db"))
    lib.add(147.6, 71.5, 7.8, [[0, 0], [147.6, 0], [147.6, 71.5], [0, 71.5]], s.get("export_folder"))
    lib.add(85.6, 54.0, None, [[0, 0], [85.6, 0], [85.6, 54], [0, 54]], s.get("export_folder"))
    store = CalibrationStore(os.path.join(d, "cal.json"))
    store.set_lens({"K": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "dist": [0] * 5, "rms": 0.21, "size": [3840, 2160], "focus": 30})
    w = MainWindow(qt_stub.Dummy(), s, lib, store, lambda lang: "Segoe UI")
    for lang in ("ka", "en"):
        for layout in ("side", "wide"):
            for pid in theme.PRESET_ORDER:
                s.set("language", lang)
                s.set("scan_layout", layout)
                s.set("theme", pid)
                w._rebuild()
                for n in range(4):
                    w.go(n)
    s.set("theme", "custom")
    s.set("custom_colors", {"bg": "#FFFFFF", "surface": "#FFFFFF", "text": "#EEEEEE", "accent": "#FFFF00"})
    w._rebuild()
    print("readability with bad colours:", [(k, round(r, 1), ok) for k, r, ok in theme.readability(w.palette)])

    # exercise page logic directly
    scan, library, cal, sett = (w.stack.widget(i) for i in range(4))
    print("pages built:", type(scan).__name__)
    w.update_status()
    w.detect_live_markers()
    print("library rows:", lib.count())
    lib.close()
    print("UI SMOKE PASS")


if __name__ == "__main__":
    run()


def run_pages():
    """Runs the scan flow (outline, height, save), library rename/search and calibration checks
    with demo frames, with background tasks run immediately."""
    import cv2
    import numpy as np
    from tests.fake_camera import DemoScene
    from app.ui import calibration_page, library_page, scan_page, settings_page
    from app.vision.synthetic import Scene

    def now(fn, done=None, err=None):
        try:
            r = fn()
        except Exception as e:
            if err:
                err(e)
            else:
                raise
        else:
            if done:
                done(r)

    for m in (scan_page, calibration_page, settings_page):
        m.run_task = now

    d = tempfile.mkdtemp()
    s = Settings(os.path.join(d, "settings.json"))
    s.set("export_folder", os.path.join(d, "exports"))
    lib = Library(os.path.join(d, "lib.db"))
    store = CalibrationStore(os.path.join(d, "cal.json"))
    w = MainWindow(qt_stub.Dummy(), s, lib, store, lambda lang: "Segoe UI")
    w.camera_ok = True
    cam = w.camera
    cam.demo = DemoScene(Scene(1920, 1080, tex_px_per_mm=4, settings=s))
    cam.wait_new_frames = lambda n=3, timeout=3.0: cam.demo.frame()
    cam.latest = lambda: (cam.demo.frame(), 1)
    cam.frame_size = lambda: (1920, 1080)
    w.esp._ser = object()                       # pretend the ESP32 is connected, LEDs drive the fake scene
    w.esp._cmd = lambda line, **k: "OK"
    w.set_led = lambda pct: setattr(cam.demo, "led", pct / 100.0)

    sp = scan_page.ScanPage(w)
    sp.capture_outline()
    if sp.result is None:
        print("outline failed:", sp.view.message)
    print("step after outline:", sp.step, "L/W:", round(sp.result["length"], 1), round(sp.result["width"], 1))
    cam.demo.mode = "plate"
    sp.capture_height()
    cam.demo.mode = "item"
    print("step after height:", sp.step, "H:", round(sp.height, 2), "L/W:", round(sp.result["length"], 1), round(sp.result["width"], 1))
    sp.save()
    print("saved; library count:", lib.count(), "names:", [r["display_name"] for r in lib.all()])
    # a failing capture: no item on the base
    cam.demo.mode = "empty"
    sp.refresh = lambda: None
    sp.capture_outline()
    print("error shown on camera view:", sp.view.message)

    class FakeItem:
        def __init__(self):
            self.d = None

        def setData(self, role, v):
            self.d = v

        def data(self, role):
            return self.d

        def setSizeHint(self, *a):
            pass

    class FakeList:
        def __init__(self):
            self.items, self.row = [], 0

        def clear(self):
            self.items = []

        def addItem(self, it):
            self.items.append(it)

        def currentItem(self):
            return self.items[self.row] if self.items else None

        def setCurrentRow(self, r):
            self.row = r

        def __getattr__(self, n):
            return lambda *a, **k: None

    library_page.QListWidgetItem = FakeItem
    lp = library_page.LibraryPage(w)
    lp.list = FakeList()
    lp.reload()
    print("library selected:", lp.current["display_name"])
    lp.current = lib.all()[0]
    lp.on_rename("ტელეფონი")
    print("after rename:", [r["display_name"] for r in lib.all("ტელ")])

    cp = calibration_page.CalibrationPage(w)
    cp._msg = lambda lab, text, error=False: print("  calibration message:", "ERROR" if error else "ok", text)
    cp.fill_lens_rows()
    cp.update_chips()
    cp.on_check_base()
    cp.on_learn_layout()
    print("  layout after learning:", s.get("base_marker_centers_mm"))
    cp.session = __import__("app.vision.calibration", fromlist=["x"]).CalibrationSession()
    w._last_preview = cv2.resize(cam.demo.frame(), (1280, 720))
    cp.look_for_board()
    cp._update_session()
    cp.session = None
    cam.demo.mode = "plate_empty"
    cp.on_zero()
    cam.demo.mode = "item"
    # live camera height from the markers, with a lens calibration of the demo camera
    from app.vision.synthetic import Scene as _Sc
    sc = _Sc(1920, 1080, tex_px_per_mm=4, settings=s)
    store.set_lens({"K": sc.K.tolist(), "dist": [0] * 5, "rms": 0.1, "size": [1920, 1080], "focus": 30})
    w._last_preview = cv2.resize(cam.demo.frame(), (1280, 720))
    w.detect_live_markers()
    print("live camera height (true 370 mm):", w.live_height_mm and round(w.live_height_mm, 1))
    sp.update_measured_height()

    stp = settings_page.SettingsPage(w)
    stp.fill_ports()
    stp.update_esp_msg()
    lib.close()
    print("PAGES PASS")


if __name__ == "__main__":
    run_pages()
