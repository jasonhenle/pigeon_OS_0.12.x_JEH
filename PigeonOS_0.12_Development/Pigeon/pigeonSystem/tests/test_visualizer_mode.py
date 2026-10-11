"""Visualizer mode: long-press toggle, audio badge, zone-6 visualizer on the NP screen, GPIO hold."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import visualizer_mode as vm  # noqa: E402
from pigeon import zone4_eq  # noqa: E402


class ModeTests(unittest.TestCase):
    def tearDown(self) -> None:
        vm._active = None

    def test_default_comes_from_option5(self) -> None:
        vm._active = None
        with mock.patch("pigeon.widgets.options_settings.zone6_visualizer_default", return_value=True):
            self.assertTrue(vm.is_active())

    def test_toggle_flips(self) -> None:
        vm.set_active(False)
        self.assertTrue(vm.toggle())
        self.assertFalse(vm.toggle())


class BadgeTests(unittest.TestCase):
    def setUp(self) -> None:
        vm.set_active(True)
        self.t0 = vm._changed_mono

    def tearDown(self) -> None:
        vm._active = None

    def test_no_red_flash_while_capture_starts(self) -> None:
        self.assertIsNone(vm.badge_state(False, self.t0 + 0.2))
        self.assertEqual(vm.badge_state(False, self.t0 + vm.STARTUP_GRACE_S + 0.1), (False, 1.0))

    def test_red_then_green_for_three_seconds_then_fade_then_gone(self) -> None:
        t = self.t0 + 5.0
        self.assertEqual(vm.badge_state(False, t), (False, 1.0))
        self.assertEqual(vm.badge_state(True, t + 1.0), (True, 1.0))
        self.assertEqual(vm.badge_state(True, t + 1.0 + vm.GREEN_HOLD_S - 0.01), (True, 1.0))
        ok, alpha = vm.badge_state(True, t + 1.0 + vm.GREEN_HOLD_S + vm.FADE_S / 2)  # type: ignore[misc]
        self.assertTrue(ok)
        self.assertAlmostEqual(alpha, 0.5, places=2)
        self.assertIsNone(vm.badge_state(True, t + 1.0 + vm.GREEN_HOLD_S + vm.FADE_S + 0.01))
        self.assertIsNone(vm.badge_state(True, t + 20.0))

    def test_audio_present_from_the_start_shows_nothing(self) -> None:
        self.assertIsNone(vm.badge_state(True, self.t0 + 5.0))

    def test_draw_badge_colors(self) -> None:
        out = np.zeros((200, 300, 3), np.uint8)
        vm.draw_badge(out, (0, 0, 300, 200), (False, 1.0))
        x, y = 300 - vm.BADGE_INSET_PX - vm.BADGE_PX, vm.BADGE_INSET_PX
        self.assertEqual(tuple(out[y + 4, x + vm.BADGE_PX // 2]), (0, 0, 255))  # red tile edge
        vm.draw_badge(out, (0, 0, 300, 200), (True, 1.0))
        self.assertEqual(tuple(out[y + 4, x + vm.BADGE_PX // 2]), (0, 255, 88))


class GpioHoldScriptTests(unittest.TestCase):
    """Run the generated GPIO helper against a fake gpiozero button."""

    def _run(self, presses: list[tuple[float, float]]) -> list[str]:
        from pigeon.rotary_serial import _gpio_poll_encoder_script

        script = _gpio_poll_encoder_script(17, 27, 22, cw="RIGHT", ccw="LEFT", push="PUSH", hold="HOLD", hold_s=0.3)
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "gpiozero.py"
            fake.write_text(textwrap.dedent(f"""
                import time, sys
                T0 = time.monotonic()
                PRESSES = {presses!r}
                END = max(b for _a, b in PRESSES) + 0.3
                class DigitalInputDevice:
                    def __init__(self, pin, pull_up=True):
                        self.pin = pin
                    @property
                    def value(self):
                        t = time.monotonic() - T0
                        if t > END:
                            sys.exit(0)
                        if self.pin != 22:
                            return 1
                        # Real gpiozero: pull_up inputs read 1 while pressed.
                        return 1 if any(a <= t < b for a, b in PRESSES) else 0
            """))
            out = subprocess.run([sys.executable, "-c", script], env={**os.environ, "PYTHONPATH": d},
                                 capture_output=True, text=True, timeout=20)
        return [line for line in out.stdout.split() if line]

    def test_short_press_on_release_and_hold_once(self) -> None:
        self.assertEqual(self._run([(0.1, 0.2)]), ["PUSH"])
        self.assertEqual(self._run([(0.1, 0.9)]), ["HOLD"])
        self.assertEqual(self._run([(0.1, 0.2), (0.4, 1.2)]), ["PUSH", "HOLD"])

    def test_contact_bounce_is_one_short_press(self) -> None:
        bounce = [(0.100, 0.103), (0.105, 0.107), (0.109, 0.25), (0.252, 0.254)]
        self.assertEqual(self._run(bounce), ["PUSH"])


class NowPlayingZone6Tests(unittest.TestCase):
    def setUp(self) -> None:
        from pigeon import auto_widgets as aw

        self._tmp = tempfile.TemporaryDirectory()
        p = mock.patch("pigeon.fullscreen_viz.config_path", lambda: Path(self._tmp.name) / "fullscreen_viz.json")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(aw.set_live_plan, None)
        mic = mock.patch.object(zone4_eq, "want_mic_capture", lambda: None)
        mic.start()
        self.addCleanup(mic.stop)
        self.aw = aw

    def _widget(self, *, metadata: bool):
        from pigeon.widgets.view_circles import ViewCirclesWidget

        plan = self.aw.resolve_auto_widgets(self.aw.AutoWidgetSignals(
            wan_ok=True, wan_ok_at_startup=True, lan_ok=True, reliable_clock=True, receiver_ok=True,
            player_metadata=self.aw.METADATA_OK if metadata else self.aw.METADATA_ABSENT, audio_levels=True))
        self.aw.set_live_plan(plan)
        w = ViewCirclesWidget(assets_dir=Path(__file__).resolve().parents[2] / "pigeonAssets")
        w.update_state(progress=0.3, elapsed_text="1:00", remaining_text="-2:00", volume_text="-32.5 dB",
                       has_now_playing=True, has_position=metadata, content_active=metadata,
                       receiver_input="TV AUDIO", has_receiver=True)
        return w

    def test_audio_only_layout_draws_visualizer_clock_and_receiver_readout(self) -> None:
        from pigeon.np_layout import NOW_PLAYING_ZONES

        w = self._widget(metadata=False)
        self.assertEqual(w._assignments()[0], "visualizer_zone6")
        self.assertTrue(w.wants_live_audio())
        self.assertTrue(w._zone3_clock_is_analog_fallback())
        # Zone 4 keeps the input; the volume moves over the zone-6 visualizer.
        self.assertEqual(w._receiver_readout(), "TV AUDIO")
        self.assertEqual(w._zone6_receiver_volume_text(), "-32.5 dB")
        t = np.arange(4800) / 48000.0
        x = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        frame = None
        for _ in range(3):
            zone4_eq.feed_pcm_stereo(x, x, 48000.0)
            frame = w.bgra_frame()
        assert frame is not None
        zx, zy, zw, zh = (int(v) for v in NOW_PLAYING_ZONES[6].xywh)
        viz = frame[zy + 20 : zy + zh - 20, zx + 20 : zx + zw - 20]
        self.assertTrue((viz[:, :, 3] == 255).all(), "zone 6 is painted every frame")
        self.assertGreater(int(viz[:, :, :3].max()), 40)
        from pigeon.widgets.view_circles import _zone3_clock_day_baseline_y

        base = int(round(_zone3_clock_day_baseline_y()))
        band = frame[max(0, base - 56) : base + 4, zx : zx + zw, :3].min(axis=2) > 200  # white ink
        cols = np.where(band.any(axis=0))[0]
        self.assertGreater(cols.size, 0, "volume over zone 6")
        self.assertLess(abs((cols.min() + cols.max()) / 2.0 - zw / 2.0), 6.0, "centered on zone 6")
        # Same baseline as the zone-3 clock's date: ink bottoms line up.
        z3 = NOW_PLAYING_ZONES[3]
        date = frame[max(0, base - 56) : base + 4, int(z3.x) : int(z3.x + z3.w), :3].min(axis=2) > 200
        vol_bottom = int(np.where(band.any(axis=1))[0].max())
        date_bottom = int(np.where(date.any(axis=1))[0].max())
        self.assertLessEqual(abs(vol_bottom - date_bottom), 2)

    def test_zone4_eq_stays_off_beside_the_zone6_visualizer(self) -> None:
        with mock.patch.object(zone4_eq, "enabled", return_value=True):
            w = self._widget(metadata=True)
            vm.set_active(True)
            self.addCleanup(setattr, vm, "_active", None)
            plan = self.aw.resolve_auto_widgets(self.aw.AutoWidgetSignals(
                wan_ok=True, wan_ok_at_startup=True, lan_ok=True, reliable_clock=True, receiver_ok=True,
                player_metadata=self.aw.METADATA_OK, audio_levels=True, visualizer_mode=True))
            self.aw.set_live_plan(plan)
            self.assertEqual(w._assignments()[3], "cast_info")

    def test_encoder_turn_changes_preset_only_while_showing(self) -> None:
        w = self._widget(metadata=False)
        viz = w._zone6_visualizer()
        start = viz.index
        self.assertTrue(w.rotate_zone6_visualizer(1))
        self.assertEqual(viz.index, start + 1)
        self.aw.set_live_plan(None)
        w2 = self._widget(metadata=True)
        self.assertFalse(w2.rotate_zone6_visualizer(1))


class FeedTests(unittest.TestCase):
    def test_feed_wanted_while_a_visualizer_draws(self) -> None:
        with mock.patch.object(zone4_eq, "enabled", return_value=False), \
                mock.patch.object(zone4_eq.shutil, "which", return_value="/usr/bin/arecord"):
            zone4_eq._mic_last_want = 0.0
            self.assertFalse(zone4_eq.feed_wanted())
            zone4_eq.want_mic_capture()  # what a visualizer calls every frame
            self.assertTrue(zone4_eq.feed_wanted())
            zone4_eq._mic_last_want = time.monotonic() - 5.0
            self.assertFalse(zone4_eq.feed_wanted())


if __name__ == "__main__":
    unittest.main()
