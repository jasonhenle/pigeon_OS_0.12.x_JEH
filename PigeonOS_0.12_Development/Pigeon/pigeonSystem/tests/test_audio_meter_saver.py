"""Diagnostic SVG stereo meter: mapping + LED-segment visibility."""

from __future__ import annotations

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

from pigeon.widgets import audio_meter_saver as am  # noqa: E402


class AudioMeterMappingTests(unittest.TestCase):
    def test_thresholds_are_ten_and_increasing(self) -> None:
        self.assertEqual(len(am.METER_SEGMENT_THRESHOLDS_DBFS), 10)
        seq = list(am.METER_SEGMENT_THRESHOLDS_DBFS)
        self.assertEqual(seq, sorted(seq))

    def test_silence_is_zero_segments(self) -> None:
        self.assertEqual(am.meter_segments_from_dbfs(-120.0), 0)
        self.assertEqual(am.meter_segments_from_dbfs(-48.01), 0)

    def test_each_threshold_lights_that_segment(self) -> None:
        for i, thr in enumerate(am.METER_SEGMENT_THRESHOLDS_DBFS, start=1):
            self.assertEqual(am.meter_segments_from_dbfs(thr), i)
            self.assertEqual(am.meter_segments_from_dbfs(thr + 0.01), i)

    def test_just_below_next_threshold_holds(self) -> None:
        # Written against the thresholds table so a retune (see the 2026-09-15
        # note on METER_SEGMENT_THRESHOLDS_DBFS) cannot silently void it.
        marks = am.METER_SEGMENT_THRESHOLDS_DBFS
        for i, thr in enumerate(marks, start=1):
            self.assertEqual(am.meter_segments_from_dbfs(thr - 0.01), i - 1)
            self.assertEqual(am.meter_segments_from_dbfs(thr), i)
            if i < len(marks):
                self.assertEqual(am.meter_segments_from_dbfs((thr + marks[i]) / 2.0), i)
        self.assertEqual(am.meter_segments_from_dbfs(marks[-1] + 6.0), len(marks))

    def test_retuned_marks_leave_headroom_for_program_material(self) -> None:
        # 2026-09-15 retune: the -3 dB test tone (cal ≈ -3) sits mid-scale and
        # typical program (cal ≈ +4) is high but not pinned; only peaks reach 10.
        self.assertEqual(am.meter_segments_from_dbfs(-3.0), 5)
        self.assertEqual(am.meter_segments_from_dbfs(4.0), 7)
        self.assertLess(am.meter_segments_from_dbfs(9.0), len(am.METER_SEGMENT_THRESHOLDS_DBFS))

    def test_not_a_linear_0_1_amplitude_map(self) -> None:
        # -20 dBFS is ~0.1 linear. A naive *10 map would show 1 LED; the dB
        # marks put a quiet-but-present signal higher than that.
        dbfs = -20.0
        linear = 10 ** (dbfs / 20.0)
        naive = int(round(linear * 10.0))
        self.assertLess(naive, 4)
        self.assertGreater(am.meter_segments_from_dbfs(dbfs), naive)
        # ...and the map is in dB: equal dB steps never skip a mark's worth of LEDs.
        lit = [am.meter_segments_from_dbfs(d) for d in range(-48, 14)]
        self.assertEqual(lit, sorted(lit))
        self.assertTrue(all(b - a <= 1 for a, b in zip(lit, lit[1:])))


