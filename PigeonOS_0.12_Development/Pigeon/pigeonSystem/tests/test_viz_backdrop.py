"""Visualizer over the clocksaver: the enter / exit timeline and its blits."""

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
        self.silent: list[bool] = []

    def render(self, out: np.ndarray, *, silent: bool = False, **_kw) -> None:
        self.silent.append(silent)
        out[:, : out.shape[1] // 2] = 200  # left half lit, right half black

    def rotate(self, steps: int) -> None:
        self.turns.append(steps)


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _face(top: int = 400) -> np.ndarray:
    f = np.zeros((800, 1280, 4), np.uint8)
    f[top : top + 100, 200:1000] = (255, 160, 60, 255)  # the time
    return f


def _full_layers():
    f = _face()
    f[100:150, 300:900] = (255, 160, 60, 255)  # the date
    return (f, (0, 0, 1280, 800)), (np.zeros((1, 1, 4), np.uint8), (0, 0, 1, 1))


class TimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = _FakeViz()
        self.clock = _Clock()
        self.audio = True
        patches = [
            mock.patch.object(vb, "_viz", self.fake),
            mock.patch.object(vb.time, "monotonic", self.clock),
            mock.patch.object(vb, "wanted", lambda: self.audio),
            mock.patch.object(vb, "_digital_face", lambda: True),
            mock.patch.object(vb, "_render_digits", lambda: _face()),
            mock.patch.object(vb, "_t", 0.0),
            mock.patch.object(vb, "_last_mono", None),
            mock.patch.object(vb, "_exit_cb", None),
            mock.patch.object(vb, "_suppressed", False),
            mock.patch.object(vb, "_painted_mono", 0.0),
            mock.patch.dict(vb._faces, clear=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _frames(self, seconds: float, fps: float = 30.0) -> np.ndarray:
        canvas = np.zeros((800, 1280, 3), np.uint8)
        for _ in range(int(seconds * fps)):
            self.clock.t += 1.0 / fps
            canvas[:] = 0
            vb.compose(canvas, 1, _full_layers)
        return canvas

    def test_enter_fades_extras_moves_dims_then_shows_the_visualizer(self) -> None:
        c = self._frames(vb.EXTRAS_S + 0.05)
        self.assertEqual(int(c[120, 600].max()), 0, "date faded out")
        self.assertGreater(int(c[450, 600].max()), 200, "time still in place, full bright")
        self.assertEqual(self.fake.silent, [])
        c = self._frames(vb.MOVE_S + vb.DIM_S)
        self.assertEqual(int(c[450, 1100].max()), 0)
        top = int(np.argmax(c[:, 900].max(axis=1) > 0))
        self.assertEqual(top, vb.CLOCK_TOP_PX, "time moved to the top")
        self.assertLess(int(c[vb.CLOCK_TOP_PX + 5, 900].max()), 255 * vb.CLOCK_DIM + 2, "time dimmed")
        c = self._frames(vb.VIZ_S + 0.1)
        self.assertEqual(int(c[vb.CLOCK_TOP_PX + 5, 300].max()), 200, "lit bars cover the time")
        self.assertGreater(int(c[vb.CLOCK_TOP_PX + 5, 900].max()), 0, "time shows where bars are dark")
        self.assertTrue(self.fake.silent and not any(self.fake.silent))

    def test_audio_stopping_runs_back_with_silent_bars(self) -> None:
        self._frames(vb._TOTAL + 0.2)
        self.audio = False
        self._frames(0.5)
        self.assertTrue(self.fake.silent[-1], "bars fall to rest")
        c = self._frames(vb._TOTAL)
        self.assertEqual(vb._t, 0.0)
        self.assertGreater(int(c[120, 600].max()), 200, "date back")
        self.assertGreater(int(c[450, 600].max()), 200, "time back in place, full bright")
        self.assertFalse(vb.active())

    def test_leave_then_calls_back_at_rest(self) -> None:
        self._frames(vb._TOTAL + 0.2)
        done = []
        self.assertTrue(vb.leave_then(lambda: done.append(1)))
        self._frames(vb._TOTAL / 2)
        self.assertEqual(done, [])
        self._frames(vb._TOTAL / 2 + 0.2)
        self.assertEqual(done, [1])

    def test_suppress_holds_until_audio_stops_and_cancel_resumes(self) -> None:
        self._frames(vb._TOTAL + 0.2)
        vb.suppress()
        self._frames(vb._TOTAL + 0.2)
        self.assertEqual(vb._t, 0.0)
        self.assertTrue(vb.cancel_leave())
        self._frames(0.5)
        self.assertGreater(vb._t, 0.0)
        self.assertFalse(vb.cancel_leave())

    def test_knob_turns_only_while_showing(self) -> None:
        self.assertFalse(vb.rotate(1))
        self._frames(vb._TOTAL + 0.2)
        with mock.patch.object(vb.time, "monotonic", lambda: self.clock.t):
            self.assertTrue(vb.rotate(-1))
        self.assertEqual(self.fake.turns, [-1])


class OverlayTests(unittest.TestCase):
    def test_overlay_matches_the_regular_alpha_blend(self) -> None:
        from pigeon.compositing import alpha_blend_bgra_over_bgr

        frame = np.zeros((800, 1280, 4), np.uint8)
        frame[100:300, 200:900] = (40, 80, 250, 255)
        frame[400:420, 100:1200, :3] = 220
        frame[400:420, 100:1200, 3] = 128  # soft edge
        bg = np.random.default_rng(5).integers(0, 255, (800, 1280, 3), dtype=np.uint8)
        want = alpha_blend_bgra_over_bgr(bg.copy(), frame)
        got = bg.copy()
        vb.ClockOverlay(frame).blit(got)
        self.assertLessEqual(int(np.abs(got.astype(int) - want.astype(int)).max()), 1)

    def test_key_page_clears_the_digital_page_keeps_ink(self) -> None:
        frame = np.zeros((10, 10, 4), np.uint8)
        frame[..., :3] = 15
        frame[..., 3] = 255
        frame[4:6, 4:6, :3] = (0, 0, 255)
        out = vb.key_page(frame)
        self.assertEqual(int(out[0, 0, 3]), 0)
        self.assertEqual(int(out[5, 5, 3]), 255)

    def test_key_page_leaves_real_transparency(self) -> None:
        analog = np.zeros((10, 10, 4), np.uint8)
        analog[3:7, 3:7] = (0, 0, 0, 255)
        self.assertIs(vb.key_page(analog), analog)


if __name__ == "__main__":
    unittest.main()
