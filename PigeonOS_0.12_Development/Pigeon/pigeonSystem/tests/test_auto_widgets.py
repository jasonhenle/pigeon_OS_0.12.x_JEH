"""Automatic default widget layout from WAN / LAN / audio / metadata."""

from __future__ import annotations

import os
import sys
import unittest

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.auto_widgets import (  # noqa: E402
    CLOCK_SAVER,
    INFO,
    LAYOUT_NP,
    LAYOUT_SETTINGS,
    LAYOUT_SHAZAM,
    LAYOUT_ZONE6_CLOCKSAVER,
    LAYOUT_ZONE6_PAUSESAVER,
    LAYOUT_ZONE8_CLOCKSAVER,
    LAYOUT_ZONE10_PAUSESAVER,
    LAYOUT_ZONE6_VISUALIZER,
    CLOCK,
    VISUALIZER_Z6,
    METADATA_ABSENT,
    METADATA_OK,
    METADATA_STOPPED,
    PAUSESAVER,
    SECONDS,
    STATUS,
    TT,
    VOLUME,
    AutoWidgetSignals,
    auto_clocksaver_wants_digital,
    classify_player_metadata,
    resolve_auto_widgets,
    room_is_renamed,
    set_live_plan,
)


def _sig(**kwargs) -> AutoWidgetSignals:
    base = dict(
        wan_ok=True,
        wan_ok_at_startup=True,
        lan_ok=True,
        reliable_clock=True,
        receiver_ok=True,
        receiver_name="AVR",
        player_metadata=METADATA_ABSENT,
        audio_levels=False,
        audio_identification=False,
        room_renamed=False,
        room_name="",
    )
    base.update(kwargs)
    return AutoWidgetSignals(**base)


