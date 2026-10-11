"""Generic receiver interface: what Pigeon needs from an AVR, in receiver terms.

No brand protocol vocabulary (MV/MU/PW/SI, AppCommand, telnet strings, HEOS)
appears here; that stays inside the adapters.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol, runtime_checkable

# ReceiverEvent.kind values (used by the diagnostic log).
EVT_COMMAND = "command"  # we sent something
EVT_RESPONSE = "response"  # receiver answered / state updated after our command
EVT_EXTERNAL = "external"  # unsolicited change (remote, front panel, app)
EVT_TIMEOUT = "timeout"
EVT_CONNECTION = "connection"  # connect / disconnect / connection failure
EVT_ERROR = "error"  # parse or protocol error
EVENT_KINDS = (EVT_COMMAND, EVT_RESPONSE, EVT_EXTERNAL, EVT_TIMEOUT, EVT_CONNECTION, EVT_ERROR)


@dataclass(frozen=True)
class ReceiverState:
    """Snapshot of the receiver as Pigeon sees it. ``None`` means unknown."""

    connected: bool = False
    powered_on: bool | None = None  # False == standby
    volume_db: float | None = None
    muted: bool | None = None
    input_label: str = ""
    audio_format: str = ""  # incoming signal format (Now Playing)
    sound_mode: str = ""  # surround / playback mode (Now Playing)

    @property
    def volume_line(self) -> str:
        """Display line in the shape Pigeon's widgets already consume."""
        if self.muted:
            return "mute"
        return "" if self.volume_db is None else f"{self.volume_db:.1f} dB"

    def diff(self, other: ReceiverState) -> dict[str, tuple[object, object]]:
        """Fields that differ, as ``{name: (self_value, other_value)}``."""
        out: dict[str, tuple[object, object]] = {}
        for name in self.__dataclass_fields__:
            a, b = getattr(self, name), getattr(other, name)
            if a != b:
                out[name] = (a, b)
        return out

    def with_(self, **kw: object) -> ReceiverState:
        return replace(self, **kw)


@dataclass(frozen=True)
class DiscoveredReceiver:
    """One network receiver found by a brand's discoverer."""

    brand: str
    host: str
    name: str = ""
    id: str = ""

    @property
    def label(self) -> str:
        return f"{self.name or 'Receiver'} — {self.host}  [{self.brand}]"


@dataclass(frozen=True)
class ReceiverEvent:
    kind: str
    text: str
    ts: float = field(default_factory=time.time)  # wall clock, for logs


StateListener = Callable[[ReceiverState, ReceiverState], None]  # (old, new)
EventSink = Callable[[ReceiverEvent], None]
VolumeListener = Callable[[str], None]  # settled volume display line, e.g. "-32.5 dB"
ResultListener = Callable[[bool, str], None]  # (ok, message) for each command attempt


@runtime_checkable
class Receiver(Protocol):
    """What Pigeon asks of any receiver adapter. Methods never raise for I/O failures."""

    brand: str

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    @property
    def connected(self) -> bool: ...

    def get_state(self) -> ReceiverState:
        """Fresh state (may block briefly on I/O). Disconnected → ``connected=False``."""
        ...

    def cached_state(self) -> ReceiverState:
        """Last known state; never does I/O."""
        ...

    def set_power(self, on: bool) -> bool: ...

    def step_volume(self, steps: int, *, wake: bool = False) -> bool:
        """Encoder detents (+up / -down). Adapters coalesce; ``wake`` powers on first."""
        ...

    def toggle_mute(self, *, wake: bool = False) -> bool: ...

    def add_state_listener(self, cb: StateListener) -> None:
        """``cb(old, new)`` when state changes for any reason, including external."""
        ...

    def add_volume_confirmed_listener(self, cb: VolumeListener) -> None:
        """``cb(line)`` when a knob/step command has settled at a confirmed level."""
        ...

    def add_command_result_listener(self, cb: ResultListener) -> None:
        """``cb(ok, message)`` after each volume/mute command attempt."""
        ...

    def volume_readout_superseded(self, line: str) -> bool:
        """True while commands are driving to a level ``line`` has not reached, so
        pollers must not paint ``line`` (it would drag the readout backwards mid-turn)."""
        ...

    def set_event_sink(self, sink: EventSink | None) -> None:
        """Optional diagnostic stream of commands/responses/errors."""
        ...


@runtime_checkable
class InputSelectable(Protocol):
    """Optional capability. Pigeon does not change inputs today; the diagnostic tool does."""

    def available_inputs(self) -> list[str]: ...
    def set_input(self, label: str) -> bool: ...


@runtime_checkable
class Relocatable(Protocol):
    """Optional capability: find the same physical receiver again after its address changed."""

    def relocate(self, identity: dict | None, *, sweep: bool = False) -> str:
        """New control address for the paired receiver ``identity``, or ``""`` if not found."""
        ...
