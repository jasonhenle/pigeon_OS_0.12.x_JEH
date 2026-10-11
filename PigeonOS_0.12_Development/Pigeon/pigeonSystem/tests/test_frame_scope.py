"""Per-frame reuse of the auto-widget policy (frame_scope)."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.core import frame_scope, saver_state  # noqa: E402


class FrameScopeTests(unittest.TestCase):
    def test_token_only_inside_a_frame(self) -> None:
        self.assertIsNone(frame_scope.token())
        with frame_scope.render_frame():
            t = frame_scope.token()
            self.assertIsNotNone(t)
            with frame_scope.render_frame():  # nested: same frame
                self.assertEqual(frame_scope.token(), t)
        self.assertIsNone(frame_scope.token())
        with frame_scope.render_frame():
            self.assertNotEqual(frame_scope.token(), t)


class PolicyPerFrameTests(unittest.TestCase):
    def _policy(self, signals):
        plan = SimpleNamespace(force_settings=False, settings_exit_enabled=False)
        with mock.patch("pigeon.auto_widgets.resolve_auto_widgets", return_value=plan), \
             mock.patch("pigeon.auto_widgets.set_live_plan"), \
             mock.patch("pigeon.paused_screen.set_pausesaver_backdrop"):
            return saver_state._apply_auto_widget_policy(
                DevPhase=SimpleNamespace(MAIN_SETTINGS="settings"),
                _auto_widget_signals=signals,
                _paused_screen_backdrop_bgr=lambda: None,
                active_tmdb_title_key=["Film"],
                apple_tv_auto_state={},
                dev_phase=["main"],
                main_settings_widget=None,
                skip_cache=[None],
            )

    def test_resolved_once_per_frame(self) -> None:
        signals = mock.Mock(return_value=object())
        with frame_scope.render_frame():
            a = self._policy(signals)
            b = self._policy(signals)
        self.assertIs(a, b)
        self.assertEqual(signals.call_count, 1)
        with frame_scope.render_frame():
            self._policy(signals)
        self.assertEqual(signals.call_count, 2)

    def test_outside_a_frame_always_recomputes(self) -> None:
        signals = mock.Mock(return_value=object())
        self._policy(signals)
        self._policy(signals)
        self.assertEqual(signals.call_count, 2)


if __name__ == "__main__":
    unittest.main()


class LivePaceTests(unittest.TestCase):
    def setUp(self) -> None:
        from pigeon.core import stage_render

        self.sr = stage_render
        stage_render._LIVE_PACE[0] = None

    def _run(self, frames, render_s, latency_s, stall_at=None):
        t, starts = 0.0, []
        for i in range(frames):
            starts.append(t)
            now = t + (0.5 if i == stall_at else render_s)
            d = self.sr._live_pace_delay_ms(t, now, 33)
            t = now + d / 1000.0 + latency_s
        return [b - a for a, b in zip(starts, starts[1:])]

    def test_timer_latency_does_not_stretch_the_cadence(self) -> None:
        iv = self._run(300, 0.022, 0.003)
        self.assertAlmostEqual(sum(iv) / len(iv), 0.033, delta=0.0006)

    def test_stall_reanchors_without_a_burst(self) -> None:
        iv = self._run(60, 0.022, 0.003, stall_at=20)
        after = iv[21:26]
        self.assertTrue(all(v > 0.025 for v in after), after)
