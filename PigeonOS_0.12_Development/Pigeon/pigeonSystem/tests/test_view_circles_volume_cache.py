"""A volume step reuses the cached volume-independent layers and draws identical pixels."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np



from tests.test_np_layout import _force_default_np_zones  # noqa: E402


def _widget():
    from pigeon.widgets.view_circles import ViewCirclesWidget

    _force_default_np_zones()
    assets = Path(__file__).resolve().parents[2] / "pigeonAssets"
    return ViewCirclesWidget(assets_dir=assets)


def _push(widget, volume_text: str) -> None:
    widget.update_state(
        progress=0.25,
        elapsed_text="0:10",
        remaining_text="-1:00",
        volume_text=volume_text,
        incoming_audio="MULTI-IN",
        playback_config="AURO3D",
        has_now_playing=True,
        has_position=True,
        content_active=True,
        paused=False,
        service_name="peacock",
        cast=[("Bill Murray", "Bob Wiley")],
    )


def _settled(volume_text: str):
    """A widget past the one-off fade/handoff transients that follow the first update."""
    w = _widget()
    # Pin the wall-clock fade so frames are comparable.
    w._volume_line_opacity = lambda now=None: 1.0
    _push(w, volume_text)
    w.bgra_frame()
    _push(w, "-41.0 dB")
    w.bgra_frame()
    _push(w, volume_text)
    w.bgra_frame()
    return w


class VolumeStaticBaseCacheTests(unittest.TestCase):
    def test_cached_base_equals_a_fresh_build(self) -> None:
        import datetime as dt
        import time
        from unittest import mock

        # Hold the wall clocks still so a rebuild is comparable to the cached layer.
        fixed = dt.datetime.now().replace(microsecond=0)
        mono = time.monotonic()
        with mock.patch(
            "pigeon.widgets.view_circles.time.monotonic", return_value=mono
        ), mock.patch("pigeon.widgets.view_circles.pigeon_now", return_value=fixed):
            w = _settled("-40.0 dB")
            for text in ("-39.5 dB", "-39.0 dB"):
                _push(w, text)
                w.bgra_frame()
            reused = w._static_base
            self.assertIsNotNone(reused)
            w._static_base = None
            w.clear_cache()
            w.bgra_frame()
            rebuilt = w._static_base
        self.assertIsNotNone(rebuilt)
        self.assertEqual(reused[0], rebuilt[0])
        self.assertTrue(np.array_equal(reused[1], rebuilt[1]))
        self.assertEqual(reused[2], rebuilt[2])

    def test_volume_step_keeps_the_cached_base(self) -> None:
        w = _settled("-40.0 dB")
        first = w._static_base
        self.assertIsNotNone(first)
        for text in ("-39.5 dB", "-39.0 dB", "-38.5 dB"):
            _push(w, text)
            w.bgra_frame()
        self.assertIs(w._static_base, first)

    def test_other_changes_rebuild_the_base(self) -> None:
        w = _settled("-40.0 dB")
        first = w._static_base
        w.update_state(
            progress=0.25, elapsed_text="0:10", remaining_text="-1:00",
            volume_text="-40.0 dB", has_now_playing=True, has_position=True,
            content_active=True, paused=True, service_name="peacock",
        )
        w.bgra_frame()
        self.assertIsNot(w._static_base, first)


class VolumeReadoutLayoutTests(unittest.TestCase):
    def test_readout_height_is_the_same_for_every_level(self) -> None:
        from pigeon.widgets.view_circles import VOLUME_INNER_R, _volume_readout_patch

        heights = {
            _volume_readout_patch(t, inner_r=VOLUME_INNER_R)[2]
            for t in ("-22", "-21.5", "-22.0", "-8", "-0.5", "-80", "12")
        }
        self.assertEqual(len(heights), 1)

    def test_disc_clock_does_not_move_with_the_level(self) -> None:
        w = _settled("-22.0 dB")
        w._assignments = lambda: ("", "", "volume", "visualizer", "status_bar")
        a = w._disc_clock_geometry()
        _push(w, "-21.5 dB")
        self.assertEqual(a, w._disc_clock_geometry())

    def test_music_layout_with_album_title_has_the_disc_clock(self) -> None:
        w = _widget()
        w._assignments = lambda: ("", "", "volume", "visualizer", "status_bar")
        w.update_state(
            progress=0.2, elapsed_text="0:10", remaining_text="-1:00",
            volume_text="-22.5 dB", has_now_playing=True, has_position=True,
            content_active=True, content_mode="music", song_title="Song",
            album_title="Red", artist_title="Artist", service_name="spotify",
        )
        self.assertTrue(w._clock_in_volume_disc())
        self.assertIsNotNone(w._disc_clock_geometry())


if __name__ == "__main__":
    unittest.main()
