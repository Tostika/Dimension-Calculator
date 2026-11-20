"""Test helper only (not part of the app): a fake camera that shows a drawn scene."""
import numpy as np

class DemoScene:
    """Drawn scene for tests: item alone, item + card, empty base, card on the empty base."""

    def __init__(self, scene):
        self.scene = scene
        self.mode = "item"
        self.led = 1.0
        self._cache = {}

    def frame(self):
        cam_h = float(self.scene.get("camera_height_cm")) * 10.0  # follows the height set in the app
        key = (self.mode, round(self.led, 2), cam_h)
        if key not in self._cache:
            light = 0.35 + 0.65 * self.led                      # room light + our LEDs
            if self.mode == "item":
                f = self.scene.render(with_item=True, light=light, noise_seed=None, cam_h=cam_h)
            elif self.mode == "plate":
                f = self.scene.render(with_item=True, with_plate=True, light=light, noise_seed=None, cam_h=cam_h)
            elif self.mode == "plate_empty":
                f = self.scene.render(with_item=False, with_plate=True, light=light, noise_seed=None, cam_h=cam_h)
            elif self.mode == "card":
                f = self.scene.render(item_h=0.8, item=(85.6, 53.98), item_center=(150, 95), light=light, noise_seed=None, cam_h=cam_h)
            else:
                f = self.scene.render(with_item=False, light=light, noise_seed=None, cam_h=cam_h)
            if len(self._cache) > 12:
                self._cache.clear()
            self._cache[key] = f
        noise = np.random.default_rng().integers(-2, 3, size=(8, 8, 3), dtype=np.int16)
        f = self._cache[key].astype(np.int16)
        f[:8, :8] += noise                                      # tiny change so frames are "new"
        return np.clip(f, 0, 255).astype(np.uint8)
