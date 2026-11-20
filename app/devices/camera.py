"""Camera reader thread. Keeps the newest full-resolution frame for measuring and sends a
smaller preview frame to the screen. Plug and unplug are handled: with no camera it keeps
looking for one every 2 s. A camera counts as unplugged when Windows no longer lists it,
when it stops sending frames, or when it only sends black frames."""
import sys
import threading
import time

import cv2
from PySide6.QtCore import QThread, Signal


def camera_names():
    """Names of the video devices, in the same order OpenCV numbers them (Windows DirectShow).
    None if the names can't be read (not Windows, or pygrabber missing)."""
    if not sys.platform.startswith("win"):
        return None
    try:
        from pygrabber.dshow_graph import FilterGraph
        return list(FilterGraph().get_input_devices())
    except Exception:
        return None


RESOLUTIONS = {"4k": (3840, 2160), "1440": (2560, 1440), "1080": (1920, 1080)}
PREVIEW_WIDTH = 1280


class CameraThread(QThread):
    preview = Signal(object)        # small BGR frame for the screen
    status = Signal(bool)           # camera connected or not

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self._lock = threading.Lock()
        self._frame = None
        self._count = 0
        self._running = True
        self._cap = None
        self._pending = []           # property changes to apply inside the thread
        self._small = {}             # camera index -> time it was found to be a small (non-4K) camera
        self.device_name = ""

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
    def _try_index(self, idx):
        backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
        cap = cv2.VideoCapture(idx, backend)
        if not cap.isOpened():
            cap.release()
            return None, 0
        w, h = RESOLUTIONS.get(self.settings.get("resolution"), RESOLUTIONS["4k"])
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))   # without MJPG, 4K usually falls back to a tiny size
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            return None, 0
        return cap, frame.shape[1]

    def _configure(self, cap):
        if self.settings.get("lock_focus"):
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            cap.set(cv2.CAP_PROP_FOCUS, float(self.settings.get("focus_value")))
        else:
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
        if self.settings.get("lock_exposure"):
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)       # DirectShow: 0.25 = manual
            cap.set(cv2.CAP_PROP_EXPOSURE, float(self.settings.get("exposure_value")))
            cap.set(cv2.CAP_PROP_AUTO_WB, 0)
        else:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)       # DirectShow: 0.75 = automatic

    def _open(self):
        """Finds the measuring camera by itself. On Windows it goes by the device name
        (EMEET / C960), so a laptop webcam or a virtual camera (OBS etc.) is never picked.
        Without names it falls back to "the first camera that gives a 4K-class picture"."""
        names = camera_names()
        min_w = int(self.settings.get("min_camera_width"))
        if names is not None:
            hints = [h.lower() for h in self.settings.get("camera_name_hints")]
            for idx, name in enumerate(names):
                if any(h in name.lower() for h in hints):
                    cap, width = self._try_index(idx)
                    if cap is not None:
                        self._configure(cap)
                        self.device_name = name
                        return cap
            return None
        last = int(self.settings.get("last_camera_index"))
        now = time.time()
        for idx in [last] + [i for i in range(4) if i != last]:
            if now - self._small.get(idx, -1e9) < 30:
                continue
            cap, width = self._try_index(idx)
            if cap is None:
                continue
            if width >= min_w:
                self._configure(cap)
                self.device_name = ""
                if idx != last:
                    self.settings.set("last_camera_index", idx)
                return cap
            cap.release()
            self._small[idx] = now
        return None

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

    def _set_state(self, connected):
        if connected != getattr(self, "_state", None):
            self._state = connected
            if not connected:
                with self._lock:
                    self._frame = None
                self.device_name = ""
            self.status.emit(connected)

    def _drop(self):
        if self._cap is not None:
            self._cap.release()
        self._cap = None
        self._set_state(False)

    def run(self):
        try:                                    # device names are read through COM, which needs this per thread
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        last_preview = 0.0
        next_try = 0.0
        next_check = 0.0
        fails = 0
        black_since = None
        self._set_state(False)
        while self._running:
            self._apply_pending()
            now = time.time()
            if self._cap is None:
                if now >= next_try:
                    self._cap = self._open()
                    next_try = time.time() + 2.0
                    fails, black_since, next_check = 0, None, time.time() + 1.0
                if self._cap is None:
                    time.sleep(0.1)
                    continue
            # still plugged in? (Windows keeps a list of cameras; ours must be on it)
            if self.device_name and now >= next_check:
                next_check = now + 1.0
                names = camera_names()
                if names is not None and self.device_name not in names:
                    self._drop()
                    continue
            ok, frame = self._cap.read()
            if not ok or frame is None:
                fails += 1
                if fails >= 15:                          # about half a second of nothing
                    self._drop()
                time.sleep(0.03)
                continue
            fails = 0
            if frame[::16, ::16].max() < 8:              # an unplugged camera can keep sending black frames
                black_since = black_since or now
                if now - black_since > 2.0:
                    self._drop()
                    continue
            else:
                black_since = None
            self._set_state(True)
            with self._lock:
                self._frame = frame
                self._count += 1
            if now - last_preview > 1 / 30:
                last_preview = now
                h, w = frame.shape[:2]
                sc = PREVIEW_WIDTH / float(w)
                small = cv2.resize(frame, (PREVIEW_WIDTH, int(h * sc)), interpolation=cv2.INTER_AREA) if sc < 1 else frame
                self.preview.emit(small)
        if self._cap is not None:
            self._cap.release()