class AudioMeterSvgTests(unittest.TestCase):
    def test_asset_exists_with_named_shapes(self) -> None:
        path = am.default_audio_meter_svg_path()
        self.assertTrue(path.is_file(), f"missing {path}")
        root = am.svg_tree_from_path(path)
        self.assertIsNotNone(am.find_meter_element(root, "left_meter_group"))
        # Illustrator export currently misspells the right group id.
        self.assertIsNotNone(
            am.find_meter_element(root, "right_meter_group", "right_meter_grouop")
        )
        for side in ("left", "right"):
            for i in range(1, 11):
                el = am.find_meter_element(root, am.meter_shape_id(side, i))
                self.assertIsNotNone(el, am.meter_shape_id(side, i))

    def test_authored_led_colors_are_preserved(self) -> None:
        root = am.svg_tree_from_path()
        green = "#39b54a"
        yellow = "#fff200"
        red = "#d60000"
        for side in ("left", "right"):
            for i in range(1, 8):
                el = am.find_meter_element(root, am.meter_shape_id(side, i))
                self.assertEqual((el.get("fill") or "").lower(), green)
            for i in (8, 9):
                el = am.find_meter_element(root, am.meter_shape_id(side, i))
                self.assertEqual((el.get("fill") or "").lower(), yellow)
            el = am.find_meter_element(root, am.meter_shape_id(side, 10))
            self.assertEqual((el.get("fill") or "").lower(), red)
        fills_before = {
            (side, i): am.find_meter_element(root, am.meter_shape_id(side, i)).get("fill")
            for side in ("left", "right")
            for i in range(1, 11)
        }
        am.apply_meter_leds(root, 10, 10)
        am.apply_meter_leds(root, 3, 0)
        for side in ("left", "right"):
            for i in range(1, 11):
                el = am.find_meter_element(root, am.meter_shape_id(side, i))
                self.assertEqual(el.get("fill"), fills_before[(side, i)])

    def test_led_visibility_is_cumulative(self) -> None:
        root = am.svg_tree_from_path()
        am.apply_meter_leds(root, 0, 7)
        for i in range(1, 11):
            left = am.find_meter_element(root, am.meter_shape_id("left", i))
            right = am.find_meter_element(root, am.meter_shape_id("right", i))
            self.assertEqual(left.get("opacity"), "0")
            if i <= 7:
                self.assertNotEqual(right.get("opacity"), "0")
            else:
                self.assertEqual(right.get("opacity"), "0")
        am.apply_meter_leds(root, 10, 1)
        for i in range(1, 11):
            left = am.find_meter_element(root, am.meter_shape_id("left", i))
            right = am.find_meter_element(root, am.meter_shape_id("right", i))
            self.assertNotEqual(left.get("opacity"), "0")
            if i == 1:
                self.assertNotEqual(right.get("opacity"), "0")
            else:
                self.assertEqual(right.get("opacity"), "0")

    @staticmethod
    def _continuous_tree():
        import xml.etree.ElementTree as ET

        root = ET.Element("svg")
        g = ET.SubElement(root, "g", id="continuous_meter_group")
        for name in (
            am.meter_bar_id("left"), am.meter_bar_id("right"),
            am.lfe_shape_id("left"), am.lfe_shape_id("right"), "background",
        ):
            ET.SubElement(g, "rect", id=name)
        return root

    def test_prune_removes_hidden_continuous_bars_and_lfe_slabs(self) -> None:
        # The live face is continuous bars + LFE slabs; the per-LED shapes are
        # legacy and no longer pruned. (Synthetic tree: the committed asset is
        # the legacy LED art, which has none of these ids.)
        root = self._continuous_tree()
        for name in (am.meter_bar_id("left"), am.lfe_shape_id("right")):
            am.find_meter_element(root, name).set("opacity", "0")
        am.find_meter_element(root, "background").set("opacity", "0")  # not a meter shape
        am._prune_hidden_meter_shapes(root)
        self.assertIsNone(am.find_meter_element(root, am.meter_bar_id("left")))
        self.assertIsNone(am.find_meter_element(root, am.lfe_shape_id("right")))
        self.assertIsNotNone(am.find_meter_element(root, am.meter_bar_id("right")))  # visible: kept
        self.assertIsNotNone(am.find_meter_element(root, am.lfe_shape_id("left")))
        self.assertIsNotNone(am.find_meter_element(root, "background"))

    def test_prune_also_drops_display_none_bars(self) -> None:
        root = self._continuous_tree()
        am.find_meter_element(root, am.meter_bar_id("right")).set("display", "none")
        am._prune_hidden_meter_shapes(root)
        self.assertIsNone(am.find_meter_element(root, am.meter_bar_id("right")))
        self.assertIsNotNone(am.find_meter_element(root, am.meter_bar_id("left")))

    def test_prune_leaves_legacy_led_shapes_alone(self) -> None:
        root = am.svg_tree_from_path()
        am.apply_meter_leds(root, 2, 0)
        before = len(list(root.iter()))
        am._prune_hidden_meter_shapes(root)
        self.assertEqual(len(list(root.iter())), before)


