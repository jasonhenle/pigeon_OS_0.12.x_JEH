"""
Now-playing zone widget selector — ``settings_0.8/pigeon_settings_preferences.svg``.

Opened from pigeon device settings when **prefs** / settings is activated.

Navigation A (zones): pick zone 1–5 or BACK (BACK → pigeon settings).
Navigation B (widgets): with a zone locked selected, cycle widgets available
for that zone; activate confirms and returns to zones. BACK still exits to
pigeon settings.
"""

from __future__ import annotations

import copy
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np

from pigeon.design import DESIGN_H, DESIGN_W
from pigeon.pigeon_locale import pigeon_now
from pigeon.np_layout import is_status_bar_widget
from pigeon.np_zone_config import (  # noqa: F401  (re-exported for existing importers)
    DEFAULT_MUSIC_ZONE_WIDGETS,
    DEFAULT_ZONE_WIDGETS,
    NP_ZONE_LAYOUT_GENERATION,
    ZONE_WIDGET_CATALOG,
    _CLOCK_12H_DEFAULT_GENERATION,
    _defaults_for_mode,
    _ensure_clock_12h_default,
    _normalize_zone_widgets,
    _state_key_for_mode,
    ensure_now_playing_layout_defaults,
    read_np_header_clock,
    read_now_playing_zone_widgets,
    write_np_header_clock,
    write_now_playing_zone_widgets,
    zone0_date_align,
)
from pigeon.widgets.settings_svg_text import center_label_on_pill
from pigeon.widgets.main_settings import (
    MainSettingsState,
    _composite_bgra_over_bgra,
    _disable_embedded_settings_background_layers,
    _draw_container_background_bgra,
    _find_by_logical_id,
    _prune_display_none,
    _set_paint,
    _set_text_content,
    _set_visible,
)
from pigeon.widgets.preferences_overlays import (  # noqa: F401  (re-exported for existing importers)
    XLINK_NS,
    _COLOR_BTN_CENTER,
    _COLOR_BTN_H,
    _COLOR_BTN_IMAGE_CACHE,
    _COLOR_BTN_IMG_TRANSFORM,
    _COLOR_BTN_RX,
    _COLOR_BTN_W,
    _COLOR_BTN_X,
    _COLOR_BTN_Y,
    _PREFS_AUDIO_CFG_SIZE_PX,
    _PREFS_BACKGROUND_DIM_ALPHA,
    _PREFS_BAR_H,
    _PREFS_BAR_L,
    _PREFS_BAR_R,
    _PREFS_BAR_RX,
    _PREFS_BAR_T,
    _PREFS_BAR_TEXT_Y,
    _PREFS_CAST_COLS_Z4,
    _PREFS_CAST_COLS_Z5,
    _PREFS_CAST_COL_W,
    _PREFS_CTI_W,
    _PREFS_DEMO_CAST,
    _PREFS_NP_CENTER_FILL_BGR,
    _PREFS_NP_DEMO_PROGRESS,
    _PREFS_NP_RING_INNER_R,
    _PREFS_NP_RING_OUTER_R,
    _PREFS_NP_TIME_SIZE_PX,
    _PREFS_POSTER_FRAMES,
    _PREFS_POSTER_IMAGE_IDS,
    _PREFS_POSTER_MASTER_CACHE,
    _PREFS_POSTER_PATCH_CACHE,
    _PREFS_POSTER_PATCH_CACHE_MAX,
    _PREFS_VIEWBOX,
    _PREFS_VOLUME_DEMO_CFG,
    _PREFS_VOLUME_DEMO_DB,
    _PREFS_VOLUME_SIZE_PX,
    _SELECTOR_LABELS,
    _SELECTOR_LABEL_LINE_PITCH,
    _SELECTOR_LABEL_SIZE_PX,
    _SELECTOR_LABEL_Y_NUDGE_PX,
    _TT_COUNTDOWN_DEMO_TIME,
    _TT_COUNTDOWN_DEMO_TITLE,
    _ZONE_ACCENT_STROKE_PX,
    _ZONE_BUTTON_STROKE_PX,
    _ZONE_NUMERAL_SIZE_PX,
    _center_digital_text,
    _clear_preferences_selector_label_texts,
    _clear_preferences_zone_number_texts,
    _collect_preferences_clock_centers,
    _collect_preferences_np_centers,
    _collect_preferences_volume_centers,
    _decode_svg_image_bgra,
    _draw_preferences_cast_bgra,
    _draw_preferences_circular_now_playing_bgra,
    _draw_preferences_clock_digitals_bgra,
    _draw_preferences_color_button_bgra,
    _draw_preferences_posters_bgra,
    _draw_preferences_selector_labels_bgra,
    _draw_preferences_status_bar_bgra,
    _draw_preferences_track_titles_bgra,
    _draw_preferences_tt_countdown_bgra,
    _draw_preferences_volume_bgra,
    _draw_preferences_zone_numbers_bgra,
    _hide_preferences_color_button_images,
    _hide_preferences_live_demo_texts,
    _hide_preferences_poster_images,
    _layer_key,
    _preferences_now_playing_progress,
    _preferences_volume_fraction,
    _preferences_volume_lines,
    _prefs_color_gradient_master,
    _prefs_color_group,
    _prefs_find_in_group,
    _prefs_poster_masters,
    _prefs_poster_patch_for_zone,
    _prefs_volume_center,
    _prefs_volume_group,
    _selector_group_for_widget,
    _selector_label_fill_rgba,
    _selector_label_font,
    _selector_pill_center,
    _sharp_text_patch,
    _stamp_preferences_artwork_mask,
    _widget_group_parts,
    _zone_group_parts,
)

