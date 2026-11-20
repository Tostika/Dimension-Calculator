"""Scan tab: step 1 outline, step 2 height (marker card on top), step 3 save / export."""
import os

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QSlider, QVBoxLayout,
                               QWidget)

from .. import export
from ..devices.camera import PREVIEW_WIDTH
from ..vision import measure
from .common import CameraView, button, card, label, repolish, run_task


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
            lay = QVBoxLayout(f)
            lay.setContentsMargins(16, 12, 16, 12)
            lay.setSpacing(2)
            top, bottom = label("", "Hint"), label("", wrap=True)
            bottom.setStyleSheet("font-weight: 600;")
            lay.addWidget(top)
            lay.addWidget(bottom)
            steps.addWidget(f, 1)
            self.step_cards.append((f, top, bottom))
        outer.addLayout(steps)

        self.message = label("", "Message", wrap=True)
        self.message.hide()
        outer.addWidget(self.message)

        # shared widgets
        self.view = CameraView(self.p["accent"], self.p["r"])
        self.view.badge = self.t("live")
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
        self.z_buttons = []
        for z in self.s.get("z_presets_mm"):
            b = button(f"{z / 10:g} {self.t('cm')}", "Toggle", checkable=True)
            b.setChecked(int(z) == int(self.s.get("z_preset_mm")))
            b.clicked.connect(lambda _=False, zz=z: self.on_z(zz))
            self.z_buttons.append((z, b))
        self.home_btn = button(self.t("home"), on_click=self.on_home)

        if self.s.get("scan_layout") == "wide":
            outer.addWidget(self._wide(), 1)
        else:
            outer.addWidget(self._side(), 1)

        main.preview_ready.connect(self.on_preview)
        self.refresh()

    # ---------- layouts ----------
    def _result_block(self, big=True):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(2)
        for col, key in enumerate(("length", "width", "height")):
            g.addWidget(label(self.t(key), "Hint"), 0, col)
            v = label(self.t("empty_value"), "BigValue" if big else "MidValue")
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
        cb = QCheckBox(self.t("remove_ambient"))
        cb.setChecked(bool(self.s.get("remove_ambient")))
        cb.toggled.connect(lambda v: self.s.set("remove_ambient", bool(v)))
        return cb

    def _z_row(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for _, b in self.z_buttons:
            lay.addWidget(b, 1)
        lay.addWidget(self.home_btn, 1)
        return w

    def _side(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        lay.addWidget(self.view, 3)
        col = QVBoxLayout()
        col.setSpacing(12)
        c, cl = card()
        cl.addWidget(label(self.t("result_mm"), "SectionTitle"))
        cl.addWidget(self._result_block())
        cl.addWidget(self.primary)
        row = QHBoxLayout()
        row.addWidget(self.export_btn)
        row.addWidget(self.new_btn)
        cl.addLayout(row)
        col.addWidget(c)
        c, cl = card()
        cl.addWidget(self._light_block())
        cl.addWidget(self._ambient_box())
        col.addWidget(c)
        c, cl = card()
        cl.addWidget(label(self.t("camera_height")))
        cl.addWidget(self._z_row())
        col.addWidget(c)
        col.addStretch(1)
        side = QWidget()
        side.setLayout(col)
        side.setMinimumWidth(320)
        side.setMaximumWidth(420)
        lay.addWidget(side, 1)
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
        hl.setContentsMargins(16, 12, 16, 12)
        hl.addWidget(self._result_block(big=False))
        g.addWidget(hud, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        g.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(holder, 1)
        dock = QHBoxLayout()
        dock.setSpacing(10)
        c, cl = card()
        cl.setContentsMargins(16, 10, 16, 10)
        cl.addWidget(self._light_block())
        dock.addWidget(c, 2)
        c, cl = card()
        cl.setContentsMargins(16, 10, 16, 10)
        cl.addWidget(self._z_row())
        dock.addWidget(c, 3)
        self.primary.setMinimumHeight(60)
        dock.addWidget(self.primary, 2)
        dock.addWidget(self.export_btn, 1)
        dock.addWidget(self.new_btn, 1)
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
        self.primary.setEnabled(not self.busy)
        self.export_btn.setEnabled(self.result is not None and not self.busy)
        for z, b in self.z_buttons:
            b.setEnabled(not self.busy)
        self.home_btn.setEnabled(not self.busy)
        r = self.result
        e = self.t("empty_value")
        self.val["length"].setText(f"{r['length']:.1f}" if r else e)
        self.val["width"].setText(f"{r['width']:.1f}" if r else e)
        self.val["height"].setText(f"{self.height:.1f}" if self.height is not None else e)
        if self.main.camera.demo is not None:
            self.main.camera.demo.mode = "plate" if self.step == 2 else "item"

    def show_message(self, text, error=False):
        self.message.setText(text)
        self.message.setObjectName("MessageError" if error else "Message")
        repolish(self.message)
        self.message.setVisible(bool(text))

    def reset(self):
        self.step, self.frames, self.base_map, self.result, self.height = 1, None, None, None, None
        self.view.contour = None
        self.show_message("")
        self.refresh()

    # ---------- live view ----------
    def on_preview(self, qimage):
        self.view.set_frame(qimage)
        self.view.markers = self.main.live_markers
        if self.result is not None and self.main.full_width:
            s = PREVIEW_WIDTH / float(self.main.full_width)
            self.view.contour = (self.result["contour_px"] * s).tolist()

    # ---------- actions ----------
    def _calib(self):
        size = self.main.camera.frame_size()
        return self.main.calib_store.get(self.s.get("z_preset_mm"), size)

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
        z = float(s.get("z_preset_mm"))

        def job():
            level = int(s.get("led_brightness"))
            main.set_led(level)
            on = cam.wait_new_frames(4)
            off = None
            if s.get("remove_ambient"):
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
        z = float(s.get("z_preset_mm"))
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

    def on_z(self, z):
        for zz, b in self.z_buttons:
            b.setChecked(zz == z)
        esp, s, store, cam = self.main.esp, self.s, self.main.calib_store, self.main.camera

        def job():
            esp.move_to(z)
            c = store.get(z, cam.frame_size())
            if c and c.get("focus") is not None:
                cam.set_focus(c["focus"])
            return True

        def done(_):
            s.set("z_preset_mm", int(z))
            self._set_busy(False)
            self.reset()

        self._set_busy(True)
        run_task(job, done, self._fail)

    def on_home(self):
        esp = self.main.esp
        self._set_busy(True)
        run_task(esp.home, lambda _: self._set_busy(False), self._fail)
