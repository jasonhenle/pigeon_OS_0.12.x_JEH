"""
State value for the now-playing circles widget.

``ViewCirclesState`` (content mode, progress, volume, cast and status fields the widget
renders from) and the video / music content-mode constants and normalizer.

``pigeon.widgets.view_circles`` re-exports every name here for existing importers.
"""

from __future__ import annotations

from dataclasses import dataclass, field


_CONTENT_MODE_VIDEO = "video"


_CONTENT_MODE_MUSIC = "music"


@dataclass
class ViewCirclesState:
    progress: float = 0.0
    elapsed_text: str = ""
    remaining_text: str = ""
    volume: str = ""
    volume_fraction: float = 0.0
    volume_muted: bool = False
    incoming: str = ""
    config: str = ""
    chrome_visible: bool = False
    cast: list[tuple[str, str]] = field(default_factory=list)
    content_mode: str = _CONTENT_MODE_VIDEO  # "video" | "music"
    song_title: str = ""
    album_title: str = ""
    artist_title: str = ""
    searching: bool = False
    search_angle_deg: float = 0.0
    missing_art: bool = False
    paused: bool = False
    service_name: str = ""
    has_position: bool = False
    # False → clock-only layout until playback / receiver broadcast / title.
    content_active: bool = False
    # Host sets this when the foreground app is YouTube (not inferred from art).
    is_youtube: bool = False
    # Sharp Sans fallback title when no TMDb title treatment is cached.
    tt_title: str = ""
    # Paired AVR name — used for pairing chrome, not the volume caption.
    receiver_name: str = ""
    # Current AVR input (SI / InputFuncSelect), shown above the volume disc
    # when the audio format is unknown.
    receiver_input: str = ""
    # False only when the host knows the AVR is gone; empty volume is not enough.
    has_receiver: bool = True
    # Auto-layout overlay for zone 4 (room or receiver name) when info is empty.
    zone4_overlay_text: str = ""


def _normalize_content_mode(mode: str | None) -> str:
    m = str(mode or "").strip().lower()
    if m == _CONTENT_MODE_MUSIC:
        return _CONTENT_MODE_MUSIC
    return _CONTENT_MODE_VIDEO
