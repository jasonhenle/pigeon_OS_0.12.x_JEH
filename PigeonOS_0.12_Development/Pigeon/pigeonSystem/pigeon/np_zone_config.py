"""
Now-playing zone widget configuration.

Which widgets may occupy each of the five now-playing zones (catalog), the
default video / music layouts, normalization of saved assignments, the persisted
header-clock flag, and the one-shot layout-generation upgrade. Pure data and
app-state access: no SVG, drawing, or settings-menu state.

``pigeon.widgets.preferences_settings`` re-exports these names for existing
importers (``view_circles``, ``input_keys``, ``main_settings``, boot phase 07).
"""

from __future__ import annotations

from pigeon.np_layout import canonical_zone_widget

# Defaults match the 1280×800 now-playing layout.
# Zone 1 stores the wide TT countdown (drawn in zone 6); zone 2 stays off.
DEFAULT_ZONE_WIDGETS: tuple[str, str, str, str, str] = (
    "tt_countdown_16x9",
    "",
    "volume",
    "cast_info",
    "status_bar",
)

# Music: wide album/TT, volume in zone 3, track titles in the zone-4 strip.
DEFAULT_MUSIC_ZONE_WIDGETS: tuple[str, str, str, str, str] = (
    "tt_countdown_16x9",
    "",
    "volume",
    "cast_info",
    "status_bar",
)

# Bump to rewrite persisted NP layouts / clocksaver defaults once.
NP_ZONE_LAYOUT_GENERATION = 168

# Spec catalog — which widgets may occupy each zone.
ZONE_WIDGET_CATALOG: dict[int, tuple[str, ...]] = {
    1: (
        "tt_countdown",
        "tt_countdown_16x9",
        "vu",
        "clock",
        "clock_16x9",
        "poster",
        "volume",
        "now_playing",
        "cast_info",
        "weather",
    ),
    2: (
        "tt_countdown",
        "tt_countdown_16x9",
        "clock",
        "clock_16x9",
        "poster",
        "volume",
        "now_playing",
        "cast_info",
        "weather",
    ),
    3: (
        "tt_countdown",
        "tt_countdown_16x9",
        "clock",
        "poster",
        "volume",
        "now_playing",
        "cast_info",
        "clock_saver_volume",
        "weather",
    ),
    4: ("cast_info", "clock_saver_volume", "weather", "clock", "status_bar"),
    5: ("status_bar", "cast_info", "clock", "weather"),
}


def _defaults_for_mode(content_mode: str | None) -> tuple[str, str, str, str, str]:
    mode = str(content_mode or "").strip().lower()
    if mode == "music":
        return DEFAULT_MUSIC_ZONE_WIDGETS
    return DEFAULT_ZONE_WIDGETS


def _state_key_for_mode(content_mode: str | None) -> str:
    mode = str(content_mode or "").strip().lower()
    if mode == "music":
        return "now_playing_zone_widgets_music"
    return "now_playing_zone_widgets"


def _normalize_zone_widgets(
    values: tuple[str, ...] | list[str] | dict[int, str] | None,
    *,
    defaults: tuple[str, str, str, str, str] | None = None,
) -> tuple[str, str, str, str, str]:
    base_defaults = list(defaults or DEFAULT_ZONE_WIDGETS)
    base = list(base_defaults)
    if isinstance(values, dict):
        for z, name in values.items():
            try:
                zi = int(z)
            except (TypeError, ValueError):
                continue
            if 1 <= zi <= 5:
                base[zi - 1] = str(name or "").strip()
    elif isinstance(values, (tuple, list)):
        for i, name in enumerate(list(values)[:5]):
            base[i] = str(name or "").strip()
    # Clamp to catalog. Empty means the zone is off. Saved ``now_playing``
    # in zone 5 becomes ``status_bar``.
    out: list[str] = []
    for i, name in enumerate(base):
        zone = i + 1
        name = canonical_zone_widget(zone, name)
        if not name:
            out.append("")
            continue
        catalog = ZONE_WIDGET_CATALOG.get(zone, ())
        out.append(name if name in catalog else base_defaults[i])
    return (out[0], out[1], out[2], out[3], out[4])


