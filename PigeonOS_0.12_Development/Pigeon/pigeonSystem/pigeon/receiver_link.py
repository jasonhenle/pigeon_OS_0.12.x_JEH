"""Pigeon's one connection to its AV receiver — through the ``Receiver`` interface only.

Pigeon code asks this module for the receiver bound to the saved AV address and
never imports a brand module. Listeners registered here survive host changes
(DHCP, re-pairing): they are re-attached to each new adapter.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from pigeon.receiver import create_receiver
from pigeon.receiver.base import (
    Receiver,
    ReceiverState,
    ResultListener,
    StateListener,
    VolumeListener,
)

# Pigeon refreshes receiver state about this often (was RECEIVER_POLL_MS).
DEFAULT_POLL_S = 0.75


class ReceiverLink:
    def __init__(self, factory: Callable[..., Receiver] = create_receiver, *, poll_s: float = DEFAULT_POLL_S) -> None:
        self._factory = factory
        self._poll_s = float(poll_s)
        self._lock = threading.RLock()
        self._rx: Receiver | None = None
        self._host = ""
        self._brand = ""
        self._bound_mono = 0.0
        self._state_cbs: list[StateListener] = []
        self._volume_cbs: list[VolumeListener] = []
        self._result_cbs: list[ResultListener] = []

    # ---- listeners (register once at boot) ----------------------------------

    def _guard(self, rx: Receiver, cb: Callable) -> Callable:
        """``cb`` only while ``rx`` is the bound receiver.

        An adapter that was replaced or released can still have a poll, a
        confirmation or a command result in flight; none of it may reach
        listeners that now speak for a different receiver (or for none).
        """

        def call(*args):
            if self._rx is rx:
                return cb(*args)

        return call

    def on_state(self, cb: StateListener) -> None:
        with self._lock:
            self._state_cbs.append(cb)
            if self._rx is not None:
                self._rx.add_state_listener(self._guard(self._rx, cb))

    def on_volume_confirmed(self, cb: VolumeListener) -> None:
        with self._lock:
            self._volume_cbs.append(cb)
            if self._rx is not None:
                self._rx.add_volume_confirmed_listener(self._guard(self._rx, cb))

    def on_command_result(self, cb: ResultListener) -> None:
        with self._lock:
            self._result_cbs.append(cb)
            if self._rx is not None:
                self._rx.add_command_result_listener(self._guard(self._rx, cb))

    # ---- binding -------------------------------------------------------------

    @property
    def receiver(self) -> Receiver | None:
        return self._rx

    @property
    def host(self) -> str:
        return self._host

    def bind(self, host: str, brand: str = "denon") -> Receiver | None:
        """Make sure the receiver at ``host`` is connected; cheap when nothing changed."""
        host = str(host or "").strip()
        brand = str(brand or "denon").strip().lower()
        if not host:
            return self._rx
        with self._lock:
            if self._rx is not None and host == self._host and brand == self._brand:
                return self._rx
            old, self._rx = self._rx, None
            try:
                rx = self._factory(brand, host, full_poll_s=self._poll_s)
            except Exception:
                self._host = self._brand = ""
                if old is not None:
                    old.disconnect()
                raise
            for cb in self._state_cbs:
                rx.add_state_listener(self._guard(rx, cb))
            for cb in self._volume_cbs:
                rx.add_volume_confirmed_listener(self._guard(rx, cb))
            for cb in self._result_cbs:
                rx.add_command_result_listener(self._guard(rx, cb))
            self._rx, self._host, self._brand = rx, host, brand
            self._bound_mono = time.monotonic()
        if old is not None:
            old.disconnect()
        threading.Thread(target=self._connect, args=(rx,), name="receiver-connect", daemon=True).start()
        return rx

    def _connect(self, rx: Receiver) -> None:
        """Connect ``rx`` unless it was already replaced; undo it if that happens meanwhile."""
        if self._rx is not rx:
            return
        try:
            rx.connect()
        finally:
            if self._rx is not rx:
                rx.disconnect()

    def seconds_since_bind(self) -> float:
        return time.monotonic() - self._bound_mono if self._rx is not None else 0.0

    def release(self) -> None:
        """Disconnect and forget the receiver (removed, or this location has none)."""
        with self._lock:
            old, self._rx, self._host, self._brand = self._rx, None, "", ""
        if old is not None:
            old.disconnect()

    # ---- conveniences ----------------------------------------------------------

    def state(self) -> ReceiverState:
        rx = self._rx
        return rx.cached_state() if rx is not None else ReceiverState()

    def readout_superseded(self, line: str) -> bool:
        rx = self._rx
        return bool(rx is not None and rx.volume_readout_superseded(line))


_LINK: ReceiverLink | None = None
_LINK_LOCK = threading.Lock()


def get_receiver_link() -> ReceiverLink:
    global _LINK
    with _LINK_LOCK:
        if _LINK is None:
            _LINK = ReceiverLink()
        return _LINK