class AudioMeterRasterTests(unittest.TestCase):
    def test_raster_lights_left_without_right(self) -> None:
        try:
            import fitz  # noqa: F401
        except ImportError:
            self.skipTest("PyMuPDF required to rasterize meter SVG")
        if am.find_meter_element(am.svg_tree_from_path(), am.meter_bar_id("left")) is None:
            self.skipTest(
                f"{am.default_audio_meter_svg_path().name} has no continuous "
                f"'{am.meter_bar_id('left')}' bar (the *_withLFE.svg art is not in the repo)"
            )
        am.clear_audio_meter_render_caches()
        dark = am.render_audio_meter_bgra(left_fill=0.0, right_fill=0.0).copy()
        left = am.render_audio_meter_bgra(left_fill=0.7, right_fill=0.0).copy()
        self.assertEqual(dark.shape[:2], (800, 1280))
        self.assertGreater(int(np.abs(left.astype(np.int16) - dark.astype(np.int16)).sum()), 0)
        # Left column (~x 548–596) should change; right column (~x 684–732) should not.
        left_band = np.abs(left[:, 548:597].astype(np.int16) - dark[:, 548:597].astype(np.int16)).sum()
        right_band = np.abs(left[:, 684:733].astype(np.int16) - dark[:, 684:733].astype(np.int16)).sum()
        self.assertGreater(int(left_band), int(right_band) * 10)


def _meter(*, fill: float, cal_dbfs: float = -20.0) -> am.MeterLevels:
    return am.MeterLevels(
        rms_l=0.1,
        rms_r=0.1,
        env_l=0.1,
        env_r=0.1,
        dbfs_l=cal_dbfs,
        dbfs_r=cal_dbfs,
        cal_dbfs_l=cal_dbfs,
        cal_dbfs_r=cal_dbfs,
        fill_l=fill,
        fill_r=fill,
        seg_l=3,
        seg_r=3,
        rms_lfe=0.0,
        env_lfe=0.0,
        lfe_fill=0.0,
    )


