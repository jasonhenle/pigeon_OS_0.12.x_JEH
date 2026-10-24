"""
PigeonOS 0.11 zoned now-playing skin (1280×800).

Portrait widgets live in ``pigeonAssets/nowPlaying/widget_np_01-02-03_*.svg``
and are placed into zones 1–3. 16×9 poster art uses ``widget_np_06_16x9`` /
``widget_np_07_16x9`` across zones 6 (1+2) or 7 (2+3). Dynamic layers (cast,
clock digital, volume pie, poster/album art, pause play) are drawn on top
with Pillow / OpenCV.
"""

from __future__ import annotations

import copy
import io
import math
import os
import re
import threading
import time
import weakref
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pigeon.compositing import (
    alpha_blend_bgra_over_bgr,
    blend_bgra_over_bgr_u8,
    cv_resize_interp,
    premultiply_bgra_on_black,
)
from pigeon.design import DESIGN_H, DESIGN_W
from pigeon.pigeon_locale import pigeon_now
from pigeon.np_zone_layout import (
    apply_connection_fallbacks,
    effective_zone_widgets,
    layout_is_fullscreen_clock,
    zone_clock_hides_header,
)
from pigeon.np_layout import (
    CAST_ACTOR_SIZE_PX,
    CAST_CHAR_SIZE_PX,
    CAST_LOCAL_ROWS,
    CAST_NAMES_PER_ZONE,
    CAST_STRIP_STACK_GAP_PX,
    CAST_VIEW_H,
    CAST_VIEW_W,
    CLOCK_DAY_LOCAL,
    CLOCK_DIGITAL_LOCAL,
    CLOCK_DIGITAL_NUDGE,
    CLOCK_DIGITAL_SIZE_PX,
    CLOCK_HEADER_SIZE_PX,
    CLOCK_LOCAL_CX,
    CLOCK_LOCAL_CY,
    CLOCK_MONTH_DATE_LOCAL,
    CLOCK_VIEW_H,
    CLOCK_VIEW_W,
    DEFAULT_16X9_POSTER_ZONE,
    NOW_PLAYING_ZONES,
    ZONE11,
    NP_HEADER_CLOCK_SIZE_PX,
    NP_ZONE6_ART_MIN_TOP_PX,
    NowPlayingZone,
    POSTER_1X1_LOCAL,
    POSTER_16X9_LOCAL,
    POSTER_16X9_VIEW_H,
    POSTER_16X9_VIEW_W,
    POSTER_2X3_LOCAL,
    STATUS_BAR_ELAPSED_LOCAL,
    STATUS_BAR_HANDOFF_S,
    STATUS_BAR_REMAINING_LOCAL,
    STATUS_BAR_SERVICE_LOCAL,
    STATUS_BAR_TIME_SIZE_PX,
    STATUS_BAR_TRACK,
    STATUS_BAR_VIEW_H,
    STATUS_BAR_VIEW_W,
    STATUS_BAR_VIEW_Y0,
    TT_COUNTDOWN_16X9_VIEW_H,
    TT_COUNTDOWN_16X9_VIEW_W,
    TT_COUNTDOWN_16X9_WIDGET,
    TT_COUNTDOWN_TEXT_SIZE_PX,
    TT_COUNTDOWN_VIEW_H,
    TT_COUNTDOWN_VIEW_W,
    VOLUME_FORMAT_SIZE_PX,
    VOLUME_INNER_R,
    VOLUME_LOCAL_CX,
    VOLUME_LOCAL_CY,
    VOLUME_OUTER_R,
    VOLUME_VIEW_H,
    VOLUME_VIEW_W,
    WIDGET_FILENAMES,
    YOUTUBE_ZONE_WIDGETS,
    canonical_zone_widget,
    cast_names_for_zone,
    design_rect_from_local,
    design_xy_from_local,
    is_status_bar_widget,
    now_playing_header_clock_text,
    header_clock_baseline_y,
    header_clock_center_x,
    header_trt_ink_box,
    status_bar_elapsed_left_x,
    status_bar_elapsed_opacity,
    status_bar_handoff_alphas,
    status_bar_service_has_room,
    apply_tt_countdown_16x9_override,
    strip_cast_columns,
    tabular_time_layout,
    tt_countdown_16x9_content_lift,
    tt_countdown_16x9_time_anchor,
    tt_countdown_16x9_tt_box,
    tt_countdown_16x9_tt_is_portrait,
    tt_countdown_16x9_zone,
    zone6_span_widget,
    tt_countdown_centered_art_rect,
    TT_COUNTDOWN_BG_PAD,
    tt_countdown_portrait_content_lift,
    layout_shows_tt_countdown_and_volume,
    tt_countdown_volume_align_dy,
    tt_countdown_time_anchor,
    tt_countdown_tt_box,
    wants_16x9_poster,
    widget_filename,
    widget_shimmer_phase,
    WIDGET_SHIMMER_BAND_FRAC,
    WIDGET_SHIMMER_OPACITY,
    WIDGET_SHIMMER_RADIUS,
)
from pigeon.font_paths import (
    resolve_digital7_font,
    resolve_ui_font_extrabold,
    resolve_ui_font_extrabold_italic,
    resolve_ui_font_light_italic,
    resolve_ui_font_medium_italic,
    resolve_ui_font_semibold,
    resolve_ui_font_semibold_italic,
)
from pigeon.widgets.playback_overlay import (
    _receiver_volume_display_line,
    volume_fraction_from_display_line,
    volume_widget_format_label,
    volume_widget_value_text,
)
from pigeon.widgets.view_circles_theme import (  # noqa: F401  (re-exported for existing importers)
    _CLOCK_TICK_OFF_HEX,
    _COLOR_ACCENT_BGR,
    _COLOR_BG_HEX,
    _COLOR_BUTTON_BGR,
    _COLOR_CENTER_BLACK_BGR,
    _COLOR_CENTER_BLACK_HEX,
    _COLOR_CHROME_BGR,
    _COLOR_CHROME_RGB,
    _COLOR_UNFILLED_BGR,
    _COLOR_UNFILLED_HEX,
    _COLOR_UNFILLED_RGB,
    _COLOR_UNPLAYED_BGR,
    _NpTheme,
    _VOLUME_CONTAINER_BGR,
    _darken_hex,
    _hex_to_bgr,
    _look_chrome_bgr,
    _look_chrome_hex,
    _look_chrome_rgb,
    _look_ink_rgb,
    _look_is_bright,
    _visible_on_dark_hex,
    _zone_clock_center_const,
    _zone_spec,
    np_theme_from_settings,
)
from pigeon.widgets.view_circles_draw import (  # noqa: F401  (re-exported for existing importers)
    NP_PIGEON_LOGO_FILENAME,
    ZONE4_VISUALIZER_WIDGET,
    ZONE6_VISUALIZER_WIDGET,
    _ACCENT_OPACITY,
    _ACCENT_STROKE_OPACITY,
    _ACCENT_STROKE_PX,
    _CANDY_STEPS,
    _CANDY_U_CACHE,
    _RING_INNER_R,
    _RING_OUTER_R,
    _ROUND_END_CAP_SCALE,
    _TT_ITALIC_SHEAR,
    _WIDGET_LABEL_BASELINE_GAP_PX,
    _ZONE4_SUBTITLE_TOP_FRAC,
    _add_round_sector_end,
    _black_rounded_plate,
    _candy_stripe_patch_bgra,
    _candy_stripe_step_bgra,
    _cast_line_patch,
    _draw_circle_pair,
    _draw_filled_circle_bgra,
    _draw_progress_ring,
    _draw_rounded_bar_bgra,
    _draw_shimmer_rounded_rect,
    _draw_stacked_cast_pair,
    _fade_bgra,
    _font_bbox_top,
    _ink_crop_bgra,
    _load_digital7,
    _load_np_pigeon_logo_bgra,
    _load_sharp_extrabold,
    _load_sharp_italic,
    _load_sharp_light_italic,
    _load_sharp_medium_italic,
    _load_sharp_semibold,
    _load_sharp_semibold_italic,
    _paste_baseline_centered,
    _paste_baseline_left,
    _paste_centered,
    _paste_ink_centered,
    _paste_label_above_circle_curved,
    _paste_label_above_widget,
    _paste_left_vcenter,
    _paste_patch_bgra,
    _paste_stroke_over_blur,
    _restore_from_backdrop_abs,
    _restore_masked_region,
    _rounded_rect_mask,
    _same_source_art,
    _shear_italic_bgra,
    _shimmer_base_patch_bgra,
    _shimmer_colors_bgr,
    _shimmer_patch_bgra,
    _text_patch_digital7,
    _text_patch_font,
    _tt_countdown_time_patch,
    _weak_or_none,
    _zone4_title_xywh,
    annular_sector_mask,
    zone4_visualizer_rect,
)
from pigeon.widgets.view_circles_svg import (  # noqa: F401  (re-exported for existing importers)
    SVG_NS,
    _CLOCK_EXTERIOR_ACCENT_R,
    _CLOCK_INTERIOR_ACCENT_R,
    _CLOCK_MIDDLE_ACCENT_R,
    _CLOCK_MINUTE_TICK_OPACITY,
    _FORCE_ANALOG_CLOCK,
    _HOUR_FACE_NAMES,
    _accent_circle_r,
    _annulus_wedge_path_d,
    _apply_clock_accent_fills,
    _apply_clock_black_rings,
    _apply_clock_ticks,
    _apply_exterior_seconds_fill,
    _apply_standalone_clock_ticks,
    _circle_cx_cy_r,
    _clear_text_content,
    _clock_accent_key,
    _clock_group_for_zone,
    _clock_include_digital_time,
    _clock_widget_is_analog,
    _detach_clock_tick_groups,
    _detach_element,
    _evenodd_ring_d,
    _find_by_id,
    _find_by_key,
    _find_direct_child_by_key,
    _fix_seconds_08_label,
    _hours_group,
    _iter_named_children,
    _layer_key,
    _local_tag,
    _minutes_group,
    _paint_seconds_ticks_alternating,
    _place_in_group,
    _punch_clock_open_ring_white,
    _raise_clock_tick_groups,
    _raise_in_group,
    _remove_by_key,
    _remove_element_by_id,
    _resolve_hour_face_el,
    _resolve_seconds_el,
    _seconds_alternate_colors,
    _seconds_group,
    _seconds_wedge_path_d,
    _set_tick_paint,
    _svg_parent,
    _zone_clock_center,
    _zone_volume_center,
)
from pigeon.widgets.view_circles_text import (  # noqa: F401  (re-exported for existing importers)
    _VOLUME_SIZE_REFERENCE_TEXT,
    _VOLUME_TEXT_INNER_FIT,
    _ZONE6_VOLUME_MARGIN_PX,
    _clock_date_baseline_y,
    _disc_clock_ink_h,
    _disc_clock_patch,
    _format_zone0_date,
    _ordinal_day,
    _volume_audio_cfg_baseline_y,
    _volume_input_patch,
    _volume_readout_patch,
    _volume_readout_size_px,
    _zone0_date_align,
    _zone3_clock_day_baseline_y,
    _zone6_volume_font_px,
)
from pigeon.widgets.view_circles_raster import (  # noqa: F401  (re-exported for existing importers)
    _SVG_H,
    _SVG_TEMPLATE_CACHE,
    _SVG_W,
    _decanvas_white_bgra,
    _rasterize_svg_tree,
    _scale_raster_to_design,
    _svg_tree_from_path,
    _svg_viewbox_wh,
)
from pigeon.widgets.view_circles_state import (  # noqa: F401  (re-exported for existing importers)
    ViewCirclesState,
    _CONTENT_MODE_MUSIC,
    _CONTENT_MODE_VIDEO,
    _normalize_content_mode,
)
from pigeon.widgets.view_circles_timecode import (  # noqa: F401  (re-exported for existing importers)
    _draw_volume_selected_pie,
    _header_digital7_size_px,
    _header_trt_size_px,
    _matching_hhmm_patch,
    format_countdown_timecode,
    format_status_bar_timecode,
)

ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")


# Now-playing clock / volume / bar use the most saturated TMDb-backdrop hue.
# Menus still read ``settings_ui_colors``. Set False to restore settings UI on NP.
_NP_UI_FROM_TT = True
# No TMDb poster: wash the page in the UI color (False → plain black, as before).
_NP_NO_POSTER_UI_WASH = True


# Zone centers (design coords) — clock/volume disc in each portrait slot.
_ZONE1_CX, _ZONE1_CY = _zone_clock_center_const(1)
_ZONE2_CX, _ZONE2_CY = _zone_clock_center_const(2)
_ZONE3_CX, _ZONE3_CY = _zone_clock_center_const(3)


# Zone2 poster 2×3 / album 1×1.
# SVG ``poster_accent-2`` path bbox ≈ 200×300 @ (300.7, 14.5); placed demo image is
# 780×1170 × 0.26 (=202.8×304.2) @ translate(300.52, 14.47). Overfill slightly so
# cover-fit art seats under the accent stroke without a gap.
_POSTER_VIDEO_X, _POSTER_VIDEO_Y, _POSTER_VIDEO_W, _POSTER_VIDEO_H, _POSTER_VIDEO_RX = (
    int(round(POSTER_2X3_LOCAL[0])),
    int(round(POSTER_2X3_LOCAL[1])),
    int(round(POSTER_2X3_LOCAL[2])),
    int(round(POSTER_2X3_LOCAL[3])),
    int(round(POSTER_2X3_LOCAL[4])),
)
# Dimmed minute/second ticks: red mixed with 50% black → dark red; current stays full red.
_TICK_DIM_FILL = "#800000"
_TICK_ACTIVE_FILL = "red"

_POSTER_MUSIC_X, _POSTER_MUSIC_Y, _POSTER_MUSIC_W, _POSTER_MUSIC_H, _POSTER_MUSIC_RX = (
    int(round(POSTER_1X1_LOCAL[0])),
    int(round(POSTER_1X1_LOCAL[1])),
    int(round(POSTER_1X1_LOCAL[2])),
    int(round(POSTER_1X1_LOCAL[3])),
    int(round(POSTER_1X1_LOCAL[4])),
)

_ARTWORK_BG_OPACITY = 0.40
# No-poster UI-color wash: opacity over black (darker than the poster blur), and a
# luma ceiling (light mode treats darker as wash).
_UI_WASH_OPACITY = 0.08
_UI_WASH_MAX_LUMA = 60.0
_ARTWORK_BG_BLUR_DOWNSCALE = 4
_ARTWORK_BG_BLUR_SIGMA = 6.0


# While TMDb is fetching (``searching``), clock ticks + volume race ahead of wall time.
_CLOCK_SPIN_SEC_RATE = 48.0  # second-ticks per real second (~1.25s / full ring)
_CLOCK_SPIN_MIN_RATE = 16.0  # minute-ticks per real second
_CLOCK_SPIN_HOUR_RATE = 6.0  # hour faces per real second
_CLOCK_SPIN_VOL_RATE = 1.8  # volume-ring revolutions per real second

_CHROME_FILL_OPACITY = 0.12
_BUTTON_FILL_OPACITY = 0.35
_POSTER_PAUSED_DIM = 0.30

_POSTER_X = _POSTER_VIDEO_X
_POSTER_Y = _POSTER_VIDEO_Y
_POSTER_W = _POSTER_VIDEO_W
_POSTER_H = _POSTER_VIDEO_H
_POSTER_RX = _POSTER_VIDEO_RX


# Zone5 status bar (SVG paths ≈ 76–724, y≈391, h≈40).
_BAR_L = 76
_BAR_R = 724
_BAR_T = 391
_BAR_H = 40
_BAR_RX = 8
_BAR_W = _BAR_R - _BAR_L
_CTI_W = 8
_CTI_OVERHANG_TOP = 0
_CTI_OVERHANG_BOTTOM = 0
_CTI_H = _BAR_H + _CTI_OVERHANG_TOP + _CTI_OVERHANG_BOTTOM
_CTI_Y = _BAR_T - _CTI_OVERHANG_TOP
_MIN_ELAPSED_W = 4
_ELAPSED_REMAINING_GAP_PX = 16
_SERVICE_FADE_PROGRESS = 0.12

# Volume readout centered in volume_container; audio config sits above the ring.
_VOLUME_CX = _ZONE3_CX
_AUDIO_CFG_CX = _ZONE3_CX
_AUDIO_CFG_SIZE_PX = VOLUME_FORMAT_SIZE_PX
_CLOCK_DIGITAL_SIZE = CLOCK_DIGITAL_SIZE_PX
_CLOCK_DATE_SIZE_PX = 32
# Gap between the disc volume number and the HH:MM sitting under it.
_VOLUME_INPUT_GAP_PX = 6.0
# Zone-3 volume disc carrying the digital clock above the number: the number is
# fitted to this fraction of the disc radius, and the clock/number pair is
# centered together with this gap between them.
_DISC_CLOCK_NUMBER_FIT = 0.80
_DISC_CLOCK_GAP_PX = 12.0

# Zone4 cast columns (center x, actor baseline y, character baseline y) — SVG geometry.
_CAST_COLS_Z4: tuple[tuple[float, float, float], ...] = (
    (_ZONE1_CX, 351.08, 369.08),
    (_ZONE2_CX, 351.08, 369.08),
    (_ZONE3_CX, 351.08, 369.08),
)
# Zone5 expanded cast strip (same columns, lower baselines).
_CAST_COLS_Z5: tuple[tuple[float, float, float], ...] = (
    (_ZONE1_CX, 405.73, 423.61),
    (_ZONE2_CX, 406.08, 423.61),
    (_ZONE3_CX, 405.73, 423.61),
)
_CAST_COLS = _CAST_COLS_Z4  # back-compat alias
_CAST_COL_W = 200
_CAST_TEXT_PAD = 2

_ELAPSED_TEXT_Y = 460
_REMAINING_TEXT_Y = 460
_SERVICE_TEXT_X = 28
_SERVICE_TEXT_Y = 460
_PAUSED_TEXT_CX = 400.0
_PAUSED_TEXT_CY = 411.0


# Canonical names (or id prefixes) stripped / hidden before rasterize (demo text / images).
_STRIP_OR_HIDE_NAMES: tuple[str, ...] = (
    "zone1_clock_digital_text",
    "zone2_clock_digital_text",
    "zone3_clock_digital_text",
    "zone3_volume_text",
    "zone3_voume_audio_config_text",
    "zone2_volume_text",
    "zone2_voume_audio_config_text",
    "zone1_volume_text",
    "zone1_voume_audio_config_text",
    "zone1_voume_audio_config_text-2",
    "zone5_now_playing_remaining_text",
    "zone5_now_playing_elapsed_text",
    "zone5_now_playing_service_text",
    "zone5_now_playing_paused_text",
    "zone5_now_playing_remaining_icon",
    "zone5_now_playing_elapsed_icon",
    "zone5_now_playing_cti_icon",
    "zone4_actor1_text",
    "zone4_character1_text",
    "zone4_actor2_text",
    "zone4_character2_text",
    "zone4_actor3_text",
    "zone4_character3_text",
    "zone0_date_left_text",
    "zone0_date_center_text",
    "zone0_date_right_text",
    "poster_tmdb",
    "zone3_volume_deselected_buton",
    "zone3_volume_selected_button",
    "zone3_volume_container",
    "zone2_volume_deselected_buton",
    "zone2_volume_selected_button",
    "zone2_volume_container",
    "zone1_volume_deselected_buton",
    "zone1_volume_selected_button",
    "zone1_volume_container",
)

# Legacy zone0 date header (removed from live NP; prefs still hides the SVG group).
_ZONE0_DATE_ALIGN_DEFAULT = "left"
_ZONE0_DATE_SIZE_PX = _CLOCK_DATE_SIZE_PX
_ZONE0_DATE_BASELINE_Y = 19.94
_ZONE0_DATE_CENTER_X: dict[str, float] = {
    "left": _ZONE1_CX,
    "center": _ZONE2_CX,
    "right": _ZONE3_CX,
}


# Zone 3 shows the volume widget this long after each adjustment, then
# returns to the saved assignment. Each new tweak restarts the hold.
ZONE3_VOLUME_TAKEOVER_S = 7.0


def default_view_circles_svg_path(
    assets_dir: Path | str | None = None,
    *,
    content_mode: str = _CONTENT_MODE_VIDEO,
) -> Path:
    """Directory of per-widget now-playing SVGs (legacy env still accepted)."""
    del content_mode
    env = (
        os.environ.get("PIGEON_VIEW_CIRCLES_SVG", "").strip()
        or os.environ.get("PIGEON_NOW_PLAYING_SVG", "").strip()
    )
    if env:
        p = Path(env).expanduser().resolve()
        return p.parent if p.is_file() else p
    if assets_dir is not None:
        return Path(assets_dir) / "nowPlaying"
    pigeon_root = Path(__file__).resolve().parents[3]
    return pigeon_root / "pigeonAssets" / "nowPlaying"


def _poster_geometry(
    content_mode: str,
    *,
    zone: int = 2,
) -> tuple[int, int, int, int, int]:
    z = _zone_spec(zone)
    if int(zone) in (6, 7):
        return design_rect_from_local(
            z,
            POSTER_16X9_LOCAL,
            view_w=POSTER_16X9_VIEW_W,
            view_h=POSTER_16X9_VIEW_H,
        )
    local = (
        POSTER_1X1_LOCAL
        if _normalize_content_mode(content_mode) == _CONTENT_MODE_MUSIC
        else POSTER_2X3_LOCAL
    )
    return design_rect_from_local(z, local)


def _zone_for_widget(assignments: tuple[str, str, str, str, str], widget: str) -> int | None:
    for i, name in enumerate(assignments):
        if name == widget:
            return i + 1
    return None


