"""Receiver-independent behavior against the generic ``Receiver`` interface.

Contract tests run against FakeReceiver; the Denon adapter is checked with
injected stand-ins (no network). No test here talks to a real receiver.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.receiver import ADAPTERS, create_receiver  # noqa: E402
from pigeon.receiver.base import (  # noqa: E402
    EVT_COMMAND, EVT_CONNECTION, EVT_EXTERNAL, EVT_RESPONSE, EVT_ERROR,
    InputSelectable, Receiver, ReceiverState,
)
from pigeon.receiver.control import apply_rotary_action  # noqa: E402
from pigeon.receiver.diag import DiagSession  # noqa: E402
from pigeon.receiver.fake import FakeReceiver  # noqa: E402


class DiscoveryTests(unittest.TestCase):
    def test_denon_discoverer_maps_scan_rows(self) -> None:
        from pigeon.receiver import DiscoveredReceiver, discover_receivers

        rows = [{"host": "10.0.4.64:8080", "name": "AVR-S670H", "id": "x"}, {"host": "", "name": "bad"}]
        with mock.patch("pigeon.receiver_denon.scan_denon_like_receivers_on_lan", return_value=(True, "", rows)):
            self.assertEqual(discover_receivers(["denon"]), [DiscoveredReceiver("denon", "10.0.4.64", "AVR-S670H", "x")])

    def test_broken_discoverer_is_skipped_and_unknown_brand_raises(self) -> None:
        from pigeon.receiver import discover_receivers

        with mock.patch("pigeon.receiver_denon.scan_denon_like_receivers_on_lan", side_effect=OSError):
            self.assertEqual([r.brand for r in discover_receivers()], ["fake"])
        with self.assertRaises(ValueError):
            discover_receivers(["nope"])


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def connected_fake(**kw) -> FakeReceiver:
    r = FakeReceiver(**kw)
    r.connect()
    return r


class FakeReceiverContract(unittest.TestCase):
    def test_conforms_to_protocols(self) -> None:
        r = FakeReceiver()
        self.assertIsInstance(r, Receiver)
        self.assertIsInstance(r, InputSelectable)

    def test_state_available_after_connect(self) -> None:
        s = connected_fake().get_state()
        self.assertTrue(s.connected)
        self.assertTrue(s.powered_on)
        self.assertEqual(s.volume_db, -40.0)
        self.assertEqual(s.volume_line, "-40.0 dB")

    def test_volume_steps_and_clamp(self) -> None:
        r = connected_fake()
        r.step_volume(3)
        self.assertEqual(r.get_state().volume_db, -38.5)
        r.step_volume(-1)
        self.assertEqual(r.get_state().volume_db, -39.0)
        r.simulate_volume(17.5)
        r.step_volume(5)
        self.assertEqual(r.get_state().volume_db, 18.0)

    def test_mute_toggle_and_line(self) -> None:
        r = connected_fake()
        r.toggle_mute()
        s = r.get_state()
        self.assertTrue(s.muted)
        self.assertEqual(s.volume_line, "mute")
        r.toggle_mute()
        self.assertFalse(r.get_state().muted)

    def test_power_and_standby_ignores_volume_unless_wake(self) -> None:
        r = connected_fake()
        r.set_power(False)
        self.assertFalse(r.get_state().powered_on)
        r.step_volume(2)
        self.assertEqual(r.get_state().volume_db, -40.0)
        self.assertFalse(r.get_state().powered_on)
        r.step_volume(2, wake=True)
        s = r.get_state()
        self.assertTrue(s.powered_on)
        self.assertEqual(s.volume_db, -39.0)

    def test_input_change(self) -> None:
        r = connected_fake()
        self.assertTrue(r.set_input("Game"))
        self.assertEqual(r.get_state().input_label, "Game")
        self.assertFalse(r.set_input("Nope"))
        self.assertEqual(r.get_state().input_label, "Game")

    def test_external_changes_reach_listeners(self) -> None:
        r = connected_fake()
        seen: list[tuple[ReceiverState, ReceiverState]] = []
        r.add_state_listener(lambda old, new: seen.append((old, new)))
        r.simulate_volume(-35)
        r.simulate_input("Game")
        r.simulate_power(False)
        self.assertEqual(len(seen), 3)
        self.assertEqual(seen[0][0].volume_db, -40.0)
        self.assertEqual(seen[0][1].volume_db, -35.0)
        last = r.cached_state()
        self.assertEqual((last.input_label, last.powered_on), ("Game", False))

    def test_disconnect_reconnect_is_safe(self) -> None:
        r = connected_fake()
        r.simulate_link(False)
        self.assertFalse(r.get_state().connected)
        self.assertFalse(r.step_volume(1))  # reported, not raised
        self.assertFalse(r.toggle_mute())
        self.assertFalse(r.set_power(False))
        r.simulate_link(True)
        s = r.get_state()
        self.assertTrue(s.connected)
        self.assertEqual(s.volume_db, -40.0)  # nothing leaked through while down
        r.disconnect()
        self.assertFalse(r.get_state().connected)
        r.connect()
        self.assertTrue(r.get_state().connected)

    def test_external_change_while_disconnected_seen_after_reconnect(self) -> None:
        r = connected_fake()
        r.simulate_link(False)
        r.simulate_volume(-10)
        r.simulate_link(True)
        self.assertEqual(r.get_state().volume_db, -10.0)

    def test_delayed_feedback(self) -> None:
        clk = Clock()
        r = connected_fake(latency_s=0.5, clock=clk)
        changes: list[float | None] = []
        r.add_state_listener(lambda o, n: changes.append(n.volume_db))
        self.assertTrue(r.step_volume(2))  # returns immediately
        self.assertEqual(r.get_state().volume_db, -40.0)  # not yet
        clk.t += 0.4
        self.assertEqual(r.get_state().volume_db, -40.0)
        clk.t += 0.2
        self.assertEqual(r.get_state().volume_db, -39.0)
        self.assertEqual(changes, [-39.0])

    def test_delayed_command_lost_when_link_drops(self) -> None:
        clk = Clock()
        r = connected_fake(latency_s=0.5, clock=clk)
        r.step_volume(4)
        r.simulate_link(False)
        r.simulate_link(True)
        clk.t += 5
        self.assertEqual(r.get_state().volume_db, -40.0)

    def test_external_change_during_delayed_command_composes(self) -> None:
        clk = Clock()
        r = connected_fake(latency_s=0.5, clock=clk)
        r.step_volume(2)  # +1 dB, lands later
        r.simulate_volume(-20)
        clk.t += 1
        self.assertEqual(r.get_state().volume_db, -19.0)

    def test_auto_pump_thread_applies_delay(self) -> None:
        r = connected_fake(latency_s=0.05)
        r.start_auto_pump(0.01)
        try:
            done = threading.Event()
            r.add_state_listener(lambda o, n: done.set() if n.volume_db != o.volume_db else None)
            r.step_volume(1)
            self.assertTrue(done.wait(1.0))
        finally:
            r.stop_auto_pump()

    def test_listener_exception_does_not_break_receiver(self) -> None:
        r = connected_fake()
        r.add_state_listener(lambda o, n: 1 / 0)
        r.simulate_volume(-30)
        self.assertEqual(r.get_state().volume_db, -30.0)


class ReceiverIndependentLogic(unittest.TestCase):
    """Code that only knows ``Receiver`` — the swap-in-another-adapter test."""

    def test_rotary_actions(self) -> None:
        r = connected_fake()
        self.assertTrue(apply_rotary_action(r, "volume_up"))
        self.assertTrue(apply_rotary_action(r, "volume_up"))
        self.assertTrue(apply_rotary_action(r, "volume_down"))
        self.assertEqual(r.get_state().volume_db, -39.5)
        apply_rotary_action(r, "mute_toggle")
        self.assertTrue(r.get_state().muted)
        self.assertFalse(apply_rotary_action(r, "bogus"))

    def test_rotary_from_standby_wakes(self) -> None:
        r = connected_fake()
        r.simulate_power(False)
        apply_rotary_action(r, "volume_up", wake=True)
        self.assertTrue(r.get_state().powered_on)

    def test_registry(self) -> None:
        self.assertEqual(set(ADAPTERS), {"denon", "fake"})
        self.assertIsInstance(create_receiver("FAKE"), FakeReceiver)
        with self.assertRaises(ValueError):
            create_receiver("yamaha")


class DiagSessionTests(unittest.TestCase):
    def make(self) -> tuple[DiagSession, FakeReceiver]:
        r = FakeReceiver()
        return DiagSession("fake", receiver=r), r

    def kinds(self, s: DiagSession) -> list[str]:
        return [e.kind for e in s.events]

    def test_log_distinguishes_event_kinds(self) -> None:
        s, r = self.make()
        s.connect()
        s.volume(1)
        r.simulate_volume(-30)
        r.simulate_link(False)
        s.volume(1)
        k = self.kinds(s)
        for want in (EVT_CONNECTION, EVT_COMMAND, EVT_RESPONSE, EVT_EXTERNAL):
            self.assertIn(want, k)
        text = s.export_text()
        self.assertIn("SENT", text)
        self.assertIn("EXTERNAL", text)
        self.assertIn("# adapter: fake", text)

    def test_state_tracks_receiver(self) -> None:
        s, r = self.make()
        s.connect()
        self.assertTrue(s.state.connected)
        r.simulate_volume(-12)
        self.assertEqual(s.state.volume_db, -12.0)

    def test_input_support_follows_capability(self) -> None:
        s, _ = self.make()
        self.assertTrue(s.supports_input)
        self.assertIn("Game", s.inputs())

        class NoInput(FakeReceiver):
            set_input = None  # type: ignore[assignment]
            available_inputs = None  # type: ignore[assignment]

        s2 = DiagSession("x", receiver=NoInput())
        self.assertFalse(s2.supports_input)
        self.assertFalse(s2.set_input("Game"))

    def test_adapter_exception_becomes_error_entry(self) -> None:
        s, r = self.make()

        def boom(*a, **k):
            raise RuntimeError("bad frame")

        r.set_power = boom  # type: ignore[assignment]
        s.connect()
        s.power(True)
        self.assertIn(EVT_ERROR, self.kinds(s))

    def test_save(self) -> None:
        import tempfile
        s, _ = self.make()
        s.connect()
        with tempfile.TemporaryDirectory() as d:
            p = s.save(os.path.join(d, "x.log"))
            with open(p) as f:
                self.assertIn("Pigeon receiver diagnostic log", f.read())


class DenonAdapterTests(unittest.TestCase):
    """DenonReceiver mapped onto the interface with injected poll + transport."""

    class Transport:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.st: dict = {"connected": True, "mv": 45.0, "mv_mono": 1.0, "mu": False, "pw": "ON"}

        def ensure(self, host): pass
        def state(self, host): return dict(self.st)
        def send(self, host, command, *, timeout):
            self.sent.append(command)
            return 1.0
        def http_send(self, host, command):
            self.sent.append("http:" + command)
            return True
        def heos_adjust(self, host, steps): return True, ""
        def add_observer(self, cb): self.observer = cb

    def make(self, result=None):
        from pigeon.receiver.denon import DenonReceiver
        from pigeon.receiver_denon import ReceiverPollResult
        from pigeon.receiver_volume import ReceiverVolumeController

        tr = self.Transport()
        res = result or ReceiverPollResult(True, "-35.0 dB", "dolby", "surround", {}, input_label="Apple TV")
        ctrl = ReceiverVolumeController(tr)
        rx = DenonReceiver("10.0.0.5", poll_fn=lambda h, t: res, transport=tr, controller=ctrl)
        rx._active = True  # skip threads: exercise mapping directly
        return rx, tr, ctrl

    def test_conforms_and_has_input_capability(self) -> None:
        rx, *_ = self.make()
        self.assertIsInstance(rx, Receiver)
        self.assertIsInstance(rx, InputSelectable)

    def test_set_input_sends_si_code(self) -> None:
        rx, tr, _ = self.make()
        with mock.patch("pigeon.receiver_denon.fetch_denon_source_renames", return_value={"mplay": "Apple TV"}):
            self.assertIn("Apple TV", rx.available_inputs())
            self.assertTrue(rx.set_input("apple tv"))
            self.assertFalse(rx.set_input("Nope"))
        self.assertEqual(tr.sent, ["SIMPLAY"])

    def test_poll_maps_to_state(self) -> None:
        rx, *_ = self.make()
        s = rx.get_state()
        self.assertEqual(
            (s.connected, s.powered_on, s.volume_db, s.muted, s.input_label, s.audio_format, s.sound_mode),
            (True, True, -35.0, False, "Apple TV", "dolby", "surround"),
        )

    def test_standby_and_mute_and_unreachable(self) -> None:
        from pigeon.receiver_denon import ReceiverPollResult
        rx, tr, _ = self.make(ReceiverPollResult(True, "-30.0 dB", "", "", {}, standby=True))
        self.assertFalse(rx.get_state().powered_on)
        rx2, *_ = self.make(ReceiverPollResult(True, "mute", "", "", {}))
        self.assertTrue(rx2.get_state().muted)
        rx3, tr3, _ = self.make(ReceiverPollResult(False, "", "", ""))
        tr3.st = {}
        self.assertFalse(rx3.get_state().connected)

    def test_hub_update_is_reported_external(self) -> None:
        rx, tr, _ = self.make()
        events, changes = [], []
        rx.set_event_sink(events.append)
        rx.add_state_listener(lambda o, n: changes.append(n.volume_db))
        rx.get_state()
        rx._reachable = True
        tr.st["mv"] = 50.0  # remote turned it up
        tr.st["mv_mono"] = time.monotonic()  # ...after the poll
        rx._merge(rx._from_hub(), source="hub")
        self.assertEqual(changes[-1], -30.0)
        self.assertEqual(events[-1].kind, EVT_EXTERNAL)

    def test_disconnected_hub_snapshot_never_overwrites_fresh_http(self) -> None:
        rx, tr, _ = self.make()
        self.assertEqual(rx.get_state().volume_db, -35.0)  # fresh HTTP reading
        rx._reachable = True
        # Socket dropped; the snapshot still holds the last session's 20.0 (-60 dB).
        tr.st.update(connected=False, mv=20.0, mv_mono=time.monotonic() + 1, mu=True, mu_mono=time.monotonic() + 1, pw="STANDBY")
        self.assertIsNone(rx._from_hub())
        self.assertEqual(rx.cached_state().volume_db, -35.0)
        self.assertTrue(rx.cached_state().powered_on)

    def test_hub_reading_older_than_the_poll_is_ignored_newer_is_taken(self) -> None:
        rx, tr, _ = self.make()
        rx._reachable = True
        old = time.monotonic() - 5
        tr.st.update(mv=20.0, mv_mono=old, mu=True, mu_mono=old, pw="STANDBY", pw_mono=old)
        rx.get_state()  # poll started after those readings
        merged = rx._from_hub()
        self.assertEqual((merged.volume_db, merged.muted, merged.powered_on), (-35.0, False, True))
        fresh = time.monotonic() + 1  # remote / front panel, after the poll
        tr.st.update(mv=50.0, mv_mono=fresh, mu=True, mu_mono=fresh, pw="STANDBY", pw_mono=fresh)
        merged = rx._from_hub()
        self.assertEqual((merged.volume_db, merged.muted, merged.powered_on), (-30.0, True, False))

    def test_poll_finishing_after_disconnect_is_discarded(self) -> None:
        from pigeon.receiver_denon import ReceiverPollResult

        started, release = threading.Event(), threading.Event()

        def slow_poll(host, timeout):
            started.set()
            release.wait(5)
            return ReceiverPollResult(True, "-35.0 dB", "dolby", "surround", {}, input_label="Apple TV")

        rx, tr, _ = self.make()
        rx._poll_fn = slow_poll
        seen = []
        rx.add_state_listener(lambda o, n: seen.append(n.connected))
        t = threading.Thread(target=rx.get_state)
        t.start()
        self.assertTrue(started.wait(2))
        rx.disconnect()
        release.set()
        t.join(5)
        self.assertFalse(rx.cached_state().connected)
        self.assertFalse(rx.connected)
        self.assertNotIn(True, seen)

    def test_unreachable_poll_finishing_after_disconnect_is_discarded(self) -> None:
        from pigeon.receiver_denon import ReceiverPollResult

        started, release = threading.Event(), threading.Event()

        def slow_poll(host, timeout):
            started.set()
            release.wait(5)
            return ReceiverPollResult(False, "", "", "")

        rx, tr, _ = self.make()
        tr.st = {}
        rx._poll_fn = slow_poll
        rx._reachable = True
        t = threading.Thread(target=rx.get_state)
        t.start()
        self.assertTrue(started.wait(2))
        rx.disconnect()
        events = []
        rx.set_event_sink(events.append)
        release.set()
        t.join(5)
        self.assertEqual(events, [])  # no "no answer" timeout reported for a closed adapter

    def test_poll_started_before_reconnect_cannot_commit_into_the_new_connection(self) -> None:
        from pigeon.receiver_denon import ReceiverPollResult

        started, release = threading.Event(), threading.Event()
        results = [ReceiverPollResult(True, "-35.0 dB", "", ""), ReceiverPollResult(True, "-20.0 dB", "", "")]

        def poll(host, timeout):
            r = results.pop(0)
            if r.volume == "-35.0 dB":
                started.set()
                release.wait(5)
            return r

        rx, tr, _ = self.make()
        rx._poll_fn = poll
        t = threading.Thread(target=rx.get_state)
        t.start()
        self.assertTrue(started.wait(2))
        rx.disconnect()
        rx._active = True
        rx._generation += 1  # a new connection took over
        self.assertEqual(rx.get_state().volume_db, -20.0)
        release.set()
        t.join(5)
        self.assertEqual(rx.cached_state().volume_db, -20.0)

    def test_disconnect_releases_worker_observer_and_hub(self) -> None:
        from pigeon.receiver.denon import DenonReceiver
        from pigeon.receiver_denon import ReceiverPollResult
        from pigeon.receiver_volume import ReceiverVolumeController

        class Tr(self.Transport):
            def __init__(self) -> None:
                super().__init__()
                self.observers, self.released = [], []

            def add_observer(self, cb): self.observers.append(cb)
            def remove_observer(self, cb): self.observers.remove(cb)
            def release(self, host): self.released.append(host)

        tr = Tr()
        ctrl = ReceiverVolumeController(tr)
        rx = DenonReceiver(
            "10.0.0.5", poll_fn=lambda h, t: ReceiverPollResult(True, "-35.0 dB", "", ""),
            transport=tr, controller=ctrl, full_poll_s=60,
        )
        rx.connect()
        self.assertTrue(rx.connected)
        worker = rx._worker
        self.assertTrue(worker.is_alive())
        self.assertEqual(len(tr.observers), 2)  # adapter wake + controller
        rx.disconnect()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(tr.observers, [])
        self.assertEqual(tr.released, ["10.0.0.5"])
        self.assertFalse(rx.step_volume(1))
        # A late command confirmation from the old session reaches nobody.
        heard = []
        rx.add_volume_confirmed_listener(heard.append)
        rx._on_confirmed("10.0.0.5", "-30.0 dB")
        self.assertEqual(heard, [])
        rx.connect()  # the same adapter can be brought back
        self.assertTrue(rx._worker.is_alive())
        rx.disconnect()

    def test_commands_use_existing_command_path(self) -> None:
        rx, tr, ctrl = self.make()
        self.assertTrue(rx.set_power(False))
        self.assertEqual(tr.sent, ["PWSTANDBY"])
        rx.step_volume(2)
        rx.toggle_mute()
        self.assertEqual(ctrl._pending_rel, 2)
        self.assertEqual(ctrl._mutes, 1)
        self.assertTrue(rx.step_volume(0))


if __name__ == "__main__":
    unittest.main()
