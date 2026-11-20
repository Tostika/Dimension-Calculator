"""Camera reader thread. Keeps the newest full-resolution frame for measuring and sends a
smaller preview frame to the screen. Falls back to a demo scene if no camera opens."""
import sys
import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

RESOLUTIONS = {"4k": (3840, 2160), "1440": (2560, 1440), "1080": (1920, 1080)}
PREVIEW_WIDTH = 1280


class CameraThread(QThread):
    preview = Signal(object)        # small BGR frame for the screen
    status = Signal(bool, bool)     # (opened, is_demo)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self._lock = threading.Lock()
        self._frame = None
        self._count = 0
        self._running = True
        self._cap = None
        self._pending = []           # property changes to apply inside the thread
        self.is_demo = False
        self.demo = None

    # ---------- used by other threads ----------
    def latest(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy(), self._count

    def frame_size(self):
        with self._lock:
            if self._frame is None:
                return None
            h, w = self._frame.shape[:2]
            return (w, h)

    def wait_new_frames(self, n=3, timeout=3.0):
        """Waits until n new frames have arrived (so a LED change is visible), then returns the newest."""
        _, start = self.latest()
        t0 = time.time()
        while time.time() - t0 < timeout:
            frame, c = self.latest()
            if c - start >= n and frame is not None:
                return frame
            time.sleep(0.01)
        frame, _ = self.latest()
        return frame

    def set_focus(self, value):
        self._pending.append(("focus", value))

    def autofocus_then_lock(self):
        """Lets the camera focus by itself for 2 s, then locks that focus. Returns the value."""
        self._pending.append(("autofocus", 1))
        time.sleep(2.0)
        self._pending.append(("read_focus", None))
        time.sleep(0.3)
        return self.settings.get("focus_value")

    def stop(self):
        self._running = False
        self.wait(3000)

    # ---------- thread ----------
    def _open(self):
        idx = int(self.settings.get("camera_index"))
        backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
        cap = cv2.VideoCapture(idx, backend)
        if not cap.isOpened():
            return None
        w, h = RESOLUTIONS.get(self.settings.get("resolution"), RESOLUTIONS["4k"])
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))   # without MJPG, 4K usually falls back to a tiny size
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if self.settings.get("lock_focus"):
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            cap.set(cv2.CAP_PROP_FOCUS, float(self.settings.get("focus_value")))
        else:
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
        if self.settings.get("lock_exposure"):
            # DirectShow: 0.25 = manual. Exposure is a power of two in seconds (-6 = 1/64 s).
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
            cap.set(cv2.CAP_PROP_EXPOSURE, float(self.settings.get("exposure_value")))
            cap.set(cv2.CAP_PROP_AUTO_WB, 0)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            return None
        return cap

    def _apply_pending(self):
        while self._pending:
            what, val = self._pending.pop(0)
            if self._cap is None:
                continue
            if what == "focus":
                self._cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
                self._cap.set(cv2.CAP_PROP_FOCUS, float(val))
            elif what == "autofocus":
                self._cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
            elif what == "read_focus":
                v = self._cap.get(cv2.CAP_PROP_FOCUS)
                self._cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
                self._cap.set(cv2.CAP_PROP_FOCUS, v)
                self.settings.set("focus_value", float(v))

    def _demo_frame(self):
        from ..vision.synthetic import Scene
        if self.demo is None:
            self.demo = DemoScene(Scene(1920, 1080, tex_px_per_mm=4, settings=self.settings))
        time.sleep(1 / 15)
        return self.demo.frame()

    def run(self):
        self._cap = self._open()
        self.is_demo = self._cap is None
        self.status.emit(not self.is_demo, self.is_demo)
        last_preview = 0.0
        while self._running:
            self._apply_pending()
            if self.is_demo:
                frame = self._demo_frame()
            else:
                ok, frame = self._cap.read()
                if not ok or frame is None:
                    time.sleep(0.05)
                    continue
            with self._lock:
                self._frame = frame
                self._count += 1
            now = time.time()
            if now - last_preview > 1 / 30:
                last_preview = now
                h, w = frame.shape[:2]
                s = PREVIEW_WIDTH / float(w)
                small = cv2.resize(frame, (PREVIEW_WIDTH, int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else frame
                self.preview.emit(small)
        if self._cap is not None:
            self._cap.release()


class DemoScene:
    """What the demo camera shows. The scan page switches it: item alone, item + card, empty."""

    def __init__(self, scene):
        self.scene = scene
        self.mode = "item"
        self.led = 1.0
        self._cache = {}

    def frame(self):
        key = (self.mode, round(self.led, 2))
        if key not in self._cache:
            light = 0.35 + 0.65 * self.led                      # room light + our LEDs
            if self.mode == "item":
                f = self.scene.render(with_item=True, light=light, noise_seed=None)
            elif self.mode == "plate":
                f = self.scene.render(with_item=True, with_plate=True, light=light, noise_seed=None)
            elif self.mode == "plate_empty":
                f = self.scene.render(with_item=False, with_plate=True, light=light, noise_seed=None)
            elif self.mode == "card":
                f = self.scene.render(item_h=0.8, item=(85.6, 53.98), item_center=(150, 95), light=light, noise_seed=None)
            else:
                f = self.scene.render(with_item=False, light=light, noise_seed=None)
            if len(self._cache) > 12:
                self._cache.clear()
            self._cache[key] = f
        noise = np.random.default_rng().integers(-2, 3, size=(8, 8, 3), dtype=np.int16)
        f = self._cache[key].astype(np.int16)
        f[:8, :8] += noise                                      # tiny change so frames are "new"
        return np.clip(f, 0, 255).astype(np.uint8)
