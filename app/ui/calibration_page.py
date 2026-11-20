"""Calibration tab: lens (once), base markers, height card."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ..vision import measure
from ..vision.calibration import CalibrationSession
from ..vision.markers import BASE_IDS
from .common import button, card, label, repolish, run_task


class CalibrationPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.setObjectName("Page")
        self.main, self.t, self.s, self.p = main, main.t, main.settings, main.palette
        self.session = None

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)
        grid.addWidget(self._lens_card(), 0, 0, 2, 1)
        grid.addWidget(self._base_card(), 0, 1)
        grid.addWidget(self._plate_card(), 1, 1)
        grid.setRowStretch(2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        main.camera_changed.connect(self.fill_lens_rows)
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
            item = self.lens_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        calib = self.main.calib_store.lens(self.main.camera.frame_size())
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        rl.addWidget(label(self.t("lens")), 1)
        st = label(self.t("calibrated") + f" ({calib['rms']:.2f} px)" if calib else self.t("not_yet"),
                   "Ok" if calib else "Muted")
        rl.addWidget(st, 2)
        b = button(self.t("redo") if calib else self.t("start"), on_click=self.on_start)
        b.setEnabled(self.session is None and self.main.camera_ok)
        rl.addWidget(b)
        self.lens_rows.addWidget(row)

    def _lens_message(self, text, error=False):
        self.lens_msg.setText(text)
        self.lens_msg.setObjectName("MessageError" if error else "Message")
        repolish(self.lens_msg)

    def on_start(self):
        cam = self.main.camera
        self._lens_message("")

        def job():
            return cam.autofocus_then_lock()

        def done(focus):
            self.session, self.session_focus = CalibrationSession(), focus
            self.session_box.show()
            self.session_title.setText(f"{self.t('camera_height')}: {self.s.get('camera_height_cm')} {self.t('cm')}")
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
        sess, focus = self.session, getattr(self, "session_focus", None)
        if not sess:
            return
        self.add_btn.setEnabled(False)
        self.finish_btn.setEnabled(False)

        def job():
            calib = sess.solve()
            calib["focus"] = focus
            self.main.calib_store.set_lens(calib)
            return calib

        def done(calib):
            if calib.get("focus") is not None:          # keep this focus from now on
                self.s.set("focus_value", float(calib["focus"]))
                self.s.set("lock_focus", True)
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
            return measure.build_base_map(frame, s, store.lens(cam.frame_size()))

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

    def on_zero(self):
        cam, s, store = self.main.camera, self.s, self.main.calib_store

        def job():
            frame = cam.wait_new_frames(3)
            bm = measure.build_base_map(frame, s, store.lens(cam.frame_size()))
            return measure.measure_height(frame, bm, s, s.camera_height_mm(), clamp=False)

        def done(h):
            self._msg(self.plate_msg, self.t("zero_result", h=f"{h:.2f}"))

        def fail(e):
            self._msg(self.plate_msg, self._err_text(e), True)

        run_task(job, done, fail)
