"""The full-screen visualizers over the Control API (``/visualizer``)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import app_state, runtime_paths  # noqa: E402
from pigeon import fullscreen_viz as fv  # noqa: E402
from pigeon.control_api.server import ControlService  # noqa: E402
from pigeon.widgets import options_settings  # noqa: E402


class VisualizerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = runtime_paths._CACHED
        runtime_paths._CACHED = Path(self._tmp.name)
        app_state._STATE_TEXT_CACHE = None
        app_state._STATE_PARSED_CACHE = None
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: setattr(runtime_paths, "_CACHED", self._prev))
        fv.set_presets(fv.default_presets())
        self.addCleanup(fv.set_presets, None)
        self.svc = ControlService(run_on_ui=lambda fn: fn())
        self.token = self.svc.auth.claim(self.svc.auth.pairing_code, "t", "c1")

    def call(self, method, path, body=None):
        return self.svc.handle(method, "/api/v1" + path, {}, self.token, body)

    def test_lists_the_rotation(self) -> None:
        self.assertIn("viz", self.call("GET", "/capabilities")[1]["capabilities"])
        st, d = self.call("GET", "/visualizer")
        self.assertEqual(st, 200)
        self.assertEqual([p["name"] for p in d["presets"]], [p["name"] for p in fv.presets()])
        self.assertEqual(d["presets"][0], {"index": 0, "name": "Spectrum", "style": "dots", "kind": "Dot matrix"})
        self.assertEqual((d["active"], d["viz_lock"]), (0, False))

    def test_pick_moves_every_remembering_visualizer_and_is_kept(self) -> None:
        zone6, backdrop = fv.FullscreenViz(remember=True), fv.FullscreenViz(remember=True)
        other = fv.FullscreenViz(0)
        st, d = self.call("PATCH", "/visualizer", {"active": 2})
        self.assertEqual((st, d["active"]), (200, 2))
        self.assertEqual((zone6.index, backdrop.index, other.index), (2, 2, 0))
        app_state._STATE_PARSED_CACHE = None
        self.assertEqual(fv.FullscreenViz(remember=True).index, 2, "a new visualizer starts on the pick")

    def test_viz_lock(self) -> None:
        st, d = self.call("PATCH", "/visualizer", {"viz_lock": True})
        self.assertEqual((st, d["viz_lock"]), (200, True))
        self.assertTrue(options_settings.viz_lock_on())
        self.assertFalse(self.call("PATCH", "/visualizer", {"viz_lock": False})[1]["viz_lock"])

    def test_validation(self) -> None:
        n = len(fv.presets())
        for body, field in (({"active": n}, "active"), ({"active": "1"}, "active"), ({"active": True}, "active"),
                            ({"viz_lock": "on"}, "viz_lock"), ({"nope": 1}, "nope")):
            st, d = self.call("PATCH", "/visualizer", body)
            self.assertEqual((st, d["error"]["details"]["fields"]), (400, [field]), body)
        self.assertEqual(self.call("PATCH", "/visualizer", {})[0], 400)


if __name__ == "__main__":
    unittest.main()
