"""Display brightness: persistence, software dimming, hardware backlight, API."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import app_state, runtime_paths  # noqa: E402
from pigeon import display_brightness as db  # noqa: E402
from pigeon.control_api.server import ControlService  # noqa: E402
from pigeon.widgets.options_settings import apply_ui_look_bgr  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = runtime_paths._CACHED
        runtime_paths._CACHED = Path(self._tmp.name)
        app_state._STATE_TEXT_CACHE = None
        app_state._STATE_PARSED_CACHE = None
        self.bl = Path(self._tmp.name) / "backlight"      # no devices by default
        self.bl.mkdir()
        self._env = mock.patch.dict(os.environ, {"PIGEON_BACKLIGHT_DIR": str(self.bl)})
        self._env.start()
        db.reset_cache()
        self.addCleanup(self._env.stop)
        self.addCleanup(db.reset_cache)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: setattr(runtime_paths, "_CACHED", self._prev))

    def make_backlight(self, max_b: int = 255, writable: bool = True) -> Path:
        d = self.bl / "rpi_backlight"
        d.mkdir()
        (d / "max_brightness").write_text(str(max_b))
        (d / "brightness").write_text(str(max_b))
        if not writable:
            (d / "brightness").chmod(0o444)
        db.reset_cache()
        return d


class LevelTests(_Base):
    def test_default_is_full_and_clamped(self) -> None:
        self.assertEqual(db.get_percent(), 100)
        self.assertEqual(db.clamp(0), db.MIN_PERCENT)
        self.assertEqual(db.clamp(500), 100)
        self.assertEqual(db.clamp("42.4"), 42)
        with self.assertRaises(ValueError):
            db.clamp("bright")

    def test_persists_across_restart(self) -> None:
        self.assertEqual(db.set_percent(55), 55)
        db.reset_cache()
        app_state._STATE_TEXT_CACHE = None
        app_state._STATE_PARSED_CACHE = None
        self.assertEqual(db.get_percent(), 55)


class SoftwareTests(_Base):
    def test_no_backlight_means_software_gain_on_frames(self) -> None:
        self.assertEqual(db.mode(), "software")
        db.set_percent(50)
        frame = np.full((4, 4, 3), 200, np.uint8)
        out = db.apply(frame)
        self.assertEqual(int(out[0, 0, 0]), 100)
        self.assertEqual(int(frame[0, 0, 0]), 200)  # input untouched

    def test_full_brightness_is_a_no_op(self) -> None:
        frame = np.full((2, 2, 3), 77, np.uint8)
        self.assertIs(db.apply(frame), frame)

    def test_runs_in_the_ui_look_path(self) -> None:
        db.set_percent(25)
        out = apply_ui_look_bgr(np.full((2, 2, 3), 200, np.uint8))
        self.assertEqual(int(out[0, 0, 0]), 50)


class BacklightTests(_Base):
    def test_hardware_does_the_dimming_and_frames_are_untouched(self) -> None:
        d = self.make_backlight(max_b=200)
        self.assertEqual(db.mode(), "backlight")
        db.set_percent(50)
        self.assertEqual((d / "brightness").read_text(), "100")
        frame = np.full((2, 2, 3), 200, np.uint8)
        self.assertIs(db.apply(frame), frame)

    def test_never_writes_zero(self) -> None:
        d = self.make_backlight(max_b=7)
        db.set_percent(db.MIN_PERCENT)
        self.assertGreaterEqual(int((d / "brightness").read_text()), 1)

    def test_saved_level_is_pushed_to_panel_on_first_frame(self) -> None:
        db.set_percent(40)
        d = self.make_backlight(max_b=100)  # appears after the level was saved
        db.apply(np.zeros((1, 1, 3), np.uint8))
        self.assertEqual((d / "brightness").read_text(), "40")

    def test_unwritable_backlight_falls_back_to_software(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("root can write read-only files")
        self.make_backlight(writable=False)
        self.assertEqual(db.mode(), "software")
        db.set_percent(50)
        out = db.apply(np.full((2, 2, 3), 100, np.uint8))
        self.assertEqual(int(out[0, 0, 0]), 50)

    def test_failed_write_switches_to_software(self) -> None:
        d = self.make_backlight()
        with mock.patch.object(Path, "write_text", side_effect=OSError("denied")):
            db.set_percent(50)
        self.assertEqual(db.mode(), "software")
        self.assertEqual(int(db.apply(np.full((1, 1, 3), 100, np.uint8))[0, 0, 0]), 50)


class RouteTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.applied: list[str] = []
        self.svc = ControlService(run_on_ui=lambda fn: fn(),
                                  apply_settings=lambda: self.applied.append("settings"))
        self.token = self.svc.auth.claim(self.svc.auth.pairing_code, "t", "c1")

    def call(self, method, path, body=None):
        return self.svc.handle(method, "/api/v1" + path, {}, self.token, body)

    def test_get_and_patch(self) -> None:
        st, d = self.call("GET", "/display")
        self.assertEqual((st, d["brightness"], d["min"], d["mode"]), (200, 100, 10, "software"))
        st, d = self.call("PATCH", "/display", {"brightness": 35})
        self.assertEqual((st, d["brightness"]), (200, 35))
        self.assertEqual(self.applied, ["settings"])  # screen repaints at once
        self.assertEqual(db.get_percent(), 35)

    def test_validation(self) -> None:
        for body in ({"brightness": 5}, {"brightness": 101}, {"brightness": "high"},
                     {"brightness": True}, {}, {"volume": 3}):
            self.assertEqual(self.call("PATCH", "/display", body)[0], 400, body)
        self.assertEqual(db.get_percent(), 100)
        self.assertEqual(self.applied, [])

    def test_requires_auth(self) -> None:
        self.assertEqual(self.svc.handle("GET", "/api/v1/display", {}, "", None)[0], 401)


if __name__ == "__main__":
    unittest.main()
