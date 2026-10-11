"""HDMI stay-alert, identity confidence, and zone fallbacks."""

from __future__ import annotations

import os
import sys
import unittest

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import display_confidence as dc  # noqa: E402
from pigeon import hdmi_capture as ho  # noqa: E402
from pigeon.tmdb_poster import is_degenerate_tmdb_query  # noqa: E402
from pigeon.widgets.view_circles import (  # noqa: E402
    _effective_zone_widgets,
    _layout_is_fullscreen_clock,
)


class PlayerMetadataTests(unittest.TestCase):
    def test_pyatv_title_is_adequate(self) -> None:
        md = {"query": "Ted Lasso", "identity_source": "pyatv"}
        self.assertTrue(dc.player_metadata_adequate(md))
        self.assertFalse(dc.hdmi_in_charge(md))
        self.assertGreaterEqual(dc.identity_confidence(md), dc.DISPLAY_MIN)

    def test_stale_identity_is_not_displayable(self) -> None:
        md = {"query": "", "identity_source": "stale", "identity_confidence": dc.STALE}
        self.assertFalse(dc.identity_displayable(md))
        self.assertTrue(dc.hdmi_in_charge(md))

    def test_foreground_app_without_title_stays_active(self) -> None:
        md = {"app_name": "Netflix", "query": "", "device_state": "Idle"}
        self.assertTrue(dc.content_should_stay_active(md, hdmi_present=True))
        self.assertFalse(dc.content_should_stay_active(md, hdmi_present=False))

    def test_hdmi_not_in_charge_when_dongle_missing(self) -> None:
        md = {"query": "", "app_name": "Netflix", "identity_source": "stale"}
        self.assertTrue(dc.hdmi_in_charge(md, hdmi_present=True))
        self.assertFalse(dc.hdmi_in_charge(md, hdmi_present=False))
        self.assertFalse(
            dc.content_should_stay_active(md, hdmi_present=False)
        )

    def test_idle_poll_holds_last_title(self) -> None:
        prev = {
            "query": "IT: Welcome to Derry",
            "title": "IT: Welcome to Derry",
            "identity_source": "pyatv",
            "identity_confidence": dc.PYATV_IDENTITY,
            "content_key": "derry",
            "device_state": "Playing",
            "app_name": "Max",
        }
        incoming = {
            "query": "",
            "title": "",
            "device_state": "Idle",
            "app_name": "Max",
            "power_state": "PowerState.On",
        }
        held = dc.hold_identity_across_idle_poll(prev, incoming)
        self.assertEqual(held["query"], "IT: Welcome to Derry")
        self.assertEqual(held["device_state"], "Idle")
        self.assertTrue(held.get("identity_held_across_idle"))
        self.assertTrue(dc.metadata_has_holdable_identity(held))
        self.assertFalse(dc.metadata_is_playback_idle(held))
        self.assertFalse(dc.playback_has_concluded(held))

    def test_switching_apps_does_not_hold_old_title(self) -> None:
        prev = {
            "query": "It",
            "title": "It",
            "identity_source": "pyatv",
            "identity_confidence": dc.PYATV_IDENTITY,
            "device_state": "DeviceState.Playing",
            "app_name": "HBO Max",
            "app_id": "com.wbd.stream",
        }
        netflix = {
            "query": "",
            "title": "",
            "device_state": "DeviceState.Playing",
            "app_name": "Netflix",
            "app_id": "com.netflix.Netflix",
        }
        held = dc.hold_identity_across_idle_poll(prev, netflix)
        self.assertEqual(held["query"], "")
        self.assertFalse(held.get("identity_held_across_idle"))
        self.assertFalse(dc.metadata_has_holdable_identity(held))

    def test_idle_at_end_of_title_is_concluded(self) -> None:
        md = {
            "query": "The Big Bang Theory",
            "title": "The Infestation Hypothesis",
            "device_state": "DeviceState.Idle",
            "position": 1260.0,
            "total_time": 1260.0,
        }
        self.assertTrue(dc.playback_has_concluded(md))
        self.assertFalse(
            dc.playback_has_concluded(
                {
                    "query": "The Big Bang Theory",
                    "device_state": "DeviceState.Idle",
                    "position": 600.0,
                    "total_time": 1260.0,
                }
            )
        )
        self.assertFalse(
            dc.playback_has_concluded(
                {
                    "query": "The Big Bang Theory",
                    "device_state": "Playing",
                    "position": 1260.0,
                    "total_time": 1260.0,
                }
            )
        )

    def test_idle_poll_keeps_end_position_when_playhead_resets(self) -> None:
        prev = {
            "query": "The Big Bang Theory",
            "title": "The Infestation Hypothesis",
            "device_state": "Playing",
            "position": 1259.0,
            "total_time": 1260.0,
        }
        incoming = {
            "query": "",
            "title": "",
            "device_state": "Idle",
            "position": 0.0,
            "total_time": 1260.0,
            "power_state": "PowerState.On",
        }
        held = dc.hold_identity_across_idle_poll(prev, incoming)
        self.assertTrue(held.get("playback_concluded"))
        self.assertGreaterEqual(float(held.get("position") or 0.0), 1259.0)
        self.assertTrue(dc.playback_has_concluded(held))

    def test_idle_poll_keeps_paused_device_state(self) -> None:
        prev = {
            "query": "Shake It Off",
            "title": "Shake It Off",
            "device_state": "DeviceState.Paused",
        }
        incoming = {
            "query": "",
            "title": "",
            "device_state": "DeviceState.Idle",
            "power_state": "PowerState.On",
        }
        held = dc.hold_identity_across_idle_poll(prev, incoming)
        self.assertEqual(held["title"], "Shake It Off")
        self.assertIn("Paused", str(held.get("device_state") or ""))

    def test_new_title_and_power_off_do_not_hold(self) -> None:
        prev = {
            "query": "IT: Welcome to Derry",
            "title": "IT: Welcome to Derry",
            "identity_source": "pyatv",
        }
        nxt = dc.hold_identity_across_idle_poll(
            prev,
            {"query": "Dune", "title": "Dune", "identity_source": "pyatv"},
        )
        self.assertEqual(nxt["query"], "Dune")
        self.assertFalse(nxt.get("identity_held_across_idle"))
        off = dc.hold_identity_across_idle_poll(
            prev,
            {"query": "", "title": "", "device_state": "Idle", "power_state": "Off"},
        )
        self.assertFalse(dc.metadata_has_holdable_identity(off))

    def test_short_movie_titles_are_adequate(self) -> None:
        for title in ("It", "Up", "Us", "Her", "Elf", "Ted", "It 2017"):
            md = {"query": title, "identity_source": "pyatv"}
            self.assertFalse(is_degenerate_tmdb_query(title), title)
            self.assertFalse(dc.is_placeholder_identity(title), title)
            self.assertTrue(dc.player_metadata_adequate(md), title)
            self.assertFalse(dc.hdmi_in_charge(md), title)