SVG_NS = "http://www.w3.org/2000/svg"


_COLOR_BLACK = "#000000"
_COLOR_WHITE = "#FFFFFF"
_COLOR_GRAY = "#808080"  # 50% gray for unavailable chrome

# Selector chrome groups (navigation B), left → right in the SVG.
_WIDGET_SELECTOR_ORDER: tuple[str, ...] = (
    "tt_countdown",
    "tt_countdown_16x9",
    "clock",
    "poster",
    "volume",
    "now_playing",
    "status_bar",
    "cast_info",
    "clock_saver_volume",
)

# Match settings_main EXIT geometry on the preferences artboard (viewBox +339,+440).
_BACK_BUTTON_D = (
    "M426.443,535H376.367c-5.278,0-9.557-4.279-9.557-9.557V507.628"
    "c0-5.831,4.727-10.557,10.557-10.557h49.075c5.278,0,9.557,4.279,9.557,9.557"
    "v18.814C436,530.721,431.721,535,426.443,535z"
)
_BACK_TEXT_X = 401.405  # button center (design 62.405 + 339)
_BACK_TEXT_Y = 525.7403  # same baseline as settings_main EXIT
_COLOR_EXIT_FILL = "#202020"
# COLOR label: group is translate(339,440); Pillow text overlay ignores parent
# transforms, so the <text> matrix must be absolute SVG (same as BACK).
_COLOR_TEXT_X = 1060.103  # pill center local 721.103 + 339
_COLOR_TEXT_Y = 803.3755  # baseline local 363.3755 + 440
_COLOR_TEXT_SIZE = "21"

_ZONE_NAV_ORDER: tuple[str, ...] = (
    "zone1",
    "zone2",
    "zone3",
    "zone4",
    "zone5",
    "color",  # after zone5; before BACK
    "exit",
)

_SVG_TREE_TEMPLATES: dict[tuple[str, int, int], ET.Element] = {}
_SVG_TREE_TEMPLATE_MAX = 4
# Structure base (theme+UI without live clock/NP overlays). Keyed without wall clock.
_PREFS_STRUCTURE_CACHE: dict[tuple[object, ...], tuple[np.ndarray, dict[str, object]]] = {}
_PREFS_STRUCTURE_CACHE_MAX = 24
# Dimmed theme plate per ui_hex (full-frame scrim is expensive on Pi).
_PREFS_DIMMED_BG_CACHE: dict[tuple[object, ...], np.ndarray] = {}
_PREFS_DIMMED_BG_CACHE_MAX = 4


