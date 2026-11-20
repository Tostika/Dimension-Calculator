"""Start the app:  python main.py"""
import glob
import os
import subprocess
import sys

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from app.config import Settings, data_dir
from app.storage import Library
from app.ui.main_window import WIN_H, WIN_W, MainWindow
from app.vision.calibration import CalibrationStore

HERE = os.path.dirname(os.path.abspath(__file__))


def restart_scaled_if_too_big(app):
    """The window has one fixed size. If the screen (after Windows scaling) is smaller than that,
    start the app again once with everything shrunk evenly, so nothing is cut off."""
    if os.environ.get("DIMENSION_SCALED"):
        return
    avail = app.primaryScreen().availableGeometry()
    need_w, need_h = WIN_W + 16, WIN_H + 40          # window frame and title bar
    factor = min(1.0, avail.width() / need_w, avail.height() / need_h)
    if factor >= 0.99:
        return
    env = dict(os.environ, DIMENSION_SCALED="1", QT_SCALE_FACTOR=f"{factor - 0.01:.2f}")
    if getattr(sys, "frozen", False):
        cmd = [sys.executable] + sys.argv[1:]
    else:
        cmd = [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]
    subprocess.Popen(cmd, env=env)
    sys.exit(0)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("DimensionDevice")
    restart_scaled_if_too_big(app)

    # any .ttf / .otf put into app/fonts is loaded (for example Noto Sans Georgian)
    for f in glob.glob(os.path.join(HERE, "app", "fonts", "*.[ot]tf")):
        QFontDatabase.addApplicationFont(f)
    families = set(QFontDatabase.families())

    def font_family(lang):
        order = ["Noto Sans Georgian", "Segoe UI", "Sylfaen"] if lang == "ka" else ["Segoe UI", "Noto Sans Georgian"]
        for name in order:
            if name in families:
                return name
        return app.font().family()

    settings = Settings()
    library = Library(os.path.join(data_dir(), "library.db"))
    calib = CalibrationStore(os.path.join(data_dir(), "calibration.json"))
    win = MainWindow(app, settings, library, calib, font_family)
    win.show()
    screen = app.primaryScreen().availableGeometry()
    win.move(screen.center() - win.rect().center())
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