def _cover_fit_bgra(src: np.ndarray, tw: int, th: int) -> np.ndarray:
    if src is None or src.size == 0 or tw < 1 or th < 1:
        return np.zeros((max(1, th), max(1, tw), 4), dtype=np.uint8)
    arr = src
    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGRA)
    elif arr.ndim == 3 and arr.shape[2] == 3:
        arr = cv2.cvtColor(arr, cv2.COLOR_BGR2BGRA)
    sh, sw = arr.shape[:2]
    if sh < 1 or sw < 1:
        return np.zeros((th, tw, 4), dtype=np.uint8)
    scale = max(tw / float(sw), th / float(sh))
    nw = max(1, int(round(sw * scale)))
    nh = max(1, int(round(sh * scale)))
    resized = cv2.resize(
        arr,
        (nw, nh),
        interpolation=cv_resize_interp(sw, sh, nw, nh),
    )
    x0 = max(0, (nw - tw) // 2)
    y0 = max(0, (nh - th) // 2)
    crop = resized[y0 : y0 + th, x0 : x0 + tw]
    if crop.shape[0] != th or crop.shape[1] != tw:
        crop = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_AREA)
    return crop


def _build_artwork_blur_bgra(src: np.ndarray) -> np.ndarray:
    tw, th = int(DESIGN_W), int(DESIGN_H)
    cover = _cover_fit_bgra(src, tw, th)
    dw = max(1, tw // _ARTWORK_BG_BLUR_DOWNSCALE)
    dh = max(1, th // _ARTWORK_BG_BLUR_DOWNSCALE)
    small = cv2.resize(cover, (dw, dh), interpolation=cv2.INTER_AREA)
    bgr = small[:, :, :3]
    sigma = float(_ARTWORK_BG_BLUR_SIGMA)
    k = max(3, int(round(sigma * 2)) | 1)
    blurred = cv2.GaussianBlur(bgr, (k, k), sigmaX=sigma, sigmaY=sigma)
    up = cv2.resize(blurred, (tw, th), interpolation=cv2.INTER_LINEAR)
    out = np.zeros((th, tw, 4), dtype=np.uint8)
    out[:, :, :3] = up
    out[:, :, 3] = int(round(255.0 * _ARTWORK_BG_OPACITY))
    return out


def _default_zone_widget_assignments(
    content_mode: str | None = None,
) -> tuple[str, str, str, str, str]:
    try:
        from pigeon.np_zone_config import read_now_playing_zone_widgets

        return read_now_playing_zone_widgets(content_mode=content_mode)
    except TypeError:
        from pigeon.np_zone_config import read_now_playing_zone_widgets

        return read_now_playing_zone_widgets()
    except Exception:
        mode = str(content_mode or "").strip().lower()
        if mode == "music":
            return ("tt_countdown_16x9", "", "volume", "cast_info", "status_bar")
        return ("tt_countdown_16x9", "", "volume", "cast_info", "status_bar")


def _header_clock_enabled() -> bool:
    try:
        from pigeon.np_zone_config import read_np_header_clock

        return bool(read_np_header_clock())
    except Exception:
        return True


def _saved_zone_widgets(
    content_mode: str | None = None,
) -> tuple[str, str, str, str, str]:
    """Prefs layout; tests may stub ``_default_zone_widget_assignments`` with no args."""
    fn = _default_zone_widget_assignments
    try:
        return fn(content_mode)
    except TypeError:
        return fn()  # type: ignore[misc]


_CAST_NAMES_PER_ZONE = CAST_NAMES_PER_ZONE


_zone_clock_hides_header = zone_clock_hides_header
_layout_is_fullscreen_clock = layout_is_fullscreen_clock
_apply_connection_fallbacks = apply_connection_fallbacks


def _effective_zone_widgets(**kwargs):
    """See :func:`pigeon.np_zone_layout.effective_zone_widgets`.

    Binds the saved-layout lookup to this module's ``_saved_zone_widgets`` so
    patching ``_default_zone_widget_assignments`` here still takes effect.
    """
    return effective_zone_widgets(saved_zone_widgets=_saved_zone_widgets, **kwargs)


def configured_status_bar_zone(
    zone_widgets: tuple[str, str, str, str, str] | None = None,
) -> int | None:
    """Prefs zone that holds the status bar, ignoring live position/cast fallbacks."""
    zones = list(zone_widgets or _default_zone_widget_assignments())
    if len(zones) < 5:
        zones = list(_default_zone_widget_assignments())
    for i, name in enumerate(zones[:5]):
        key = canonical_zone_widget(i + 1, name)
        if is_status_bar_widget(key, i + 1):
            return i + 1
    return None


def settings_main_keeps_np_status_bar(
    *, show_pigeon_settings: bool, content_playing: bool
) -> bool:
    """Never: the SEARCH bar owns the bottom strip of settings_main."""
    del show_pigeon_settings, content_playing
    return False


def _zone_widget_visibility(
    *,
    content_mode: str,
    paused: bool,
    zone_widgets: tuple[str, str, str, str, str] | None = None,
) -> dict[str, bool]:
    """Zone widget on/off map from preferences (defaults: wide countdown / volume / cast / bar)."""
    mode = _normalize_content_mode(content_mode)
    is_music = mode == _CONTENT_MODE_MUSIC
    assignments = zone_widgets if zone_widgets is not None else _default_zone_widget_assignments()

    def _is(zone: int, widget: str) -> bool:
        if not (1 <= zone <= 5):
            return False
        return assignments[zone - 1] == widget

    # Poster/album: music prefers 1×1 album art; video prefers 2×3 poster.
    def _poster_on(zone: int) -> tuple[bool, bool]:
        if not _is(zone, "poster"):
            return False, False
        if is_music:
            return False, True
        return True, False

    z1_poster, z1_album = _poster_on(1)
    z2_poster, z2_album = _poster_on(2)
    z3_poster, z3_album = _poster_on(3)
    play_z1 = bool(paused) and (z1_poster or z1_album)
    play_z2 = bool(paused) and (z2_poster or z2_album)
    play_z3 = bool(paused) and (z3_poster or z3_album)
    vis = {
        # zone1
        # volume chrome is also used by circular now_playing (playback progress).
        "zone1_volume_group": _is(1, "volume") or _is(1, "now_playing"),
        "zone1_audio_levels_group": False,
        "zone1_clock_group": _is(1, "clock"),
        "zone1_poster_2x3": z1_poster,
        "zone1_album_art_1x1": z1_album,
        "zone1_cast_group": _is(1, "cast_info") and not is_music,
        "zone1_play_button": play_z1,
        # zone2
        "zone2_volume_group": _is(2, "volume") or _is(2, "now_playing"),
        "zone2_audio_levels_group": False,
        "zone2_audio_levles_gtoup": False,  # Illustrator typo id
        "zone2_clock_group": _is(2, "clock"),
        "zone2_poster_2x3": z2_poster,
        "zone2_album_art_1x1": z2_album,
        "zone2_cast_group": _is(2, "cast_info") and not is_music,
        "zone2_play_button": play_z2,
        # zone3
        "zone3_volume_group": _is(3, "volume") or _is(3, "now_playing"),
        "zone3_audio_levels_group": False,
        "zone3_clock_group": _is(3, "clock"),
        "zone3_poster_2x3": z3_poster,
        "zone3_2x3_poster_group": z3_poster,
        "zone3_album_art_1x1": z3_album,
        "zone3_cast_group": _is(3, "cast_info") and not is_music,
        "zone3_play_button": play_z3,
        # zone4 — TMDb cast strip
        "zone4_cast_group": _is(4, "cast_info") and not is_music,
        # zone5 — status bar or expanded cast
        "zone5_now_playing_group": _is(5, "now_playing") or _is(5, "status_bar"),
        "zone5_locations_group": False,
        "zone5_cast_group": _is(5, "cast_info"),
        "zone5_now_playing_paused_text": False,  # pausesaver plate lives in zone 4
        # zone0 — retired; date now lives above the clock widget
        "zone0_header_group": False,
    }
    return vis


def _apply_zone_visibility(root: ET.Element, vis: dict[str, bool]) -> None:
    for name, on in vis.items():
        if not on:
            _remove_by_key(root, name)


def _now_playing_widget_path(
    assets_dir: Path | str | None, widget_key: str, zone: int | None = None
) -> Path:
    folder = default_view_circles_svg_path(assets_dir)
    return folder / widget_filename(widget_key, zone)


def _prepare_volume_svg(root: ET.Element) -> None:
    for name in (
        "volume_selected_button",
        "volume_text",
        "volume_scale_text",
        "volume_source_text",
        "volume_format_text",
    ):
        el = _find_by_key(root, name)
        if el is not None:
            _detach_element(root, el)
    track = _find_by_key(root, "volume_deselected_buton")
    if track is not None:
        _set_tick_paint(track, color=_COLOR_UNFILLED_HEX)


def _prepare_cast_svg(root: ET.Element) -> None:
    for el in list(root.iter()):
        key = _layer_key(el)
        if key.endswith("_text") and key.startswith("cast_info_"):
            _detach_element(root, el)


def _prepare_tt_countdown_svg(root: ET.Element) -> None:
    """Drop live layers and the SVG plate. TT and countdown are Pillow; dividers are guides only."""
    for name in (
        "tt_countdown_background",
        "tmdb_tt",
        "countdown_text",
        "divider",
        "dividers",
        "top_divider",
        "left_divider",
        "right_divider",
        "horizontal_divider",
    ):
        el = _find_by_key(root, name)
        if el is not None:
            _detach_element(root, el)


def _prepare_status_bar_svg(root: ET.Element) -> None:
    """Keep remaining_icon; drop demo elapsed/text. Crop artboard to the used 130px band."""
    root.set("viewBox", f"0 {STATUS_BAR_VIEW_Y0} {STATUS_BAR_VIEW_W} {STATUS_BAR_VIEW_H}")
    root.set("width", str(int(STATUS_BAR_VIEW_W)))
    root.set("height", str(int(STATUS_BAR_VIEW_H)))
    for name in (
        "status_bar_elapsed_icon",
        "status_bar_elapsed_text",
        "status_bar_remaining_text",
        "status_bar_service_text",
        "status_bar_paused_text",
    ):
        el = _find_by_key(root, name)
        if el is not None:
            _detach_element(root, el)


_NAMED_WIDGET_CACHE: dict[tuple[object, ...], np.ndarray] = {}
_NAMED_WIDGET_CACHE_MAX = 64
_CLOCK_SECONDS_LAYERS: dict[tuple[object, ...], tuple[np.ndarray, ...]] = {}
_CLOCK_SECONDS_LAYERS_MAX = 4


def _finish_widget_raster(
    root: ET.Element,
    widget_key: str,
    *,
    dest_w: int,
    dest_h: int,
    view_h: float | None = None,
) -> np.ndarray:
    vh = CLOCK_VIEW_H if view_h is None else float(view_h)
    if widget_key == "clock" and vh != CLOCK_VIEW_H:
        # Taller artboard: the outer ring's stroke is tangent to the bottom edge.
        root.set("viewBox", f"0 0 {CLOCK_VIEW_W:g} {vh:.4f}")
    bgra = _rasterize_svg_tree(root, dest_w=dest_w, dest_h=dest_h)
    bgra = _decanvas_white_bgra(bgra)
    if widget_key == "clock":
        bgra = _punch_clock_open_ring_white(bgra, view_h=vh)
    return bgra


def _clock_seconds_layers(
    path: Path,
    *,
    dest_w: int,
    dest_h: int,
    theme: _NpTheme,
    odd_minute: bool,
    view_h: float = CLOCK_VIEW_H,
) -> tuple[np.ndarray, ...]:
    """Seconds-ring pixels with every tick flipped vs none, plus each pixel's angle.

    Only the outer ring (seconds ticks + accent wedge) changes within a
    minute, and only its colors depend on the minute's parity, so these are
    rasterized once per size / theme / parity.
    """
    key = (
        str(path),
        int(dest_w),
        int(dest_h),
        theme.cache_key,
        bool(odd_minute),
        round(float(view_h), 3),
    )
    hit = _CLOCK_SECONDS_LAYERS.get(key)
    if hit is not None:
        return hit
    ref = datetime(2000, 1, 1, 12, 1 if odd_minute else 2)

    def render(second: int, wedge_idx: int | None) -> np.ndarray:
        root = _svg_tree_from_path(path)
        _apply_standalone_clock_ticks(root, ref.replace(second=second), theme=theme)
        if wedge_idx is None:
            _remove_by_key(root, "clock_exterior_seconds_fill")
        else:
            _apply_exterior_seconds_fill(root, None, sec_idx=wedge_idx, theme=theme)
        return _finish_widget_raster(
            root, "clock", dest_w=dest_w, dest_h=dest_h, view_h=view_h
        )

    # Tick 60 never flips (``:00`` resets the ring), but the wedge reaches it.
    flipped = render(59, 60)
    unflipped = render(0, None)
    sx = float(dest_w) / CLOCK_VIEW_W
    sy = float(dest_h) / float(view_h)
    yy, xx = np.ogrid[:dest_h, :dest_w]
    # The seconds live on the outer ring; keep minute ticks touching its inner edge.
    on_ring = np.hypot((xx + 0.5) / sx - CLOCK_LOCAL_CX, (yy + 0.5) / sy - CLOCK_LOCAL_CY) >= (
        _CLOCK_MIDDLE_ACCENT_R - 1.0
    )
    ys, xs = np.nonzero(np.any(flipped != unflipped, axis=2) & on_ring)
    dx = xs + 0.5 - CLOCK_LOCAL_CX * sx
    dy = ys + 0.5 - CLOCK_LOCAL_CY * sy
    # Degrees clockwise from 12 o'clock, and pixels per degree at that radius.
    deg = np.degrees(np.arctan2(dx, -dy)) % 360.0
    px_per_deg = np.hypot(dx, dy) * (math.pi / 180.0)
    layers = (
        ys,
        xs,
        deg.astype(np.float32),
        px_per_deg.astype(np.float32),
        flipped[ys, xs].astype(np.float32),
        unflipped[ys, xs].astype(np.float32),
    )
    while len(_CLOCK_SECONDS_LAYERS) >= _CLOCK_SECONDS_LAYERS_MAX:
        _CLOCK_SECONDS_LAYERS.pop(next(iter(_CLOCK_SECONDS_LAYERS)))
    _CLOCK_SECONDS_LAYERS[key] = layers
    return layers


def _blend_clock_seconds(
    face: np.ndarray,
    *,
    path: Path,
    now: datetime,
    theme: _NpTheme,
    view_h: float = CLOCK_VIEW_H,
) -> np.ndarray:
    """``face`` (the clock at ``:00``) with the seconds ring advanced to ``now``."""
    h, w = face.shape[:2]
    ys, xs, deg, px_per_deg, flipped, unflipped = _clock_seconds_layers(
        path,
        dest_w=w,
        dest_h=h,
        theme=theme,
        odd_minute=bool(now.minute % 2),
        view_h=view_h,
    )
    edge = 6.0 * max(1, min(59, int(now.second)))
    # Ticks and wedge both span 12 o'clock → ``edge``; antialias both ends.
    t = np.clip(np.minimum(deg, edge - deg) * px_per_deg + 0.5, 0.0, 1.0)[:, None]
    out = face.copy()
    out[ys, xs] = (unflipped + (flipped - unflipped) * t + 0.5).astype(np.uint8)
    return out


def _rasterize_named_widget(
    *,
    assets_dir: Path | str | None,
    widget_key: str,
    dest_w: int,
    dest_h: int,
    now: datetime,
    theme: _NpTheme,
    zone: int | None = None,
    include_play_overlay: bool = True,
    include_clock_ticks: bool | None = None,
    view_h: float | None = None,
) -> np.ndarray | None:
    path = _now_playing_widget_path(assets_dir, widget_key, zone)
    if not path.is_file():
        return None
    paint_ticks = widget_key == "clock" and include_clock_ticks is not False
    if paint_ticks and now.second:
        # Rasterizing the clock SVG costs ~100 ms on the Pi, enough to hitch
        # VU / visualizers if done every second. Rasterize the face once a
        # minute and blend just the seconds ring on top each second.
        face = _rasterize_named_widget(
            assets_dir=assets_dir,
            widget_key=widget_key,
            dest_w=dest_w,
            dest_h=dest_h,
            now=now.replace(second=0, microsecond=0),
            theme=theme,
            zone=zone,
            include_play_overlay=include_play_overlay,
            include_clock_ticks=include_clock_ticks,
            view_h=view_h,
        )
        if face is None:
            return None
        return _blend_clock_seconds(
            face,
            path=path,
            now=now,
            theme=theme,
            view_h=CLOCK_VIEW_H if view_h is None else view_h,
        )
    h12 = now.hour % 12
    if h12 == 0:
        h12 = 12
    cache_key = (
        str(path),
        int(dest_w),
        int(dest_h),
        int(zone) if zone is not None else -1,
        widget_key,
        theme.cache_key,
        bool(include_play_overlay),
        bool(paint_ticks),
        h12 if paint_ticks else -1,
        int(now.minute) if paint_ticks else -1,
        None if view_h is None else round(float(view_h), 3),
    )
    cached = _NAMED_WIDGET_CACHE.get(cache_key)
    if cached is not None:
        return cached
    root = _svg_tree_from_path(path)
    if widget_key == "clock":
        if paint_ticks:
            _apply_standalone_clock_ticks(root, now, theme=theme)
        else:
            _apply_clock_black_rings(root, zone=None)
            _detach_clock_tick_groups(root, zone=None)
            for name in ("clock_digital_text", "day_text", "month_date_text"):
                el = _find_by_key(root, name)
                if el is not None:
                    _clear_text_content(el)
                    _detach_element(root, el)
    elif widget_key == "volume":
        _prepare_volume_svg(root)
    elif widget_key == "cast_info":
        _prepare_cast_svg(root)
    elif widget_key in ("tt_countdown", TT_COUNTDOWN_16X9_WIDGET):
        _prepare_tt_countdown_svg(root)
    elif widget_key in ("now_playing", "status_bar"):
        _prepare_status_bar_svg(root)
    elif widget_key == "play" and not include_play_overlay:
        overlay = _find_by_key(root, "50_percent_overlay")
        if overlay is None:
            overlay = _find_by_id(root, "_50_percent_overlay")
        _detach_element(root, overlay)
    bgra = _finish_widget_raster(
        root, widget_key, dest_w=dest_w, dest_h=dest_h, view_h=view_h
    )
    while len(_NAMED_WIDGET_CACHE) >= _NAMED_WIDGET_CACHE_MAX:
        _NAMED_WIDGET_CACHE.pop(next(iter(_NAMED_WIDGET_CACHE)))
    _NAMED_WIDGET_CACHE[cache_key] = bgra
    return bgra


# Idle / paused saver (zone 9 / full frame): scale of the NP analog clock. The date line
# above the disc and the ring below it are centered as a unit (see the ink extents
# below), which is what lets the face grow to ~80% of the screen height.
_SAVER_CLOCK_SCALE = 1.6
# Ink extent of the clock artboard around the disc center, in design px at scale 1:
# date line top is this far above the center, the outer ring this far below.
_SAVER_CLOCK_INK_ABOVE = 264.0
_SAVER_CLOCK_INK_BELOW = 200.0
# The outer ring's stroke is tangent to the artboard's bottom edge; the saver renders
# with this much extra artboard below so it isn't shaved flat.
_SAVER_CLOCK_PAD_BOTTOM = 4.0
_CENTERED_CLOCK_CACHE: dict[tuple[object, ...], np.ndarray] = {}
_CENTERED_CLOCK_CACHE_MAX = 2


def _draw_clock_labels_in_zone(
    out: np.ndarray,
    zone: NowPlayingZone,
    now: datetime,
    *,
    include_digital_time: bool = True,
) -> None:
    """Day / month_date / optional HH:MM for a clock placed in ``zone``."""
    sx = float(zone.w) / CLOCK_VIEW_W
    header_px = max(12, int(round(CLOCK_HEADER_SIZE_PX * sx)))
    digital_px = max(12, int(round(CLOCK_DIGITAL_SIZE_PX * sx)))
    day_x, day_y = design_xy_from_local(
        zone,
        CLOCK_DAY_LOCAL[0],
        CLOCK_DAY_LOCAL[1],
        view_w=CLOCK_VIEW_W,
        view_h=CLOCK_VIEW_H,
    )
    month_x, month_y = design_xy_from_local(
        zone,
        CLOCK_MONTH_DATE_LOCAL[0],
        CLOCK_MONTH_DATE_LOCAL[1],
        view_w=CLOCK_VIEW_W,
        view_h=CLOCK_VIEW_H,
    )
    zx, zy, zw, zh = zone.xywh
    cx = float(zx) + CLOCK_DIGITAL_LOCAL[0] * (float(zw) / CLOCK_VIEW_W)
    cy = float(zy) + CLOCK_DIGITAL_LOCAL[1] * (float(zh) / CLOCK_VIEW_H)
    day_label = now.strftime("%A")
    month_label = f"{now.strftime('%b')} {int(now.day)}"
    day_max_w = max(40, int(round(month_x - day_x - 8.0)))
    font_day = _load_sharp_extrabold(header_px)
    day_patch, dw, _dh = _text_patch_font(
        day_label, font=font_day, fill_rgb=_look_ink_rgb()
    )
    if dw > day_max_w:
        for size in range(header_px - 2, 18, -2):
            font_day = _load_sharp_extrabold(size)
            day_patch, dw, _dh = _text_patch_font(
                day_label, font=font_day, fill_rgb=_look_ink_rgb()
            )
            if dw <= day_max_w:
                break
    _paste_baseline_left(
        out,
        day_patch,
        day_x,
        day_y,
        bbox_top=_font_bbox_top(day_label, font_day),
    )
    font_month = _load_sharp_semibold(header_px)
    month_patch, _mw, _mh = _text_patch_font(
        month_label, font=font_month, fill_rgb=_look_ink_rgb()
    )
    _paste_baseline_left(
        out,
        month_patch,
        month_x,
        month_y,
        bbox_top=_font_bbox_top(month_label, font_month),
    )
    if not include_digital_time:
        return
    time_p = _ink_crop_bgra(
        _matching_hhmm_patch(
            _clock_hhmm(now), size_px=digital_px, fill_rgb=_look_ink_rgb()
        )
    )
    nudge_x = CLOCK_DIGITAL_NUDGE[0] * sx
    nudge_y = CLOCK_DIGITAL_NUDGE[1] * (float(zh) / CLOCK_VIEW_H)
    _paste_centered(out, time_p, cx + nudge_x, cy + nudge_y)


def render_centered_clock_widget_bgra(
    *,
    layer_opacity: float = 1.0,
    assets_dir: Path | str | None = None,
    now: datetime | None = None,
    scale: float | None = None,
) -> np.ndarray:
    """Full-frame BGRA: NP clock widget centered (analog idle / zone 9)."""
    from pigeon.widgets.clock_calendar import _resolve_display_time

    when = now if now is not None else _resolve_display_time()
    th = np_theme_from_settings()
    s = float(_SAVER_CLOCK_SCALE if scale is None else scale)
    s = max(0.5, min(2.0, s))
    o = max(0.0, min(1.0, float(layer_opacity)))
    cache_key = (
        when.year,
        when.month,
        when.day,
        when.hour,
        when.minute,
        when.second,
        round(s, 3),
        round(o, 3),
        th.cache_key,
        bool(_clock_widget_is_analog()),
        str(assets_dir or ""),
    )
    hit = _CENTERED_CLOCK_CACHE.get(cache_key)
    if hit is not None:
        return hit
    z1 = NOW_PLAYING_ZONES[1]
    dest_w = max(64, int(round(float(z1.w) * s)))
    dest_h = max(64, int(round(float(z1.h) * s)))
    # Horizontally center the disc (not the artboard) on the design canvas.
    sx = float(dest_w) / CLOCK_VIEW_W
    sy = float(dest_h) / CLOCK_VIEW_H
    x = int(round(DESIGN_W * 0.5 - CLOCK_LOCAL_CX * sx))
    # Center the whole ink (date + ring), not the disc, so the date clears the top edge.
    ink_shift = (_SAVER_CLOCK_INK_ABOVE - _SAVER_CLOCK_INK_BELOW) * 0.5 * s
    y = int(round(DESIGN_H * 0.5 + ink_shift - CLOCK_LOCAL_CY * sy))
    zone = NowPlayingZone(9, float(x), float(y), float(dest_w), float(dest_h), ())
    out = np.zeros((int(DESIGN_H), int(DESIGN_W), 4), dtype=np.uint8)
    try:
        patch = _rasterize_named_widget(
            assets_dir=assets_dir,
            widget_key="clock",
            dest_w=dest_w,
            dest_h=int(round(dest_h * (CLOCK_VIEW_H + _SAVER_CLOCK_PAD_BOTTOM) / CLOCK_VIEW_H)),
            now=when,
            theme=th,
            zone=None,
            view_h=CLOCK_VIEW_H + _SAVER_CLOCK_PAD_BOTTOM,
        )
    except Exception:
        patch = None
    if patch is not None and patch.size > 0:
        _paste_patch_bgra(out, patch, x, y)
    _draw_clock_labels_in_zone(
        out, zone, when, include_digital_time=_clock_include_digital_time()
    )
    if o < 0.999:
        faded = out.astype(np.float32)
        faded[:, :, 3] *= o
        out = np.clip(faded, 0, 255).astype(np.uint8)
    if len(_CENTERED_CLOCK_CACHE) >= _CENTERED_CLOCK_CACHE_MAX:
        _CENTERED_CLOCK_CACHE.clear()
    _CENTERED_CLOCK_CACHE[cache_key] = out
    return out


def apply_view_circles_svg_state(
    root: ET.Element,
    *,
    content_mode: str = _CONTENT_MODE_VIDEO,
    paused: bool = False,
    now: datetime | None = None,
    active_clock_zone: int = 1,
    theme: _NpTheme | None = None,
    zone_widgets: tuple[str, str, str, str, str] | None = None,
) -> None:
    mode = _normalize_content_mode(content_mode)
    th = theme or np_theme_from_settings()
    root.set("style", "background:transparent")
    _remove_element_by_id(root, "background")
    _remove_element_by_id(root, "background-2")

    vis = _zone_widget_visibility(
        content_mode=mode, paused=paused, zone_widgets=zone_widgets
    )
    _apply_zone_visibility(root, vis)

    # Play triangle: match chrome grey used for icons / unplayed bar (#939393).
    for z in (1, 2, 3):
        play = _find_by_key(root, f"zone{z}_play_button")
        if play is not None:
            _set_tick_paint(play, color=_look_chrome_hex())

    # Remove demo text / embedded images / volume pies we redraw (keep tick paths).
    for name in _STRIP_OR_HIDE_NAMES:
        _remove_by_key(root, name)
    # Remove poster_tmdb images (Illustrator -N copies) and unused cast demo text.
    # Also strip audio-levels channel labels (Digital-7 redrawn after rasterize).
    pending: list[ET.Element] = []
    for el in root.iter():
        key = _layer_key(el)
        eid = el.get("id") or ""
        if key == "poster_tmdb" or eid.startswith("poster_tmdb"):
            pending.append(el)
            continue
        if key.endswith("_text") and any(
            key.startswith(p)
            for p in (
                "zone1_actor",
                "zone1_character",
                "zone2_actor",
                "zone2_character",
                "zone3_actor",
                "zone3_character",
                "zone4_actor",
                "zone4_character",
                "zone5_actor",
                "zone5_character",
                "zone5character",
            )
        ):
            pending.append(el)
            continue
        if "voume_audio_config" in key or key.endswith("audio_config_text"):
            pending.append(el)
            continue
        if el.tag.endswith("text") and "audio_levels" in key:
            pending.append(el)
    for el in pending:
        _detach_element(root, el)

    dt = now if now is not None else pigeon_now()
    # Exterior (button) under middle (button); active zone adds accent seconds wedge.
    _apply_clock_accent_fills(root, theme=th)
    # Audio-levels channel bars follow settings UI color (LFE stays chrome).
    for zone in (1, 2, 3):
        group = None
        if vis.get(f"zone{zone}_audio_levels_group", False):
            group = _find_by_key(root, f"zone{zone}_audio_levels_group")
        if group is None and zone == 2 and vis.get("zone2_audio_levles_gtoup", False):
            group = _find_by_key(root, "zone2_audio_levles_gtoup")
        if group is None:
            continue
        for el in group.iter():
            key = _layer_key(el)
            if "lfe" in key.lower():
                continue
            if "audio_levels" in key and "button" in key and not key.endswith("_text"):
                _set_tick_paint(el, color=th.ui_hex)
    # Drive ticks for whichever clock zone is visible (preferences may move it).
    clock_zone = int(active_clock_zone)
    for z in (1, 2, 3):
        if vis.get(f"zone{z}_clock_group", False):
            clock_zone = z
            break
    if vis.get(f"zone{clock_zone}_clock_group", False):
        if _clock_widget_is_analog():
            _apply_clock_ticks(root, clock_zone, dt, theme=th)
        else:
            _apply_clock_black_rings(root, zone=clock_zone)
            _detach_clock_tick_groups(root, zone=clock_zone)
    # Clear any leftover digital clock text nodes.
    for z in (1, 2, 3):
        _clear_text_content(_find_by_key(root, f"zone{z}_clock_digital_text"))


def render_view_circles_svg_base_bgra(
    *,
    svg_path: Path | str | None = None,
    assets_dir: Path | str | None = None,
    content_mode: str = _CONTENT_MODE_VIDEO,
    paused: bool = False,
    now: datetime | None = None,
    theme: _NpTheme | None = None,
    zone_widgets: tuple[str, str, str, str, str] | None = None,
) -> np.ndarray:
    del svg_path, paused, content_mode
    th = theme or np_theme_from_settings()
    assignments = zone_widgets or _default_zone_widget_assignments()
    out = np.zeros((int(DESIGN_H), int(DESIGN_W), 4), dtype=np.uint8)
    now_dt = now if now is not None else pigeon_now()
    chrome_keys = {
        "clock": "clock",
        "volume": "volume",
        "cast_info": "cast_info",
        "tt_countdown": "tt_countdown",
    }
    for z in (1, 2, 3, 4, 5):
        key = str(assignments[z - 1] if z <= len(assignments) else "").strip()
        if key in (
            "cast_info",
            "now_playing",
            "status_bar",
            "tt_countdown",
            TT_COUNTDOWN_16X9_WIDGET,
            "clock_saver_volume",
            "weather",
        ):
            # Cast, bar, TT, and weather are Pillow.
            continue
        if zone6_span_widget(assignments) == "clock" and z in (1, 2) and key == "clock":
            # Wide zone-6 clock saver face replaces the portrait disc.
            continue
        widget_key = chrome_keys.get(key)
        if not widget_key:
            continue
        zone = _zone_spec(z)
        zx, zy, zw, zh = zone.xywh
        try:
            patch = _rasterize_named_widget(
                assets_dir=assets_dir,
                widget_key=widget_key,
                dest_w=zw,
                dest_h=zh,
                now=now_dt,
                theme=th,
                zone=z,
            )
        except Exception:
            patch = None
        if patch is None or patch.size == 0:
            continue
        _paste_patch_bgra(out, patch, zx, zy)
    return out


def _clock_hhmm(now: datetime | None = None) -> str:
    dt = now if now is not None else pigeon_now()
    try:
        from pigeon.widgets.options_settings import clock_uses_24h

        if clock_uses_24h():
            return f"{dt.hour:02d}:{dt.minute:02d}"
    except Exception:
        pass
    h12 = dt.hour % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{dt.minute:02d}"


def _fallback_base_bgra() -> np.ndarray:
    out = np.zeros((int(DESIGN_H), int(DESIGN_W), 4), dtype=np.uint8)
    out[:, :, 3] = 255
    paper = (255, 255, 255) if _look_is_bright() else (0, 0, 0)
    out[:, :, 0] = paper[2]
    out[:, :, 1] = paper[1]
    out[:, :, 2] = paper[0]
    return out


class ViewCirclesWidget:
    """Zoned now-playing layout for DisplayView.ONE (circles skin)."""

    def __init__(self, *, assets_dir: Path) -> None:
        self._assets_dir = Path(assets_dir)
        self._state = ViewCirclesState()
        self._poster_bgra: np.ndarray | None = None
        self._backdrop_bgr: np.ndarray | None = None
        self._tt_bgra: np.ndarray | None = None
        # Last caller arrays behind _poster_bgra / _tt_bgra (see _same_source_art).
        self._poster_src: weakref.ref | None = None
        self._tt_src: weakref.ref | None = None
        self._tt_theme_hex: str | None = None
        self._tt_theme_src_id: object | None = None
        self._tt_patch_cache: dict[tuple[object, ...], np.ndarray | None] = {}
        self._header_slot_patch_cache: tuple[object, ...] | None = None
        self._zone6_volume_patch: tuple[object, np.ndarray, float] | None = None
        self._input_caption_patch_cache: tuple[object, ...] | None = None
        self._cached_bgra: np.ndarray | None = None
        self._cached_sig: tuple[object, ...] | None = None
        self._static_bgr: np.ndarray | None = None
        self._ticking_under: np.ndarray | None = None
        self._ticking_under_sig: tuple[object, ...] | None = None
        self._svg_chrome_by_key: dict[tuple[object, ...], np.ndarray] = {}
        self._static_base: tuple[tuple[object, ...], np.ndarray, list] | None = None
        self._bar_overlay_layer: np.ndarray | None = None
        # Union of everything the last _draw_status_bar painted (x0, y0, x1, y1);
        # the timecodes sit below the zone box, so the zone rect alone misses them.
        self._status_bar_paint_bounds: tuple[int, int, int, int] | None = None
        self._zone4_eq = None
        self._zone4_meter = None
        self._zone6_viz = None
        # Where _overlay_ticking last stamped TT-countdown digits (x, y, w, h).
        self._tt_time_paint_rects: list[tuple[int, int, int, int]] = []
        self._artwork_blur_bgra: np.ndarray | None = None
        self._artwork_blur_poster_id: int | None = None
        self._ui_wash_cache: tuple[str, np.ndarray] | None = None
        self._search_frames: tuple[np.ndarray, ...] | None = None
        self._search_frames_tried = False
        self._last_tick_mono: float | None = None
        self._bar_handoff = 0.0
        self._bar_handoff_want = 0.0
        self._bar_handoff_inited = False
        self._bar_handoff_mono: float | None = None
        self._spin_sec_phase = 0.0
        self._spin_min_phase = 0.0
        self._spin_hour_phase = 0.0
        self._spin_vol_phase = 0.0
        self._shimmer_rects: list[tuple[int, int, int, int, int]] = []
        self._shimmer_work: np.ndarray | None = None
        # Last frame shown while TMDb was loading, and when the reveal wipe off it began.
        self._loading_snapshot: np.ndarray | None = None
        self._loading_regions: list[tuple[int, int, int, int, int]] = []
        self._loading_bar: tuple[int, int, int, int, int] | None = None
        # Reveal: pending while a worker thread builds the finished page (slow) and the
        # loading stripes keep running; then ``_reveal_t0`` runs the wipe clock.
        self._reveal_pending = False
        self._reveal_started = False
        self._reveal_ready = False
        self._reveal_failed = False
        self._reveal_gen = 0
        self._reveal_pending_mono = 0.0
        # Fast path: the loading / wipe frames kept as BGR-on-black so a frame is a few
        # slice copies instead of a full-frame alpha blend.
        self._loading_bgr: np.ndarray | None = None
        self._anim_out: np.ndarray | None = None
        self._anim_regions: dict[int, np.ndarray] = {}
        self._reveal_new_bgr: np.ndarray | None = None
        self._reveal_new_opaque = False
        self._loading_opaque = False
        self._anim_done_x = 0
        self._hold_out: np.ndarray | None = None
        self._reveal_t0: float | None = None
        self._reveal_new: np.ndarray | None = None
        self._reveal_out: np.ndarray | None = None
        self._reveal_live: np.ndarray | None = None
        self._reveal_rows: np.ndarray | None = None
        self._reveal_done_x = 0
        # ``_overlay_ticking`` result reused across loading / reveal frames.
        self._ticking_base: np.ndarray | None = None
        self._ticking_base_key: tuple[object, ...] | None = None
        self._volume_line_changed_mono = 0.0
        self._volume_takeover_until = 0.0

    @property
    def chrome_visible(self) -> bool:
        return self._state.chrome_visible

    @property
    def searching(self) -> bool:
        return bool(self._state.searching)

    @property
    def content_mode(self) -> str:
        return _normalize_content_mode(self._state.content_mode)

    def clear_cache(self, *, keep_base: bool = False) -> None:
        """Drop the rendered frame. ``keep_base`` keeps the volume-independent layers,
        which are keyed on the cache signature and so rebuild themselves on any change
        the signature sees; callers that change something it cannot see leave it False."""
        self._cached_bgra = None
        if not keep_base:
            self._static_base = None
        self._cached_sig = None
        self._static_bgr = None
        self._ticking_under = None
        self._ticking_under_sig = None
        self._header_slot_patch_cache = None
        self._input_caption_patch_cache = None

    def _clear_artwork_blur_cache(self) -> None:
        self._artwork_blur_bgra = None
        self._artwork_blur_poster_id = None

    def _reset_clock_spin_from_wall(self) -> None:
        """Seed intro spin phases from the current wall clock + volume."""
        n = pigeon_now()
        h12 = n.hour % 12
        self._spin_hour_phase = float(h12)  # 0 = 12 o'clock face
        self._spin_min_phase = float(n.minute)
        self._spin_sec_phase = float(n.second)
        self._spin_vol_phase = float(self._state.volume_fraction)

    def _clock_now_for_display(self) -> datetime:
        """Wall clock. (Intro racing-clock animation removed — real values always.)"""
        return pigeon_now()

    def _volume_fraction_for_display(self) -> float:
        if self._state.volume_muted:
            return 0.0
        return float(self._state.volume_fraction)

    def _volume_line_opacity(self, now: float | None = None) -> float:
        from pigeon.widgets.clock_saver import volume_line_fade_opacity

        t = time.monotonic() if now is None else float(now)
        return volume_line_fade_opacity(t, float(self._volume_line_changed_mono or 0.0))

    def note_volume_adjustment(self, now: float | None = None) -> None:
        """Show the volume widget in zone 3 and restart the hold timer."""
        t = time.monotonic() if now is None else float(now)
        self._volume_takeover_until = t + float(ZONE3_VOLUME_TAKEOVER_S)
        self.clear_cache(keep_base=True)

    def volume_takeover_active(self, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else float(now)
        return t < float(self._volume_takeover_until or 0.0)

    def set_now_playing_chrome_visible(self, visible: bool) -> bool:
        v = bool(visible)
        if v == self._state.chrome_visible:
            return False
        self._state.chrome_visible = v
        if v and self._state.searching:
            self._reset_clock_spin_from_wall()
            self._last_tick_mono = None
        self.clear_cache()
        return True

    def set_poster_bgra(self, poster_bgra: np.ndarray | None) -> bool:
        if poster_bgra is None:
            if self._poster_bgra is None:
                return False
            self._poster_bgra = None
            self._poster_src = None
            self._clear_artwork_blur_cache()
            self.clear_cache()
            return True
        if _same_source_art(self._poster_src, poster_bgra, self._poster_bgra):
            return False
        arr = np.asarray(poster_bgra, dtype=np.uint8)
        if self._poster_bgra is not None and self._poster_bgra.shape == arr.shape:
            if np.array_equal(self._poster_bgra, arr):
                self._poster_src = _weak_or_none(poster_bgra)
                return False
        self._poster_bgra = arr.copy()
        self._poster_src = _weak_or_none(poster_bgra)
        self._clear_artwork_blur_cache()
        self._tt_theme_src_id = None
        self.clear_cache()
        return True

    def set_tt_bgra(self, tt_bgra: np.ndarray | None) -> bool:
        """Update the cached TMDb title-treatment source art (BGRA)."""
        if tt_bgra is None:
            if self._tt_bgra is None:
                return False
            self._tt_bgra = None
            self._tt_src = None
            self._tt_theme_hex = None
            self._tt_theme_src_id = None
            self._tt_patch_cache.clear()
            self.clear_cache()
            return True
        if _same_source_art(self._tt_src, tt_bgra, self._tt_bgra):
            return False
        arr = np.asarray(tt_bgra, dtype=np.uint8)
        if self._tt_bgra is not None and self._tt_bgra.shape == arr.shape:
            if np.array_equal(self._tt_bgra, arr):
                self._tt_src = _weak_or_none(tt_bgra)
                return False
        self._tt_bgra = arr.copy()
        self._tt_src = _weak_or_none(tt_bgra)
        self._tt_theme_hex = None
        self._tt_theme_src_id = None
        self._tt_patch_cache.clear()
        self.clear_cache()
        return True

    def set_backdrop_bgr(self, backdrop_bgr: np.ndarray | None) -> bool:
        """Keep a reference to the live TMDb backdrop (BGR) for NP UI color."""
        if backdrop_bgr is None or getattr(backdrop_bgr, "size", 0) == 0:
            if self._backdrop_bgr is None:
                return False
            self._backdrop_bgr = None
            self._tt_theme_hex = None
            self._tt_theme_src_id = None
            return True
        arr = np.ascontiguousarray(backdrop_bgr)
        if arr.ndim != 3 or arr.shape[2] < 3:
            return self.set_backdrop_bgr(None)
        if self._backdrop_bgr is arr:
            return False
        prev = self._backdrop_bgr
        if (
            prev is not None
            and prev.shape == arr.shape
            and prev.ctypes.data == arr.ctypes.data
        ):
            return False
        if (
            prev is not None
            and prev.shape == arr.shape
            and prev.dtype == arr.dtype
            and np.array_equal(prev, arr)
        ):
            return False
        self._backdrop_bgr = arr
        self._tt_theme_hex = None
        self._tt_theme_src_id = None
        return True

    def _ui_color_wash_bgra(self, theme: _NpTheme) -> np.ndarray:
        """Full-frame UI color, dimmed (the no-poster background)."""
        key = theme.ui_hex.lower()
        cached = self._ui_wash_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        b, g, r = theme.ui_bgr
        luma = 0.114 * b + 0.587 * g + 0.299 * r
        # Keep the wash under the light-mode wash threshold (compositing
        # ``_BRIGHT_WASH_LUMA``) so a white / yellow UI color isn't snapped to ink.
        opacity = min(_UI_WASH_OPACITY, _UI_WASH_MAX_LUMA / max(1.0, luma))
        wash = np.empty((int(DESIGN_H), int(DESIGN_W), 4), dtype=np.uint8)
        wash[:, :, :3] = theme.ui_bgr
        wash[:, :, 3] = int(round(255.0 * opacity))
        self._ui_wash_cache = (key, wash)
        return wash

    def _ensure_artwork_blur_bgra(self) -> np.ndarray | None:
        src = self._poster_bgra
        if src is None or src.size == 0:
            self._clear_artwork_blur_cache()
            return None
        pid = id(src)
        if self._artwork_blur_bgra is not None and self._artwork_blur_poster_id == pid:
            return self._artwork_blur_bgra
        self._artwork_blur_bgra = _build_artwork_blur_bgra(src)
        self._artwork_blur_poster_id = pid
        return self._artwork_blur_bgra

    def update_state(
        self,
        *,
        progress: float,
        elapsed_text: str,
        remaining_text: str,
        volume_text: str,
        volume_fraction: float | None = None,
        incoming_audio: str = "",
        playback_config: str = "",
        cast: list[tuple[str, str]] | None = None,
        poster_bgra: np.ndarray | None = None,
        has_now_playing: bool = True,
        searching: bool | None = None,
        missing_art: bool | None = None,
        content_mode: str | None = None,
        song_title: str | None = None,
        album_title: str | None = None,
        artist_title: str | None = None,
        paused: bool | None = None,
        service_name: str | None = None,
        has_position: bool | None = None,
        content_active: bool | None = None,
        is_youtube: bool | None = None,
        tt_bgra: np.ndarray | None = None,
        tt_title: str | None = None,
        receiver_name: str | None = None,
        receiver_input: str | None = None,
        has_receiver: bool | None = None,
        zone4_overlay_text: str | None = None,
        backdrop_bgr: np.ndarray | None = None,
    ) -> bool:
        chrome = False
        ticking = False
        if self.set_now_playing_chrome_visible(has_now_playing):
            chrome = True
        if content_active is not None:
            want_active = bool(content_active)
            if want_active != self._state.content_active:
                self._state.content_active = want_active
                chrome = True
        if content_mode is not None:
            mode = _normalize_content_mode(content_mode)
            if mode != self._state.content_mode:
                self._state.content_mode = mode
                chrome = True
        is_music = self._state.content_mode == _CONTENT_MODE_MUSIC
        pf = max(0.0, min(1.0, float(progress)))
        if abs(pf - self._state.progress) > 1e-9:
            self._state.progress = pf
            ticking = True
        et = str(elapsed_text or "")
        if et != self._state.elapsed_text:
            self._state.elapsed_text = et
            ticking = True
        rt = str(remaining_text or "")
        if rt != self._state.remaining_text:
            self._state.remaining_text = rt
            ticking = True
        vol = str(volume_text or "")
        if vol != self._state.volume:
            if str(self._state.volume or "").strip():
                self._volume_line_changed_mono = time.monotonic()
            self._state.volume = vol
            chrome = True
        muted = vol.strip().lower() in ("mute", "muted", "off")
        if muted != self._state.volume_muted:
            self._state.volume_muted = muted
            chrome = True
        if volume_fraction is None:
            vf = volume_fraction_from_display_line(vol)
        else:
            vf = max(0.0, min(1.0, float(volume_fraction)))
        if abs(vf - self._state.volume_fraction) > 1e-6:
            self._state.volume_fraction = vf
            chrome = True
        inc = str(incoming_audio or "")
        cfg = str(playback_config or "")
        if inc != self._state.incoming:
            self._state.incoming = inc
            chrome = True
        if cfg != self._state.config:
            self._state.config = cfg
            chrome = True
        if paused is not None:
            want_paused = bool(paused)
            if want_paused != self._state.paused:
                self._state.paused = want_paused
                chrome = True
        if has_position is not None:
            want_pos = bool(has_position)
            if want_pos != self._state.has_position:
                self._state.has_position = want_pos
                chrome = True
        if service_name is not None:
            svc = str(service_name or "").strip()
            if svc != self._state.service_name:
                self._state.service_name = svc
                chrome = True
        if is_youtube is not None:
            want_yt = bool(is_youtube)
            if want_yt != self._state.is_youtube:
                self._state.is_youtube = want_yt
                chrome = True
        keep_titles = is_music or bool(self._state.is_youtube)
        if keep_titles:
            if song_title is not None:
                st = str(song_title or "")
                if st != self._state.song_title:
                    self._state.song_title = st
                    chrome = True
            if album_title is not None:
                al = str(album_title or "")
                if al != self._state.album_title:
                    self._state.album_title = al
                    chrome = True
            if artist_title is not None:
                ar = str(artist_title or "")
                if ar != self._state.artist_title:
                    self._state.artist_title = ar
                    chrome = True
            if self._state.cast:
                self._state.cast = []
                chrome = True
        else:
            if self._state.song_title or self._state.album_title or self._state.artist_title:
                self._state.song_title = ""
                self._state.album_title = ""
                self._state.artist_title = ""
                chrome = True
            if cast is not None:
                norm = [(str(a or ""), str(c or "")) for a, c in cast[:21]]
                if norm != self._state.cast:
                    self._state.cast = norm
                    chrome = True
        if searching is not None:
            want = bool(searching)
            if want != self._state.searching:
                self._state.searching = want
                if not want and self._loading_snapshot is not None:
                    self._reveal_gen += 1
                    self._reveal_pending = True
                    self._reveal_started = False
                    self._reveal_ready = False
                    self._reveal_failed = False
                    self._reveal_pending_mono = time.monotonic()
                    self._reveal_t0 = None
                    self._reveal_new = None
                elif want:
                    self._end_reveal()
                if want:
                    self._state.search_angle_deg = 0.0
                    self._last_tick_mono = None
                    self._reset_clock_spin_from_wall()
                else:
                    # TMDb settled — next frame uses real wall clock / volume.
                    self._last_tick_mono = None
                chrome = True
        if missing_art is not None:
            want_miss = bool(missing_art)
            if want_miss != self._state.missing_art:
                self._state.missing_art = want_miss
                chrome = True
        if self._state.searching:
            if self.set_poster_bgra(None):
                chrome = True
        elif self.set_poster_bgra(poster_bgra):
            chrome = True
        if tt_title is not None:
            tt = str(tt_title or "").strip()
            if tt != self._state.tt_title:
                self._state.tt_title = tt
                self._tt_patch_cache.clear()
                chrome = True
        if receiver_name is not None:
            rn = str(receiver_name or "").strip()
            if rn != self._state.receiver_name:
                self._state.receiver_name = rn
                chrome = True
        if receiver_input is not None:
            ri = str(receiver_input or "").strip()
            if ri != self._state.receiver_input:
                self._state.receiver_input = ri
                chrome = True
        if has_receiver is not None:
            want_recv = bool(has_receiver)
            if want_recv != self._state.has_receiver:
                self._state.has_receiver = want_recv
                chrome = True
        if zone4_overlay_text is not None:
            overlay = str(zone4_overlay_text or "").strip()
            if overlay != self._state.zone4_overlay_text:
                self._state.zone4_overlay_text = overlay
                chrome = True
        if self.set_tt_bgra(tt_bgra):
            chrome = True
        if self.set_backdrop_bgr(backdrop_bgr):
            chrome = True
        self._sync_meter_content_key()
        if chrome:
            self.clear_cache(keep_base=True)
        return chrome or ticking

    def _sync_meter_content_key(self) -> None:
        from pigeon.widgets.audio_meter_saver import (
            meter_content_key,
            set_meter_content_key,
        )

        title = str(self._state.tt_title or self._state.song_title or "").strip()
        artist = str(self._state.artist_title or "").strip()
        set_meter_content_key(
            meter_content_key(
                title=title,
                artist=artist,
                mode=self._state.content_mode,
            )
        )

    def _advance_status_bar_handoff(self, now: float | None = None) -> bool:
        """Lerp parked-elapsed → service + traveling elapsed. True if ``t`` changed."""
        if now is None:
            now = time.monotonic()
        want = float(self._bar_handoff_want)
        cur = float(self._bar_handoff)
        if self._bar_handoff_mono is None:
            self._bar_handoff_mono = now
            return False
        dt = max(0.0, now - self._bar_handoff_mono)
        self._bar_handoff_mono = now
        if abs(cur - want) <= 1e-4:
            if cur != want:
                self._bar_handoff = want
                return True
            return False
        step = dt / max(1e-6, float(STATUS_BAR_HANDOFF_S))
        if cur < want:
            self._bar_handoff = min(want, cur + step)
        else:
            self._bar_handoff = max(want, cur - step)
        return True

    def tick(self) -> None:
        now = time.monotonic()
        self._advance_status_bar_handoff(now)

    def _shimmer_phase(self) -> float:
        return widget_shimmer_phase()

    def _record_shimmer(
        self, x: int, y: int, w: int, h: int, radius: int
    ) -> None:
        self._shimmer_rects.append((int(x), int(y), int(w), int(h), int(max(1, radius))))

    def _zone11_loading(self) -> bool:
        """Zone 11 while TMDb is in flight: header + status bar only, the bar shimmers."""
        return bool(self._state.searching) and self._zone11_on()

    def _loading_bar_rect(
        self, *, loading: bool | None = None
    ) -> tuple[int, int, int, int, int] | None:
        """Status bar track ``(x, y, w, h, radius)`` that carries the loading shimmer."""
        if not (self._zone11_loading() if loading is None else bool(loading) and self._zone11_on()):
            return None
        for i, name in enumerate(self._assignments()[:5]):
            if is_status_bar_widget(name, i + 1):
                tx, ty, tw, th, trx = design_rect_from_local(
                    _zone_spec(i + 1),
                    STATUS_BAR_TRACK,
                    view_w=STATUS_BAR_VIEW_W,
                    view_h=STATUS_BAR_VIEW_H,
                )
                return int(tx), int(ty), int(tw), int(th), int(trx)
        return None

    def _has_live_shimmer(self) -> bool:
        return bool(self._shimmer_rects) or self._loading_bar_rect() is not None

    # One stripe period crosses the bar this often.
    _BAR_STRIPE_PERIOD_S = 0.6

    def _paint_live_shimmers(self, out: np.ndarray, *, loading: bool | None = None) -> None:
        self._paint_shimmers(
            out, self._shimmer_rects, self._loading_bar_rect(loading=loading)
        )

    def _paint_shimmers(
        self,
        out: np.ndarray,
        rects: list[tuple[int, int, int, int, int]],
        bar: tuple[int, int, int, int, int] | None,
    ) -> None:
        phase = self._shimmer_phase()
        for x, y, w, h, radius in rects:
            _draw_shimmer_rounded_rect(
                out, x=x, y=y, w=w, h=h, radius=radius, phase=phase
            )
        if bar is not None:
            x, y, w, h, radius = bar
            phase = (time.monotonic() / float(self._BAR_STRIPE_PERIOD_S)) % 1.0
            patch = _candy_stripe_step_bgra(
                int(w),
                int(h),
                int(radius),
                int(phase * _CANDY_STEPS) % _CANDY_STEPS,
                tuple(int(c) for c in self._effective_np_theme().ui_bgr),
            )
            _paste_patch_bgra(out, patch, x, y)

    def _poster_widget_loading(self) -> bool:
        return bool(self._state.searching)

    def _tt_widget_loading(self) -> bool:
        src = self._tt_source_bgra()
        has_art = src is not None and src.size > 0
        return bool(self._state.searching) and not has_art

    def _cast_widget_loading(self) -> bool:
        named = any(
            str(actor or "").strip() for actor, _role in (self._state.cast or [])
        )
        return bool(self._state.searching) and not named

    def _title_widget_loading(self) -> bool:
        if not self._state.is_youtube:
            return False
        has_title = bool(
            str(self._state.song_title or "").strip()
            or str(self._state.artist_title or "").strip()
            or str(self._state.album_title or "").strip()
        )
        return bool(self._state.searching) and not has_title

    def _any_widget_loading(self) -> bool:
        return bool(self._state.searching) and bool(self._state.content_active)

    def _wants_16x9_poster(self) -> bool:
        if self._state.is_youtube:
            return str(self.content_mode or "video").strip().lower() != "music"
        return wants_16x9_poster(
            service_name=self._state.service_name,
            poster_bgra=self._poster_bgra,
            content_mode=self.content_mode,
        )

    def _has_drawable_poster(self) -> bool:
        """True when the poster slot has art or an in-flight search spinner."""
        if self._state.searching:
            return True
        src = self._poster_bgra
        return src is not None and src.size > 0

    def _has_title_info(self) -> bool:
        st = self._state
        if st.searching:
            return True
        if str(st.tt_title or "").strip():
            return True
        if str(st.song_title or "").strip():
            return True
        if str(st.artist_title or "").strip():
            return True
        if str(st.album_title or "").strip():
            return True
        src = self._tt_source_bgra() if hasattr(self, "_tt_source_bgra") else self._tt_bgra
        return src is not None and getattr(src, "size", 0) > 0

    def _has_info_content(self) -> bool:
        st = self._state
        if st.searching:
            return True
        if any(str(actor or "").strip() for actor, _role in (st.cast or [])):
            return True
        title, artist, album = self._info_text_lines()
        return bool(title or artist or album)

    def _info_text_lines(self) -> tuple[str, str, str]:
        """Cast-info / title stack: track or show name, then AVR lines if needed."""
        st = self._state
        title = (
            str(st.song_title or "").strip()
            or str(st.tt_title or "").strip()
            or str(st.service_name or "").strip()
            or str(st.incoming or "").strip()
        )
        artist = str(st.artist_title or "").strip() or str(st.config or "").strip()
        album = str(st.album_title or "").strip()
        if title or artist:
            album = album or str(st.receiver_name or "").strip()

        def _same(a: str, b: str) -> bool:
            return bool(a) and bool(b) and a.casefold() == b.casefold()

        if _same(artist, title):
            artist = str(st.config or "").strip()
            if _same(artist, title):
                artist = ""
        if _same(album, title) or _same(album, artist):
            album = ""
        return title, artist, album

    def _has_receiver_connection(self) -> bool:
        return bool(self._state.has_receiver)

    def _zone3_clock_is_analog_fallback(self) -> bool:
        """Zone 3 clock is the analog face with no receiver, and beside the zone-6 visualizer."""
        assignments = self._assignments()
        if str(assignments[2] if len(assignments) > 2 else "") != "clock":
            return False
        return (not self._has_receiver_connection()) or self._zone6_viz_on(assignments)

    def _has_audio_connection(self) -> bool:
        try:
            from pigeon.widgets.audio_meter_saver import audio_connection_ok

            return bool(audio_connection_ok())
        except Exception:
            return False

    def wants_live_audio(self) -> bool:
        """True when NP needs the ALSA capture thread (VU, visualizers)."""
        assignments = self._assignments()
        if self._zone6_viz_on(assignments):
            # Also with no title: the visualizer is how audio-only playback shows.
            return True
        if not self._state.content_active:
            return False
        keys = set(assignments)
        return "vu" in keys or ZONE4_VISUALIZER_WIDGET in keys

    def _assignments(self) -> tuple[str, str, str, str, str]:
        named = sum(1 for actor, _role in (self._state.cast or []) if str(actor or "").strip())
        has_poster = self._has_drawable_poster()
        auto_zones: tuple[str, str, str, str, str] | None = None
        try:
            from pigeon.auto_widgets import live_plan

            plan = live_plan()
            if plan is not None and plan.assignments:
                auto_zones = plan.assignments
        except Exception:
            auto_zones = None
        zones = _effective_zone_widgets(
            has_position=bool(self._state.has_position),
            cast_count=named,
            content_active=bool(self._state.content_active),
            zone_widgets=auto_zones or _saved_zone_widgets(self.content_mode),
            poster_16x9=self._wants_16x9_poster() and bool(self._state.content_active),
            poster_16x9_zone=int(DEFAULT_16X9_POSTER_ZONE),
            has_poster=has_poster,
            has_volume=bool(_receiver_volume_display_line(self._state.volume)),
            loading_cast=self._cast_widget_loading(),
            content_mode=self.content_mode,
            has_title=self._has_title_info(),
            has_audio=self._has_audio_connection(),
            has_receiver=self._has_receiver_connection(),
            has_info=self._has_info_content(),
        )
        youtube = self._wants_16x9_poster() and bool(self._state.content_active)
        if auto_zones is not None:
            try:
                from pigeon.auto_widgets import LAYOUT_NP, live_plan

                plan = live_plan()
                if plan is not None and plan.layout != LAYOUT_NP:
                    youtube = False
            except Exception:
                pass
            if not youtube:
                zones = auto_zones
        # One visualizer at a time: beside the zone-6 visualizer, zone 4 keeps
        # its cast info (the Pi has no headroom for both). The YouTube layout
        # leaves zone 4 blank for the video title; the visualizer takes it too.
        zone4_info = zones[3] == "cast_info" or (youtube and zones[3] == "")
        if zone4_info and self._zone4_eq_on() and not self._zone6_viz_on(zones):
            zones = (zones[0], zones[1], zones[2], ZONE4_VISUALIZER_WIDGET, zones[4])
        # Zone 11 reserves zones 1-3 as one continuous TT canvas and reports the
        # receiver volume in its top-right corner. The zone-3 volume widget must
        # never come up there, takeover or not.
        if (
            self.volume_takeover_active()
            and self._state.chrome_visible
            and not self._zone11_on(zones)
        ):
            return (zones[0], zones[1], "volume", zones[3], zones[4])
        return zones

    def _poster_zone(self) -> int | None:
        if not self._has_drawable_poster():
            return None
        return _zone_for_widget(self._assignments(), "poster")

    def _live_tmdb_backdrop_bgr(self) -> np.ndarray | None:
        src = self._backdrop_bgr
        if src is not None and getattr(src, "size", 0) > 0:
            return src
        try:
            from pigeon.paused_screen import pausesaver_backdrop

            bg = pausesaver_backdrop()
        except Exception:
            return None
        if bg is None or getattr(bg, "size", 0) == 0:
            return None
        return bg

    def _theme_sources(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """``(tt, poster)`` for the UI color — TMDb art, or album art in music.

        Music has no TT, so album art (held as the poster) is the only source;
        a stale video TT must not color it. YouTube thumbnails never set it.
        """
        if self._state.is_youtube:
            return None, None
        poster = self._poster_bgra
        if poster is not None and getattr(poster, "size", 0) == 0:
            poster = None
        if self.content_mode == _CONTENT_MODE_MUSIC:
            return None, poster
        tt = self._tt_bgra
        if tt is not None and getattr(tt, "size", 0) == 0:
            tt = None
        return tt, poster

    def _effective_np_theme(self) -> _NpTheme:
        """Settings theme, with the UI hue taken from TMDb art.

        TT logo color first, then the poster (backdrops are often production
        stills that miss the title's palette), then the settings UI color.
        White / black / gray art has no hue and falls through. While TMDb is
        still being searched, the settings UI color holds (the previous
        title's art must not color the new one); the art's hue takes over
        once it arrives.
        """
        base = np_theme_from_settings()
        if not _NP_UI_FROM_TT or self._state.searching:
            return base
        tt, poster = self._theme_sources()
        sid = (
            id(tt) if tt is not None else None,
            id(poster) if poster is not None else None,
        )
        if sid != self._tt_theme_src_id:
            self._tt_theme_src_id = sid
            try:
                from pigeon.tmdb_tt_contrast import theme_hex_from_tt_bgra

                self._tt_theme_hex = theme_hex_from_tt_bgra(tt) or theme_hex_from_tt_bgra(
                    poster
                )
            except Exception:
                self._tt_theme_hex = None
        hex_c = str(self._tt_theme_hex or "").strip()
        if not hex_c:
            return base
        return _NpTheme(
            ui_hex=hex_c,
            accent_hex=base.accent_hex,
            button_hex=base.button_hex,
        )

    def _cache_sig(self, *, ticking: bool = True, volume: bool = True) -> tuple[object, ...]:
        st = self._state
        cast_sig = tuple(st.cast[:21])
        poster_id = id(self._poster_bgra) if self._poster_bgra is not None else None
        tt_id = id(self._tt_bgra) if self._tt_bgra is not None else None
        now = self._clock_now_for_display()
        h12 = now.hour % 12
        if h12 == 0:
            h12 = 12
        vol_disp = self._volume_fraction_for_display()
        zone_widgets = self._assignments()
        theme_key = self._effective_np_theme().cache_key
        header_on = _header_clock_enabled()
        fullscreen_clock = _layout_is_fullscreen_clock(zone_widgets)
        keep_second = bool(ticking or fullscreen_clock)
        return (
            60,  # cache schema — live audio does not rebuild chrome on progress
            st.content_mode,
            st.has_position,
            st.content_active,
            round(st.progress, 6) if ticking else 0.0,
            st.elapsed_text if ticking else "",
            st.remaining_text if ticking else "",
            st.volume if volume else None,
            round(vol_disp, 5) if volume else None,
            (st.volume_muted and not st.searching) if volume else None,
            st.incoming,
            st.config,
            st.chrome_visible,
            cast_sig,
            st.song_title,
            st.album_title,
            st.artist_title,
            poster_id,
            tt_id,
            self._backdrop_cache_token(),
            st.tt_title,
            st.receiver_name,
            st.receiver_input,
            st.searching,
            st.missing_art,
            st.paused,
            st.service_name,
            st.is_youtube,
            h12,
            int(now.minute),
            int(now.second) if keep_second else -1,
            _format_zone0_date(pigeon_now()),
            zone_widgets,
            theme_key,
            header_on,
            1 if self._volume_line_opacity() > 0.05 else 0,
            self._zone3_clock_is_analog_fallback(),
            self.volume_takeover_active(),
            self._state.zone4_overlay_text,
            # Service ↔ elapsed fade: rebuild until it settles, or a static
            # bar (LIVE) freezes mid-handoff with both labels drawn.
            round(float(self._bar_handoff), 3),
            self._zone10_pausesaver_active(),
            (
                self._pausesaver_backdrop_id()
                if self._zone10_pausesaver_active()
                else None
            ),
        )

    def _backdrop_cache_token(self) -> object:
        src = self._backdrop_bgr
        if src is None or getattr(src, "size", 0) == 0:
            return None
        return (src.shape, int(src.dtype.num), int(src.ctypes.data))

    def _pausesaver_backdrop_id(self) -> object:
        try:
            from pigeon.paused_screen import pausesaver_backdrop

            bg = pausesaver_backdrop()
        except Exception:
            return None
        if bg is None or getattr(bg, "size", 0) == 0:
            return None
        return (bg.shape, int(bg.dtype.num), int(bg.ctypes.data))

    def _zone10_pausesaver_active(self) -> bool:
        try:
            from pigeon.auto_widgets import LAYOUT_ZONE10_PAUSESAVER, live_plan

            plan = live_plan()
        except Exception:
            plan = None
        planned = plan is not None and plan.layout == LAYOUT_ZONE10_PAUSESAVER
        if not planned:
            keys = self._assignments()
            planned = bool(keys) and keys[0] == "" and keys[3] == "pausesaver"
        if not planned:
            return False
        try:
            from pigeon.paused_screen import pausesaver_has_usable_art

            return bool(pausesaver_has_usable_art())
        except Exception:
            return True

    def _paused_clock_in_zone6(self) -> bool:
        """Paused NP: clock-saver face in zone 6 over the backdrop, not a play glyph."""
        if self._zone10_pausesaver_active():
            return False
        if not self._state.paused or not self._state.content_active:
            return False
        span = zone6_span_widget(self._assignments())
        if span in ("clock", "clock_saver", "pausesaver"):
            return False
        return True

    def _ticking_needs_wall_second(self) -> bool:
        keys = self._assignments()
        if self._paused_clock_in_zone6():
            return True
        if any(k == "clock_saver_seconds" for k in keys):
            return True
        if zone6_span_widget(keys) in ("clock", "clock_saver", "pausesaver"):
            return True
        return any(k in ("clock", "clock_16x9") for k in keys)

    def _ticking_sig(self) -> tuple[object, ...]:
        now = self._clock_now_for_display()
        st = self._state
        second = int(now.second) if self._ticking_needs_wall_second() else -1
        return (
            now.hour,
            now.minute,
            second,
            st.elapsed_text,
            st.remaining_text,
            int(round(max(0.0, min(1.0, float(st.progress))) * 200.0)),
        )

    def _stamp_clock_widget(self, out: np.ndarray, now: datetime) -> None:
        assignments = self._assignments()
        if zone6_span_widget(assignments) in ("clock", "clock_saver", "pausesaver"):
            self._draw_zone6_span_widget(out)
            return
        clock_zone = _zone_for_widget(assignments, "clock")
        if clock_zone is None or int(clock_zone) in (4, 5):
            return
        z = _zone_spec(int(clock_zone))
        zx, zy, zw, zh = z.xywh
        patch = _rasterize_named_widget(
            assets_dir=self._assets_dir,
            widget_key="clock",
            dest_w=zw,
            dest_h=zh,
            now=now,
            theme=self._effective_np_theme(),
            zone=int(clock_zone),
        )
        if patch is not None and patch.size:
            _paste_patch_bgra(out, patch, zx, zy)

    def _ticking_dirty_rects(self) -> list[tuple[int, int, int, int]]:
        """Zones restamped by ``_overlay_ticking`` — restore these instead of the full frame."""
        rects: list[tuple[int, int, int, int]] = []
        assignments = self._assignments()
        if (
            _header_clock_enabled()
            and not _zone_clock_hides_header(assignments)
            and self._header_slot_ticks()
        ):
            baseline = float(header_clock_baseline_y())
            size = float(NP_HEADER_CLOCK_SIZE_PX)
            disc = self._disc_clock_geometry()
            if disc is not None:
                dcx, dbottom, _nh = disc
                ch = _disc_clock_ink_h()
                half_w = int(round(float(VOLUME_INNER_R) * 0.8))
                rects.append(
                    (
                        int(round(dcx)) - half_w,
                        max(0, int(round(dbottom)) - ch - 4),
                        2 * half_w,
                        ch + 8,
                    )
                )
            elif self._zone11_on(assignments):
                rects.append((0, 0, int(DESIGN_W), int(self._zone11_volume_bottom()) + 4))
            else:
                top = max(0, int(round(baseline - size - 8.0)))
                header_h = max(1, int(round(size + 16.0)))
                rects.append((0, top, int(DESIGN_W), header_h))
        if zone6_span_widget(assignments) == "clock" or self._paused_clock_in_zone6():
            z = NOW_PLAYING_ZONES[6]
            zx, zy, zw, zh = (int(v) for v in z.xywh)
            rects.append((zx, zy, zw, zh))
        if zone6_span_widget(assignments) in ("clock_saver", "pausesaver"):
            z = NOW_PLAYING_ZONES[6]
            zx, zy, zw, zh = (int(v) for v in z.xywh)
            rects.append((zx, zy, zw, zh))
        clock_zone = _zone_for_widget(assignments, "clock")
        if clock_zone is not None:
            z = _zone_spec(int(clock_zone))
            zx, zy, zw, zh = (int(v) for v in z.xywh)
            rects.append((zx, zy, zw, zh))
        for i, key in enumerate(assignments):
            if key == "clock_saver_seconds" or is_status_bar_widget(key, i + 1):
                z = _zone_spec(i + 1)
                zx, zy, zw, zh = (int(v) for v in z.xywh)
                rects.append((zx, zy, zw, zh))
        painted = self._status_bar_paint_bounds
        if painted is not None:
            x0, y0, x1, y1 = painted
            rects.append((x0, y0, x1 - x0, y1 - y0))
        rects.extend(self._tt_time_paint_rects)
        return rects

    def _restore_ticking_rects(self, under: np.ndarray) -> None:
        src = self._static_bgr
        if src is None or src.shape != under.shape:
            return
        for x, y, w, h in self._ticking_dirty_rects():
            y0 = max(0, int(y))
            x0 = max(0, int(x))
            y1 = min(int(under.shape[0]), y0 + max(0, int(h)))
            x1 = min(int(under.shape[1]), x0 + max(0, int(w)))
            if y1 <= y0 or x1 <= x0:
                continue
            under[y0:y1, x0:x1] = src[y0:y1, x0:x1]

    def _overlay_ticking(self, out: np.ndarray) -> None:
        if _layout_is_fullscreen_clock(self._assignments()):
            return
        if self._zone10_pausesaver_active():
            self._draw_status_bar(out)
            return
        now = self._clock_now_for_display()
        self._stamp_clock_widget(out, now)
        self._draw_paused_zone6_clock_saver(out, now)
        self._draw_clock_digital(out, now)
        if self._header_slot_ticks():
            self._draw_header_clock(out, now)
        self._draw_seconds_bar_zones(out, now)
        self._draw_zone4_overlay_text(out)
        self._tt_time_paint_rects = []
        self._draw_tt_countdowns(out, part="time")
        assignments = self._assignments()
        if any(is_status_bar_widget(assignments[i], i + 1) for i in range(5)):
            self._draw_status_bar(out)

    def _svg_chrome_cache_key(self, now: datetime) -> tuple[object, ...]:
        mode = self.content_mode
        path = default_view_circles_svg_path(self._assets_dir, content_mode=mode)
        mtime = 0
        try:
            if path.is_dir():
                for name in WIDGET_FILENAMES.values():
                    try:
                        mtime ^= (path / name).stat().st_mtime_ns
                    except OSError:
                        mtime ^= -1
            else:
                mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = -1
        h12 = now.hour % 12
        if h12 == 0:
            h12 = 12
        zone_widgets = self._assignments()
        # Ticks live in the per-widget raster cache; do not keep 96 full-frame
        # 1280×800 copies (that was hundreds of MB and a raster every second).
        return (
            str(path),
            mtime,
            mode,
            bool(self._state.paused),
            h12,
            int(now.minute),
            13,  # chrome pipeline — 30/70 unfilled volume track
            zone_widgets,
            self._effective_np_theme().cache_key,
            self._zone3_clock_is_analog_fallback(),
        )

    def _render_svg_base(self, now: datetime) -> np.ndarray:
        global _FORCE_ANALOG_CLOCK
        prev_analog = _FORCE_ANALOG_CLOCK
        if self._zone3_clock_is_analog_fallback():
            _FORCE_ANALOG_CLOCK = True
        try:
            return self._render_svg_base_inner(now)
        finally:
            _FORCE_ANALOG_CLOCK = prev_analog

    def _render_svg_base_inner(self, now: datetime) -> np.ndarray:
        key = self._svg_chrome_cache_key(now)
        cached = self._svg_chrome_by_key.get(key)
        if cached is not None:
            # Clock second ticks are per-widget; restamp them onto the minute chrome.
            clock_zone = _zone_for_widget(self._assignments(), "clock")
            if clock_zone is not None:
                out = cached.copy()
                z = _zone_spec(int(clock_zone))
                zx, zy, zw, zh = z.xywh
                patch = _rasterize_named_widget(
                    assets_dir=self._assets_dir,
                    widget_key="clock",
                    dest_w=zw,
                    dest_h=zh,
                    now=now,
                    theme=self._effective_np_theme(),
                    zone=int(clock_zone),
                )
                if patch is not None and patch.size:
                    _paste_patch_bgra(out, patch, zx, zy)
                return out
            return cached
        try:
            base = render_view_circles_svg_base_bgra(
                assets_dir=self._assets_dir,
                content_mode=self.content_mode,
                paused=bool(self._state.paused),
                now=now,
                theme=self._effective_np_theme(),
                zone_widgets=self._assignments(),
            )
        except Exception:
            base = _fallback_base_bgra()
        while len(self._svg_chrome_by_key) > 8:
            self._svg_chrome_by_key.pop(next(iter(self._svg_chrome_by_key)))
        self._svg_chrome_by_key[key] = base
        return base

    def _draw_missing_art_placeholder(
        self, out: np.ndarray, px: int, py: int, pw: int, ph: int, prx: int
    ) -> None:
        mask = _rounded_rect_mask(pw, ph, prx)
        plate = np.zeros((ph, pw, 4), dtype=np.uint8)
        plate[:, :, 0] = 78
        plate[:, :, 1] = 78
        plate[:, :, 2] = 78
        plate[:, :, 3] = np.minimum(np.uint8(230), mask)
        _paste_patch_bgra(out, plate, px, py)
        try:
            from pigeon.font_paths import resolve_ui_font_extrabold

            font_path = resolve_ui_font_extrabold()
        except Exception:
            font_path = None
        cx = int(round(px + pw / 2.0))
        cy = int(round(py + ph / 2.0))
        if font_path is not None:
            try:
                font = ImageFont.truetype(str(font_path), size=max(48, int(round(ph * 0.42))))
                img = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                glyph = "?"
                bbox = draw.textbbox((0, 0), glyph, font=font)
                tw = max(1, int(bbox[2] - bbox[0]))
                th = max(1, int(bbox[3] - bbox[1]))
                tx = (pw - tw) // 2 - int(bbox[0])
                ty = (ph - th) // 2 - int(bbox[1]) - max(2, ph // 40)
                draw.text((tx, ty), glyph, font=font, fill=(220, 220, 220, 255))
                arr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)
                arr[:, :, 3] = np.minimum(arr[:, :, 3], mask)
                _paste_patch_bgra(out, arr, px, py)
                return
            except Exception:
                pass
        scale = max(1.5, ph / 140.0)
        thickness = max(2, int(round(scale * 2.2)))
        (tw, th), _ = cv2.getTextSize("?", cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
        tx = cx - tw // 2
        ty = cy + th // 2
        cv2.putText(
            out,
            "?",
            (tx, ty),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (220, 220, 220, 255) if out.shape[2] == 4 else (220, 220, 220),
            thickness,
            lineType=cv2.LINE_AA,
        )

    def _draw_poster(self, out: np.ndarray) -> None:
        poster_zone = self._poster_zone()
        if poster_zone is None:
            return
        px, py, pw, ph, prx = _poster_geometry(
            self.content_mode, zone=int(poster_zone)
        )
        if self._poster_widget_loading():
            _draw_shimmer_rounded_rect(
                out,
                x=px,
                y=py,
                w=pw,
                h=ph,
                radius=prx,
                recorder=self._record_shimmer,
            )
            return
        src = self._poster_bgra
        if src is not None and src.size > 0:
            if src.ndim == 3 and src.shape[2] == 3:
                src = cv2.cvtColor(src, cv2.COLOR_BGR2BGRA)
            sh, sw = src.shape[:2]
            if sh >= 1 and sw >= 1:
                scale = max(pw / float(sw), ph / float(sh))
                nw = max(1, int(round(sw * scale)))
                nh = max(1, int(round(sh * scale)))
                resized = cv2.resize(
                    src,
                    (nw, nh),
                    interpolation=cv_resize_interp(sw, sh, nw, nh),
                )
                x0 = max(0, (nw - pw) // 2)
                y0 = max(0, (nh - ph) // 2)
                crop = resized[y0 : y0 + ph, x0 : x0 + pw]
                if crop.shape[0] != ph or crop.shape[1] != pw:
                    crop = cv2.resize(crop, (pw, ph), interpolation=cv2.INTER_AREA)
                mask = _rounded_rect_mask(pw, ph, prx)
                patch = crop.copy()
                if patch.shape[2] == 3:
                    patch = cv2.cvtColor(patch, cv2.COLOR_BGR2BGRA)
                patch[:, :, 3] = np.minimum(patch[:, :, 3], mask)
                _paste_patch_bgra(out, patch, px, py)

    def _draw_status_bar(self, out: np.ndarray, *, zone: int | None = None) -> None:
        bar_zone = int(zone) if zone is not None else None
        if bar_zone is None:
            assignments = self._assignments()
            for i, name in enumerate(assignments[:5]):
                if is_status_bar_widget(name, i + 1):
                    bar_zone = i + 1
                    break
        if bar_zone is None:
            return
        zone = _zone_spec(int(bar_zone))
        zx, zy, zw, zh = (int(v) for v in zone.xywh)
        bounds = [zx, zy, zx + zw, zy + zh]
        st = self._state
        pf = max(0.0, min(1.0, float(st.progress)))
        tx, ty, tw, th, trx = design_rect_from_local(
            zone,
            STATUS_BAR_TRACK,
            view_w=STATUS_BAR_VIEW_W,
            view_h=STATUS_BAR_VIEW_H,
        )
        _draw_rounded_bar_bgra(
            out,
            x=tx,
            y=ty,
            w=tw,
            h=th,
            fill_bgr=(122, 122, 122),
            radius=trx,
            stroke_bgr=None,
            fill_opacity=1.0,
        )
        # Reveal elapsed by cropping a UI-colored copy of the same rounded rect
        # from the left (0% hidden … 100% fully visible).
        if pf > 1e-6 and tw > 1 and th > 1:
            vis_w = max(0, min(tw, int(round(pf * float(tw)))))
            if vis_w > 0:
                mask = _rounded_rect_mask(tw, th, trx)
                elapsed = np.zeros((th, tw, 4), dtype=np.uint8)
                elapsed[:, :, :3] = self._effective_np_theme().ui_bgr
                elapsed[:, :, 3] = mask
                elapsed[:, vis_w:, 3] = 0
                _paste_patch_bgra(out, elapsed, tx, ty)
        # White CTI at the playhead while the zone-4 visualizer is up.
        if ZONE4_VISUALIZER_WIDGET in self._assignments() and tw > 1 and th > 1:
            cx = max(1, min(tw - 1, int(round(pf * float(tw)))))
            cti = np.zeros((th, tw, 4), dtype=np.uint8)
            cti[:, cx - 1 : cx + 1, :3] = 255
            cti[:, cx - 1 : cx + 1, 3] = _rounded_rect_mask(tw, th, trx)[:, cx - 1 : cx + 1]
            _paste_patch_bgra(out, cti, tx, ty)

        def _bar_xy(local: tuple[float, float]) -> tuple[float, float]:
            return design_xy_from_local(
                zone, local[0], local[1], view_w=STATUS_BAR_VIEW_W, view_h=STATUS_BAR_VIEW_H
            )

        et = format_status_bar_timecode(st.elapsed_text, remaining=False)
        rt = format_status_bar_timecode(st.remaining_text, remaining=True)
        if et.upper() == "LIVE" and rt.upper() == "LIVE":
            # One LIVE (right) is enough; the left one sat on the service name.
            et = ""
        svc = str(st.service_name or "").strip()
        if svc.lower() in ("", "unknown", "none", "n/a", "na", "--"):
            svc = str(st.incoming or "").strip()
        if svc.lower() in ("", "unknown", "none", "n/a", "na", "--"):
            svc = ""
        if self._zone11_on():
            # Zone 11: app id / input id moved to the top-right and elapsed / TRT
            # live in the strip above the bar; nothing is drawn under the bar.
            et, rt = "", ""
            svc = ""

        sx, sy = _bar_xy(STATUS_BAR_SERVICE_LOCAL)
        _, ey = _bar_xy(STATUS_BAR_ELAPSED_LOCAL)
        _, ry = _bar_xy(STATUS_BAR_REMAINING_LOCAL)
        size = STATUS_BAR_TIME_SIZE_PX

        def _label_patch(
            label: str, *, fill_rgb: tuple[int, int, int] | None = None
        ) -> tuple[np.ndarray, int, int]:
            ink = fill_rgb if fill_rgb is not None else _look_chrome_rgb()
            if not label:
                return np.zeros((1, 1, 4), dtype=np.uint8), 0, 0
            if label.upper() == "LIVE":
                patch, pw, ph = _text_patch_digital7(label, size_px=size, fill_rgb=ink)
            else:
                patch = _matching_hhmm_patch(label, size_px=size, fill_rgb=ink)
                ph, pw = patch.shape[:2]
            return patch, int(pw), int(ph)

        def _paste_patch(
            patch: np.ndarray,
            x: float,
            y: float,
            *,
            right: bool = False,
            opacity: float = 1.0,
        ) -> None:
            if opacity <= 0.01:
                return
            if opacity < 0.999:
                patch = _fade_bgra(patch, opacity)
            if patch.size == 0 or int(patch[:, :, 3].max()) < 8:
                return
            ph, pw = patch.shape[:2]
            paste_x = int(round(x - pw)) if right else int(round(x))
            paste_y = int(round(y - ph))
            _paste_patch_bgra(out, patch, paste_x, paste_y)
            bounds[0] = min(bounds[0], paste_x)
            bounds[1] = min(bounds[1], paste_y)
            bounds[2] = max(bounds[2], paste_x + pw)
            bounds[3] = max(bounds[3], paste_y + ph)

        et_patch, et_w, _et_h = _label_patch(et)
        rt_patch, rt_w, _rt_h = _label_patch(rt, fill_rgb=_look_ink_rgb())
        svc_patch, svc_w, _svc_h = _label_patch(svc.lower() if svc else "")
        remaining_left = float(tx + tw) - float(rt_w) if rt_w > 0 else None
        elapsed_x = status_bar_elapsed_left_x(
            track_x=float(tx),
            track_w=float(tw),
            progress=pf,
            elapsed_w=float(et_w),
            remaining_left_x=remaining_left,
        )
        elapsed_a = status_bar_elapsed_opacity(
            track_x=float(tx),
            track_w=float(tw),
            progress=pf,
            elapsed_w=float(et_w),
            remaining_left_x=remaining_left,
        )
        if svc:
            ready = (not et) or status_bar_service_has_room(
                service_x=float(sx),
                service_w=float(svc_w),
                elapsed_x=float(elapsed_x),
            )
            want = 1.0 if ready else 0.0
            self._bar_handoff_want = want
            if not self._bar_handoff_inited:
                self._bar_handoff = want
                self._bar_handoff_inited = True
            _parked_a, svc_a, _travel_a = status_bar_handoff_alphas(self._bar_handoff)
            if svc_a > 0.01:
                _paste_patch(svc_patch, sx, sy, opacity=svc_a)
        else:
            self._bar_handoff_want = 0.0
            if not self._bar_handoff_inited:
                self._bar_handoff = 0.0
                self._bar_handoff_inited = True
        if elapsed_a > 0.01:
            _paste_patch(et_patch, elapsed_x, ey, opacity=elapsed_a)
        # Remaining is authored near the right; right-align to the track end.
        _paste_patch(rt_patch, float(tx + tw), ry, right=True)
        self._status_bar_paint_bounds = (bounds[0], bounds[1], bounds[2], bounds[3])

    def _draw_play_overlay(self, out: np.ndarray) -> None:
        if not self._state.paused:
            return
        poster_zone = self._poster_zone()
        if poster_zone is None:
            return
        px, py, pw, ph, prx = _poster_geometry(
            self.content_mode, zone=int(poster_zone)
        )
        if int(poster_zone) in (6, 7):
            if self._paused_clock_in_zone6():
                return
            mask = _rounded_rect_mask(pw, ph, prx)
            dim = np.zeros((ph, pw, 4), dtype=np.uint8)
            dim[:, :, 3] = (mask.astype(np.float32) * 127.0).astype(np.uint8)
            _paste_patch_bgra(out, dim, px, py)
            dest_h = max(1, int(ph))
            dest_w = max(
                1,
                int(round(dest_h * float(NOW_PLAYING_ZONES[1].w) / float(NOW_PLAYING_ZONES[1].h))),
            )
            try:
                patch = _rasterize_named_widget(
                    assets_dir=self._assets_dir,
                    widget_key="play",
                    dest_w=dest_w,
                    dest_h=dest_h,
                    now=self._clock_now_for_display(),
                    theme=self._effective_np_theme(),
                    include_play_overlay=False,
                )
            except Exception:
                patch = None
            if patch is None or patch.size == 0:
                return
            ox = int(round(px + (pw - dest_w) / 2.0))
            oy = int(round(py + (ph - dest_h) / 2.0))
            _paste_patch_bgra(out, patch, ox, oy)
            return
        zone = _zone_spec(int(poster_zone))
        zx, zy, zw, zh = zone.xywh
        try:
            patch = _rasterize_named_widget(
                assets_dir=self._assets_dir,
                widget_key="play",
                dest_w=zw,
                dest_h=zh,
                now=self._clock_now_for_display(),
                    theme=self._effective_np_theme(),
            )
        except Exception:
            patch = None
        if patch is None or patch.size == 0:
            return
        _paste_patch_bgra(out, patch, zx, zy)

    def _header_slot_text(self, now: datetime) -> str:
        """Header chrome: album title during music, otherwise the clock."""
        if self.content_mode == _CONTENT_MODE_MUSIC:
            album = str(self._state.album_title or "").strip()
            if album:
                return album
        return now_playing_header_clock_text(now)

    def _header_slot_ticks(self) -> bool:
        """True when the header slot is a clock that must restamp each minute."""
        if not _header_clock_enabled():
            return False
        if _zone_clock_hides_header(self._assignments()):
            return False
        if self.content_mode == _CONTENT_MODE_MUSIC and str(
            self._state.album_title or ""
        ).strip():
            return False
        return True

    def _header_slot_fitted(
        self, now: datetime
    ) -> tuple[np.ndarray, object, str] | None:
        """Rasterize header chrome once per label / theme / width."""
        label = self._header_slot_text(now)
        if not label:
            return None
        z6 = NOW_PLAYING_ZONES[6]
        max_w = max(80, int(round(float(z6.w) - 48.0)))
        theme = self._effective_np_theme().cache_key
        key = (label, int(max_w), theme)
        cached = self._header_slot_patch_cache
        if cached is not None and cached[0] == key:
            return cached[1]  # type: ignore[return-value]
        fill = _look_chrome_rgb()
        size_hi = int(NP_HEADER_CLOCK_SIZE_PX)
        font = _load_sharp_extrabold(size_hi)
        patch, pw, _ph = _text_patch_font(label, font=font, fill_rgb=fill)
        if pw > max_w:
            lo, hi = 18, size_hi
            best_font = font
            best_patch, best_pw = patch, pw
            while lo <= hi:
                mid = (lo + hi) // 2
                trial_font = _load_sharp_extrabold(mid)
                trial, tw, _th = _text_patch_font(
                    label, font=trial_font, fill_rgb=fill
                )
                if tw <= max_w:
                    best_font, best_patch, best_pw = trial_font, trial, tw
                    lo = mid + 1
                else:
                    hi = mid - 1
            font, patch, pw = best_font, best_patch, best_pw
        if pw > max_w:
            lo, hi = 0, len(label)
            best = label
            while lo <= hi:
                mid = (lo + hi) // 2
                cand = (label[:mid].rstrip() + "...") if mid < len(label) else label
                trial, tw, _th = _text_patch_font(cand, font=font, fill_rgb=fill)
                if tw <= max_w:
                    best = cand
                    patch = trial
                    lo = mid + 1
                else:
                    hi = mid - 1
            label = best
        if patch.size == 0 or int(patch[:, :, 3].max()) < 8:
            return None
        fitted = (patch, font, label)
        self._header_slot_patch_cache = (key, fitted)
        return fitted

    def _paste_disc_clock(self, out: np.ndarray, now: datetime) -> bool:
        """Stamp the clock in the zone-3 volume disc. False when it isn't showing."""
        disc = self._disc_clock_geometry()
        if disc is None:
            return False
        cx, bottom, _nh = disc
        patch = _disc_clock_patch(now_playing_header_clock_text(now), _look_chrome_rgb())
        if patch.size:
            ph, pw = patch.shape[:2]
            _paste_patch_bgra(out, patch, int(round(cx - pw / 2.0)), int(round(bottom - ph)))
        return True

    def _draw_header_clock(self, out: np.ndarray, now: datetime) -> None:
        """Header chrome centered on the wide TT / album (clock, or album when music)."""
        if not _header_clock_enabled():
            return
        if _zone_clock_hides_header(self._assignments()):
            return
        if self._header_slot_ticks():
            if self._zone11_on():
                # Zone 11: clock top-center at the volume's size (volume top-right,
                # app / input labels top-left).
                self._paste_zone11_corner_text(
                    out,
                    now_playing_header_clock_text(now),
                    align="center",
                    fill_rgb=_look_chrome_rgb(),
                    clock=True,
                    scale=self._ZONE11_VOLUME_SCALE,
                )
                return
            # Digital-7 clock over zone 3; zone 6's header slot holds the TRT.
            z3 = NOW_PLAYING_ZONES[3]
            cx = float(z3.x) + float(z3.w) * 0.5
            if self._paste_disc_clock(out, now):
                # Volume readout showing in zone 3: the clock sits in the disc above it.
                return
            self._paste_header_digital7(
                out,
                now_playing_header_clock_text(now),
                cx,
                fill_rgb=_look_chrome_rgb(),
            )
            return
        # Album title in the header slot; the clock still sits in the volume disc.
        self._paste_disc_clock(out, now)
        fitted = self._header_slot_fitted(now)
        if fitted is None:
            return
        patch, font, label = fitted
        cx = header_clock_center_x(self._assignments())
        if self._wants_16x9_poster() and self._state.content_active:
            z6 = NOW_PLAYING_ZONES[int(DEFAULT_16X9_POSTER_ZONE)]
            cx = float(z6.x) + float(z6.w) * 0.5
        fy = header_clock_baseline_y()
        _paste_baseline_centered(
            out, patch, cx, fy, bbox_top=_font_bbox_top(label, font)
        )

    def _draw_clock_digital(self, out: np.ndarray, now: datetime) -> None:
        global _FORCE_ANALOG_CLOCK
        assignments = self._assignments()
        if zone6_span_widget(assignments) in ("clock", "clock_saver", "pausesaver"):
            return
        clock_zone = _zone_for_widget(assignments, "clock")
        if clock_zone is None:
            return
        if int(clock_zone) in (4, 5):
            self._draw_strip_clock(out, int(clock_zone), now)
            return
        zone = _zone_spec(int(clock_zone))
        prev_analog = _FORCE_ANALOG_CLOCK
        if self._zone3_clock_is_analog_fallback():
            _FORCE_ANALOG_CLOCK = True
        try:
            _draw_clock_labels_in_zone(
                out, zone, now, include_digital_time=_clock_include_digital_time()
            )
        finally:
            _FORCE_ANALOG_CLOCK = prev_analog

    def _draw_strip_clock(self, out: np.ndarray, zone_idx: int, now: datetime) -> None:
        zone = _zone_spec(int(zone_idx))
        zx, zy, zw, zh = zone.xywh
        label = now_playing_header_clock_text(now)
        if not label:
            return
        px = max(22, min(58, int(round(zh * 0.48))))
        patch, pw, ph = _text_patch_font(
            label,
            font=_load_sharp_extrabold(px),
            fill_rgb=_look_ink_rgb(),
        )
        if pw > zw - 24 and px > 18:
            px = max(18, int(px * (zw - 24) / float(max(pw, 1))))
            patch, pw, ph = _text_patch_font(
                label,
                font=_load_sharp_extrabold(px),
                fill_rgb=_look_ink_rgb(),
            )
        _paste_centered(out, patch, zx + zw * 0.5, zy + zh * 0.5)

    def _draw_seconds_bar_zones(self, out: np.ndarray, now: datetime) -> None:
        from pigeon.widgets.clock_saver import render_seconds_bar_widget_bgra

        assignments = self._assignments()
        for i, key in enumerate(assignments):
            if key != "clock_saver_seconds":
                continue
            zone = _zone_spec(i + 1)
            zx, zy, zw, zh = zone.xywh
            patch = render_seconds_bar_widget_bgra(int(zw), int(zh), now=now)
            _paste_patch_bgra(out, patch, int(zx), int(zy))

    def _draw_pigeonclock_zones(self, out: np.ndarray) -> None:
        assignments = self._assignments()
        for i, key in enumerate(assignments):
            if key != "pigeonclock":
                continue
            zone = _zone_spec(i + 1)
            zx, zy, zw, zh = zone.xywh
            px = max(22, min(72, int(round(zh * 0.55))))
            patch, pw, ph = _text_patch_font(
                "pigeonclock",
                font=_load_sharp_extrabold(px),
                fill_rgb=_look_ink_rgb(),
            )
            if pw > zw - 16 and px > 16:
                px = max(16, int(px * (zw - 16) / float(max(pw, 1))))
                patch, pw, ph = _text_patch_font(
                    "pigeonclock",
                    font=_load_sharp_extrabold(px),
                    fill_rgb=_look_ink_rgb(),
                )
            _paste_centered(out, patch, zx + zw * 0.5, zy + zh * 0.5)

    def _draw_live_audio_widgets(self, out: np.ndarray) -> None:
        assignments = self._assignments()
        bgr = out.ndim == 3 and int(out.shape[2]) == 3
        if self._zone6_viz_on(assignments):
            z = NOW_PLAYING_ZONES[6]
            zx, zy, zw, zh = z.xywh
            rect = (int(round(zx)), int(round(zy)), int(round(zw)), int(round(zh)), 13)
            # No page fill: the visualizer draws over the wash / poster blur.
            self._zone6_visualizer().render(out, rect, clear=True)
            self._draw_zone6_receiver_volume(out)
            from pigeon import visualizer_mode
            from pigeon.widgets.audio_meter_saver import program_audio_present

            # The badge reports a missing feed in visualizer mode; the audio-only
            # layout only exists while audio is present.
            if visualizer_mode.is_active():
                visualizer_mode.draw_badge(out, z.xywh, visualizer_mode.badge_state(program_audio_present()))
            return
        if zone6_span_widget(assignments) == "vu":
            z = NOW_PLAYING_ZONES[6]
            zx, zy, zw, zh = z.xywh
            if bgr:
                from pigeon.widgets.vu_meters import render_vu_meters_into_bgr

                render_vu_meters_into_bgr(
                    out[int(zy) : int(zy) + int(zh), int(zx) : int(zx) + int(zw)],
                    face_key=self._cached_sig,
                )
            else:
                from pigeon.widgets.vu_meters import render_vu_meters_bgra

                patch = render_vu_meters_bgra(int(zw), int(zh))
                _paste_patch_bgra(out, patch, int(zx), int(zy))

    def _draw_paused_zone6_clock_saver(
        self, out: np.ndarray, now: datetime | None = None
    ) -> None:
        """Scale the clock-saver face into zone 6 over the backdrop / poster."""
        if not self._paused_clock_in_zone6():
            return
        z = NOW_PLAYING_ZONES[6]
        zx, zy, zw, zh = z.xywh
        from pigeon.widgets.clock_saver import render_clock_saver_face_bgra

        patch = render_clock_saver_face_bgra(
            width=int(zw),
            height=int(zh),
            include_weather=False,
            when=now,
        )
        if patch is None or patch.size == 0:
            return
        _paste_patch_bgra(out, patch, int(zx), int(zy))

    def _draw_zone6_span_widget(self, out: np.ndarray) -> None:
        """Clock-saver face, weather cluster, or VU in the wide zone-6 slot."""
        kind = zone6_span_widget(self._assignments())
        if kind not in ("clock", "clock_saver", "pausesaver", "weather"):
            return
        z = NOW_PLAYING_ZONES[6]
        zx, zy, zw, zh = z.xywh
        if kind == "clock_saver":
            from pigeon.auto_widgets import live_plan
            from pigeon.widgets.clock_saver import render_scaled_clock_saver_bgra

            plan = None
            try:
                plan = live_plan()
            except Exception:
                plan = None
            include_weather = not bool(getattr(plan, "blank_weather", False))
            volume = "" if bool(getattr(plan, "blank_volume", False)) else self._state.volume
            patch = render_scaled_clock_saver_bgra(
                int(zw),
                int(zh),
                volume=volume,
                include_weather=include_weather,
            )
            _paste_patch_bgra(out, patch, int(zx), int(zy))
            return
        if kind == "pausesaver":
            from pigeon.paused_screen import pausesaver_backdrop, render_pausesaver_bgra

            patch = render_pausesaver_bgra(
                int(zw), int(zh), pausesaver_backdrop()
            )
            _paste_patch_bgra(out, patch, int(zx), int(zy))
            return
        if kind == "clock":
            from pigeon.widgets.clock_saver import render_clock_saver_face_bgra

            patch = render_clock_saver_face_bgra(
                width=int(zw),
                height=int(zh),
                include_weather=False,
            )
            _paste_patch_bgra(out, patch, int(zx), int(zy))
            return
        self._paste_weather_cluster(out, (int(zx), int(zy), int(zw), int(zh)))

    def _draw_zone4_overlay_text(self, out: np.ndarray) -> None:
        label = str(self._state.zone4_overlay_text or "").strip()
        if not label:
            try:
                from pigeon.auto_widgets import live_plan

                plan = live_plan()
                label = str(getattr(plan, "zone4_text", "") or "").strip()
                if not label and bool(getattr(plan, "zone4_receiver", False)):
                    label = self._receiver_readout()
            except Exception:
                label = ""
        if not label:
            return
        assignments = self._assignments()
        if len(assignments) > 3 and str(assignments[3] or "").strip():
            return
        zone = _zone_spec(4)
        zx, zy, zw, zh = zone.xywh
        px = max(22, min(72, int(round(zh * 0.55))))
        patch, pw, ph = _text_patch_font(
            label,
            font=_load_sharp_extrabold(px),
            fill_rgb=_look_ink_rgb(),
        )
        if pw > zw - 24 and px > 16:
            px = max(16, int(px * (zw - 24) / float(max(pw, 1))))
            patch, pw, ph = _text_patch_font(
                label,
                font=_load_sharp_extrabold(px),
                fill_rgb=_look_ink_rgb(),
            )
        _paste_centered(out, patch, zx + zw * 0.5, zy + zh * 0.5)

    def _receiver_readout(self) -> str:
        """Receiver input label for zone 4, e.g. ``TV AUDIO`` (the volume sits over zone 6)."""
        if not self._has_receiver_connection():
            return ""  # unreachable: the last values would be stale
        return str(self._state.receiver_input or "").strip()

    def _zone6_receiver_volume_text(self) -> str:
        """Receiver volume for the zone-6 header slot, when zone 4 shows the receiver."""
        if not self._zone6_viz_on(self._assignments()) or not self._has_receiver_connection():
            return ""
        try:
            from pigeon.auto_widgets import live_plan

            if not bool(getattr(live_plan(), "zone4_receiver", False)):
                return ""
        except Exception:
            return ""
        return _receiver_volume_display_line(self._state.volume)

    def _draw_zone6_receiver_volume(self, out: np.ndarray) -> None:
        """Volume (``-32.5 dB``) centered over zone 6, on the zone-3 clock's date baseline,
        as large as the band above that baseline allows."""
        label = self._zone6_receiver_volume_text()
        if not label:
            return
        ink = _look_ink_rgb()
        key = (label, ink)
        cached = self._zone6_volume_patch
        if cached is None or cached[0] != key:
            font = _load_sharp_extrabold(_zone6_volume_font_px())
            patch, _pw, _ph = _text_patch_font(label, font=font, fill_rgb=ink)
            cached = (key, patch, _font_bbox_top(label, font))
            self._zone6_volume_patch = cached
        _key, patch, bbox_top = cached
        z6 = NOW_PLAYING_ZONES[6]
        _paste_baseline_centered(
            out, patch, float(z6.x) + float(z6.w) * 0.5, _zone3_clock_day_baseline_y(), bbox_top=bbox_top
        )

    def _draw_weather_zones(self, out: np.ndarray) -> None:
        assignments = self._assignments()
        if zone6_span_widget(assignments) == "weather":
            return
        for z_idx in (1, 2, 3, 4, 5):
            if assignments[z_idx - 1] != "weather":
                continue
            zone = _zone_spec(z_idx)
            self._paste_weather_cluster(out, zone.xywh)

    def _paste_weather_cluster(
        self, out: np.ndarray, box: tuple[int, int, int, int]
    ) -> None:
        from pigeon.widgets.clock_saver import render_clock_saver_weather_cluster_bgra

        try:
            cluster = render_clock_saver_weather_cluster_bgra(
                assets_dir=self._assets_dir
            )
        except Exception:
            return
        if cluster is None or cluster.size == 0:
            return
        x, y, w, h = (int(v) for v in box)
        cropped = _ink_crop_bgra(cluster, pad=2)
        if cropped is None or cropped.size == 0:
            return
        ph, pw = int(cropped.shape[0]), int(cropped.shape[1])
        if pw < 1 or ph < 1 or w < 1 or h < 1:
            return
        scale = min(w / float(pw), h / float(ph))
        nw = max(1, int(round(pw * scale)))
        nh = max(1, int(round(ph * scale)))
        resized = cv2.resize(
            cropped, (nw, nh), interpolation=cv_resize_interp(pw, ph, nw, nh)
        )
        _paste_patch_bgra(out, resized, x + (w - nw) // 2, y + (h - nh) // 2)

    def _draw_clock_date_above(
        self,
        out: np.ndarray,
        *,
        cx: float,
        cy: float,
        now: datetime,
    ) -> None:
        """Date now lives in ``_draw_clock_digital`` (day + month_date layers)."""
        del out, cx, cy, now
        return

    def _draw_zone0_date(
        self,
        out: np.ndarray,
        now: datetime,
        *,
        align: str | None = None,
    ) -> None:
        """Deprecated zone0 header path — no-op (date draws with the clock)."""
        return

    def _draw_audio_sep_line(
        self,
        out: np.ndarray,
        *,
        cx: float = _ZONE3_CX,
        cy: float = _ZONE1_CY,
    ) -> None:
        """Deprecated separator between in-ring volume/config — no-op."""
        return

    def _disc_clock_enabled(self) -> bool:
        """The disc clock follows the header-clock setting. Unlike the header slot
        it does not give way to the album title, so the music layout has one too."""
        return _header_clock_enabled() and not _zone_clock_hides_header(self._assignments())

    def _clock_in_volume_disc(self, vol_zone: int | None = None) -> bool:
        """True when the digital clock sits inside the zone-3 volume disc, above the
        number (a readout is showing and the header clock is enabled)."""
        if vol_zone is None:
            vol_zone = _zone_for_widget(self._assignments(), "volume")
        if vol_zone is None or int(vol_zone) != 3:
            return False
        if not self._disc_clock_enabled():
            return False
        vol_value = volume_widget_value_text(self._state.volume)
        muted = vol_value.strip().lower() in ("mute", "muted", "off") or self._state.volume_muted
        return bool(vol_value) and not muted

    def _disc_number_dy(self, number_h: int) -> float:
        """Offset of the volume number below the disc center so the clock/number
        pair (clock, gap, number) is centered together in the disc."""
        del number_h  # the pair is centered, so the number height cancels out
        clock_h = _disc_clock_ink_h()
        return (float(clock_h) + float(_DISC_CLOCK_GAP_PX)) * 0.5

    def _disc_clock_geometry(self) -> tuple[float, float, int] | None:
        """``(cx, ink_bottom_y, number_h)`` of the disc clock, or ``None``."""
        if not self._clock_in_volume_disc():
            return None
        z = _zone_spec(3)
        cx_v, cy_v = design_xy_from_local(
            z, VOLUME_LOCAL_CX, VOLUME_LOCAL_CY, view_w=VOLUME_VIEW_W, view_h=VOLUME_VIEW_H
        )
        vol_value = volume_widget_value_text(self._state.volume)
        _p, _w, vh = _volume_readout_patch(
            vol_value,
            inner_r=float(VOLUME_INNER_R) * _DISC_CLOCK_NUMBER_FIT,
            fill_rgb=_look_ink_rgb(),
        )
        num_dy = self._disc_number_dy(int(vh))
        bottom = cy_v + num_dy - float(vh) * 0.5 - float(_DISC_CLOCK_GAP_PX)
        return float(cx_v), float(bottom), int(vh)

    def _draw_audio_group(
        self,
        out: np.ndarray,
        *,
        cx: float = _ZONE3_CX,
        cy: float = _ZONE1_CY,
        zone: int | None = None,
    ) -> None:
        """Volume number centered in the disc; AVR input label under it."""
        del cx, cy
        assignments = self._assignments()
        vol_zone = int(zone) if zone is not None else _zone_for_widget(assignments, "volume")
        if vol_zone is None:
            return
        z = _zone_spec(vol_zone)
        st = self._state
        vol_value = volume_widget_value_text(st.volume)
        muted = vol_value.strip().lower() in ("mute", "muted", "off") or st.volume_muted

        if vol_value and not muted:
            cx_v, cy_v = design_xy_from_local(
                z,
                VOLUME_LOCAL_CX,
                VOLUME_LOCAL_CY,
                view_w=VOLUME_VIEW_W,
                view_h=VOLUME_VIEW_H,
            )
            clock_in_disc = self._clock_in_volume_disc(vol_zone)
            vol_p, vw, vh = _volume_readout_patch(
                vol_value,
                inner_r=(
                    float(VOLUME_INNER_R) * _DISC_CLOCK_NUMBER_FIT
                    if clock_in_disc
                    else VOLUME_INNER_R
                ),
                fill_rgb=_look_ink_rgb(),
            )
            num_dy = 0.0
            if clock_in_disc:
                num_dy = self._disc_number_dy(int(vh))
            _paste_centered(out, vol_p, cx_v, cy_v + num_dy)
            inner_r = float(VOLUME_INNER_R) * float(_VOLUME_TEXT_INNER_FIT)
            top_dy = num_dy + float(vh) * 0.5 + float(_VOLUME_INPUT_GAP_PX)
            label = volume_widget_format_label(
                st.incoming,
                st.config,
                receiver_input=str(st.receiver_input or "").strip(),
            )
            key = (label, int(vh), int(top_dy), self._effective_np_theme().cache_key)
            cached = self._input_caption_patch_cache
            if cached is not None and cached[0] == key:
                in_p, _iw, ih = cached[1]  # type: ignore[misc]
            else:
                in_p, _iw, ih = _volume_input_patch(
                    label,
                    top_dy=top_dy,
                    inner_r=inner_r,
                    max_h=max(0, int(inner_r - top_dy)),
                    fill_rgb=_look_ink_rgb(),
                )
                self._input_caption_patch_cache = (key, (in_p, _iw, ih))
            if ih > 1:
                _paste_centered(out, in_p, cx_v, cy_v + top_dy + float(ih) * 0.5)

    def _draw_circular_now_playing(
        self,
        out: np.ndarray,
        *,
        cx: float,
        cy: float,
        now: datetime | None = None,
    ) -> None:
        """Volume-ring chrome: red = watched; centered readout is time of day.

        No audio-config line (unlike the volume widget).
        """
        st = self._state
        pf = max(0.0, min(1.0, float(st.progress)))
        _draw_circle_pair(
            out,
            cx=cx,
            cy=cy,
            fraction=pf,
            show_accent=pf > 1e-6,
            theme=self._effective_np_theme(),
        )
        time_p, _, _ = _text_patch_digital7(
            _clock_hhmm(now),
            size_px=_CLOCK_DIGITAL_SIZE,
        )
        _paste_centered(out, time_p, cx, cy)

    def _draw_cast(self, out: np.ndarray, *, cast_zone: int = 4) -> None:
        assignments = self._assignments()
        z_idx = int(cast_zone)
        if not (1 <= z_idx <= 5) or assignments[z_idx - 1] != "cast_info":
            return
        start = 0
        for z in range(1, z_idx):
            if assignments[z - 1] == "cast_info":
                start += cast_names_for_zone(z)
        n_names = cast_names_for_zone(z_idx)
        cast = list(self._state.cast or [])[start : start + n_names]
        zone = _zone_spec(z_idx)
        if self._cast_widget_loading() and not any(
            str(actor or "").strip() or str(role or "").strip() for actor, role in cast
        ):
            self._draw_cast_shimmer(out, zone=zone, z_idx=z_idx)
            return
        if not any(
            str(actor or "").strip() or str(role or "").strip() for actor, role in cast
        ):
            self._draw_track_titles(out)
            return
        if z_idx in (4, 5):
            mid_y = float(zone.y) + float(zone.h) * 0.5
            for i, (x0, col_w) in enumerate(strip_cast_columns(zone)):
                actor, character = cast[i] if i < len(cast) else ("", "")
                _draw_stacked_cast_pair(
                    out,
                    actor=actor,
                    character=character,
                    cx=float(x0) + float(col_w) * 0.5,
                    max_width_px=max(48, int(col_w) - 24),
                    actor_px=CAST_ACTOR_SIZE_PX,
                    char_px=CAST_CHAR_SIZE_PX,
                    gap_px=CAST_STRIP_STACK_GAP_PX,
                    mid_y=mid_y,
                )
            return
        cx = float(zone.x) + float(zone.w) * 0.5
        max_w = max(80, int(round(zone.w - 32)))
        for i, (_actor_x, actor_y, char_y) in enumerate(CAST_LOCAL_ROWS):
            actor, character = cast[i] if i < len(cast) else ("", "")
            _ax, ay = design_xy_from_local(
                zone, 0.0, actor_y, view_w=CAST_VIEW_W, view_h=CAST_VIEW_H
            )
            _cx, cy = design_xy_from_local(
                zone, 0.0, char_y, view_w=CAST_VIEW_W, view_h=CAST_VIEW_H
            )
            del _ax, _cx
            ap = _cast_line_patch(
                actor, size_px=CAST_ACTOR_SIZE_PX, max_width_px=max_w
            )
            cp = _cast_line_patch(
                character, size_px=CAST_CHAR_SIZE_PX, max_width_px=max_w
            )
            # SVG y is the typographic baseline; ink-cropped patches sit on it.
            if ap is not None:
                _paste_ink_centered(out, ap, cx, ay - ap.shape[0])
            if cp is not None:
                _paste_ink_centered(out, cp, cx, cy - cp.shape[0])

    def _draw_cast_shimmer(
        self, out: np.ndarray, *, zone: NowPlayingZone, z_idx: int
    ) -> None:
        note = self._record_shimmer
        if z_idx in (4, 5):
            mid_y = float(zone.y) + float(zone.h) * 0.5
            for x0, col_w in strip_cast_columns(zone):
                bar_w = max(40, int(round(float(col_w) * 0.72)))
                actor_h, char_h = 22, 16
                gap = int(CAST_STRIP_STACK_GAP_PX)
                top = mid_y - (actor_h + gap + char_h) * 0.5
                cx = float(x0) + float(col_w) * 0.5
                _draw_shimmer_rounded_rect(
                    out,
                    x=int(round(cx - bar_w / 2.0)),
                    y=int(round(top)),
                    w=bar_w,
                    h=actor_h,
                    radius=8,
                    recorder=note,
                )
                _draw_shimmer_rounded_rect(
                    out,
                    x=int(round(cx - bar_w * 0.42)),
                    y=int(round(top + actor_h + gap)),
                    w=max(24, int(round(bar_w * 0.84))),
                    h=char_h,
                    radius=7,
                    recorder=note,
                )
            return
        max_w = max(80, int(round(zone.w - 48)))
        actor_w = int(round(max_w * 0.78))
        char_w = int(round(max_w * 0.55))
        cx = float(zone.x) + float(zone.w) * 0.5
        for _actor_x, actor_y, char_y in CAST_LOCAL_ROWS:
            _ax, ay = design_xy_from_local(
                zone, 0.0, actor_y, view_w=CAST_VIEW_W, view_h=CAST_VIEW_H
            )
            _cx, cy = design_xy_from_local(
                zone, 0.0, char_y, view_w=CAST_VIEW_W, view_h=CAST_VIEW_H
            )
            del _ax, _cx
            _draw_shimmer_rounded_rect(
                out,
                x=int(round(cx - actor_w / 2.0)),
                y=int(round(ay - 26.0)),
                w=actor_w,
                h=20,
                radius=8,
                recorder=note,
            )
            _draw_shimmer_rounded_rect(
                out,
                x=int(round(cx - char_w / 2.0)),
                y=int(round(cy - 20.0)),
                w=char_w,
                h=16,
                radius=7,
                recorder=note,
            )

    def _title_box_xywh(self, zone: int) -> tuple[int, int, int, int]:
        z = int(zone)
        if z == 4:
            return _zone4_title_xywh()
        spec = _zone_spec(z)
        x, y, w, h = spec.xywh
        return x, y, max(1, int(w)), max(8, int(h))

    def _draw_track_titles(self, out: np.ndarray) -> None:
        """Song or video name using the music title/artist/album stack."""
        st = self._state
        music = self.content_mode == _CONTENT_MODE_MUSIC
        youtube = bool(st.is_youtube) and not music
        if music:
            zone = 4
            subtitle_frac: float | None = None
        elif youtube:
            zone = 4
            subtitle_frac = _ZONE4_SUBTITLE_TOP_FRAC
        else:
            zone_i = _zone_for_widget(self._assignments(), "cast_info")
            if zone_i is None:
                return
            zone = int(zone_i)
            # Portrait (zone 3) auto-packs; the zone-4 strip keeps its grid frac.
            subtitle_frac = _ZONE4_SUBTITLE_TOP_FRAC if zone == 4 else None
        title, artist, album = self._info_text_lines()
        if music:
            album = ""
        zx, zy, zw, zh = self._title_box_xywh(zone)
        if not title and not artist and not album:
            if self._title_widget_loading():
                if zw >= 8 and zh >= 8:
                    bar_h = max(22, int(round(zh * 0.28)))
                    bar_w = max(80, int(round(zw * 0.52)))
                    _draw_shimmer_rounded_rect(
                        out,
                        x=zx,
                        y=zy + max(0, int(round((zh - bar_h) * 0.18))),
                        w=bar_w,
                        h=bar_h,
                        radius=12,
                        recorder=self._record_shimmer,
                    )
            return
        if zw < 8 or zh < 8:
            return
        try:
            from pigeon.view_one_variants import render_ui_music_text_patch_bgra
        except Exception:
            render_ui_music_text_patch_bgra = None  # type: ignore[assignment]
        patch = None
        if render_ui_music_text_patch_bgra is not None:
            kwargs: dict[str, object] = {}
            if subtitle_frac is not None:
                kwargs["subtitle_top_frac"] = subtitle_frac
            patch = render_ui_music_text_patch_bgra(
                title,
                artist,
                album,
                zw,
                zh,
                **kwargs,  # type: ignore[arg-type]
            )
        if patch is None or patch.size == 0:
            return
        if int(patch.shape[0]) > zh:
            patch = patch[:zh]
        _paste_patch_bgra(out, patch, zx, zy)

    def _draw_clock_saver_volume(self, out: np.ndarray) -> None:
        """Clock-saver volume line + Digital-7, sized to the assigned strip."""
        zone = _zone_for_widget(self._assignments(), "clock_saver_volume")
        if zone is None:
            return
        zx, zy, zw, zh = self._title_box_xywh(int(zone))
        if zw < 8 or zh < 8:
            return
        try:
            from pigeon.widgets.clock_saver import clock_saver_volume_strip_bgra
        except Exception:
            return
        rgb = _look_ink_rgb()
        patch = clock_saver_volume_strip_bgra(
            self._state.volume,
            width=zw,
            height=zh,
            color=(int(rgb[0]), int(rgb[1]), int(rgb[2]), 255),
            line_opacity=self._volume_line_opacity(),
        )
        if patch is None or patch.size == 0:
            return
        _paste_patch_bgra(out, patch, zx, zy)

    def _tt_source_bgra(self) -> np.ndarray | None:
        """Image for the TT slot: album art, TMDb logo, or the poster fallback."""
        if self.content_mode == _CONTENT_MODE_MUSIC or self._state.is_youtube:
            src = self._poster_bgra
            if src is not None and getattr(src, "size", 0) > 0:
                return src
        src = self._tt_bgra
        if src is not None and getattr(src, "size", 0) > 0:
            return src
        src = self._poster_bgra
        if src is not None and getattr(src, "size", 0) > 0:
            return src
        return None

    def _tt_art_is_poster_fallback(self) -> bool:
        """True when the artwork slot is using poster/album art, not a TT logo."""
        tt = self._tt_bgra
        if tt is not None and getattr(tt, "size", 0) > 0:
            return False
        poster = self._poster_bgra
        return poster is not None and getattr(poster, "size", 0) > 0

    def _tt_countdown_tt_patch(
        self,
        z: NowPlayingZone,
        *,
        wide: bool = False,
        dest_wh: tuple[int, int] | None = None,
    ) -> np.ndarray | None:
        """Title-treatment patch sized for the TT box, or a Sharp Sans fallback.

        Near-black TT art is recolored pure white; everything else displays
        unchanged. When no TT is cached, the title renders in Sharp Sans
        Semibold instead. ``dest_wh`` overrides the landscape box (portrait
        side-by-side uses an explicit size).
        """
        if dest_wh is not None:
            box_w = max(1, int(dest_wh[0]))
            box_h = max(1, int(dest_wh[1]))
        elif wide:
            tt_x, tt_y, tt_w, tt_h = tt_countdown_16x9_tt_box()
            view_w, view_h = TT_COUNTDOWN_16X9_VIEW_W, TT_COUNTDOWN_16X9_VIEW_H
            x0, y0 = design_xy_from_local(z, tt_x, tt_y, view_w=view_w, view_h=view_h)
            x1, y1 = design_xy_from_local(
                z,
                tt_x + tt_w,
                tt_y + tt_h,
                view_w=view_w,
                view_h=view_h,
            )
            box_w = max(1, int(round(x1 - x0)))
            box_h = max(1, int(round(y1 - y0)))
        else:
            tt_x, tt_y, tt_w, tt_h = tt_countdown_tt_box()
            view_w, view_h = TT_COUNTDOWN_VIEW_W, TT_COUNTDOWN_VIEW_H
            x0, y0 = design_xy_from_local(z, tt_x, tt_y, view_w=view_w, view_h=view_h)
            x1, y1 = design_xy_from_local(
                z,
                tt_x + tt_w,
                tt_y + tt_h,
                view_w=view_w,
                view_h=view_h,
            )
            box_w = max(1, int(round(x1 - x0)))
            box_h = max(1, int(round(y1 - y0)))
        src = self._tt_source_bgra()
        title = (
            str(self._state.tt_title or "").strip()
            or str(self._state.song_title or "").strip()
        )
        logo = None
        if (
            wide
            and (src is None or src.size == 0)
            and self.content_mode != _CONTENT_MODE_MUSIC
            and not self._tt_widget_loading()
        ):
            logo = _load_np_pigeon_logo_bgra(
                str(self._assets_dir / "nowPlaying" / NP_PIGEON_LOGO_FILENAME)
            )
        key: tuple[object, ...]
        if src is not None and src.size > 0:
            key = ("img", self.content_mode, id(src), box_w, box_h)
        elif logo is not None:
            # Nothing found for this video: the pigeon logo, not the typed title.
            src = logo
            key = ("logo", box_w, box_h)
        elif title:
            key = ("txt", title, box_w, box_h)
        else:
            return None
        if key in self._tt_patch_cache:
            return self._tt_patch_cache[key]
        patch: np.ndarray | None = None
        if src is not None and src.size > 0:
            arr = src
            if arr.ndim == 3 and arr.shape[2] == 3:
                arr = cv2.cvtColor(arr, cv2.COLOR_BGR2BGRA)
            if (
                self.content_mode != _CONTENT_MODE_MUSIC
                and key[0] != "logo"
                and not self._tt_art_is_poster_fallback()
            ):
                try:
                    from pigeon.tmdb_tt_contrast import whiten_dark_tt_bgra

                    arr = whiten_dark_tt_bgra(arr)
                except Exception:
                    pass
            sh, sw = arr.shape[:2]
            if sh >= 1 and sw >= 1:
                # Fill the divider width; shrink further only if too tall.
                scale = box_w / float(sw)
                if sh * scale > box_h:
                    scale = box_h / float(sh)
                nw = max(1, int(round(sw * scale)))
                nh = max(1, int(round(sh * scale)))
                patch = cv2.resize(
                    arr, (nw, nh), interpolation=cv_resize_interp(sw, sh, nw, nh)
                )
        elif title and not self._tt_widget_loading():
            probe_px = 100
            font = _load_sharp_semibold(probe_px)
            probe = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
            draw = ImageDraw.Draw(probe)
            l, t, r, b = draw.textbbox((0, 0), title, font=font)
            tw0, th0 = max(1, r - l), max(1, b - t)
            fit = box_w / float(tw0)
            if th0 * fit > box_h:
                fit = box_h / float(th0)
            size_px = max(16, int(probe_px * fit))
            font = _load_sharp_semibold(size_px)
            patch, _, _ = _text_patch_font(title, font=font, fill_rgb=(255, 255, 255))
        while len(self._tt_patch_cache) >= 4:
            self._tt_patch_cache.pop(next(iter(self._tt_patch_cache)))
        self._tt_patch_cache[key] = patch
        return patch

    def _zone11_on(self, assignments: tuple[str, ...] | list[str] | None = None) -> bool:
        """option5 = zone11 layout: TT across zones 1-3, input / volume / TRT in zone 4."""
        zones = self._assignments() if assignments is None else assignments
        return bool(zones) and str(zones[0] or "") == "tt_zone11"

    def _zone11_art_box(self) -> tuple[int, int, int, int]:
        zx, zy, zw, zh = ZONE11.xywh
        # Top padding clears the header clock that sits above zones 1-3.
        pad_top = max(36, int(round(float(header_clock_baseline_y()) + 10.0 - zy)))
        pad_side, pad_bottom = 40, 8
        return (
            zx + pad_side,
            zy + pad_top,
            max(1, zw - 2 * pad_side),
            max(1, zh - pad_top - pad_bottom),
        )

    # How far the art may reach up into the enlarged volume readout (design px); 0 = none.
    _ZONE11_ART_VOLUME_OVERLAP_PX = 0

    def _zone11_volume_bottom(self) -> float:
        """Design-Y the art must stay below: the header row at ``_ZONE11_ART_RESERVE_SCALE``."""
        return self._zone11_header_top() + self._zone11_header_ink_h() * float(
            self._ZONE11_ART_RESERVE_SCALE
        )

    def _draw_zone11_art(self, out: np.ndarray) -> None:
        """TT (or album art) scaled down so the volume readout has room above it.

        The art keeps its bottom-middle anchor (where it sat when centered in the full
        box) and only its top edge is pulled down, to the volume's bottom less a small
        overlap allowance.
        """
        z = ZONE11
        bx, by, bw, bh = self._zone11_art_box()
        new_top = max(
            by,
            int(round(self._zone11_volume_bottom() - self._ZONE11_ART_VOLUME_OVERLAP_PX)),
        )
        nbh = max(1, bh - (new_top - by))
        patch = self._tt_countdown_tt_patch(z, dest_wh=(bw, nbh))
        if patch is None or patch.size == 0:
            if self._tt_widget_loading() and not self._zone11_loading():
                sh_h = max(56, int(round(nbh * 0.42)))
                _draw_shimmer_rounded_rect(
                    out,
                    x=bx + (bw - int(bw * 0.8)) // 2,
                    y=new_top + (nbh - sh_h) // 2,
                    w=int(bw * 0.8),
                    h=sh_h,
                    radius=int(round(float(WIDGET_SHIMMER_RADIUS))),
                    recorder=self._record_shimmer,
                )
            return
        ph, pw = int(patch.shape[0]), int(patch.shape[1])
        # Bottom of the art as it was when centered in the full box.
        full = self._tt_countdown_tt_patch(z, dest_wh=(bw, bh))
        full_ph = int(full.shape[0]) if full is not None and full.size else ph
        bottom = by + (bh - full_ph) // 2 + full_ph
        y = max(new_top, bottom - ph)
        _paste_patch_bgra(out, patch, bx + (bw - pw) // 2, min(y, by + bh - ph))

    # Larger than the cast-info names (CAST_ACTOR_SIZE_PX): the strip has no second line.
    _ZONE11_INFO_PX = 68
    _ZONE11_APP_ID_PX = 46
    _ZONE11_APP_ID_GAP = 10
    # Fixed multiple of the header size; independent of the art so it never jumps
    # when the title / poster finishes loading.
    _ZONE11_VOLUME_SCALE = 2.0
    # The art keeps clearing the row as it was sized at this scale, so shrinking the
    # header text opens a gap above the art instead of pulling the art up.
    _ZONE11_ART_RESERVE_SCALE = 2.5
    # Header row (clock, volume, labels) sits a little lower, and the volume clear of the edge.
    _ZONE11_HEADER_DROP_PX = 14
    _ZONE11_VOLUME_RIGHT_PAD_PX = 14
    _ZONE11_STACK_CLOCK_GAP_PX = 24

    def _zone11_clock_half_width(self) -> float:
        """Half the width of the centered header clock at its widest (``88:88AM``)."""
        size = int(round(_header_digital7_size_px() * float(self._ZONE11_VOLUME_SCALE)))
        patch = _matching_hhmm_patch("88:88AM", size_px=size, fill_rgb=_look_chrome_rgb())
        cols = np.where((patch[:, :, 3] > 8).any(axis=0))[0]
        return float(cols.max() - cols.min() + 1) / 2.0 if cols.size else 0.0

    def _zone11_service_label(self) -> str:
        """Streaming app / incoming source name (the status bar's service text)."""
        st = self._state
        svc = str(st.service_name or "").strip()
        if svc.lower() in ("", "unknown", "none", "n/a", "na", "--"):
            svc = str(st.incoming or "").strip()
        if svc.lower() in ("", "unknown", "none", "n/a", "na", "--"):
            return ""
        return svc

    def _zone11_header_ink_h(self) -> float:
        """Ink height of one unscaled header digit (the clock's height before scaling)."""
        patch, _tw, _th = _text_patch_digital7(
            "0", size_px=_header_digital7_size_px(), fill_rgb=_look_chrome_rgb()
        )
        rows = np.where((patch[:, :, 3] > 8).any(axis=1))[0]
        return float(rows.max() - rows.min() + 1) if rows.size else 0.0

    def _zone11_header_top(self) -> float:
        """Design-Y of the top of the header row (clock, volume, label stack)."""
        return (
            float(header_clock_baseline_y())
            - self._zone11_header_ink_h()
            + float(self._ZONE11_HEADER_DROP_PX)
        )

    def _paste_zone11_corner_text(
        self,
        out: np.ndarray,
        label: str,
        *,
        align: str,
        fill_rgb: tuple[int, int, int],
        clock: bool = False,
        scale: float = 1.0,
    ) -> tuple[int, int, int, int] | None:
        """Header-size Digital-7, top-aligned on the header row.

        ``align`` is ``left``, ``center`` or ``right`` within zone 11 (right keeps a small
        inset from the edge).
        """
        if not label:
            return None
        size = int(round(_header_digital7_size_px() * float(scale)))
        if clock:
            patch = _matching_hhmm_patch(
                label, size_px=size, fill_rgb=fill_rgb, pad_y=size // 2
            )
        else:
            patch, _tw, _th = _text_patch_digital7(
                label.upper(), size_px=size, fill_rgb=fill_rgb
            )
        a = patch[:, :, 3] > 8
        rows, cols = np.where(a.any(axis=1))[0], np.where(a.any(axis=0))[0]
        if rows.size == 0:
            return None
        patch = patch[int(rows.min()) : int(rows.max()) + 1, int(cols.min()) : int(cols.max()) + 1]
        ph, pw = patch.shape[:2]
        z = ZONE11
        if align == "left":
            x = int(round(float(z.x)))
        elif align == "center":
            x = int(round(float(z.x) + (float(z.w) - pw) / 2.0))
        else:
            x = int(round(float(z.x) + float(z.w) - pw - float(self._ZONE11_VOLUME_RIGHT_PAD_PX)))
        y = int(round(self._zone11_header_top()))
        _paste_patch_bgra(out, patch, x, y)
        return (x, y, int(pw), int(ph))

    def _zone11_bar_rect(self) -> tuple[int, int, int, int] | None:
        """``(x, y, w, h)`` of the status bar track the elapsed time rides along."""
        for i, name in enumerate(self._assignments()[:5]):
            if is_status_bar_widget(name, i + 1):
                zone = _zone_spec(i + 1)
                tx, ty, tw, th, _trx = design_rect_from_local(
                    zone,
                    STATUS_BAR_TRACK,
                    view_w=STATUS_BAR_VIEW_W,
                    view_h=STATUS_BAR_VIEW_H,
                )
                return int(tx), int(ty), int(tw), int(th)
        return None

    def _zone11_bar_track(self) -> tuple[int, int] | None:
        """``(track_x, track_w)`` of the status bar the elapsed time rides along."""
        rect = self._zone11_bar_rect()
        return None if rect is None else (rect[0], rect[2])

    def _draw_zone11_info(self, out: np.ndarray) -> None:
        """Top-right: volume (2x header size). Top-left: input id (same size). Under the
        status bar: app id. Zone 4 strip: elapsed
        riding the status bar's playhead (gray, fading before it meets the TRT) and
        the TRT in the title's UI color."""
        zone = _zone_spec(4)
        zx, zy, zw, zh = (int(v) for v in zone.xywh)
        self._tt_time_paint_rects.append((zx, zy, zw, zh))
        recv = self._has_receiver_connection()
        vol = _receiver_volume_display_line(self._state.volume) if recv else ""
        # Drop the unit: the big readout is self-explanatory and the width matters.
        vol = re.sub(r"\s*dB\s*$", "", vol)

        # Top-left: input id at the header size (same as the clock / volume). It is
        # shrunk only as far as needed to clear the centered clock.
        z = ZONE11
        max_w = int(
            float(z.w) * 0.5
            - self._zone11_clock_half_width()
            - float(self._ZONE11_STACK_CLOCK_GAP_PX)
        )
        size = int(round(_header_digital7_size_px() * float(self._ZONE11_VOLUME_SCALE)))
        pt = _cast_line_patch(self._receiver_readout(), size_px=size, max_width_px=max(80, max_w))
        if pt is not None:
            px, py = int(round(float(z.x))), int(round(self._zone11_header_top()))
            _paste_patch_bgra(out, pt, px, py)
            self._tt_time_paint_rects.append((px, py, int(pt.shape[1]), int(pt.shape[0])))

        # Bottom-left, just under the status bar: streaming app id.
        bar = self._zone11_bar_rect()
        app = _cast_line_patch(
            self._zone11_service_label(),
            size_px=self._ZONE11_APP_ID_PX,
            max_width_px=max(80, int(float(z.w) * 0.5)),
        )
        if bar is not None and app is not None:
            bx, by, _bw, bh = bar
            ax, ay = bx, by + bh + int(self._ZONE11_APP_ID_GAP)
            _paste_patch_bgra(out, app, ax, ay)
            self._tt_time_paint_rects.append((ax, ay, int(app.shape[1]), int(app.shape[0])))

        # Top-right: volume.
        rect = self._paste_zone11_corner_text(
            out,
            vol,
            align="right",
            fill_rgb=_look_chrome_rgb(),
            scale=self._ZONE11_VOLUME_SCALE,
        )
        if rect is not None:
            self._tt_time_paint_rects.append(rect)

        # Strip: TRT (right column) and the traveling elapsed time.
        if self.content_mode == _CONTENT_MODE_MUSIC or self._zone11_loading():
            return
        mid_y = float(zy) + float(zh) * 0.5
        cols = strip_cast_columns(zone)
        trt_left: float | None = None
        trt_bottom = mid_y
        right = format_countdown_timecode(self._state.remaining_text) or ""
        if right and len(cols) >= 3:
            x0, col_w = cols[2]
            template = re.sub(r"\d", "8", right)
            size = _header_trt_size_px(template, max(48, int(col_w) - 24), self._ZONE11_INFO_PX)
            fill_rgb = tuple(reversed(self._effective_np_theme().ui_bgr))
            patch = _matching_hhmm_patch(right, size_px=size, fill_rgb=fill_rgb, pad_y=size // 2)
            a = patch[:, :, 3] > 8
            rows, pcols = np.where(a.any(axis=1))[0], np.where(a.any(axis=0))[0]
            if rows.size:
                patch = patch[
                    int(rows.min()) : int(rows.max()) + 1,
                    int(pcols.min()) : int(pcols.max()) + 1,
                ]
                ph, pw = patch.shape[:2]
                px = int(round(float(x0) + float(col_w) * 0.5 - pw / 2.0))
                py = int(round(mid_y - ph / 2.0))
                self._paste_trt_with_plate(out, patch, px, py)
                trt_left = float(px)
                trt_bottom = float(py + ph)

        elapsed = format_status_bar_timecode(self._state.elapsed_text, remaining=False)
        track = self._zone11_bar_track()
        if not elapsed or elapsed.upper() == "LIVE" or track is None:
            return
        # Same size and gray as the volume readout in the top-right corner.
        patch = _matching_hhmm_patch(
            elapsed,
            size_px=_header_digital7_size_px(),
            fill_rgb=_look_chrome_rgb(),
            pad_y=_header_digital7_size_px() // 2,
        )
        a = patch[:, :, 3] > 8
        rows, pcols = np.where(a.any(axis=1))[0], np.where(a.any(axis=0))[0]
        if rows.size == 0:
            return
        patch = patch[int(rows.min()) : int(rows.max()) + 1, int(pcols.min()) : int(pcols.max()) + 1]
        ph, pw = patch.shape[:2]
        tx, tw = track
        pf = max(0.0, min(1.0, float(self._state.progress)))
        left = status_bar_elapsed_left_x(
            track_x=float(tx),
            track_w=float(tw),
            progress=pf,
            elapsed_w=float(pw),
            remaining_left_x=trt_left,
        )
        alpha = status_bar_elapsed_opacity(
            track_x=float(tx),
            track_w=float(tw),
            progress=pf,
            elapsed_w=float(pw),
            remaining_left_x=trt_left,
        )
        if alpha <= 0.01:
            return
        if alpha < 0.999:
            patch = _fade_bgra(patch, alpha)
        _paste_patch_bgra(
            out, patch, int(round(left)), int(round(trt_bottom - ph))
        )

    def _draw_tt_countdowns(self, out: np.ndarray, *, part: str = "all") -> None:
        assignments = self._assignments()
        if self._zone11_on(assignments):
            if part in ("all", "art"):
                self._draw_zone11_art(out)
            if part in ("all", "time"):
                self._draw_zone11_info(out)
            return
        for z in (1, 2, 3):
            if assignments[z - 1] == "tt_countdown":
                self._draw_tt_countdown(out, zone=z, part=part)
        wide_tt_zone = tt_countdown_16x9_zone(assignments)
        if wide_tt_zone is not None and not self._paused_clock_in_zone6():
            self._draw_tt_countdown(out, zone=int(wide_tt_zone), wide=True, part=part)

    def _paste_header_digital7(
        self,
        out: np.ndarray,
        label: str,
        cx: float,
        *,
        fill_rgb: tuple[int, int, int] = (255, 255, 255),
    ) -> tuple[int, int, int, int] | None:
        """Digital-7 header text (clock / TRT) centered on ``cx``, ink bottom on
        the header baseline. Returns the painted ``(x, y, w, h)``."""
        patch = _matching_hhmm_patch(
            label, size_px=_header_digital7_size_px(), fill_rgb=fill_rgb
        )
        rows = np.where(patch[:, :, 3] > 8)[0]
        if rows.size == 0:
            return None
        patch = patch[int(rows.min()) : int(rows.max()) + 1]
        ph, pw = patch.shape[:2]
        px = int(round(cx - pw / 2.0))
        py = int(round(header_clock_baseline_y() - ph))
        _paste_patch_bgra(out, patch, px, py)
        return (px, py, int(pw), int(ph))

    def _draw_header_trt(self, out: np.ndarray, wide_zone: int, label: str) -> None:
        """Header TRT: Digital-7 in the UI color, centered above the zone-3
        volume disc and sized to the band above the ring. If the header clock
        is drawn over zone 3 (no readout to hold it in the disc), the TRT
        stays centered at the top of the wide TT's zone instead."""
        clock_over_zone3 = self._header_slot_ticks() and not self._clock_in_volume_disc()
        cx, top, max_w, max_h = header_trt_ink_box(int(wide_zone), over_volume=not clock_over_zone3)
        template = re.sub(r"\d", "8", label)
        size = _header_trt_size_px(template, int(max_w), int(max_h))
        fill_rgb = tuple(reversed(self._effective_np_theme().ui_bgr))
        patch = _matching_hhmm_patch(label, size_px=size, fill_rgb=fill_rgb, pad_y=size // 2)
        a = patch[:, :, 3] > 8
        rows, cols = np.where(a.any(axis=1))[0], np.where(a.any(axis=0))[0]
        if rows.size == 0:
            return
        patch = patch[int(rows.min()) : int(rows.max()) + 1, int(cols.min()) : int(cols.max()) + 1]
        ph, pw = patch.shape[:2]
        px = int(round(cx - pw / 2.0))
        py = int(round(top + (max_h - ph) / 2.0))
        self._paste_trt_with_plate(out, patch, px, py)

    def _paste_trt_with_plate(self, out: np.ndarray, patch: np.ndarray, px: int, py: int) -> None:
        """Paste TRT digits on a soft black plate (heavily blurred, 50% opaque)."""
        import cv2

        ph, pw = patch.shape[:2]
        pad_x = max(10, int(round(ph * 0.45)))
        pad_y = max(6, int(round(ph * 0.28)))
        sigma = max(4.0, ph * 0.42)
        margin = int(round(sigma * 3))  # room for the blur to fade out
        plate = cv2.copyMakeBorder(
            _black_rounded_plate(int(pw) + 2 * pad_x, int(ph) + 2 * pad_y),
            margin, margin, margin, margin, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0),
        )
        alpha = cv2.GaussianBlur(plate[:, :, 3], (0, 0), sigma).astype(np.float32)
        # A wide blur drains the middle of a short plate; renormalize so the
        # shape keeps its size (its edge stays the half-strength contour).
        peak = float(alpha.max())
        if peak > 0:
            alpha = np.minimum(alpha * (255.0 / peak), 255.0)
        plate[:, :, 3] = (alpha * 0.5).astype(np.uint8)
        ox, oy = px - pad_x - margin, py - pad_y - margin
        _paste_patch_bgra(out, plate, ox, oy)
        _paste_patch_bgra(out, patch, px, py)
        self._tt_time_paint_rects.append((ox, oy, int(plate.shape[1]), int(plate.shape[0])))

    def _draw_tt_countdown(
        self, out: np.ndarray, *, zone: int, wide: bool = False, part: str = "all"
    ) -> None:
        """TT art anchored above the divider guide, live countdown hanging below.

        The countdown text consumes ``remaining_text``, which the host updates
        every second from the drift-corrected playback clock — it starts at the
        content's total running time and counts down in real time. The timecode
        formatter drops leading-zero fields, so the readout shortens naturally
        (e.g. "-1:00:00" ticks to "-59:59").

        ``wide`` selects the 16:9 (zone 6/7) geometry. Landscape TTs width-fit
        the divider box, seat on the horizontal guide, then lift so the group
        is vertically centered in the widget. Portrait TTs (too tall to
        width-fit) go side-by-side: left-aligned art, right-aligned TRT.
        Music skips the countdown and centers album art in the widget.

        ``part`` limits what is pasted: ``"art"`` (static frame) or ``"time"``
        (ticking overlay, so the TRT advances every second). Layout always
        uses both, so the halves line up exactly.
        """
        if wide:
            tt_box_fn = tt_countdown_16x9_tt_box
            view_w, view_h = TT_COUNTDOWN_16X9_VIEW_W, TT_COUNTDOWN_16X9_VIEW_H
        else:
            tt_box_fn = tt_countdown_tt_box
            view_w, view_h = TT_COUNTDOWN_VIEW_W, TT_COUNTDOWN_VIEW_H
        z = _zone_spec(int(zone))
        st = self._state
        music = self.content_mode == _CONTENT_MODE_MUSIC or bool(st.is_youtube)
        tpatch = None
        if not music:
            label = format_countdown_timecode(st.remaining_text)
            if label and wide:
                # 16:9 TRT lives in the header slot above the art, so the art
                # lays out alone below.
                if part in ("all", "time"):
                    self._draw_header_trt(out, int(zone), label)
            elif label:
                sx = float(z.w) / view_w
                size_px = max(12, int(round(TT_COUNTDOWN_TEXT_SIZE_PX * sx)))
                tpatch = _tt_countdown_time_patch(label, size_px=size_px)

        shimmer_id = None
        shimmer_radius = max(8, int(round(float(WIDGET_SHIMMER_RADIUS))))

        def _paste_group(pastes: list[tuple[np.ndarray, int, int]]) -> None:
            if not pastes:
                return

            def _ink_y_span(
                img: np.ndarray, px: int, py: int
            ) -> tuple[float, float] | None:
                if img is None or img.size == 0 or img.ndim < 3 or img.shape[2] < 4:
                    return None
                ys = np.where(img[:, :, 3] > 8)[0]
                if ys.size == 0:
                    return None
                return (float(py) + float(ys.min()), float(py) + float(ys.max()) + 1.0)

            spans = [
                span
                for img, px, py in pastes
                if (span := _ink_y_span(img, px, py)) is not None
            ]
            if not spans:
                return
            y0 = min(s[0] for s in spans)
            y1 = max(s[1] for s in spans)
            zx, zy, zw, zh = z.xywh
            dy = 0.0
            art_min_top = float(zy) + float(NP_ZONE6_ART_MIN_TOP_PX)
            if wide:
                # Zone 6/7: the TRT lives in the header slot, so the art is
                # always centered on the zone (no volume alignment / clamps).
                dy = float(zy) + float(zh) * 0.5 - (y0 + y1) * 0.5
            elif layout_shows_tt_countdown_and_volume(self._assignments()):
                vol_zone = _zone_for_widget(self._assignments(), "volume")
                if vol_zone is not None:
                    _vcx, vcy = _zone_volume_center(int(vol_zone))
                    dy = tt_countdown_volume_align_dy(
                        plate_top=y0,
                        plate_bottom=y1,
                        volume_cy=vcy,
                        zone_top=float(zy),
                        zone_bottom=float(zy + zh),
                    )
            else:
                zone_cy = float(zy) + float(zh) * 0.5
                dy = zone_cy - (y0 + y1) * 0.5
                min_dy = art_min_top - y0
                max_dy = float(zy + zh) - y1
                if max_dy >= min_dy:
                    dy = min(max(dy, min_dy), max_dy)
            if abs(dy) >= 0.5:
                pastes = [
                    (img, px, int(round(float(py) + dy)))
                    for img, px, py in pastes
                ]
            for img, px, py in pastes:
                is_time = tpatch is not None and img is tpatch
                if (part == "art" and is_time) or (part == "time" and not is_time):
                    continue
                _paste_patch_bgra(out, img, px, py)
                if is_time and part == "time":
                    self._tt_time_paint_rects.append(
                        (px, py, int(img.shape[1]), int(img.shape[0]))
                    )
                if shimmer_id is not None and id(img) == shimmer_id:
                    self._record_shimmer(
                        px, py, int(img.shape[1]), int(img.shape[0]), shimmer_radius
                    )

        src = self._tt_source_bgra()
        if (
            music
            and src is not None
            and src.size > 0
            and src.ndim >= 2
        ):
            rect = tt_countdown_centered_art_rect(
                float(src.shape[1]),
                float(src.shape[0]),
                view_w=view_w,
                view_h=view_h,
            )
            x0, y0 = design_xy_from_local(
                z, rect[0], rect[1], view_w=view_w, view_h=view_h
            )
            x1, y1 = design_xy_from_local(
                z,
                rect[0] + rect[2],
                rect[1] + rect[3],
                view_w=view_w,
                view_h=view_h,
            )
            dest_w = max(1, int(round(x1 - x0)))
            dest_h = max(1, int(round(y1 - y0)))
            patch = self._tt_countdown_tt_patch(
                z, wide=wide, dest_wh=(dest_w, dest_h)
            )
            pastes: list[tuple[np.ndarray, int, int]] = []
            if patch is not None and patch.size > 0:
                ph, pw = int(patch.shape[0]), int(patch.shape[1])
                px = int(round(x0 + (dest_w - pw) / 2.0))
                py = int(round(y0 + (dest_h - ph) / 2.0))
                pastes.append((patch, px, py))
            _paste_group(pastes)
            return

        portrait_wide = False
        if (
            wide
            and src is not None
            and src.size > 0
            and src.ndim >= 2
        ):
            sh, sw = int(src.shape[0]), int(src.shape[1])
            portrait_wide = tt_countdown_16x9_tt_is_portrait(sw, sh)

        if portrait_wide:
            # Centered, shrunk symmetrically so its top clears the header TRT band.
            _tcx, trt_top, _tw, trt_h = header_trt_ink_box(int(zone))
            header_clear_d = max(
                float(header_clock_baseline_y()), float(trt_top) + float(trt_h)
            ) + 8.0 - float(z.y)
            pad = max(
                float(TT_COUNTDOWN_BG_PAD),
                header_clear_d * view_h / max(float(z.h), 1.0),
            )
            tt_rect = tt_countdown_centered_art_rect(
                float(src.shape[1]),
                float(src.shape[0]),
                view_w=view_w,
                view_h=view_h,
                pad=pad,
            )
            x0, y0 = design_xy_from_local(
                z, tt_rect[0], tt_rect[1], view_w=view_w, view_h=view_h
            )
            x1, y1 = design_xy_from_local(
                z,
                tt_rect[0] + tt_rect[2],
                tt_rect[1] + tt_rect[3],
                view_w=view_w,
                view_h=view_h,
            )
            dest_w = max(1, int(round(x1 - x0)))
            dest_h = max(1, int(round(y1 - y0)))
            patch = self._tt_countdown_tt_patch(
                z, wide=True, dest_wh=(dest_w, dest_h)
            )
            pastes: list[tuple[np.ndarray, int, int]] = []
            if patch is not None and patch.size > 0:
                ph, pw = int(patch.shape[0]), int(patch.shape[1])
                px = int(round(x0 + (dest_w - pw) / 2.0))
                py = int(round(y0 + (dest_h - ph) / 2.0))
                pastes.append((patch, px, py))
            _paste_group(pastes)
            return

        patch = self._tt_countdown_tt_patch(z, wide=wide)
        if (patch is None or patch.size == 0) and self._tt_widget_loading():
            tt_x, tt_y, tt_w, tt_h = tt_box_fn()
            x0, y0 = design_xy_from_local(
                z, tt_x, tt_y, view_w=view_w, view_h=view_h
            )
            x1, y1 = design_xy_from_local(
                z, tt_x + tt_w, tt_y + tt_h, view_w=view_w, view_h=view_h
            )
            box_w = max(1, int(round(x1 - x0)))
            box_h = max(1, int(round(y1 - y0)))
            sh_h = max(56, int(round(box_h * 0.42)))
            patch = _shimmer_base_patch_bgra(
                box_w,
                sh_h,
                radius=shimmer_radius,
            )
            shimmer_id = id(patch)
        scale_y = view_h / max(float(z.h), 1.0)
        tt_local_h = 0.0
        trt_local_h = 0.0
        if patch is not None and patch.size > 0:
            tt_local_h = float(patch.shape[0]) * scale_y
        if tpatch is not None and tpatch.size > 0:
            trt_local_h = float(tpatch.shape[0]) * scale_y
        if wide:
            lift = tt_countdown_16x9_content_lift(
                tt_local_h,
                trt_height=trt_local_h,
            )
        else:
            lift = tt_countdown_portrait_content_lift(
                tt_local_h, trt_height=trt_local_h
            )
        pastes = []
        if patch is not None and patch.size > 0:
            tt_x, tt_y, tt_w, tt_h = tt_box_fn()
            ph, pw = patch.shape[:2]
            cx_d, bottom_d = design_xy_from_local(
                z,
                tt_x + tt_w / 2.0,
                tt_y + tt_h - lift,
                view_w=view_w,
                view_h=view_h,
            )
            px = cx_d - pw / 2.0
            py = bottom_d - ph
            pastes.append((patch, int(round(px)), int(round(py))))
        if tpatch is not None and tpatch.size > 0:
            ax, ay = (
                tt_countdown_16x9_time_anchor(lift=lift)
                if wide
                else tt_countdown_time_anchor()
            )
            if not wide:
                ay -= lift
            cx_d, top_d = design_xy_from_local(
                z, ax, ay, view_w=view_w, view_h=view_h
            )
            tw_p = tpatch.shape[1]
            px = cx_d - tw_p / 2.0
            pastes.append((tpatch, int(round(px)), int(round(top_d))))
        _paste_group(pastes)

    def _render_zone10_pausesaver_bgra(self) -> np.ndarray:
        """Fullscreen TMDb backdrop, paused plate in zone 4, status in zone 5."""
        from pigeon.paused_screen import (
            compose_pausesaver_backdrop_bgr,
            pausesaver_backdrop,
            render_pausesaver_plate_bgra,
        )

        out = _fallback_base_bgra()
        backdrop = compose_pausesaver_backdrop_bgr(
            int(DESIGN_W), int(DESIGN_H), pausesaver_backdrop()
        )
        out[:, :, :3] = backdrop
        out[:, :, 3] = 255
        z4 = NOW_PLAYING_ZONES[4]
        plate = render_pausesaver_plate_bgra(int(round(z4.w)), int(round(z4.h)))
        _paste_patch_bgra(out, plate, int(round(z4.x)), int(round(z4.y)))
        # Status bar is stamped by _overlay_ticking; baking it here leaves stale timecodes.
        return out

    def _render_static_bgra(self) -> np.ndarray:
        self._shimmer_rects = []
        now = self._clock_now_for_display()
        assignments = self._assignments()
        if self._zone10_pausesaver_active():
            return self._render_zone10_pausesaver_bgra()
        if _layout_is_fullscreen_clock(assignments):
            out = _fallback_base_bgra()
            clock = render_centered_clock_widget_bgra(
                assets_dir=self._assets_dir,
                now=now,
            )
            _paste_patch_bgra(out, clock, 0, 0)
            return out
        theme = self._effective_np_theme()
        # Everything up to the SVG chrome is independent of the volume level, and
        # pasting those full-frame layers is most of a rebuild (~140 ms on the Pi).
        # A volume step reuses them and redraws only what depends on the level.
        base_key = self._cache_sig(ticking=False, volume=False)
        cached_base = self._static_base
        if cached_base is not None and cached_base[0] == base_key:
            out = cached_base[1].copy()
            self._shimmer_rects = list(cached_base[2])
        else:
            out = _fallback_base_bgra()
            has_poster = self._poster_bgra is not None and self._poster_bgra.size > 0
            if self._state.content_active and has_poster and not self._state.searching:
                blur = self._ensure_artwork_blur_bgra()
                if blur is not None:
                    _paste_patch_bgra(out, blur, 0, 0)
            elif _NP_NO_POSTER_UI_WASH and self._state.content_active and not has_poster:
                # No TMDb poster to blur: wash the page in the UI color instead.
                _paste_patch_bgra(out, self._ui_color_wash_bgra(theme), 0, 0)
            # Poster/album under play overlay; SVG chrome sits in sibling zones.
            self._draw_poster(out)
            self._draw_play_overlay(out)
            _paste_patch_bgra(out, self._render_svg_base(now), 0, 0)
            self._static_base = (base_key, out.copy(), list(self._shimmer_rects))
        vol_zone = _zone_for_widget(assignments, "volume")
        if vol_zone is not None:
            vol_frac = self._volume_fraction_for_display()
            vcx, vcy = _zone_volume_center(int(vol_zone))
            _draw_volume_selected_pie(
                out, cx=vcx, cy=vcy, fraction=vol_frac, theme=theme
            )
            self._draw_audio_group(out, zone=int(vol_zone))
        self._draw_clock_saver_volume(out)
        self._draw_clock_digital(out, now)
        self._draw_zone6_span_widget(out)
        self._draw_weather_zones(out)
        self._draw_seconds_bar_zones(out, now)
        self._draw_pigeonclock_zones(out)
        self._draw_zone4_overlay_text(out)
        if (
            self.content_mode == _CONTENT_MODE_MUSIC or self._state.is_youtube
        ) and self._assignments()[3] not in (ZONE4_VISUALIZER_WIDGET, "zone11_info"):
            self._draw_track_titles(out)
        # Status bar is stamped by _overlay_ticking; the static sig ignores its
        # timecodes, so baking it here would leave stale digits under the live ones.
        self._draw_header_clock(out, now)
        # TRT digits are stamped by _overlay_ticking (_draw_tt_countdown_times);
        # the static sig ignores remaining_text, so baking them here froze them.
        self._draw_tt_countdowns(out, part="art")
        if self.content_mode != _CONTENT_MODE_MUSIC and not self._state.is_youtube:
            for z in (1, 2, 3, 4, 5):
                if assignments[z - 1] == "cast_info":
                    self._draw_cast(out, cast_zone=z)
        return out

    def overlay_status_bar(self, canvas_bgr: np.ndarray) -> bool:
        """Composite the NP status bar onto an existing BGR canvas (settings_main)."""
        if canvas_bgr is None or canvas_bgr.size == 0 or canvas_bgr.ndim < 3:
            return False
        bar_zone = configured_status_bar_zone()
        if bar_zone is None:
            return False
        self._advance_status_bar_handoff()
        zone = _zone_spec(int(bar_zone))
        zx, zy, zw, zh = (int(v) for v in zone.xywh)
        ch, cw = int(canvas_bgr.shape[0]), int(canvas_bgr.shape[1])
        y0 = max(0, zy)
        x0 = max(0, zx)
        y1 = min(ch, zy + zh)
        x1 = min(cw, zx + zw)
        if y1 <= y0 or x1 <= x0:
            return False
        dh, dw = int(DESIGN_H), int(DESIGN_W)
        layer = self._bar_overlay_layer
        if layer is None or layer.shape[0] != dh or layer.shape[1] != dw:
            layer = np.zeros((dh, dw, 4), dtype=np.uint8)
            self._bar_overlay_layer = layer
        else:
            layer[y0:y1, x0:x1] = 0
        self._draw_status_bar(layer, zone=int(bar_zone))
        bar = layer[y0:y1, x0:x1]
        if int(bar[:, :, 3].max()) < 8:
            return False
        roi = canvas_bgr[y0:y1, x0:x1]
        roi[:] = alpha_blend_bgra_over_bgr(roi, bar)
        return True

    def _stamp_current_poster_protect(self) -> None:
        """Mark the live poster/thumbnail so bright mode does not invert it."""
        from pigeon.compositing import (
            clear_bright_artwork_mask,
            clear_bright_slant_mask,
            stamp_bright_artwork_mask,
        )

        clear_bright_artwork_mask()
        clear_bright_slant_mask()
        if self._state.searching:
            return
        poster_zone = self._poster_zone()
        if poster_zone is None:
            return
        src = self._poster_bgra
        if src is None or src.size == 0:
            return
        px, py, pw, ph, prx = _poster_geometry(
            self.content_mode, zone=int(poster_zone)
        )
        stamp_bright_artwork_mask(_rounded_rect_mask(pw, ph, prx), px, py)

    def _live_audio_widgets_on(self) -> bool:
        keys = self._assignments()
        return "vu" in keys or zone6_span_widget(keys) in ("vu", ZONE6_VISUALIZER_WIDGET)

    @staticmethod
    def _zone6_viz_on(assignments: tuple[str, ...] | list[str]) -> bool:
        return zone6_span_widget(assignments) == ZONE6_VISUALIZER_WIDGET

    def rotate_zone6_visualizer(self, steps: int) -> bool:
        """Encoder turn in visualizer mode: next / previous preset. False when not showing."""
        if not self._zone6_viz_on(self._assignments()):
            return False
        self._zone6_visualizer().rotate(int(steps))
        return True

    def _zone6_visualizer(self):
        if self._zone6_viz is None:
            from pigeon.fullscreen_viz import FullscreenViz

            self._zone6_viz = FullscreenViz(remember=True)
            zw, zh = NOW_PLAYING_ZONES[6].xywh[2:]
            # Build every preset's static art now, so the first turn to each
            # preset does not stall a frame on the Pi.
            threading.Thread(
                target=self._zone6_viz.prewarm,
                args=(int(round(zw)), int(round(zh))),
                kwargs={"clear": True},
                name="pigeon-zone6-viz-prewarm",
                daemon=True,
            ).start()
        return self._zone6_viz

    def _zone4_eq_on(self) -> bool:
        """Settings option4 = visualizer (see ``pigeon/zone4_eq.py``)."""
        if not self._state.content_active:
            return False
        from pigeon import zone4_eq

        return zone4_eq.enabled()

    def _draw_zone4_eq(self, out: np.ndarray) -> None:
        if self._assignments()[3] != ZONE4_VISUALIZER_WIDGET:
            return
        from pigeon import zone4_meter

        if zone4_meter.selected():
            if self._zone4_meter is None:
                self._zone4_meter = zone4_meter.Zone4Meter()
            # No container plate: the meters sit straight on the background.
            self._zone4_meter.render_into(out, zone4_visualizer_rect(), track_bgr=None)
            return
        from pigeon.zone4_eq import Zone4EQ

        if self._zone4_eq is None:
            self._zone4_eq = Zone4EQ()
        self._zone4_eq.render_into(
            out,
            zone4_visualizer_rect(),
            float(self._state.progress),
            track_bgr=_VOLUME_CONTAINER_BGR,
        )

    _REVEAL_S = 0.7
    _REVEAL_FEATHER_PX = 0  # hard edge; >0 feathers the leading edge over that many px

    def reveal_active(self) -> bool:
        """True while the finished page is wiping on over the loading page."""
        if self._reveal_pending:
            if time.monotonic() - self._reveal_pending_mono > 5.0:
                self._end_reveal()  # the build never landed: show the page as is
                return False
            return True
        t0 = self._reveal_t0
        if t0 is None:
            return False
        if time.monotonic() - t0 >= self._REVEAL_S:
            self._end_reveal()
            return False
        return True

    def _end_reveal(self) -> None:
        self._reveal_gen += 1  # a build still running must not publish
        self._reveal_pending = False
        self._reveal_started = False
        self._reveal_ready = False
        self._reveal_failed = False
        self._reveal_t0 = None
        self._loading_snapshot = None
        self._reveal_new = None
        self._reveal_out = None
        self._reveal_live = None
        self._reveal_rows = None
        self._hold_out = None
        self._reveal_new_bgr = None
        self._anim_out = None
        self._anim_done_x = 0

    def reveal_wiping(self) -> bool:
        """True while the wipe itself is running (not while the page is still building)."""
        return self.reveal_active() and self._reveal_t0 is not None

    def _start_reveal_build(self) -> None:
        """Build the finished page on a worker thread; the stripes keep animating."""
        import threading

        snap = self._loading_snapshot
        if snap is None:
            self._reveal_failed = True
            return
        self._reveal_started = True
        self._hold_out = snap.copy()
        gen = self._reveal_gen
        threading.Thread(
            target=self._build_reveal_page, args=(gen,), name="np-reveal-build", daemon=True
        ).start()

    def _build_reveal_page(self, gen: int) -> None:
        try:
            sig = self._cache_sig(ticking=False)
            static = self._render_static_bgra()
            base = static.copy()
            self._overlay_ticking(base)
            key = (sig, self._ticking_sig())
            snap = self._loading_snapshot
            if gen != self._reveal_gen or snap is None or snap.shape != base.shape:
                if gen == self._reveal_gen:
                    self._reveal_failed = True
                return
            live = snap.copy()
            out = snap.copy()
            changed = (base != snap).reshape(base.shape[0], -1).any(axis=1)
            for _x, y, _w, h, _r in self._loading_live_regions():
                changed[max(0, y) : max(0, y + h)] = True
            if gen != self._reveal_gen:
                return
            # Publish: the normal path finds the finished page already cached.
            self._cached_bgra = static
            self._cached_sig = sig
            self._static_bgr = None
            self._ticking_under = None
            self._ticking_under_sig = None
            self._ticking_base = base
            self._ticking_base_key = key
            self._reveal_new_bgr = premultiply_bgra_on_black(base)
            self._reveal_new_opaque = int(base[:, :, 3].min()) == 255
            self._anim_done_x = 0
            self._reveal_new = base
            self._reveal_live = live
            self._reveal_out = out
            self._reveal_rows = np.nonzero(changed)[0]
            self._reveal_done_x = 0
            self._reveal_ready = True
        except Exception:
            if gen == self._reveal_gen:
                self._reveal_failed = True

    def _loading_hold_frame(self) -> np.ndarray:
        """The loading page, stripes still moving, while the finished page builds."""
        out, snap = self._hold_out, self._loading_snapshot
        assert out is not None and snap is not None
        for x, y, w, h, _r in self._loading_live_regions():
            out[y : y + h, x : x + w] = snap[y : y + h, x : x + w]
        self._paint_shimmers(out, self._loading_regions, self._loading_bar)
        return out

    def _loading_live_regions(self) -> list[tuple[int, int, int, int, int]]:
        regions = list(self._loading_regions)
        if self._loading_bar is not None:
            regions.append(self._loading_bar)
        return regions

    def _reveal_step(self) -> np.ndarray:
        """One wipe frame, updated incrementally in a persistent buffer."""
        out, new, live, snap = (
            self._reveal_out,
            self._reveal_new,
            self._reveal_live,
            self._loading_snapshot,
        )
        assert out is not None and new is not None and live is not None and snap is not None
        t0 = self._reveal_t0 if self._reveal_t0 is not None else time.monotonic()
        p = max(0.0, min(1.0, (time.monotonic() - t0) / float(self._REVEAL_S)))
        p = p * p * (3.0 - 2.0 * p)  # eases in and out: no jolt at either end
        w = int(new.shape[1])
        feather = int(self._REVEAL_FEATHER_PX)
        edge = p * float(w + feather)
        x_new = max(0, min(w, int(edge - feather)))  # final left of this
        x_old = max(0, min(w, int(math.ceil(edge)))) if feather > 0 else x_new  # loading page intact right of this

        # The loading page keeps animating until the wipe covers it.
        regions = self._loading_live_regions()
        for x, y, rw, rh, _r in regions:
            live[y : y + rh, x : x + rw] = snap[y : y + rh, x : x + rw]
        self._paint_shimmers(live, self._loading_regions, self._loading_bar)
        for x, y, rw, rh, _r in regions:
            if x_old < x + rw:
                x0 = max(x, x_old)
                out[y : y + rh, x0 : x + rw] = live[y : y + rh, x0 : x + rw]

        if x_new > self._reveal_done_x:
            out[:, self._reveal_done_x : x_new] = new[:, self._reveal_done_x : x_new]
            self._reveal_done_x = x_new
        rows = self._reveal_rows
        if feather > 0 and x_old > x_new and rows is not None and rows.size:
            xs = np.arange(x_new, x_old, dtype=np.float32)
            m = np.clip((edge - xs) / float(feather), 0.0, 1.0)[None, :, None]
            n = new[rows, x_new:x_old].astype(np.float32)
            o = live[rows, x_new:x_old].astype(np.float32)
            a_n = n[:, :, 3:4] / 255.0
            a_o = o[:, :, 3:4] / 255.0
            a = m * a_n + (1.0 - m) * a_o
            c = (m * a_n * n[:, :, :3] + (1.0 - m) * a_o * o[:, :, :3]) / np.maximum(a, 1e-4)
            res = np.empty_like(n)
            res[:, :, :3] = c
            res[:, :, 3:4] = a * 255.0
            out[rows, x_new:x_old] = np.clip(res + 0.5, 0, 255).astype(np.uint8)
        return out

    def _reveal_advance(self) -> str:
        """Move the reveal along: ``none``, ``hold`` (page building) or ``wipe``."""
        if not self.reveal_active():
            return "none"
        if self._reveal_failed:
            self._end_reveal()
            return "none"
        if self._reveal_pending:
            if not self._reveal_started:
                self._start_reveal_build()
                if self._reveal_failed:
                    self._end_reveal()
                    return "none"
            if self._reveal_ready:
                self._stamp_current_poster_protect()
                self._reveal_pending = False
                self._reveal_t0 = time.monotonic()
                return "wipe"
            return "hold"
        if self._reveal_new is not None:
            return "wipe"
        self._end_reveal()
        return "none"

    def _anim_bar_region(self, step: int) -> np.ndarray | None:
        """Stripes composited over the loading page's bar, as BGR-on-black (cached per phase)."""
        bar, base = self._loading_bar, self._loading_bgr
        if bar is None or base is None:
            return None
        hit = self._anim_regions.get(step)
        if hit is not None:
            return hit
        x, y, w, h, radius = bar
        patch = _candy_stripe_step_bgra(
            int(w), int(h), int(radius), step,
            tuple(int(c) for c in self._effective_np_theme().ui_bgr),
        )
        region = alpha_blend_bgra_over_bgr(base[y : y + h, x : x + w], patch)
        self._anim_regions[step] = region
        return region

    def _anim_bgr_frame(self, canvas_bgr: np.ndarray) -> np.ndarray | None:
        """Loading / hold / wipe frame as BGR-on-black, or None to use the general path.

        Only for the zone 11 bar-only loading page with a hard-edged wipe: the page is
        static apart from the stripes and the wipe edge, so a frame is a handful of
        slice copies.
        """
        if self._REVEAL_FEATHER_PX > 0 or self._loading_regions or self._live_audio_widgets_on():
            return None
        snap, bar = self._loading_snapshot, self._loading_bar
        if snap is None or bar is None:
            return None
        if self._state.searching:
            key = (self._cache_sig(ticking=False), self._ticking_sig())
            if key != self._ticking_base_key:
                return None  # the loading page changed: the general path rebuilds it
        base = self._loading_bgr
        if base is None or base.shape[:2] != snap.shape[:2] or self._anim_out is None:
            base = self._loading_bgr = premultiply_bgra_on_black(snap)
            self._loading_opaque = int(snap[:, :, 3].min()) == 255
            self._anim_out = base.copy()
            self._anim_regions.clear()
            self._anim_done_x = 0
        out = self._anim_out
        step = int(
            ((time.monotonic() / float(self._BAR_STRIPE_PERIOD_S)) % 1.0) * _CANDY_STEPS
        ) % _CANDY_STEPS
        region = self._anim_bar_region(step)
        if region is None:
            return None
        bx, by, bw, bh, _r = bar
        new = self._reveal_new_bgr
        wiping = self._reveal_t0 is not None and new is not None
        # BGR-on-black replaces the canvas outright only if every page involved is
        # opaque (or the canvas underneath is black anyway).
        if not (self._loading_opaque and (not wiping or self._reveal_new_opaque)):
            if canvas_bgr.any():
                return None
        x_new = 0
        if self._reveal_t0 is not None and new is not None:
            p = max(0.0, min(1.0, (time.monotonic() - self._reveal_t0) / float(self._REVEAL_S)))
            p = p * p * (3.0 - 2.0 * p)
            w = int(out.shape[1])
            x_new = max(0, min(w, int(p * w)))
            if x_new > self._anim_done_x:
                out[:, self._anim_done_x : x_new] = new[:, self._anim_done_x : x_new]
                self._anim_done_x = x_new
        x0 = max(bx, x_new)
        if x0 < bx + bw:
            out[by : by + bh, x0 : bx + bw] = region[:, x0 - bx :]
        return out

    def bgra_frame(self) -> np.ndarray | None:
        if not self._state.chrome_visible:
            return None
        mode = self._reveal_advance()
        revealing = mode != "none"
        if mode == "wipe":
            return self._reveal_step()
        if mode == "hold" and self._hold_out is not None:
            return self._loading_hold_frame()
        sig = self._cache_sig(ticking=False)
        if self._cached_bgra is None or self._cached_sig != sig:
            self._cached_bgra = self._render_static_bgra()
            self._cached_sig = sig
            self._static_bgr = None
            self._ticking_under = None
            self._ticking_under_sig = None
            self._ticking_base = None
        self._stamp_current_poster_protect()
        frame = self._cached_bgra
        if _layout_is_fullscreen_clock(self._assignments()):
            return frame
        work = self._shimmer_work
        cached = frame
        if work is None or work.shape != cached.shape:
            work = cached.copy()
            self._shimmer_work = work
        else:
            work[:] = cached
        rebuilt = False
        if self._state.searching or revealing:
            # Nothing but the stripes / wipe changes between frames: restamping the
            # clock, volume and bar every frame is most of the frame time.
            key = (sig, self._ticking_sig())
            base = self._ticking_base
            if base is None or base.shape != cached.shape or self._ticking_base_key != key:
                base = cached.copy()
                self._overlay_ticking(base)
                self._ticking_base = base
                self._ticking_base_key = key
                rebuilt = True
            work[:] = base
        else:
            self._overlay_ticking(work)
        frame = work
        if self._live_audio_widgets_on():
            self._draw_live_audio_widgets(work)
        self._draw_zone4_eq(work)
        if self._state.searching:
            # The loading page without its animation; the wipe repaints that live.
            snap = self._loading_snapshot
            if snap is None or snap.shape != work.shape:
                self._loading_snapshot = work.copy()
                self._loading_bgr = None
            elif rebuilt:
                snap[:] = work
                self._loading_bgr = None
            self._loading_regions = list(self._shimmer_rects)
            self._loading_bar = self._loading_bar_rect()
        if self._has_live_shimmer():
            self._paint_live_shimmers(work)
        return frame

    def render(self, canvas_bgr: np.ndarray) -> None:
        if canvas_bgr is None or canvas_bgr.size == 0:
            return
        self.tick()
        if not self._state.chrome_visible:
            canvas_bgr[:] = (0, 0, 0)
            return
        if self._has_live_shimmer() or self.reveal_active():
            mode = self._reveal_advance()
            if mode != "none" or self._state.searching:
                fast = self._anim_bgr_frame(canvas_bgr)
                if fast is not None and fast.shape == canvas_bgr.shape:
                    canvas_bgr[:] = fast
                    return
            frame = self.bgra_frame()
            if frame is None:
                return
            if frame.shape[2] >= 4:
                if frame.shape[:2] == canvas_bgr.shape[:2] and int(frame[:, :, 3].min()) == 255:
                    canvas_bgr[:] = frame[:, :, :3]  # opaque page: no intermediate copy
                else:
                    canvas_bgr[:] = alpha_blend_bgra_over_bgr(canvas_bgr, frame)
            else:
                h = min(canvas_bgr.shape[0], frame.shape[0])
                w = min(canvas_bgr.shape[1], frame.shape[1])
                canvas_bgr[:h, :w] = frame[:h, :w, :3]
            return
        sig = self._cache_sig(ticking=False)
        if self._cached_bgra is None or self._cached_sig != sig:
            self._cached_bgra = self._render_static_bgra()
            self._cached_sig = sig
            self._static_bgr = None
            self._ticking_under = None
            self._ticking_under_sig = None
        self._stamp_current_poster_protect()
        static = self._cached_bgra
        if self._static_bgr is None or self._static_bgr.shape[:2] != static.shape[:2]:
            self._static_bgr = premultiply_bgra_on_black(static)
        tick = self._ticking_sig()
        under = self._ticking_under
        if (
            under is None
            or under.shape != canvas_bgr.shape
            or self._ticking_under_sig != (sig, tick)
        ):
            if under is None or under.shape != canvas_bgr.shape:
                under = self._static_bgr.copy()
                self._ticking_under = under
            elif (
                self._ticking_under_sig is not None
                and self._ticking_under_sig[0] == sig
            ):
                self._restore_ticking_rects(under)
            else:
                under[:] = self._static_bgr
            self._overlay_ticking(under)
            self._ticking_under_sig = (sig, tick)
        canvas_bgr[:] = under
        if self._live_audio_widgets_on():
            self._draw_live_audio_widgets(canvas_bgr)
        self._draw_zone4_eq(canvas_bgr)
