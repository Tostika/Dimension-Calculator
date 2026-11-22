"""App settings: loaded from and saved to settings.json next to the app data."""
import json
import os
from copy import deepcopy

APP_NAME = "DimensionDevice"


def data_dir():
    """Folder where settings, the library database and exports live."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


SETTINGS_VERSION = 6

# The two printed base sheets (print/base_A3.pdf, print/base_A4.pdf). The app tells them apart by
# how the markers sit relative to each other and switches to the one it sees.
BASE_SHEETS = {
    "A4": {"marker_size_mm": 20.0,
           "base_marker_centers_mm": {"0": [0.0, 0.0], "1": [250.0, 0.0], "2": [0.0, 140.0], "3": [250.0, 140.0]}},
    "A3": {"marker_size_mm": 30.0,
           "base_marker_centers_mm": {"0": [0.0, 0.0], "1": [300.0, 0.0], "2": [0.0, 190.0], "3": [300.0, 190.0]}},
}

SHEET_KEYS = ("marker_size_mm", "base_marker_centers_mm", "plate_marker_size_mm", "plate_marker_centers_mm")

DEFAULTS = {
    "settings_version": SETTINGS_VERSION,
    "language": "ka",            # "ka" or "en"
    "theme": "graphite",         # preset id, or "custom"
    "custom_colors": None,       # {"bg","surface","text","accent"} when theme == "custom"
    "scan_layout": "side",       # "side" or "wide"
    "corners": "round",          # "round" or "sharp"
    "last_camera_index": 0,      # the app finds the camera itself; this only makes it look there first
    "camera_name_hints": ["EMEET", "C960"],   # the camera is found by its name (Windows)
    "min_camera_width": 1280,    # only accept a camera that gives at least this width (the 4K C960, not a laptop webcam)
    "resolution": "4k",          # "4k", "1440", "1080"
    "lock_focus": False,         # switched on automatically after lens calibration, with the focus it found
    "focus_value": 30,
    "lock_exposure": False,
    "exposure_value": -6,
    "serial_port": "",
    "led_brightness": 80,
    "camera_height_cm": 37,      # lens height above the base, 30-40 cm in 1 cm steps
    "camera_height_min_cm": 30,
    "camera_height_max_cm": 40,
    "remove_ambient": True,
    "marker_size_mm": 20.0,      # printed side length of base markers 0-3
    "base_marker_centers_mm": {  # centre of each base marker on the base, in mm (origin = marker 0)
        "0": [0.0, 0.0],
        "1": [250.0, 0.0],
        "2": [0.0, 140.0],
        "3": [250.0, 140.0]
    },
    "plate_marker_size_mm": 26.0,  # side length of markers 4-7 on the height card (card 100 x 70 mm)
    "plate_marker_centers_mm": {   # marker centres on the card, origin = card centre
        "4": [-31.0, -16.0],
        "5": [31.0, -16.0],
        "6": [-31.0, 16.0],
        "7": [31.0, 16.0]
    },
    "base_sheet": "A4",          # which printed base sheet is in use ("A4", "A3", or "custom" after Learn layout)
    "plate_thickness_mm": 2.0,
    "export_folder": "",
    "save_json": True,
}


class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "settings.json")
        self.data = deepcopy(DEFAULTS)
        stored_version = self.load()
        if stored_version < 3:
            # v0.1.0/v0.1.1 saved "lock focus" and "lock exposure" as on, which forces the camera to a
            # dark manual exposure, manual white balance and a fixed (blurry) focus. Switch them off.
            # (The v2 version of this fix never ran: it read the version from the defaults.)
            self.data["lock_focus"] = False
            self.data["lock_exposure"] = False
            self.data["settings_version"] = SETTINGS_VERSION
            self.save()
        if stored_version < 4:
            # v0.1.9 ships fixed print sheets (print/base_A3.pdf, height_card_A4.pdf) that match
            # the defaults exactly: forget layouts learned from older sheets
            self.use_sheet_layout()
            self.data["settings_version"] = SETTINGS_VERSION
            self.save()
        if stored_version < 5:
            # v0.1.10 widens the camera height range from 35-40 cm to 30-40 cm
            self.data["camera_height_min_cm"] = DEFAULTS["camera_height_min_cm"]
            self.data["camera_height_max_cm"] = DEFAULTS["camera_height_max_cm"]
            self.data["settings_version"] = SETTINGS_VERSION
            self.save()
        if stored_version < 6:
            # v0.1.11 replaces the A3 base with a smaller A4 base (print/base_A4.pdf) that the
            # camera sees whole from 30 cm up
            self.use_sheet_layout()
            self.data["settings_version"] = SETTINGS_VERSION
            self.save()
        if not self.data.get("export_folder"):
            self.data["export_folder"] = os.path.join(data_dir(), "exports")

    def load(self):
        """Reads settings.json. Returns the settings version the file was saved with
        (1 for files from before versions existed, the current one if there is no file yet)."""
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                stored = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return SETTINGS_VERSION
        for k, v in stored.items():
            if k in DEFAULTS:
                self.data[k] = v
        return int(stored.get("settings_version", 1))

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def use_sheet_layout(self):
        """Marker sizes and positions of the printed sheets (base_A4.pdf or base_A3.pdf, height_card_A4.pdf)."""
        for k in SHEET_KEYS:
            self.data[k] = deepcopy(DEFAULTS[k])
        sheet = self.data.get("base_sheet")
        self.use_sheet(sheet if sheet in BASE_SHEETS else "A4")

    def use_sheet(self, name):
        """Switch to one of the printed base sheets (BASE_SHEETS)."""
        for k, v in BASE_SHEETS[name].items():
            self.data[k] = deepcopy(v)
        self.data["base_sheet"] = name
        self.save()

    def camera_height_mm(self):
        return float(self.get("camera_height_cm")) * 10.0

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key, value, save=True):
        self.data[key] = value
        if save:
            self.save()

    def reset_appearance(self):
        for k in ("theme", "custom_colors", "scan_layout", "corners"):
            self.data[k] = deepcopy(DEFAULTS[k])
        self.save()
