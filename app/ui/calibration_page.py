"""Calibration tab: lens (once), base markers, height card."""
import time

import cv2
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ..config import BASE_SHEETS, DEFAULTS
from ..vision import measure
from ..vision.calibration import BOARD_INNER, CalibrationSession, focal_from_base
from ..vision.markers import BASE_IDS, detect, learn_layout
from .common import CameraView, button, card, label, repolish, run_task


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
        main.preview_ready.connect(self.on_preview)
        self._board_busy = False
        self.board_timer = QTimer(self)
        self.board_timer.timeout.connect(self.look_for_board)
        self.board_timer.start(300)
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
        # live view: green dots = checkerboard corners found now, faint frames = boards already added
        self.cal_view = CameraView(self.p, self.p["rs"], min_height=230)
        self.cal_view.offline_title = self.t("no_camera")
        self.cal_view.offline_hint = self.t("no_camera_hint")
        sl.addWidget(self.cal_view, 1)
        self.cover_hint = label("", "Hint", wrap=True)
        sl.addWidget(self.cover_hint)
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

        s = self.s

        def job():
            focus = cam.autofocus_then_lock()
            frame = cam.wait_new_frames(3)
            try:
                bm = measure.build_base_map(frame, s, None)
            except measure.MeasureError:
                raise measure.MeasureError("err_cal_need_base")
            return focus, focal_from_base(bm, cam.frame_size(), s.camera_height_mm())

        def done(r):
            focus, f_px = r
            self.session, self.session_focus = CalibrationSession(f_px), focus
            self._last_auto = 0.0
            self.session_box.show()
            self.session_title.setText(f"{self.t('camera_height')}: {self.s.get('camera_height_cm')} {self.t('cm')}")
            self._update_session()
            self.fill_lens_rows()

        run_task(job, done, lambda e: self._lens_message(self._err_text(e), True))

    def on_preview(self, qimage):
        if self.session is not None and self.main.camera_ok:
            self.cal_view.set_frame(qimage)

    def look_for_board(self):
        """Finds the checkerboard in the preview a few times a second, in the background."""
        if self.session is None or self._board_busy or not self.main.camera_ok:
            return
        f = self.main._last_preview
        if f is None:
            return
        self._board_busy = True
        gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)

        def job():
            flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE + cv2.CALIB_CB_FAST_CHECK
            ok, corners = cv2.findChessboardCorners(gray, BOARD_INNER, flags)
            return corners.reshape(-1, 2).tolist() if ok else []

        def done(pts):
            self._board_busy = False
            if pts and time.time() - getattr(self, "_last_auto", 0.0) > 1.2:
                self._auto_add()
            self.cal_view.dots = pts
            self.cal_view.right_badge = self.t("board_found") if pts else self.t("board_searching")
            self.cal_view.update()

        def fail(_):
            self._board_busy = False

        run_task(job, done, fail)

    def _ghosts(self):
        """Outlines of the boards already added, scaled to the preview (shows which areas are covered)."""
        size = self.main.camera.frame_size()
        f = self.main._last_preview
        if not self.session or not size or f is None:
            return []
        sc = f.shape[1] / float(size[0])
        cols, rows = BOARD_INNER
        out = []
        for c in self.session.img_points:
            c = c.reshape(-1, 2) * sc
            out.append([c[0].tolist(), c[cols - 1].tolist(), c[-1].tolist(), c[-cols].tolist()])
        return out

    def _update_session(self):
        n = self.session.count if self.session else 0
        self.add_btn.setText(self.t("take_photo", n=n))
        missing = self.session.missing_corners() if self.session else []
        self.finish_btn.setEnabled(n >= 10 and not missing)
        if missing:
            where = ", ".join(self.t("corner_" + k) for k in missing)
            self.cover_hint.setText(self.t("cal_missing", where=where))
        else:
            self.cover_hint.setText(self.t("cal_corners_ok") if n < 10 else self.t("cal_ready"))
        self.cal_view.ghosts = self._ghosts()
        self.cal_view.update()

    def _auto_add(self):
        """Adds the current full frame by itself when the board lies somewhere new."""
        frame, _ = self.main.camera.latest()
        sess = self.session
        if frame is None or sess is None or getattr(self, "_adding", False):
            return
        self._adding = True
        self._last_auto = time.time()

        def done(ok):
            self._adding = False
            if ok:
                self._update_session()

        def fail(_):
            self._adding = False

        run_task(lambda: sess.add(frame, only_new=True), done, fail)

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

        cam, s = self.main.camera, self.s

        def job():
            calib = sess.solve()
            calib["focus"] = focus
            # check against the base: with the new correction the four markers must fit their
            # layout at least as well as without it
            frame = cam.wait_new_frames(2)
            try:
                raw = measure.build_base_map(frame, s, None)
            except measure.MeasureError:
                raw = None                    # base markers hidden under the board: nothing to compare with
            if raw is not None:
                try:
                    new = measure.build_base_map(frame, s, calib)
                except measure.MeasureError:
                    raise measure.MeasureError("err_cal_worse")
                if new.layout_error_mm > max(raw.layout_error_mm, 0.3) * 1.5:
                    raise measure.MeasureError("err_cal_worse")
            self.main.calib_store.set_lens(calib)
            self.s.set("plate_zero_scale", None)          # the zero check depends on the lens correction
            return calib

        def done(calib):
            if calib.get("focus") is not None:          # keep this focus from now on
                self.s.set("focus_value", float(calib["focus"]))
                self.s.set("lock_focus", True)
            self.on_cancel()
            self._lens_message(self.t("cal_done", err=f"{calib['rms']:.2f}"))

        def fail(e):
            self.add_btn.setEnabled(True)
            self._update_session()
            self._lens_message(self._err_text(e), True)

        run_task(job, done, fail)

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
        lay.addWidget(label(self.t("learn_layout_hint"), "Hint", wrap=True))
        self.learn_btn = button(self.t("learn_layout"), "Primary", self.on_learn_layout)
        lay.addWidget(self.learn_btn)
        self.layout_label = label("", "Muted", wrap=True)
        lay.addWidget(self.layout_label)
        lay.addWidget(button(self.t("use_sheet_layout"), on_click=self.on_sheet_layout))
        self.show_layout()
        # how the printed sheet really came out: two long distances from a tape measure
        lay.addWidget(label(self.t("print_size_title"), "Muted", wrap=True))
        self.span_label_x = label("", wrap=True)
        lay.addWidget(self.span_label_x)
        self.span_x = QDoubleSpinBox()
        self.span_y = QDoubleSpinBox()
        for sp in (self.span_x, self.span_y):
            sp.setRange(50, 600)
            sp.setDecimals(1)
            sp.setSingleStep(0.5)
        lay.addWidget(self.span_x)
        self.span_label_y = label("", wrap=True)
        lay.addWidget(self.span_label_y)
        lay.addWidget(self.span_y)
        lay.addWidget(button(self.t("print_size_save"), on_click=self.on_print_size))
        self.fill_print_size()
        lay.addWidget(button(self.t("check_base"), on_click=self.on_check_base))
        self.base_msg = label("", "Message", wrap=True)
        lay.addWidget(self.base_msg)
        lay.addStretch(1)
        return c

    def show_layout(self):
        c = self.s.get("base_marker_centers_mm")
        a = float(np.hypot(c["1"][0] - c["0"][0], c["1"][1] - c["0"][1]))
        b = float(np.hypot(c["2"][0] - c["0"][0], c["2"][1] - c["0"][1]))
        self.layout_label.setText(self.t("layout_now", a=f"{a:.1f}", b=f"{b:.1f}"))

    def _sheet_nominal(self):
        """Outer edge to outer edge, marker 0 to 1 and marker 0 to 2, on the sheet as designed."""
        sh = BASE_SHEETS[self.s.get("base_sheet")]
        c, m = sh["base_marker_centers_mm"], sh["marker_size_mm"]
        return abs(c["1"][0] - c["0"][0]) + m, abs(c["2"][1] - c["0"][1]) + m

    def fill_print_size(self):
        sheet = self.s.get("base_sheet")
        ok = sheet in BASE_SHEETS
        for w in (self.span_x, self.span_y):
            w.setEnabled(ok)
        if not ok:
            self.span_label_x.setText(self.t("print_size_custom"))
            self.span_label_y.setText("")
            return
        nx, ny = self._sheet_nominal()
        sx, sy = (self.s.get("sheet_scale") or {}).get(sheet, [1.0, 1.0])
        self.span_label_x.setText(self.t("print_size_x", n=f"{nx:.0f}"))
        self.span_label_y.setText(self.t("print_size_y", n=f"{ny:.0f}"))
        self.span_x.setValue(nx * sx)
        self.span_y.setValue(ny * sy)

    def on_print_size(self):
        sheet = self.s.get("base_sheet")
        if sheet not in BASE_SHEETS:
            return
        nx, ny = self._sheet_nominal()
        sx, sy = self.span_x.value() / nx, self.span_y.value() / ny
        if not (0.9 < sx < 1.1 and 0.9 < sy < 1.1):
            self._msg(self.base_msg, self.t("err_print_size"), True)
            return
        scales = dict(self.s.get("sheet_scale") or {})
        scales[sheet] = [sx, sy]
        self.s.data["sheet_scale"] = scales
        self.s.use_sheet(sheet)
        self.s.set("plate_zero_scale", None)          # the zero check depends on the base scale
        self.marker_spin.setValue(float(self.s.get("marker_size_mm")))
        self.show_layout()
        self._msg(self.base_msg, self.t("print_size_saved", x=f"{(sx - 1) * 100:+.1f}", y=f"{(sy - 1) * 100:+.1f}"))

    def on_sheet_layout(self):
        self.s.use_sheet_layout()
        self.marker_spin.setValue(float(self.s.get("marker_size_mm")))
        self.show_layout()
        self.fill_print_size()
        self._msg(self.base_msg, "")

    def on_learn_layout(self):
        cam, s, store = self.main.camera, self.s, self.main.calib_store
        size = float(s.get("marker_size_mm"))
        self.learn_btn.setEnabled(False)

        def job():
            calib = store.lens(cam.frame_size())
            dets = []
            for _ in range(15):                      # about half a second of frames, averaged
                f = cam.wait_new_frames(1)
                if f is not None:
                    dets.append(detect(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)))
            return learn_layout(dets, size, calib)

        def done(r):
            centers, spread = r
            self.learn_btn.setEnabled(True)
            if spread > 1.0:
                self._msg(self.base_msg, self.t("err_layout_unsteady"), True)
                return
            s.set("base_marker_centers_mm", centers)
            s.set("base_sheet", "custom")
            s.set("plate_zero_scale", None)
            self.show_layout()
            self._msg(self.base_msg, "")

        def fail(e):
            self.learn_btn.setEnabled(True)
            self._msg(self.base_msg, self.t("err_no_markers") if isinstance(e, LookupError) else self._err_text(e), True)

        run_task(job, done, fail)

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
        lay.addWidget(label(self.t("card_marker_size")))
        self.plate_marker_spin = QDoubleSpinBox()
        self.plate_marker_spin.setRange(10, 60)
        self.plate_marker_spin.setDecimals(1)
        self.plate_marker_spin.setSingleStep(0.1)
        self.plate_marker_spin.setValue(float(self.s.get("plate_marker_size_mm")))
        self.plate_marker_spin.valueChanged.connect(self.on_plate_marker_size)
        lay.addWidget(self.plate_marker_spin)
        lay.addWidget(label(self.t("card_marker_hint"), "Hint", wrap=True))
        lay.addWidget(button(self.t("zero_check"), on_click=self.on_zero))
        self.plate_msg = label("", "Message", wrap=True)
        lay.addWidget(self.plate_msg)
        lay.addStretch(1)
        return c

    def on_plate_marker_size(self, v):
        """A card printed off size: everything on it scales with the marker the user measured."""
        f = float(v) / float(DEFAULTS["plate_marker_size_mm"])
        self.s.data["plate_marker_size_mm"] = float(v)
        self.s.set("plate_marker_centers_mm",
                   {k: [c[0] * f, c[1] * f] for k, c in DEFAULTS["plate_marker_centers_mm"].items()})

    def on_zero(self):
        cam, s, store = self.main.camera, self.s, self.main.calib_store

        def job():
            frame = cam.wait_new_frames(3)
            bm = measure.build_base_map(frame, s, store.lens(cam.frame_size()))
            old = s.get("plate_zero_scale")
            s.data["plate_zero_scale"] = None
            before = measure.measure_height(frame, bm, s, s.camera_height_mm(), clamp=False)
            c = measure.zero_scale(frame, bm, s, s.camera_height_mm())
            if not 0.9 < c < 1.1:
                s.data["plate_zero_scale"] = old
                raise measure.MeasureError("err_zero_scale", pct=f"{(c - 1) * 100:+.1f}")
            s.set("plate_zero_scale", c)
            return before, c

        def done(r):
            before, c = r
            msg = self.t("zero_saved", h=f"{before:.1f}")
            if abs(c - 1) > 0.02:
                msg += " " + self.t("zero_off_size", pct=f"{(c - 1) * 100:+.1f}")
            self._msg(self.plate_msg, msg)

        def fail(e):
            self._msg(self.plate_msg, self._err_text(e), True)

        run_task(job, done, fail)
