"""Scan tab: step 1 outline, step 2 height (marker card on top), step 3 save / export."""
import os

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QSlider, QVBoxLayout,
                               QWidget)

from .. import export
from ..devices.camera import PREVIEW_WIDTH
from ..vision import measure
from .common import CameraView, Stepper, WrapCheck, button, card, label, repolish, run_task


class ScanPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.setObjectName("Page")
        self.main, self.t, self.s, self.p = main, main.t, main.settings, main.palette
        self.step = 1
        self.frames = None          # (on, off) from step 1
        self.base_map = None
        self.result = None          # outline result
        self.height = None
        self.busy = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        # steps row
        steps = QHBoxLayout()
        steps.setSpacing(10)
        self.step_cards = []
        for i in range(3):
            f = QFrame()
            f.setObjectName("StepCard")
            f.setFixedHeight(74)
            lay = QVBoxLayout(f)
            lay.setContentsMargins(14, 10, 14, 10)
            lay.setSpacing(2)
            top, bottom = label("", "Hint"), label("", wrap=True)
            bottom.setStyleSheet("font-weight: 600;")
            lay.addWidget(top)
            lay.addWidget(bottom)
            steps.addWidget(f, 1)
            self.step_cards.append((f, top, bottom))
        outer.addLayout(steps)

        # shared widgets
        self.view = CameraView(self.p, self.p["r"])
        self.view.badge = self.t("live")
        self.view.offline_title = self.t("no_camera")
        self.view.offline_hint = self.t("no_camera_hint")
        self.val = {}
        self.primary = button("", "Primary", self.on_primary)
        self.export_btn = button(self.t("export_dxf"), on_click=self.on_export)
        self.new_btn = button(self.t("new_scan"), on_click=self.reset)
        self.led_slider = QSlider(Qt.Orientation.Horizontal)
        self.led_slider.setRange(0, 100)
        self.led_slider.setValue(int(self.s.get("led_brightness")))
        self.led_value = label(f"{self.led_slider.value()}%", "AccentValue")
        self.led_slider.valueChanged.connect(self.on_led)
        self._led_timer = QTimer(self)
        self._led_timer.setSingleShot(True)
        self._led_timer.setInterval(120)
        self._led_timer.timeout.connect(lambda: self.main.set_led(self.led_slider.value()))
        self.z_spin = Stepper(self.s.get("camera_height_cm"), self.s.get("camera_height_min_cm"),
                              self.s.get("camera_height_max_cm"), self.t("cm"))
        self.z_set_btn = button(self.t("set_height"), on_click=self.on_set_height)
        self.z_measured = label("", "Hint", wrap=True)
        self._z_timer = QTimer(self)
        self._z_timer.timeout.connect(self.update_measured_height)
        self._z_timer.start(700)

        if self.s.get("scan_layout") == "wide":
            outer.addWidget(self._wide(), 1)
        else:
            outer.addWidget(self._side(), 1)

        main.preview_ready.connect(self.on_preview)
        main.camera_changed.connect(self.on_camera_changed)
        self.on_camera_changed()
        self.refresh()

    # ---------- layouts ----------
    def _result_block(self, big=True):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(2)
        if big:      # one value per line, large, in the side panel
            for n, key in enumerate(("length", "width", "height")):
                g.addWidget(label(self.t(key), "Hint"), n * 2, 0)
                v = label(self.t("empty_value"), "HugeValue")
                g.addWidget(v, n * 2 + 1, 0)
                self.val[key] = v
            return w
        for col, key in enumerate(("length", "width", "height")):
            g.addWidget(label(self.t(key), "Hint"), 0, col)
            v = label(self.t("empty_value"), "MidValue")
            g.addWidget(v, 1, col)
            self.val[key] = v
        return w

    def _light_block(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label(self.t("led_brightness")))
        top.addStretch(1)
        top.addWidget(self.led_value)
        lay.addLayout(top)
        lay.addWidget(self.led_slider)
        return w

    def _ambient_box(self):
        return WrapCheck(self.t("remove_ambient"), self.s.get("remove_ambient"),
                         lambda v: self.s.set("remove_ambient", bool(v)))

    def _z_row(self, with_measured=True):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.z_spin, 3)
        row.addWidget(self.z_set_btn, 2)
        lay.addLayout(row)
        if with_measured:
            lay.addWidget(self.z_measured)
        return w

    def _controls_row(self):
        """LED card and camera-height card side by side (under the camera)."""
        row = QHBoxLayout()
        row.setSpacing(12)
        c, cl = card(spacing=8)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.addWidget(self._light_block())
        cl.addWidget(self._ambient_box())
        row.addWidget(c, 1)
        c, cl = card(spacing=8)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.addWidget(label(self.t("camera_height_cm")))
        cl.addWidget(self._z_row())
        row.addWidget(c, 1)
        return row

    def _side(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(12)
        self.view.align_top = True
        left.addWidget(self.view, 1)
        left.addLayout(self._controls_row())
        lay.addLayout(left, 1)
        c, cl = card(spacing=12)
        c.setFixedWidth(310)
        cl.addWidget(label(self.t("result_mm"), "SectionTitle"))
        cl.addWidget(self._result_block())
        cl.addStretch(1)
        cl.addWidget(self.primary)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.export_btn)
        row.addWidget(self.new_btn)
        cl.addLayout(row)
        lay.addWidget(c)
        return w

    def _wide(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        holder = QWidget()
        g = QGridLayout(holder)
        g.setContentsMargins(0, 0, 0, 0)
        g.addWidget(self.view, 0, 0)
        hud, hl = card(spacing=4)
        hl.setContentsMargins(16, 10, 16, 10)
        hl.addWidget(self._result_block(big=False))
        g.addWidget(hud, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        lay.addWidget(holder, 1)
        dock = QHBoxLayout()
        dock.setSpacing(10)
        c, cl = card()
        cl.setContentsMargins(14, 8, 14, 8)
        cl.addWidget(self._light_block())
        dock.addWidget(c, 3)
        c, cl = card(spacing=2)
        cl.setContentsMargins(14, 8, 14, 8)
        cl.addWidget(label(self.t("camera_height_cm"), "Hint"))
        cl.addWidget(self._z_row(with_measured=False))
        dock.addWidget(c, 3)
        for b, stretch in ((self.primary, 3), (self.export_btn, 2), (self.new_btn, 2)):
            b.setMinimumHeight(64)
            dock.addWidget(b, stretch)
        lay.addLayout(dock)
        return w

    # ---------- state ----------
    def refresh(self):
        texts = [("step1", "step1_do", "step1_done"), ("step2", "step2_do", "step2_done"), ("step3", "step3_do", "step3_do")]
        for i, (f, top, bottom) in enumerate(self.step_cards):
            n = i + 1
            title, todo, done = texts[i]
            active = n == self.step
            top.setText(self.t(title) + (f"  ({self.t('now')})" if active else ""))
            if n < self.step:
                bottom.setText(self.t(done))
                bottom.setStyleSheet(f"font-weight: 600; color: {self.p['ok']};")
            elif active:
                bottom.setText(self.t(todo))
                bottom.setStyleSheet("font-weight: 600;")
            else:
                bottom.setText(self.t("waiting"))
                bottom.setStyleSheet(f"font-weight: 600; color: {self.p['muted']};")
            f.setProperty("active", "true" if active else "false")
            repolish(f)
        self.primary.setText({1: self.t("capture_outline"), 2: self.t("capture_height"), 3: self.t("save")}[self.step])
        has_camera = self.main.camera_ok
        ready = has_camera and not self.busy
        self.primary.setEnabled(ready)
        self.export_btn.setEnabled(ready and self.result is not None)
        self.new_btn.setEnabled(ready and (self.step > 1 or self.result is not None))
        self.z_spin.setEnabled(not self.busy)
        self.z_set_btn.setEnabled(not self.busy)
        r = self.result
        e = self.t("empty_value")
        self.val["length"].setText(f"{r['length']:.1f}" if r else e)
        self.val["width"].setText(f"{r['width']:.1f}" if r else e)
        self.val["height"].setText(f"{self.height:.1f}" if self.height is not None else e)

    def show_message(self, text, error=False):
        self.view.message = text or ""
        self.view.message_error = error
        self.view.update()

    def reset(self):
        self.step, self.frames, self.base_map, self.result, self.height = 1, None, None, None, None
        self.view.contour = None
        self.show_message("")
        self.refresh()

    # ---------- live view ----------
    def on_camera_changed(self):
        if not self.main.camera_ok:
            self.view.set_offline()
            self.view.markers = []
            self.view.right_badge = ""
        self.refresh()

    def on_preview(self, qimage):
        if not self.main.camera_ok:
            return
        self.view.set_frame(qimage)
        self.view.markers = self.main.live_markers
        n = len(self.main.live_ids & {0, 1, 2, 3})
        self.view.right_badge = f"{self.t('base_markers')} {n}/4"
        if self.result is not None and self.main.full_width:
            s = PREVIEW_WIDTH / float(self.main.full_width)
            self.view.contour = (self.result["contour_px"] * s).tolist()

    # ---------- actions ----------
    def _calib(self):
        return self.main.calib_store.lens(self.main.camera.frame_size())

    def _set_busy(self, v):
        self.busy = v
        self.refresh()

    def _fail(self, e):
        self._set_busy(False)
        if isinstance(e, measure.MeasureError):
            self.show_message(self.t(e.key, **e.params), error=True)
        else:
            self.show_message(str(e), error=True)

    def on_primary(self):
        if self.step == 1:
            self.capture_outline()
        elif self.step == 2:
            self.capture_height()
        else:
            self.save()

    def capture_outline(self):
        cam, s, main = self.main.camera, self.s, self.main
        calib = self._calib()
        z = s.camera_height_mm()

        def job():
            level = int(s.get("led_brightness"))
            main.set_led(level)
            on = cam.wait_new_frames(4)
            off = None
            if s.get("remove_ambient") and main.esp.connected:   # without the ESP32 the LEDs can't switch off
                main.set_led(0)
                off = cam.wait_new_frames(4)
                main.set_led(level)
            bm = measure.build_base_map(on, s, calib)
            res = measure.measure_outline(on, off, bm, None, z)
            return on, off, bm, res

        def done(r):
            self.frames = (r[0], r[1])
            self.base_map, self.result = r[2], r[3]
            self.step = 2
            self._set_busy(False)
            self.show_message("" if calib else self.t("err_not_calibrated"))

        self._set_busy(True)
        self.show_message("")
        run_task(job, done, self._fail)

    def capture_height(self):
        cam, s = self.main.camera, self.s
        z = s.camera_height_mm()
        bm, (on, off) = self.base_map, self.frames

        def job():
            frame = cam.wait_new_frames(3)
            h = measure.measure_height(frame, bm, s, z)
            res = measure.measure_outline(on, off, bm, h, z)   # outline again, now corrected for height
            return h, res

        def done(r):
            self.height, self.result = r
            self.step = 3
            self._set_busy(False)
            self.show_message("")

        self._set_busy(True)
        run_task(job, done, self._fail)

    def save(self):
        r = self.result
        item = self.main.library.add(r["length"], r["width"], self.height, np.asarray(r["outline_mm"]).tolist(),
                                     self.s.get("export_folder"), bool(self.s.get("save_json")))
        self.reset()
        self.show_message(self.t("saved_as", name=item["display_name"]))

    def on_export(self):
        r = self.result
        if r is None:
            return
        start = os.path.join(self.s.get("export_folder"), "scan.dxf")
        path, _ = QFileDialog.getSaveFileName(self, self.t("export_dxf"), start, "DXF (*.dxf)")
        if not path:
            return
        if not path.lower().endswith(".dxf"):
            path += ".dxf"
        export.write_dxf(path, np.asarray(r["outline_mm"]).tolist(), r["length"], r["width"], self.height)
        self.show_message(self.t("exported_to", path=path))

    def on_led(self, v):
        self.led_value.setText(f"{v}%")
        self.s.set("led_brightness", int(v))
        self._led_timer.start()

    def update_measured_height(self):
        h = self.main.live_height_mm
        self.z_measured.setText(self.t("height_measured", cm=f"{h / 10:.1f}") if h else self.t("height_unknown"))

    def on_set_height(self):
        cm = int(self.z_spin.value())
        esp, s = self.main.esp, self.s

        def job():
            esp.move_to(cm * 10)
            return cm

        def done(_):
            s.set("camera_height_cm", cm)
            self._set_busy(False)
            self.reset()

        self._set_busy(True)
        run_task(job, done, self._fail)
