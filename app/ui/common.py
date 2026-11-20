"""Small building blocks shared by all pages."""
import traceback

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

# ---------- background tasks ----------
_alive = set()


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn, signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            result = self.fn()
        except Exception as e:          # handed to the page, which shows a message
            traceback.print_exc()
            self.signals.failed.emit(e)
        else:
            self.signals.done.emit(result)


def run_task(fn, on_done=None, on_error=None):
    """Runs fn() in a background thread; on_done(result) / on_error(exc) run back on the UI thread."""
    sig = _Signals()
    _alive.add(sig)

    def finish(cb, value):
        _alive.discard(sig)
        if cb:
            try:
                cb(value)
            except RuntimeError as e:     # the page was rebuilt (language or theme change) meanwhile
                if "already deleted" not in str(e):
                    raise

    sig.done.connect(lambda r: finish(on_done, r))
    sig.failed.connect(lambda e: finish(on_error, e))
    QThreadPool.globalInstance().start(_Task(fn, sig))


# ---------- widgets ----------
def label(text="", name=None, wrap=False):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    if wrap:
        w.setWordWrap(True)
    return w


class FitButton(QPushButton):
    """A button whose text gets a smaller font when it would not fit, so it is never cut off."""
    BASE_PX = 14
    MIN_PX = 10

    def __init__(self, text=""):
        super().__init__(text)
        self._px = None
        # may be narrower than its text: the font shrinks instead of the window growing
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def minimumSizeHint(self):
        return QSize(48, super().minimumSizeHint().height())

    def setText(self, text):
        super().setText(text)
        self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        avail = self.width() - 20 - (self.iconSize().width() + 6 if not self.icon().isNull() else 0)
        if avail <= 0:
            return
        f = self.font()
        px = self.BASE_PX
        while px > self.MIN_PX:
            f.setPixelSize(px)
            if QFontMetrics(f).horizontalAdvance(self.text()) <= avail:
                break
            px -= 1
        if px != self._px:
            self._px = px
            self.setStyleSheet(f"font-size: {px}px; padding-left: 6px; padding-right: 6px;" if px < self.BASE_PX else "")


def button(text, name=None, on_click=None, checkable=False):
    b = FitButton(text)
    if name:
        b.setObjectName(name)
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        b.clicked.connect(on_click)
    return b


class WrapCheck(QWidget):
    """A checkbox whose text wraps onto more lines instead of being cut off."""

    def __init__(self, text, checked=False, on_toggle=None):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(bool(checked))
        self.text = label(text, wrap=True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.text.setCursor(Qt.CursorShape.PointingHandCursor)
        self.text.mousePressEvent = lambda e: self.checkbox.toggle()
        lay.addWidget(self.checkbox, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.text, 1)
        if on_toggle:
            self.checkbox.toggled.connect(on_toggle)


class Stepper(QFrame):
    """A number with round - and + buttons on both sides (replaces the old Windows spin box)."""

    def __init__(self, value, minimum, maximum, unit="", on_change=None):
        super().__init__()
        self.setObjectName("Stepper")
        self.v, self.lo, self.hi, self.unit, self.on_change = int(value), int(minimum), int(maximum), unit, on_change
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self.minus = QPushButton("\u2212")
        self.plus = QPushButton("+")
        for b in (self.minus, self.plus):
            b.setObjectName("StepBtn")
            b.setFixedSize(36, 36)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setAutoRepeat(True)
        self.value_label = QLabel()
        self.value_label.setObjectName("StepValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.minus)
        lay.addWidget(self.value_label, 1)
        lay.addWidget(self.plus)
        self.minus.clicked.connect(lambda: self.setValue(self.v - 1))
        self.plus.clicked.connect(lambda: self.setValue(self.v + 1))
        self._show()

    def value(self):
        return self.v

    def setValue(self, v):
        v = max(self.lo, min(self.hi, int(v)))
        changed = v != self.v
        self.v = v
        self._show()
        if changed and self.on_change:
            self.on_change(v)

    def _show(self):
        self.value_label.setText(f"{self.v} {self.unit}".strip())
        self.minus.setEnabled(self.isEnabled() and self.v > self.lo)
        self.plus.setEnabled(self.isEnabled() and self.v < self.hi)

    def setEnabled(self, on):
        super().setEnabled(on)
        self._show()


def card(title=None, spacing=12, name="Card"):
    f = QFrame()
    f.setObjectName(name)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 18, 18, 18)
    lay.setSpacing(spacing)
    if title:
        lay.addWidget(label(title, "CardTitle", wrap=True))
    return f, lay


def hbox(*widgets, spacing=8, stretch_last=False):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for x in widgets:
        lay.addWidget(x)
    if stretch_last:
        lay.addStretch(1)
    return w


def repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)


def bgr_to_qimage(frame):
    frame = np.ascontiguousarray(frame)
    h, w = frame.shape[:2]
    return QImage(frame.data, w, h, frame.strides[0], QImage.Format.Format_BGR888).copy()


