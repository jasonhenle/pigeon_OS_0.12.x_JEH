"""AVR master-volume control for the rotary encoder.

Encoder detents never become a list of queued commands. They fold into one
replaceable intent per receiver:

* With a trustworthy baseline (a live ``MV`` reading from the telnet hub)
  the intent is an absolute target. The worker sends ``MV<nn[5]>`` for the
  *latest* target, at most once per ``SEND_INTERVAL_S``, so a fast spin
  costs a handful of commands and a reversal simply moves the target back.
* With no baseline, detents are counted as net relative steps. The worker
  asks the hub for ``MV?``; if that does not answer quickly it sends a
  bounded batch of ``MVUP`` / ``MVDOWN`` instead of guessing an absolute.

Confirmation only counts an ``MV`` reading that arrived *after* the command
was written and equals what was sent. Late feedback is never a reason to
resend; HEOS player volume is only touched when fresh post-command feedback
proves the AVR ignored ``MV`` (the old ``apply_denon_master_volume``
fallback), and its level is never shown as master volume.

All network work happens on the worker thread (or the caller of
:func:`apply_receiver_volume_once`). :meth:`ReceiverVolumeController.submit`
only updates state and is safe to call from the Tk thread.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from typing import Protocol

# One encoder detent == one Denon ``MVUP`` step == 0.5 dB.
STEP_UNITS = 0.5
MIN_UNITS = 0.0
HARD_MAX_UNITS = 98.0
# A target never runs further than this from the last level the AVR reported,
# so a runaway encoder cannot jump the volume before feedback catches up.
MAX_OFFSET_UNITS = 12.0
# Spacing between absolute ``MV`` writes. Denon's minimum is 50 ms.
SEND_INTERVAL_S = 0.08
# A hub ``MV`` reading this recent (with the socket up) is a usable baseline.
BASELINE_FRESH_S = 3.0
# How long to wait for an ``MV?`` answer before using relative steps.
BASELINE_WAIT_S = 0.45
# How long to wait for the hub to (re)connect before using HTTP AppDirect.
CONNECT_WAIT_S = 0.6
RELATIVE_BATCH_MAX = 8
# No matching ``MV`` this long after the last write → ask ``MV?`` once.
CONFIRM_S = 1.2
# …and this much longer after that → stop waiting and reconcile.
CONFIRM_GRACE_S = 0.8
# After an intent settles, keep lagging pollers from painting older levels.
SETTLE_HOLD_S = 1.0
# Give up on an intent whose commands cannot be written at all.
SEND_GIVE_UP_S = 3.0


def units_to_line(units: float) -> str:
    return f"{float(units) - 80.0:.1f} dB"


def line_to_units(line: str) -> float | None:
    from pigeon.receiver_denon import _volume_db_value

    db = _volume_db_value(line)
    return None if db is None else db + 80.0


def _same(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) < 0.25


class VolumeTransport(Protocol):
    def ensure(self, host: str) -> None: ...
    def state(self, host: str) -> dict[str, object]: ...
    def send(self, host: str, command: str, *, timeout: float) -> float | None: ...
    def http_send(self, host: str, command: str) -> bool: ...
    def heos_adjust(self, host: str, steps: int) -> tuple[bool, str]: ...
    def add_observer(self, cb: Callable[[], None]) -> None: ...


class DenonHubTransport:
    """Production transport: the persistent telnet hub, HTTP AppDirect, HEOS."""

    def ensure(self, host: str) -> None:
        from pigeon.receiver_denon_telnet import denon_hub_host, start_denon_telnet_hub

        # The adapter owns the hub and keeps it on its host: an address change
        # re-binds it, but a hub already on this host is left alone (re-binding
        # would drop a live session).
        if denon_hub_host() != str(host or "").strip():
            start_denon_telnet_hub(host)

    def state(self, host: str) -> dict[str, object]:
        from pigeon.receiver_denon_telnet import denon_hub_volume_state

        return denon_hub_volume_state(host)

    def send(self, host: str, command: str, *, timeout: float) -> float | None:
        from pigeon.receiver_denon_telnet import denon_hub_send

        return denon_hub_send(host, command, timeout=timeout)

    def http_send(self, host: str, command: str) -> bool:
        from pigeon.receiver_denon import send_denon_http_command

        ok, _msg = send_denon_http_command(host, command, timeout=0.8)
        return ok

    def heos_adjust(self, host: str, steps: int) -> tuple[bool, str]:
        from pigeon.receiver_denon import send_heos_volume_control

        return send_heos_volume_control(host, steps=steps, timeout=1.5)

    def add_observer(self, cb: Callable[[], None]) -> None:
        from pigeon.receiver_denon_telnet import denon_hub_add_observer

        denon_hub_add_observer(cb)

    def remove_observer(self, cb: Callable[[], None]) -> None:
        from pigeon.receiver_denon_telnet import denon_hub_remove_observer

        denon_hub_remove_observer(cb)

    def release(self, host: str) -> None:
        """Give the hub back: stops it only while it is still on ``host``."""
        from pigeon.receiver_denon_telnet import release_denon_telnet_hub

        release_denon_telnet_hub(host)


class LatencyDiag:
    """Rate-limited stderr summary of encoder → write → confirm timings."""

    def __init__(self, *, every_s: float = 3.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.every_s = float(every_s)
        self._clock = clock
        self._last_emit = 0.0
        self._detents = 0
        self._writes = 0
        self._tx: list[float] = []
        self._confirm: list[float] = []
        self._e2e: list[float] = []
        self._notes: list[str] = []
        self.lines: list[str] = []  # emitted lines, kept for tests

    def detent(self) -> None:
        self._detents += 1

    def wrote(self, input_to_tx_s: float | None) -> None:
        self._writes += 1
        if input_to_tx_s is not None:
            self._tx.append(input_to_tx_s)

    def confirmed(self, tx_to_confirm_s: float, input_to_confirm_s: float | None) -> None:
        self._confirm.append(tx_to_confirm_s)
        if input_to_confirm_s is not None:
            self._e2e.append(input_to_confirm_s)

    def note(self, text: str) -> None:
        if len(self._notes) < 4:
            self._notes.append(text)

    @staticmethod
    def _fmt(name: str, xs: list[float]) -> str:
        if not xs:
            return f"{name} -"
        avg = sum(xs) / len(xs) * 1000.0
        return f"{name} avg {avg:.0f}ms max {max(xs) * 1000.0:.0f}ms"

    def maybe_emit(self, last_line: str = "") -> None:
        now = self._clock()
        if now - self._last_emit < self.every_s:
            return
        if not (self._detents or self._writes or self._confirm or self._notes):
            return
        self._last_emit = now
        parts = [
            f"detents={self._detents} writes={self._writes}",
            self._fmt("input→tx", self._tx),
            self._fmt("tx→confirm", self._confirm),
            self._fmt("input→confirm", self._e2e),
        ]
        if last_line:
            parts.append(f"last={last_line}")
        parts.extend(self._notes)
        line = "pigeon: receiver_volume: " + "; ".join(parts)
        self.lines.append(line)
        del self.lines[:-20]
        try:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
        except Exception:
            pass
        self._detents = self._writes = 0
        self._tx, self._confirm, self._e2e, self._notes = [], [], [], []


class ReceiverVolumeController:
    def __init__(
        self,
        transport: VolumeTransport,
        *,
        on_confirmed: Callable[[str, str], None] | None = None,
        on_result: Callable[[str, bool, str], None] | None = None,
        on_busy: Callable[[bool], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        diag: LatencyDiag | None = None,
    ) -> None:
        self.transport = transport
        self.on_confirmed = on_confirmed
        self.on_result = on_result
        self.on_busy = on_busy
        self.clock = clock
        self.sleep = sleep
        self.diag = diag or LatencyDiag(clock=clock)
        self._cond = threading.Condition()
        self._observing = False
        self._busy = False
        self._run_token = 0
        self._reset_locked("")
        self.last_result: tuple[bool, str, str] = (True, "", "")

    # ---- state -----------------------------------------------------------

    def _reset_locked(self, host: str) -> None:
        self._host = host
        self._gen = getattr(self, "_gen", 0) + 1
        self._pending_rel = 0       # detents with no baseline yet
        self._target: float | None = None
        self._anchor: float | None = None  # last level the AVR reported
        self._start_level: float | None = None
        self._mutes = 0
        self._wake = False
        self._sent: float | None = None
        self._sent_mono = 0.0
        self._last_tx = 0.0
        self._awaiting = False
        self._query_mono = 0.0      # when we asked MV? for a baseline
        self._confirm_query = False
        self._first_input = 0.0     # oldest unsent detent, for diagnostics
        self._sent_input = 0.0
        self._send_fail_since = 0.0
        self._rel_sent = 0          # relative steps written, awaiting feedback
        self._rel_mono = 0.0
        self._rel_start: float | None = None
        self._hold_line_units: float | None = None
        self._hold_until = 0.0

    def _active_locked(self) -> bool:
        return bool(
            self._pending_rel
            or self._mutes
            or self._wake
            or self._awaiting
            or self._rel_sent
            or (self._target is not None)
        )

    def _notify(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def reset(self, host: str = "") -> None:
        """Drop all pending work (receiver selection changed)."""
        with self._cond:
            self._reset_locked(str(host or "").strip())
            self._cond.notify_all()

    def stop(self) -> None:
        """Drop pending work, end the worker thread and detach from the transport."""
        with self._cond:
            self._run_token += 1
            self._reset_locked("")
            observing, self._observing = self._observing, False
            self._cond.notify_all()
        if observing:
            remove = getattr(self.transport, "remove_observer", None)
            if remove is not None:
                try:
                    remove(self._notify)
                except Exception:
                    pass

    def submit(self, host: str, action: str, *, wake: bool = False) -> bool:
        """Fold one encoder action into the pending intent. Never blocks on I/O."""
        h = str(host or "").strip()
        act = str(action or "").strip().lower()
        if not h or act not in ("volume_up", "volume_down", "mute_toggle"):
            return False
        now = self.clock()
        with self._cond:
            if h != self._host:
                self._reset_locked(h)
            if wake:
                self._wake = True
            if act == "mute_toggle":
                self._mutes += 1
            else:
                step = 1 if act == "volume_up" else -1
                self.diag.detent()
                if not self._first_input:
                    self._first_input = now
                if self._target is None:
                    self._pending_rel += step
                else:
                    self._target = self._clamp_locked(self._target + step * STEP_UNITS)
            self._cond.notify_all()
        return True

    def _max_units_locked(self, st: dict[str, object] | None = None) -> float:
        mx = (st or {}).get("max") if st else None
        if isinstance(mx, (int, float)) and 0 < float(mx) <= HARD_MAX_UNITS:
            return float(mx)
        return getattr(self, "_max_units", HARD_MAX_UNITS)

    def _clamp_locked(self, units: float) -> float:
        lo, hi = MIN_UNITS, self._max_units_locked()
        if self._anchor is not None:
            lo = max(lo, self._anchor - MAX_OFFSET_UNITS)
            hi = min(hi, self._anchor + MAX_OFFSET_UNITS)
        u = round(float(units) * 2.0) / 2.0
        return max(lo, min(hi, u))

    def readout_superseded(self, line: str) -> bool:
        """True when ``line`` is an older level than the one Pigeon is driving to.

        Pollers (telnet listener, AppCommand) call this before painting so an
        echo of an intermediate target, or a lagging HTTP read, cannot drag
        the readout backwards mid-turn.
        """
        u = None
        try:
            u = line_to_units(line)
        except Exception:
            u = None
        if u is None:
            return False  # "mute" and blanks are never superseded
        now = self.clock()
        with self._cond:
            if self._active_locked():
                want = self._target if self._target is not None else self._sent
                # Relative mode has no known level to protect.
                return want is not None and not _same(u, want)
            if self._hold_line_units is not None and now < self._hold_until:
                return not _same(u, self._hold_line_units)
        return False

    # ---- worker ------------------------------------------------------------

    def _observe(self) -> None:
        if not self._observing:
            try:
                self.transport.add_observer(self._notify)
            except Exception:
                pass
            self._observing = True

    def _set_busy(self, busy: bool) -> None:
        if busy == self._busy:
            return
        self._busy = busy
        cb = self.on_busy
        if cb is not None:
            try:
                cb(busy)
            except Exception:
                pass

    def _publish(self, host: str, units: float, msg: str, *, ok: bool = True) -> None:
        line = units_to_line(units)
        self.last_result = (ok, msg, line)
        if ok and self.on_confirmed is not None:
            try:
                self.on_confirmed(host, line)
            except Exception:
                pass
        if self.on_result is not None:
            try:
                self.on_result(host, ok, msg)
            except Exception:
                pass

    def _fail(self, host: str, msg: str) -> None:
        self.last_result = (False, msg, "")
        if self.on_result is not None:
            try:
                self.on_result(host, False, msg)
            except Exception:
                pass

    def has_work(self) -> bool:
        with self._cond:
            return self._active_locked()

    def run_forever(self) -> None:
        token = self._run_token
        self._observe()
        while token == self._run_token:
            with self._cond:
                while not self._active_locked():
                    self._set_busy(False)
                    if token != self._run_token:
                        return
                    self._cond.wait(timeout=1.0)
                    self.diag.maybe_emit()
            if token != self._run_token:
                break
            self._set_busy(True)
            try:
                delay = self.step()
            except Exception as exc:  # never let the worker die
                self._fail(self._host, f"receiver volume worker: {exc}")
                delay = 0.2
            if delay > 0:
                with self._cond:
                    self._cond.wait(timeout=delay)
            self.diag.maybe_emit()

    def drain(self, timeout: float) -> tuple[bool, str, str]:
        """Run :meth:`step` on the calling thread until idle or ``timeout``."""
        self._observe()
        deadline = self.clock() + float(timeout)
        while self.has_work() and self.clock() < deadline:
            delay = self.step()
            if delay > 0:
                with self._cond:
                    self._cond.wait(timeout=min(delay, max(0.0, deadline - self.clock())))
        with self._cond:
            if self._active_locked():
                self._reset_locked(self._host)
        return self.last_result

    def _send(self, host: str, cmd: str, st: dict[str, object]) -> float | None:
        """Write via the hub when it owns the socket, else HTTP AppDirect."""
        if st:
            tx = self.transport.send(host, cmd, timeout=CONNECT_WAIT_S)
            if tx is not None:
                return tx
        if self.transport.http_send(host, cmd):
            return self.clock()
        return None

    def step(self) -> float:
        """One round of work. Returns how long to wait before the next round."""
        now = self.clock()
        with self._cond:
            host, gen = self._host, self._gen
            if not host or not self._active_locked():
                return 0.0
        self.transport.ensure(host)
        st = self.transport.state(host) or {}
        connected = bool(st.get("connected"))
        mv = st.get("mv")
        mv = float(mv) if isinstance(mv, (int, float)) else None
        mv_mono = float(st.get("mv_mono") or 0.0)
        with self._cond:
            if gen != self._gen:
                return 0.0
            self._max_units = self._max_units_locked(st)
            if mv is not None and mv_mono and (
                mv_mono > max(self._sent_mono, self._rel_mono) or not self._awaiting
            ):
                self._anchor = mv
            wake = self._wake
            self._wake = False

        # 1. Wake from standby (once per pending episode).
        if wake and str(st.get("pw") or "") != "ON":
            if self._send(host, "PWON", st) is not None:
                self.sleep(0.7)  # let the AVR come up before volume commands
                self.diag.note("sent PWON")

        # 2. Mute toggles (parity; MU state comes from the hub).
        with self._cond:
            mutes = self._mutes
        if mutes:
            delay = self._do_mute(host, gen, mutes, st, now)
            if delay is not None:
                return delay

        # 3. Relative steps already written: wait for feedback, never resend.
        with self._cond:
            if self._rel_sent:
                if mv is not None and mv_mono > self._rel_mono:
                    self._publish(host, mv, f"Denon: relative {self._rel_sent:+d} steps → MV")
                    self.diag.confirmed(mv_mono - self._rel_mono, None)
                    self._rel_sent = 0
                    self._anchor = mv
                elif now - self._rel_mono > CONFIRM_S + CONFIRM_GRACE_S:
                    self.diag.note(f"relative {self._rel_sent:+d} unconfirmed")
                    self.last_result = (True, f"Denon: relative {self._rel_sent:+d} sent", "")
                    self._rel_sent = 0
                else:
                    return 0.05

        # 4. Turn relative detents into an absolute target, or send them as-is.
        with self._cond:
            pending = self._pending_rel
            has_target = self._target is not None
        if pending and not has_target:
            fresh = (
                mv is not None
                and connected
                and mv_mono > 0
                and (now - mv_mono) <= BASELINE_FRESH_S
            )
            if fresh:
                with self._cond:
                    if gen != self._gen:
                        return 0.0
                    self._anchor = mv
                    self._start_level = mv
                    self._target = self._clamp_locked(mv + self._pending_rel * STEP_UNITS)
                    self._pending_rel = 0
                    self._query_mono = 0.0
            elif connected and not self._query_mono:
                with self._cond:
                    self._query_mono = now
                self.transport.send(host, "MV?", timeout=CONNECT_WAIT_S)
                return 0.05
            elif connected and now - self._query_mono < BASELINE_WAIT_S:
                return 0.05
            else:
                return self._send_relative(host, gen, st, now)

        # 5. Absolute target.
        with self._cond:
            if gen != self._gen:
                return 0.0
            target, sent = self._target, self._sent
            if target is not None and sent is None and _same(target, self._anchor) and not self._awaiting:
                # Net zero before anything went out (e.g. up then down).
                self._settle_locked(now, self._anchor)
                return 0.0
        if target is not None and not _same(target, sent):
            wait = SEND_INTERVAL_S - (now - self._last_tx)
            if wait > 0:
                return wait
            cmd = "MV" + _units_to_mv(target)
            tx = self._send(host, cmd, st)
            with self._cond:
                if gen != self._gen:
                    return 0.0
                if tx is None:
                    if not self._send_fail_since:
                        self._send_fail_since = now
                    if now - self._send_fail_since > SEND_GIVE_UP_S:
                        self._reset_locked(host)
                        self._fail(host, f"Denon: {cmd} not sent (no telnet / HTTP)")
                        return 0.0
                    return 0.2
                self._send_fail_since = 0.0
                self._sent = target
                self._sent_mono = tx
                self._last_tx = tx
                self._awaiting = True
                self._confirm_query = False
                self._sent_input = self._first_input
                self.diag.wrote((tx - self._first_input) if self._first_input else None)
                self._first_input = 0.0
            return SEND_INTERVAL_S

        # 6. Confirmation of the latest write.
        with self._cond:
            if not self._awaiting or gen != self._gen:
                return 0.0
            sent, sent_mono = self._sent, self._sent_mono
        if mv is not None and mv_mono > sent_mono and _same(mv, sent):
            with self._cond:
                if gen != self._gen:
                    return 0.0
                self.diag.confirmed(
                    mv_mono - sent_mono,
                    (mv_mono - self._sent_input) if self._sent_input else None,
                )
                self._settle_locked(now, mv)
            self._publish(host, mv, f"Denon: MV{_units_to_mv(mv)} confirmed")
            return 0.0
        age = now - sent_mono
        if age < CONFIRM_S:
            return min(0.1, CONFIRM_S - age)
        if not self._confirm_query:
            # A status query, not a resend: the adjustment is never repeated.
            self._confirm_query = True
            self.transport.send(host, "MV?", timeout=0.3)
            return 0.1
        if age < CONFIRM_S + CONFIRM_GRACE_S:
            return 0.1
        fresh = mv if (mv is not None and mv_mono > sent_mono) else None
        with self._cond:
            if gen != self._gen:
                return 0.0
            start = self._start_level
            self._settle_locked(now, fresh)
        if fresh is None:
            self.diag.note(f"MV{_units_to_mv(sent)} unconfirmed (no fresh MV)")
            self.last_result = (True, f"Denon: MV{_units_to_mv(sent)} sent, no fresh feedback", "")
            return 0.0
        if start is not None and _same(fresh, start) and not _same(sent, start):
            # Fresh post-command MV still shows the pre-command level: the AVR
            # ignored MV. Move the HEOS player instead; keep showing AVR master.
            steps = int(round((float(sent) - start) / STEP_UNITS))
            ok_h, msg_h = self.transport.heos_adjust(host, steps)
            self.diag.note(f"HEOS fallback {steps:+d}: {'ok' if ok_h else 'failed'}")
            self._publish(host, fresh, msg_h, ok=ok_h)
            return 0.0
        # Receiver clamped (volume limit) or someone used the remote: adopt it.
        self._publish(host, fresh, f"Denon: MV{_units_to_mv(sent)} → receiver reports {units_to_line(fresh)}")
        return 0.0

    def _settle_locked(self, now: float, level: float | None) -> None:
        self._target = None
        self._sent = None
        self._awaiting = False
        self._confirm_query = False
        self._start_level = None
        self._sent_input = 0.0
        if level is not None:
            self._anchor = level
            self._hold_line_units = level
            self._hold_until = now + SETTLE_HOLD_S

    def _send_relative(self, host: str, gen: int, st: dict[str, object], now: float) -> float:
        with self._cond:
            n = max(-RELATIVE_BATCH_MAX, min(RELATIVE_BATCH_MAX, self._pending_rel))
        cmd = "MVUP" if n > 0 else "MVDOWN"
        sent = 0
        last_tx = 0.0
        for _ in range(abs(n)):
            tx = self._send(host, cmd, st)
            if tx is None:
                break
            sent += 1
            last_tx = tx
        with self._cond:
            if gen != self._gen:
                return 0.0
            self._query_mono = 0.0
            if not sent:
                if not self._send_fail_since:
                    self._send_fail_since = now
                if now - self._send_fail_since > SEND_GIVE_UP_S:
                    self._reset_locked(host)
                    self._fail(host, f"Denon: {cmd} not sent (no telnet / HTTP)")
                    return 0.0
                return 0.2
            self._send_fail_since = 0.0
            signed = sent if n > 0 else -sent
            self._pending_rel -= signed
            self._rel_sent += signed
            self._rel_mono = last_tx
            self.diag.wrote((last_tx - self._first_input) if self._first_input else None)
            self.diag.note(f"no baseline: relative {signed:+d}")
            self._first_input = 0.0
        return 0.05

    def _do_mute(
        self, host: str, gen: int, mutes: int, st: dict[str, object], now: float
    ) -> float | None:
        if mutes % 2 == 0:
            with self._cond:
                if gen == self._gen:
                    self._mutes -= mutes
            return None
        mu = st.get("mu")
        if mu is None and st.get("connected"):
            with self._cond:
                asked = self._query_mono
                if not asked:
                    self._query_mono = now
            if not asked:
                self.transport.send(host, "MU?", timeout=0.3)
                return 0.05
            if now - asked < BASELINE_WAIT_S:
                return 0.05
        cmd = "MUOFF" if mu is True else "MUON"
        tx = self._send(host, cmd, st)
        with self._cond:
            if gen != self._gen:
                return 0.0
            self._query_mono = 0.0
            self._mutes -= mutes
        if tx is None:
            self._fail(host, f"Denon: {cmd} not sent")
        else:
            self.last_result = (True, f"Denon: {cmd}", "mute" if cmd == "MUON" else "")
            if self.on_result is not None:
                try:
                    self.on_result(host, True, f"Denon: {cmd}")
                except Exception:
                    pass
        return None


def _units_to_mv(units: float) -> str:
    from pigeon.receiver_denon_telnet import denon_units_to_mv

    return denon_units_to_mv(units)


_CONTROLLER: ReceiverVolumeController | None = None
_CONTROLLER_LOCK = threading.Lock()


def get_receiver_volume_controller() -> ReceiverVolumeController:
    global _CONTROLLER
    with _CONTROLLER_LOCK:
        if _CONTROLLER is None:
            _CONTROLLER = ReceiverVolumeController(DenonHubTransport())
        return _CONTROLLER


def receiver_volume_readout_superseded(line: str) -> bool:
    c = _CONTROLLER
    return bool(c is not None and c.readout_superseded(line))


def reset_receiver_volume(host: str = "") -> None:
    c = _CONTROLLER
    if c is not None:
        c.reset(host)


def apply_receiver_volume_once(
    host: str,
    *,
    steps: int = 0,
    mute_toggles: int = 0,
    timeout: float = 3.5,
    transport: VolumeTransport | None = None,
) -> tuple[bool, str, str]:
    """Synchronous one-shot adjustment (``(ok, msg, confirmed_line)``)."""
    c = ReceiverVolumeController(transport or DenonHubTransport())
    for _ in range(int(mute_toggles) % 2):
        c.submit(host, "mute_toggle")
    n = max(-24, min(24, int(steps)))
    for _ in range(abs(n)):
        c.submit(host, "volume_up" if n > 0 else "volume_down")
    if not c.has_work():
        return True, "No receiver volume change.", ""
    return c.drain(timeout)
