"""Zone-4 meter: L/R Sweep VU arcs (default) or peak/RMS ladders in zone 4, in place of the EQ."""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest import mock

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import zone4_eq, zone4_meter  # noqa: E402

TRACK = (113, 536, 1067, 100, 13)
GREEN = (0x84, 0xDC, 0x3D)  # ladder colSafe, BGR
BLUE = (0xF7, 0xA6, 0x4E)  # sweep lit, BGR


def _render(layout: str, left: float, right: float, *, channels: int = 3, frames: int = 30,
            **meter: object) -> np.ndarray:
    """``layout`` is a ladder layout, or ``"sweep"``."""
    meter_cfg = dict(meter, style="sweep") if layout == "sweep" else dict(meter, style="ladder", layout=layout)
    raw = dict(zone4_eq.DEFAULT_PARAMS, meter=meter_cfg)
    meter = zone4_meter.Zone4Meter()
    out = np.zeros((800, 1280, channels), dtype=np.uint8)
    rng = np.random.default_rng(0)
    with mock.patch.object(zone4_eq, "params", return_value=raw), \
            mock.patch.object(zone4_eq, "want_mic_capture", lambda: None):
        for _ in range(frames):
            n = 2048
            zone4_eq.feed_pcm_stereo(rng.standard_normal(n) * left, rng.standard_normal(n) * right, 48_000.0)
            meter._last_t = time.monotonic() - 1.0 / 30.0  # one 30 fps frame per render
            meter.render_into(out, TRACK)
    return out


def _lit(out: np.ndarray, x0: int, x1: int, y0: int, y1: int, color: tuple[int, int, int]) -> int:
    zone = out[y0:y1, x0:x1, :3].astype(int)
    return int((np.abs(zone - np.array(color)).sum(axis=2) < 12).sum())


def _lit_green(out: np.ndarray, x0: int, x1: int, y0: int, y1: int) -> int:
    return _lit(out, x0, x1, y0, y1, GREEN)


