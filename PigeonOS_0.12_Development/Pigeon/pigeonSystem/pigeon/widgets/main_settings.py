"""
Pigeon 0.8 main settings — SVG chrome from ``settings_0.8/settings_main.svg``.

Renders the primary settings menu (800×480 BGRA) with left/right focus navigation
and selection recoloring. Text entry opens the shared settings keyboard overlay
(``settings_keyboard.py``).
"""

from __future__ import annotations

import io
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pigeon.widgets.search_spinner import (
    blit_spinner_patch as _blit_spinner_patch,
    precompute_rotated_patches as _precompute_rotated_patches,
    rotated_patch_for_angle as _rotated_patch_for_angle,
)
from pigeon.widgets.settings_svg_text import _is_hidden as _is_subtree_hidden, _style_prop
from pigeon.widgets.settings_svg_tree import (  # noqa: F401  (re-exported for existing importers)
    _AI_SUFFIX_RE,
    _HEX_RE,
    _LOGICAL_INDEX_BY_ROOT,
    _find_all_by_logical_id,
    _find_by_id,
    _find_by_logical_id,
    _invalidate_logical_index,
    _is_descendant_of,
    _iter_style_fill_stroke,
    _logical_id_index,
    _norm_hex,
    _normalize_logical,
    _parent_map,
    _prune_display_none,
    _remove_by_logical_id,
    _rewrite_style_prop,
    _set_paint,
    _set_text_content,
    _set_visible,
    _strip_ai_uniqueness,
    _style_has_display_none,
    decode_svg_id,
    encode_svg_id,
)
from pigeon.widgets.settings_theme_background import (
    _transform_rect_corners as _transform_rect_corners_svg,
)
from pigeon.compositing import alpha_blend_bgra_over_bgr
from pigeon.design import DESIGN_H, DESIGN_W, LEGACY_DESIGN_H, LEGACY_DESIGN_W, map_legacy_size, map_legacy_xy
from pigeon.font_paths import resolve_digital7_font, resolve_ui_font_medium
from pigeon.widgets.box_device_search import (
    BOX_DEVICE_ROW_CANCEL,
    BOX_DEVICE_ROW_ENTER_IP,
    BoxDevicePanelState,
    ManualDeviceEntry,
    _BOX_DEVICE_ROW_COUNT,
    _BOX_SCAN_MAX_DURATION_S,
    _BOX_SCAN_ROTATION_DPS,
    box_devices_with_special_rows,
    box_search_center_svg,
    device_row_from_pick,
    is_special_device_row,
    scan_lan_devices,
)
from pigeon.widgets.box_device_pairing import BoxPairingSession
from pigeon.widgets.settings_state import (  # noqa: F401  (re-exported for existing importers)
    COLOR_ACCENT_DEFAULT,
    COLOR_DESELECTED,
    COLOR_INACTIVE,
    COLOR_SELECTED,
    COLOR_UI_DEFAULT,
    MainSettingsFocus,
    MainSettingsState,
    SettingsTheme,
    _LOCATION_SLOT_DEFAULT_NAMES,
    _LOCATION_SWITCH_SPINNER_DELAY_S,
    _NEST_OR_ROOM_RE,
    _PICKER_ROW_MINI_BUTTONS,
    _PICKER_ROW_TEXTS,
    _PRIMARY_FOCUS_CANDIDATES,
    _WIFI_ONBOARDING_FOCUS,
    location_name_is_default,
    location_room_label,
)
from pigeon.widgets.settings_text_entry import (  # noqa: F401  (re-exported for existing importers)
    _ARTBOARD_H,
    _COLOR_GRAY_RGBA,
    _DUAL_NETWORK_TEXT_X0_SVG,
    _DUAL_NETWORK_TEXT_X1_SVG,
    _TEXT_ENTRY_FIELDS,
    _asterisk_font_for_password_mask,
    _centered_field_cursor_x,
    _clamp_field_cursor_x,
    _draw_centered_field_text,
    _draw_password_mask_text,
    _draw_text_entry_content,
    _draw_text_entry_cursor,
    _dual_location_text_bounds_px,
    _entry_content_font_size_px,
    _entry_cursor_display,
    _entry_display_text,
    _entry_field_bounds_px,
    _field_font,
    _field_font_size_px,
    _fit_text_font_size,
    _load_digital7,
    _load_sharp_medium,
    _location_text_is_grayed,
    _password_mask_display,
    _password_mask_layout,
    _text_field_spec,
)
from pigeon.widgets.settings_search_overlays import (  # noqa: F401  (re-exported for existing importers)
    XLINK_NS,
    _BoxSearchArcOverlay,
    _COLOR_GRAY_BGR,
    _DUAL_LOCATION_WIFI_CENTER_SVG,
    _MATRIX_RE,
    _OnboardingSearchArcSpec,
    _SEARCH_GLYPH_BGR,
    _SVG_ARC_PATH_RE,
    _StarMaskedCircleSpec,
    _TRANSLATE_RE,
    _WIFI_FAIL_SIZE_SVG,
    _WIFI_RADII_SVG,
    _WIFI_SEARCH_CENTER_SVG,
    _WIFI_SEARCH_GLYPH_BGR,
    _WIFI_SEARCH_PATCH_RADIUS_PX,
    _WIFI_SEARCH_RING_RADIUS_SVG,
    _WIFI_SEARCH_RING_STROKE_SVG,
    _WIFI_STROKE_SVG,
    _WifiIconLayout,
    _ancestor_search_icon,
    _arc_spec_from_search_path,
    _box_focus_button,
    _box_search_star_specs,
    _circle_stroke_from_element,
    _collect_box_search_arc_overlays,
    _composite_stroke_mask,
    _discover_box_search_arc_specs,
    _discover_box_search_triangle_specs,
    _discover_onboarding_search_arc_specs,
    _discover_onboarding_search_triangle_specs,
    _discover_search_arc_specs_in_group,
    _discover_star_masked_circles,
    _discover_wifi_icon_layouts,
    _draw_box_search_arc_overlays,
    _draw_onboarding_search_arc_overlays,
    _draw_onboarding_search_arc_overlays_on_patch,
    _draw_onboarding_search_arc_stroke,
    _draw_onboarding_search_triangle_overlays,
    _draw_star_masked_circle_overlays,
    _draw_star_masked_circle_stroke,
    _draw_star_spec_on_patch,
    _draw_triangle_specs_on_patch,
    _draw_wifi_fail_badge,
    _draw_wifi_icon_overlay,
    _draw_wifi_overlays,
    _find_box_column_search_icon,
    _find_box_root_group,
    _hex_to_bgr,
    _hide_box_column_search_svg_circles,
    _hide_box_search_animation_layers,
    _hide_box_search_icon_vectors,
    _hide_star_masked_svg_circles,
    _hide_svg_wifi_icons,
    _load_wifi_fail_font,
    _mask_search_glyph_patch,
    _mask_wifi_search_glyph_patch,
    _needs_wifi_setup,
    _parse_matrix_translate,
    _parse_svg_matrix,
    _parse_svg_points,
    _path_stroke_width,
    _stroke_bgr_for_star_spec,
    _svg_arc_center_and_angles,
    _svg_id_index,
    _svg_radius_to_px,
    _svg_scale,
    _svg_to_px,
    _wedge_clip_corners,
    _wifi_circle_center,
    _wifi_fail_text_xy,
    _wifi_onboarding_add_search_group,
    _wifi_onboarding_search_group,
    _wifi_star_clip_polygon,
)
from pigeon.widgets.settings_container_background import (  # noqa: F401  (re-exported for existing importers)
    _BACKGROUND_CONTAINERS,
    _CONTAINER_BG_PLATE_CACHE,
    _ContainerStripeSpec,
    _MENU_CONTAINER_BBOX,
    _MENU_CONTAINER_RADIUS_PX,
    _composite_bgra_over_bgra,
    _container_stripe_cache_key,
    _disable_embedded_settings_background_layers,
    _discover_container_stripe_specs,
    _draw_container_background_bgra,
    _hide_container_stripe_rects,
    _menu_container_mask,
    _parse_svg_slant_transform,
    _remove_canvas_background_rect,
)
from pigeon.widgets.settings_paint import (  # noqa: F401  (re-exported for existing importers)
    COLOR_LEGACY_GREEN,
    _BUTTON_FILL_CANDIDATES,
    _CONTRAST_SWAP_CANDIDATES,
    _UI_BRAND_COLORS,
    _apply_accent_paint,
    _apply_button_fill,
    _apply_contrast_paint,
    _apply_direct_glyph_contrast,
    _apply_ui_brand_paint,
    _is_ui_brand_color,
    _theme_swatch_hexes,
    _ui_recolor_hexes,
)
from pigeon.widgets.settings_box_text_layout import (  # noqa: F401  (re-exported for existing importers)
    _BOX_COLUMN_INNER_SVG,
    _BOX_DEVICE_GROUPS,
    _BOX_DEVICE_IP_FONT_SVG,
    _BOX_DEVICE_IP_Y_SVG,
    _BOX_DEVICE_NAME_FONT_SVG,
    _BOX_DEVICE_NAME_Y_SVG,
    _BOX_RESULT_ROW_FONT_SIZE_SVG,
    _BOX_RESULT_ROW_GAP_SVG,
    _BOX_RESULT_ROW_Y_SVG,
    _apply_box_device_group_layout,
    _apply_box_result_row_text_layout,
    _box_column_inner_svg,
    _find_box_device_group,
    _format_box_result_device_name,
    _is_device_label_logical,
    _layout_box_device_label,
    _px_to_svg_x,
    _result_row_font,
    _result_row_font_size_px,
    _set_svg_text_centered,
    _set_svg_text_font_size_px,
    _set_svg_text_horiz_centered,
    _set_svg_text_left_aligned,
    _set_svg_text_right_aligned,
    _text_width_px,
    _truncate_text_to_width,
)
from pigeon.widgets.settings_scene import (  # noqa: F401  (re-exported for existing importers)
    COLOR_VERSION_TEXT,
    _BOX_CHROME_NUM_RE,
    _BOX_CHROME_PREFIXES,
    _BOX_CONTAINER_LOGICALS,
    _BOX_LOCATION_GROUPS,
    _BOX_LOCATION_TEXT_FONT_SVG,
    _BOX_LOCATION_TEXT_Y_SVG,
    _DUAL_LOCATION_ICON_IDS,
    _DUAL_LOCATION_ICON_RADIUS_SVG,
    _DUAL_LOCATION_TEXT_ICON_GAP_SVG,
    _DUAL_LOCATION_TEXT_X0_SVG,
    _DUAL_LOCATION_TEXT_X1_SVG,
    _FOCUS_ASSOCIATED,
    _HIDDEN_MAIN_ACCENT_IDS,
    _HIDE_ALWAYS_LOGICAL,
    _KEYBOARD_HIDE_WHEN_OPEN,
    _PICKER_ROW_LOCK_GROUPS,
    _PICKER_TEXT_CENTER_X_SVG,
    _active_background_container,
    _apply_background_container,
    _apply_box1_host_device_labels,
    _apply_box_column_nav_fills,
    _apply_box_device_group_labels,
    _apply_box_device_panel_layers,
    _apply_box_device_text_contrast,
    _apply_box_location_group_labels,
    _apply_box_location_text_contrast,
    _apply_box_pigeon_logo_icon_styles,
    _apply_box_result_text_style,
    _apply_box_search_icon_glyph_styles,
    _apply_box_search_icon_variant,
    _apply_dual_bar_nav_fills,
    _apply_keyboard_layer_visibility,
    _apply_network_picker_arrows,
    _apply_network_picker_rows,
    _apply_picker_network_labels,
    _apply_scene_layer_visibility,
    _apply_scroll_arrow_glyph,
    _apply_wifi_onboarding_search_layers,
    _apply_wifi_onboarding_visibility,
    _apply_wifi_search_glyph_layers,
    _apply_wifi_search_icon_styles,
    _box_button_fill_selected,
    _box_location_label_for_slot,
    _box_location_text_bounds_svg,
    _box_nav_button_selected,
    _box_num_from_chrome_logical,
    _box_shows_location_group,
    _center_wifi_plus_icon,
    _draw_dual_bar_network_prompt,
    _draw_wifi_onboarding_search_overlays,
    _dual_bar_pill_center_y_px,
    _dual_location_text_bounds_svg,
    _finalize_wifi_onboarding_layers,
    _find_box_result_device_layer,
    _find_box_result_layer,
    _find_box_scroll_arrow,
    _force_layer_white,
    _hide_add_search_glyphs,
    _hide_all_box_chrome,
    _hide_vertical_scroll_arrows,
    _hide_wifi_onboarding_chrome_for_picker,
    _hide_wifi_onboarding_search_svg_circles,
    _hide_wifi_onboarding_search_svg_glyphs,
    _hide_wifi_search_glyphs,
    _is_box_chrome_logical,
    _is_box_results_device_logical,
    _is_onboarding_search_group,
    _layer_class,
    _location_display_text,
    _network_field_font_size_svg,
    _network_field_text,
    _pairing_instruction_text,
    _parse_svg_text_y_svg,
    _set_box_columns_visible,
    _set_box_search_plus_visible,
    _set_box_search_results_visible,
    _show_box_search_icon_vectors,
    _wifi_logout_instruction_text,
    apply_main_settings_svg_state,
    discover_focus_ring_in_svg,
)


SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)


# Native 1280 keyboards live in settings/keyboard/; yes/no stays legacy.
KEYBOARD_SVG_NAMES: tuple[str, ...] = (
    "keyboard_bottom_row.svg",
    "keyboard_lower.svg",
    "keyboard_upper.svg",
    "keyboard_numeric.svg",
    "keyboard_pin.svg",
    "keyboard_ip.svg",
    "keyboard_symbolic.svg",
    "keyboard_yes_no.svg",
)
KEYBOARD_NUMERIC_IP_SVG = "keyboard_ip.svg"


_ACTIVATE_ACTIONS: dict[str, str] = {
    "main_dual_location_button": "focus_location",
    "main_dual_network_button": "focus_network",
    "main_box1_button": "focus_box1",
    "main_box2_button": "focus_box2",
    "main_box3_button": "focus_box3",
    "main_box2_device_results": "pick_box2_device",
    "main_box3_device_results": "pick_box3_device",
    "main_exit_button": "exit",
    "main_search_button": "focus_search",
    "main_search_clear_button": "clear_search",
    "main_network_picker_button": "focus_network_picker",
    "main_box2_add_search_icon": "wifi_search",
}

