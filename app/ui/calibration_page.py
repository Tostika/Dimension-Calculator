"""Calibration tab: lens per camera height, base markers, height card, accuracy check."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ..vision import measure
from ..vision.calibration import FRAMES_NEEDED, CalibrationSession
from ..vision.markers import BASE_IDS
from .common import button, card, label, repolish, run_task

BANK_CARD = (85.60, 53.98)


class CalibrationPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.setObjectName("Page")
        self.main, self.t, self.s, self.p = main, main.t, main.settings, main.palette
        self.session = None
        self.session_z = None

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)
        grid.addWidget(self._lens_card(), 0, 0)
        grid.addWidget(self._base_card(), 0, 1)
        grid.addWidget(self._plate_card(), 1, 0)
        grid.addWidget(self._accuracy_card(), 1, 1)
        grid.setRowStretch(2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_chips)
        self.timer.start(400)

    # ---------- 1. lens ----------
    def _lens_card(self):
        c, lay = card(self.t("cal1"))
        lay.addWidget(label(self.t("cal1_desc"), "Muted", wrap=True))
        self.lens_rows = QVBoxLayout()
        self.lens_rows.setSpacing(0)
        lay.addLayout(self.lens_rows)
        self.session_box = QFrame()
        self.session_box.setObjectName("Inset")
        sl = QVBoxLayout(self.session_box)
        sl.setContentsMargins(12, 12, 12, 12)
        self.session_title = label("", wrap=True)
        self.session_title.setStyleSheet("font-weight: 600;")
        sl.addWidget(self.session_title)
        row = QHBoxLayout()
        self.add_btn = button("", "Primary", self.on_add_frame)
        self.finish_btn = button(self.t("finish"), on_click=self.on_finish)
        row.addWidget(self.add_btn, 2)
        row.addWidget(self.finish_btn, 1)
        row.addWidget(button(self.t("cancel"), on_click=self.on_cancel), 1)
        sl.addLayout(row)
        self.session_box.hide()
        lay.addWidget(self.session_box)
        self.lens_msg = label("", "Message", wrap=True)
        lay.addWidget(self.lens_msg)
        lay.addStretch(1)
        self.fill_lens_rows()
        return c

    def fill_lens_rows(self):
        while self.lens_rows.count():
            w = self.lens_rows.takeAt(0).widget()
            if w:
                w.deleteLater()
        size = self.main.camera.frame_size()
        for z in self.s.get("z_presets_mm"):
            calib = self.main.calib_store.get(z, size)
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 10, 0, 10)
            rl.addWidget(label(f"{z / 10:g} {self.t('cm')}"), 1)
            st = label(self.t("calibrated") + f" ({calib['rms']:.2f} px)" if calib else self.t("not_yet"),
                       "Ok" if calib else "Muted")
            rl.addWidget(st, 2)
            b = button(self.t("redo") if calib else self.t("start"), on_click=lambda _=False, zz=z: self.on_start(zz))
            b.setEnabled(self.session is None)
            rl.addWidget(b)
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setStyleSheet(f"color: {self.p['border']};")
            self.lens_rows.addWidget(line)
            self.lens_rows.addWidget(row)

    def _lens_message(self, text, error=False):
        self.lens_msg.setText(text)
        self.lens_msg.setObjectName("MessageError" if error else "Message")
        repolish(self.lens_msg)

    def on_start(self, z):
        esp, cam = self.main.esp, self.main.camera
        self._lens_message("")

        def job():
            esp.move_to(z)
            return cam.autofocus_then_lock()

        def done(focus):
            self.s.set("z_preset_mm", int(z))
            self.session, self.session_z, self.session_focus = CalibrationSession(), z, focus
            self.session_box.show()
            self.session_title.setText(f"{z / 10:g} {self.t('cm')}")
            self._update_session()
            self.fill_lens_rows()

        run_task(job, done, lambda e: self._lens_message(str(e), True))

    def _update_session(self):
        n = self.session.count if self.session else 0
        self.add_btn.setText(self.t("take_photo", n=n))
        self.finish_btn.setEnabled(n >= 10)

    def on_add_frame(self):
        frame, _ = self.main.camera.latest()
        if frame is None or self.session is None:
            return
        self.add_btn.setEnabled(False)
        sess = self.session

        def done(ok):
            self.add_btn.setEnabled(True)
            self._lens_message("" if ok else self.t("board_not_found"), not ok)
            self._update_session()

        run_task(lambda: sess.add(frame), done, lambda e: self._lens_message(str(e), True))

    def on_finish(self):
        sess, z, focus = self.session, self.session_z, getattr(self, "session_focus", None)
        if not sess:
            return
        self.add_btn.setEnabled(False)
        self.finish_btn.setEnabled(False)

        def job():
            calib = sess.solve()
            calib["focus"] = focus
            self.main.calib_store.put(z, calib)
            return calib

        def done(calib):
            self.on_cancel()
            self._lens_message(self.t("cal_done", err=f"{calib['rms']:.2f}"))

        run_task(job, done, lambda e: self._lens_message(str(e), True))

    def on_cancel(self):
        self.session = None
        self.session_box.hide()
        self.add_btn.setEnabled(True)
        self.fill_lens_rows()

    # ---------- 2. base ----------
    def _base_card(self):
        c, lay = card(self.t("cal2"))
        lay.addWidget(label(self.t("cal2_desc"), "Muted", wrap=True))
        chips = QHBoxLayout()
        self.chips = {}
        for i in BASE_IDS:
            ch = label(f"ID {i}", "ChipOff")
            chips.addWidget(ch)
            self.chips[i] = ch
        chips.addStretch(1)
        lay.addLayout(chips)
        lay.addWidget(label(self.t("marker_size")))
        self.marker_spin = QDoubleSpinBox()
        self.marker_spin.setRange(5, 200)
        self.marker_spin.setDecimals(1)
        self.marker_spin.setValue(float(self.s.get("marker_size_mm")))
        self.marker_spin.valueChanged.connect(lambda v: self.s.set("marker_size_mm", float(v)))
        lay.addWidget(self.marker_spin)
        lay.addWidget(button(self.t("check_base"), on_click=self.on_check_base))
        self.base_msg = label("", "Message", wrap=True)
        lay.addWidget(self.base_msg)
        lay.addStretch(1)
        return c

    def update_chips(self):
        found = self.main.live_ids
        for i, ch in self.chips.items():
            on = i in found
            ch.setText(f"ID {i} ✓" if on else f"ID {i}")
            name = "Chip" if on else "ChipOff"
            if ch.objectName() != name:
                ch.setObjectName(name)
                repolish(ch)

    def _msg(self, lab, text, error=False):
        lab.setText(text)
        lab.setObjectName("MessageError" if error else "Message")
        repolish(lab)

    def _err_text(self, e):
        return self.t(e.key, **e.params) if isinstance(e, measure.MeasureError) else str(e)

    def on_check_base(self):
        cam, s, store = self.main.camera, self.s, self.main.calib_store

        def job():
            frame, _ = cam.latest()
            calib = store.get(s.get("z_preset_mm"), cam.frame_size())
            return measure.build_base_map(frame, s, calib)

        run_task(job, lambda bm: self._msg(self.base_msg, self.t("base_ok", mmpx=f"{bm.mm_per_px:.3f}")),
                 lambda e: self._msg(self.base_msg, self._err_text(e), True))

    # ---------- 3. height card ----------
    def _plate_card(self):
        c, lay = card(self.t("cal3"))
        lay.addWidget(label(self.t("cal3_desc"), "Muted", wrap=True))
        lay.addWidget(label(self.t("card_thickness")))
        self.plate_spin = QDoubleSpinBox()
        self.plate_spin.setRange(0, 20)
        self.plate_spin.setDecimals(2)
        self.plate_spin.setSingleStep(0.1)
        self.plate_spin.setValue(float(self.s.get("plate_thickness_mm")))
        self.plate_spin.valueChanged.connect(lambda v: self.s.set("plate_thickness_mm", float(v)))
        lay.addWidget(self.plate_spin)
        lay.addWidget(button(self.t("zero_check"), on_click=self.on_zero))
        self.plate_msg = label("", "Message", wrap=True)
        lay.addWidget(self.plate_msg)
        lay.addStretch(1)
        return c

    def _demo_mode(self, mode):
        if self.main.camera.demo is not None:
            self.main.camera.demo.mode = mode

    def on_zero(self):
        cam, s, store = self.main.camera, self.s, self.main.calib_store
        self._demo_mode("plate_empty")

        def job():
            frame = cam.wait_new_frames(3)
            calib = store.get(s.get("z_preset_mm"), cam.frame_size())
            bm = measure.build_base_map(frame, s, calib)
            return measure.measure_height(frame, bm, s, float(s.get("z_preset_mm")), clamp=False)

        def done(h):
            self._demo_mode("item")
            self._msg(self.plate_msg, self.t("zero_result", h=f"{h:.2f}"))

        def fail(e):
            self._demo_mode("item")
            self._msg(self.plate_msg, self._err_text(e), True)

        run_task(job, done, fail)

    # ---------- 4. accuracy ----------
    def _accuracy_card(self):
        c, lay = card(self.t("cal4"))
        lay.addWidget(label(self.t("cal4_desc"), "Muted", wrap=True))
        box = QFrame()
        box.setObjectName("Inset")
        g = QGridLayout(box)
        g.setContentsMargins(12, 12, 12, 12)
        g.addWidget(label(self.t("expected"), "Hint"), 0, 0)
        g.addWidget(label(self.t("measured"), "Hint"), 0, 1)
        exp = label(f"{BANK_CARD[0]:.2f} × {BANK_CARD[1]:.2f}")
        exp.setStyleSheet("font-family: Consolas, monospace; font-weight: 600;")
        g.addWidget(exp, 1, 0)
        self.acc_value = label(self.t("not_run"), "Muted")
        g.addWidget(self.acc_value, 1, 1)
        lay.addWidget(box)
        lay.addWidget(button(self.t("run_check"), "Primary", self.on_accuracy))
        self.acc_msg = label("", "Message", wrap=True)
        lay.addWidget(self.acc_msg)
        lay.addStretch(1)
        return c

    def on_accuracy(self):
        cam, s, store = self.main.camera, self.s, self.main.calib_store
        self._demo_mode("card")

        def job():
            frame = cam.wait_new_frames(3)
            calib = store.get(s.get("z_preset_mm"), cam.frame_size())
            bm = measure.build_base_map(frame, s, calib)
            return measure.measure_outline(frame, None, bm, 0.8, float(s.get("z_preset_mm")))

        def done(r):
            self._demo_mode("item")
            dl, dw = r["length"] - BANK_CARD[0], r["width"] - BANK_CARD[1]
            self.acc_value.setText(f"{r['length']:.2f} × {r['width']:.2f}  ({dl:+.2f} / {dw:+.2f})")
            self.acc_value.setObjectName("Ok" if max(abs(dl), abs(dw)) <= 0.5 else "Bad")
            repolish(self.acc_value)
            self._msg(self.acc_msg, "")

        def fail(e):
            self._demo_mode("item")
            self._msg(self.acc_msg, self._err_text(e), True)

        run_task(job, done, fail)