def read_now_playing_zone_widgets(
    content_mode: str | None = None,
) -> tuple[str, str, str, str, str]:
    """Zone widgets for now playing.

    Widgets are no longer user-assignable (0.11): always the default layout;
    ``pigeon.auto_widgets`` handles per-content fallbacks. Layouts saved by
    older widget pickers are ignored.
    """
    return _defaults_for_mode(content_mode)


def write_now_playing_zone_widgets(
    values: tuple[str, ...] | list[str] | dict[int, str],
    *,
    persist: bool = True,
    content_mode: str | None = None,
) -> tuple[str, str, str, str, str]:
    """Normalize zone widgets; optionally persist to app state.

    Live widget-nav preview should pass ``persist=False`` so the Pi SD card is
    not rewritten on every Left/Right. Persist on activate / BACK / exit.
    """
    defaults = _defaults_for_mode(content_mode)
    key = _state_key_for_mode(content_mode)
    norm = _normalize_zone_widgets(values, defaults=defaults)
    if not persist:
        return norm
    try:
        from pigeon.app_state import write_app_state

        write_app_state(
            **{
                key: {
                    "1": norm[0],
                    "2": norm[1],
                    "3": norm[2],
                    "4": norm[3],
                    "5": norm[4],
                }
            }
        )
    except Exception:
        pass
    return norm


def read_np_header_clock() -> bool:
    try:
        from pigeon.app_state import read_app_state

        raw = read_app_state().get("np_header_clock")
    except Exception:
        raw = None
    if raw is None:
        return True
    return bool(raw)


def write_np_header_clock(on: bool, *, persist: bool = True) -> bool:
    flag = bool(on)
    if not persist:
        return flag
    try:
        from pigeon.app_state import write_app_state

        write_app_state(np_header_clock=flag)
    except Exception:
        pass
    return flag


_CLOCK_12H_DEFAULT_GENERATION = 1


def _ensure_clock_12h_default() -> None:
    """One-shot: persist 12-hour so older 24-hour defaults flip on upgrade."""
    try:
        from pigeon.app_state import read_app_state, write_app_state

        if int(read_app_state().get("clock_12h_default_generation") or 0) >= int(
            _CLOCK_12H_DEFAULT_GENERATION
        ):
            return
        from pigeon.widgets.options_settings import read_options, write_options

        opts = read_options()
        opts["time_format"] = "12"
        write_options(opts)
        write_app_state(clock_12h_default_generation=int(_CLOCK_12H_DEFAULT_GENERATION))
    except Exception:
        pass


def ensure_now_playing_layout_defaults() -> None:
    """Once per generation: video/music zone defaults, header clock, digital °F."""
    _ensure_clock_12h_default()
    try:
        from pigeon.app_state import read_app_state, write_app_state

        gen = int(read_app_state().get("np_zone_layout_generation") or 0)
    except Exception:
        return
    if gen >= int(NP_ZONE_LAYOUT_GENERATION):
        return
    write_now_playing_zone_widgets(DEFAULT_ZONE_WIDGETS)
    write_now_playing_zone_widgets(
        DEFAULT_MUSIC_ZONE_WIDGETS, content_mode="music"
    )
    write_np_header_clock(True)
    try:
        from pigeon.widgets.options_settings import read_options, write_options

        opts = read_options()
        opts["time_format"] = "12"
        opts["clock_format"] = "digital"
        opts["temp_format"] = "f"
        write_options(opts)
    except Exception:
        pass
    try:
        write_app_state(np_zone_layout_generation=int(NP_ZONE_LAYOUT_GENERATION))
    except Exception:
        pass


def zone0_date_align(
    assignments: tuple[str, ...] | list[str] | dict[int, str] | None = None,
) -> str | None:
    """Where the zone0 date header sits on now-playing.

    - default → ``left``
    - zone1 poster → ``center``
    - zone1 + zone2 poster → ``right``
    - zone1 + zone2 + zone3 poster → ``None`` (header off)

    Preferences keeps this logic but does not display the header.
    """
    a = _normalize_zone_widgets(assignments)
    p1 = a[0] == "poster"
    p2 = a[1] == "poster"
    p3 = a[2] == "poster"
    if p1 and p2 and p3:
        return None
    if p1 and p2:
        return "right"
    if p1:
        return "center"
    return "left"