_WIFI_SCAN_MIN_DURATION_S = 0.0
_WIFI_SCAN_MAX_DURATION_S = 55.0
_WIFI_SCAN_ROTATION_DPS = 720.0
_WIFI_SCAN_CACHE_TTL_S = 120.0
_BOX_SCAN_CACHE_TTL_S = 180.0
_BOX_PREFETCH_INTERVAL_S = 90.0
_BOX_SCAN_CACHE_HIT_MIN_S = 1.2
_BOX_SCAN_LIVE_MIN_S = 1.2
_LOCATION_SWITCH_ROTATION_DPS = _WIFI_SCAN_ROTATION_DPS


# Launch-visible layer groups (``settingInstructions_0.8.0``).
_LAUNCH_VISIBLE_LOGICAL: frozenset[str] = frozenset(
    {
        "settings_background",
        "main_exit_group",
        "main_dual",
        "main_box1_device_group",
        "main_box2_device_group",
        "main_box3_device_group",
    }
)


_BOX_ROOT_LOGICALS: tuple[str, ...] = ("main_box1", "main_box2", "main_box3")
_BOX_BUTTON_LOGICALS: frozenset[str] = frozenset(
    {"main_box1_button", "main_box2_button", "main_box3_button"}
)


def default_main_settings_svg_path(assets_dir: Path | str | None = None) -> Path:
    """Resolve ``settings_main.svg`` (override with ``PIGEON_MAIN_SETTINGS_SVG``)."""
    env = os.environ.get("PIGEON_MAIN_SETTINGS_SVG", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if assets_dir is not None:
        return Path(assets_dir) / "settings_0.8" / "settings_main.svg"
    pigeon_root = Path(__file__).resolve().parents[3]
    return pigeon_root / "pigeonAssets" / "settings_0.8" / "settings_main.svg"


def keyboard_svg_path(
    name: str,
    *,
    assets_dir: Path | str | None = None,
) -> Path:
    """Resolve a keyboard SVG (native ``settings/keyboard/``, then legacy ``settings_0.8/``)."""
    base = Path(assets_dir) if assets_dir is not None else Path(__file__).resolve().parents[3] / "pigeonAssets"
    native = Path(base) / "settings" / "keyboard" / name
    if native.is_file():
        return native
    return Path(base) / "settings_0.8" / name


# Full-frame registration PNG for the box1 pigeon mark (replaces the SVG wing polygon).
_BOX1_PIGEON_LOGO_PNG = "settings_main_box1_pigeon_logo.png"
_BOX1_PIGEON_LOGO_CACHE: dict[tuple[str, float, int, int], np.ndarray] = {}


def box1_pigeon_logo_png_path(*, assets_dir: Path | str | None = None) -> Path:
    """Resolve the full-screen box1 pigeon logo under ``settings_0.8/``."""
    base = Path(assets_dir) if assets_dir is not None else Path(__file__).resolve().parents[3] / "pigeonAssets"
    return Path(base) / "settings_0.8" / _BOX1_PIGEON_LOGO_PNG


def _hide_box1_wing_logo_polygon(root: ET.Element) -> None:
    """Drop the Illustrator wing polygon; left/right rules stay for chrome."""
    icon = _find_by_logical_id(root, "main_box1_pigeon_logo_icon")
    if icon is None:
        return
    for el in icon.iter():
        if el.tag.endswith("polygon"):
            _set_visible(el, False)


def _load_box1_pigeon_logo_overlay_bgra(
    *,
    assets_dir: Path | str | None = None,
) -> np.ndarray | None:
    """Load + scale the registration PNG to the design canvas (BGRA)."""
    path = box1_pigeon_logo_png_path(assets_dir=assets_dir)
    if not path.is_file():
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    key = (str(path.resolve()), float(mtime), int(DESIGN_W), int(DESIGN_H))
    hit = _BOX1_PIGEON_LOGO_CACHE.get(key)
    if hit is not None:
        return hit
    src = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if src is None or src.size == 0:
        return None
    if src.ndim == 2:
        src = cv2.cvtColor(src, cv2.COLOR_GRAY2BGRA)
    elif src.shape[2] == 3:
        src = cv2.cvtColor(src, cv2.COLOR_BGR2BGRA)
    elif src.shape[2] != 4:
        return None
    if src.shape[0] != DESIGN_H or src.shape[1] != DESIGN_W:
        from pigeon.np_layout import letterbox_legacy_ui

        src = letterbox_legacy_ui(src)
    _BOX1_PIGEON_LOGO_CACHE.clear()
    _BOX1_PIGEON_LOGO_CACHE[key] = src
    return src


def _draw_box1_pigeon_logo_overlay(
    bgra: np.ndarray,
    *,
    assets_dir: Path | str | None = None,
    ui_hex: str = COLOR_UI_DEFAULT,
) -> None:
    """Composite the full-frame box1 pigeon mark, tinted brand red like the SVG icons."""
    overlay = _load_box1_pigeon_logo_overlay_bgra(assets_dir=assets_dir)
    if overlay is None or overlay.shape[:2] != bgra.shape[:2]:
        return
    if not np.any(overlay[:, :, 3]):
        return
    tinted = overlay.copy()
    b, g, r = _hex_to_bgr(ui_hex or COLOR_UI_DEFAULT)
    tinted[:, :, 0] = b
    tinted[:, :, 1] = g
    tinted[:, :, 2] = r
    blended = _composite_bgra_over_bgra(bgra, tinted)
    bgra[:] = blended


_SVG_TREE_TEMPLATES: dict[tuple[str, int], ET.Element] = {}
_SVG_TREE_TEMPLATE_MAX = 2
# Stable art discovers (wifi / onboarding) keyed by SVG path+mtime.
# Star-masked pigeon-logo rings are NOT cached: discovery depends on layer
# visibility after apply, and specs carry per-tree element ids used to hide circles.
_SVG_GEOMETRY_CACHE: dict[tuple[str, int], dict[str, object]] = {}


def _svg_geometry_bundle(path: Path, root: ET.Element) -> dict[str, object]:
    key = (str(path.resolve()), path.stat().st_mtime_ns)
    hit = _SVG_GEOMETRY_CACHE.get(key)
    if hit is not None:
        return hit
    bundle = {
        "onboarding_arcs": _discover_onboarding_search_arc_specs(root),
        "onboarding_tris": _discover_onboarding_search_triangle_specs(root),
        "wifi_layouts": _discover_wifi_icon_layouts(root),
    }
    if len(_SVG_GEOMETRY_CACHE) >= 4:
        _SVG_GEOMETRY_CACHE.clear()
    _SVG_GEOMETRY_CACHE[key] = bundle
    return bundle


def _svg_tree_from_path(path: Path) -> ET.Element:
    import copy

    path = Path(path)
    key = (str(path.resolve()), path.stat().st_mtime_ns)
    template = _SVG_TREE_TEMPLATES.get(key)
    if template is None:
        tree = ET.parse(path)
        root = tree.getroot()
        # Native 800×480 artboard — letterboxed into the 1280×800 design canvas.
        root.set("viewBox", "0 0 800 480")
        root.set("width", str(LEGACY_DESIGN_W))
        root.set("height", str(LEGACY_DESIGN_H))
        if len(_SVG_TREE_TEMPLATES) >= _SVG_TREE_TEMPLATE_MAX:
            _SVG_TREE_TEMPLATES.clear()
        _SVG_TREE_TEMPLATES[key] = root
        template = root
    return copy.deepcopy(template)


def _rasterize_svg_tree(root: ET.Element) -> np.ndarray:
    """Return BGRA uint8 (DESIGN_H × DESIGN_W) with Digital-7 / Sharp Sans labels."""
    from pigeon.np_layout import letterbox_legacy_ui
    from pigeon.widgets.settings_svg_text import rasterize_settings_svg_bgra

    native = rasterize_settings_svg_bgra(
        root, width=LEGACY_DESIGN_W, height=LEGACY_DESIGN_H
    )
    return letterbox_legacy_ui(native)


def render_main_settings_bgra(
    state: MainSettingsState | None = None,
    *,
    svg_path: Path | str | None = None,
    assets_dir: Path | str | None = None,
    skip_text_entry: bool = False,
) -> np.ndarray:
    """Compose native 1280×800 settings main from the PDF widgets.

    ``skip_text_entry`` leaves dual-bar field text undrawn so callers can cache
    chrome and patch the buffer without a full SVG re-raster.
    """
    del svg_path
    from pigeon.widgets.settings_main_1280 import render_settings_main_1280_bgra

    st = state if state is not None else MainSettingsState()
    st.ensure_focus_ring()
    return render_settings_main_1280_bgra(
        st, assets_dir=assets_dir, skip_text_entry=skip_text_entry
    )


class MainSettingsWidget:
    """Cached main-settings compositor (similar to ``NowPlayingScreenWidget``)."""

    def __init__(
        self,
        *,
        assets_dir: Path | str | None = None,
        svg_path: Path | str | None = None,
        state: MainSettingsState | None = None,
    ) -> None:
        self._assets_dir = Path(assets_dir) if assets_dir is not None else None
        self._svg_path = Path(svg_path) if svg_path is not None else None
        self._state = state if state is not None else MainSettingsState()
        if self._state.version_string in ("", "0.8.0"):
            try:
                from pigeon.version import version_string

                self._state.version_string = version_string()
            except Exception:
                pass
        try:
            from pigeon.widgets.ui_color_settings import load_persisted_theme_into_state

            load_persisted_theme_into_state(self._state)
        except Exception:
            pass
        if self._state.needs_wifi_setup():
            self._state.wifi_onboarding = False
        try:
            from pigeon.app_state import read_current_location_name

            self._state.reload_location_wifi()
            self._state.location_name = read_current_location_name()
        except Exception:
            pass
        self._state.load_saved_box_devices()
        try:
            from pigeon.manual_search import current_title

            self._state.manual_search_title = current_title()
        except Exception:
            pass
        self._state.ensure_focus_ring()
        self._cached_bgra: np.ndarray | None = None
        self._cached_sig: tuple[object, ...] | None = None
        self._cached_main_bgra: np.ndarray | None = None
        self._cached_main_sig: tuple[object, ...] | None = None
        self._cached_kb_bgra: np.ndarray | None = None
        self._cached_kb_sig: tuple[object, ...] | None = None
        # Main chrome under the keyboard (no field text) — typing patches text only.
        self._cached_kb_chrome_bgra: np.ndarray | None = None
        self._cached_kb_chrome_sig: tuple[object, ...] | None = None
        # Per-key keyboard overlays for the active mode — Left/Right revisits skip PyMuPDF.
        self._kb_focus_frame_cache: dict[tuple[object, ...], np.ndarray] = {}
        # (key, base frame, composed frame) for the settings_pigeon clock/keypad.
        self._pigeon_overlay_cache: tuple[object, np.ndarray, np.ndarray] | None = None
        self._kb_composed_cache: dict[tuple[object, ...], np.ndarray] = {}
        self._kb_cache_mode: object | None = None
        self._kb_prewarm_inflight: bool = False
        # Opaque-flag cache for keyboard overlays (avoid float blend when possible).
        self._kb_frame_opaque: dict[tuple[object, ...], bool] = {}
        self._wifi_search_glyph_cache: np.ndarray | None = None
        self._wifi_scan_result: tuple[str, ...] | None = None
        self._wifi_scan_cache: tuple[tuple[str, ...], float] | None = None
        self._box_scan_result: dict[int, tuple[tuple[tuple[str, str], ...], tuple[dict[str, str], ...]] | None] = {}
        self._box_scan_cache: dict[int, tuple[tuple[tuple[str, str], ...], tuple[dict[str, str], ...], float]] = {}
        self._box_search_glyph_cache: dict[int, np.ndarray | None] = {}
        self._wifi_search_rotated_cache: tuple[np.ndarray, ...] | None = None
        self._location_switch_spinner_frames: tuple[np.ndarray, ...] | None = None
        self._location_switch_spinner_tried = False
        self._box_search_rotated_cache: dict[int, tuple[np.ndarray, ...]] = {}
        self._box_scan_pending: set[int] = set()
        self._wifi_prefetch_inflight: bool = False
        self._box_prefetch_inflight: set[int] = set()
        self._box_prefetch_shared_inflight: bool = False
        self._periodic_prefetch_started: bool = False
        self._pre_scan_main_bgra: dict[int, np.ndarray] = {}
        self._last_tick_mono: float = time.monotonic()
        # Per-focus bitmaps for the current structure — left/right nav revisits are free.
        self._focus_frame_cache: dict[tuple[object, ...], np.ndarray] = {}
        self._focus_cache_structure: tuple[object, ...] | None = None
        self._prewarm_all_inflight: bool = False
        # Kick full-ring prewarm only after the first live paint for a structure.
        self._want_prewarm_after_paint: bool = False
        # Avoid repeated full-frame alpha.min() when the current paste is known opaque.
        self._paste_fully_opaque: bool | None = None
        # True while Left/Right / rotary ticks are coalesced — skip cursor copy.
        self._nav_scrub: bool = False
        # Warm LAN IP off the first settings paint (hostname/ipconfig can take tens of ms).
        try:
            from pigeon.local_ip import local_ipv4_address

            local_ipv4_address()
        except Exception:
            pass

    @property
    def state(self) -> MainSettingsState:
        return self._state

    def _status_bar_animating(self) -> bool:
        st = self._state
        if st.wifi_scanning or st.wifi_connecting:
            return True
        if st.box2_devices.scanning or st.box3_devices.scanning:
            return True
        return bool(st.location_switch_spinner_visible())

    def _scan_anim_token(self) -> int:
        """Quantized status-bar fill so the main-frame cache cannot freeze mid-scan."""
        st = self._state
        now = time.monotonic()

        def steps(started: float, duration: float) -> int:
            if started <= 0.0 or duration <= 0.0:
                return 0
            return int(max(0.0, min(1.0, (now - started) / duration)) * 100)

        if st.box2_devices.scanning:
            return 2000 + steps(
                float(st.box2_devices.scan_started_mono),
                float(getattr(st.box2_devices, "scan_duration_s", 0.0) or _BOX_SCAN_MAX_DURATION_S),
            )
        if st.box3_devices.scanning:
            return 3000 + steps(
                float(st.box3_devices.scan_started_mono),
                float(getattr(st.box3_devices, "scan_duration_s", 0.0) or _BOX_SCAN_MAX_DURATION_S),
            )
        if st.wifi_scanning:
            return 1000 + steps(float(st.wifi_scan_started_mono), _WIFI_SCAN_MAX_DURATION_S)
        if st.wifi_connecting:
            return 1100 + steps(
                float(getattr(st, "wifi_connect_started_mono", 0.0) or 0.0),
                _WIFI_SCAN_MAX_DURATION_S,
            )
        if st.location_switch_spinner_visible():
            return 4000 + int(round(float(st.location_switch_angle_deg) / 10.0))
        return -1

    def invalidate(self) -> None:
        self._cached_bgra = None
        self._cached_sig = None
        self._cached_main_bgra = None
        self._cached_main_sig = None
        self._cached_kb_bgra = None
        self._cached_kb_sig = None
        self._cached_kb_chrome_bgra = None
        self._cached_kb_chrome_sig = None
        self._kb_focus_frame_cache.clear()
        self._kb_composed_cache.clear()
        self._kb_frame_opaque.clear()
        self._kb_cache_mode = None
        self._kb_prewarm_inflight = False
        self._focus_frame_cache.clear()
        self._focus_cache_structure = None
        self._prewarm_all_inflight = False
        self._want_prewarm_after_paint = True
        self._paste_fully_opaque = None

    def frame_cache_token(self) -> tuple[object, ...]:
        """Stable token for skip-cache while the settings bitmap is unchanged."""
        kb_open = self._state.keyboard is not None
        return (
            self._cached_main_sig,
            self._cached_kb_sig,
            round(float(self._state.wifi_scan_angle_deg), 0)
            if self._state.wifi_scanning or self._state.wifi_connecting
            else 0,
            round(float(self._state.box2_devices.scan_angle_deg), 0)
            if self._state.box2_devices.scanning
            else 0,
            round(float(self._state.box3_devices.scan_angle_deg), 0)
            if self._state.box3_devices.scanning
            else 0,
            round(float(self._state.location_switch_angle_deg), 0)
            if self._state.location_switch_spinner_visible()
            else 0,
            # Drive caret blink without forcing a full redraw every wake.
            int(time.monotonic() * 2) % 2 if kb_open else 0,
            1 if kb_open else 0,
            # Prefs live overlays (HH:MM / NP rings / content) refresh each
            # second without busting the heavy SVG structure cache.
            # Widget-settings demos are static stills — do not tick them.
            (
                datetime.now().strftime("%H%M%S"),
                int(round(float(self._state.preferences_np_progress) * 100))
                if self._state.preferences_np_progress is not None
                else -1,
                1 if self._state.preferences_live_content else 0,
                str(self._state.preferences_volume or ""),
                round(float(self._state.preferences_volume_fraction or 0.0), 3),
                str(self._state.preferences_elapsed_text or ""),
                str(self._state.preferences_remaining_text or ""),
                str(self._state.preferences_service_name or ""),
                str(self._state.preferences_song_title or ""),
                str(self._state.preferences_album_title or ""),
                str(self._state.preferences_artist_title or ""),
                id(self._state.preferences_poster_bgra)
                if self._state.preferences_poster_bgra is not None
                else 0,
                id(self._state.preferences_tt_bgra)
                if self._state.preferences_tt_bgra is not None
                else 0,
                tuple(self._state.preferences_cast or ()),
            )
            if self._state.show_preferences
            else (),
            # settings_pigeon HH:MM:SS clock overlay.
            int(time.time()) if self._state.show_pigeon_settings else 0,
        )

    def _clear_keyboard_focus_caches(self) -> None:
        self._kb_focus_frame_cache.clear()
        self._kb_composed_cache.clear()
        self._kb_frame_opaque.clear()
        self._kb_cache_mode = None
        self._kb_prewarm_inflight = False
        self._cached_kb_bgra = None
        self._cached_kb_sig = None

    def _invalidate_keyboard_cache(self) -> None:
        """Drop composed output; keep per-key kb bitmaps for Left/Right reuse."""
        self._cached_kb_bgra = None
        self._cached_kb_sig = None
        self._cached_bgra = None
        self._cached_sig = None
        self._paste_fully_opaque = None

    def _keyboard_chrome_sig(self) -> tuple[object, ...]:
        """Main chrome under the keyboard — excludes typing buffer."""
        st = self._state
        th = st.theme
        kb = st.keyboard
        kb_main: tuple[object, ...] = ()
        if kb is not None:
            kb_main = (
                getattr(kb, "mode", None),
                str(getattr(kb, "target", "")),
                str(getattr(kb, "initial_text", "")),
                bool(getattr(kb, "supports_lowercase", True)),
                int(getattr(kb, "focus_index", 0) or 0)
                if str(getattr(kb, "target", "") or "") == "wifi_logout"
                else -1,
            )
        return (
            th.ui,
            th.selected,
            th.deselected,
            th.inactive,
            th.accent,
            int(st.wifi_level),
            st.location_name,
            st.wifi_password,
            st.selected_wifi_ssid,
            st.live_wifi_ssid,
            bool(st.wifi_logged_out),
            st.displayed_wifi_ssid(),
            st.pending_wifi_ssid,
            bool(st.network_password_error),
            bool(st.wifi_connecting),
            st.version_string,
            bool(st.show_network_picker),
            bool(st.show_box1_panel),
            bool(st.show_box2_panel),
            bool(st.show_box3_panel),
            bool(st.show_location_picker),
            bool(st.location_switching),
            bool(st.location_switch_spinner_visible()),
            round(float(st.location_switch_angle_deg) / 10.0)
            if st.location_switch_spinner_visible()
            else -1,
            bool(st.show_pigeon_settings),
            bool(st.show_update_popup),
            bool(st.update_available),
            bool(st.update_checking),
            bool(st.update_applying),
            bool(st.update_latest_confirmed),
            round(float(st.update_progress), 3),
            str(st.update_local_version or ""),
            str(st.update_remote_version or ""),
            str(st.update_changelog or ""),
            str(st.update_error or ""),
            int(st.update_popup_focus_index),
            bool(st.keyboard_open),
            str(self._svg_path or ""),
            str(self._assets_dir or ""),
            kb_main,
            None
            if st.box_pairing is None
            else (
                int(st.box_pairing.box_num),
                str(st.box_pairing.step),
                str(st.box_pairing.session_key),
                str(st.box_pairing.device_name),
            ),
        )

    def _main_with_text_from_chrome(self) -> np.ndarray:
        """Copy keyboard chrome and paint current field text (no SVG raster)."""
        from pigeon.widgets.settings_main_1280 import draw_settings_main_text_entry

        assert self._cached_kb_chrome_bgra is not None
        frame = self._cached_kb_chrome_bgra.copy()
        draw_settings_main_text_entry(frame, self._state)
        return frame

    def _compose_keyboard_over_main(
        self, main_frame: np.ndarray, kb_frame: np.ndarray, kb_sig: tuple[object, ...] | None
    ) -> np.ndarray:
        """Alpha-compose keyboard overlay; blend only the inked band."""
        alpha_u8 = kb_frame[:, :, 3]
        rows = np.any(alpha_u8 > 0, axis=1)
        if not np.any(rows):
            return main_frame.copy()
        ys = np.flatnonzero(rows)
        xs = np.flatnonzero(np.any(alpha_u8 > 0, axis=0))
        y0, y1 = int(ys[0]), int(ys[-1]) + 1
        x0, x1 = int(xs[0]), int(xs[-1]) + 1
        out = main_frame.copy()
        kb_roi = kb_frame[y0:y1, x0:x1]
        main_roi = out[y0:y1, x0:x1]
        opaque = int(kb_roi[:, :, 3].min()) == 255
        if kb_sig is not None:
            self._kb_frame_opaque[kb_sig] = opaque
        if opaque:
            main_roi[:, :, :3] = kb_roi[:, :, :3]
            main_roi[:, :, 3] = 255
            return out
        blended = alpha_blend_bgra_over_bgr(main_roi[:, :, :3], kb_roi)
        alpha = kb_roi[:, :, 3:4].astype(np.float32) / 255.0
        out_a = np.clip(
            alpha * 255.0 + (1.0 - alpha) * main_roi[:, :, 3:4].astype(np.float32),
            0,
            255,
        ).astype(np.uint8)
        out[y0:y1, x0:x1] = np.dstack([blended, out_a[:, :, 0]])
        return out

    def _keyboard_overlay_sig_for(
        self,
        mode: object,
        focus_index: int,
        *,
        supports_lowercase: bool = True,
        target: str = "",
    ) -> tuple[object, ...]:
        # Include supports_lowercase/target so location (uppercase-only, no Shift)
        # frames are never reused for network password (mixed case + Shift).
        return (
            mode,
            int(focus_index),
            bool(supports_lowercase),
            str(target or ""),
            str(self._assets_dir or ""),
        )

    def _store_kb_frame(self, kb_sig: tuple[object, ...], frame: np.ndarray) -> None:
        if kb_sig not in self._kb_focus_frame_cache:
            self._kb_focus_frame_cache[kb_sig] = frame
            if len(self._kb_focus_frame_cache) > 8:
                oldest = next(iter(self._kb_focus_frame_cache))
                if oldest != kb_sig:
                    self._kb_focus_frame_cache.pop(oldest, None)

    def _store_kb_composed(
        self, compose_key: tuple[object, ...], frame: np.ndarray
    ) -> None:
        if compose_key not in self._kb_composed_cache:
            self._kb_composed_cache[compose_key] = frame
            if len(self._kb_composed_cache) > 8:
                oldest = next(iter(self._kb_composed_cache))
                if oldest != compose_key:
                    self._kb_composed_cache.pop(oldest, None)

    def _metadata_debug_sig(self) -> tuple[object, ...]:
        """Metadata inspector page + a live-data token (repaint on change)."""
        st = self._state
        if not st.show_metadata_debug:
            return (False,)
        try:
            from pigeon.widgets.metadata_debug import metadata_debug_data

            data_token = hash(repr(metadata_debug_data()))
        except Exception:
            data_token = 0
        return (True, int(st.metadata_debug_page), data_token)

    def _pigeon_page_sig(self) -> tuple[object, ...]:
        """settings_pigeon content that is not focus: lights, zip, timezone, options."""
        st = self._state
        if not st.show_pigeon_settings:
            return ()
        st.refresh_pigeon_status()
        try:
            from pigeon.pigeon_locale import timezone_abbrev, zipcode_display_text

            locale = (zipcode_display_text(), timezone_abbrev())
        except Exception:
            locale = ("", "")
        return (
            locale,
            bool(st.pigeon_metadata_ok),
            bool(st.pigeon_audio_ok),
            bool(st.pigeon_network_ok),
            str(st.live_wifi_ssid or ""),
            str(st.ui_color_committed_key or ""),
            tuple(sorted((str(k), str(v)) for k, v in (st.options_values or {}).items())),
            bool(st.tz_dropdown_open),
            int(st.tz_dropdown_index) if st.tz_dropdown_open else -1,
        )

    def _main_state_sig(self) -> tuple[object, ...]:
        st = self._state
        th = st.theme
        kb = st.keyboard
        kb_main: tuple[object, ...] = ()
        if kb is not None:
            kb_main = (
                getattr(kb, "mode", None),
                str(getattr(kb, "buffer", "")),
                str(getattr(kb, "target", "")),
                str(getattr(kb, "initial_text", "")),
                bool(getattr(kb, "supports_lowercase", True)),
                int(getattr(kb, "focus_index", 0) or 0)
                if str(getattr(kb, "target", "") or "") == "wifi_logout"
                else -1,
            )
        return (
            int(st.focus_index) if not st.keyboard_open else -1,
            st.focus_ring,
            th.ui,
            th.selected,
            th.deselected,
            th.inactive,
            th.accent,
            int(st.wifi_level),
            st.location_name,
            st.wifi_password,
            st.selected_wifi_ssid,
            st.live_wifi_ssid,
            bool(st.wifi_logged_out),
            st.displayed_wifi_ssid(),
            st.pending_wifi_ssid,
            bool(st.network_password_error),
            bool(st.wifi_connecting),
            st.version_string,
            bool(st.exit_enabled),
            bool(st.show_network_picker),
            int(st.network_picker_row),
            int(st.network_picker_scroll),
            str(st.network_picker_arrow),
            bool(st.show_instructions),
            bool(st.wifi_onboarding),
            bool(st.wifi_scanning),
            st.wifi_networks,
            bool(st.show_box1_panel),
            bool(st.show_box2_panel),
            bool(st.show_box3_panel),
            bool(st.show_location_picker),
            bool(st.location_switching),
            bool(st.location_switch_spinner_visible()),
            round(float(st.location_switch_angle_deg) / 10.0)
            if st.location_switch_spinner_visible()
            else -1,
            tuple(st.location_slots),
            str(st.renaming_location_id),
            int(st.renaming_location_slot),
            tuple(st.box2_devices.devices),
            st.box2_devices.phase,
            bool(st.box2_devices.scanning),
            int(st.box2_devices.scroll),
            int(st.box2_devices.row),
            str(st.box2_devices.arrow),
            st.box2_devices.picked,
            tuple(st.box3_devices.devices),
            st.box3_devices.phase,
            bool(st.box3_devices.scanning),
            int(st.box3_devices.scroll),
            int(st.box3_devices.row),
            str(st.box3_devices.arrow),
            st.box3_devices.picked,
            bool(st.show_pigeon_settings),
            int(st.pigeon_focus_index),
            str(st.pigeon_view),
            bool(st.pigeon_needs_update_prefetch),
            st.pigeon_metadata_ok,
            bool(st.pigeon_audio_ok),
            bool(st.wifi_configured),
            bool(st.show_preferences),
            self._metadata_debug_sig(),
            str(st.preferences_nav or ""),
            int(st.preferences_focus_index),
            int(st.preferences_active_zone),
            tuple(st.preferences_zone_widgets),
            str(st.ui_color_accent_key or ""),
            str(st.ui_color_ui_key or ""),
            str(st.ui_color_button_key or ""),
            self._pigeon_page_sig(),
            str(st.theme.ui),
            str(st.theme.accent),
            str(st.theme.deselected),
            bool(st.show_update_popup),
            bool(st.update_available),
            bool(st.update_checking),
            bool(st.update_applying),
            bool(st.update_latest_confirmed),
            round(float(st.update_progress), 3),
            str(st.update_local_version or ""),
            str(st.update_remote_version or ""),
            str(st.update_changelog or ""),
            str(st.update_error or ""),
            int(st.update_popup_focus_index),
            bool(st.keyboard_open),
            str(self._svg_path or ""),
            str(self._assets_dir or ""),
            kb_main,
            None if st.box_pairing is None else (
                int(st.box_pairing.box_num),
                str(st.box_pairing.step),
                str(st.box_pairing.session_key),
                str(st.box_pairing.device_name),
            ),
            self._scan_anim_token(),
        )

    def _keyboard_overlay_sig(self) -> tuple[object, ...] | None:
        kb = self._state.keyboard
        if kb is None:
            return None
        return self._keyboard_overlay_sig_for(
            getattr(kb, "mode", None),
            int(getattr(kb, "focus_index", 0)),
            supports_lowercase=bool(getattr(kb, "supports_lowercase", True)),
            target=str(getattr(kb, "target", "") or ""),
        )

    def _structure_sig(self) -> tuple[object, ...]:
        """State that forces a full SVG rebuild (everything except pure focus indices)."""
        st = self._state
        th = st.theme
        kb = st.keyboard
        kb_main: tuple[object, ...] = ()
        if kb is not None:
            kb_main = (
                getattr(kb, "mode", None),
                # Buffer is Pillow-patched on chrome — not SVG structure.
                str(getattr(kb, "target", "")),
                str(getattr(kb, "initial_text", "")),
                bool(getattr(kb, "supports_lowercase", True)),
            )
        return (
            st.focus_ring,
            th.ui,
            th.selected,
            th.deselected,
            th.inactive,
            th.accent,
            int(st.wifi_level),
            st.location_name,
            st.wifi_password,
            st.selected_wifi_ssid,
            st.live_wifi_ssid,
            bool(st.wifi_logged_out),
            st.displayed_wifi_ssid(),
            st.pending_wifi_ssid,
            bool(st.network_password_error),
            bool(st.wifi_connecting),
            st.version_string,
            bool(st.show_network_picker),
            int(st.network_picker_scroll),
            str(st.network_picker_arrow),
            bool(st.show_instructions),
            bool(st.wifi_onboarding),
            bool(st.wifi_scanning),
            st.wifi_networks,
            bool(st.show_box1_panel),
            bool(st.show_box2_panel),
            bool(st.show_box3_panel),
            bool(st.show_location_picker),
            bool(st.location_switching),
            bool(st.location_switch_spinner_visible()),
            round(float(st.location_switch_angle_deg) / 10.0)
            if st.location_switch_spinner_visible()
            else -1,
            tuple(st.location_slots),
            str(st.renaming_location_id),
            int(st.renaming_location_slot),
            tuple(st.box2_devices.devices),
            st.box2_devices.phase,
            bool(st.box2_devices.scanning),
            int(st.box2_devices.scroll),
            st.box2_devices.picked,
            tuple(st.box3_devices.devices),
            st.box3_devices.phase,
            bool(st.box3_devices.scanning),
            int(st.box3_devices.scroll),
            st.box3_devices.picked,
            bool(st.show_pigeon_settings),
            bool(st.pigeon_audio_ok),
            bool(st.show_preferences),
            str(st.preferences_nav or ""),
            int(st.preferences_active_zone),
            # Zone widget assignments are focus-key only (change every widget nav).
            str(st.ui_color_accent_key or ""),
            str(st.ui_color_ui_key or ""),
            str(st.ui_color_button_key or ""),
            self._pigeon_page_sig(),
            str(st.theme.ui),
            str(st.theme.accent),
            str(st.theme.deselected),
            bool(st.show_update_popup),
            bool(st.update_available),
            bool(st.update_checking),
            bool(st.update_applying),
            round(float(st.update_progress), 3),
            str(st.update_remote_version or ""),
            str(st.update_changelog or ""),
            str(st.update_error or ""),
            bool(st.keyboard_open),
            str(self._svg_path or ""),
            str(self._assets_dir or ""),
            kb_main,
            None
            if st.box_pairing is None
            else (
                int(st.box_pairing.box_num),
                str(st.box_pairing.step),
                str(st.box_pairing.session_key),
                str(st.box_pairing.device_name),
            ),
        )

    def _focus_cache_key(self) -> tuple[object, ...]:
        """Must match ``_focus_key_for_state`` so off-thread prewarm can hit."""
        return self._focus_key_for_state(self._state)

    def _store_focus_frame(self, frame: np.ndarray) -> None:
        if self._status_bar_animating():
            return
        structure = self._structure_sig()
        if structure != self._focus_cache_structure:
            self._focus_frame_cache.clear()
            self._focus_cache_structure = structure
        key = self._focus_cache_key()
        if key not in self._focus_frame_cache:
            self._focus_frame_cache[key] = frame.copy()
            # Bound memory: keep recent focus + list-row bitmaps (WiFi 3 / box 5).
            if len(self._focus_frame_cache) > 20:
                oldest = next(iter(self._focus_frame_cache))
                if oldest != key:
                    self._focus_frame_cache.pop(oldest, None)

    def _list_row_count(self) -> int | None:
        """Visible selection rows when WiFi picker or box results are locked."""
        st = self._state
        if st.show_network_picker and not st.wifi_configured:
            return len(_PICKER_ROW_TEXTS)
        for box_num in (2, 3):
            if st._box_panel(box_num).results_locked:
                return int(_BOX_DEVICE_ROW_COUNT)
        return None

    def _current_list_row(self) -> int | None:
        st = self._state
        if st.show_network_picker and not st.wifi_configured:
            return int(st.network_picker_row)
        for box_num in (2, 3):
            panel = st._box_panel(box_num)
            if panel.results_locked:
                return int(panel.row)
        return None

    def _apply_list_row(self, st: MainSettingsState, row: int) -> None:
        if st.show_network_picker and not st.wifi_configured:
            st.network_picker_row = int(row)
            st.network_picker_arrow = ""
            return
        for box_num in (2, 3):
            panel = st._box_panel(box_num)
            if panel.results_locked:
                panel.row = int(row)
                panel.arrow = ""
                return

    def _focus_key_for_state(self, st: MainSettingsState) -> tuple[object, ...]:
        kb = st.keyboard
        logout_focus = -1
        if kb is not None and str(getattr(kb, "target", "") or "") == "wifi_logout":
            logout_focus = int(getattr(kb, "focus_index", 0) or 0)
        return (
            int(st.focus_index) if not st.keyboard_open else logout_focus,
            int(st.network_picker_row),
            int(st.box2_devices.row),
            str(st.box2_devices.arrow),
            int(st.box3_devices.row),
            str(st.box3_devices.arrow),
            int(st.pigeon_focus_index),
            str(st.pigeon_view),
            int(st.preferences_focus_index) if st.show_preferences else -1,
            str(st.preferences_nav or "") if st.show_preferences else "",
            int(st.preferences_active_zone) if st.show_preferences else 0,
            tuple(st.preferences_zone_widgets) if st.show_preferences else (),
            str(st.theme.ui),
            int(st.update_popup_focus_index) if st.show_update_popup else -1,
            bool(st.show_update_popup),
        )

    def navigate(self, forward: bool = True) -> None:
        st = self._state
        if st.keyboard is not None:
            st.navigate(forward=forward)
            kb = st.keyboard
            mode = getattr(kb, "mode", None) if kb is not None else None
            if self._kb_cache_mode is None:
                self._kb_cache_mode = mode
            elif self._kb_cache_mode != mode:
                self._clear_keyboard_focus_caches()
                self._kb_cache_mode = mode
            kb_sig = self._keyboard_overlay_sig()
            # Soft reuse: keep per-key overlays; only drop composed PhotoImage input.
            self._cached_bgra = None
            self._cached_sig = None
            self._paste_fully_opaque = None
            if kb_sig is not None and kb_sig in self._kb_focus_frame_cache:
                self._cached_kb_bgra = self._kb_focus_frame_cache[kb_sig]
                self._cached_kb_sig = kb_sig
            else:
                self._cached_kb_bgra = None
                self._cached_kb_sig = None
            self._prewarm_neighbor_keyboard(forward=forward)
            return
        if st.show_pigeon_settings:
            st.navigate_pigeon(forward=forward)
            # Soft nav — reuse per-focus pigeon bitmaps like main chrome.
            self._cached_bgra = None
            self._cached_sig = None
            self._paste_fully_opaque = None
            if st.show_metadata_debug:
                # Inspector pages render live; a grid focus bitmap here would
                # be served by bgra_frame() as the "current" frame and make
                # arrow presses appear to exit to the settings grid.
                self._cached_main_bgra = None
                self._cached_main_sig = None
                return
            focus_key = self._focus_cache_key()
            structure = self._structure_sig()
            if (
                structure == self._focus_cache_structure
                and focus_key in self._focus_frame_cache
            ):
                self._cached_main_bgra = self._focus_frame_cache[focus_key]
                self._cached_main_sig = self._main_state_sig()
            else:
                self._cached_main_bgra = None
                self._cached_main_sig = None
            self._prewarm_neighbor_focus(forward=forward)
            return
        st.navigate(forward=forward)
        # Drop composed frame so PhotoImage refreshes; reuse focus bitmap when available.
        self._cached_bgra = None
        self._cached_sig = None
        self._paste_fully_opaque = None
        focus_key = self._focus_cache_key()
        structure = self._structure_sig()
        if structure != self._focus_cache_structure:
            # Scroll / list content changed — refill row bitmaps after the next live paint.
            self._want_prewarm_after_paint = True
        if (
            structure == self._focus_cache_structure
            and focus_key in self._focus_frame_cache
        ):
            self._cached_main_bgra = self._focus_frame_cache[focus_key]
            self._cached_main_sig = self._main_state_sig()
        else:
            self._cached_main_bgra = None
            self._cached_main_sig = None
        self.prefetch_scans_for_focus(st.focused_id)
        self._prewarm_neighbor_focus(forward=forward)

    def prewarm_focus_ring(self) -> None:
        """Rasterize every focus / list-row target for the current structure off-thread."""
        import copy
        import threading

        if self._prewarm_all_inflight:
            return
        st = self._state
        if st.keyboard_open:
            return
        structure = self._structure_sig()
        if st.show_pigeon_settings and st.show_preferences:
            from pigeon.widgets.preferences_settings import (
                preferences_widget_focus_ring,
                preferences_zone_focus_ring,
                render_preferences_settings_bgra,
            )

            if str(st.preferences_nav or "") == "widgets":
                ring = preferences_widget_focus_ring(int(st.preferences_active_zone))
            else:
                ring = preferences_zone_focus_ring()
            n = len(ring)
            if n <= 1:
                return
            missing = []
            for idx in range(n):
                probe = copy.deepcopy(st)
                probe.preferences_focus_index = idx
                if self._focus_key_for_state(probe) not in self._focus_frame_cache:
                    missing.append(idx)
            if not missing:
                return
            self._prewarm_all_inflight = True
            state_snap = copy.deepcopy(st)
            assets_dir = self._assets_dir
            cache = self._focus_frame_cache
            struct_ref = structure

            def _work_prefs() -> None:
                try:
                    for idx in missing:
                        if self._focus_cache_structure not in (None, struct_ref):
                            return
                        state_snap.preferences_focus_index = idx
                        # Mirror live widget assignment while prewarming widget nav.
                        if str(state_snap.preferences_nav or "") == "widgets":
                            focused = ring[idx % n]
                            zone = int(state_snap.preferences_active_zone)
                            if focused != "exit" and 1 <= zone <= 5:
                                widgets = list(state_snap.preferences_zone_widgets)
                                widgets[zone - 1] = focused
                                state_snap.preferences_zone_widgets = (
                                    widgets[0],
                                    widgets[1],
                                    widgets[2],
                                    widgets[3],
                                    widgets[4],
                                )
                        key = self._focus_key_for_state(state_snap)
                        if key in cache:
                            continue
                        try:
                            frame = render_preferences_settings_bgra(
                                state_snap, assets_dir=assets_dir
                            )
                        except Exception:
                            return
                        if self._focus_cache_structure not in (None, struct_ref):
                            return
                        if self._focus_cache_structure is None:
                            self._focus_cache_structure = struct_ref
                        cache[key] = frame
                finally:
                    self._prewarm_all_inflight = False

            import threading as _threading

            _threading.Thread(
                target=_work_prefs, name="prefs-prewarm-all", daemon=True
            ).start()
            return
        if st.show_pigeon_settings:
            from pigeon.widgets.pigeon_settings import (
                color_key_for_focus,
                pigeon_focus_ring,
                render_pigeon_settings_bgra,
            )

            if st.tz_dropdown_open or st.show_update_popup or st.show_metadata_debug:
                return
            ring = pigeon_focus_ring(st.pigeon_view)
            n = len(ring)
            if n <= 1:
                return
            missing = []
            for idx in range(n):
                # Color focus re-themes the page, so those frames never share
                # this structure — render them live instead.
                if color_key_for_focus(ring[idx]) is not None:
                    continue
                probe = copy.deepcopy(st)
                probe.pigeon_focus_index = idx
                if self._focus_key_for_state(probe) not in self._focus_frame_cache:
                    missing.append(idx)
            if not missing:
                return
            self._prewarm_all_inflight = True
            state_snap = copy.deepcopy(st)
            assets_dir = self._assets_dir
            cache = self._focus_frame_cache
            struct_ref = structure

            def _work_pigeon() -> None:
                try:
                    for idx in missing:
                        if self._focus_cache_structure not in (None, struct_ref):
                            return
                        state_snap.pigeon_focus_index = idx
                        key = self._focus_key_for_state(state_snap)
                        if key in cache:
                            continue
                        try:
                            frame = render_pigeon_settings_bgra(
                                state_snap, assets_dir=assets_dir
                            )
                        except Exception:
                            return
                        if self._focus_cache_structure not in (None, struct_ref):
                            return
                        if self._focus_cache_structure is None:
                            self._focus_cache_structure = struct_ref
                        cache[key] = frame
                finally:
                    self._prewarm_all_inflight = False

            threading.Thread(
                target=_work_pigeon, name="pigeon-submenu-prewarm", daemon=True
            ).start()
            return
        row_count = self._list_row_count()
        # Search results: focus ring is length 1 — prewarm selection rows instead.
        if row_count is not None:
            cur = self._current_list_row() or 0
            # Prefer rows ahead of the selection so the next Left/Right is ready first.
            order = list(range(cur + 1, row_count)) + list(range(0, cur))
            missing: list[int] = []
            for row in order:
                snap_probe = copy.deepcopy(st)
                self._apply_list_row(snap_probe, row)
                key = self._focus_key_for_state(snap_probe)
                if key not in self._focus_frame_cache:
                    missing.append(row)
            if not missing:
                return
            self._prewarm_all_inflight = True
            state_snap = copy.deepcopy(st)
            svg_path = self._svg_path
            assets_dir = self._assets_dir
            cache = self._focus_frame_cache
            struct_ref = structure

            def _work_rows() -> None:
                try:
                    for row in missing:
                        if self._focus_cache_structure not in (None, struct_ref):
                            return
                        self._apply_list_row(state_snap, row)
                        key = self._focus_key_for_state(state_snap)
                        if key in cache:
                            continue
                        try:
                            frame = render_main_settings_bgra(
                                state_snap,
                                svg_path=svg_path,
                                assets_dir=assets_dir,
                            )
                        except Exception:
                            return
                        if self._focus_cache_structure not in (None, struct_ref):
                            return
                        if self._focus_cache_structure is None:
                            self._focus_cache_structure = struct_ref
                        cache[key] = frame
                finally:
                    self._prewarm_all_inflight = False

            threading.Thread(
                target=_work_rows, name="pigeon-settings-prewarm-rows", daemon=True
            ).start()
            return

        if not st.focus_ring:
            return
        n = len(st.focus_ring)
        if n <= 1:
            return
        self._prewarm_all_inflight = True
        state_snap = copy.deepcopy(st)
        svg_path = self._svg_path
        assets_dir = self._assets_dir
        cache = self._focus_frame_cache
        struct_ref = structure

        def _work() -> None:
            try:
                for idx in range(n):
                    if self._focus_cache_structure not in (None, struct_ref):
                        return
                    state_snap.focus_index = idx
                    key = self._focus_key_for_state(state_snap)
                    if key in cache:
                        continue
                    try:
                        frame = render_main_settings_bgra(
                            state_snap,
                            svg_path=svg_path,
                            assets_dir=assets_dir,
                        )
                    except Exception:
                        return
                    if self._focus_cache_structure not in (None, struct_ref):
                        return
                    if self._focus_cache_structure is None:
                        self._focus_cache_structure = struct_ref
                    cache[key] = frame
            finally:
                self._prewarm_all_inflight = False

        threading.Thread(target=_work, name="pigeon-settings-prewarm-all", daemon=True).start()

    def _prewarm_neighbor_focus(self, *, forward: bool) -> None:
        """Rasterize the next focus/list-row target off-thread for the following keypress."""
        import copy
        import threading

        structure = self._structure_sig()
        if structure != self._focus_cache_structure:
            return
        st = self._state
        if st.keyboard_open:
            return

        if st.show_pigeon_settings and st.show_preferences:
            from pigeon.widgets.preferences_settings import (
                preferences_widget_focus_ring,
                preferences_zone_focus_ring,
                render_preferences_settings_bgra,
            )

            if str(st.preferences_nav or "") == "widgets":
                ring = preferences_widget_focus_ring(int(st.preferences_active_zone))
            else:
                ring = preferences_zone_focus_ring()
            n = len(ring)
            if n <= 0:
                return
            nxt = (int(st.preferences_focus_index) + (1 if forward else -1)) % n
            snap = copy.deepcopy(st)
            snap.preferences_focus_index = nxt
            focused = ring[nxt]
            zone = int(snap.preferences_active_zone)
            if (
                str(snap.preferences_nav or "") == "widgets"
                and focused != "exit"
                and 1 <= zone <= 5
            ):
                widgets = list(snap.preferences_zone_widgets)
                widgets[zone - 1] = focused
                snap.preferences_zone_widgets = (
                    widgets[0],
                    widgets[1],
                    widgets[2],
                    widgets[3],
                    widgets[4],
                )
            key_probe = self._focus_key_for_state(snap)
            if key_probe in self._focus_frame_cache:
                return
            assets = self._assets_dir
            cache = self._focus_frame_cache
            struct_ref = structure

            def _work_prefs_n() -> None:
                try:
                    frame = render_preferences_settings_bgra(snap, assets_dir=assets)
                except Exception:
                    return
                if self._focus_cache_structure != struct_ref:
                    return
                cache.setdefault(key_probe, frame)

            threading.Thread(
                target=_work_prefs_n, name="prefs-prewarm-n", daemon=True
            ).start()
            return

        if st.show_pigeon_settings:
            from pigeon.widgets.pigeon_settings import (
                color_key_for_focus,
                pigeon_focus_ring,
                render_pigeon_settings_bgra,
            )

            if st.tz_dropdown_open or st.show_update_popup or st.show_metadata_debug:
                return
            ring = pigeon_focus_ring(st.pigeon_view)
            n = len(ring)
            nxt = (int(st.pigeon_focus_index) + (1 if forward else -1)) % n
            if color_key_for_focus(ring[nxt]) is not None:
                return
            snap = copy.deepcopy(st)
            snap.pigeon_focus_index = nxt
            key_probe = self._focus_key_for_state(snap)
            if key_probe in self._focus_frame_cache:
                return
            assets = self._assets_dir
            cache = self._focus_frame_cache
            struct_ref = structure

            def _work_pigeon_n() -> None:
                try:
                    frame = render_pigeon_settings_bgra(snap, assets_dir=assets)
                except Exception:
                    return
                if self._focus_cache_structure != struct_ref:
                    return
                cache.setdefault(key_probe, frame)

            threading.Thread(
                target=_work_pigeon_n, name="pigeon-submenu-prewarm-n", daemon=True
            ).start()
            return

        row_count = self._list_row_count()
        if row_count is not None:
            cur = self._current_list_row()
            if cur is None:
                return
            nxt = int(cur) + (1 if forward else -1)
            if nxt < 0 or nxt >= row_count:
                return
            snap = copy.deepcopy(st)
            self._apply_list_row(snap, nxt)
            key_probe = self._focus_key_for_state(snap)
            if key_probe in self._focus_frame_cache:
                return
            assets = self._assets_dir
            svg = self._svg_path
            cache = self._focus_frame_cache
            struct_ref = structure

            def _work_row() -> None:
                try:
                    frame = render_main_settings_bgra(snap, svg_path=svg, assets_dir=assets)
                except Exception:
                    return
                if self._focus_cache_structure != struct_ref:
                    return
                cache.setdefault(key_probe, frame)

            threading.Thread(
                target=_work_row, name="pigeon-settings-prewarm-row", daemon=True
            ).start()
            return

        if not st.focus_ring:
            return
        n = len(st.focus_ring)
        nxt = (int(st.focus_index) + (1 if forward else -1)) % n
        snap = copy.deepcopy(st)
        snap.focus_index = nxt
        key_probe = self._focus_key_for_state(snap)
        if key_probe in self._focus_frame_cache:
            return
        assets = self._assets_dir
        svg = self._svg_path
        cache = self._focus_frame_cache
        struct_ref = structure

        def _work() -> None:
            try:
                frame = render_main_settings_bgra(snap, svg_path=svg, assets_dir=assets)
            except Exception:
                return
            if self._focus_cache_structure != struct_ref:
                return
            cache.setdefault(key_probe, frame)

        threading.Thread(target=_work, name="pigeon-settings-prewarm", daemon=True).start()

    def prewarm_keyboard_focus(self) -> None:
        """Rasterize idle + remaining keys off-thread (patches, not full-frame L1)."""
        import copy
        import threading

        if self._kb_prewarm_inflight:
            return
        st = self._state
        kb = st.keyboard
        if kb is None or not kb.focus_ring:
            return
        mode = getattr(kb, "mode", None)
        supports_lower = bool(getattr(kb, "supports_lowercase", True))
        kb_target = str(getattr(kb, "target", "") or "")
        if self._kb_cache_mode not in (None, mode):
            self._clear_keyboard_focus_caches()
        self._kb_cache_mode = mode
        n = len(kb.focus_ring)
        cur = int(kb.focus_index) % n
        from pigeon.widgets.settings_keyboard import keyboard_overlay_cached

        probe = copy.copy(kb)
        needs_work = False
        for i in range(n):
            probe.focus_index = i
            if not keyboard_overlay_cached(probe, assets_dir=self._assets_dir):
                needs_work = True
                break
        if not needs_work:
            return
        # Neighbors first, then the rest of the ring so wrap-around stays warm.
        order = [(cur + 1) % n, (cur - 1) % n]
        for i in range(n):
            idx = (cur + i) % n
            if idx not in order:
                order.append(idx)
        self._kb_prewarm_inflight = True
        assets = self._assets_dir
        mode_ref = mode
        lower_ref = supports_lower
        target_ref = kb_target

        def _work() -> None:
            try:
                from pigeon.widgets.settings_keyboard import (
                    keyboard_overlay_cached,
                    render_keyboard_bgra,
                    warm_keyboard_idle,
                )

                if self._state.keyboard is None:
                    return
                live = self._state.keyboard
                if getattr(live, "mode", None) != mode_ref:
                    return
                if bool(getattr(live, "supports_lowercase", True)) != lower_ref:
                    return
                if str(getattr(live, "target", "") or "") != target_ref:
                    return
                snap = copy.copy(live)
                warm_keyboard_idle(snap, assets_dir=assets)
                for idx in order:
                    if self._state.keyboard is None:
                        return
                    if getattr(self._state.keyboard, "mode", None) != mode_ref:
                        return
                    snap.focus_index = idx
                    if keyboard_overlay_cached(snap, assets_dir=assets):
                        continue
                    try:
                        render_keyboard_bgra(snap, assets_dir=assets)
                    except Exception:
                        return
            finally:
                self._kb_prewarm_inflight = False

        threading.Thread(
            target=_work, name="pigeon-settings-prewarm-kb", daemon=True
        ).start()

    def _prewarm_neighbor_keyboard(self, *, forward: bool) -> None:
        """Rasterize the next keyboard key overlay off-thread."""
        import copy
        import threading

        kb = self._state.keyboard
        if kb is None or not kb.focus_ring:
            return
        mode = getattr(kb, "mode", None)
        supports_lower = bool(getattr(kb, "supports_lowercase", True))
        kb_target = str(getattr(kb, "target", "") or "")
        if self._kb_cache_mode not in (None, mode):
            return
        n = len(kb.focus_ring)
        nxt = (int(kb.focus_index) + (1 if forward else -1)) % n
        snap = copy.copy(kb)
        snap.focus_index = nxt
        from pigeon.widgets.settings_keyboard import keyboard_overlay_cached

        if keyboard_overlay_cached(snap, assets_dir=self._assets_dir):
            nxt2 = (nxt + (1 if forward else -1)) % n
            snap.focus_index = nxt2
            if keyboard_overlay_cached(snap, assets_dir=self._assets_dir):
                return
            nxt = nxt2
        snap.focus_index = nxt
        assets = self._assets_dir
        mode_ref = mode
        lower_ref = supports_lower
        target_ref = kb_target
        cache = self._kb_focus_frame_cache
        key = self._keyboard_overlay_sig_for(
            mode,
            nxt,
            supports_lowercase=supports_lower,
            target=kb_target,
        )

        def _work() -> None:
            try:
                from pigeon.widgets.settings_keyboard import render_keyboard_bgra

                frame = render_keyboard_bgra(snap, assets_dir=assets)
            except Exception:
                return
            if self._state.keyboard is None:
                return
            live = self._state.keyboard
            if getattr(live, "mode", None) != mode_ref:
                return
            if bool(getattr(live, "supports_lowercase", True)) != lower_ref:
                return
            if str(getattr(live, "target", "") or "") != target_ref:
                return
            cache.setdefault(key, frame)

        threading.Thread(
            target=_work, name="pigeon-settings-prewarm-kb-n", daemon=True
        ).start()

    def navigate_vertical(self, *, up: bool) -> None:
        """Vertical navigation disabled — use left/right only."""
        return

    def _any_box_scanning(self) -> bool:
        if self._state.keyboard_open:
            return False
        return bool(self._state.box2_devices.scanning or self._state.box3_devices.scanning)

    def tick(self) -> None:
        """Advance WiFi/box/location-switch animations; complete when platform scan returns."""
        st = self._state
        now = time.monotonic()
        dt = max(0.0, now - self._last_tick_mono)
        self._last_tick_mono = now
        invalidated = False
        if st.keyboard is not None:
            # Overlay is painted per frame in render(); no chrome invalidation.
            st.sync_search_suggestions()
        if st.wifi_scanning or st.wifi_connecting:
            st.wifi_scan_angle_deg = (st.wifi_scan_angle_deg + _WIFI_SCAN_ROTATION_DPS * dt) % 360.0
        if st.location_switching:
            # Keep advancing once the delayed spinner is eligible so frames stay smooth.
            if st.location_switch_spinner_visible():
                prev = st.location_switch_angle_deg
                st.location_switch_angle_deg = (
                    st.location_switch_angle_deg + _LOCATION_SWITCH_ROTATION_DPS * dt
                ) % 360.0
                if int(round(prev / 10.0)) != int(round(st.location_switch_angle_deg / 10.0)):
                    invalidated = True
            elif (now - float(st.location_switch_started_mono)) >= float(
                _LOCATION_SWITCH_SPINNER_DELAY_S
            ):
                # Crossed the delay threshold — force a paint so the spinner appears.
                invalidated = True
        if st.wifi_scanning:
            elapsed = now - st.wifi_scan_started_mono
            result_ready = self._wifi_scan_result is not None
            timed_out = elapsed >= _WIFI_SCAN_MAX_DURATION_S
            if result_ready or timed_out:
                networks = self._wifi_scan_result if self._wifi_scan_result is not None else ()
                st.complete_wifi_scan(networks)
                if networks:
                    self._wifi_scan_cache = (networks, now)
                self._wifi_scan_result = None
                self._wifi_search_glyph_cache = None
                self._wifi_search_rotated_cache = None
                invalidated = True
        for box_num in (2, 3):
            panel = st._box_panel(box_num)
            pending = box_num in self._box_scan_pending
            if panel.scanning:
                panel.scan_angle_deg = (panel.scan_angle_deg + _BOX_SCAN_ROTATION_DPS * dt) % 360.0
                invalidated = True
            if not panel.scanning and not pending:
                continue
            elapsed = now - panel.scan_started_mono
            result = self._box_scan_result.get(box_num)
            if result is None:
                cached = self._cached_box_scan(box_num)
                if cached is not None:
                    result = cached
                    self._box_scan_result[box_num] = cached
            result_ready = result is not None and bool(result[0] or result[1])
            hold_s = float(getattr(panel, "scan_duration_s", 0.0) or _BOX_SCAN_MAX_DURATION_S)
            min_hold = min(hold_s, _BOX_SCAN_LIVE_MIN_S)
            timed_out = elapsed >= _BOX_SCAN_MAX_DURATION_S
            if (result_ready and elapsed >= min_hold) or timed_out:
                devices = result if result is not None else ()
                self._box_scan_result.pop(box_num, None)
                self._box_scan_pending.discard(box_num)
                self._clear_box_search_spinner_cache(box_num)
                if panel.scanning:
                    st.complete_box_device_scan(box_num, devices)
                    if devices:
                        self._box_scan_cache[box_num] = (*devices, now)
                    self._pre_scan_main_bgra.pop(box_num, None)
                elif devices:
                    # UI was aborted mid-scan — keep results for the next open.
                    self._box_scan_cache[box_num] = (*devices, now)
                invalidated = True
                self.invalidate()
        self._maybe_refresh_box_scan_cache()
        if invalidated and not (
            st.wifi_scanning
            or self._any_box_scanning()
            or st.location_switch_spinner_visible()
        ):
            self.invalidate()
        elif invalidated:
            # Spinner still animating — drop composed frames so the next blit rotates.
            self._cached_bgra = None
            self._cached_sig = None
            self._cached_main_bgra = None
            self._cached_main_sig = None

    def _ensure_location_switch_spinner_frames(self) -> tuple[np.ndarray, ...] | None:
        if self._location_switch_spinner_frames is not None:
            return self._location_switch_spinner_frames
        if self._location_switch_spinner_tried:
            return None
        self._location_switch_spinner_tried = True
        try:
            from pigeon.widgets.search_spinner import build_search_spinner_frames

            frames = build_search_spinner_frames(self._assets_dir)
        except Exception:
            frames = None
        if frames:
            self._location_switch_spinner_frames = frames
        return self._location_switch_spinner_frames

    def _draw_location_switch_spinner(self, frame: np.ndarray) -> None:
        frames = self._ensure_location_switch_spinner_frames()
        if not frames:
            return
        from pigeon.widgets.search_spinner import blit_spinner_patch, rotated_patch_for_angle

        patch = rotated_patch_for_angle(frames, self._state.location_switch_angle_deg)
        blit_spinner_patch(
            frame,
            patch,
            cx=int(DESIGN_W) // 2,
            cy=int(DESIGN_H) // 2,
        )

    def _apply_location_switch_overlay(self, frame: np.ndarray) -> None:
        if not self._state.location_switch_spinner_visible():
            return
        self._draw_location_switch_spinner(frame)

    def _clear_box_search_spinner_cache(self, box_num: int) -> None:
        self._box_search_glyph_cache.pop(box_num, None)
        self._box_search_rotated_cache.pop(box_num, None)

    def _search_glyph_center_px(self) -> tuple[int, int]:
        return _svg_to_px(_WIFI_SEARCH_CENTER_SVG[0], _WIFI_SEARCH_CENTER_SVG[1])

    def _build_wifi_search_glyph_patch(self) -> np.ndarray | None:
        """Render glyph-only patch (transparent bg) for rotation during scan."""
        if self._svg_path is not None:
            path = Path(self._svg_path)
        else:
            path = default_main_settings_svg_path(self._assets_dir)
        if not path.is_file():
            return None
        root = _svg_tree_from_path(path)
        arc_specs = _discover_onboarding_search_arc_specs(root)
        triangle_specs = _discover_onboarding_search_triangle_specs(root)
        if not arc_specs and not triangle_specs:
            return None
        cx_px, cy_px = self._search_glyph_center_px()
        r = _WIFI_SEARCH_PATCH_RADIUS_PX
        x0 = max(0, cx_px - r)
        y0 = max(0, cy_px - r)
        patch = np.zeros((2 * r, 2 * r, 4), dtype=np.uint8)
        _draw_onboarding_search_arc_overlays_on_patch(
            patch, arc_specs, origin_x0=x0, origin_y0=y0, color_bgr=_WIFI_SEARCH_GLYPH_BGR
        )
        _draw_triangle_specs_on_patch(
            patch,
            triangle_specs,
            origin_x0=x0,
            origin_y0=y0,
            color_bgr=_WIFI_SEARCH_GLYPH_BGR,
        )
        return _mask_wifi_search_glyph_patch(patch)

    def _ensure_wifi_search_glyph_cache(self) -> None:
        if self._wifi_search_rotated_cache is not None:
            return
        patch = self._build_wifi_search_glyph_patch()
        if patch is not None:
            self._wifi_search_glyph_cache = patch
            self._wifi_search_rotated_cache = _precompute_rotated_patches(patch)

    def _cached_wifi_scan(self) -> tuple[str, ...] | None:
        cached = self._wifi_scan_cache
        if cached is None:
            return None
        networks, ts = cached
        if time.monotonic() - ts > _WIFI_SCAN_CACHE_TTL_S:
            self._wifi_scan_cache = None
            return None
        return networks

    def _box_cache_age_s(self, box_num: int) -> float | None:
        cached = self._box_scan_cache.get(box_num)
        if cached is None:
            return None
        return time.monotonic() - float(cached[-1])

    def _cached_box_scan(self, box_num: int) -> tuple[tuple[tuple[str, str], ...], tuple[dict[str, str], ...]] | None:
        cached = self._box_scan_cache.get(box_num)
        if cached is None:
            return None
        display, rows, ts = cached
        if time.monotonic() - ts > _BOX_SCAN_CACHE_TTL_S:
            self._box_scan_cache.pop(box_num, None)
            return None
        return display, rows

    def _wifi_prefetch_needed(self) -> bool:
        return self._cached_wifi_scan() is None and not getattr(self, "_wifi_prefetch_inflight", False)

    def _box_prefetch_needed(self, box_num: int) -> bool:
        if box_num in getattr(self, "_box_prefetch_inflight", set()):
            return False
        if getattr(self, "_box_prefetch_shared_inflight", False):
            return False
        age = self._box_cache_age_s(box_num)
        return age is None or age >= _BOX_PREFETCH_INTERVAL_S

    def prefetch_scans_for_settings(self) -> None:
        """Silent background scans so Space on WiFi/box buttons can finish from cache."""
        st = self._state
        if not st.wifi_configured:
            self._prefetch_wifi_into_cache()
        else:
            self._prefetch_boxes_shared()
        self._ensure_periodic_box_prefetch()
        # Full-ring prewarm after the first live paint — avoid contending with cold SVG.
        self._want_prewarm_after_paint = True
        self._prewarm_neighbor_focus(forward=True)

    def prefetch_scans_for_focus(self, focused: str) -> None:
        """Prefetch when the user lands on a search-capable control."""
        if focused in ("main_dual_network_button", "main_box2_add_search_icon"):
            if not self._state.wifi_configured:
                self._prefetch_wifi_into_cache()
            return
        if focused in ("main_box2_button", "main_box3_button"):
            self._prefetch_boxes_shared()

    def _ensure_periodic_box_prefetch(self) -> None:
        if getattr(self, "_periodic_prefetch_started", False):
            return
        self._periodic_prefetch_started = True
        import threading

        def loop() -> None:
            while True:
                try:
                    # settings_pigeon zip / timezone (retries if the network was down).
                    from pigeon.pigeon_locale import ensure_location_detected

                    ensure_location_detected()
                except Exception:
                    pass
                time.sleep(_BOX_PREFETCH_INTERVAL_S)
                try:
                    self._maybe_refresh_box_scan_cache()
                except Exception:
                    pass

        threading.Thread(target=loop, name="pigeon-lan-prefetch", daemon=True).start()

    def _maybe_refresh_box_scan_cache(self) -> None:
        st = self._state
        if not bool(getattr(st, "wifi_configured", True)):
            return
        if bool(st.box2_devices.scanning or st.box3_devices.scanning):
            return
        if self._box_prefetch_needed(2) or self._box_prefetch_needed(3):
            self._prefetch_boxes_shared()

    def _store_box_scan_result(
        self,
        box_num: int,
        result: tuple[tuple[tuple[str, str], ...], tuple[dict[str, str], ...]],
    ) -> None:
        display, rows = result
        if display or rows:
            self._box_scan_cache[box_num] = (*result, time.monotonic())
        if box_num in self._box_scan_pending and self._box_scan_result.get(box_num) is None:
            self._box_scan_result[box_num] = result

    def _prefetch_boxes_shared(self) -> None:
        if getattr(self, "_box_prefetch_shared_inflight", False):
            return
        if self._box_prefetch_inflight:
            return
        if not (self._box_prefetch_needed(2) or self._box_prefetch_needed(3)):
            return
        import threading

        self._box_prefetch_shared_inflight = True
        self._box_prefetch_inflight.update((2, 3))

        def worker() -> None:
            try:
                from pigeon.widgets.box_device_pairing import scan_devices_for_boxes

                found = scan_devices_for_boxes()
            except Exception:
                found = {2: ((), ()), 3: ((), ())}
            finally:
                self._box_prefetch_shared_inflight = False
                self._box_prefetch_inflight.discard(2)
                self._box_prefetch_inflight.discard(3)
            for box_num, result in found.items():
                self._store_box_scan_result(int(box_num), result)

        threading.Thread(target=worker, name="pigeon-lan-prefetch-scan", daemon=True).start()

    def _prefetch_wifi_into_cache(self) -> None:
        if not self._wifi_prefetch_needed():
            return
        import threading

        self._wifi_prefetch_inflight = True

        def worker() -> None:
            try:
                from pigeon.wifi_scan import scan_wifi_networks

                result = scan_wifi_networks()
            except Exception:
                result = ()
            finally:
                self._wifi_prefetch_inflight = False
            if result:
                self._wifi_scan_cache = (result, time.monotonic())

        threading.Thread(target=worker, name="pigeon-wifi-prefetch", daemon=True).start()

    def _prefetch_box_into_cache(self, box_num: int) -> None:
        del box_num
        self._prefetch_boxes_shared()

    def _start_wifi_scan_async(self) -> None:
        import threading

        def worker() -> None:
            try:
                from pigeon.wifi_scan import scan_wifi_networks

                result = scan_wifi_networks()
            except Exception:
                result = ()
            self._wifi_scan_result = result
            if result:
                self._wifi_scan_cache = (result, time.monotonic())

        self._wifi_scan_result = None
        threading.Thread(target=worker, daemon=True).start()

    def _start_box_device_scan_async(self, box_num: int) -> None:
        import threading

        def worker() -> None:
            try:
                result = scan_lan_devices(box_num)
            except Exception:
                result = (), ()
            self._box_scan_result[box_num] = result
            self._store_box_scan_result(box_num, result)

        self._box_scan_result[box_num] = None
        threading.Thread(target=worker, daemon=True).start()

    def _begin_wifi_scan(self) -> None:
        st = self._state
        cached = self._cached_wifi_scan()
        if cached is not None:
            # Prefetch hit — open the picker immediately (no spinner).
            st.complete_wifi_scan(cached)
            self.invalidate()
            return
        st.show_network_picker = False
        st.wifi_networks = ()
        st.spinner_glyph_capture = True
        try:
            patch = self._build_wifi_search_glyph_patch()
            self._wifi_search_glyph_cache = patch
            self._wifi_search_rotated_cache = (
                _precompute_rotated_patches(patch) if patch is not None else None
            )
        finally:
            st.spinner_glyph_capture = False
        st.start_wifi_scan()
        self._start_wifi_scan_async()
        self.invalidate()

    def _start_box_device_scan(self, box_num: int) -> None:
        st = self._state
        cached = self._cached_box_scan(box_num)
        if cached is not None:
            if box_num == 2:
                st.show_box2_panel = True
            elif box_num == 3:
                st.show_box3_panel = True
            st.start_box_device_scan(box_num, duration_s=_BOX_SCAN_CACHE_HIT_MIN_S)
            self._box_scan_result[box_num] = cached
            self._box_scan_pending.add(box_num)
            self.invalidate()
            return
        if box_num in self._box_prefetch_inflight or self._box_prefetch_shared_inflight:
            if self._cached_main_bgra is not None:
                self._pre_scan_main_bgra[box_num] = self._cached_main_bgra.copy()
            st.start_box_device_scan(box_num)
            self._box_scan_pending.add(box_num)
            self.invalidate()
            return
        # Snapshot the idle UI so abort can restore it without a mid-spin freeze frame.
        if self._cached_main_bgra is not None:
            self._pre_scan_main_bgra[box_num] = self._cached_main_bgra.copy()
        panel = st._box_panel(box_num)
        panel.active = True
        panel.phase = "scanning"
        if box_num == 2:
            st.show_box2_panel = True
        elif box_num == 3:
            st.show_box3_panel = True
        st.spinner_glyph_capture = True
        try:
            patch = self._build_box_search_glyph_patch(box_num)
            self._box_search_glyph_cache[box_num] = patch
            if patch is not None:
                self._box_search_rotated_cache[box_num] = _precompute_rotated_patches(patch)
            else:
                self._box_search_rotated_cache.pop(box_num, None)
        finally:
            st.spinner_glyph_capture = False
        st.start_box_device_scan(box_num)
        self._box_scan_pending.add(box_num)
        self._start_box_device_scan_async(box_num)

    def _abort_box_device_scan_ui(self, box_num: int) -> bool:
        """Dismiss the spinner immediately; restore prior device/idle state."""
        st = self._state
        self._clear_box_search_spinner_cache(box_num)
        if not st.abort_box_device_scan_ui(box_num):
            return False
        self._pre_scan_main_bgra.pop(box_num, None)
        # Force a full re-render from restored state (not a stale mid-scan frame).
        self._cached_kb_bgra = None
        self._cached_kb_sig = None
        self._cached_bgra = None
        self._cached_sig = None
        self._cached_main_bgra = None
        self._cached_main_sig = None
        self.invalidate()
        return True

    def _box_search_center_px(self, box_num: int) -> tuple[int, int]:
        cx, cy = box_search_center_svg(box_num)
        return _svg_to_px(cx, cy)

    def _build_box_search_glyph_patch(self, box_num: int) -> np.ndarray | None:
        if self._svg_path is not None:
            path = Path(self._svg_path)
        else:
            path = default_main_settings_svg_path(self._assets_dir)
        if not path.is_file():
            return None
        root = _svg_tree_from_path(path)
        arc_specs = _discover_box_search_arc_specs(root, box_num)
        triangle_specs = _discover_box_search_triangle_specs(root, box_num)
        if not arc_specs and not triangle_specs:
            return None
        cx_px, cy_px = self._box_search_center_px(box_num)
        r = _WIFI_SEARCH_PATCH_RADIUS_PX
        x0 = max(0, cx_px - r)
        y0 = max(0, cy_px - r)
        patch = np.zeros((2 * r, 2 * r, 4), dtype=np.uint8)
        color = _hex_to_bgr("#202020")
        _draw_onboarding_search_arc_overlays_on_patch(
            patch, arc_specs, origin_x0=x0, origin_y0=y0
        )
        _draw_triangle_specs_on_patch(
            patch, triangle_specs, origin_x0=x0, origin_y0=y0, color_bgr=color
        )
        return _mask_wifi_search_glyph_patch(patch)

    def _ensure_box_search_glyph_cache(self, box_num: int) -> None:
        if box_num in self._box_search_rotated_cache:
            return
        st = self._state
        st.spinner_glyph_capture = True
        try:
            patch = self._build_box_search_glyph_patch(box_num)
        finally:
            st.spinner_glyph_capture = False
        if patch is not None:
            self._box_search_glyph_cache[box_num] = patch
            self._box_search_rotated_cache[box_num] = _precompute_rotated_patches(patch)

    def _draw_box_search_spinner(self, frame: np.ndarray, box_num: int) -> None:
        rotated_frames = self._box_search_rotated_cache.get(box_num)
        if not rotated_frames:
            return
        panel = self._state._box_panel(box_num)
        cx, cy = self._box_search_center_px(box_num)
        patch = _rotated_patch_for_angle(rotated_frames, panel.scan_angle_deg)
        _blit_spinner_patch(frame, patch, cx=cx, cy=cy)

    def _draw_wifi_search_spinner(self, frame: np.ndarray) -> None:
        rotated_frames = self._wifi_search_rotated_cache
        if not rotated_frames:
            return
        cx, cy = self._search_glyph_center_px()
        patch = _rotated_patch_for_angle(rotated_frames, self._state.wifi_scan_angle_deg)
        _blit_spinner_patch(frame, patch, cx=cx, cy=cy)

    def _apply_box_search_overlays(self, frame: np.ndarray) -> None:
        if self._state.manual_device_entry is not None:
            return
        for box_num in (2, 3):
            panel = self._state._box_panel(box_num)
            if not panel.scanning:
                continue
            self._ensure_box_search_glyph_cache(box_num)
            self._draw_box_search_spinner(frame, box_num)

    def _apply_wifi_search_overlay(self, frame: np.ndarray) -> None:
        st = self._state
        if st.wifi_configured:
            return
        if st.wifi_scanning or st.wifi_connecting:
            self._ensure_wifi_search_glyph_cache()
            self._draw_wifi_search_spinner(frame)

    def _activate_location_picker_slot(self, box_num: int) -> str:
        """Select a room card, or open rename if that room is already current.

        Renamed rooms return to settings_main right after the switch; rooms that
        still carry a placeholder name stay in the picker (rename on next press).
        """
        st = self._state
        if st.location_switching:
            return "location_switch:busy"
        if not st.location_slots:
            try:
                st.refresh_location_slots()
            except Exception:
                pass
        slot = st.location_slot(box_num)
        current_lid = ""
        try:
            from pigeon.app_state import read_current_location_id

            current_lid = str(read_current_location_id() or "").strip()
        except Exception:
            current_lid = ""
        if slot is not None and current_lid and str(slot[0]) == current_lid:
            if st.begin_rename_location_slot(box_num):
                st.open_keyboard(
                    "location",
                    assets_dir=self._assets_dir,
                    trigger_button="main_dual_location_button",
                )
                self.invalidate()
                return "keyboard_open:location"
        if st.select_location_slot(box_num):
            if slot is not None and not location_name_is_default(slot[1]):
                # A renamed room is a finished choice: confirm the switch and drop
                # straight back to settings_main with it active (no BACK needed).
                # Rooms still on their placeholder name stay in the picker so
                # activating again can rename them.
                st.exit_location_picker()
            self.invalidate()
            return "location_switch"
        return ""

    def _activate_search_keyboard(self, result: str) -> str | None:
        """Search-target keyboard results; ``None`` falls through to the shared path."""
        from pigeon import manual_search

        st = self._state
        kb = st.keyboard
        if kb is None:
            return None
        if result == "typing":
            manual_search.request_suggestions(str(getattr(kb, "buffer", "") or ""))
            return None
        if result == "cancel":
            manual_search.reset_suggestions()
            return None
        if result.startswith("suggest:"):
            rows = manual_search.suggestions()
            try:
                picked = rows[int(result.split(":", 1)[1])]
            except (ValueError, IndexError):
                return "typing"
            st.commit_search(dict(picked))
            self._clear_keyboard_focus_caches()
            self.invalidate()
            return "manual_search:set"
        if result == "go":
            typed = " ".join(str(getattr(kb, "buffer", "") or "").split())
            if not typed:
                st.keyboard = None
                manual_search.reset_suggestions()
                st.ensure_focus_ring()
                st.focus_main_button("main_search_button")
                self._clear_keyboard_focus_caches()
                self.invalidate()
                return "keyboard_cancel"
            entry: dict = {"title": typed}
            rows = manual_search.suggestions()
            if rows and manual_search.titles_match(rows[0]["title"], typed):
                entry = dict(rows[0])
            st.commit_search(entry)
            self._clear_keyboard_focus_caches()
            self.invalidate()
            return "manual_search:set"
        return None

    def activate(self) -> str:
        """Return an action string for the focused control."""
        st = self._state
        if st.keyboard is not None:
            from pigeon.widgets.settings_keyboard import activate_key

            result = activate_key(st.keyboard, assets_dir=self._assets_dir)
            if str(getattr(st.keyboard, "target", "") or "") == "search":
                search_action = self._activate_search_keyboard(result)
                if search_action is not None:
                    return search_action
            if result == "typing":
                kb = st.keyboard
                if (
                    kb is not None
                    and str(getattr(kb, "target", "") or "") == "network"
                    and st.network_password_error
                ):
                    st.network_password_error = False
                    # Error chrome changed — rebuild chrome under the keyboard.
                    self._cached_kb_chrome_bgra = None
                    self._cached_kb_chrome_sig = None
                chrome_sig = self._keyboard_chrome_sig()
                if (
                    self._cached_kb_chrome_bgra is not None
                    and self._cached_kb_chrome_sig == chrome_sig
                ):
                    frame = self._main_with_text_from_chrome()
                    self._cached_main_bgra = frame
                    self._cached_main_sig = self._main_state_sig()
                    self._cached_bgra = None
                    self._kb_composed_cache.clear()
                    self._paste_fully_opaque = None
                else:
                    self._cached_main_bgra = None
                    self._cached_main_sig = None
                    self._cached_bgra = None
                    self._kb_composed_cache.clear()
            elif result.startswith("mode:"):
                # Keep main chrome; only rebuild keyboard overlays for the new layout.
                self._clear_keyboard_focus_caches()
                self._cached_bgra = None
                self._paste_fully_opaque = None
                self._want_prewarm_after_paint = True
            else:
                self.invalidate()
            if result == "cancel":
                st.close_keyboard(commit=False)
                if st.manual_device_entry is not None:
                    box_num = int(st.manual_device_entry.box_num)
                    st.manual_device_entry = None
                    st.reset_box_device_panel(box_num)
                    self._clear_box_search_spinner_cache(box_num)
                    st.ensure_focus_ring()
                if st.box_pairing is not None:
                    try:
                        from pigeon.apple_tv_now_playing import abandon_pairing_session

                        sk = st.box_pairing.session_key
                        if sk:
                            abandon_pairing_session(sk)
                    except Exception:
                        pass
                    st.clear_box_pairing()
                if st.renaming_location_id or st.show_location_picker:
                    st.renaming_location_id = ""
                    st.renaming_location_slot = 0
                    try:
                        from pigeon.app_state import read_current_location_name

                        st.location_name = read_current_location_name()
                    except Exception:
                        pass
                    if st.show_location_picker:
                        st.ensure_focus_ring()
                self.invalidate()
                return "keyboard_cancel"
            if result == "yes":
                st.close_keyboard(commit=False)
                self.invalidate()
                return "wifi_logout:yes"
            if result == "no":
                st.close_keyboard(commit=False)
                st.ensure_focus_ring()
                btn = "main_dual_network_button"
                if btn in st.focus_ring:
                    st.focus_index = st.focus_ring.index(btn)
                self.invalidate()
                return "wifi_logout:no"
            if result == "go":
                kb = st.keyboard
                pin_buf = ""
                kb_target = str(getattr(kb, "target", "") or "") if kb is not None else ""
                if kb is not None and kb_target == "pin":
                    pin_buf = "".join(c for c in str(getattr(kb, "buffer", "") or "") if c.isdigit())
                    if len(pin_buf) != 4:
                        return "keyboard_pin_incomplete"
                if kb is not None and kb_target == "network":
                    st.pending_network_password = str(getattr(kb, "buffer", "") or "")
                    st.close_keyboard(commit=False)
                    self.invalidate()
                    return "keyboard_go:network"
                if kb is not None and kb_target == "device_ip":
                    entry = st.manual_device_entry
                    if entry is None:
                        st.close_keyboard(commit=False)
                        self.invalidate()
                        return "keyboard_cancel"
                    entry.ip = str(getattr(kb, "buffer", "") or "").strip()
                    entry.step = "name"
                    st.close_keyboard(commit=False)
                    st.ensure_focus_ring()
                    self.invalidate()
                    return "manual_device_ip_done"
                if kb is not None and kb_target == "zipcode":
                    from pigeon.pigeon_locale import set_zipcode_manual

                    set_zipcode_manual(str(getattr(kb, "buffer", "") or ""))
                    st.close_keyboard(commit=False)
                    self.invalidate()
                    return "keyboard_go:zipcode"
                if kb is not None and kb_target == "location":
                    buf = str(getattr(kb, "buffer", "") or "").strip()
                    if not buf:
                        buf = str(getattr(kb, "initial_text", "") or "").strip()
                    st.location_name = location_room_label(
                        buf, slot_index=st.renaming_location_slot or None
                    )
                    st.close_keyboard(commit=False)
                    self.invalidate()
                    return "keyboard_go:location"
                if kb is not None and kb_target == "device_name":
                    entry = st.manual_device_entry
                    if entry is None:
                        st.close_keyboard(commit=False)
                        self.invalidate()
                        return "keyboard_cancel"
                    name = str(getattr(kb, "buffer", "") or "").strip()
                    st.close_keyboard(commit=False)
                    st.finish_manual_device_entry(
                        name=name,
                        ip=str(entry.ip or "").strip(),
                        ip_valid=True,
                    )
                    self.invalidate()
                    return "keyboard_go:device_name"
                target, _buf = st.close_keyboard(commit=True)
                self.invalidate()
                if target == "pin" and pin_buf:
                    return f"keyboard_pin:{pin_buf}"
                return f"keyboard_go:{target or ''}"
            return f"keyboard:{result}"

        if st.show_pigeon_settings:
            if st.show_metadata_debug:
                # EXIT is the only control — land back on the pigeon settings page.
                st.close_metadata_debug()
                self.invalidate()
                return "metadata_debug_exit"
            if st.tz_dropdown_open:
                action = st.activate_tz_dropdown()
                self.invalidate()
                return action
            if st.show_preferences:
                action = st.activate_preferences()
                # Soft invalidate: keep neighbor focus bitmaps; drop current paste only.
                self._cached_bgra = None
                self._cached_sig = None
                self._cached_main_bgra = None
                self._cached_main_sig = None
                self._paste_fully_opaque = None
                self._want_prewarm_after_paint = True
                return action
            if st.show_update_popup:
                if st.update_applying:
                    return "update_popup:busy"
                choice = st.update_popup_focused_choice
                if choice == "back":
                    st.close_update_popup()
                    self.invalidate()
                    return "update_popup:back"
                if choice == "current":
                    # "Stay on this version" — same as cancel.
                    st.close_update_popup()
                    self.invalidate()
                    return "update_popup:stay"
                if st.update_checking:
                    return "update_popup:busy"
                if st.update_available:
                    # Also retries after a failed install.
                    return "update_popup:now"
                # No update known: CHECK queries GitHub again.
                st.begin_update_check()
                self.invalidate()
                return "update_popup:check"
            from pigeon.widgets.pigeon_settings import (
                color_key_for_focus,
                option_for_focus,
                theme_key_for_focus,
                view_for_section,
            )

            focused = st.pigeon_focused_id
            if focused == "exit":
                st.exit_pigeon_settings()
                self.invalidate()
                # EXIT leaves settings for now playing; while WiFi setup still
                # locks settings open it only goes back to settings_main.
                return "exit" if st.exit_enabled else "pigeon_settings_back"
            target_view = view_for_section(st.pigeon_view, focused)
            if target_view is not None:
                st.set_pigeon_view(target_view, focus=focused)
                self.invalidate()
                return f"pigeon_view:{target_view}"
            if focused == "zipcode":
                st.open_keyboard("zipcode", assets_dir=self._assets_dir)
                self.invalidate()
                return "keyboard_open:zipcode"
            if focused == "timezone":
                st.open_tz_dropdown()
                self.invalidate()
                return "timezone_dropdown_open"
            from pigeon.widgets.options_settings import set_option_value

            if theme_key_for_focus(focused) == "dark":
                st.options_values = set_option_value("color_format", "dark", st.options_values or None)
                self.invalidate()
                return "ui_color_dark"
            color = color_key_for_focus(focused)
            if color is not None:
                st.commit_pigeon_color(color)
                st.options_values = set_option_value("color_format", "color", st.options_values or None)
                self.invalidate()
                return f"ui_color_swatch:ui:{color}"
            option = option_for_focus(focused)
            if option is not None:
                from pigeon.widgets.options_settings import toggle_option

                st.options_values = toggle_option(option, st.options_values or None)
                self.invalidate()
                return f"options_toggle:{option}"
            if focused == "update":
                st.open_update_popup()
                self.invalidate()
                return "update_popup:open"
            if focused == "reset":
                self.invalidate()
                return "pigeon_factory_reset"
            if focused == "restart":
                self.invalidate()
                return "pigeon_restart"
            return f"pigeon_activate:{focused}"

        focused = st.focused_id
        action = _ACTIVATE_ACTIONS.get(focused, f"activate:{focused}")
        if action == "exit" and not st.exit_enabled:
            return "exit_locked"
        if action == "exit" and st.show_location_picker:
            st.exit_location_picker()
            try:
                from pigeon.app_state import read_current_location_name

                st.location_name = read_current_location_name()
            except Exception:
                pass
            self.invalidate()
            return "location_picker_exit"
        if action == "focus_location":
            entry = st.manual_device_entry
            if entry is not None and entry.step == "name" and str(entry.ip or "").strip():
                st.open_keyboard("device_name", assets_dir=self._assets_dir)
                self.invalidate()
                return "keyboard_open:device_name"
            if st.show_location_picker:
                st.exit_location_picker()
                try:
                    from pigeon.app_state import read_current_location_name

                    st.location_name = read_current_location_name()
                except Exception:
                    pass
                self.invalidate()
                return "location_picker_exit"
            st.enter_location_picker()
            self.invalidate()
            return "location_picker"
        if action == "focus_network":
            if st.show_location_picker:
                if st.begin_rename_current_location():
                    st.open_keyboard(
                        "location",
                        assets_dir=self._assets_dir,
                        trigger_button="main_dual_location_button",
                    )
                    self.invalidate()
                    return "keyboard_open:location"
                return action
            if not st.wifi_configured:
                self._begin_wifi_scan()
                return "wifi_scan_start"
            st.open_keyboard("wifi_logout", assets_dir=self._assets_dir)
            self.invalidate()
            return "keyboard_open:wifi_logout"
        if action == "focus_search":
            from pigeon import manual_search

            manual_search.reset_suggestions()
            st.open_keyboard("search", assets_dir=self._assets_dir)
            self._clear_keyboard_focus_caches()
            self.invalidate()
            return "keyboard_open:search"
        if action == "clear_search":
            st.clear_search()
            self.invalidate()
            return "manual_search:clear"
        if action == "wifi_search":
            self._begin_wifi_scan()
            return "wifi_scan_start"
        if action == "focus_network_picker":
            rows = st.wifi_networks
            idx = st.network_picker_absolute_row
            ssid = rows[idx] if 0 <= idx < len(rows) else ""
            if ssid:
                st.select_wifi_network(ssid)
                self._wifi_search_glyph_cache = None
                self._wifi_search_rotated_cache = None
                st.open_keyboard(
                    "network",
                    assets_dir=self._assets_dir,
                    trigger_button="main_dual_network_button",
                )
                self.invalidate()
                return f"wifi_selected:{ssid}"
            return action
        if action == "focus_box1":
            if st.show_location_picker:
                picked = self._activate_location_picker_slot(1)
                if picked:
                    return picked
                return action
            st.enter_pigeon_settings()
            self.invalidate()
            return "pigeon_settings"
        if action in ("pick_box2_device", "focus_box2"):
            if st.show_location_picker and action == "focus_box2":
                picked = self._activate_location_picker_slot(2)
                if picked:
                    return picked
                return action
            if st.box2_devices.results_locked or action == "pick_box2_device":
                row = st.pick_box_device(2)
                if row is None:
                    self._clear_box_search_spinner_cache(2)
                if st.manual_device_entry is not None:
                    st.open_keyboard("device_ip", assets_dir=self._assets_dir)
                    self.invalidate()
                    return "keyboard_open:device_ip"
                if row:
                    st.start_box_pairing(2, row)
                    self.invalidate()
                    return "box2_pair_start"
                self.invalidate()
                return action
            if st.box2_devices.scanning:
                self._abort_box_device_scan_ui(2)
                return "box2_scan_abort"
            if st.box2_devices.phase != "scanning":
                self._start_box_device_scan(2)
                self.invalidate()
                return "box2_scan_start"
            return action
        if action in ("pick_box3_device", "focus_box3"):
            if st.show_location_picker and action == "focus_box3":
                picked = self._activate_location_picker_slot(3)
                if picked:
                    return picked
                return action
            if st.box3_devices.results_locked or action == "pick_box3_device":
                row = st.pick_box_device(3)
                if row is None:
                    self._clear_box_search_spinner_cache(3)
                if st.manual_device_entry is not None:
                    st.open_keyboard("device_ip", assets_dir=self._assets_dir)
                    self.invalidate()
                    return "keyboard_open:device_ip"
                if row:
                    st.start_box_pairing(3, row)
                    self.invalidate()
                    return "box3_pair_start"
                self.invalidate()
                return action
            if st.box3_devices.scanning:
                self._abort_box_device_scan_ui(3)
                return "box3_scan_abort"
            if st.box3_devices.phase != "scanning":
                self._start_box_device_scan(3)
                self.invalidate()
                return "box3_scan_start"
            return action
        return action

    def _pigeon_page_overlays(self, base: np.ndarray) -> np.ndarray:
        """settings_pigeon live layers over the cached page: clock + zip keypad."""
        from pigeon.widgets.pigeon_settings import draw_companion_code, draw_pigeon_settings_clock

        st = self._state
        kb_sig = self._keyboard_overlay_sig()
        key = (int(time.time()), kb_sig, bool(st.show_update_popup))
        hit = self._pigeon_overlay_cache
        if hit is not None and hit[0] == key and hit[1] is base:
            return hit[2]
        frame = base
        if st.show_update_popup:
            from pigeon.widgets.update_popup import draw_update_status_bar_bgra

            frame = draw_update_status_bar_bgra(frame, st)
        else:
            frame = draw_pigeon_settings_clock(frame)
            frame = draw_companion_code(frame)
        if st.keyboard is not None and kb_sig is not None:
            from pigeon.widgets.settings_keyboard import render_keyboard_bgra

            kb_frame = self._kb_focus_frame_cache.get(kb_sig)
            if kb_frame is None:
                kb_frame = render_keyboard_bgra(st.keyboard, assets_dir=self._assets_dir)
                self._store_kb_frame(kb_sig, kb_frame)
            frame = self._compose_keyboard_over_main(frame, kb_frame, kb_sig)
        self._pigeon_overlay_cache = (key, base, frame)
        return frame

    def bgra_frame(self) -> np.ndarray | None:
        try:
            from pigeon.compositing import clear_bright_artwork_mask

            clear_bright_artwork_mask()
        except Exception:
            pass
        try:
            st = self._state
            if st.show_pigeon_settings:
                main_sig = self._main_state_sig()
                structure = self._structure_sig()
                focus_key = self._focus_cache_key()
                if structure != self._focus_cache_structure:
                    self._focus_frame_cache.clear()
                    self._focus_cache_structure = structure
                if st.show_metadata_debug:
                    # Live debug page — render every frame signature change; the
                    # sig carries a 1s token so values stay fresh.
                    from pigeon.widgets.metadata_debug import (
                        render_metadata_debug_bgra,
                    )

                    if (
                        self._cached_main_bgra is not None
                        and self._cached_main_sig == main_sig
                    ):
                        frame = self._cached_main_bgra
                    else:
                        frame = render_metadata_debug_bgra(
                            st,
                            assets_dir=self._assets_dir,
                        )
                        self._cached_main_bgra = frame
                        self._cached_main_sig = main_sig
                elif st.show_preferences:
                    # Prefs keeps a structure cache + live overlays; always go through
                    # render so HH:MM / NP progress stay fresh without per-second SVG.
                    from pigeon.widgets.preferences_settings import (
                        render_preferences_settings_bgra,
                    )

                    frame = render_preferences_settings_bgra(
                        st,
                        assets_dir=self._assets_dir,
                    )
                    self._cached_main_bgra = frame
                    self._cached_main_sig = main_sig
                    self._store_focus_frame(frame)
                elif not st.keyboard_open and focus_key in self._focus_frame_cache:
                    frame = self._focus_frame_cache[focus_key]
                    self._cached_main_bgra = frame
                    self._cached_main_sig = main_sig
                elif self._cached_main_bgra is not None and self._cached_main_sig == main_sig:
                    frame = self._cached_main_bgra
                else:
                    from pigeon.widgets.pigeon_settings import render_pigeon_settings_bgra

                    frame = render_pigeon_settings_bgra(
                        st,
                        assets_dir=self._assets_dir,
                    )
                    if st.show_update_popup:
                        from pigeon.widgets.update_popup import (
                            composite_update_popup_over_bgra,
                        )

                        frame = composite_update_popup_over_bgra(
                            frame,
                            st,
                            assets_dir=self._assets_dir,
                        )
                    self._cached_main_bgra = frame
                    self._cached_main_sig = main_sig
                    if not st.keyboard_open:
                        self._store_focus_frame(frame)
                if not st.show_metadata_debug and not st.show_preferences:
                    frame = self._pigeon_page_overlays(frame)
                self._cached_bgra = frame
                if self._want_prewarm_after_paint:
                    self._want_prewarm_after_paint = False
                    if st.keyboard is not None:
                        self.prewarm_keyboard_focus()
                    else:
                        self.prewarm_focus_ring()
                return frame

            main_sig = self._main_state_sig()
            structure = self._structure_sig()
            focus_key = self._focus_cache_key()
            if structure != self._focus_cache_structure:
                self._focus_frame_cache.clear()
                self._focus_cache_structure = structure
            if (
                not self._status_bar_animating()
                and focus_key in self._focus_frame_cache
            ):
                frame = self._focus_frame_cache[focus_key]
                self._cached_main_bgra = frame
                self._cached_main_sig = main_sig
            elif (
                not self._status_bar_animating()
                and self._cached_main_bgra is not None
                and self._cached_main_sig == main_sig
            ):
                frame = self._cached_main_bgra
            elif st.keyboard is not None:
                kb = st.keyboard
                if str(getattr(kb, "target", "") or "") == "wifi_logout":
                    # Native YES/NO lives on the main frame — do not reuse chrome
                    # that ignores keyboard focus, or left/right look dead.
                    frame = render_main_settings_bgra(
                        self._state,
                        svg_path=self._svg_path,
                        assets_dir=self._assets_dir,
                    )
                else:
                    chrome_sig = self._keyboard_chrome_sig()
                    if (
                        self._cached_kb_chrome_bgra is not None
                        and self._cached_kb_chrome_sig == chrome_sig
                    ):
                        frame = self._main_with_text_from_chrome()
                    else:
                        chrome = render_main_settings_bgra(
                            self._state,
                            svg_path=self._svg_path,
                            assets_dir=self._assets_dir,
                            skip_text_entry=True,
                        )
                        self._cached_kb_chrome_bgra = chrome
                        self._cached_kb_chrome_sig = chrome_sig
                        frame = self._main_with_text_from_chrome()
                self._cached_main_bgra = frame
                self._cached_main_sig = main_sig
            else:
                frame = render_main_settings_bgra(
                    self._state,
                    svg_path=self._svg_path,
                    assets_dir=self._assets_dir,
                )
                self._cached_main_bgra = frame
                self._cached_main_sig = main_sig
                self._store_focus_frame(frame)

            # Native 1280 compositor draws the scan status bar; skip legacy spinners.

            if self._state.keyboard is not None:
                from pigeon.widgets.settings_keyboard import KeyboardMode, render_keyboard_bgra

                kb = self._state.keyboard
                skip_yes_no_overlay = (
                    getattr(kb, "mode", None) == KeyboardMode.YES_NO
                    and str(getattr(kb, "target", "") or "") == "wifi_logout"
                )
                mode = getattr(kb, "mode", None)
                if not skip_yes_no_overlay:
                    if self._kb_cache_mode is None:
                        self._kb_cache_mode = mode
                    elif self._kb_cache_mode != mode:
                        self._clear_keyboard_focus_caches()
                        self._kb_cache_mode = mode
                    kb_sig = self._keyboard_overlay_sig()
                    compose_key = (main_sig, kb_sig)
                    if compose_key in self._kb_composed_cache:
                        frame = self._kb_composed_cache[compose_key]
                        self._cached_kb_bgra = self._kb_focus_frame_cache.get(kb_sig)  # type: ignore[arg-type]
                        self._cached_kb_sig = kb_sig
                    else:
                        if (
                            kb_sig is not None
                            and self._cached_kb_bgra is not None
                            and self._cached_kb_sig == kb_sig
                        ):
                            kb_frame = self._cached_kb_bgra
                        elif kb_sig is not None and kb_sig in self._kb_focus_frame_cache:
                            kb_frame = self._kb_focus_frame_cache[kb_sig]
                            self._cached_kb_bgra = kb_frame
                            self._cached_kb_sig = kb_sig
                        else:
                            kb_frame = render_keyboard_bgra(
                                self._state.keyboard,
                                assets_dir=self._assets_dir,
                            )
                            self._cached_kb_bgra = kb_frame
                            self._cached_kb_sig = kb_sig
                            if kb_sig is not None:
                                self._store_kb_frame(kb_sig, kb_frame)
                        frame = self._compose_keyboard_over_main(frame, kb_frame, kb_sig)
                        if kb_sig is not None:
                            self._store_kb_composed(compose_key, frame)
        except Exception:
            self.invalidate()
            raise
        self._cached_bgra = frame
        if self._want_prewarm_after_paint and not st.show_pigeon_settings:
            self._want_prewarm_after_paint = False
            if st.keyboard is not None:
                self.prewarm_keyboard_focus()
            else:
                self.prewarm_focus_ring()
        elif st.keyboard is not None and not self._kb_prewarm_inflight:
            self.prewarm_keyboard_focus()
        return frame

    def render(self, canvas_bgr: np.ndarray) -> None:
        """Paste main settings onto the design canvas (800×480, uniform scale only)."""
        self.tick()
        frame = self.bgra_frame()
        if frame is None or canvas_bgr is None or canvas_bgr.size == 0:
            return
        kb_open = self._state.keyboard is not None
        search_kb = kb_open and (
            str(getattr(self._state.keyboard, "target", "") or "") == "search"
        )
        if kb_open and (search_kb or not self._nav_scrub):
            frame = frame.copy()
            if not self._nav_scrub:
                _draw_text_entry_cursor(frame, self._state)
            if search_kb:
                # Painted even while nav-scrubbing: the cached frame underneath
                # still shows the dual bar, which flashed white on every step.
                from pigeon.widgets.settings_main_1280 import draw_search_overlay

                draw_search_overlay(
                    frame,
                    self._state,
                    caret_on=not self._nav_scrub and not int(time.monotonic() * 2) % 2,
                )
            self._paste_fully_opaque = None
        ch, cw = int(canvas_bgr.shape[0]), int(canvas_bgr.shape[1])
        fh, fw = int(frame.shape[0]), int(frame.shape[1])
        if fh == ch and fw == cw:
            alpha_u8 = frame[:, :, 3]
            # Settings is usually fully opaque over black — avoid full-frame float blend.
            opaque = self._paste_fully_opaque
            if opaque is None:
                opaque = int(alpha_u8.min()) == 255
                self._paste_fully_opaque = opaque
            if opaque:
                canvas_bgr[:] = frame[:, :, :3]
            else:
                canvas_bgr[:] = alpha_blend_bgra_over_bgr(canvas_bgr, frame)
            return
        scale = min(cw / float(fw), ch / float(fh))
        tw = max(1, int(round(fw * scale)))
        th = max(1, int(round(fh * scale)))
        resized = cv2.resize(frame, (tw, th), interpolation=cv2.INTER_AREA)
        x0 = max(0, (cw - tw) // 2)
        y0 = max(0, (ch - th) // 2)
        roi = canvas_bgr[y0 : y0 + th, x0 : x0 + tw]
        alpha_u8 = resized[:, :, 3]
        if int(alpha_u8.min()) == 255:
            roi[:] = resized[:, :, :3]
        else:
            roi[:] = alpha_blend_bgra_over_bgr(roi, resized)

    # Alias used by ``pigeon_0_12`` composite paths.
    render_on_bgr = render


__all__ = [
    "COLOR_ACCENT_DEFAULT",
    "COLOR_DESELECTED",
    "COLOR_INACTIVE",
    "COLOR_SELECTED",
    "COLOR_UI_DEFAULT",
    "DESIGN_H",
    "DESIGN_W",
    "KEYBOARD_NUMERIC_IP_SVG",
    "KEYBOARD_SVG_NAMES",
    "MainSettingsFocus",
    "MainSettingsState",
    "MainSettingsWidget",
    "SettingsTheme",
    "apply_main_settings_svg_state",
    "decode_svg_id",
    "default_main_settings_svg_path",
    "encode_svg_id",
    "keyboard_svg_path",
    "render_main_settings_bgra",
]