class CameraView(QWidget):
    """Shows the preview frame (kept in proportion, rounded corners, no black bars) with
    overlays in preview pixels: marker boxes, the measured outline, a LIVE badge, a status
    badge and a message box. With no camera it draws a calm "no camera" panel instead."""

    def __init__(self, palette, radius=12, min_height=300):
        super().__init__()
        self.p = palette
        self.image = None
        self.markers = []
        self.contour = None
        self.badge = ""
        self.right_badge = ""
        self.message = ""
        self.message_error = False
        self.offline_title = ""
        self.offline_hint = ""
        self.offline = True
        self.align_top = False
        self.radius = radius
        self.setMinimumHeight(min_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_frame(self, qimage):
        self.image = qimage
        self.offline = False
        self.update()

    def set_offline(self):
        self.image = None
        self.offline = True
        self.update()

    def _target(self):
        iw, ih = (self.image.width(), self.image.height()) if self.image is not None else (16, 9)
        s = min(self.width() / iw, self.height() / ih)
        w, h = iw * s, ih * s
        y = 0 if self.align_top else (self.height() - h) / 2
        return QRectF((self.width() - w) / 2, y, w, h)

    def _badge(self, p, text, x, y, dot=None, right=False):
        f = p.font()
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        tw = QFontMetrics(f).horizontalAdvance(text) + (30 if dot else 20)
        box = QRectF(x - tw if right else x, y, tw, 26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(box, 6, 6)
        if dot:
            p.setBrush(QColor(dot))
            p.drawEllipse(QPointF(box.x() + 12, box.center().y()), 4, 4)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(box.adjusted(22 if dot else 10, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._target()
        clip = QPainterPath()
        clip.addRoundedRect(r, self.radius, self.radius)

        if self.offline or self.image is None:
            p.setPen(QPen(QColor(self.p["border"]), 1))
            p.setBrush(QColor(self.p["surface"]))
            p.drawPath(clip)
            # simple camera icon
            c = r.center()
            pen = QPen(QColor(self.p["muted"]), 2.5)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            body = QRectF(c.x() - 34, c.y() - 58, 68, 46)
            p.drawRoundedRect(body, 8, 8)
            p.drawEllipse(QPointF(body.center().x(), body.center().y() + 1), 13, 13)
            p.drawLine(QPointF(c.x() - 46, c.y() - 70), QPointF(c.x() + 46, c.y() + 2))
            f = p.font()
            f.setPixelSize(17)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(self.p["text"]))
            p.drawText(QRectF(r.x() + 20, c.y() + 6, r.width() - 40, 28),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, self.offline_title)
            f.setPixelSize(13)
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(self.p["muted"]))
            p.drawText(QRectF(r.x() + 40, c.y() + 36, r.width() - 80, 48),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, self.offline_hint)
            self._message(p, r)
            return

        p.save()
        p.setClipPath(clip)
        p.drawImage(r, self.image)
        p.restore()
        s = r.width() / self.image.width()

        def poly(pts):
            return QPolygonF([QPointF(r.x() + x * s, r.y() + y * s) for x, y in pts])

        accent = QColor(self.p["accent"])
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(accent, 2))
        for m in self.markers:
            p.drawPolygon(poly(m))
        if self.contour is not None and len(self.contour) > 2:
            p.setPen(QPen(accent, 3))
            p.drawPolygon(poly(self.contour))
        if self.badge:
            self._badge(p, self.badge, r.x() + 12, r.y() + 12, dot="#FF5C5C")
        if self.right_badge:
            self._badge(p, self.right_badge, r.right() - 12, r.y() + 12, right=True)
        self._message(p, r)

    def _message(self, p, r):
        if not self.message:
            return
        f = p.font()
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        w = r.width() - 24
        rect = QFontMetrics(f).boundingRect(0, 0, int(w - 24), 400, int(Qt.TextFlag.TextWordWrap), self.message)
        box = QRectF(r.x() + 12, r.bottom() - rect.height() - 34, w, rect.height() + 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.p["danger"]) if self.message_error else QColor(0, 0, 0, 190))
        p.drawRoundedRect(box, 8, 8)
        # red box: dark text on the light red of dark themes, white text on the deep red of light themes
        p.setPen(QColor("#FFFFFF") if not self.message_error else QColor("#1A0000" if self.p["dark"] else "#FFFFFF"))
        p.drawText(box.adjusted(12, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                   self.message)


class OutlinePreview(QWidget):
    """Draws an outline (mm points) scaled to fit, for the Library details."""

    def __init__(self, accent, bg, radius=9):
        super().__init__()
        self.points = []
        self.accent, self.bg, self.radius = QColor(accent), QColor(bg), radius
        self.setMinimumHeight(170)

    def set_points(self, pts):
        self.points = pts or []
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.bg)
        p.drawRoundedRect(QRectF(self.rect()), self.radius, self.radius)
        if len(self.points) < 3:
            return
        xs = [x for x, _ in self.points]
        ys = [y for _, y in self.points]
        w, h = max(xs) - min(xs) or 1, max(ys) - min(ys) or 1
        pad = 18
        s = min((self.width() - 2 * pad) / w, (self.height() - 2 * pad) / h)
        ox = (self.width() - w * s) / 2 - min(xs) * s
        oy = (self.height() - h * s) / 2 - min(ys) * s
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self.accent, 2))
        p.drawPolygon(QPolygonF([QPointF(ox + x * s, oy + y * s) for x, y in self.points]))