class ProgramAudioPresentTests(unittest.TestCase):
    def tearDown(self) -> None:
        am._latest = am._SILENCE
        am._last_pcm_mono = 0.0
        am._capture_dead = False
        am._reset_program_audio_hiss()

    def test_session_hold_outlasts_short_gate(self) -> None:
        now = time.monotonic()
        am._latest = am._SILENCE
        am._last_pcm_mono = now
        am._capture_dead = False
        am._program_audio_until = now - 0.1
        am._program_audio_session_until = now + 60.0
        self.assertFalse(am.program_audio_present())
        self.assertTrue(am.program_audio_session_present())

    def test_loud_fill_arms_session_hold(self) -> None:
        now = time.monotonic()
        am._latest = _meter(fill=0.2)
        am._last_pcm_mono = now
        am._capture_dead = False
        am._program_audio_until = 0.0
        am._program_audio_session_until = 0.0
        self.assertTrue(am.program_audio_present())
        self.assertTrue(am.program_audio_session_present())
        self.assertGreater(am._program_audio_session_until, now + 60.0)

    def _feed_steady_fill(self, fill: float, *, seconds: float = 8.0) -> float:
        t0 = time.monotonic()
        last = t0
        steps = int(seconds / am.HISS_NOTE_S) + 2
        for i in range(steps):
            last = t0 + i * am.HISS_NOTE_S
            am._note_program_fill(fill, now=last)
        return last

    def test_persistent_hiss_is_not_program_audio(self) -> None:
        now = time.monotonic()
        self._feed_steady_fill(0.08)
        am._latest = _meter(fill=0.08, cal_dbfs=-48.0)
        am._last_pcm_mono = now
        am._capture_dead = False
        am._program_audio_until = now + 2.0
        am._program_audio_session_until = now + 90.0
        self.assertTrue(am.persistent_hiss_present())
        self.assertFalse(am.program_audio_present())
        self.assertFalse(am.program_audio_session_present())
        self.assertEqual(am._program_audio_session_until, 0.0)

    def test_steady_hiss_never_arms_session_hold(self) -> None:
        now = time.monotonic()
        self._feed_steady_fill(0.09, seconds=0.7)
        am._latest = _meter(fill=0.09, cal_dbfs=-48.0)
        am._last_pcm_mono = now
        self.assertTrue(am.program_audio_present())
        self.assertEqual(am._program_audio_session_until, 0.0)
        self._feed_steady_fill(0.09)
        self.assertTrue(am.persistent_hiss_present())
        self.assertFalse(am.program_audio_present())
        self.assertFalse(am.program_audio_session_present())

    def test_program_hit_clears_hiss(self) -> None:
        last = self._feed_steady_fill(0.08)
        self.assertTrue(am.persistent_hiss_present())
        # Two note periods on: exactly one is 0.0999999… at this clock's magnitude
        # and the rate limiter would swallow the hit.
        hit_at = last + 2 * am.HISS_NOTE_S
        am._note_program_fill(0.55, now=hit_at)
        am._latest = _meter(fill=0.55)
        am._last_pcm_mono = time.monotonic()
        self.assertFalse(am.persistent_hiss_present(now=hit_at))
        self.assertTrue(am.program_audio_present())
        self.assertTrue(am.program_audio_session_present())


class StereoMeterWidgetLayoutTests(unittest.TestCase):
    def test_volume_band_is_the_lower_fifth(self) -> None:
        self.assertEqual(am.stereo_meter_volume_band_h(400), 88)
        self.assertEqual(am.stereo_meter_volume_band_h(488), 107)

    def test_bars_stay_above_volume_band(self) -> None:
        try:
            import fitz  # noqa: F401
        except ImportError:
            self.skipTest("PyMuPDF required to rasterize meter SVG")
        if not am.default_audio_meter_svg_path().is_file():
            self.skipTest("meter SVG not in this tree")
        am.clear_audio_meter_render_caches()
        h = 400
        patch = am.render_stereo_meter_widget_bgra(
            200, h, left_fill=1.0, right_fill=1.0
        )
        ys = np.where(patch[:, :, 3] > 16)[0]
        self.assertGreater(int(ys.size), 50)
        reserve = am.stereo_meter_volume_band_h(h)
        self.assertLess(int(ys.max()), h - reserve + 2)
        self.assertLess(float(ys.mean()), h * 0.45)