class AutoWidgetResolveTests(unittest.TestCase):
    def test_no_wan_no_clock_locks_settings(self) -> None:
        plan = resolve_auto_widgets(
            _sig(wan_ok=False, wan_ok_at_startup=False, reliable_clock=False)
        )
        self.assertEqual(plan.layout, LAYOUT_SETTINGS)
        self.assertTrue(plan.force_settings)
        self.assertFalse(plan.settings_exit_enabled)

    def test_playing_defaults(self) -> None:
        plan = resolve_auto_widgets(
            _sig(player_metadata=METADATA_OK, audio_levels=True)
        )
        self.assertEqual(plan.layout, LAYOUT_NP)
        self.assertEqual(plan.assignments, (TT, "", VOLUME, INFO, STATUS))
        self.assertTrue(plan.settings_exit_enabled)

    def test_playing_volume_when_levels_idle(self) -> None:
        plan = resolve_auto_widgets(
            _sig(player_metadata=METADATA_OK, audio_levels=False, lan_ok=True)
        )
        self.assertEqual(plan.layout, LAYOUT_NP)
        self.assertEqual(plan.assignments[2], VOLUME)

    def test_zone3_is_volume_whenever_lan_is_up(self) -> None:
        for audio in (True, False):
            plan = resolve_auto_widgets(
                _sig(player_metadata=METADATA_OK, audio_levels=audio, lan_ok=True)
            )
            self.assertEqual(plan.assignments[2], VOLUME)

    def test_lan_down_with_audio_shows_the_visualizer(self) -> None:
        plan = resolve_auto_widgets(
            _sig(
                wan_ok=False,
                wan_ok_at_startup=True,
                lan_ok=False,
                receiver_ok=False,
                audio_levels=True,
            )
        )
        self.assertEqual(plan.layout, LAYOUT_ZONE6_VISUALIZER)
        self.assertEqual(plan.assignments, (VISUALIZER_Z6, "", CLOCK, "", SECONDS))
        self.assertTrue(plan.blank_volume)

    def test_audio_levels_widget_is_retired(self) -> None:
        import pigeon.auto_widgets as aw

        self.assertFalse(hasattr(aw, "LEVELS"))
        self.assertNotIn("audio_levels", aw.DEFAULT_NP_ASSIGNMENTS)

    def test_playing_without_lan_or_audio_stays_now_playing(self) -> None:
        plan = resolve_auto_widgets(
            _sig(
                player_metadata=METADATA_OK,
                audio_levels=False,
                lan_ok=False,
            )
        )
        self.assertEqual(plan.layout, LAYOUT_NP)
        self.assertEqual(plan.assignments[3], INFO)
        self.assertEqual(plan.assignments[4], STATUS)

    def test_paused_with_audio_uses_zone6_pausesaver(self) -> None:
        plan = resolve_auto_widgets(
            _sig(
                player_metadata=METADATA_STOPPED,
                audio_levels=True,
                pausesaver_art=True,
            )
        )
        self.assertEqual(plan.layout, LAYOUT_ZONE6_PAUSESAVER)
        self.assertEqual(plan.assignments[0], PAUSESAVER)
        self.assertEqual(plan.assignments[2], VOLUME)

    def test_paused_without_art_is_clocksaver(self) -> None:
        plan = resolve_auto_widgets(
            _sig(
                player_metadata=METADATA_STOPPED,
                audio_levels=False,
                pausesaver_art=False,
            )
        )
        self.assertEqual(plan.layout, LAYOUT_ZONE8_CLOCKSAVER)
        # No still to show, but audio: the visualizer shows what is playing.
        zone6 = resolve_auto_widgets(
            _sig(
                player_metadata=METADATA_STOPPED,
                audio_levels=True,
                pausesaver_art=False,
            )
        )
        self.assertEqual(zone6.layout, LAYOUT_ZONE6_VISUALIZER)

    def test_paused_for_thirty_seconds_becomes_clocksaver(self) -> None:
        still_paused = resolve_auto_widgets(
            _sig(
                player_metadata=METADATA_STOPPED,
                audio_levels=False,
                paused_for_s=29.0,
                pausesaver_art=True,
            )
        )
        self.assertEqual(still_paused.layout, LAYOUT_ZONE10_PAUSESAVER)
        zone10 = resolve_auto_widgets(
            _sig(player_metadata=METADATA_STOPPED, audio_levels=False, paused_for_s=30.0)
        )
        self.assertEqual(zone10.layout, LAYOUT_ZONE8_CLOCKSAVER)
        self.assertEqual(zone10.zone8, CLOCK_SAVER)
        zone6 = resolve_auto_widgets(
            _sig(player_metadata=METADATA_STOPPED, audio_levels=True, paused_for_s=30.0)
        )
        self.assertEqual(zone6.layout, LAYOUT_ZONE6_VISUALIZER)
        self.assertEqual(zone6.assignments[0], VISUALIZER_Z6)

    def test_paused_without_audio_uses_zone10(self) -> None:
        plan = resolve_auto_widgets(
            _sig(
                player_metadata=METADATA_STOPPED,
                audio_levels=False,
                pausesaver_art=True,
            )
        )
        self.assertEqual(plan.layout, LAYOUT_ZONE10_PAUSESAVER)
        self.assertEqual(plan.zone10, PAUSESAVER)
        self.assertEqual(plan.assignments, ("", "", "", PAUSESAVER, STATUS))

    def test_absent_metadata_with_audio_is_the_zone6_visualizer(self) -> None:
        # Audio but no player metadata: visualizer, analog clock, the receiver's
        # input + volume in zone 4, seconds in zone 5.
        plan = resolve_auto_widgets(
            _sig(player_metadata=METADATA_ABSENT, audio_levels=True)
        )
        self.assertEqual(plan.layout, LAYOUT_ZONE6_VISUALIZER)
        self.assertEqual(plan.assignments, (VISUALIZER_Z6, "", CLOCK, "", SECONDS))
        self.assertTrue(plan.zone4_receiver)
        # Metadata returns: back to the standard layout.
        back = resolve_auto_widgets(_sig(player_metadata=METADATA_OK, audio_levels=True))
        self.assertEqual(back.layout, LAYOUT_NP)

    def test_stale_title_from_previous_app_is_absent(self) -> None:
        # Netflix after It on Max: the carried-over title is marked stale.
        md = {
            "query": "It",
            "title": "It",
            "identity_source": "stale",
            "device_state": "DeviceState.Playing",
            "app_name": "Netflix",
        }
        meta = classify_player_metadata(md, playing=True)
        self.assertEqual(meta, METADATA_ABSENT)
        plan = resolve_auto_widgets(_sig(player_metadata=meta, audio_levels=True))
        self.assertEqual(plan.layout, LAYOUT_ZONE6_VISUALIZER)
        plan = resolve_auto_widgets(_sig(player_metadata=meta, audio_levels=False))
        self.assertEqual(plan.layout, LAYOUT_ZONE8_CLOCKSAVER)

    def test_absent_metadata_without_audio_is_zone8_clocksaver(self) -> None:
        plan = resolve_auto_widgets(
            _sig(player_metadata=METADATA_ABSENT, audio_levels=False)
        )
        self.assertEqual(plan.layout, LAYOUT_ZONE8_CLOCKSAVER)
        self.assertEqual(plan.zone8, CLOCK_SAVER)
        self.assertEqual(plan.assignments[4], SECONDS)

    def test_shazam_branch_when_identification_active(self) -> None:
        plan = resolve_auto_widgets(
            _sig(
                player_metadata=METADATA_ABSENT,
                audio_identification=True,
                audio_levels=True,
            )
        )
        self.assertEqual(plan.layout, LAYOUT_SHAZAM)

    def test_wan_off_after_startup_scales_clocksaver_into_zone6(self) -> None:
        plan = resolve_auto_widgets(
            _sig(
                wan_ok=False,
                wan_ok_at_startup=True,
                reliable_clock=True,
                audio_levels=False,
                receiver_ok=False,
            )
        )
        self.assertEqual(plan.layout, LAYOUT_ZONE6_CLOCKSAVER)
        self.assertTrue(plan.blank_weather)
        self.assertTrue(plan.blank_volume)
        self.assertFalse(plan.settings_exit_enabled)

    def test_wan_off_rtc_only_uses_zone8(self) -> None:
        plan = resolve_auto_widgets(
            _sig(
                wan_ok=False,
                wan_ok_at_startup=False,
                reliable_clock=True,
                audio_levels=False,
            )
        )
        self.assertEqual(plan.layout, LAYOUT_ZONE8_CLOCKSAVER)
        self.assertTrue(plan.blank_weather)

    def test_zone4_room_name_when_metadata_absent(self) -> None:
        plan = resolve_auto_widgets(
            _sig(
                player_metadata=METADATA_ABSENT,
                audio_levels=False,
                room_renamed=True,
                room_name="LOUNGE",
            )
        )
        self.assertEqual(plan.zone4_text, "LOUNGE")

    def test_zone4_receiver_readout_when_wan_off(self) -> None:
        plan = resolve_auto_widgets(
            _sig(
                wan_ok=False,
                wan_ok_at_startup=True,
                player_metadata=METADATA_ABSENT,
                audio_levels=True,
                lan_ok=True,
                receiver_ok=True,
                receiver_name="DENON",
            )
        )
        self.assertTrue(plan.zone4_receiver)
        self.assertEqual(plan.zone4_text, "")

    def test_auto_clocksaver_never_uses_analog_face(self) -> None:
        zone8 = resolve_auto_widgets(
            _sig(player_metadata=METADATA_ABSENT, audio_levels=False)
        )
        zone6 = resolve_auto_widgets(
            _sig(wan_ok=False, wan_ok_at_startup=True, player_metadata=METADATA_ABSENT, audio_levels=False)
        )
        playing = resolve_auto_widgets(
            _sig(player_metadata=METADATA_OK, audio_levels=True)
        )
        self.assertTrue(auto_clocksaver_wants_digital(zone8))
        self.assertTrue(auto_clocksaver_wants_digital(zone6))
        self.assertFalse(auto_clocksaver_wants_digital(playing))
        set_live_plan(zone8)
        try:
            self.assertTrue(auto_clocksaver_wants_digital())
        finally:
            set_live_plan(None)

    def test_receiver_ok_keeps_volume_on_clocksaver(self) -> None:
        plan = resolve_auto_widgets(
            _sig(player_metadata=METADATA_ABSENT, audio_levels=False, receiver_ok=True)
        )
        self.assertFalse(plan.blank_volume)
        plan_off = resolve_auto_widgets(
            _sig(player_metadata=METADATA_ABSENT, audio_levels=False, receiver_ok=False)
        )
        self.assertTrue(plan_off.blank_volume)


