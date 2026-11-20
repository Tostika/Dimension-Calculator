"""Themes: 6 presets plus the user's own 4 colours. Everything else is derived,
so any colour choice still gives readable text, borders and buttons."""

PRESETS = {
    "graphite":   {"bg": "#131315", "surface": "#1C1C20", "text": "#EDEDEF", "accent": "#FFB020"},
    "indigo":     {"bg": "#100E1C", "surface": "#191629", "text": "#ECEAF7", "accent": "#A99BFF"},
    "copper":     {"bg": "#0B1315", "surface": "#121D20", "text": "#E7EFEF", "accent": "#F0965F"},
    "instrument": {"bg": "#0E1116", "surface": "#151A21", "text": "#E6EAF0", "accent": "#00F5A0"},
    "ocean":      {"bg": "#0B1626", "surface": "#122238", "text": "#E6EEF8", "accent": "#5FD4FF"},
    "daylight":   {"bg": "#F4F6F9", "surface": "#FFFFFF", "text": "#141922", "accent": "#1F4FE0"},
}
PRESET_ORDER = ["graphite", "indigo", "copper", "instrument", "ocean", "daylight"]


def _rgb(h):
    h = str(h or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        return [0, 0, 0]


def _hex(rgb):
    return "#" + "".join("%02X" % max(0, min(255, round(v))) for v in rgb)


def mix(a, b, t):
    x, y = _rgb(a), _rgb(b)
    return _hex([x[i] * (1 - t) + y[i] * t for i in range(3)])


def luminance(h):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def rgba(h, alpha):
    r, g, b = _rgb(h)
    return "rgba(%d, %d, %d, %d)" % (r, g, b, round(alpha * 255))


def base_colors(settings):
    if settings.get("theme") == "custom" and settings.get("custom_colors"):
        c = dict(PRESETS["graphite"])
        c.update(settings.get("custom_colors"))
        return c
    return dict(PRESETS.get(settings.get("theme"), PRESETS["graphite"]))


def palette(base, corners="round"):
    bg, surface, text, accent = base["bg"], base["surface"], base["text"], base["accent"]
    dark = luminance(bg) < 0.25
    on_accent = "#FFFFFF" if contrast(accent, "#FFFFFF") >= contrast(accent, "#111111") else "#111111"
    return {
        "bg": bg, "surface": surface, "text": text, "accent": accent, "on_accent": on_accent,
        "muted": mix(text, bg, 0.36),
        "nav_text": mix(text, surface, 0.22),
        "border": mix(surface, text, 0.14),
        "field": mix(bg, text, 0.03),
        "accent_soft": rgba(accent, 0.15),
        "accent_hover": mix(accent, text if dark else "#000000", 0.12),
        "danger": "#FF7A7A" if dark else "#C42B30",
        "ok": "#4ADE80" if dark else "#14843F",
        "r": 4 if corners == "sharp" else 14,
        "rs": 3 if corners == "sharp" else 9,
        "dark": dark,
    }


def readability(p):
    """Returns [(label_key, ratio, ok)] for the Settings readability check."""
    return [
        ("r_text", contrast(p["text"], p["bg"]), contrast(p["text"], p["bg"]) >= 4.5),
        ("r_accent", contrast(p["accent"], p["bg"]), contrast(p["accent"], p["bg"]) >= 3.0),
        ("r_button", contrast(p["on_accent"], p["accent"]), contrast(p["on_accent"], p["accent"]) >= 4.5),
    ]


def stylesheet(p, family="Segoe UI"):
    """Qt style sheet for the whole app. Widgets pick styles through objectName / properties."""
    font = '"%s"' % family
    return f"""
* {{ font-family: {font}; font-size: 14px; color: {p['text']}; }}
QMainWindow, QWidget#Root, QWidget#Page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p['bg']}; }}
QWidget#Sidebar {{ background: {p['surface']}; border-right: 1px solid {p['border']}; }}
QLabel {{ background: transparent; }}
QLabel#AppTitle {{ font-size: 16px; font-weight: 700; }}
QLabel#Muted, QLabel#Hint {{ color: {p['muted']}; }}
QLabel#Hint {{ font-size: 12px; }}
QLabel#PageTitle {{ font-size: 21px; font-weight: 700; }}
QLabel#CardTitle {{ font-size: 16px; font-weight: 700; }}
QLabel#SectionTitle {{ font-size: 13px; font-weight: 600; color: {p['muted']}; }}
QLabel#HugeValue {{ font-family: Consolas; font-size: 32px; font-weight: 700; }}
QLabel#BigValue {{ font-family: Consolas; font-size: 26px; font-weight: 700; }}
QLabel#MidValue {{ font-family: Consolas; font-size: 20px; font-weight: 700; }}
QLabel#Mono {{ font-family: Consolas; color: {p['muted']}; }}
QLabel#AccentValue {{ font-family: Consolas; color: {p['accent']}; }}
QLabel#Ok {{ color: {p['ok']}; font-weight: 600; }}
QLabel#Bad {{ color: {p['danger']}; font-weight: 600; }}
QLabel#Message {{ color: {p['muted']}; }}
QLabel#MessageError {{ color: {p['danger']}; }}
QLabel#Chip {{ background: {p['accent_soft']}; color: {p['accent']}; border-radius: {p['rs']}px; padding: 5px 9px; font-family: Consolas; font-weight: 600; }}
QLabel#ChipOff {{ background: transparent; color: {p['muted']}; border: 1px solid {p['border']}; border-radius: {p['rs']}px; padding: 5px 9px; font-family: Consolas; }}
QLabel#CameraView {{ background: #000000; border: 1px solid {p['border']}; border-radius: {p['r']}px; }}

QFrame#Card {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: {p['r']}px; }}
QFrame#StepCard {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: {p['r']}px; }}
QFrame#StepCard[active="true"] {{ border: 2px solid {p['accent']}; }}
QFrame#Inset {{ background: {p['bg']}; border: 1px solid {p['border']}; border-radius: {p['rs']}px; }}

QPushButton {{ min-height: 40px; padding: 0 10px; border-radius: {p['rs']}px; border: 1px solid {p['border']}; background: transparent; color: {p['text']}; }}
QPushButton:hover {{ background: {p['accent_soft']}; }}
QPushButton:disabled {{ color: {p['muted']}; border-color: {p['border']}; }}
QPushButton#Primary {{ background: {p['accent']}; color: {p['on_accent']}; border: 0; font-weight: 700; min-height: 48px; }}
QPushButton#Primary:hover {{ background: {p['accent_hover']}; }}
QPushButton#Primary:disabled {{ background: {p['border']}; color: {p['muted']}; }}
QPushButton#Danger {{ border: 1px solid {p['danger']}; color: {p['danger']}; }}
QPushButton#Nav {{ text-align: left; border: 0; min-height: 46px; padding-left: 14px; font-weight: 600; color: {p['nav_text']}; }}
QPushButton#Nav:checked {{ background: {p['accent_soft']}; color: {p['accent']}; }}
QPushButton#Toggle:checked, QPushButton#Lang:checked {{ background: {p['accent_soft']}; color: {p['accent']}; border: 1px solid {p['accent']}; font-weight: 700; }}
QPushButton#Lang {{ min-height: 36px; border: 0; font-weight: 600; color: {p['nav_text']}; }}
QPushButton#Option {{ border: 2px solid {p['border']}; border-radius: {p['r']}px; background: {p['bg']}; padding: 8px; }}
QPushButton#Option:checked {{ border: 2px solid {p['accent']}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ min-height: 42px; padding: 0 10px; border-radius: {p['rs']}px; border: 1px solid {p['border']}; background: {p['field']}; color: {p['text']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {p['accent']}; }}
QLineEdit#NameEdit {{ font-size: 17px; font-weight: 700; border: 1px solid {p['accent']}; }}
QComboBox QAbstractItemView {{ background: {p['surface']}; color: {p['text']}; selection-background-color: {p['accent_soft']}; selection-color: {p['accent']}; }}

QCheckBox {{ spacing: 10px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px; border: 1px solid {p['border']}; background: {p['field']}; }}
QCheckBox::indicator:checked {{ background: {p['accent']}; border: 1px solid {p['accent']}; }}

QSlider::groove:horizontal {{ height: 6px; border-radius: 3px; background: {p['border']}; }}
QSlider::sub-page:horizontal {{ height: 6px; border-radius: 3px; background: {p['accent']}; }}
QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -6px 0; border-radius: 9px; background: {p['accent']}; }}

QListWidget {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: {p['r']}px; outline: 0; }}
QListWidget::item {{ border-bottom: 1px solid {p['border']}; padding: 0; }}
QListWidget::item:selected {{ background: {p['accent_soft']}; border-left: 3px solid {p['accent']}; }}

QScrollBar:vertical {{ width: 10px; background: transparent; }}
QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; }}
QMessageBox {{ background: {p['surface']}; }}
"""
