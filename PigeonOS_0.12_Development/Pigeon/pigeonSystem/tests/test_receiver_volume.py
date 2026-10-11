"""Rotary → AVR master volume: coalescing, confirmation, fallbacks.

Controller tests drive ``ReceiverVolumeController.step`` against a fake
receiver on a fake clock. Hub tests use a real localhost TCP server standing
in for the AVR's port 23. Nothing here talks to a real receiver.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.receiver_denon_telnet import (  # noqa: E402
    _denon_mv_to_db,
    denon_mv_to_units,
    denon_units_to_mv,
)
from pigeon.receiver_volume import (  # noqa: E402
    CONFIRM_GRACE_S,
    CONFIRM_S,
    SEND_GIVE_UP_S,
    SETTLE_HOLD_S,
    LatencyDiag,
    ReceiverVolumeController,
    apply_receiver_volume_once,
    units_to_line,
)

HOST = "10.0.0.50"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += max(0.0, float(dt))


class FakeAvr:
    """Receiver + hub as the controller sees them."""

    def __init__(
        self,
        clock: Clock,
        *,
        mv: float | None = 50.0,
        connected: bool = True,
        max_units: float | None = 98.0,
        mu: bool | None = False,
        pw: str = "ON",
        latency: float = 0.05,
        echo: bool = True,
        ignore_mv: bool = False,
        answers_query: bool = True,
        http_ok: bool = True,
    ) -> None:
        self.clock = clock
        self.level = mv            # what the AVR is actually at
        self.reported = mv         # what the hub last heard
        self.mv_mono = clock() if mv is not None else 0.0
        self.connected = connected
        self.max_units = max_units
        self.mu = mu
        self.mu_mono = clock()
        self.pw = pw
        self.latency = latency
        self.echo = echo
        self.ignore_mv = ignore_mv
        self.answers_query = answers_query
        self.http_ok = http_ok
        self.written: list[tuple[str, str]] = []   # (host, cmd) that hit the wire
        self.http: list[tuple[str, str]] = []
        self.heos: list[tuple[str, int]] = []
        self.feedback: list[tuple[float, str, object]] = []

    # -- receiver side --
    def _queue(self, kind: str, value: object, delay: float | None = None) -> None:
        d = self.latency if delay is None else delay
        self.feedback.append((self.clock() + d, kind, value))

    def deliver(self) -> None:
        now = self.clock()
        due = [f for f in self.feedback if f[0] <= now]
        self.feedback = [f for f in self.feedback if f[0] > now]
        for at, kind, value in sorted(due, key=lambda f: f[0]):
            if kind == "MV":
                self.reported = value
                self.mv_mono = at
            elif kind == "MU":
                self.mu = value
                self.mu_mono = at

    def _apply(self, cmd: str) -> None:
        if cmd == "MV?":
            if self.answers_query and self.level is not None:
                self._queue("MV", self.level)
            return
        if cmd == "MU?":
            if self.answers_query:
                self._queue("MU", bool(self.mu))
            return
        if cmd in ("MUON", "MUOFF"):
            self._queue("MU", cmd == "MUON")
            return
        if cmd == "PWON":
            self.pw = "ON"
            return
        if cmd in ("MVUP", "MVDOWN"):
            if self.level is not None and not self.ignore_mv:
                self.level += 0.5 if cmd == "MVUP" else -0.5
            if self.echo and self.level is not None:
                self._queue("MV", self.level)
            return
        if cmd.startswith("MV"):
            if not self.ignore_mv:
                u = denon_mv_to_units(cmd[2:])
                hi = self.max_units if self.max_units is not None else 98.0
                self.level = max(0.0, min(hi, u))
            if self.echo:
                self._queue("MV", self.level)

    # -- transport API --
    def ensure(self, host: str) -> None:
        pass

    def state(self, host: str) -> dict[str, object]:
        self.deliver()
        return {
            "connected": self.connected,
            "mv": self.reported,
            "mv_mono": self.mv_mono,
            "max": self.max_units,
            "mu": self.mu,
            "mu_mono": self.mu_mono,
            "pw": self.pw,
        }

    def send(self, host: str, command: str, *, timeout: float) -> float | None:
        if not self.connected:
            return None
        self.written.append((host, command))
        self._apply(command)
        return self.clock()

    def http_send(self, host: str, command: str) -> bool:
        self.http.append((host, command))
        if self.http_ok:
            self._apply(command)
        return self.http_ok

    def heos_adjust(self, host: str, steps: int) -> tuple[bool, str]:
        self.heos.append((host, steps))
        return True, f"HEOS: {steps:+d}"

    def add_observer(self, cb) -> None:
        pass

    # -- helpers --
    def mv_writes(self) -> list[str]:
        return [c for _h, c in self.written if c.startswith("MV") and c != "MV?"]


def make(avr: FakeAvr, clock: Clock):
    confirmed: list[str] = []
    results: list[tuple[bool, str]] = []
    c = ReceiverVolumeController(
        avr,
        clock=clock,
        sleep=clock.advance,
        on_confirmed=lambda _h, line: confirmed.append(line),
        on_result=lambda _h, ok, msg: results.append((ok, msg)),
        diag=LatencyDiag(clock=clock, every_s=1e9),
    )
    return c, confirmed, results


def run(c: ReceiverVolumeController, clock: Clock, *, limit: float = 10.0) -> None:
    end = clock() + limit
    while c.has_work() and clock() < end:
        d = c.step()
        clock.advance(max(0.01, d))


class EncodingTests(unittest.TestCase):
    def test_units_to_mv(self) -> None:
        self.assertEqual(denon_units_to_mv(52.5), "525")
        self.assertEqual(denon_units_to_mv(52.0), "52")
        self.assertEqual(denon_units_to_mv(5.0), "05")
        self.assertEqual(denon_units_to_mv(0.5), "005")
        self.assertEqual(denon_units_to_mv(0.0), "00")
        self.assertEqual(denon_units_to_mv(-3.0), "00")
        self.assertEqual(denon_units_to_mv(120.0), "98")
        self.assertEqual(denon_units_to_mv(52.3), "525")

    def test_mv_to_units_and_db(self) -> None:
        self.assertEqual(denon_mv_to_units("525"), 52.5)
        self.assertEqual(denon_mv_to_units("80"), 80.0)
        self.assertEqual(denon_mv_to_units("05"), 5.0)
        self.assertIsNone(denon_mv_to_units("MAX"))
        # 99 / 995 are the below-00 minimum, not +19 dB.
        self.assertEqual(denon_mv_to_units("995"), -0.5)
        self.assertEqual(_denon_mv_to_db("995"), "-80.5 dB")
        self.assertEqual(_denon_mv_to_db("575"), "-22.5 dB")
        self.assertEqual(units_to_line(52.5), "-27.5 dB")


class BurstTests(unittest.TestCase):
    def test_rapid_burst_sends_one_absolute_target(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0)
        c, confirmed, _ = make(avr, clock)
        for _ in range(16):
            c.submit(HOST, "volume_up")
        run(c, clock)
        self.assertEqual(avr.mv_writes(), ["MV58"])
        self.assertEqual(avr.level, 58.0)
        self.assertEqual(confirmed, ["-22.0 dB"])
        self.assertFalse(c.has_work())

    def test_continuous_spin_is_rate_limited_not_backlogged(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, latency=0.12)
        c, confirmed, _ = make(avr, clock)
        # 20 detents, one every 15 ms, worker stepping in between.
        for _ in range(20):
            c.submit(HOST, "volume_up")
            d = c.step()
            clock.advance(min(0.015, max(0.0, d)) or 0.015)
        run(c, clock)
        writes = avr.mv_writes()
        self.assertLessEqual(len(writes), 6, writes)
        self.assertEqual(writes[-1], "MV60")
        self.assertEqual(avr.level, 60.0)
        self.assertEqual(confirmed[-1], "-20.0 dB")
        # Nothing went out after the AVR reached the final level.
        self.assertEqual(writes.count("MV60"), 1)

    def test_reversal_supersedes_pending_target(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, latency=0.3)
        c, confirmed, _ = make(avr, clock)
        for _ in range(6):
            c.submit(HOST, "volume_up")
        c.step()  # writes MV53
        self.assertEqual(avr.mv_writes(), ["MV53"])
        for _ in range(8):
            c.submit(HOST, "volume_down")
        # The pending target is now 49; MV53 echoes are older than that.
        self.assertTrue(c.readout_superseded("-27.0 dB"))
        self.assertFalse(c.readout_superseded("-31.0 dB"))
        run(c, clock)
        self.assertEqual(avr.mv_writes(), ["MV53", "MV49"])
        self.assertEqual(avr.level, 49.0)
        self.assertEqual(confirmed, ["-31.0 dB"])
        self.assertNotIn("-27.0 dB", confirmed)

    def test_up_then_down_before_send_is_a_no_op(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0)
        c, _, _ = make(avr, clock)
        c.submit(HOST, "volume_up")
        c.submit(HOST, "volume_down")
        run(c, clock)
        self.assertEqual(avr.mv_writes(), [])


class FeedbackTests(unittest.TestCase):
    def test_late_hub_feedback_never_triggers_heos_or_resend(self) -> None:
        # Command lands, but the hub snapshot stays at the pre-command level
        # (no echo yet). HTTP would already show the move; we never read it.
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, echo=False, answers_query=False)
        c, confirmed, results = make(avr, clock)
        c.submit(HOST, "volume_up")
        run(c, clock)
        self.assertEqual(avr.mv_writes(), ["MV505"])
        self.assertEqual(avr.level, 50.5)  # the AVR did move
        self.assertEqual(avr.heos, [])
        self.assertEqual(avr.http, [])
        self.assertEqual(confirmed, [])
        # The moved HTTP level is not suppressed once we stop waiting.
        self.assertFalse(c.readout_superseded("-29.5 dB"))

    def test_slow_echo_confirms_without_resend(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, latency=CONFIRM_S + 0.3)
        c, confirmed, _ = make(avr, clock)
        c.submit(HOST, "volume_up")
        run(c, clock)
        self.assertEqual(avr.mv_writes(), ["MV505"])
        self.assertEqual(avr.heos, [])
        self.assertEqual(confirmed, ["-29.5 dB"])

    def test_pre_command_snapshot_is_not_confirmation(self) -> None:
        # Hub already shows the target value, but from *before* the write.
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, echo=False, answers_query=False)
        c, confirmed, _ = make(avr, clock)
        c.submit(HOST, "volume_up")
        c.step()  # MV505 written at t0
        avr.reported = 50.5
        avr.mv_mono = clock() - 0.5  # arrived before the write
        c.step()
        self.assertEqual(confirmed, [])
        self.assertTrue(c.has_work())

    def test_heos_only_when_fresh_feedback_proves_no_move(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, ignore_mv=True)
        c, confirmed, results = make(avr, clock)
        c.submit(HOST, "volume_up")
        c.submit(HOST, "volume_up")
        run(c, clock)
        self.assertEqual(avr.mv_writes(), ["MV51"])
        self.assertEqual(avr.heos, [(HOST, 2)])
        # Readout stays AVR master volume, not the HEOS player level.
        self.assertEqual(confirmed, ["-30.0 dB"])
        self.assertTrue(results[-1][0])

    def test_late_feedback_cannot_overwrite_newer_target(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, latency=0.25)
        c, confirmed, _ = make(avr, clock)
        c.submit(HOST, "volume_up")
        c.submit(HOST, "volume_up")
        c.step()  # MV51
        clock.advance(0.1)
        for _ in range(4):
            c.submit(HOST, "volume_up")
        c.step()  # MV53
        clock.advance(0.2)  # MV51 echo arrives now, after MV53 went out
        c.step()
        self.assertEqual(confirmed, [])
        self.assertTrue(c.readout_superseded("-29.0 dB"))  # MV51
        run(c, clock)
        self.assertEqual(confirmed, ["-27.0 dB"])
        # Lagging pollers stay held to the confirmed level briefly…
        self.assertTrue(c.readout_superseded("-29.0 dB"))
        self.assertFalse(c.readout_superseded("-27.0 dB"))
        # …then the receiver is free to report anything (e.g. the remote).
        clock.advance(SETTLE_HOLD_S + 0.1)
        self.assertFalse(c.readout_superseded("-29.0 dB"))

    def test_receiver_clamp_is_adopted(self) -> None:
        clock = Clock()
        # AVR limit 55 but MVMAX not reported: AVR clamps; we adopt, no retry.
        avr = FakeAvr(clock, mv=54.0, max_units=None)
        avr.max_units = None
        c, confirmed, _ = make(avr, clock)
        avr_hi = 55.0

        orig_apply = avr._apply

        def clamp_apply(cmd: str) -> None:
            orig_apply(cmd)
            if avr.level is not None and avr.level > avr_hi:
                avr.level = avr_hi
                avr.feedback = [(t, k, avr_hi if k == "MV" else v) for t, k, v in avr.feedback]

        avr._apply = clamp_apply
        for _ in range(6):
            c.submit(HOST, "volume_up")
        run(c, clock)
        self.assertEqual(avr.mv_writes(), ["MV57"])
        self.assertEqual(confirmed, ["-25.0 dB"])
        self.assertEqual(avr.heos, [])


class LimitTests(unittest.TestCase):
    def test_mvmax_caps_target(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=59.5, max_units=60.0)
        c, confirmed, _ = make(avr, clock)
        for _ in range(5):
            c.submit(HOST, "volume_up")
        run(c, clock)
        self.assertEqual(avr.mv_writes(), ["MV60"])

    def test_floor_is_mv00(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=0.5)
        c, confirmed, _ = make(avr, clock)
        for _ in range(5):
            c.submit(HOST, "volume_down")
        run(c, clock)
        self.assertEqual(avr.mv_writes(), ["MV00"])

    def test_single_burst_is_bounded(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=40.0)
        c, _, _ = make(avr, clock)
        for _ in range(80):  # 40 dB of detents before any feedback
            c.submit(HOST, "volume_up")
        c.step()
        self.assertEqual(avr.mv_writes(), ["MV52"])  # +12 dB cap from last report


class UnknownBaselineTests(unittest.TestCase):
    def test_fetches_fresh_baseline_then_absolute(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=None)
        avr.level = 40.0  # AVR knows; the hub has not heard yet
        c, confirmed, _ = make(avr, clock)
        for _ in range(3):
            c.submit(HOST, "volume_up")
        run(c, clock)
        self.assertEqual([cmd for _h, cmd in avr.written], ["MV?", "MV415"])
        self.assertEqual(confirmed, ["-38.5 dB"])

    def test_stale_baseline_is_not_trusted(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0)
        avr.level = 44.0          # changed by the remote while the hub was quiet
        clock.advance(10.0)       # hub reading is old now
        c, _, _ = make(avr, clock)
        c.submit(HOST, "volume_up")
        run(c, clock)
        self.assertEqual([cmd for _h, cmd in avr.written], ["MV?", "MV445"])

    def test_no_answer_uses_bounded_relative_steps(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=None, answers_query=False, echo=False)
        avr.level = 40.0
        c, confirmed, _ = make(avr, clock)
        for _ in range(11):
            c.submit(HOST, "volume_up")
        c.step()  # MV?
        clock.advance(0.5)
        c.step()  # first relative batch
        cmds = [cmd for _h, cmd in avr.written]
        self.assertEqual(cmds, ["MV?"] + ["MVUP"] * 8)  # bounded batch
        run(c, clock)
        cmds = [cmd for _h, cmd in avr.written]
        self.assertEqual(cmds.count("MVUP"), 11)
        # Never guessed an absolute level.
        self.assertFalse(any(x[2:].isdigit() for x in cmds))
        self.assertEqual(avr.level, 45.5)

    def test_relative_echo_becomes_the_baseline(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=None, answers_query=False)
        avr.level = 40.0
        c, confirmed, _ = make(avr, clock)
        for _ in range(11):
            c.submit(HOST, "volume_up")
        run(c, clock)
        cmds = [cmd for _h, cmd in avr.written]
        # 8 relative steps, then the AVR's own echo is a fresh baseline.
        self.assertEqual(cmds, ["MV?"] + ["MVUP"] * 8 + ["MV455"])
        self.assertEqual(confirmed[-1], "-34.5 dB")

    def test_hub_down_uses_http_relative(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, connected=False)
        avr.state = lambda host: {}  # hub not managing this host
        c, _, _ = make(avr, clock)
        for _ in range(3):
            c.submit(HOST, "volume_down")
        run(c, clock)
        self.assertEqual(avr.http, [(HOST, "MVDOWN")] * 3)
        self.assertEqual(avr.written, [])


class MuteWakeTests(unittest.TestCase):
    def test_mute_toggle_follows_hub_state(self) -> None:
        for mu, want in ((False, "MUON"), (True, "MUOFF")):
            clock = Clock()
            avr = FakeAvr(clock, mu=mu)
            c, _, results = make(avr, clock)
            c.submit(HOST, "mute_toggle")
            run(c, clock)
            self.assertEqual([cmd for _h, cmd in avr.written], [want])
            self.assertTrue(results[-1][0])

    def test_double_toggle_sends_nothing(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock)
        c, _, _ = make(avr, clock)
        c.submit(HOST, "mute_toggle")
        c.submit(HOST, "mute_toggle")
        run(c, clock)
        self.assertEqual(avr.written, [])

    def test_unknown_mute_asks_first(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mu=None)
        c, _, _ = make(avr, clock)
        c.submit(HOST, "mute_toggle")
        # The receiver answers MU? with "muted".
        orig = avr._apply

        def apply(cmd: str) -> None:
            if cmd == "MU?":
                avr._queue("MU", True)
                return
            orig(cmd)

        avr._apply = apply
        run(c, clock)
        self.assertEqual([cmd for _h, cmd in avr.written], ["MU?", "MUOFF"])

    def test_wake_sends_pwon_before_volume(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, pw="STANDBY")
        c, _, _ = make(avr, clock)
        c.submit(HOST, "volume_up", wake=True)
        run(c, clock)
        self.assertEqual([cmd for _h, cmd in avr.written][:2], ["PWON", "MV505"])

    def test_no_wake_when_already_on(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, pw="ON")
        c, _, _ = make(avr, clock)
        c.submit(HOST, "volume_up", wake=True)
        run(c, clock)
        self.assertNotIn("PWON", [cmd for _h, cmd in avr.written])


class ReconnectAndSelectionTests(unittest.TestCase):
    def test_unwritten_target_goes_out_once_after_reconnect(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, http_ok=False)
        c, confirmed, _ = make(avr, clock)
        c.submit(HOST, "volume_up")
        c.submit(HOST, "volume_up")
        c.step()  # target 51, MV51 written
        self.assertEqual(avr.mv_writes(), ["MV51"])
        c.submit(HOST, "volume_up")  # target 51.5
        avr.connected = False
        clock.advance(0.1)
        c.step()  # write fails (hub down, HTTP down): nothing sent
        self.assertEqual(avr.mv_writes(), ["MV51"])
        clock.advance(0.5)
        avr.connected = True
        run(c, clock)
        self.assertEqual(avr.mv_writes(), ["MV51", "MV515"])
        self.assertEqual(confirmed[-1], "-28.5 dB")

    def test_gives_up_when_nothing_can_be_written(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, http_ok=False)
        c, _, results = make(avr, clock)
        c.submit(HOST, "volume_up")
        c.step()  # baseline taken, MV505 written while connected
        c.submit(HOST, "volume_up")
        avr.connected = False
        run(c, clock, limit=SEND_GIVE_UP_S + CONFIRM_S + CONFIRM_GRACE_S + 2)
        self.assertFalse(c.has_work())
        self.assertFalse(results[-1][0])

    def test_receiver_change_clears_pending(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, latency=0.5)
        c, _, _ = make(avr, clock)
        for _ in range(4):
            c.submit(HOST, "volume_up")
        c.step()
        c.submit("10.0.0.99", "volume_down")
        run(c, clock)
        hosts = [h for h, cmd in avr.written if cmd.startswith("MV") and cmd != "MV?"]
        # The old host's pending target was dropped, not finished.
        self.assertEqual(hosts, [HOST, "10.0.0.99"])

    def test_reset_drops_work(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0)
        c, _, _ = make(avr, clock)
        c.submit(HOST, "volume_up")
        c.reset("10.0.0.99")
        self.assertFalse(c.has_work())
        run(c, clock)
        self.assertEqual(avr.written, [])


class DiagTests(unittest.TestCase):
    def test_diag_is_rate_limited(self) -> None:
        clock = Clock()
        d = LatencyDiag(clock=clock, every_s=2.0)
        with patch("sys.stderr"):
            d.detent()
            d.wrote(0.01)
            d.confirmed(0.08, 0.09)
            d.maybe_emit("-30.0 dB")
            d.detent()
            d.maybe_emit()
            clock.advance(2.1)
            d.maybe_emit()
        self.assertEqual(len(d.lines), 2)
        self.assertIn("input→tx avg 10ms", d.lines[0])
        self.assertIn("tx→confirm avg 80ms", d.lines[0])

    def test_controller_records_latency(self) -> None:
        clock = Clock()
        avr = FakeAvr(clock, mv=50.0, latency=0.07)
        c, _, _ = make(avr, clock)
        c.diag.every_s = 0.0
        c.submit(HOST, "volume_up")
        with patch("sys.stderr"):
            run(c, clock)
            c.diag.maybe_emit()
        self.assertTrue(c.diag.lines)
        self.assertIn("tx→confirm avg 70ms", c.diag.lines[-1])


class ApplyOnceTests(unittest.TestCase):
    def test_apply_once_reports_confirmed_master(self) -> None:
        # One-shot path runs on the real clock; the fake answers immediately.
        avr = FakeAvr(Clock(), mv=66.5, latency=0.0)
        avr.clock = time.monotonic
        avr.mv_mono = time.monotonic()
        ok, msg, vol = apply_receiver_volume_once(HOST, steps=1, transport=avr)
        self.assertTrue(ok, msg)
        self.assertEqual(vol, "-13.0 dB")
        self.assertEqual(avr.mv_writes(), ["MV67"])

    def test_send_denon_volume_control_uses_no_http_reads(self) -> None:
        from pigeon.receiver_denon import send_denon_volume_control

        avr = FakeAvr(Clock(), mv=66.5, latency=0.0)
        avr.clock = time.monotonic
        avr.mv_mono = time.monotonic()
        with patch(
            "pigeon.receiver_volume.DenonHubTransport", return_value=avr
        ), patch(
            "pigeon.receiver_denon.read_denon_appcommand_status",
            side_effect=AssertionError("no HTTP status reads on the volume path"),
        ):
            ok, msg = send_denon_volume_control(HOST, "volume_down")
        self.assertTrue(ok, msg)
        self.assertEqual(avr.mv_writes(), ["MV66"])


class FakeTelnetAvr:
    """Localhost TCP stand-in for the AVR's single-client port 23."""

    def __init__(self, level: str = "50") -> None:
        self.level = level
        self.connections = 0
        self.received: list[str] = []
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.srv.settimeout(0.2)
        self.port = self.srv.getsockname()[1]
        self.stop = threading.Event()
        self.conns: list[socket.socket] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while not self.stop.is_set():
            try:
                conn, _ = self.srv.accept()
            except (socket.timeout, OSError):
                continue
            self.connections += 1
            self.conns.append(conn)
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn: socket.socket) -> None:
        conn.settimeout(0.1)
        buf = b""
        try:
            while not self.stop.is_set():
                try:
                    chunk = conn.recv(256)
                except socket.timeout:
                    continue
                if not chunk:
                    return
                buf += chunk
                while b"\r" in buf:
                    line, buf = buf.split(b"\r", 1)
                    cmd = line.decode()
                    self.received.append(cmd)
                    out = self._reply(cmd)
                    if out:
                        conn.sendall(out.encode())
        except OSError:
            return

    def _reply(self, cmd: str) -> str:
        if cmd == "PW?":
            return "PWON\r"
        if cmd == "MU?":
            return "MUOFF\r"
        if cmd == "MV?":
            return f"MV{self.level}\rMVMAX 98\r"
        if cmd in ("MUON", "MUOFF"):
            return cmd + "\r"
        if cmd.startswith("MV") and cmd[2:].isdigit():
            self.level = cmd[2:]
            return f"MV{self.level}\rMVMAX 98\r"
        return ""

    def close(self) -> None:
        self.stop.set()
        for c in self.conns:
            try:
                c.close()
            except OSError:
                pass
        self.srv.close()


