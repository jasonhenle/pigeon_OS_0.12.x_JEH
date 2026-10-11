"""Receiver diagnostic session: drives any ``Receiver`` adapter and keeps a log.

UI-free so it can be tested; ``receiver_diag.py`` is the Tk front end.
"""

from __future__ import annotations

import datetime as _dt
import platform
import sys
import threading
import time

from pigeon.receiver import create_receiver
from pigeon.receiver.base import (
    EVT_CONNECTION,
    EVT_ERROR,
    InputSelectable,
    Receiver,
    ReceiverEvent,
    ReceiverState,
)

KIND_LABEL = {
    "command": "SENT",
    "response": "RESP",
    "external": "EXTERNAL",
    "timeout": "TIMEOUT",
    "connection": "CONN",
    "error": "ERROR",
}


def format_entry(ev: ReceiverEvent, prev_ts: float | None) -> str:
    t = _dt.datetime.fromtimestamp(ev.ts).strftime("%H:%M:%S.%f")[:-3]
    delta = "" if prev_ts is None else f" (+{(ev.ts - prev_ts) * 1000:.0f}ms)"
    return f"{t}  {KIND_LABEL.get(ev.kind, ev.kind.upper()):<8} {ev.text}{delta}"


class DiagSession:
    def __init__(self, brand: str, host: str = "", *, receiver: Receiver | None = None) -> None:
        self.brand = brand
        self.host = host
        self.receiver: Receiver = receiver or create_receiver(brand, host)
        self.events: list[ReceiverEvent] = []
        self.state: ReceiverState = self.receiver.cached_state()
        self._lock = threading.Lock()
        self._on_event = None
        self.receiver.set_event_sink(self._sink)
        self.receiver.add_state_listener(self._state_changed)

    # ---- wiring ------------------------------------------------------------

    def set_ui_callback(self, cb) -> None:
        """``cb()`` is called (from any thread) whenever log or state changed."""
        self._on_event = cb

    def _sink(self, ev: ReceiverEvent) -> None:
        with self._lock:
            self.events.append(ev)
        self._poke()

    def _state_changed(self, _old: ReceiverState, new: ReceiverState) -> None:
        self.state = new
        self._poke()

    def _poke(self) -> None:
        cb = self._on_event
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _guard(self, label: str, fn):
        try:
            return fn()
        except Exception as exc:  # adapter bug / protocol error must not kill the tool
            self._sink(ReceiverEvent(EVT_ERROR, f"{label} raised {type(exc).__name__}: {exc}"))
            return None

    # ---- actions -------------------------------------------------------------

    def connect(self) -> None:
        self._guard("connect", self.receiver.connect)
        self.refresh()

    def disconnect(self) -> None:
        self._guard("disconnect", self.receiver.disconnect)
        self.state = self.receiver.cached_state()
        self._poke()

    def refresh(self) -> ReceiverState:
        st = self._guard("get_state", self.receiver.get_state)
        if st is not None:
            self.state = st
        self._poke()
        return self.state

    def power(self, on: bool) -> bool | None:
        return self._guard("set_power", lambda: self.receiver.set_power(on))

    def volume(self, steps: int) -> bool | None:
        return self._guard("step_volume", lambda: self.receiver.step_volume(steps))

    def mute(self) -> bool | None:
        return self._guard("toggle_mute", self.receiver.toggle_mute)

    @property
    def supports_input(self) -> bool:
        return isinstance(self.receiver, InputSelectable)

    def inputs(self) -> list[str]:
        if not self.supports_input:
            return []
        return self._guard("available_inputs", self.receiver.available_inputs) or []

    def set_input(self, label: str) -> bool | None:
        if not self.supports_input:
            self._sink(ReceiverEvent(EVT_CONNECTION, "input selection not supported by this adapter"))
            return False
        return self._guard("set_input", lambda: self.receiver.set_input(label))

    # ---- log -------------------------------------------------------------------

    def log_lines(self) -> list[str]:
        with self._lock:
            evs = list(self.events)
        out, prev = [], None
        for ev in evs:
            out.append(format_entry(ev, prev))
            prev = ev.ts
        return out

    def export_text(self) -> str:
        head = [
            "# Pigeon receiver diagnostic log",
            f"# started/exported: {_dt.datetime.now().isoformat(timespec='seconds')}",
            f"# adapter: {self.brand}  host: {self.host or '-'}",
            f"# host machine: {platform.platform()}  python {sys.version.split()[0]}",
            f"# last state: {self.state}",
            "# columns: time  kind  text  (+ms since previous entry)",
            "",
        ]
        return "\n".join(head + self.log_lines()) + "\n"

    def save(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.export_text())
        return path

    def default_filename(self) -> str:
        return f"receiver_diag_{self.brand}_{time.strftime('%Y%m%d_%H%M%S')}.log"
