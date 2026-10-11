"""In-memory receiver for development and tests. No sockets, no Denon packets."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from pigeon.receiver.base import (
    EVT_COMMAND,
    EVT_CONNECTION,
    EVT_EXTERNAL,
    EVT_RESPONSE,
    EventSink,
    ReceiverEvent,
    ReceiverState,
    StateListener,
)

STEP_DB = 0.5
MIN_DB = -80.0
MAX_DB = 18.0
DEFAULT_INPUTS = ("Apple TV", "Blu-ray", "Game", "TV Audio", "Tuner")


class FakeReceiver:
    """Simulated AVR.

    ``latency_s`` delays when *our* commands take effect, so callers can be
    tested against slow feedback. Delayed effects are applied by :meth:`pump`
    (deterministic, for tests with an injected ``clock``) or by a background
    thread after :meth:`start_auto_pump` (harness / diagnostic tool).
    ``simulate_*`` methods model changes made by something else (a remote).
    """

    brand = "fake"

    def __init__(
        self,
        *,
        latency_s: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        inputs: tuple[str, ...] = DEFAULT_INPUTS,
        initial: ReceiverState | None = None,
    ) -> None:
        self.latency_s = float(latency_s)
        self._clock = clock
        self._inputs = list(inputs)
        self._lock = threading.RLock()
        self._link_up = True  # "the receiver is reachable on the network"
        self._session = False  # connect() called
        self._truth = initial or ReceiverState(
            connected=True,
            powered_on=True,
            volume_db=-40.0,
            muted=False,
            input_label=self._inputs[0],
            audio_format="dolby digital",
            sound_mode="dolby surround",
        )
        self._seen = ReceiverState()  # what Pigeon last observed
        self._pending: list[tuple[float, Callable[[], None], str]] = []
        self._listeners: list[StateListener] = []
        self._sink: EventSink | None = None
        self._volume_confirmed: list = []
        self._command_results: list = []
        self._pump_thread: threading.Thread | None = None
        self._pump_stop = threading.Event()

    # ---- Receiver interface ---------------------------------------------

    @property
    def connected(self) -> bool:
        return self._session and self._link_up

    def connect(self) -> None:
        with self._lock:
            self._session = True
            ok = self._link_up
        self._emit(EVT_CONNECTION, "connected" if ok else "connection failed: receiver unreachable")
        self._refresh_seen()

    def disconnect(self) -> None:
        with self._lock:
            self._session = False
            self._pending.clear()  # in-flight commands are lost with the session
        self._emit(EVT_CONNECTION, "disconnected")
        self._refresh_seen()

    def get_state(self) -> ReceiverState:
        self.pump()
        return self._refresh_seen()

    def cached_state(self) -> ReceiverState:
        with self._lock:
            return self._seen

    def set_power(self, on: bool) -> bool:
        return self._command(f"power {'on' if on else 'standby'}", lambda t: t.with_(powered_on=bool(on)))

    def step_volume(self, steps: int, *, wake: bool = False) -> bool:
        n = int(steps)
        if not n:
            return True

        def apply(t: ReceiverState) -> ReceiverState:
            if t.powered_on is False and not wake:
                return t
            vol = t.volume_db if t.volume_db is not None else MIN_DB
            vol = max(MIN_DB, min(MAX_DB, vol + n * STEP_DB))
            return t.with_(volume_db=vol, powered_on=True if wake else t.powered_on)

        return self._command(f"volume {n:+d} step(s)", apply)

    def toggle_mute(self, *, wake: bool = False) -> bool:
        def apply(t: ReceiverState) -> ReceiverState:
            if t.powered_on is False and not wake:
                return t
            return t.with_(muted=not bool(t.muted), powered_on=True if wake else t.powered_on)

        return self._command("mute toggle", apply)

    def add_state_listener(self, cb: StateListener) -> None:
        self._listeners.append(cb)

    def add_volume_confirmed_listener(self, cb) -> None:
        self._volume_confirmed.append(cb)

    def add_command_result_listener(self, cb) -> None:
        self._command_results.append(cb)

    def volume_readout_superseded(self, line: str) -> bool:
        return False

    def set_event_sink(self, sink: EventSink | None) -> None:
        self._sink = sink

    # ---- InputSelectable ---------------------------------------------------

    def available_inputs(self) -> list[str]:
        return list(self._inputs)

    def set_input(self, label: str) -> bool:
        if label not in self._inputs:
            self._emit(EVT_RESPONSE, f"unknown input {label!r}")
            return False
        return self._command(f"input {label}", lambda t: t.with_(input_label=label))

    # ---- simulation controls (not part of Receiver) ----------------------

    def simulate_volume(self, db: float) -> None:
        self._external(f"volume → {db:.1f} dB", lambda t: t.with_(volume_db=float(db)))

    def simulate_mute(self, muted: bool) -> None:
        self._external(f"mute → {muted}", lambda t: t.with_(muted=bool(muted)))

    def simulate_power(self, on: bool) -> None:
        self._external(f"power → {'on' if on else 'standby'}", lambda t: t.with_(powered_on=bool(on)))

    def simulate_input(self, label: str) -> None:
        self._external(f"input → {label}", lambda t: t.with_(input_label=label))

    def simulate_link(self, up: bool) -> None:
        """Network drop / return. While down, nothing reaches the receiver."""
        with self._lock:
            self._link_up = bool(up)
            if not up:
                self._pending.clear()  # in-flight commands never arrive
        self._emit(EVT_CONNECTION, "link up" if up else "link down")
        self._refresh_seen()

    def truth(self) -> ReceiverState:
        """The receiver's real state (what a front-panel display would show)."""
        with self._lock:
            return self._truth.with_(connected=self.connected)

    # ---- time ----------------------------------------------------------------

    def pump(self) -> int:
        """Apply delayed effects whose time has come. Returns how many ran."""
        now = self._clock()
        with self._lock:
            due = [p for p in self._pending if p[0] <= now]
            self._pending = [p for p in self._pending if p[0] > now]
        for _t, fn, _d in sorted(due, key=lambda p: p[0]):
            fn()
        if due:
            self._refresh_seen()
        return len(due)

    def start_auto_pump(self, interval_s: float = 0.02) -> None:
        if self._pump_thread is not None:
            return
        self._pump_stop.clear()

        def run() -> None:
            while not self._pump_stop.wait(interval_s):
                self.pump()

        self._pump_thread = threading.Thread(target=run, name="fake-receiver-pump", daemon=True)
        self._pump_thread.start()

    def stop_auto_pump(self) -> None:
        self._pump_stop.set()
        t, self._pump_thread = self._pump_thread, None
        if t is not None:
            t.join(timeout=1.0)

    # ---- internals ---------------------------------------------------------

    def _command(self, desc: str, apply: Callable[[ReceiverState], ReceiverState]) -> bool:
        if not self.connected:
            self._emit(EVT_CONNECTION, f"command not sent (not connected): {desc}")
            return False
        self._emit(EVT_COMMAND, desc)

        def run() -> None:
            with self._lock:
                before = self._truth
                self._truth = apply(self._truth)
                after = self._truth
            self._emit(EVT_RESPONSE, f"{desc} applied")
            for cb in list(self._command_results):
                cb(True, f"{desc} applied")
            if after.volume_db != before.volume_db:
                for cb in list(self._volume_confirmed):
                    cb(after.with_(muted=False).volume_line)

        if self.latency_s <= 0:
            run()
            self._refresh_seen()
        else:
            with self._lock:
                self._pending.append((self._clock() + self.latency_s, run, desc))
        return True

    def _external(self, desc: str, apply: Callable[[ReceiverState], ReceiverState]) -> None:
        with self._lock:
            self._truth = apply(self._truth)
        self._emit(EVT_EXTERNAL, desc)
        self._refresh_seen()

    def _refresh_seen(self) -> ReceiverState:
        """Recompute what Pigeon sees and notify listeners on change."""
        with self._lock:
            if self.connected:
                new = self._truth.with_(connected=True)
            else:
                new = ReceiverState(connected=False)
            old, self._seen = self._seen, new
            listeners = list(self._listeners)
        if new != old:
            for cb in listeners:
                try:
                    cb(old, new)
                except Exception:
                    pass
        return new

    def _emit(self, kind: str, text: str) -> None:
        sink = self._sink
        if sink is not None:
            try:
                sink(ReceiverEvent(kind, text))
            except Exception:
                pass
