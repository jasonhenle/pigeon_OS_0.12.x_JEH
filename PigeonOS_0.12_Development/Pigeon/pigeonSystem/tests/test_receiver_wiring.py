"""Pigeon's main loop talks to its receiver only through ``ReceiverLink`` / ``Receiver``.

Drives the real ``device_control`` functions against a FakeReceiver — no network,
no brand module involved.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.core import device_control as dc  # noqa: E402
from pigeon.receiver.base import ReceiverState  # noqa: E402
from pigeon.receiver.fake import FakeReceiver  # noqa: E402
from pigeon.receiver_link import ReceiverLink  # noqa: E402


def wait_for(cond, timeout=2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


class LinkTests(unittest.TestCase):
    def make(self):
        made: list[FakeReceiver] = []

        def factory(brand, host, **opts):
            r = FakeReceiver()
            r.host, r.opts = host, opts
            made.append(r)
            return r

        return ReceiverLink(factory), made

    def test_bind_connects_and_is_idempotent(self) -> None:
        link, made = self.make()
        rx = link.bind("10.0.0.5")
        self.assertTrue(wait_for(lambda: rx.connected))
        self.assertIs(link.bind("10.0.0.5"), rx)
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0].opts, {"full_poll_s": 0.75})

    def test_rebind_replaces_receiver_keeps_listeners(self) -> None:
        link, made = self.make()
        seen: list[str] = []
        link.on_volume_confirmed(seen.append)
        first = link.bind("10.0.0.5")
        wait_for(lambda: first.connected)
        second = link.bind("10.0.0.9")
        self.assertIsNot(first, second)
        self.assertFalse(first.connected)  # old one disconnected
        wait_for(lambda: second.connected)
        second.step_volume(1)
        self.assertEqual(len(seen), 1)

    def test_state_is_empty_until_bound(self) -> None:
        link, _ = self.make()
        self.assertEqual(link.state(), ReceiverState())
        self.assertFalse(link.readout_superseded("-30.0 dB"))
        self.assertIsNone(link.bind(""))


    def test_release_disconnects_and_empties_state(self) -> None:
        link, made = self.make()
        rx = link.bind("10.0.0.5")
        wait_for(lambda: rx.connected)
        link.release()
        self.assertFalse(rx.connected)
        self.assertIsNone(link.receiver)
        self.assertEqual(link.host, "")
        self.assertEqual(link.state(), ReceiverState())
        self.assertFalse(link.readout_superseded("-30.0 dB"))
        self.assertIsNot(link.bind("10.0.0.5"), rx)  # a later bind starts clean

    def test_callbacks_from_a_replaced_or_released_receiver_are_dropped(self) -> None:
        class Capturing(FakeReceiver):
            def __init__(self) -> None:
                super().__init__()
                self.state_cbs, self.vol_cbs, self.res_cbs = [], [], []

            def add_state_listener(self, cb): self.state_cbs.append(cb)
            def add_volume_confirmed_listener(self, cb): self.vol_cbs.append(cb)
            def add_command_result_listener(self, cb): self.res_cbs.append(cb)

        made = []

        def factory(brand, host, **opts):
            r = Capturing()
            made.append(r)
            return r

        link = ReceiverLink(factory)
        seen = []
        link.on_state(lambda o, n: seen.append(("state", n)))
        link.on_volume_confirmed(lambda line: seen.append(("vol", line)))
        link.on_command_result(lambda ok, msg: seen.append(("res", msg)))
        first = link.bind("10.0.0.5")
        wait_for(lambda: first.connected)
        first.vol_cbs[0]("-30.0 dB")
        self.assertEqual(seen, [("vol", "-30.0 dB")])
        seen.clear()
        second = link.bind("10.0.0.9")  # replaced while old callbacks are still pending
        first.vol_cbs[0]("-10.0 dB")
        first.state_cbs[0](ReceiverState(), ReceiverState(volume_db=-10.0))
        first.res_cbs[0](True, "old")
        self.assertEqual(seen, [])
        second.vol_cbs[0]("-45.0 dB")
        self.assertEqual(seen, [("vol", "-45.0 dB")])
        seen.clear()
        link.release()
        second.vol_cbs[0]("-5.0 dB")
        second.res_cbs[0](True, "removed")
        self.assertEqual(seen, [])

    def test_connect_pending_when_replaced_never_goes_live(self) -> None:
        gate, entered, finished = threading.Event(), threading.Event(), threading.Event()

        class Slow(FakeReceiver):
            def connect(self) -> None:
                entered.set()
                gate.wait(5)
                super().connect()
                finished.set()

        made = []

        def factory(brand, host, **opts):
            r = Slow() if not made else FakeReceiver()
            made.append(r)
            return r

        link = ReceiverLink(factory)
        first = link.bind("10.0.0.5")
        self.assertTrue(entered.wait(2))
        second = link.bind("10.0.0.9")  # replace while the first connect is still blocked
        gate.set()
        self.assertTrue(finished.wait(2))  # the stale connect ran to completion...
        self.assertTrue(wait_for(lambda: second.connected))
        self.assertTrue(wait_for(lambda: not first._session))  # ...and was undone
        self.assertFalse(first.connected)
        self.assertIs(link.receiver, second)

    def test_connect_pending_when_released_never_goes_live(self) -> None:
        gate, entered, finished = threading.Event(), threading.Event(), threading.Event()

        class Slow(FakeReceiver):
            def connect(self) -> None:
                entered.set()
                gate.wait(5)
                super().connect()
                finished.set()

        link = ReceiverLink(lambda brand, host, **o: Slow())
        rx = link.bind("10.0.0.5")
        self.assertTrue(entered.wait(2))
        link.release()
        gate.set()
        self.assertTrue(finished.wait(2))
        self.assertTrue(wait_for(lambda: not rx._session))
        self.assertIsNone(link.receiver)

    def test_connect_not_started_when_already_replaced(self) -> None:
        link = ReceiverLink(lambda brand, host, **o: FakeReceiver())
        rx = FakeReceiver()
        link._connect(rx)  # never bound: must not connect
        self.assertFalse(rx._session)

    def test_factory_failure_does_not_leak_the_old_receiver(self) -> None:
        made = []

        def factory(brand, host, **opts):
            if made:
                raise RuntimeError("boom")
            made.append(FakeReceiver())
            return made[0]

        link = ReceiverLink(factory)
        rx = link.bind("10.0.0.5")
        wait_for(lambda: rx.connected)
        with self.assertRaises(RuntimeError):
            link.bind("10.0.0.9")
        self.assertFalse(rx.connected)
        self.assertIsNone(link.receiver)


class DeviceControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rx = FakeReceiver()
        self.link = ReceiverLink(lambda brand, host, **o: self.rx)
        p = mock.patch.object(dc, "get_receiver_link", return_value=self.link)
        p.start()
        self.addCleanup(p.stop)

    def bound(self):
        self.link.bind("10.0.0.5")
        self.assertTrue(wait_for(lambda: self.rx.connected))

    def test_knob_action_changes_volume_and_wakes(self) -> None:
        self.bound()
        slot = [{"address": "10.0.0.5"}]
        pending = [False]
        before = self.rx.cached_state().volume_db
        self.assertTrue(dc._queue_receiver_volume_action("volume_up", avr_slot_holder=slot, receiver_power_on_pending=pending))
        self.assertGreater(self.rx.cached_state().volume_db, before)
        self.rx.simulate_power(False)
        self.assertTrue(dc._queue_receiver_volume_action("volume_up", avr_slot_holder=slot, receiver_power_on_pending=[True]))
        self.assertTrue(self.rx.cached_state().powered_on)

    def test_knob_action_without_saved_receiver_is_refused(self) -> None:
        self.assertFalse(dc._queue_receiver_volume_action("volume_up", avr_slot_holder=[None], receiver_power_on_pending=[False]))
        self.assertFalse(dc._queue_receiver_volume_action("volume_up", avr_slot_holder=[{"address": ""}], receiver_power_on_pending=[False]))

    def test_audio_fallback_and_input_label_come_from_receiver_state(self) -> None:
        self.bound()
        self.assertEqual(dc._receiver_audio_fallback(), ("dolby digital", "dolby surround"))
        self.assertEqual(dc._resolve_receiver_input_label(receiver_overlay_state={}, receiver_standby_holder=[False]),
                         self.rx.cached_state().input_label)
        self.assertEqual(dc._resolve_receiver_input_label(receiver_overlay_state={"input": "X"}, receiver_standby_holder=[False]), "X")
        self.assertEqual(dc._resolve_receiver_input_label(receiver_overlay_state={}, receiver_standby_holder=[True]), "")
        self.rx.simulate_power(False)
        self.assertEqual(dc._receiver_audio_fallback(), ("", ""))

    def test_callbacks_paint_confirmed_volume_and_clear_standby(self) -> None:
        self.bound()
        holders = dict(
            _clock_saver_volume=mock.Mock(), _note_volume_graphics=mock.Mock(),
            _volume_rotary_fail_log_count=[0], _volume_rotary_ok_log_count=[0],
            denon_vol_cache={}, receiver_overlay_state={}, receiver_power_on_pending=[True],
            receiver_standby_holder=[True], render_once=mock.Mock(),
            root=mock.Mock(after=lambda ms, fn: fn()),
        )
        with mock.patch("pigeon.runtime_state.update_receiver_runtime"):
            dc._register_receiver_callbacks(**holders)
            self.link.bind("10.0.0.5")  # same host: callbacks must reach the live receiver
            self.rx.step_volume(1)
        self.assertEqual(holders["receiver_overlay_state"]["volume"], "-39.5 dB")
        self.assertEqual(holders["denon_vol_cache"]["effective"], "-39.5 dB")
        self.assertEqual(holders["receiver_power_on_pending"], [False])
        self.assertEqual(holders["receiver_standby_holder"], [False])


    def test_no_saved_receiver_releases_the_link(self) -> None:
        self.bound()
        with mock.patch.object(dc, "read_saved_av_receiver", return_value=None):
            dc._bind_receiver_volume_hub("")
        self.assertIsNone(self.link.receiver)
        self.assertFalse(self.rx.connected)
        self.assertEqual(dc._receiver_audio_fallback(), ("", ""))
        self.assertEqual(dc._resolve_receiver_input_label(receiver_overlay_state={}, receiver_standby_holder=[False]), "")

    def test_unreadable_settings_keep_the_receiver(self) -> None:
        self.bound()
        with mock.patch.object(dc, "read_saved_av_receiver", side_effect=OSError("settings busy")):
            dc._bind_receiver_volume_hub("")
        self.assertIs(self.link.receiver, self.rx)
        self.assertTrue(self.rx.connected)

    def test_release_clears_receiver_derived_display_state(self) -> None:
        self.bound()
        cache = {"effective": "-40.0 dB", "np_hold": "-40.0 dB", "mono_usable": 5.0, "bound_host": "10.0.0.5"}
        overlay = {"incoming": "dolby", "config": "x", "volume": "-40.0 dB", "input": "TV"}
        standby, debug = [True], [{"a": "b"}]
        dc._release_receiver(denon_vol_cache=cache, receiver_overlay_state=overlay,
                             receiver_standby_holder=standby, receiver_debug_holder=debug)
        self.assertIsNone(self.link.receiver)
        self.assertEqual(cache, {"effective": "", "np_hold": "", "mono_usable": 0.0, "bound_host": ""})
        self.assertEqual(set(overlay.values()), {""})
        self.assertEqual((standby, debug), ([False], [{}]))

    def test_switching_to_a_location_without_a_receiver_releases_it(self) -> None:
        self.bound()
        cache = {"effective": "-40.0 dB", "np_hold": "-40.0 dB", "mono_usable": 5.0}
        overlay = {"incoming": "dolby", "config": "x", "volume": "-40.0 dB", "input": "TV"}
        names = dc._apply_persisted_location_to_runtime.__code__
        kw = {n: mock.Mock() for n in names.co_varnames[:names.co_kwonlyargcount]}
        kw.update(
            avr_slot_holder=[{"address": "10.0.0.5"}], streaming_slot_holder=[None],
            receiver_http_host={"host": "10.0.0.5"}, current_apple_tv={}, apple_tv_auto_state={},
            apple_tv_playback_clock={}, apple_tv_dashboard_track={}, last_atv_interaction_mono=[0.0],
            _atv_ix_sig_ds=[""], _atv_ix_sig_ck=[None], _atv_ix_pos=[None], _atv_ix_pos_mono=[0.0],
            _atv_ix_extrap_playing=[False], _atv_ix_prev_idle=[True], skip_cache=[None],
            playback_overlay_widget=None, denon_vol_cache=cache, receiver_overlay_state=overlay,
            receiver_standby_holder=[False], receiver_debug_holder=[{}],
        )
        with mock.patch.object(dc, "read_saved_streaming_device", return_value=None), \
             mock.patch.object(dc, "read_saved_av_receiver", return_value=None), \
             mock.patch.object(dc, "clear_last_apple_tv"), mock.patch.object(dc, "clear_last_receiver"):
            dc._apply_persisted_location_to_runtime(**kw)
        self.assertEqual(kw["receiver_http_host"]["host"], "")
        self.assertIsNone(self.link.receiver)
        self.assertFalse(self.rx.connected)
        self.assertEqual(cache["effective"], "")
        self.assertEqual(overlay["volume"], "")

    def test_switching_between_receivers_rebinds_and_old_callbacks_are_dropped(self) -> None:
        made = []

        def factory(brand, host, **o):
            r = FakeReceiver()
            made.append(r)
            return r

        link = ReceiverLink(factory)
        seen = []
        link.on_volume_confirmed(seen.append)
        with mock.patch.object(dc, "get_receiver_link", return_value=link):
            with mock.patch.object(dc, "read_saved_av_receiver", return_value={"address": "10.0.0.5"}):
                dc._bind_receiver_volume_hub("")
            wait_for(lambda: made[0].connected)
            with mock.patch.object(dc, "read_saved_av_receiver", return_value={"address": "10.0.0.9"}):
                dc._bind_receiver_volume_hub("10.0.0.9")
            wait_for(lambda: made[1].connected)
        self.assertFalse(made[0].connected)
        made[0].step_volume(1)  # old receiver still finishing a command
        self.assertEqual(seen, [])
        made[1].step_volume(1)
        self.assertEqual(len(seen), 1)


class PollTickTests(unittest.TestCase):
    """``_receiver_poll_tick`` end to end: receiver state in, overlay state out."""

    def setUp(self) -> None:
        self.rx = FakeReceiver()
        self.link = ReceiverLink(lambda brand, host, **o: self.rx)
        self.link.bind("10.0.0.5")
        wait_for(lambda: self.rx.connected)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, kw in (
            (mock.patch.object(dc, "get_receiver_link", return_value=self.link), {}),
            (mock.patch.object(dc, "read_saved_av_receiver", return_value={"address": "10.0.0.5"}), {}),
            (mock.patch("pigeon.roku_ecp.resolve_roku_ecp_base_url", return_value=""), {}),
            (mock.patch("pigeon.runtime_state.update_receiver_runtime"), {}),
            (mock.patch("pigeon.observed_capability.update_observed_capabilities_from_receiver_poll"), {}),
        ):
            target.start()
            self.addCleanup(target.stop)

    def run_tick(self, **over):
        after_calls = []
        root = mock.Mock()
        root.after = lambda ms, fn=None, *a: (fn() if ms == 0 else after_calls.append(ms))
        saver = mock.Mock()
        saver.is_stale_poll.return_value = False
        saver.display_line.return_value = ""
        saver.hold = ""
        kw = {name: mock.Mock() for name in dc._receiver_poll_tick.__code__.co_varnames[:dc._receiver_poll_tick.__code__.co_kwonlyargcount]}
        kw.update(
            RECEIVER_POLL_MS=750, _PIGEON_EXT=True, _clock_saver_volume=saver,
            _clock_saver_for_compose=lambda now: False, _clock_saver_receiver_off=lambda: False,
            _idle_audio_meter_active=lambda: False, _view_one_uses_now_playing_screen=lambda: False,
            apple_tv_auto_state={}, avr_slot_holder=[{"address": "10.0.0.5"}], clock_saver_force_on=[False],
            denon_vol_cache={}, receiver_http_host={"host": "10.0.0.5"}, receiver_overlay_state={},
            receiver_panel_led_holder=[None], receiver_poll_busy={"active": False},
            receiver_power_on_pending=[False], receiver_power_on_until=[0.0], receiver_standby_holder=[False],
            receiver_debug_holder=[{}], skip_cache=[None], streaming_slot_holder=[None],
            _bind_receiver_volume_hub=lambda host: None, _quick_receiver_volume_poll=lambda: None,
            _receiver_poll_tick=lambda: None, root=root,
        )
        kw.update(over)
        threads = []
        real_thread = threading.Thread

        def run_inline(target=None, **k):
            t = real_thread(target=target, args=k.get("args", ()))
            threads.append(t)
            return t

        with mock.patch.object(dc.threading, "Thread", side_effect=run_inline):
            dc._receiver_poll_tick(**kw)
        for t in threads:
            t.join(5)
        return kw

    def test_live_receiver_populates_overlay(self) -> None:
        kw = self.run_tick()
        ov = kw["receiver_overlay_state"]
        self.assertEqual(ov["incoming"], "dolby digital")
        self.assertEqual(ov["config"], "dolby surround")
        self.assertEqual(ov["input"], self.rx.cached_state().input_label)
        self.assertEqual(ov["volume"], "-40.0 dB")
        self.assertFalse(kw["receiver_standby_holder"][0])
        self.assertFalse(kw["receiver_poll_busy"]["active"])
        self.assertEqual(kw["receiver_debug_holder"][0]["sound mode"], "dolby surround")

    def test_standby_blanks_source_lines_but_keeps_volume(self) -> None:
        self.rx.simulate_power(False)
        kw = self.run_tick()
        ov = kw["receiver_overlay_state"]
        self.assertTrue(kw["receiver_standby_holder"][0])
        self.assertEqual((ov["incoming"], ov["config"], ov["input"]), ("", "", ""))

    def test_unreachable_receiver_does_not_crash_or_stick_busy(self) -> None:
        self.rx.simulate_link(False)
        self.rx.get_state()
        kw = self.run_tick()
        self.assertFalse(kw["receiver_poll_busy"]["active"])
        self.assertEqual(kw["receiver_overlay_state"].get("incoming", ""), "")

    def test_moved_receiver_is_relocated_and_saved(self) -> None:
        class Moved(FakeReceiver):
            def relocate(self, identity, *, sweep=False):
                return "10.0.0.77"

        self.rx = Moved()
        self.link = ReceiverLink(lambda brand, host, **o: self.rx)
        self.link.bind("10.0.0.5")
        self.rx.simulate_link(False)
        self.rx.get_state()
        saved = []
        with mock.patch.object(self.link, "seconds_since_bind", return_value=30.0), \
             mock.patch.object(dc, "get_receiver_link", return_value=self.link), \
             mock.patch.object(dc, "write_saved_av_receiver", side_effect=saved.append):
            kw = self.run_tick(avr_slot_holder=[{"address": "10.0.0.5"}])
        self.assertEqual(kw["receiver_http_host"]["host"], "10.0.0.77")
        self.assertEqual(self.link.host, "10.0.0.77")
        self.assertEqual(saved[0]["address"], "10.0.0.77")


    def test_tick_without_a_saved_receiver_releases_and_blanks_display(self) -> None:
        with mock.patch.object(dc, "read_saved_av_receiver", return_value=None):
            kw = self.run_tick(
                receiver_overlay_state={"incoming": "x", "config": "y", "volume": "-40.0 dB", "input": "TV"},
                denon_vol_cache={"effective": "-40.0 dB", "np_hold": "-40.0 dB"},
                receiver_http_host={"host": "10.0.0.5"},
            )
        self.assertIsNone(self.link.receiver)
        self.assertFalse(self.rx.connected)
        self.assertEqual(kw["receiver_http_host"]["host"], "")
        self.assertIsNone(kw["avr_slot_holder"][0])
        self.assertEqual(set(kw["receiver_overlay_state"].values()), {""})
        self.assertEqual(kw["denon_vol_cache"]["effective"], "")

    def test_tick_with_unreadable_settings_keeps_the_receiver(self) -> None:
        with mock.patch.object(dc, "read_saved_av_receiver", side_effect=OSError("busy")):
            kw = self.run_tick()
        self.assertIs(self.link.receiver, self.rx)
        self.assertTrue(self.rx.connected)
        self.assertEqual(kw["receiver_overlay_state"]["incoming"], "dolby digital")

    def test_poll_result_for_a_removed_receiver_does_not_repaint(self) -> None:
        host = {"host": "10.0.0.5"}

        def removed_mid_poll():
            host["host"] = ""  # the receiver is removed while the worker thread runs
            return ReceiverState(connected=True, volume_db=-40.0)

        with mock.patch.object(self.link, "state", side_effect=removed_mid_poll):
            kw = self.run_tick(receiver_http_host=host)
        self.assertEqual(kw["receiver_overlay_state"], {})
        self.assertFalse(kw["receiver_poll_busy"]["active"])


if __name__ == "__main__":
    unittest.main()