class Zone4MeterTests(unittest.TestCase):
    def test_meters_are_the_default_visualizer(self) -> None:
        with mock.patch.object(zone4_eq, "params", return_value=dict(zone4_eq.DEFAULT_PARAMS)):
            self.assertTrue(zone4_meter.selected())
        with mock.patch.object(zone4_eq, "params", return_value=dict(zone4_eq.DEFAULT_PARAMS, visualizer="eq")):
            self.assertFalse(zone4_meter.selected())

    def test_meter_params_come_from_zone4_eq_json(self) -> None:
        with mock.patch.object(zone4_eq, "params", return_value=dict(zone4_eq.DEFAULT_PARAMS)):
            p = zone4_meter.params()
        # Sweep by default, with the fullscreen Sweep VU's colors and mode.
        self.assertEqual((p["style"], p["lit"], p["mode"]), ("sweep", "#4EA6F7", "spot"))
        raw = dict(zone4_eq.DEFAULT_PARAMS, meter={"style": "ladder", "layout": "stacked", "segments": 12})
        with mock.patch.object(zone4_eq, "params", return_value=raw):
            p = zone4_meter.params()
        self.assertEqual((p["style"], p["layout"], p["segments"]), ("ladder", "stacked", 12))
        bad = dict(raw, meter={"style": "nope", "layout": "nope"})
        with mock.patch.object(zone4_eq, "params", return_value=bad):
            self.assertEqual(zone4_meter.params()["style"], "sweep")
        with mock.patch.object(zone4_eq, "params", return_value=dict(raw, meter={"style": "ladder", "layout": "x"})):
            self.assertEqual(zone4_meter.params()["layout"], "mirror")

    def test_sweep_arcs_fit_each_half_of_the_track(self) -> None:
        p = dict(zone4_meter.COMMON_DEFAULTS, **zone4_meter.SWEEP_DEFAULTS)
        x, y, w, h, _r = TRACK
        meters, sweep = zone4_meter.sweep_geometry(p, w, h)
        self.assertTrue(30.0 < sweep < 90.0, sweep)
        ins, bw = p["insetPx"], p["bandW"]
        for cx, cy, R, _bw, _ch in meters:
            self.assertAlmostEqual(cy - R - bw / 2, ins)  # crown at the top inset
            end_y = cy - R * np.cos(np.radians(sweep / 2))
            self.assertAlmostEqual(end_y + bw / 2, h - ins)  # ends at the bottom inset
        self.assertLess(meters[0][0], w / 2)
        self.assertGreater(meters[1][0], w / 2)

    def test_sweep_silence_rests_at_the_start(self) -> None:
        """Like the fullscreen Sweep VU: no signal → only a resting dot at each arc's floor."""
        x, y, w, h, _r = TRACK
        for mode in ("spot", "fill"):
            out = _render("sweep", 0.0, 0.0, mode=mode)
            for x0 in (x, x + w // 2):
                self.assertGreater(_lit(out, x0, x0 + w // 8, y, y + h, BLUE), 20, mode)
                self.assertEqual(_lit(out, x0 + w // 8, x0 + w // 2, y, y + h, BLUE), 0, mode)

    def test_sweep_left_only_moves_left_arc(self) -> None:
        x, y, w, h, _r = TRACK
        for mode in ("spot", "fill"):
            out = _render("sweep", 0.1, 0.0, mode=mode)
            self.assertGreater(_lit(out, x + w // 8, x + w // 2, y, y + h, BLUE), 50, mode)  # L off the floor
            self.assertEqual(_lit(out, x + w // 2 + w // 8, x + w, y, y + h, BLUE), 0, mode)  # R at rest

    def test_silence_lights_nothing(self) -> None:
        out = _render("mirror", 0.0, 0.0)
        x, y, w, h, _r = TRACK
        self.assertEqual(_lit_green(out, x, x + w, y, y + h), 0)

    def test_left_only_lights_left_half(self) -> None:
        x, y, w, h, _r = TRACK
        for layout in ("mirror", "split"):
            out = _render(layout, 0.2, 0.0)
            self.assertGreater(_lit_green(out, x, x + w // 2, y, y + h), 500, layout)
            self.assertEqual(_lit_green(out, x + w // 2, x + w, y, y + h), 0, layout)

    def test_mirror_grows_out_from_the_center(self) -> None:
        x, y, w, h, _r = TRACK
        out = _render("mirror", 0.0, 0.01)  # quiet R: only the first segments
        lit = _lit_green(out, x + w // 2, x + w // 2 + w // 8, y, y + h)
        self.assertGreater(lit, 0)
        self.assertEqual(_lit_green(out, x + w - w // 8, x + w, y, y + h), 0)

    def test_stacked_puts_left_on_top(self) -> None:
        x, y, w, h, _r = TRACK
        out = _render("stacked", 0.2, 0.0)
        self.assertGreater(_lit_green(out, x, x + w, y, y + h // 2), 300)
        self.assertEqual(_lit_green(out, x, x + w, y + h // 2, y + h), 0)

    def test_only_the_track_is_painted(self) -> None:
        x, y, w, h, _r = TRACK
        for layout in ("sweep", "split"):
            out = _render(layout, 0.3, 0.3)
            self.assertEqual(int(out[: y].sum()) + int(out[y + h :].sum()), 0, layout)
            # Rounded corner: the very corner pixel stays (mostly) what was under it.
            self.assertLess(int(out[y, x].max()), 20, layout)

    def test_bgra_output_gets_alpha(self) -> None:
        x, y, w, h, _r = TRACK
        for layout in ("sweep", "mirror"):
            out = _render(layout, 0.1, 0.1, channels=4, frames=2)
            self.assertEqual(int(out[y + h // 2, x + w // 2, 3]), 255, layout)
            self.assertEqual(int(out[y - 1, x + w // 2, 3]), 0, layout)


if __name__ == "__main__":
    unittest.main()
