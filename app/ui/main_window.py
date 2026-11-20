"""Main window: side menu, the four tabs, language and theme switching, device status."""
import cv2
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QMainWindow, QScrollArea, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import theme
from ..devices.camera import CameraThread
from ..devices.esp32 import Esp32
from ..i18n import Translator
from ..vision.calibration import scaled
from ..vision.markers import BASE_IDS, BaseMap, detect
from .calibration_page import CalibrationPage
from .common import bgr_to_qimage, button, label, run_task
from .library_page import LibraryPage
from .scan_page import ScanPage
from .settings_page import SettingsPage

WIN_W, WIN_H = 1280, 700      # fixed window size; every page is laid out for exactly this

TABS = (("scan", "tab_scan", "desc_scan"), ("library", "tab_library", "desc_library"),
        ("calibration", "tab_calibration", "desc_calibration"), ("settings", "tab_settings", "desc_settings"))


class MainWindow(QMainWindow):
    preview_ready = Signal(object)       # QImage of the newest preview frame
    camera_changed = Signal()            # camera plugged in / unplugged / demo switched

    def __init__(self, app, settings, library, calib_store, font_family):
        super().__init__()
        self.app, self.settings, self.library, self.calib_store = app, settings, library, calib_store
        self.font_family = font_family
        self.tab = 0
        self.live_markers, self.live_ids, self.full_width = [], set(), None
        self.live_height_mm = None        # camera height measured from the base markers (needs lens calibration)
        self._old_cameras = []
        self._last_preview = None
        self.camera_ok, self.camera_demo = False, False

        self.esp = Esp32()
        self.camera = None
        self.start_camera()
        run_task(lambda: self.esp.connect(self.settings.get("serial_port") or None), self._esp_ready)

        self.setFixedSize(WIN_W, WIN_H)
        self.apply_theme()
        self.build()

        self.marker_timer = QTimer(self)
        self.marker_timer.timeout.connect(self.detect_live_markers)
        self.marker_timer.start(330)
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)

    # ---------- devices ----------
    def start_camera(self):
        self.camera = CameraThread(self.settings)
        self.camera.preview.connect(self.on_preview)
        self.camera.status.connect(self.on_camera_status)
        self.camera.start()

    def restart_camera(self):
        old = self.camera
        old.preview.disconnect(self.on_preview)
        old.status.disconnect(self.on_camera_status)
        old._running = False
        self._old_cameras.append(old)        # keep it alive until its thread has really stopped
        old.finished.connect(lambda: self._old_cameras.remove(old) if old in self._old_cameras else None)
        self.start_camera()

    def on_camera_status(self, opened, demo):
        self.camera_ok, self.camera_demo = opened, demo
        if not opened and not demo:
            self._last_preview = None
            self.live_ids, self.live_markers = set(), []
        self.camera_changed.emit()
        self.update_status()

    def _esp_ready(self, ok):
        if ok:
            self.settings.set("serial_port", self.esp.port)
            self.set_led(int(self.settings.get("led_brightness")))
            run_task(lambda: self.esp.move_to(self.settings.camera_height_mm()))
        self.update_status()

    def set_led(self, percent):
        """Safe from any thread."""
        self.esp.set_led(percent)
        if self.camera is not None and self.camera.demo is not None:
            self.camera.demo.led = percent / 100.0

    def on_preview(self, frame):
        self._last_preview = frame
        size = self.camera.frame_size()
        self.full_width = size[0] if size else None
        self.preview_ready.emit(bgr_to_qimage(frame))

    def detect_live_markers(self):
        f = self._last_preview
        if f is None:
            return
        found = detect(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
        self.live_ids = set(found)
        self.live_markers = [c.tolist() for c in found.values()]
        self.live_height_mm = None
        size = self.camera.frame_size()
        lens = self.calib_store.lens(size)
        if lens and size and all(i in found for i in BASE_IDS):
            try:
                bm = BaseMap(found, self.settings.get("base_marker_centers_mm"), self.settings.get("marker_size_mm"),
                             scaled(lens, f.shape[1] / float(size[0])))
                self.live_height_mm = bm.camera_height_mm
            except Exception:
                pass

    def update_status(self):
        if not hasattr(self, "st_camera"):
            return
        t = self.t
        try:
            if self.camera_demo:
                self.st_camera.setText(t("demo_camera"))
                self._dot(self.st_camera_dot, False)
            else:
                self.st_camera.setText(f"{t('camera')}: {t('connected') if self.camera_ok else t('not_connected')}")
                self._dot(self.st_camera_dot, self.camera_ok)
            self.st_esp.setText(f"ESP32 {self.esp.port}: {t('connected')}" if self.esp.connected
                                else f"ESP32: {t('not_connected')}")
            self._dot(self.st_esp_dot, self.esp.connected)
            base = len(self.live_ids & {0, 1, 2, 3})
            self.st_markers.setText(f"{t('base_markers')} {base}/4")
            self._dot(self.st_markers_dot, base == 4)
        except RuntimeError:
            pass

    def _dot(self, w, ok):
        w.setStyleSheet(f"background: {self.palette['ok'] if ok else self.palette['danger']}; border-radius: 4px;")

    # ---------- look and language ----------
    def apply_theme(self):
        self.t = Translator(self.settings.get("language"))
        self.palette = theme.palette(theme.base_colors(self.settings), self.settings.get("corners"))
        self.app.setStyleSheet(theme.stylesheet(self.palette, self.font_family(self.settings.get("language"))))

    def appearance_changed(self):
        QTimer.singleShot(0, self._rebuild)      # rebuild after the click handler has finished

    def set_language(self, code):
        self.settings.set("language", code)
        self.appearance_changed()

    def _rebuild(self):
        self.apply_theme()
        self.build()

    def build(self):
        t = self.t
        self.setWindowTitle(t("app_title"))
        root = QWidget()
        root.setObjectName("Root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # side menu
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 16)
        sl.setSpacing(6)
        sl.addWidget(label(t("app_title"), "AppTitle", wrap=True))
        sl.addWidget(label(t("app_sub"), "Hint", wrap=True))
        sl.addSpacing(16)
        group = QButtonGroup(side)
        group.setExclusive(True)
        self.nav = []
        for i, (_, key, _) in enumerate(TABS):
            b = button(t(key), "Nav", checkable=True)
            b.setChecked(i == self.tab)
            b.clicked.connect(lambda _=False, n=i: self.go(n))
            group.addButton(b)
            sl.addWidget(b)
            self.nav.append(b)
        sl.addStretch(1)
        langs = QFrame()
        langs.setObjectName("Inset")
        ll = QHBoxLayout(langs)
        ll.setContentsMargins(4, 4, 4, 4)
        ll.setSpacing(4)
        for code, short in (("ka", "ქარ"), ("en", "ENG")):
            b = button(short, "Lang", checkable=True)
            b.setChecked(self.settings.get("language") == code)
            b.clicked.connect(lambda _=False, c=code: self.set_language(c))
            ll.addWidget(b)
        sl.addWidget(langs)
        sl.addSpacing(10)
        self.st_camera_dot, self.st_camera = self._status_row(sl)
        self.st_esp_dot, self.st_esp = self._status_row(sl)
        self.st_markers_dot, self.st_markers = self._status_row(sl)
        h.addWidget(side)

        # content
        content = QWidget()
        content.setObjectName("Page")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(22, 16, 22, 18)
        cl.setSpacing(4)
        self.page_title = label("", "PageTitle")
        self.page_desc = label("", "Muted", wrap=True)
        cl.addWidget(self.page_title)
        cl.addWidget(self.page_desc)
        cl.addSpacing(10)
        self.stack = QStackedWidget()
        for cls in (ScanPage, LibraryPage, CalibrationPage, SettingsPage):
            page = cls(self)
            if cls is ScanPage:
                self.stack.addWidget(page)
            else:
                sc = QScrollArea()
                sc.setWidgetResizable(True)
                sc.setFrameShape(QFrame.Shape.NoFrame)
                sc.setWidget(page)
                self.stack.addWidget(sc)
        cl.addWidget(self.stack, 1)
        h.addWidget(content, 1)

        self.setCentralWidget(root)
        self.go(self.tab)
        self.update_status()

    def _status_row(self, layout):
        w = QWidget()
        r = QHBoxLayout(w)
        r.setContentsMargins(4, 2, 4, 2)
        r.setSpacing(8)
        dot = QWidget()
        dot.setFixedSize(8, 8)
        text = label("", "Hint", wrap=True)
        r.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
        r.addWidget(text, 1)
        layout.addWidget(w)
        return dot, text

    def go(self, n):
        self.tab = n
        self.stack.setCurrentIndex(n)
        self.nav[n].setChecked(True)
        _, key, desc = TABS[n]
        self.page_title.setText(self.t(key))
        self.page_desc.setText(self.t(desc))

    # ---------- closing ----------
    def closeEvent(self, e):
        try:
            self.esp.set_led(0)
            self.esp.close()
        except Exception:
            pass
        self.camera.stop()
        for old in list(self._old_cameras):
            old.wait(3000)
        self.library.close()
        super().closeEvent(e)