def default_preferences_svg_path(assets_dir: Path | str | None = None) -> Path:
    env = os.environ.get("PIGEON_PREFERENCES_SVG", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if assets_dir is not None:
        return Path(assets_dir) / "settings_0.8" / "pigeon_settings_preferences.svg"
    pigeon_root = Path(__file__).resolve().parents[3]
    return pigeon_root / "pigeonAssets" / "settings_0.8" / "pigeon_settings_preferences.svg"


def preferences_zone_focus_ring() -> tuple[str, ...]:
    return _ZONE_NAV_ORDER


def preferences_widget_focus_ring(zone: int) -> tuple[str, ...]:
    """BACK + widgets available for ``zone`` (selector order)."""
    z = int(zone)
    available = set(ZONE_WIDGET_CATALOG.get(z, ()))
    ring: list[str] = ["exit"]
    for wid in _WIDGET_SELECTOR_ORDER:
        if wid in available:
            ring.append(wid)
    return tuple(ring)


def _strip_embedded_poster_images(root: ET.Element) -> int:
    """Remove ``poster_tmdb`` ``<image>`` nodes (≈2MB base64). Redrawn after raster."""
    parent_map = {c: p for p in root.iter() for c in p}
    removed = 0
    for el in list(root.iter()):
        if not el.tag.endswith("image"):
            continue
        key = _layer_key(el)
        eid = (el.get("id") or "").strip()
        if key == "poster_tmdb" or eid.startswith("poster_tmdb"):
            parent = parent_map.get(el)
            if parent is not None:
                try:
                    parent.remove(el)
                    removed += 1
                except (ValueError, TypeError):
                    _set_visible(el, False)
            else:
                _set_visible(el, False)
    return removed


def _svg_tree_from_path(path: Path) -> ET.Element:
    try:
        st = path.stat()
        key = (str(path.resolve()), int(st.st_mtime_ns), int(st.st_size))
    except OSError:
        key = (str(path), 0, 0)
    template = _SVG_TREE_TEMPLATES.get(key)
    if template is None:
        root = ET.parse(path).getroot()
        x, y, w, h = _PREFS_VIEWBOX
        root.set("viewBox", f"{x} {y} {w} {h}")
        root.set("width", str(DESIGN_W))
        root.set("height", str(DESIGN_H))
        # Drop embedded posters once so every deepcopy stays ~100KB, not ~2MB.
        _strip_embedded_poster_images(root)
        if len(_SVG_TREE_TEMPLATES) >= _SVG_TREE_TEMPLATE_MAX:
            _SVG_TREE_TEMPLATES.clear()
        _SVG_TREE_TEMPLATES[key] = root
        template = root
    return copy.deepcopy(template)


def _paint_subtree(
    el: ET.Element | None,
    *,
    fill: str | None = None,
    stroke: str | None = None,
) -> None:
    if el is None:
        return
    tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
    if tag in ("path", "polygon", "polyline", "circle", "ellipse", "rect"):
        kwargs: dict[str, str] = {}
        if fill is not None:
            kwargs["fill"] = fill
        if stroke is not None:
            kwargs["stroke"] = stroke
        if kwargs:
            _set_paint(el, **kwargs)
    for child in list(el):
        _paint_subtree(child, fill=fill, stroke=stroke)


def _paint_text(el: ET.Element | None, color: str) -> None:
    if el is None:
        return
    nodes = [el] if el.tag.endswith("text") else [
        n for n in el.iter() if n.tag.endswith("text") or n.tag.endswith("tspan")
    ]
    if not nodes:
        nodes = [el]
    for node in nodes:
        _set_paint(node, fill=color)


def _apply_zone_chrome(group: ET.Element | None, *, selected: bool) -> None:
    button, accent, text = _zone_group_parts(group)
    if selected:
        _paint_subtree(button, fill=_COLOR_WHITE, stroke=_COLOR_BLACK)
        _paint_text(text, _COLOR_BLACK)
    else:
        _paint_subtree(button, fill=_COLOR_BLACK, stroke=_COLOR_BLACK)
        _paint_text(text, _COLOR_WHITE)
    # Accent stays white stroke / no fill in both states.
    _paint_subtree(accent, fill="none", stroke=_COLOR_WHITE)


def _apply_widget_chrome(
    group: ET.Element | None,
    *,
    selected: bool,
    available: bool,
    idle_fill: str | None = None,
) -> None:
    button, accent, text = _widget_group_parts(group)
    rest_fill = idle_fill if idle_fill is not None else _COLOR_BLACK
    if not available:
        _paint_subtree(button, fill=rest_fill, stroke=_COLOR_BLACK)
        _paint_subtree(accent, fill="none", stroke=_COLOR_GRAY)
        _paint_text(text, _COLOR_GRAY)
        return
    if selected:
        _paint_subtree(button, fill=_COLOR_WHITE, stroke=_COLOR_BLACK)
        _paint_text(text, _COLOR_BLACK)
        _paint_subtree(accent, fill="none", stroke=_COLOR_WHITE)
        return
    _paint_subtree(button, fill=rest_fill, stroke=_COLOR_BLACK)
    _paint_text(text, _COLOR_WHITE)
    _paint_subtree(accent, fill="none", stroke=_COLOR_WHITE)


def _sync_preferences_back_button(root: ET.Element) -> None:
    """Match settings_main EXIT placement; label centered as BACK."""
    group = _find_by_logical_id(root, "selector_exit_group")
    button, accent, text = _widget_group_parts(group)
    for path_el in (button, accent):
        if path_el is not None:
            path_el.set("d", _BACK_BUTTON_D)
            if path_el is button and not (path_el.get("fill") or "").strip():
                path_el.set("fill", _COLOR_EXIT_FILL)
    if text is not None:
        text.set("transform", f"translate({_BACK_TEXT_X:.4f} {_BACK_TEXT_Y:.4f})")
        text.set("text-anchor", "middle")
        text.set("font-family", "Digital-7, Digital-7")
        text.set("font-size", "29")
        _set_text_content(text, "BACK")
        text.attrib.pop("text-anchor", None)
        center_label_on_pill(
            text,
            button if button is not None else accent,
            viewbox=_PREFS_VIEWBOX,
            canvas=(DESIGN_W, DESIGN_H),
        )


def _prefs_color_find(group: ET.Element | None, logical_id: str) -> ET.Element | None:
    """Find a descendant of the color group by decoded logical id."""
    from pigeon.widgets.main_settings import _normalize_logical

    if group is None:
        return None
    want = _normalize_logical(logical_id)
    for el in group.iter():
        if _normalize_logical(el.get("id") or "") == want:
            return el
    return _find_by_logical_id(group, logical_id)


def _apply_preferences_color_chrome(root: ET.Element, *, selected: bool) -> None:
    """Selected/deselected chrome for the prefs color control (nav after zone5).

    Graphic: ``color_button_prefs_selected`` / ``_deselected`` visibility toggle.
    Text pill:
      - ``…_color_button_interior_fill`` — black deselected, white selected
      - ``…_color_text_accent`` — path stroke: white deselected, black selected
      - ``…_color_text_accent_interior_stroke`` — outer stroke (white)
      - ``…_color_text`` — glyph fill: white deselected, black selected
    """
    group = _prefs_color_group(root)
    if group is None:
        return
    _set_visible(group, True)
    sel = _prefs_color_find(group, "color_button_prefs_selected")
    des = _prefs_color_find(group, "color_button_prefs_deselected")
    _set_visible(sel, bool(selected))
    _set_visible(des, not bool(selected))

    interior_fill = _prefs_color_find(
        group, "settings_pigeon_preferences_color_button_interior_fill"
    )
    text_accent = _prefs_color_find(
        group, "settings_pigeon_preferences_color_text_accent"
    )
    interior_stroke = _prefs_color_find(
        group, "settings_pigeon_preferences_color_text_accent_interior_stroke"
    ) or _prefs_color_find(
        group, "settings_pigeon_preferences_color_text_interior_stroke"
    )
    text_el = _prefs_color_find(group, "settings_pigeon_preferences_color_text")
    if text_el is not None:
        # Absolute coords so Pillow overlay (no parent transforms) lands in the pill.
        text_el.set(
            "transform",
            f"matrix(1 0 0 1 {_COLOR_TEXT_X:.4f} {_COLOR_TEXT_Y:.4f})",
        )
        text_el.set("text-anchor", "middle")
        text_el.set("font-family", "Digital-7, Digital-7")
        text_el.set("font-size", _COLOR_TEXT_SIZE)
        style = text_el.get("style") or ""
        style = re.sub(
            r"font-family\s*:\s*[^;]+;?\s*", "", style, flags=re.IGNORECASE
        )
        style = re.sub(
            r"font-size\s*:\s*[^;]+;?\s*", "", style, flags=re.IGNORECASE
        )
        style = style.strip().rstrip(";")
        if style:
            text_el.set("style", style)
        else:
            text_el.attrib.pop("style", None)
        _set_text_content(text_el, "COLOR")

    if selected:
        if interior_fill is not None:
            _set_paint(interior_fill, fill=_COLOR_WHITE)
        if text_accent is not None:
            _set_paint(text_accent, fill="none", stroke=_COLOR_BLACK)
        if interior_stroke is not None:
            _set_paint(interior_stroke, fill="none", stroke=_COLOR_WHITE)
        _paint_text(text_el, _COLOR_BLACK)
    else:
        if interior_fill is not None:
            _set_paint(interior_fill, fill=_COLOR_BLACK)
        if text_accent is not None:
            _set_paint(text_accent, fill="none", stroke=_COLOR_WHITE)
        if interior_stroke is not None:
            _set_paint(interior_stroke, fill="none", stroke=_COLOR_WHITE)
        _paint_text(text_el, _COLOR_WHITE)


        # No curved audio-config label on the preferences page — live
        # now-playing keeps it.


def _apply_preferences_zone_dynamics(
    root: ET.Element,
    assignments: tuple[str, str, str, str, str],
    *,
    now: datetime | None = None,
) -> None:
    """Drive clock ticks / digital time; adapt volume vs circular now-playing.

    When nothing is playing the SVG keeps its static examples (volume level,
    cast, poster, zone5 bar). Clock always follows wall time.
    """
    from pigeon.widgets.view_circles import (
        _apply_clock_accent_fills,
        _apply_clock_ticks,
        _find_by_key,
    )

    dt = now if now is not None else pigeon_now()
    _apply_clock_accent_fills(root)

    for zone in (1, 2, 3):
        widget = assignments[zone - 1]
        if widget == "clock":
            # Tick wedges bake into the structure bitmap; HH:MM is Pillow-overlaid
            # each second so the full SVG path need not re-run for wall clock.
            _apply_clock_ticks(root, zone, dt)
            digital = _find_by_key(root, f"zone{zone}_clock_digital_text")
            if digital is not None:
                _set_visible(digital, False)
            continue

        if widget not in ("volume", "now_playing"):
            continue

        vol_group = _prefs_volume_group(root, zone)
        center = _prefs_volume_center(root, zone)
        vol_text = _prefs_find_in_group(vol_group, key_endswith="volume_text")
        cfg_text = _prefs_find_in_group(
            vol_group, key_endswith="voume_audio_config_text"
        ) or _prefs_find_in_group(vol_group, key_endswith="audio_config_text")
        if widget == "now_playing":
            # Circular now-playing: pie + time are redrawn after rasterize.
            if cfg_text is not None:
                _set_visible(cfg_text, False)
            if vol_text is not None:
                _set_visible(vol_text, False)
            for suffix in (
                "volume_selected_button",
                "volume_deselected_buton",
                "volume_container",
            ):
                el = _prefs_find_in_group(vol_group, key_endswith=suffix)
                if el is not None:
                    _set_visible(el, False)
            continue

        # Volume widget — pie + readout are redrawn after rasterize (same as
        # circular now_playing). Hide static full-disc SVG chrome / demo text.
        if cfg_text is not None:
            _set_visible(cfg_text, False)
        if vol_text is not None:
            _set_visible(vol_text, False)
        for suffix in (
            "volume_selected_button",
            "volume_deselected_buton",
            "volume_container",
        ):
            el = _prefs_find_in_group(vol_group, key_endswith=suffix)
            if el is not None:
                _set_visible(el, False)


def _widget_preview_keys(zone: int, widget: str) -> tuple[str, ...]:
    """Layer keys under the preferences SVG that belong to ``widget`` in ``zone``."""
    z = int(zone)
    w = str(widget)
    if z == 4:
        return ("zone4_cast_info_group",) if w == "cast_info" else ()
    if z == 5:
        # Cast sits beside the bar under a shared outer ``zone5_now_playing_group``.
        # Toggle the inner bar / cast kids — not the outer container.
        if w in ("now_playing", "status_bar"):
            return ("zone5_now_playing_bar", "zone5_now_playing_group")
        if w == "cast_info":
            return ("zone5_cast_info_group", "zone5_cast_group")
        return ()
    if w == "clock":
        return (f"zone{z}_clock_group",)
    if w == "volume":
        return (f"zone{z}_volume_group",)
    if w == "now_playing":
        # Zones 1–3 reuse the volume ring chrome for playback progress.
        return (f"zone{z}_volume_group",)
    if w == "cast_info":
        return (f"zone{z}_cast_info_group", f"zone{z}_cast_group")
    if w == "poster":
        return (
            f"zone{z}_poster_group",
            f"zone{z}_poster_art_group",
            f"zone{z}_poster_2x3",
            f"zone{z}_2x3_poster_group",
            f"zone{z}_album_art_1x1",
        )
    return ()


def _zone5_container_and_kids(
    root: ET.Element,
) -> tuple[ET.Element | None, ET.Element | None, ET.Element | None]:
    """Return ``(outer, bar_group, cast_group)`` for zone5 preview layers.

    Current Illustrator export nests cast under the outer now-playing group::

        zone5_now_playing_group
          zone5_cast_info_group
          zone5_now_playing_group   (inner bar / CTI)
    """
    outer = _find_by_logical_id(root, "zone5_now_playing_group")
    if outer is None:
        return None, None, None
    bar = cast = None
    for child in list(outer):
        key = _layer_key(child)
        if key in ("zone5_cast_info_group", "zone5_cast_group"):
            cast = child
        elif "now_playing" in key:
            bar = child
    # Flat export fallback (siblings, not nested).
    if cast is None:
        cast = _find_by_logical_id(root, "zone5_cast_info_group") or _find_by_logical_id(
            root, "zone5_cast_group"
        )
    return outer, bar, cast


def _iter_zone_widget_layers(root: ET.Element, zone: int):
    """Yield direct widget layers for a zone (preferences preview)."""
    z = int(zone)
    if z in (1, 2, 3):
        parent = _find_by_logical_id(root, f"zone{z}_group")
        if parent is None:
            return
        for child in list(parent):
            yield child
        return
    if z == 4:
        el = _find_by_logical_id(root, "zone4_cast_info_group")
        if el is not None:
            yield el
        return
    if z == 5:
        _outer, bar, cast = _zone5_container_and_kids(root)
        if bar is not None:
            yield bar
        if cast is not None:
            yield cast


def _apply_zone0_date_preview(
    root: ET.Element,
    _assignments: tuple[str, str, str, str, str],
) -> None:
    """Hide zone0 date chrome on preferences (align logic still drives now-playing)."""
    header = _find_by_logical_id(root, "zone0_header_group")
    _set_visible(header, False)
    for name in ("left", "center", "right"):
        _set_visible(_find_by_logical_id(root, f"zone0_date_{name}_text"), False)


def _apply_zone_preview(root: ET.Element, zone: int, widget: str) -> None:
    z = int(zone)
    w = str(widget)
    if z == 5:
        outer, bar, cast = _zone5_container_and_kids(root)
        # Keep the outer wrapper visible so nested cast/bar can show.
        if outer is not None:
            _set_visible(outer, True)
        if bar is not None:
            # Inner bar group often reuses the now_playing name — show only for bar widget.
            _set_visible(bar, w in ("now_playing", "status_bar"))
        if cast is not None:
            _set_visible(cast, w == "cast_info")
        return

    want = set(_widget_preview_keys(z, w))
    for el in _iter_zone_widget_layers(root, z):
        key = _layer_key(el)
        show = key in want or any(key.startswith(prefix) for prefix in want)
        # Nested poster groups: show parent if any child key matches.
        if not show and "poster" in key and any("poster" in prefix for prefix in want):
            show = True
        _set_visible(el, show)


def apply_preferences_svg_state(root: ET.Element, state: MainSettingsState) -> None:
    nav = str(getattr(state, "preferences_nav", "zones") or "zones")
    active_zone = int(getattr(state, "preferences_active_zone", 0) or 0)
    assignments = _normalize_zone_widgets(
        getattr(state, "preferences_zone_widgets", None) or DEFAULT_ZONE_WIDGETS
    )
    live = bool(getattr(state, "preferences_live_content", False))
    if live:
        all_cast = list(getattr(state, "preferences_cast", None) or ())
        named = sum(1 for actor, _role in all_cast if str(actor or "").strip())
        from pigeon.widgets.view_circles import _effective_zone_widgets

        assignments = _effective_zone_widgets(
            has_position=getattr(state, "preferences_np_progress", None) is not None,
            cast_count=named,
            zone_widgets=assignments,
        )
    else:
        from pigeon.np_layout import apply_tt_countdown_16x9_override

        assignments = apply_tt_countdown_16x9_override(assignments)
    focused = str(getattr(state, "preferences_focused_id", "") or "")

    # Zone preview layers follow current assignments (live while browsing widgets).
    for zone in (1, 2, 3, 4, 5):
        _apply_zone_preview(root, zone, assignments[zone - 1])

    # Zone0 date: left / center / right / off from poster occupancy.
    _apply_zone0_date_preview(root, assignments)

    # Zone selector chrome.
    for zone in (1, 2, 3, 4, 5):
        group = _find_by_logical_id(root, f"selector_zone{zone}_group")
        if nav == "widgets" and active_zone == zone:
            selected = True  # locked selected while editing widgets
        elif nav == "zones":
            selected = focused == f"zone{zone}"
        else:
            selected = False
        _apply_zone_chrome(group, selected=selected)

    # Live clock ticks / digital time; volume keeps static example when idle.
    _apply_preferences_zone_dynamics(root, assignments)

    live = bool(getattr(state, "preferences_live_content", False))
    if live:
        # Cast + zone5 bar/text are redrawn after rasterize from live state.
        _hide_preferences_live_demo_texts(root)
    else:
        # Zone5 demo elapsed fill follows settings UI color.
        try:
            from pigeon.widgets.view_circles import _set_tick_paint, np_theme_from_settings

            elapsed = _find_by_logical_id(root, "zone5_now_playing_elapsed_icon")
            if elapsed is None:
                from pigeon.widgets.view_circles import _find_by_key

                elapsed = _find_by_key(root, "zone5_now_playing_elapsed_icon")
            if elapsed is not None:
                _set_tick_paint(elapsed, color=np_theme_from_settings().ui_hex)
        except Exception:
            pass

    # Widget selector chrome + BACK (settings_main EXIT twin).
    _sync_preferences_back_button(root)
    available: set[str] = set()
    if nav == "widgets" and active_zone in ZONE_WIDGET_CATALOG:
        available = set(ZONE_WIDGET_CATALOG[active_zone])

    for wid in _WIDGET_SELECTOR_ORDER:
        if nav == "widgets" and active_zone == 5:
            if wid == "now_playing":
                continue
        elif wid == "status_bar":
            continue
        group = _selector_group_for_widget(root, wid)
        if nav == "zones":
            # Resting available look while choosing a zone.
            _apply_widget_chrome(group, selected=False, available=True)
        else:
            selected = focused == wid or (
                wid == "now_playing" and focused == "status_bar"
            ) or (
                wid == "status_bar" and focused == "now_playing"
            )
            is_avail = wid in available or (
                wid == "now_playing" and "status_bar" in available
            ) or (
                wid == "status_bar" and "now_playing" in available
            )
            _apply_widget_chrome(
                group,
                selected=selected,
                available=is_avail,
            )

    # Audio levels was retired; keep its legacy selector pill out of the art.
    retired = _find_by_logical_id(root, "selector_audio_levels_group")
    if retired is not None:
        _set_visible(retired, False)

    exit_group = _selector_group_for_widget(root, "exit")
    exit_selected = focused == "exit"
    _apply_widget_chrome(
        exit_group,
        selected=exit_selected,
        available=True,
        idle_fill=_COLOR_EXIT_FILL,
    )

    # Color control lives in zone navigation (zone5 → color → BACK).
    color_selected = nav == "zones" and focused == "color"
    _apply_preferences_color_chrome(root, selected=color_selected)

    # Labels / numerals / posters are Pillow-composited after rasterize
    # (SVG text metrics skew; PyMuPDF drops rounded clip-path on poster images).
    _clear_preferences_selector_label_texts(root)
    _clear_preferences_zone_number_texts(root)
    _hide_preferences_poster_images(root)
    _hide_preferences_color_button_images(root)


def _prefs_structure_cache_key(
    state: MainSettingsState,
    *,
    path: Path,
    assets_dir: Path | str | None,
) -> tuple[object, ...]:
    try:
        st_stat = path.stat()
        path_key = (str(path.resolve()), int(st_stat.st_mtime_ns), int(st_stat.st_size))
    except OSError:
        path_key = (str(path), 0, 0)
    th = state.theme
    return (
        path_key,
        str(assets_dir or ""),
        str(th.ui),
        str(th.selected),
        str(th.deselected),
        str(th.accent),
        str(getattr(state, "preferences_nav", "zones") or "zones"),
        int(getattr(state, "preferences_focus_index", 0) or 0),
        int(getattr(state, "preferences_active_zone", 0) or 0),
        tuple(
            _normalize_zone_widgets(
                getattr(state, "preferences_zone_widgets", None) or DEFAULT_ZONE_WIDGETS
            )
        ),
        # Minute bucket: second wedges refresh at most once/min without full nav.
        pigeon_now().strftime("%H%M"),
        1 if getattr(state, "preferences_live_content", False) else 0,
        6,  # structure schema — TT+TRT vertically centered
    )


def _prefs_dimmed_theme_bgra(
    state: MainSettingsState,
    *,
    assets_dir: Path | str | None,
    path: Path,
) -> np.ndarray:
    """Cached theme plate + 80% black scrim (full-frame partial alpha is costly on Pi)."""
    ui_hex = str(state.theme.ui)
    adir = str(assets_dir if assets_dir is not None else path.parent.parent)
    key = (ui_hex, adir, int(_PREFS_BACKGROUND_DIM_ALPHA), int(DESIGN_W), int(DESIGN_H))
    cached = _PREFS_DIMMED_BG_CACHE.get(key)
    if cached is not None:
        return cached
    bg_bgra = np.zeros((DESIGN_H, DESIGN_W, 4), dtype=np.uint8)
    bg_bgra[:, :, 3] = 255
    _draw_container_background_bgra(
        bg_bgra,
        ui_hex=ui_hex,
        assets_dir=adir,
    )
    # Uniform black scrim: scale RGB in-place (avoids float32 composite of 800×480).
    a = float(_PREFS_BACKGROUND_DIM_ALPHA) / 255.0
    keep = 1.0 - a
    dimmed = bg_bgra.copy()
    dimmed[:, :, :3] = np.clip(
        dimmed[:, :, :3].astype(np.float32) * keep, 0, 255
    ).astype(np.uint8)
    while len(_PREFS_DIMMED_BG_CACHE) >= _PREFS_DIMMED_BG_CACHE_MAX:
        _PREFS_DIMMED_BG_CACHE.pop(next(iter(_PREFS_DIMMED_BG_CACHE)))
    _PREFS_DIMMED_BG_CACHE[key] = dimmed
    return dimmed


def _render_preferences_structure_bgra(
    state: MainSettingsState,
    *,
    path: Path,
    assets_dir: Path | str | None,
) -> tuple[np.ndarray, dict[str, object]]:
    """Full SVG raster + labels/chrome; posters/NP overlays drawn each frame."""
    root = _svg_tree_from_path(path)
    apply_preferences_svg_state(root, state)
    np_centers = _collect_preferences_np_centers(root, state)
    volume_centers = _collect_preferences_volume_centers(root, state)
    clock_centers = _collect_preferences_clock_centers(root, state)
    _disable_embedded_settings_background_layers(root)
    _prune_display_none(root)
    from pigeon.widgets.settings_svg_text import rasterize_settings_svg_bgra

    ui_bgra = rasterize_settings_svg_bgra(
        root,
        width=DESIGN_W,
        height=DESIGN_H,
        font_mode="preferences",
    )
    # Idle demo posters bake into the structure; live artwork is overlaid later.
    if not getattr(state, "preferences_live_content", False):
        _draw_preferences_posters_bgra(ui_bgra, state, svg_path=path)
    # tt_countdown zones show a schematic card (demo title + countdown).
    _draw_preferences_tt_countdown_bgra(ui_bgra, state)
    _draw_preferences_color_button_bgra(ui_bgra, state, svg_path=path)
    _draw_preferences_selector_labels_bgra(ui_bgra, root, state)
    _draw_preferences_zone_numbers_bgra(ui_bgra, root, state)
    dimmed_bg = _prefs_dimmed_theme_bgra(state, assets_dir=assets_dir, path=path)
    base = _composite_bgra_over_bgra(dimmed_bg, ui_bgra)
    meta: dict[str, object] = {
        "np_centers": np_centers,
        "volume_centers": volume_centers,
        "clock_centers": clock_centers,
        "svg_path": path,
    }
    return base, meta


def render_preferences_settings_bgra(
    state: MainSettingsState | None = None,
    *,
    svg_path: Path | str | None = None,
    assets_dir: Path | str | None = None,
) -> np.ndarray:
    if svg_path is not None:
        path = Path(svg_path)
    else:
        path = default_preferences_svg_path(assets_dir)
    if not path.is_file():
        raise FileNotFoundError(f"preferences SVG not found: {path}")

    st = state if state is not None else MainSettingsState()
    key = _prefs_structure_cache_key(st, path=path, assets_dir=assets_dir)
    cached = _PREFS_STRUCTURE_CACHE.get(key)
    if cached is None:
        base, meta = _render_preferences_structure_bgra(
            st, path=path, assets_dir=assets_dir
        )
        if len(_PREFS_STRUCTURE_CACHE) >= _PREFS_STRUCTURE_CACHE_MAX:
            # Drop oldest insertion.
            oldest = next(iter(_PREFS_STRUCTURE_CACHE))
            _PREFS_STRUCTURE_CACHE.pop(oldest, None)
        _PREFS_STRUCTURE_CACHE[key] = (base, meta)
    else:
        base, meta = cached

    out = base.copy()
    np_centers = meta.get("np_centers") or {}
    volume_centers = meta.get("volume_centers") or {}
    clock_centers = meta.get("clock_centers") or {}
    svg_path_meta = meta.get("svg_path")
    if getattr(st, "preferences_live_content", False) and isinstance(
        svg_path_meta, Path
    ):
        _draw_preferences_posters_bgra(out, st, svg_path=svg_path_meta)
    elif isinstance(svg_path_meta, Path):
        _stamp_preferences_artwork_mask(st, svg_path_meta)
    if isinstance(np_centers, dict) and np_centers:
        _draw_preferences_circular_now_playing_bgra(out, np_centers, st)
    if isinstance(volume_centers, dict) and volume_centers:
        _draw_preferences_volume_bgra(out, volume_centers, st)
    if isinstance(clock_centers, dict) and clock_centers:
        _draw_preferences_clock_digitals_bgra(out, clock_centers)
    if getattr(st, "preferences_live_content", False):
        _draw_preferences_cast_bgra(out, st)
        _draw_preferences_status_bar_bgra(out, st)
        _draw_preferences_track_titles_bgra(out, st)
    return out


def clear_preferences_render_caches() -> None:
    """Drop prefs structure / plate caches (theme asset reload, tests)."""
    _PREFS_STRUCTURE_CACHE.clear()
    _PREFS_DIMMED_BG_CACHE.clear()
    _PREFS_POSTER_PATCH_CACHE.clear()
    _COLOR_BTN_IMAGE_CACHE.clear()
    _sharp_text_patch.cache_clear()


__all__ = [
    "DEFAULT_MUSIC_ZONE_WIDGETS",
    "DEFAULT_ZONE_WIDGETS",
    "NP_ZONE_LAYOUT_GENERATION",
    "ZONE_WIDGET_CATALOG",
    "apply_preferences_svg_state",
    "default_preferences_svg_path",
    "ensure_now_playing_layout_defaults",
    "preferences_widget_focus_ring",
    "preferences_zone_focus_ring",
    "read_np_header_clock",
    "read_now_playing_zone_widgets",
    "render_preferences_settings_bgra",
    "write_np_header_clock",
    "write_now_playing_zone_widgets",
    "zone0_date_align",
]
