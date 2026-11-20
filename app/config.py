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


DEFAULTS = {
    "language": "ka",            # "ka" or "en"
    "theme": "graphite",         # preset id, or "custom"
    "custom_colors": None,       # {"bg","surface","text","accent"} when theme == "custom"
    "scan_layout": "side",       # "side" or "wide"
    "corners": "round",          # "round" or "sharp"
    "camera_index": 0,
    "resolution": "4k",          # "4k", "1440", "1080"
    "lock_focus": True,
    "focus_value": 30,           # manual focus value per camera height is stored in calibration
    "lock_exposure": True,
    "exposure_value": -6,
    "serial_port": "",
    "led_brightness": 80,
    "z_preset_mm": 400,
    "z_presets_mm": [350, 400, 450],  # lens height above the base; all 4 base markers must be visible
    "remove_ambient": True,
    "marker_size_mm": 30.0,      # printed side length of base markers 0-3
    "base_marker_centers_mm": {  # centre of each base marker on the base, in mm (origin = marker 0)
        "0": [0.0, 0.0],
        "1": [300.0, 0.0],
        "2": [0.0, 190.0],
        "3": [300.0, 190.0]
    },
    "plate_marker_size_mm": 26.0,  # side length of markers 4-7 on the height card (card 100 x 70 mm)
    "plate_marker_centers_mm": {   # marker centres on the card, origin = card centre
        "4": [-31.0, -16.0],
        "5": [31.0, -16.0],
        "6": [-31.0, 16.0],
        "7": [31.0, 16.0]
    },
    "plate_thickness_mm": 2.0,
    "export_folder": "",
    "save_json": True,
}


class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "settings.json")
        self.data = deepcopy(DEFAULTS)
        self.load()
        if not self.data.get("export_folder"):
            self.data["export_folder"] = os.path.join(data_dir(), "exports")

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            for k, v in stored.items():
                if k in DEFAULTS:
                    self.data[k] = v
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

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
