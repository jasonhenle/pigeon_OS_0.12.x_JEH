"""Zone-4 EQ visualizer: band count vs position, toggle / config, rendering."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import zone4_eq  # noqa: E402


def _params(**over: object) -> dict[str, object]:
    p = dict(zone4_eq.DEFAULT_PARAMS)
    p.update(over)
    return p


class TargetBandsTests(unittest.TestCase):
    def test_ramp_up_spans_min_to_max(self) -> None:
        p = _params(minBands=4, maxBands=48)
        self.assertEqual(zone4_eq.target_bands(p, 0.0), 4)
        self.assertEqual(zone4_eq.target_bands(p, 1.0), 48)
        self.assertEqual(zone4_eq.target_bands(p, 0.5), 26)

    def test_gamma_holds_low_counts_longer(self) -> None:
        p = _params(minBands=67, maxBands=178, gamma=3.4)
        self.assertLess(zone4_eq.target_bands(p, 0.5), 80)

    def test_arc_peaks_mid_program(self) -> None:
        p = _params(shape="arc", minBands=3, maxBands=96)
        self.assertEqual(zone4_eq.target_bands(p, 0.5), 96)
        self.assertEqual(zone4_eq.target_bands(p, 0.0), 3)

    def test_powers_of_two(self) -> None:
        p = _params(quantize="powers of 2", minBands=2, maxBands=128)
        for x in (0.1, 0.3, 0.7, 0.95):
            n = int(zone4_eq.target_bands(p, x))
            self.assertEqual(n & (n - 1), 0, n)

    def test_random_chapters_are_stable(self) -> None:
        p = _params(shape="random chapters", cycles=8)
        self.assertEqual(zone4_eq.target_bands(p, 0.26), zone4_eq.target_bands(p, 0.37))


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / zone4_eq.CONFIG_NAME
        self._patch = mock.patch.object(zone4_eq, "config_path", return_value=self.path)
        self._patch.start()
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        os.environ.pop("PIGEON_ZONE4_EQ", None)
        zone4_eq._cfg_checked = 0.0
        zone4_eq._cfg_mtime = -1

    def tearDown(self) -> None:
        self._env.stop()
        self._patch.stop()
        self._tmp.cleanup()
        zone4_eq._cfg_checked = 0.0
        zone4_eq._cfg_mtime = -1

    def test_settings_option4_turns_it_on(self) -> None:
        from pigeon.widgets import options_settings

        with mock.patch.object(options_settings, "read_options", return_value={"zone4_mode": "info"}):
            self.assertFalse(zone4_eq.enabled())
        with mock.patch.object(
            options_settings, "read_options", return_value={"zone4_mode": "visualizer"}
        ):
            self.assertTrue(zone4_eq.enabled())

    def test_env_overrides_toggle(self) -> None:
        from pigeon.widgets import options_settings

        os.environ["PIGEON_ZONE4_EQ"] = "0"
        with mock.patch.object(
            options_settings, "read_options", return_value={"zone4_mode": "visualizer"}
        ):
            self.assertFalse(zone4_eq.enabled())
        os.environ["PIGEON_ZONE4_EQ"] = "1"
        self.assertTrue(zone4_eq.enabled())

    def test_lab_json_sets_params(self) -> None:
        self.path.write_text(json.dumps({"minBands": 50, "maxBands": 50}))
        self.assertEqual(zone4_eq.params()["minBands"], 50)
        self.assertEqual(zone4_eq.params()["fMin"], zone4_eq.DEFAULT_PARAMS["fMin"])


class InputGainTests(unittest.TestCase):
    """Visualizer input gain: auto gain steers program loudness toward a target, plus a trim."""

    SR = 48_000.0

    def setUp(self) -> None:
        self._p = _params()
        patch = mock.patch.object(zone4_eq, "params", side_effect=lambda: self._p)
        patch.start()
        self.addCleanup(patch.stop)
        zone4_eq.reset_input_gain()
        self.addCleanup(zone4_eq.reset_input_gain)
        self._rng = np.random.default_rng(0)

    def _feed(self, rms_db: float, seconds: float) -> None:
        amp = 10.0 ** (rms_db / 20.0)
        for _ in range(int(seconds * 30)):
            x = self._rng.standard_normal(1600) * amp
            zone4_eq.feed_pcm_stereo(x, x, self.SR)

    def _read_db(self) -> float:
        x = zone4_eq.latest_samples(4800)
        return 10.0 * float(np.log10((x * x).mean() + 1e-12))

    def test_quiet_program_is_lifted_to_the_target(self) -> None:
        self._feed(-40.0, 3.0)
        self.assertAlmostEqual(zone4_eq.input_gain_db(), 20.0, delta=0.5)
        self.assertAlmostEqual(self._read_db(), -20.0, delta=0.5)

    def test_loud_program_is_cut_up_to_the_limit(self) -> None:
        self._feed(-12.0, 3.0)
        self.assertAlmostEqual(zone4_eq.input_gain_db(), -8.0, delta=0.5)
        zone4_eq.reset_input_gain()
        self._feed(-3.0, 3.0)
        self.assertAlmostEqual(zone4_eq.input_gain_db(), -12.0, delta=0.01)  # inputMaxCutDb

    def test_boost_is_capped(self) -> None:
        self._feed(-58.0, 3.0)
        self.assertAlmostEqual(zone4_eq.input_gain_db(), 30.0, delta=0.01)  # inputMaxBoostDb

    def test_silence_holds_the_gain(self) -> None:
        self._feed(-40.0, 3.0)
        g = zone4_eq.input_gain_db()
        self._feed(-80.0, 5.0)  # below inputGateDb: hiss between tracks
        self.assertAlmostEqual(zone4_eq.input_gain_db(), g, delta=0.01)

    def test_gain_drops_fast_and_climbs_slowly(self) -> None:
        self._feed(-40.0, 3.0)
        self._feed(-20.0, 1.5)  # louder: follows within a couple of rise constants
        self.assertLess(zone4_eq.input_gain_db(), 2.0)
        self._feed(-40.0, 1.5)  # quieter again: only part of the way back up
        self.assertLess(zone4_eq.input_gain_db(), 8.0)

    def test_trim_adds_and_auto_can_be_off(self) -> None:
        self._feed(-40.0, 3.0)
        self._p = _params(inputTrimDb=-6.0)
        self.assertAlmostEqual(zone4_eq.input_gain_db(), 14.0, delta=0.5)
        self._p = _params(inputAutoGain=False, inputTrimDb=6.0)
        self.assertAlmostEqual(zone4_eq.input_gain_db(), 6.0)
        self.assertAlmostEqual(self._read_db(), -34.0, delta=0.5)

    def test_gain_clips_at_full_scale(self) -> None:
        self._p = _params(inputAutoGain=False, inputTrimDb=40.0)
        self._feed(-20.0, 0.2)
        self.assertLessEqual(float(np.abs(zone4_eq.latest_samples(4800)).max()), 1.0)


class RenderTests(unittest.TestCase):
    TRACK = (113, 536, 1067, 100, 13)

    def setUp(self) -> None:
        self._patches = [
            mock.patch.object(zone4_eq, "want_mic_capture", lambda: None),
            mock.patch.object(
                zone4_eq,
                "params",
                return_value=_params(
                    minBands=20, maxBands=20, colA="#ff6a00",
                    peaks=True, fftSize="4096",
                ),
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()

    def _feed_tone(self, hz: float) -> None:
        t = np.arange(16384) / 48_000.0
        zone4_eq.feed_pcm(0.5 * np.sin(2 * np.pi * hz * t), 48_000.0)

    def test_tone_lights_elapsed_bars_in_accent(self) -> None:
        eq = zone4_eq.Zone4EQ()
        out = np.zeros((800, 1280, 3), dtype=np.uint8)
        for _ in range(10):
            self._feed_tone(1000.0)
            eq.render_into(out, self.TRACK, progress=1.0)
            time.sleep(0.005)
        x, y, w, h, _r = self.TRACK
        zone = out[y : y + h, x : x + w].astype(int)
        orange = (zone[:, :, 2] > 200) & (zone[:, :, 1] > 80) & (zone[:, :, 0] < 60)
        self.assertGreater(int(orange.sum()), 200)
        # Outside the track stays untouched.
        self.assertEqual(int(out[: y - 1].sum()), 0)

    def test_no_status_info_in_zone4(self) -> None:
        """Lab progress fill / playhead keys are ignored; only the container shows."""
        eq = zone4_eq.Zone4EQ()
        out = np.zeros((800, 1280, 3), dtype=np.uint8)
        over = _params(progressBg=True, showPlayhead=True, trackFill="#ff0000",
                       minLevel=0.0, peaks=False)
        with mock.patch.object(zone4_eq, "params", return_value=over):
            eq.render_into(out, self.TRACK, progress=0.5, track_bgr=(35, 35, 35))
        x, y, w, _h, _r = self.TRACK
        row = y + 8  # above the (silent) bars
        for cx in (x + w // 4, x + w // 2, x + 3 * w // 4):
            self.assertEqual(tuple(int(v) for v in out[row, cx]), (35, 35, 35))

    def test_butterfly_puts_left_bass_center_and_right_treble_outside(self) -> None:
        eq = zone4_eq.Zone4EQ()
        out = np.zeros((800, 1280, 3), dtype=np.uint8)
        over = _params(stereoMode="butterfly (bass center)", minBands=24, maxBands=24,
                       stereoColor="channel colors", colL="#00ff00", colR="#ff0000", minLevel=0.0,
                       peaks=False, showTrack=False, autoGain=True, splitGapPx=20, barRadius=30)
        t = np.arange(16384) / 48_000.0
        with mock.patch.object(zone4_eq, "params", return_value=over):
            for _ in range(10):
                zone4_eq.feed_pcm_stereo(0.5 * np.sin(2 * np.pi * 80 * t),
                                         0.5 * np.sin(2 * np.pi * 6000 * t), 48_000.0)
                eq.render_into(out, self.TRACK, progress=0.5)
                time.sleep(0.005)
        x, y, w, h, _r = self.TRACK
        zone = out[y : y + h, x : x + w].astype(int)
        green_cols = np.where((zone[:, :, 1] > 150).any(axis=0))[0]
        red_cols = np.where((zone[:, :, 2] > 150).any(axis=0))[0]
        self.assertTrue(green_cols.size and red_cols.size)
        # L (green) bass sits just left of center; R (red) treble toward the right edge.
        self.assertTrue(w * 0.3 < green_cols.mean() < w * 0.5, green_cols.mean())
        self.assertGreater(red_cols.mean(), w * 0.7)

    def test_bgra_output_gets_alpha(self) -> None:
        eq = zone4_eq.Zone4EQ()
        out = np.zeros((800, 1280, 4), dtype=np.uint8)
        self._feed_tone(250.0)
        eq.render_into(out, self.TRACK, progress=0.3)
        x, y, w, h, _r = self.TRACK
        self.assertEqual(int(out[y + h // 2, x + w // 2, 3]), 255)


class ViewCirclesZone4Tests(unittest.TestCase):
    ZONES = ("tt_countdown_16x9", "", "volume", "cast_info", "status_bar")

    def _widget(self, *, visualizer: bool):
        from pigeon.widgets import view_circles
        from pigeon.widgets.view_circles import ViewCirclesWidget

        assets = Path(__file__).resolve().parents[2] / "pigeonAssets"
        w = ViewCirclesWidget(assets_dir=assets)
        w._state.cast = [("Actor One", "Role One"), ("Actor Two", "Role Two")]
        w.update_state(
            progress=0.4,
            elapsed_text="40:00",
            remaining_text="-1:28:00",
            volume_text="-22.5 dB",
            has_now_playing=True,
            has_position=True,
            content_active=True,
            content_mode="video",
        )
        env = mock.patch.dict(os.environ, {"PIGEON_ZONE4_EQ": "1" if visualizer else "0"})
        env.start()
        self.addCleanup(env.stop)
        patch = mock.patch.object(view_circles, "_effective_zone_widgets", return_value=self.ZONES)
        patch.start()
        self.addCleanup(patch.stop)
        mic = mock.patch.object(zone4_eq, "want_mic_capture", lambda: None)
        mic.start()
        self.addCleanup(mic.stop)
        return w

    def test_toggle_swaps_cast_for_visualizer(self) -> None:
        from pigeon.widgets.view_circles import ZONE4_VISUALIZER_WIDGET

        self.assertEqual(self._widget(visualizer=False)._assignments()[3], "cast_info")
        w = self._widget(visualizer=True)
        self.assertEqual(w._assignments()[3], ZONE4_VISUALIZER_WIDGET)
        self.assertEqual(w._assignments()[4], "status_bar")
        self.assertTrue(w.wants_live_audio())

    def test_visualizer_paints_zone4_and_cti_moves_to_zone5(self) -> None:
        from pigeon.widgets.view_circles import zone4_visualizer_rect

        x, y, w, h, _r = zone4_visualizer_rect()
        self.assertEqual((x, y, w, h), (113, 536, 1067, 100))
        over = _params(minLevel=0.0, peaks=False, showTrack=True)
        with mock.patch.object(zone4_eq, "params", return_value=over):
            on = self._widget(visualizer=True).bgra_frame()
        off = self._widget(visualizer=False).bgra_frame()
        assert on is not None and off is not None
        # No container fill: the page shows between the meters, arcs still drawn.
        page = tuple(int(v) for v in on[y - 6, x + w // 2, :3])
        self.assertEqual(tuple(int(v) for v in on[y + h // 2, x + w // 2, :3]), page)
        arcs = np.abs(on[y : y + h, x : x + w, :3].astype(int) - page).max(axis=2) > 20
        self.assertGreater(int(np.count_nonzero(arcs)), 500)
        # Zone 5: the only difference is a 2 px white CTI at 40% of the track.
        cti = x + int(round(0.4 * w))
        mid = 646 + 65 // 2
        self.assertEqual(tuple(int(v) for v in on[mid, cti - 1 : cti + 1, :3].reshape(-1)), (255,) * 6)
        self.assertNotEqual(tuple(int(v) for v in off[mid, cti, :3]), (255, 255, 255))
        below = slice(y + h + 5, None)
        diff = np.any(on[below, :, :3] != off[below, :, :3], axis=(0, 2))
        self.assertEqual(sorted(np.where(diff)[0].tolist()), [cti - 1, cti])


class YouTubeZone4Tests(unittest.TestCase):
    """The zone-4 toggle applies to the YouTube layout, whose zone 4 is the video title."""

    def _widget(self, *, visualizer: bool):
        from pigeon.widgets.view_circles import ViewCirclesWidget

        env = mock.patch.dict(os.environ, {"PIGEON_ZONE4_EQ": "1" if visualizer else "0"})
        env.start()
        self.addCleanup(env.stop)
        mic = mock.patch.object(zone4_eq, "want_mic_capture", lambda: None)
        mic.start()
        self.addCleanup(mic.stop)
        assets = Path(__file__).resolve().parents[2] / "pigeonAssets"
        w = ViewCirclesWidget(assets_dir=assets)
        w.update_state(
            progress=0.2,
            elapsed_text="0:10",
            remaining_text="-1:00",
            volume_text="-22.5 dB",
            has_now_playing=True,
            has_position=True,
            content_active=True,
            content_mode="video",
            is_youtube=True,
            song_title="Never Gonna Give You Up",
            artist_title="Rick Astley",
            poster_bgra=np.full((90, 160, 3), (0, 255, 0), dtype=np.uint8),
        )
        return w

    def test_toggle_swaps_video_title_for_visualizer(self) -> None:
        from pigeon.np_layout import YOUTUBE_ZONE_WIDGETS
        from pigeon.widgets.view_circles import ZONE4_VISUALIZER_WIDGET

        self.assertEqual(self._widget(visualizer=False)._assignments(), YOUTUBE_ZONE_WIDGETS)
        w = self._widget(visualizer=True)
        zones = w._assignments()
        self.assertEqual(zones[3], ZONE4_VISUALIZER_WIDGET)
        self.assertEqual((zones[2], zones[4]), (YOUTUBE_ZONE_WIDGETS[2], YOUTUBE_ZONE_WIDGETS[4]))
        self.assertEqual(w._poster_zone(), 6)  # thumbnail stays
        self.assertTrue(w.wants_live_audio())

    def test_visualizer_replaces_the_title_in_the_frame(self) -> None:
        from pigeon.widgets.view_circles import _zone4_title_xywh, zone4_visualizer_rect

        zx, zy, zw, zh = _zone4_title_xywh()
        title = self._widget(visualizer=False).bgra_frame()
        viz = self._widget(visualizer=True).bgra_frame()
        assert title is not None and viz is not None
        lit = lambda f: int(np.count_nonzero(f[zy : zy + zh, zx : zx + zw, :3].min(axis=2) > 180))  # noqa: E731
        self.assertGreater(lit(title), 300)  # white title text
        x, y, w, h, _r = zone4_visualizer_rect()
        # No container fill: the poster blur shows through between the meters.
        self.assertEqual(tuple(int(v) for v in viz[y + h // 2, x + w // 2, :3]), tuple(int(v) for v in viz[y - 6, x + w // 2, :3]))
        # No title text anywhere in zone 4 (in or around the container).
        self.assertLess(lit(viz), 50)


if __name__ == "__main__":
    unittest.main()
