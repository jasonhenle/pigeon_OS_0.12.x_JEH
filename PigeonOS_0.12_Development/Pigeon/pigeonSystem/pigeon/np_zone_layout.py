"""
Now-playing zone layout selection.

Pure logic that turns the saved zone-widget layout plus live content flags
(position, cast, poster, volume, receiver, ...) into the widgets actually shown,
and small predicates over a layout. No drawing, SVG, or app-state access: the
saved-layout lookup is passed in so callers keep control of it.

``pigeon.widgets.view_circles`` imports these under their historical private
names and binds ``saved_zone_widgets`` to its own (test-patchable) lookup.
"""

from __future__ import annotations

from typing import Callable

from pigeon.np_layout import (
    DEFAULT_16X9_POSTER_ZONE,
    apply_tt_countdown_16x9_override,
    canonical_zone_widget,
    cast_names_for_zone,
)


def zone_clock_hides_header(assignments: object | None) -> bool:
    """Zone clock / wide clock already shows the time — skip the header chip."""
    for key in assignments or ():
        if str(key or "").strip() in ("clock", "clock_16x9"):
            return True
    return False


def layout_is_fullscreen_clock(
    assignments: tuple[str, ...] | list[str],
) -> bool:
    """True when no populated NP boxes remain — clock should fill the frame."""
    keys = [str(z or "").strip() for z in assignments]
    filled = [k for k in keys if k]
    return not filled or all(k == "clock" for k in filled)


def effective_zone_widgets(
    *,
    has_position: bool,
    cast_count: int = 0,
    content_active: bool = True,
    zone_widgets: tuple[str, str, str, str, str] | None = None,
    poster_16x9: bool = False,
    poster_16x9_zone: int = DEFAULT_16X9_POSTER_ZONE,
    has_poster: bool = True,
    has_volume: bool = False,
    loading_cast: bool = False,
    content_mode: str = "",
    has_title: bool | None = None,
    has_audio: bool = True,
    has_receiver: bool = True,
    has_info: bool | None = None,
    saved_zone_widgets: Callable[[str | None], tuple[str, str, str, str, str]],
) -> tuple[str, str, str, str, str]:
    """Show only widgets we have content for; never two copies of the same one.

    When ``content_active`` is False (no title / playback / receiver broadcast),
    keep the clock only so empty poster/volume/cast/bar shells do not look broken.
    The renderer then expands that clock-only layout to fill the screen.

    Saved zone widgets stay on screen. Zone 3 still falls back
    levels → volume → clock when audio or the receiver is missing. Empty
    artwork / info / status wells stay those widgets instead of swapping in
    seconds or pigeonclock. A second cast strip is kept only when more names
    remain. While cast is still loading, keep one empty ``cast_info`` slot
    for shimmer. Any other repeated widget is dropped so the layout does not
    duplicate.

    Music ``cast_info`` is track titles, so it stays even with no TMDb names.

    YouTube (``poster_16x9``) uses the same saved layout as regular now
    playing; its thumbnail is drawn as the wide art and the video title fills
    the zone-4 strip.

    ``saved_zone_widgets(content_mode)`` supplies the prefs layout when ``zone_widgets``
    is not given; callers pass their own lookup so it stays patchable.
    """
    mode = str(content_mode or "").strip().lower()
    music = mode == "music"
    zones = list(zone_widgets or saved_zone_widgets(content_mode))
    if len(zones) < 5:
        return saved_zone_widgets(content_mode)
    zones = [canonical_zone_widget(i + 1, w) for i, w in enumerate(zones[:5])]
    saver_layout = any(
        str(z or "") in {"pausesaver", "clock_saver", "clock_saver_seconds"}
        for z in zones
    )
    if not content_active:
        keep_vol = {"volume", "clock_saver_volume"}
        keep_clock = {"clock", "clock_16x9"}
        return tuple(
            z if z in keep_clock or (z in keep_vol and has_volume) else ""
            for z in zones
        )
    # Wide TT countdown spans zone 6 (slots 1+2) or zone 7 (slots 2+3):
    # blank the covered sibling portrait slot before dedupe.
    zones = list(apply_tt_countdown_16x9_override(tuple(zones)))
    named = max(0, int(cast_count))
    title_ok = bool(content_active) if has_title is None else bool(has_title)
    info_ok = (
        bool(named > 0 or loading_cast or music)
        if has_info is None
        else bool(has_info)
    )
    audio_ok = bool(has_audio)
    recv_ok = bool(has_receiver)
    zones = list(
        apply_connection_fallbacks(
            tuple(zones),
            has_title=title_ok,
            has_audio=audio_ok,
            has_receiver=recv_ok,
            has_position=bool(has_position),
            has_info=info_ok,
            loading_cast=bool(loading_cast),
        )
    )
    seen: set[str] = set()
    cast_used = 0
    cast_skeleton = False
    for i, widget in enumerate(zones):
        key = str(widget or "").strip()
        if not key:
            zones[i] = ""
            continue
        if key == "poster" and not has_poster:
            zones[i] = ""
            continue
        if key == "cast_info":
            if key in seen:
                zones[i] = ""
                continue
            if music:
                seen.add(key)
                continue
            remaining = named - cast_used
            if remaining <= 0:
                # Keep the selected info well even with no names yet.
                seen.add(key)
                if loading_cast and not cast_skeleton:
                    cast_skeleton = True
                continue
            cast_used += cast_names_for_zone(i + 1)
            seen.add(key)
            continue
        if key in seen:
            zones[i] = ""
            continue
        seen.add(key)
    return (zones[0], zones[1], zones[2], zones[3], zones[4])


def apply_connection_fallbacks(
    zones: tuple[str, str, str, str, str],
    *,
    has_title: bool,
    has_audio: bool,
    has_receiver: bool,
    has_position: bool,
    has_info: bool,
    loading_cast: bool,
) -> tuple[str, str, str, str, str]:
    """Zone 3 only: keep volume usable when the AVR is gone."""
    z = list(zones)
    _ = has_title
    _ = has_position
    _ = loading_cast
    _ = has_audio

    z3 = str(z[2] or "")
    if z3 == "volume" and not has_receiver:
        z[2] = "clock"
    elif z3 == "cast_info" and not has_info:
        z[2] = "volume" if has_receiver else "clock"
    return (z[0], z[1], z[2], z[3], z[4])