class TitleMeterCalTests(unittest.TestCase):
    def setUp(self) -> None:
        am.reset_meter_title_calibration(persist=False)

    def tearDown(self) -> None:
        am.reset_meter_title_calibration(persist=False)

    def test_content_key_requires_a_title(self) -> None:
        self.assertEqual(am.meter_content_key(title=""), "")
        self.assertEqual(
            am.meter_content_key(title="Popstar", artist="", mode="video"),
            "video|popstar|",
        )

    def test_new_title_does_not_boost_during_warmup(self) -> None:
        am.set_meter_content_key("video|popstar|")
        am.note_title_peak_db(-18.0, -18.0, -30.0)
        self.assertEqual(am.title_meter_gain_db(), 0.0)

    def test_loud_peak_cuts_immediately(self) -> None:
        am.set_meter_content_key("video|popstar|")
        am.note_title_peak_db(18.0, 16.0, 10.0)
        gain = am.title_meter_gain_db()
        self.assertAlmostEqual(gain, am.TITLE_CAL_TARGET_DB - 18.0, places=5)
        raw = am.meter_fill_from_calibrated_dbfs(18.0)
        shown = am.title_calibrated_fill(18.0)
        self.assertLess(shown, raw)
        self.assertGreater(shown, 0.7)

    def test_quiet_title_boosts_after_warmup(self) -> None:
        am.set_meter_content_key("video|quiet film|")
        am.note_title_peak_db(-12.0, -12.0, -20.0)
        am._title_since_mono = time.monotonic() - 20.0
        gain = am.title_meter_gain_db()
        self.assertGreater(gain, 0.0)
        self.assertAlmostEqual(
            gain,
            min(am.TITLE_CAL_MAX_BOOST_DB, am.TITLE_CAL_TARGET_DB - (-12.0)),
            places=5,
        )

    def test_title_change_isolates_peaks(self) -> None:
        am.set_meter_content_key("video|loud|")
        am.note_title_peak_db(16.0, 16.0, 8.0)
        am.set_meter_content_key("video|quiet|")
        self.assertLess(am._title_peak_db, am.TITLE_CAL_MIN_PEAK_DB)
        am.set_meter_content_key("video|loud|")
        self.assertAlmostEqual(am._title_peak_db, 16.0, places=5)


if __name__ == "__main__":
    unittest.main()


def _card(root: Path, index: int, card_id: str, pcms: tuple[str, ...], *, usb: bool = False) -> None:
    card = root / f"card{index}"
    card.mkdir()
    (card / "id").write_text(card_id + "\n")
    for pcm in pcms:
        (card / pcm).mkdir()
    if usb:
        (card / "usbid").write_text("0d8c:0014\n")


class CaptureDeviceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pi_without_usb_interface_has_no_capture(self) -> None:
        _card(self.root, 0, "Headphones", ("pcm0p",))
        _card(self.root, 1, "vc4hdmi0", ("pcm0p",))
        _card(self.root, 2, "vc4hdmi1", ("pcm0p",))
        self.assertEqual(am._capture_devices(self.root), [])

    def test_usb_capture_is_named_not_numbered(self) -> None:
        _card(self.root, 0, "Headphones", ("pcm0p",))
        _card(self.root, 1, "vc4hdmi0", ("pcm0p",))
        _card(self.root, 3, "Device", ("pcm0p", "pcm0c"), usb=True)
        self.assertEqual(am._capture_devices(self.root), ["hw:CARD=Device,DEV=0"])

    def test_usb_card_wins_over_lower_numbered_capture(self) -> None:
        _card(self.root, 0, "Loopback", ("pcm0c", "pcm1c"))
        _card(self.root, 4, "Device", ("pcm0c",), usb=True)
        self.assertEqual(
            am._capture_devices(self.root),
            ["hw:CARD=Device,DEV=0", "hw:CARD=Loopback,DEV=0", "hw:CARD=Loopback,DEV=1"],
        )

    def test_env_override_wins(self) -> None:
        with mock.patch.dict(os.environ, {"PIGEON_ALSA_CAPTURE_DEVICE": "hw:5,0"}):
            self.assertEqual(am._alsa_device(), "hw:5,0")

    def test_reaper_matches_our_argv_on_any_device(self) -> None:
        argv = am._arecord_argv("/usr/bin/arecord", "hw:CARD=Device,DEV=0", low_latency=True)
        self.assertTrue(am._cmdline_looks_like_arecord(" ".join(argv)))
        self.assertFalse(am._cmdline_looks_like_arecord("arecord -D hw:1,0 take.wav"))