class ShortTitleQueryTests(unittest.TestCase):
    def test_service_names_stay_degenerate(self) -> None:
        self.assertTrue(is_degenerate_tmdb_query("Netflix"))
        self.assertTrue(is_degenerate_tmdb_query("disney+"))
        self.assertTrue(is_degenerate_tmdb_query("2017"))

    def test_chapter_two_still_passes(self) -> None:
        self.assertFalse(is_degenerate_tmdb_query("It: Chapter Two"))

    def test_welcome_to_derry_is_a_real_title(self) -> None:
        title = "IT: Welcome to Derry"
        self.assertFalse(is_degenerate_tmdb_query(title))
        self.assertFalse(dc.is_placeholder_identity(title))
        self.assertTrue(
            dc.player_metadata_adequate(
                {"query": title, "identity_source": "pyatv"}
            )
        )


class HdmiFrameStreakTests(unittest.TestCase):
    def setUp(self) -> None:
        ho.reset_frame_schedule()

    def tearDown(self) -> None:
        ho.reset_frame_schedule()

    def test_frame_fingerprint_counts_unchanged_streak(self) -> None:
        import numpy as np

        frame_a = np.full((108, 192, 3), 40, dtype=np.uint8)
        frame_b = np.full((108, 192, 3), 200, dtype=np.uint8)
        self.assertTrue(ho._note_frame_fingerprint(frame_a))
        self.assertEqual(ho.hdmi_unchanged_streak(), 0)
        self.assertFalse(ho._note_frame_fingerprint(frame_a))
        self.assertEqual(ho.hdmi_unchanged_streak(), 1)
        self.assertFalse(ho._note_frame_fingerprint(frame_a))
        self.assertEqual(ho.hdmi_unchanged_streak(), 2)
        self.assertTrue(ho._note_frame_fingerprint(frame_b))
        self.assertEqual(ho.hdmi_unchanged_streak(), 0)
        self.assertFalse(ho.hdmi_clock_saver_due())

    def test_clock_saver_due_after_streak(self) -> None:
        ho._schedule.consecutive_unchanged = ho.CLOCK_SAVER_FRAME_STREAK
        self.assertTrue(ho.hdmi_clock_saver_due())



class TitleDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        from pigeon.title_decision import reset_title_decisions

        reset_title_decisions()

    def tearDown(self) -> None:
        from pigeon.title_decision import reset_title_decisions

        reset_title_decisions()

    def test_records_and_explains(self) -> None:
        from pigeon.title_decision import (
            apply_decision_to_metadata,
            decision_from_metadata,
            latest_title_decision,
            record_title_decision,
        )

        d = record_title_decision(
            "The Crown",
            source="pyatv",
            reason="player metadata supplied a usable title",
        )
        self.assertIn("The Crown", d.explain())
        self.assertIn("pyatv", d.explain())
        md: dict = {}
        apply_decision_to_metadata(md, d)
        self.assertEqual(decision_from_metadata(md), d.explain())
        self.assertIs(latest_title_decision(), d)


class TrtConfidenceTests(unittest.TestCase):
    def test_parse_duration_treats_huge_values_as_milliseconds(self) -> None:
        self.assertEqual(dc.parse_duration_seconds(192 * 60), 192 * 60)
        self.assertAlmostEqual(dc.parse_duration_seconds(192 * 60 * 1000), 192 * 60)
        self.assertIsNone(dc.parse_duration_seconds(0))
        self.assertIsNone(dc.parse_duration_seconds(None))

    def test_player_duration_uses_total_time_then_fallbacks(self) -> None:
        self.assertEqual(
            dc.player_duration_seconds({"total_time": 5400}),
            5400,
        )
        self.assertEqual(
            dc.player_duration_seconds({}, fallbacks=(None, 96 * 60)),
            96 * 60,
        )

    def test_similarity_and_reject_thresholds(self) -> None:
        self.assertAlmostEqual(dc.trt_similarity(192 * 60, 192 * 60), 1.0)
        parody = dc.trt_confidence(192 * 60, 4 * 60)
        mini = dc.trt_confidence(192 * 60, [96 * 60, 192 * 60])
        self.assertIsNotNone(parody)
        self.assertIsNotNone(mini)
        self.assertLess(parody, dc.TRT_REJECT)
        self.assertTrue(dc.trt_is_reject(192 * 60, 4 * 60))
        self.assertTrue(dc.trt_is_reject(192 * 60, 135 * 60))
        self.assertTrue(dc.trt_is_reject(190 * 60, 105 * 60))
        self.assertFalse(dc.trt_is_reject(190 * 60, [105 * 60, 210 * 60]))
        self.assertFalse(dc.trt_is_reject(192 * 60, [96 * 60, 192 * 60]))
        self.assertGreaterEqual(mini, dc.TRT_AGREE)

    def test_no_duration_skips_trt(self) -> None:
        self.assertIsNone(dc.trt_confidence(None, 135 * 60))
        scores = dc.scores_for_metadata(
            {"query": "It", "identity_source": "pyatv"},
            tmdb_matches=True,
        )
        self.assertIsNone(scores["trt"])
        self.assertEqual(scores["art"], dc.ART_MATCHED)

    def test_art_confidence_drops_on_trt_mismatch(self) -> None:
        scores = dc.scores_for_metadata(
            {"query": "It", "identity_source": "pyatv", "total_time": 192 * 60},
            tmdb_matches=True,
            tmdb_runtime_s=4 * 60,
        )
        self.assertLess(scores["trt"], dc.TRT_REJECT)
        self.assertLess(scores["art"], 0.30)
        long_parody = dc.scores_for_metadata(
            {"query": "It", "identity_source": "pyatv", "total_time": 190 * 60},
            tmdb_matches=True,
            tmdb_runtime_s=105 * 60,
        )
        self.assertTrue(dc.trt_is_reject(190 * 60, 105 * 60))
        self.assertLess(long_parody["art"], 0.30)

    def test_art_confidence_rises_when_trt_agrees(self) -> None:
        scores = dc.scores_for_metadata(
            {"query": "It", "identity_source": "pyatv", "total_time": 192 * 60},
            tmdb_matches=True,
            tmdb_runtime_s=[96 * 60, 192 * 60],
        )
        self.assertGreaterEqual(scores["trt"], dc.TRT_AGREE)
        self.assertGreaterEqual(scores["art"], dc.ART_MATCHED)


