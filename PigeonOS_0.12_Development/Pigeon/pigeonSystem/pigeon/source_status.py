"""Live status for Pigeon's data sources (network, player metadata, audio).

settings_pigeon only *reports* whether each source is active; every source is
always used. (Older installs may still carry a ``source_toggles`` key in
``state.json``; it is ignored and cleared by a factory reset.)

The metadata and audio indicators are green when that source was seen in the
last :data:`SOURCE_RECENT_S` seconds.
"""

from __future__ import annotations

import time
from typing import Any

SOURCE_RECENT_S = 60.0

_metadata_seen_mono = 0.0


def note_metadata_received(now: float | None = None) -> None:
    """Stamp a metadata poll result from the player / receiver."""
    global _metadata_seen_mono
    _metadata_seen_mono = float(time.monotonic() if now is None else now)


def metadata_received_within(seconds: float = SOURCE_RECENT_S) -> bool:
    seen = float(_metadata_seen_mono)
    return seen > 0.0 and (time.monotonic() - seen) < float(seconds)


def audio_received_within(seconds: float = SOURCE_RECENT_S) -> bool:
    try:
        from pigeon.widgets.audio_meter_saver import program_audio_seen_within

        return bool(program_audio_seen_within(seconds))
    except Exception:
        return False


def apply_source_status_to_settings_state(state: Any) -> None:
    """Refresh the network / metadata / audio flags behind the settings_pigeon lights."""
    state.pigeon_audio_ok = audio_received_within()
    state.pigeon_metadata_ok = metadata_received_within()
    state.pigeon_network_ok = network_connected()


def network_connected() -> bool:
    """Host is on a network (the SSID alone misses wired links and macOS,
    which hides the SSID from apps without Location access)."""
    try:
        from pigeon.local_ip import has_lan_route

        return has_lan_route()
    except Exception:
        return False