class AutoWidgetHelperTests(unittest.TestCase):
    def test_room_is_renamed(self) -> None:
        self.assertFalse(room_is_renamed("ROOM 1", slot_index=1))
        self.assertFalse(room_is_renamed("NEST 2", slot_index=2))
        self.assertTrue(room_is_renamed("LOUNGE", slot_index=1))

    def test_classify_metadata(self) -> None:
        playing = classify_player_metadata(
            {"title": "Dune", "device_state": "Playing"},
            playing=True,
        )
        self.assertEqual(playing, METADATA_OK)
        paused = classify_player_metadata(
            {"title": "Dune", "device_state": "Paused"},
            paused=True,
        )
        self.assertEqual(paused, METADATA_STOPPED)
        absent = classify_player_metadata({}, playing=False)
        self.assertEqual(absent, METADATA_ABSENT)
        idle_held = classify_player_metadata(
            {
                "query": "IT: Welcome to Derry",
                "title": "IT: Welcome to Derry",
                "device_state": "Idle",
            },
            playing=False,
        )
        self.assertEqual(idle_held, METADATA_OK)
        idle_ended = classify_player_metadata(
            {
                "query": "The Big Bang Theory",
                "title": "The Infestation Hypothesis",
                "device_state": "DeviceState.Idle",
                "position": 1260.0,
                "total_time": 1260.0,
            },
            playing=True,
        )
        self.assertEqual(idle_ended, METADATA_STOPPED)
        idle_ended_clock = classify_player_metadata(
            {
                "query": "The Big Bang Theory",
                "title": "The Infestation Hypothesis",
                "device_state": "DeviceState.Idle",
            },
            playing=True,
            remaining_s=0.0,
        )
        self.assertEqual(idle_ended_clock, METADATA_STOPPED)
        stopped = classify_player_metadata(
            {
                "query": "Taylor Swift",
                "title": "Shake It Off",
                "device_state": "DeviceState.Stopped",
            },
            playing=False,
        )
        self.assertEqual(stopped, METADATA_STOPPED)
        # Held title can still look like playback while the overlay says paused.
        overlay_and_playing = classify_player_metadata(
            {
                "title": "Dune",
                "query": "Dune",
                "device_state": "",
            },
            paused=True,
            playing=True,
        )
        self.assertEqual(overlay_and_playing, METADATA_STOPPED)
        from pigeon.clock_saver_policy import pausesaver_hold_from_metadata_class

        self.assertTrue(pausesaver_hold_from_metadata_class(overlay_and_playing))
        self.assertFalse(pausesaver_hold_from_metadata_class(METADATA_OK))