class TelnetHubTests(unittest.TestCase):
    def setUp(self) -> None:
        from pigeon.receiver_denon_telnet import start_denon_telnet_hub

        self.avr = FakeTelnetAvr("50")
        start_denon_telnet_hub("127.0.0.1", port=self.avr.port)
        from pigeon.receiver_denon_telnet import _VOLUME_HUB

        end = time.monotonic() + 3.0
        while time.monotonic() < end and not _VOLUME_HUB.is_connected("127.0.0.1"):
            time.sleep(0.02)
        self.assertTrue(_VOLUME_HUB.is_connected("127.0.0.1"))

    def tearDown(self) -> None:
        from pigeon.receiver_denon_telnet import stop_denon_telnet_hub

        stop_denon_telnet_hub()
        self.avr.close()

    def test_commands_ride_the_hub_socket(self) -> None:
        from pigeon.receiver_denon_telnet import (
            denon_hub_volume_state,
            send_denon_telnet_commands,
        )

        ok, msg = send_denon_telnet_commands("127.0.0.1", ["MUON"], timeout=1.5)
        self.assertTrue(ok, msg)
        self.assertIn("MUON", msg)
        ok, msg = send_denon_telnet_commands("127.0.0.1", ["MV525"], timeout=1.5)
        self.assertTrue(ok, msg)
        st = denon_hub_volume_state("127.0.0.1")
        self.assertEqual(st["mv"], 52.5)
        self.assertEqual(self.avr.connections, 1)

    def test_feedback_is_timestamped_after_write(self) -> None:
        from pigeon.receiver_denon_telnet import denon_hub_send, denon_hub_volume_state

        tx = denon_hub_send("127.0.0.1", "MV60", timeout=1.0)
        self.assertIsNotNone(tx)
        end = time.monotonic() + 1.0
        st: dict = {}
        while time.monotonic() < end:
            st = denon_hub_volume_state("127.0.0.1")
            if st.get("mv") == 60.0:
                break
            time.sleep(0.01)
        self.assertEqual(st.get("mv"), 60.0)
        self.assertGreater(float(st["mv_mono"]), float(tx))

    def test_stale_snapshot_withheld_when_disconnected(self) -> None:
        from pigeon.receiver_denon_telnet import _VOLUME_HUB, query_denon_volume_telnet

        self.assertTrue(query_denon_volume_telnet("127.0.0.1").get("MV"))
        _VOLUME_HUB._connected = ""
        with _VOLUME_HUB._state:
            _VOLUME_HUB._mv_mono -= 60.0
            _VOLUME_HUB._mu_mono -= 60.0
        self.assertEqual(query_denon_volume_telnet("127.0.0.1"), {})

    def test_controller_end_to_end_single_connection(self) -> None:
        from pigeon.receiver_volume import DenonHubTransport

        confirmed: list[str] = []
        c = ReceiverVolumeController(
            DenonHubTransport(),
            on_confirmed=lambda _h, line: confirmed.append(line),
            diag=LatencyDiag(every_s=1e9),
        )
        with patch(
            "pigeon.receiver_denon.send_denon_http_command",
            side_effect=AssertionError("HTTP fallback while hub is up"),
        ):
            for _ in range(10):
                c.submit("127.0.0.1", "volume_up")
                time.sleep(0.01)
            ok, msg, vol = c.drain(4.0)
        self.assertTrue(ok, msg)
        self.assertEqual(vol, "-25.0 dB")
        self.assertEqual(self.avr.level, "55")
        self.assertEqual(self.avr.connections, 1)
        mv_cmds = [x for x in self.avr.received if x.startswith("MV") and x[2:].isdigit()]
        self.assertLessEqual(len(mv_cmds), 3, mv_cmds)
        self.assertEqual(mv_cmds[-1], "MV55")

class ControllerStopTests(unittest.TestCase):
    def test_stop_ends_the_worker_drops_work_and_detaches(self) -> None:
        class Tr:
            def __init__(self) -> None:
                self.observers: list = []

            def add_observer(self, cb): self.observers.append(cb)
            def remove_observer(self, cb): self.observers.remove(cb)
            def state(self, host): return {}
            def send(self, host, command, *, timeout): return None
            def http_send(self, host, command): return False

        tr = Tr()
        c = ReceiverVolumeController(tr)
        t = threading.Thread(target=c.run_forever, daemon=True)
        t.start()
        deadline = time.monotonic() + 2
        while not tr.observers and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(len(tr.observers), 1)
        c.stop()
        t.join(3)
        self.assertFalse(t.is_alive())
        self.assertEqual(tr.observers, [])
        self.assertFalse(c.has_work())



if __name__ == "__main__":
    unittest.main()
