"""Start the app:  python main.py"""
import glob
import os
import sys

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from app.config import Settings, data_dir
from app.storage import Library
from app.ui.main_window import MainWindow
from app.vision.calibration import CalibrationStore

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("DimensionDevice")

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
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
