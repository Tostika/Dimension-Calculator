"""Small building blocks shared by all pages."""
import traceback

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

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


def button(text, name=None, on_click=None, checkable=False):
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        b.clicked.connect(on_click)
    return b


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
    """Shows the preview frame (kept in proportion) with drawn overlays:
    marker boxes and the measured outline, both given in preview pixels."""

    def __init__(self, accent, radius=12, min_height=360):
        super().__init__()
        self.image = None
        self.markers = []
        self.contour = None
        self.badge = ""
        self.accent = QColor(accent)
        self.radius = radius
        self.setMinimumHeight(min_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_frame(self, qimage):
        self.image = qimage
        self.update()

    def _target(self):
        if self.image is None:
            return QRectF(self.rect())
        iw, ih = self.image.width(), self.image.height()
        s = min(self.width() / iw, self.height() / ih)
        w, h = iw * s, ih * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#000000"))
        p.drawRoundedRect(QRectF(self.rect()), self.radius, self.radius)
        if self.image is None:
            return
        r = self._target()
        p.drawImage(r, self.image)
        s = r.width() / self.image.width()

        def poly(pts):
            return QPolygonF([QPointF(r.x() + x * s, r.y() + y * s) for x, y in pts])

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self.accent, 2))
        for m in self.markers:
            p.drawPolygon(poly(m))
        if self.contour is not None and len(self.contour) > 2:
            p.setPen(QPen(self.accent, 3))
            p.drawPolygon(poly(self.contour))
        if self.badge:
            f = p.font()
            f.setPointSize(9)
            f.setBold(True)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(self.badge) + 30
            box = QRectF(r.x() + 12, r.y() + 12, tw, 26)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 180))
            p.drawRoundedRect(box, 6, 6)
            p.setBrush(QColor("#FF5C5C"))
            p.drawEllipse(QPointF(box.x() + 12, box.center().y()), 4, 4)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(box.adjusted(22, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.badge)


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