class ZoneAdaptTests(unittest.TestCase):
    def test_no_position_keeps_the_saved_status_bar_in_zone5(self) -> None:
        # Saved zones stay on screen: a missing position no longer swaps zone 5
        # for spare cast names or blanks it (see _apply_connection_fallbacks).
        for cast_count in (0, 3, 6):
            with self.subTest(cast_count=cast_count):
                zones = _effective_zone_widgets(
                    has_position=False,
                    cast_count=cast_count,
                    zone_widgets=("clock", "poster", "volume", "cast_info", "now_playing"),
                )
                self.assertEqual(zones[4], "status_bar")
                self.assertEqual(zones[3], "cast_info")

    def test_position_makes_no_difference_to_the_layout(self) -> None:
        saved = ("clock", "poster", "volume", "cast_info", "now_playing")
        self.assertEqual(
            _effective_zone_widgets(has_position=False, cast_count=6, zone_widgets=saved),
            _effective_zone_widgets(has_position=True, cast_count=6, zone_widgets=saved),
        )

    def test_a_saved_cast_strip_in_zone5_is_not_duplicated(self) -> None:
        zones = _effective_zone_widgets(
            has_position=False,
            cast_count=3,
            zone_widgets=("clock", "poster", "volume", "cast_info", "cast_info"),
        )
        self.assertEqual(zones.count("cast_info"), 1)
        self.assertEqual(zones[4], "")

    def test_duplicate_clock_is_dropped(self) -> None:
        zones = _effective_zone_widgets(
            has_position=True,
            cast_count=0,
            zone_widgets=("clock", "clock", "volume", "cast_info", "now_playing"),
        )
        self.assertEqual(zones[0], "clock")
        self.assertEqual(zones[1], "")
        self.assertEqual(zones[4], "status_bar")

    def test_status_bar_alias_and_circular_np_are_distinct(self) -> None:
        zones = _effective_zone_widgets(
            has_position=True,
            cast_count=6,
            zone_widgets=("now_playing", "poster", "volume", "cast_info", "now_playing"),
        )
        self.assertEqual(zones[0], "now_playing")
        self.assertEqual(zones[4], "status_bar")

    def test_no_position_keeps_circular_np_in_zone1(self) -> None:
        zones = _effective_zone_widgets(
            has_position=False,
            cast_count=6,
            zone_widgets=("now_playing", "poster", "volume", "cast_info", "status_bar"),
        )
        self.assertEqual(zones[0], "now_playing")

    def test_idle_content_keeps_clock_only(self) -> None:
        zones = _effective_zone_widgets(
            has_position=False,
            cast_count=0,
            content_active=False,
            zone_widgets=("clock", "poster", "volume", "cast_info", "status_bar"),
        )
        self.assertEqual(zones, ("clock", "", "", "", ""))
        self.assertTrue(_layout_is_fullscreen_clock(zones))

    def test_idle_content_keeps_volume_when_readout_present(self) -> None:
        zones = _effective_zone_widgets(
            has_position=False,
            cast_count=0,
            content_active=False,
            has_volume=True,
            zone_widgets=("clock", "poster", "volume", "cast_info", "status_bar"),
        )
        self.assertEqual(zones, ("clock", "", "volume", "", ""))
        self.assertFalse(_layout_is_fullscreen_clock(zones))

    def test_missing_poster_does_not_leave_an_empty_slot(self) -> None:
        zones = _effective_zone_widgets(
            has_position=True,
            cast_count=0,
            has_poster=False,
            poster_16x9=True,
            zone_widgets=("clock", "poster", "volume", "cast_info", "status_bar"),
        )
        self.assertEqual(zones, ("", "", "volume", "", "status_bar"))
        self.assertFalse(_layout_is_fullscreen_clock(zones))

    def test_populated_layout_is_not_fullscreen_clock(self) -> None:
        zones = _effective_zone_widgets(
            has_position=True,
            cast_count=3,
            zone_widgets=("clock", "poster", "volume", "cast_info", "status_bar"),
        )
        self.assertFalse(_layout_is_fullscreen_clock(zones))

    def test_16x9_override_clears_zones_1_2_and_4(self) -> None:
        zones = _effective_zone_widgets(
            has_position=True,
            cast_count=3,
            zone_widgets=("clock", "poster", "volume", "cast_info", "status_bar"),
            poster_16x9=True,
        )
        self.assertEqual(zones, ("", "", "volume", "", "status_bar"))

    def test_16x9_does_not_eat_pausesaver_or_clocksaver(self) -> None:
        paused = _effective_zone_widgets(
            has_position=True,
            cast_count=0,
            zone_widgets=("", "", "", "pausesaver", "status_bar"),
            poster_16x9=True,
        )
        self.assertEqual(paused[3], "pausesaver")
        clock = _effective_zone_widgets(
            has_position=False,
            cast_count=0,
            zone_widgets=("", "", "", "", "clock_saver_seconds"),
            poster_16x9=True,
        )
        self.assertEqual(clock[4], "clock_saver_seconds")


if __name__ == "__main__":
    unittest.main()
