"""Playback clock must pick up a new duration when the title stays the same."""

from __future__ import annotations

import os
import sys
import unittest

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.core import now_playing as np_mod  # noqa: E402


def _poll(clk: dict, *, total: float | None, position: float) -> None:
    np_mod._apply_playback_clock_from_poll(
        {
            "device_state": "DeviceState.Playing",
            "title": "The Social Network",
            "total_time": total,
            "position": position,
        },
        _content_key_from_metadata=lambda md: "the social network|auto|The Social Network",
        apple_tv_playback_clock=clk,
        last_timecode_motion_mono=[0.0],
    )


class AdThenMovieLatchTests(unittest.TestCase):
    def test_movie_duration_replaces_ad_duration(self) -> None:
        clk: dict = {}
        _poll(clk, total=143.0, position=10.0)  # Tubi ad, same title
        self.assertEqual(clk["latched_total"], 143.0)
        _poll(clk, total=7240.0, position=5.0)  # movie resumes
        self.assertEqual(clk["latched_total"], 7240.0)
        frac = np_mod._playback_progress_fraction_for_bar(apple_tv_playback_clock=clk)
        self.assertIsNotNone(frac)
        self.assertLess(frac, 0.01)
        played, remaining = np_mod._playback_extrapolated_pair(apple_tv_playback_clock=clk)
        self.assertGreater(remaining, 7000)

    def test_small_duration_jitter_keeps_latch(self) -> None:
        clk: dict = {}
        _poll(clk, total=7240.0, position=100.0)
        _poll(clk, total=7241.5, position=101.0)
        self.assertEqual(clk["latched_total"], 7240.0)

    def test_missing_total_keeps_latch(self) -> None:
        clk: dict = {}
        _poll(clk, total=7240.0, position=100.0)
        _poll(clk, total=None, position=101.0)
        self.assertEqual(clk["latched_total"], 7240.0)


if __name__ == "__main__":
    unittest.main()
