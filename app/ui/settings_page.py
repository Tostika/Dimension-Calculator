"""Settings tab: appearance (themes, own colours, layout, corners), language, camera, ESP32, saving."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .. import theme
from ..devices.esp32 import list_ports
from .common import button, card, label, run_task


class ThemeButton(QPushButton):
    """A theme preset drawn in its own colours, with a ring when chosen."""

    def __init__(self, name, colors, ring, chosen, radius):
        super().__init__()
        self.name, self.c, self.ring, self.radius = name, colors, QColor(ring), radius
        self.setCheckable(True)
        self.setChecked(chosen)
        self.setMinimumSize(150, 84)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("border: 0; background: transparent;")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(QPen(self.ring if self.isChecked() else QColor(theme.mix(self.c["surface"], self.c["text"], 0.2)),
                      2.5 if self.isChecked() else 1))
        p.setBrush(QColor(self.c["bg"]))
        p.drawRoundedRect(r, self.radius, self.radius)
        x = r.x() + 12
        for key in ("surface", "accent", "text"):
            p.setPen(QPen(QColor(theme.mix(self.c["surface"], self.c["text"], 0.2)), 1))
            p.setBrush(QColor(self.c[key]))
            p.drawRoundedRect(QRectF(x, r.y() + 12, 22, 22), 6, 6)
            x += 28
        p.setPen(QColor(self.c["text"]))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(r.x() + 12, r.y() + 40, r.width() - 20, r.height() - 44),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, self.name)


def layout_icon(kind, p):
    pix = QPixmap(120, 70)
    pix.fill(QColor(0, 0, 0, 0))
    g = QPainter(pix)
    g.setRenderHint(QPainter.RenderHint.Antialiasing)
    g.setPen(Qt.PenStyle.NoPen)
    border, surface, accent = QColor(p["border"]), QColor(p["surface"]), QColor(p["accent"])
    if kind == "side":
        g.setBrush(border)
        g.drawRoundedRect(QRectF(2, 2, 76, 66), 4, 4)
        g.setBrush(surface)
        g.setPen(QPen(border, 1))
        g.drawRoundedRect(QRectF(82, 2, 36, 20), 3, 3)
        g.drawRoundedRect(QRectF(82, 25, 36, 20), 3, 3)
        g.setPen(Qt.PenStyle.NoPen)
        g.setBrush(accent)
        g.drawRoundedRect(QRectF(82, 48, 36, 20), 3, 3)
    else:
        g.setBrush(border)
        g.drawRoundedRect(QRectF(2, 2, 116, 48), 4, 4)
        g.setBrush(surface)
        g.setPen(QPen(border, 1))
        g.drawRoundedRect(QRectF(2, 54, 54, 14), 3, 3)
        g.setPen(Qt.PenStyle.NoPen)
        g.setBrush(accent)
        g.drawRoundedRect(QRectF(60, 54, 58, 14), 3, 3)
    g.end()
    return QIcon(pix)


class SettingsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.setObjectName("Page")
        self.main, self.t, self.s, self.p = main, main.t, main.settings, main.palette

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        lay.addWidget(self._appearance(), 3, Qt.AlignmentFlag.AlignTop)
        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(self._language())
        right.addWidget(self._camera())
        right.addWidget(self._esp())
        right.addWidget(self._saving())
        right.addStretch(1)
        rw = QWidget()
        rw.setLayout(right)
        rw.setMinimumWidth(320)
        rw.setMaximumWidth(460)
        lay.addWidget(rw, 2)

    # ---------- appearance ----------
    def _appearance(self):
        c, lay = card(spacing=16)
        head = QHBoxLayout()
        t = label(self.t("appearance"), "CardTitle")
        t.setStyleSheet("font-size: 18px;")
        head.addWidget(t)
        head.addStretch(1)
        head.addWidget(button(self.t("reset_default"), on_click=self.on_reset))
        lay.addLayout(head)

        lay.addWidget(label(self.t("theme"), "SectionTitle"))
        grid = QGridLayout()
        grid.setSpacing(10)
        is_custom = self.s.get("theme") == "custom"
        for n, pid in enumerate(theme.PRESET_ORDER):
            b = ThemeButton(self.t("theme_" + pid), theme.PRESETS[pid], self.p["accent"],
                            not is_custom and self.s.get("theme") == pid, self.p["r"])
            b.clicked.connect(lambda _=False, x=pid: self.on_preset(x))
            grid.addWidget(b, n // 3, n % 3)
        lay.addLayout(grid)

        title = self.t("own_colours") + ("  " + self.t("custom_in_use") if is_custom else "")
        lay.addWidget(label(title, "SectionTitle"))
        cg = QGridLayout()
        cg.setSpacing(10)
        current = theme.base_colors(self.s)
        for n, (key, name) in enumerate((("bg", "c_bg"), ("surface", "c_surface"), ("text", "c_text"), ("accent", "c_accent"))):
            f = QFrame()
            f.setObjectName("Inset")
            fl = QHBoxLayout(f)
            fl.setContentsMargins(10, 8, 10, 8)
            sw = QPushButton()
            sw.setFixedSize(44, 44)
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setToolTip(self.t("pick_colour"))
            sw.setStyleSheet(f"background: {current[key]}; border: 1px solid {self.p['border']}; border-radius: 8px;")
            sw.clicked.connect(lambda _=False, k=key: self.on_pick(k))
            fl.addWidget(sw)
            col = QVBoxLayout()
            col.setSpacing(0)
            nm = label(self.t(name))
            nm.setStyleSheet("font-weight: 600;")
            col.addWidget(nm)
            col.addWidget(label(current[key].upper(), "Mono"))
            fl.addLayout(col)
            fl.addStretch(1)
            cg.addWidget(f, n // 2, n % 2)
        lay.addLayout(cg)

        box = QFrame()
        box.setObjectName("Inset")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.setSpacing(6)
        h = label(self.t("readability"))
        h.setStyleSheet("font-weight: 600;")
        bl.addWidget(h)
        for key, ratio, ok in theme.readability(self.p):
            row = QHBoxLayout()
            row.addWidget(label(self.t(key), "Muted"))
            row.addStretch(1)
            row.addWidget(label(f"{ratio:.1f}:1  {self.t('reads_well') if ok else self.t('reads_badly')}", "Ok" if ok else "Bad"))
            bl.addLayout(row)
        lay.addWidget(box)

        bottom = QHBoxLayout()
        bottom.setSpacing(18)
        left = QVBoxLayout()
        left.addWidget(label(self.t("scan_layout"), "SectionTitle"))
        opts = QHBoxLayout()
        for kind, key in (("side", "layout_side"), ("wide", "layout_wide")):
            b = button(self.t(key), "Option", checkable=True)
            b.setIcon(layout_icon(kind, self.p))
            b.setIconSize(QSize(96, 56))
            b.setMinimumHeight(80)
            b.setChecked(self.s.get("scan_layout") == kind)
            b.clicked.connect(lambda _=False, k=kind: self.on_setting("scan_layout", k))
            opts.addWidget(b)
        left.addLayout(opts)
        bottom.addLayout(left, 2)
        right = QVBoxLayout()
        right.addWidget(label(self.t("corners"), "SectionTitle"))
        for kind, key in (("round", "rounded"), ("sharp", "sharp")):
            b = button(self.t(key), "Option", checkable=True)
            b.setChecked(self.s.get("corners") == kind)
            b.clicked.connect(lambda _=False, k=kind: self.on_setting("corners", k))
            right.addWidget(b)
        bottom.addLayout(right, 1)
        lay.addLayout(bottom)
        return c

    def on_preset(self, pid):
        self.s.set("theme", pid)
        self.main.appearance_changed()

    def on_pick(self, key):
        current = theme.base_colors(self.s)
        col = QColorDialog.getColor(QColor(current[key]), self, self.t("pick_colour"))
        if not col.isValid():
            return
        current[key] = col.name().upper()
        self.s.set("custom_colors", current, save=False)
        self.s.set("theme", "custom")
        self.main.appearance_changed()

    def on_setting(self, key, value):
        self.s.set(key, value)
        self.main.appearance_changed()

    def on_reset(self):
        self.s.reset_appearance()
        self.main.appearance_changed()

    # ---------- language ----------
    def _language(self):
        c, lay = card(self.t("language"))
        lay.addWidget(label(self.t("language_desc"), "Muted", wrap=True))
        row = QHBoxLayout()
        for code, name in (("ka", "ქართული"), ("en", "English")):
            b = button(name, "Toggle", checkable=True)
            b.setMinimumHeight(48)
            b.setChecked(self.s.get("language") == code)
            b.clicked.connect(lambda _=False, x=code: self.main.set_language(x))
            row.addWidget(b)
        lay.addLayout(row)
        return c

    # ---------- camera ----------
    def _camera(self):
        c, lay = card(self.t("camera"))
        lay.addWidget(label(self.t("camera_number")))
        idx = QSpinBox()
        idx.setRange(0, 9)
        idx.setValue(int(self.s.get("camera_index")))
        idx.valueChanged.connect(lambda v: self._camera_setting("camera_index", int(v)))
        lay.addWidget(idx)
        lay.addWidget(label(self.t("resolution")))
        res = QComboBox()
        for key, text in (("4k", "3840 × 2160 (4K)"), ("1440", "2560 × 1440"), ("1080", "1920 × 1080")):
            res.addItem(text, key)
        res.setCurrentIndex(max(0, res.findData(self.s.get("resolution"))))
        res.currentIndexChanged.connect(lambda _: self._camera_setting("resolution", res.currentData()))
        lay.addWidget(res)
        for key, text in (("lock_focus", "lock_focus"), ("lock_exposure", "lock_exposure")):
            cb = QCheckBox(self.t(text))
            cb.setChecked(bool(self.s.get(key)))
            cb.toggled.connect(lambda v, k=key: self._camera_setting(k, bool(v)))
            lay.addWidget(cb)
        demo = QCheckBox(self.t("demo_camera_setting"))
        demo.setChecked(bool(self.s.get("demo_camera")))
        demo.toggled.connect(lambda v: self.s.set("demo_camera", bool(v)))   # the camera thread picks it up live
        lay.addWidget(demo)
        return c

    def _camera_setting(self, key, value):
        self.s.set(key, value)
        self.main.restart_camera()

    # ---------- ESP32 ----------
    def _esp(self):
        c, lay = card("ESP32")
        lay.addWidget(label(self.t("port")))
        row = QHBoxLayout()
        self.port_box = QComboBox()
        self.fill_ports()
        row.addWidget(self.port_box, 1)
        row.addWidget(button(self.t("refresh"), on_click=self.fill_ports))
        lay.addLayout(row)
        lay.addWidget(button(self.t("reconnect"), "Primary", self.on_connect))
        row2 = QHBoxLayout()
        row2.addWidget(button(self.t("test_leds"), on_click=self.on_test_leds))
        row2.addWidget(button(self.t("home_camera"), on_click=lambda: run_task(self.main.esp.home)))
        lay.addLayout(row2)
        self.esp_msg = label("", "Message", wrap=True)
        lay.addWidget(self.esp_msg)
        self.update_esp_msg()
        return c

    def fill_ports(self):
        self.port_box.clear()
        self.port_box.addItem("Auto", "")
        for dev, desc in list_ports():
            self.port_box.addItem(f"{dev}  ({desc})", dev)
        self.port_box.setCurrentIndex(max(0, self.port_box.findData(self.s.get("serial_port"))))

    def update_esp_msg(self):
        esp = self.main.esp
        self.esp_msg.setText(f"ESP32 {esp.port}: {self.t('connected')}" if esp.connected else f"ESP32: {self.t('not_connected')}")

    def on_connect(self):
        port = self.port_box.currentData() or ""
        self.s.set("serial_port", port)
        esp = self.main.esp
        run_task(lambda: esp.connect(port or None), lambda ok: (self.update_esp_msg(), self.main.update_status()))

    def on_test_leds(self):
        main, level = self.main, int(self.s.get("led_brightness"))

        def job():
            import time
            for v in (0, 100, 0, 100, level):
                main.set_led(v)
                time.sleep(0.4)
        run_task(job)

    # ---------- saving ----------
    def _saving(self):
        c, lay = card(self.t("saving"))
        lay.addWidget(label(self.t("export_folder")))
        row = QHBoxLayout()
        self.folder = QLineEdit(self.s.get("export_folder"))
        self.folder.setReadOnly(True)
        row.addWidget(self.folder, 1)
        row.addWidget(button(self.t("choose"), on_click=self.on_choose_folder))
        lay.addLayout(row)
        cb = QCheckBox(self.t("save_json"))
        cb.setChecked(bool(self.s.get("save_json")))
        cb.toggled.connect(lambda v: self.s.set("save_json", bool(v)))
        lay.addWidget(cb)
        return c

    def on_choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, self.t("export_folder"), self.s.get("export_folder"))
        if path:
            self.s.set("export_folder", path)
            self.folder.setText(path)