if __name__ == "__main__":
    unittest.main()


class VisualizerModeLayoutTests(unittest.TestCase):
    """Long-press visualizer mode (``visualizer_mode`` signal)."""

    def test_with_metadata_keeps_cast_info_and_status_bar(self) -> None:
        plan = resolve_auto_widgets(_sig(player_metadata=METADATA_OK, audio_levels=True, visualizer_mode=True))
        self.assertEqual(plan.layout, LAYOUT_ZONE6_VISUALIZER)
        self.assertEqual(plan.assignments, (VISUALIZER_Z6, "", CLOCK, INFO, STATUS))
        self.assertFalse(plan.zone4_receiver)

    def test_paused_title_keeps_cast_info(self) -> None:
        plan = resolve_auto_widgets(
            _sig(player_metadata=METADATA_STOPPED, pausesaver_art=True, visualizer_mode=True)
        )
        self.assertEqual(plan.assignments, (VISUALIZER_Z6, "", CLOCK, INFO, STATUS))

    def test_without_metadata_shows_receiver_and_seconds(self) -> None:
        for audio in (True, False):  # stays up with no audio (the badge reports it)
            plan = resolve_auto_widgets(_sig(audio_levels=audio, visualizer_mode=True))
            self.assertEqual(plan.assignments, (VISUALIZER_Z6, "", CLOCK, "", SECONDS))
            self.assertTrue(plan.zone4_receiver)

    def test_forced_settings_still_win(self) -> None:
        plan = resolve_auto_widgets(_sig(wan_ok=False, reliable_clock=False, visualizer_mode=True))
        self.assertEqual(plan.layout, LAYOUT_SETTINGS)
