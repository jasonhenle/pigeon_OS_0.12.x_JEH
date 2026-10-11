"""Automatic now-playing zone widgets from WAN / LAN / audio / metadata.

User-custom layouts still exist in settings. Live display follows these
rules so Pigeon stays useful when a source drops out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pigeon.clock_saver_policy import CLOCK_SAVER_PAUSED_AFTER_S

METADATA_OK = "ok"
METADATA_STOPPED = "stopped"
METADATA_ABSENT = "absent"

LAYOUT_NP = "np"
LAYOUT_ZONE6_PAUSESAVER = "zone6_pausesaver"
LAYOUT_ZONE10_PAUSESAVER = "zone10_pausesaver"
LAYOUT_ZONE6_CLOCKSAVER = "zone6_clocksaver"
LAYOUT_ZONE8_CLOCKSAVER = "zone8_clocksaver"
LAYOUT_SETTINGS = "settings"
LAYOUT_SHAZAM = "shazam"
# Zone-6 visualizer: visualizer mode (long encoder press), or program audio
# arriving with no player metadata while in Now Playing mode.
LAYOUT_ZONE6_VISUALIZER = "zone6_visualizer"

TT = "tt_countdown_16x9"
VOLUME = "volume"
INFO = "cast_info"
STATUS = "status_bar"
SECONDS = "clock_saver_seconds"
CLOCK_SAVER = "clock_saver"
PAUSESAVER = "pausesaver"
VISUALIZER_Z6 = "visualizer_zone6"
CLOCK = "clock"  # zone 3 shows the analog face in the visualizer layout

DEFAULT_NP_ASSIGNMENTS: tuple[str, str, str, str, str] = (
    TT,
    "",
    VOLUME,
    INFO,
    STATUS,
)

_LIVE_PLAN: AutoWidgetPlan | None = None
_WAN_OK_AT_STARTUP: bool | None = None


@dataclass(frozen=True)
class AutoWidgetSignals:
    wan_ok: bool
    wan_ok_at_startup: bool
    lan_ok: bool
    reliable_clock: bool
    receiver_ok: bool
    receiver_name: str = ""
    player_metadata: str = METADATA_ABSENT
    audio_levels: bool = False
    audio_identification: bool = False
    room_renamed: bool = False
    room_name: str = ""
    paused_for_s: float = 0.0
    pausesaver_art: bool = False
    visualizer_mode: bool = False


@dataclass(frozen=True)
class AutoWidgetPlan:
    layout: str
    assignments: tuple[str, str, str, str, str]
    zone8: str = ""
    zone10: str = ""
    blank_weather: bool = False
    blank_volume: bool = False
    force_settings: bool = False
    settings_exit_enabled: bool = True
    zone4_text: str = ""
    # Zone 4 shows the receiver's input label and volume (no player metadata).
    zone4_receiver: bool = False


def reliable_clock_now(when: datetime | None = None) -> bool:
    """True when the system clock looks like it has been set (not 1970)."""
    now = when if when is not None else datetime.now()
    return int(now.year) >= 2020


def note_wan_status(wan_ok: bool) -> bool:
    """Remember whether WAN was available at boot; once True it stays True."""
    global _WAN_OK_AT_STARTUP
    ok = bool(wan_ok)
    if _WAN_OK_AT_STARTUP is None:
        _WAN_OK_AT_STARTUP = ok
    elif ok:
        _WAN_OK_AT_STARTUP = True
    return bool(_WAN_OK_AT_STARTUP)


def wan_ok_at_startup() -> bool:
    return bool(_WAN_OK_AT_STARTUP)


def reset_wan_startup_flag() -> None:
    """Test helper."""
    global _WAN_OK_AT_STARTUP
    _WAN_OK_AT_STARTUP = None


def set_live_plan(plan: AutoWidgetPlan | None) -> None:
    global _LIVE_PLAN
    _LIVE_PLAN = plan


def live_plan() -> AutoWidgetPlan | None:
    return _LIVE_PLAN


def auto_clocksaver_wants_digital(plan: AutoWidgetPlan | None = None) -> bool:
    """True when automatic widgets are showing Clocksaver (never the analog face)."""
    current = plan if plan is not None else _LIVE_PLAN
    if current is None:
        return False
    return current.layout in (LAYOUT_ZONE6_CLOCKSAVER, LAYOUT_ZONE8_CLOCKSAVER)


def room_is_renamed(name: str, *, slot_index: int = 1) -> bool:
    """True when the current ROOM label is a custom name, not ROOM N."""
    raw = str(name or "").strip()
    if not raw:
        return False
    slot = max(1, int(slot_index))
    compact = "".join(raw.split()).upper()
    if compact in {f"ROOM{slot}", f"NEST{slot}"}:
        return False
    if raw.upper() == f"ROOM {slot}":
        return False
    return True


def classify_player_metadata(
    metadata: dict[str, object] | None,
    *,
    paused: bool = False,
    playing: bool = False,
    remaining_s: float | None = None,
) -> str:
    """Map player state to ok / stopped / absent."""
    md = metadata if isinstance(metadata, dict) else {}
    if str(md.get("identity_source") or "").strip().lower() == "stale":
        # A title carried over from a previous app is not what is playing.
        return METADATA_ABSENT
    present = False
    try:
        from pigeon.display_confidence import (
            identity_displayable,
            is_placeholder_identity,
            player_metadata_adequate,
        )

        present = bool(player_metadata_adequate(md) or identity_displayable(md))
        if not present:
            q = str(
                md.get("query") or md.get("title") or ""
            ).strip()
            present = bool(q) and not is_placeholder_identity(q)
    except Exception:
        q = str(md.get("query") or md.get("title") or "").strip()
        present = bool(q)
    if not present:
        return METADATA_ABSENT
    ds = str(md.get("device_state") or "")
    try:
        from pigeon.display_confidence import playback_has_concluded

        if playback_has_concluded(md, remaining_s=remaining_s):
            return METADATA_STOPPED
    except Exception:
        pass
    if paused or "Paused" in ds or "Stopped" in ds:
        return METADATA_STOPPED
    if playing and "Paused" not in ds and "Stopped" not in ds:
        return METADATA_OK
    if playing:
        return METADATA_OK
    return METADATA_OK


def _zone3_widget(sig: AutoWidgetSignals) -> str:
    """Zone 3 is always the volume disc while LAN or program audio is present.

    With LAN down but audio still arriving, the disc stays up with a blank
    readout (``blank_volume``) until the receiver is reachable again.
    """
    if sig.lan_ok or sig.audio_levels:
        return VOLUME
    return ""


def _zone4_fallback(sig: AutoWidgetSignals) -> tuple[str, str]:
    """Return ``(widget, overlay_text)`` for zone 4 when metadata is missing."""
    if sig.wan_ok:
        if sig.room_renamed and sig.room_name:
            return ("", sig.room_name)
        return ("", "")
    if sig.audio_levels and sig.lan_ok and sig.receiver_ok and sig.receiver_name:
        return ("", sig.receiver_name)
    if sig.room_renamed and sig.room_name:
        return ("", sig.room_name)
    return ("", "")


def _plan(
    *,
    layout: str,
    assignments: tuple[str, str, str, str, str],
    sig: AutoWidgetSignals,
    zone8: str = "",
    zone10: str = "",
    force_settings: bool = False,
    zone4_text: str = "",
    zone4_receiver: bool = False,
    exit_ok: bool | None = None,
) -> AutoWidgetPlan:
    exit_enabled = bool(sig.wan_ok) if exit_ok is None else bool(exit_ok)
    return AutoWidgetPlan(
        layout=layout,
        assignments=assignments,
        zone8=zone8,
        zone10=zone10,
        blank_weather=not bool(sig.wan_ok),
        blank_volume=(not bool(sig.wan_ok)) or (not bool(sig.receiver_ok)),
        force_settings=force_settings,
        settings_exit_enabled=exit_enabled and not force_settings,
        zone4_text=zone4_text,
        zone4_receiver=zone4_receiver,
    )


def _visualizer_plan(sig: AutoWidgetSignals, *, metadata: bool) -> AutoWidgetPlan:
    """Zone 6 visualizer, analog clock in zone 3. With player metadata, zone 4/5
    keep cast info and the status bar; without it, zone 4 shows the receiver's
    input and volume and zone 5 the seconds widget."""
    if metadata:
        return _plan(layout=LAYOUT_ZONE6_VISUALIZER, assignments=(VISUALIZER_Z6, "", CLOCK, INFO, STATUS), sig=sig)
    return _plan(
        layout=LAYOUT_ZONE6_VISUALIZER,
        assignments=(VISUALIZER_Z6, "", CLOCK, "", SECONDS),
        sig=sig,
        zone4_receiver=True,
    )


def resolve_auto_widgets(sig: AutoWidgetSignals) -> AutoWidgetPlan:
    """Pick the live layout from connectivity / content signals."""
    meta = str(sig.player_metadata or METADATA_ABSENT).strip().lower()
    if meta not in (METADATA_OK, METADATA_STOPPED, METADATA_ABSENT):
        meta = METADATA_ABSENT
    if meta == METADATA_STOPPED and (
        float(sig.paused_for_s) >= float(CLOCK_SAVER_PAUSED_AFTER_S)
        or not bool(sig.pausesaver_art)
    ):
        # Pausesaver timed out, or no still to show, belongs to Clocksaver.
        meta = METADATA_ABSENT

    if not sig.wan_ok and not sig.reliable_clock:
        return _plan(
            layout=LAYOUT_SETTINGS,
            assignments=("", "", "", "", ""),
            sig=sig,
            force_settings=True,
            exit_ok=False,
        )

    if sig.visualizer_mode:
        # Stays up with or without audio (the audio badge reports a missing feed).
        # A paused title still has cast info and a position to show.
        return _visualizer_plan(sig, metadata=meta != METADATA_ABSENT)

    if sig.wan_ok:
        if meta == METADATA_OK:
            # A known title stays on now-playing even when the receiver or
            # meters briefly drop. Clocksaver is only for absent / idle content.
            z3 = _zone3_widget(sig) or VOLUME
            return _plan(
                layout=LAYOUT_NP,
                assignments=(TT, "", z3, INFO, STATUS),
                sig=sig,
            )

        if meta == METADATA_STOPPED:
            if sig.audio_levels:
                return _plan(
                    layout=LAYOUT_ZONE6_PAUSESAVER,
                    assignments=(PAUSESAVER, "", VOLUME, INFO, STATUS),
                    sig=sig,
                )
            return _plan(
                layout=LAYOUT_ZONE10_PAUSESAVER,
                assignments=("", "", "", PAUSESAVER, STATUS),
                sig=sig,
                zone10=PAUSESAVER,
            )

        if sig.audio_identification:
            z4, z4_text = _zone4_fallback(sig)
            return _plan(
                layout=LAYOUT_SHAZAM,
                assignments=(TT, "", _zone3_widget(sig) or VOLUME, z4, SECONDS),
                sig=sig,
                zone4_text=z4_text,
            )

        z4, z4_text = _zone4_fallback(sig)
        if sig.audio_levels:
            # Audio but no player metadata: the visualizer shows what is playing.
            return _visualizer_plan(sig, metadata=False)
        return _plan(
            layout=LAYOUT_ZONE8_CLOCKSAVER,
            assignments=("", "", "", z4, SECONDS),
            sig=sig,
            zone8=CLOCK_SAVER,
            zone4_text=z4_text,
        )

    # WAN off, but a usable clock exists.
    z3 = _zone3_widget(sig)
    z4, z4_text = _zone4_fallback(sig)
    if not sig.wan_ok_at_startup and not sig.reliable_clock:
        return _plan(
            layout=LAYOUT_SETTINGS,
            assignments=("", "", "", "", ""),
            sig=sig,
            force_settings=True,
            exit_ok=False,
        )
    if sig.audio_levels:
        return _visualizer_plan(sig, metadata=False)
    if sig.wan_ok_at_startup:
        return _plan(
            layout=LAYOUT_ZONE6_CLOCKSAVER,
            assignments=(CLOCK_SAVER, "", z3, z4, ""),
            sig=sig,
            zone4_text=z4_text,
        )
    return _plan(
        layout=LAYOUT_ZONE8_CLOCKSAVER,
        assignments=("", "", z3, z4, SECONDS),
        sig=sig,
        zone8=CLOCK_SAVER,
        zone4_text=z4_text,
    )
