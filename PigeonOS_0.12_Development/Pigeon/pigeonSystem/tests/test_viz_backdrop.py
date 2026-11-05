"""Full-screen visualizer behind the clocksaver."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import viz_backdrop as vb  # noqa: E402


class _FakeViz:
    def __init__(self) -> None:
        self.turns: list[int] = []

    def render(self, out: np.ndarray, **_kw) -> None:
        out[:] = 200

    def rotate(self, steps: int) -> None:
        self.turns.append(steps)


class VizBackdropTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = _FakeViz()
        vb._viz = self.fake
        vb._painted_mono = 0.0

    def tearDown(self) -> None:
        vb._viz = None
        vb._buf = None
        vb._painted_mono = 0.0

    def test_no_audio_leaves_the_canvas_alone(self) -> None:
        canvas = np.full((8, 10, 3), 7, np.uint8)
        with mock.patch.object(vb, "wanted", return_value=False):
            self.assertFalse(vb.paint(canvas))
        self.assertTrue((canvas == 7).all())

    def test_paints_the_dimmed_visualizer(self) -> None:
        canvas = np.zeros((8, 10, 3), np.uint8)
        with mock.patch.object(vb, "wanted", return_value=True):
            self.assertTrue(vb.paint(canvas))
        self.assertTrue((canvas == round(200 * vb.DIM)).all())

    def test_knob_turns_only_while_showing(self) -> None:
        self.assertFalse(vb.rotate(1))
        with mock.patch.object(vb, "wanted", return_value=True):
            vb.paint(np.zeros((4, 4, 3), np.uint8))
        self.assertTrue(vb.rotate(1))
        self.assertTrue(vb.rotate(-1))
        self.assertEqual(self.fake.turns, [1, -1])

    def test_key_page_clears_the_digital_page_keeps_ink(self) -> None:
        frame = np.zeros((10, 10, 4), np.uint8)
        frame[..., :3] = 15  # the digital face's page
        frame[..., 3] = 255
        frame[4:6, 4:6, :3] = (0, 0, 255)  # ink
        out = vb.key_page(frame)
        self.assertEqual(int(out[0, 0, 3]), 0)
        self.assertEqual(int(out[5, 5, 3]), 255)

    def test_key_page_leaves_real_transparency(self) -> None:
        analog = np.zeros((10, 10, 4), np.uint8)
        analog[3:7, 3:7] = (0, 0, 0, 255)  # black ring art, rest transparent
        self.assertIs(vb.key_page(analog), analog)


    def test_overlay_matches_the_regular_alpha_blend(self) -> None:
        from pigeon.compositing import alpha_blend_bgra_over_bgr

        rng = np.random.default_rng(5)
        frame = np.zeros((800, 1280, 4), np.uint8)
        frame[100:300, 200:900] = (40, 80, 250, 255)  # opaque ink
        frame[400:420, 100:1200, :3] = 220
        frame[400:420, 100:1200, 3] = 128  # soft edge
        layers = ((frame, (0, 0, 1280, 800)), (np.zeros((1, 1, 4), np.uint8), (0, 0, 1, 1)))
        bg = rng.integers(0, 255, (800, 1280, 3), dtype=np.uint8)
        want = alpha_blend_bgra_over_bgr(bg.copy(), frame)
        got = bg.copy()
        vb.ClockOverlay(layers).blit(got)
        self.assertLessEqual(int(np.abs(got.astype(int) - want.astype(int)).max()), 1)

    def test_clock_overlay_renders_once_then_reuses(self) -> None:
        calls = []

        def render():
            calls.append(1)
            f = np.zeros((800, 1280, 4), np.uint8)
            f[..., 3] = 0
            return (f, (0, 0, 1280, 800)), (np.zeros((1, 1, 4), np.uint8), (0, 0, 1, 1))

        vb._clock_key = vb._clock_val = None
        self.addCleanup(setattr, vb, "_clock_val", None)
        a = vb.clock_overlay(1, render)
        b = vb.clock_overlay(1, render)
        self.assertIs(a, b)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
