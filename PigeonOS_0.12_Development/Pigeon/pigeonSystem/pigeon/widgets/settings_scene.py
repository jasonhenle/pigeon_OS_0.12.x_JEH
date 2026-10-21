"""
Apply ``MainSettingsState`` to the main settings SVG tree.

Per-state layer visibility, focus ring discovery, labels, fills and contrast for the
main menu, wifi onboarding, box device columns, location slots, network picker and
keyboard overlay. Mutates the ``ElementTree`` only; rasterizing, caching and input
handling stay in ``main_settings``.

``pigeon.widgets.main_settings`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image, ImageDraw

from pigeon.design import DESIGN_W
from pigeon.widgets.box_device_search import (
    BOX_DEVICE_ROW_CANCEL,
    BOX_DEVICE_ROW_ENTER_IP,
    BoxDevicePanelState,
    _BOX_DEVICE_ROW_COUNT,
)
from pigeon.widgets.settings_box_text_layout import (
    _BOX_DEVICE_GROUPS,
    _BOX_RESULT_ROW_Y_SVG,
    _apply_box_device_group_layout,
    _apply_box_result_row_text_layout,
    _box_column_inner_svg,
    _find_box_device_group,
    _is_device_label_logical,
    _set_svg_text_centered,
    _set_svg_text_font_size_px,
    _set_svg_text_horiz_centered,
    _truncate_text_to_width,
)
from pigeon.widgets.settings_container_background import _BACKGROUND_CONTAINERS
from pigeon.widgets.settings_paint import (
    _apply_accent_paint,
    _apply_button_fill,
    _apply_contrast_paint,
    _apply_direct_glyph_contrast,
    _apply_ui_brand_paint,
)
from pigeon.widgets.settings_search_overlays import (
    _MATRIX_RE,
    _OnboardingSearchArcSpec,
    _WIFI_SEARCH_CENTER_SVG,
    _draw_onboarding_search_arc_overlays,
    _draw_onboarding_search_triangle_overlays,
    _find_box_column_search_icon,
    _find_box_root_group,
    _hide_box_search_animation_layers,
    _hide_box_search_icon_vectors,
    _needs_wifi_setup,
    _parse_matrix_translate,
    _wifi_onboarding_add_search_group,
    _wifi_onboarding_search_group,
)
from pigeon.widgets.settings_state import (
    COLOR_DESELECTED,
    COLOR_UI_DEFAULT,
    MainSettingsState,
    SettingsTheme,
    _LOCATION_SLOT_DEFAULT_NAMES,
    _PICKER_ROW_MINI_BUTTONS,
    _PICKER_ROW_TEXTS,
    _PRIMARY_FOCUS_CANDIDATES,
    location_room_label,
)
from pigeon.widgets.settings_svg_tree import (
    _find_all_by_logical_id,
    _find_by_logical_id,
    _is_descendant_of,
    _iter_style_fill_stroke,
    _logical_id_index,
    _normalize_logical,
    _parent_map,
    _remove_by_logical_id,
    _set_paint,
    _set_text_content,
    _set_visible,
)
from pigeon.widgets.settings_text_entry import (
    _COLOR_GRAY_RGBA,
    _DUAL_NETWORK_TEXT_X0_SVG,
    _DUAL_NETWORK_TEXT_X1_SVG,
    _TEXT_ENTRY_FIELDS,
    _draw_centered_field_text,
    _field_font,
    _field_font_size_px,
    _fit_text_font_size,
)


_BOX_LOCATION_TEXT_Y_SVG: dict[int, float] = {1: 325.6104, 2: 325.704, 3: 325.6104}


_BOX_LOCATION_TEXT_FONT_SVG = 48.0


COLOR_VERSION_TEXT = "#000000"


_KEYBOARD_HIDE_WHEN_OPEN: tuple[str, ...] = (
    "main_exit_group",
    "main_box1",
    "main_box2",
    "main_box3",
    "main_box1_device_group",
    "main_box2_device_group",
    "main_box3_device_group",
    "main_box1_location_group",
    "main_box2_location_group",
    "main_box3_location_group",
    "main_box1_container",
    "main_box2_container",
    "main_box3_container",
    "main_box1_search_icon",
    "main_box2_search_icon",
    "main_box3_search_icon",
)


# Accent outlines hidden on settings_main tiles (exit / back accents stay).
_HIDDEN_MAIN_ACCENT_IDS = frozenset(
    {
        "main_dual_accent",
        "main_03.02_dual_button_accent",
        "main_box1_accent",
        "main_box2_accent",
        "main_box3_accent",
    }
)


_DUAL_LOCATION_TEXT_X0_SVG = 82.0


_DUAL_LOCATION_TEXT_X1_SVG = 395.0


_DUAL_LOCATION_ICON_RADIUS_SVG = 6.921


_DUAL_LOCATION_TEXT_ICON_GAP_SVG = 10.0


_DUAL_LOCATION_ICON_IDS: tuple[str, ...] = (
    "main_dual_locaion1_icon",
    "main_dual_locaion2_icon",
    "main_dual_locaion3_icon",
)


_PICKER_TEXT_CENTER_X_SVG = 400.0


# Button → associated contrast layers (logical ids; AI suffixes tolerated).
_FOCUS_ASSOCIATED: dict[str, tuple[str, ...]] = {
    "main_dual_location_button": (
        "main_dual_location_text",
        "main_dual_locaion1_icon",
        "main_dual_locaion2_icon",
        "main_dual_locaion3_icon",
    ),
    "main_dual_network_button": (
        "main_dual_network_name_text",
    ),
    "main_box1_button": (),
    "main_box2_button": (),
    "main_box3_button": (),
    "main_exit_button": (
        "main_exit_text",
        "main_exit_icon",
    ),
    "main_network_picker_button": (),
    "main_box2_add_search_icon": ("main_box2_+_icon",),
}


_PICKER_ROW_LOCK_GROUPS: tuple[str, ...] = (
    "main_network_picker_row1_lock_info",
    "main_network_picker_row22_lock_info",
    "main_network_picker_lock3_icon",
)


_HIDE_ALWAYS_LOGICAL: tuple[str, ...] = (
    "keyboardtemp",
)


_BOX_LOCATION_GROUPS: tuple[str, ...] = (
    "main_box1_location_group",
    "main_box2_location_group",
    "main_box3_location_group",
)


# Box panel chrome (container, search, results) hidden until a box is opened.
_BOX_CHROME_PREFIXES: tuple[str, ...] = (
    "main_box1_container",
    "main_box1_search_results",
    "main_box1_search_icon",
    "main_box2_container",
    "main_box2_search_results",
    "main_box2_search_icon",
    "main_box3_container",
    "main_box3_search_results",
    "main_box3_search_icon",
)


_BOX_CHROME_NUM_RE = re.compile(r"^main_box([123])_")


# Rounded column chrome (button + accent) — always visible at launch.
_BOX_CONTAINER_LOGICALS: frozenset[str] = frozenset(
    {
        "main_box1_container",
        "main_box2_container",
        "main_box3_container",
    }
)


def _is_onboarding_search_group(
    root: ET.Element,
    search_group: ET.Element,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    add_group = _wifi_onboarding_add_search_group(root)
    return add_group is not None and _is_descendant_of(search_group, add_group, parents)


def _set_box_columns_visible(root: ET.Element, visible: bool) -> None:
    """Show/hide the three main box column groups (``main_box1`` … ``main_box3``)."""
    for i in (1, 2, 3):
        _set_visible(_find_box_root_group(root, i), visible)


def _apply_wifi_onboarding_search_layers(root: ET.Element, state: MainSettingsState) -> None:
    """
    WiFi discovery chrome under ``main_instructions``.

    Idle onboarding: ``main_box2_search_icon`` + ``main_box2_+_icon``.
    Scanning: only the search glyph (triangles + ellipse strokes via overlay spin).
    """
    plus_group = _find_by_logical_id(root, "main_box2_+_icon")
    search_group = _wifi_onboarding_search_group(root)
    welcome_el = _find_by_logical_id(root, "welcome_to_pigeon_find_your_wifi_text")
    _set_visible(welcome_el, False)
    scanning = bool(state.wifi_scanning or state.wifi_connecting)
    capture = bool(getattr(state, "spinner_glyph_capture", False))
    if scanning or capture:
        _set_visible(plus_group, False)
        if search_group is not None:
            _set_visible(search_group, True)
        return
    _set_visible(plus_group, True)
    if search_group is not None:
        _set_visible(search_group, True)


def _hide_wifi_onboarding_search_svg_glyphs(root: ET.Element) -> None:
    """Hide leftover clip-path circles. Stroke arcs + filled triangles stay in the SVG."""
    search_group = _wifi_onboarding_search_group(root)
    if search_group is None:
        return
    for el in search_group.iter():
        if el.tag.endswith("circle"):
            _set_visible(el, False)


def _hide_wifi_onboarding_search_svg_circles(root: ET.Element) -> None:
    """Backward-compatible alias."""
    _hide_wifi_onboarding_search_svg_glyphs(root)


def _center_wifi_plus_icon(root: ET.Element) -> None:
    """Anchor ``main_box2_+_icon`` on the search ring center."""
    plus_group = _find_by_logical_id(root, "main_box2_+_icon")
    if plus_group is None:
        return
    cx, cy = _WIFI_SEARCH_CENTER_SVG
    for el in plus_group.iter():
        if el.tag.endswith("text"):
            _set_svg_text_centered(el, cx, cy)


def _draw_wifi_onboarding_search_overlays(
    bgra: np.ndarray,
    state: MainSettingsState,
    arc_specs: tuple[_OnboardingSearchArcSpec, ...],
    triangle_specs: tuple[tuple[tuple[float, float], ...], ...] = (),
) -> None:
    if not _needs_wifi_setup(state) or state.show_network_picker:
        return
    if not (state.wifi_scanning or state.wifi_connecting):
        return
    if (state.wifi_scanning or state.wifi_connecting) and not bool(
        getattr(state, "spinner_glyph_capture", False)
    ):
        return
    _draw_onboarding_search_arc_overlays(bgra, arc_specs)
    _draw_onboarding_search_triangle_overlays(bgra, triangle_specs)


def _dual_location_text_bounds_svg(root: ET.Element | None = None) -> tuple[float, float]:
    """Text span for the location field: right of nest icons, left of the ``|`` divider."""
    x1 = _DUAL_LOCATION_TEXT_X1_SVG
    icon_right = _DUAL_LOCATION_TEXT_X0_SVG
    if root is not None:
        for lid in _DUAL_LOCATION_ICON_IDS:
            el = _find_by_logical_id(root, lid)
            if el is None or not el.tag.endswith("circle"):
                continue
            try:
                cx = float(el.get("cx") or 0.0)
                r = float(el.get("r") or _DUAL_LOCATION_ICON_RADIUS_SVG)
            except (TypeError, ValueError):
                continue
            icon_right = max(icon_right, cx + r)
    else:
        icon_right = 128.26 + _DUAL_LOCATION_ICON_RADIUS_SVG
    return icon_right + _DUAL_LOCATION_TEXT_ICON_GAP_SVG, x1


def _hide_add_search_glyphs(root: ET.Element) -> None:
    """Hide plus/arrow search art so it cannot bleed through PIN / overlay screens."""
    for lid in (
        "main_box1_search_icon",
        "main_box2_search_icon",
        "main_box3_search_icon",
        "main_box2_add_search_icon",
        "main_box2_+_icon",
        "welcome_to_pigeon_group",
    ):
        _set_visible(_find_by_logical_id(root, lid), False)
    search_group = _wifi_onboarding_search_group(root)
    if search_group is not None:
        _set_visible(search_group, False)
    for box_num in (1, 2, 3):
        _hide_box_search_animation_layers(root, box_num)


def _apply_keyboard_layer_visibility(root: ET.Element, state: MainSettingsState) -> None:
    """While the keyboard is open, hide chrome under the overlay."""
    if not state.keyboard_open and not state.wifi_connecting:
        return
    kb_target = ""
    if state.keyboard is not None:
        kb_target = str(getattr(state.keyboard, "target", "") or "")
    pairing_pin = kb_target == "pin" and state.box_pairing is not None
    wifi_logout = kb_target == "wifi_logout"
    manual_entry = state.manual_device_entry is not None
    device_entry = kb_target in ("device_ip", "device_name") or manual_entry
    password_flow = kb_target == "network" or state.wifi_connecting
    if wifi_logout:
        for lid in (
            "main_exit_group",
            "main_network_picker",
            "welcome_to_pigeon_find_your_wifi_text",
            "welcome_to_pigeon_group",
            "main_box1_text",
            "main_box1_device_group",
            "main_box2_device_group",
            "main_box3_device_group",
            "main_box1_container",
            "main_box2_container",
            "main_box3_container",
            "main_box2_add_search_icon",
            "main_box2_+_icon",
        ):
            _set_visible(_find_by_logical_id(root, lid), False)
        _hide_add_search_glyphs(root)
        for lid in _DUAL_LOCATION_ICON_IDS:
            _set_visible(_find_by_logical_id(root, lid), False)
        _set_visible(_find_by_logical_id(root, "main_dual_network_wifi_group"), False)
        _set_visible(_find_by_logical_id(root, "main_instructions"), True)
        nest_el = _find_by_logical_id(root, "rename_your_nest_text")
        if nest_el is not None:
            _set_text_content(nest_el, _wifi_logout_instruction_text(state))
            _force_layer_white(nest_el)
            _set_visible(nest_el, True)
        return
    if pairing_pin or device_entry:
        for lid in (
            "main_exit_group",
            "main_instructions",
            "main_network_picker",
            "welcome_to_pigeon_find_your_wifi_text",
            "main_box1_text",
            "main_box1_device_group",
            "main_box2_device_group",
            "main_box3_device_group",
            "main_box1",
            "main_box2",
            "main_box3",
            "main_box1_container",
            "main_box2_container",
            "main_box3_container",
            "main_box2_add_search_icon",
        ):
            _set_visible(_find_by_logical_id(root, lid), False)
        _hide_add_search_glyphs(root)
        for lid in _DUAL_LOCATION_ICON_IDS:
            _set_visible(_find_by_logical_id(root, lid), False)
        _set_visible(_find_by_logical_id(root, "main_dual_network_wifi_group"), False)
        if pairing_pin:
            _set_visible(_find_by_logical_id(root, "main_instructions"), True)
            _set_visible(_find_by_logical_id(root, "welcome_to_pigeon_group"), False)
            nest_el = _find_by_logical_id(root, "rename_your_nest_text")
            if nest_el is not None:
                _set_text_content(nest_el, _pairing_instruction_text(state))
                _force_layer_white(nest_el)
                _set_visible(nest_el, True)
        return
    if password_flow:
        for lid in (
            "main_exit_group",
            "main_instructions",
            "main_network_picker",
            "rename_your_nest_text",
            "welcome_to_pigeon_find_your_wifi_text",
            "main_box1",
            "main_box2",
            "main_box3",
            "main_box2_add_search_icon",
            "main_box1_text",
        ):
            _set_visible(_find_by_logical_id(root, lid), False)
        if state.keyboard_open and kb_target == "network":
            for lid in _DUAL_LOCATION_ICON_IDS:
                _set_visible(_find_by_logical_id(root, lid), False)
        return
    # Location rename / default keyboard: suppress every box column layer under the overlay.
    for lid in _KEYBOARD_HIDE_WHEN_OPEN:
        _set_visible(_find_by_logical_id(root, lid), False)
    _set_box_columns_visible(root, False)
    for box_num in (1, 2, 3):
        _set_visible(_find_by_logical_id(root, _BOX_LOCATION_GROUPS[box_num - 1]), False)
        _set_visible(_find_by_logical_id(root, _BOX_DEVICE_GROUPS[box_num]), False)
        _set_visible(_find_by_logical_id(root, f"main_box{box_num}_container"), False)
        _set_visible(_find_by_logical_id(root, f"main_box{box_num}_search_icon"), False)
        _set_box_search_results_visible(root, box_num, False)
        _hide_box_search_animation_layers(root, box_num)


def _wifi_logout_instruction_text(state: MainSettingsState) -> str:
    ssid = state.displayed_wifi_ssid() or str(state.selected_wifi_ssid or "").strip() or "network"
    return f"disconnect {ssid}"


def _pairing_instruction_text(state: MainSettingsState) -> str:
    sess = state.box_pairing
    if sess is None:
        return "PAIR COMPANION (1 of 2)"
    if sess.step == "airplay_pin":
        return "PAIR AIRPLAY (2 of 2)"
    return "PAIR COMPANION (1 of 2)"


def _layer_class(logical_id: str) -> str | None:
    for cls in ("_text", "_icon", "_button", "_accent", "_group", "_container"):
        if logical_id.endswith(cls) or f"{cls}_" in logical_id:
            # Prefer the terminal class token.
            if logical_id.endswith(cls):
                return cls
    for cls in ("_text", "_icon", "_button", "_accent", "_group", "_container"):
        if logical_id.endswith(cls):
            return cls
    return None


def _active_background_container(state: MainSettingsState, focused: str) -> str:
    """Which diagonal-stripe ``containerN`` group matches the focused box button."""
    if state.show_network_picker or _needs_wifi_setup(state):
        return "container1"
    if focused == "main_box3_button":
        return "container3"
    if focused == "main_box2_button":
        return "container2"
    if focused == "main_box1_button":
        return "container1"
    return "container1"


def _apply_background_container(
    root: ET.Element,
    state: MainSettingsState,
    *,
    focused: str,
) -> None:
    """Legacy no-op: stripe backgrounds come from ``settings_background.svg`` now."""
    del state, focused
    for cid in _BACKGROUND_CONTAINERS:
        _set_visible(_find_by_logical_id(root, cid), False)


def _is_box_chrome_logical(logical: str) -> bool:
    if logical in _BOX_CONTAINER_LOGICALS:
        return True
    return any(
        logical == prefix or logical.startswith(f"{prefix}_")
        for prefix in _BOX_CHROME_PREFIXES
    )


def _apply_box1_host_device_labels(root: ET.Element) -> None:
    """Show this Pigeon host name + LAN IP in box1 device chrome."""
    from pigeon.local_ip import local_ipv4_address

    ip = local_ipv4_address() or ""
    _apply_box_device_group_layout(root, 1, name="pigeon", ip=ip)


def _apply_box_device_group_labels(
    root: ET.Element,
    state: MainSettingsState,
    box_num: int,
) -> None:
    """Populate box2/box3 device_group name + IP after the user picks a LAN device."""
    if box_num not in (2, 3):
        return
    panel = state._box_panel(box_num)
    picked = state.saved_box_device(box_num)
    if picked is None:
        return
    if panel.picked is None:
        panel.picked = picked
    name, ip = picked
    ip_invalid = state.box2_ip_invalid if box_num == 2 else state.box3_ip_invalid
    _apply_box_device_group_layout(root, box_num, name=name, ip=ip)
    group = _find_box_device_group(root, box_num)
    if group is None:
        return
    _apply_box_pigeon_logo_icon_styles(root, box_num, theme=state.theme)
    if ip_invalid:
        for el in group.iter():
            logical = _normalize_logical(el.get("id") or "")
            if logical.endswith("_device_ip_text"):
                for node in el.iter():
                    if node.tag.endswith("text"):
                        _set_paint(node, fill=COLOR_UI_DEFAULT)


def _apply_box_pigeon_logo_icon_styles(
    root: ET.Element,
    box_num: int,
    *,
    theme: SettingsTheme,
) -> None:
    """Paint hex-clip ring strokes / speaker polygons with ``theme.ui``."""
    icon = _find_by_logical_id(root, f"main_box{box_num}_pigeon_logo_icon")
    if icon is None:
        return
    ui = theme.ui or COLOR_UI_DEFAULT
    edge = theme.deselected or COLOR_DESELECTED
    for el in icon.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "circle":
            _set_paint(el, fill="none", stroke=ui)
        elif tag == "line":
            _set_paint(el, fill="none", stroke=ui)
        elif tag == "polygon":
            _set_paint(el, fill=ui, stroke=edge)


def _apply_box_device_text_contrast(
    root: ET.Element,
    *,
    box_num: int,
    selected: bool,
    theme: SettingsTheme,
) -> None:
    """Selected box pill is white → black text; deselected dark → white text."""
    contrast = theme.deselected if selected else theme.selected
    group = _find_box_device_group(root, box_num)
    if group is None:
        return
    for el in group.iter():
        logical = _normalize_logical(el.get("id") or "")
        if not _is_device_label_logical(logical):
            continue
        for node in el.iter():
            if node.tag.endswith("text"):
                _set_paint(node, fill=contrast)


def _box_shows_location_group(
    state: MainSettingsState,
    box_num: int,
    panel: BoxDevicePanelState,
) -> bool:
    if box_num not in (2, 3):
        return False
    if panel.results_locked or (panel.active and panel.phase == "scanning"):
        return False
    if _needs_wifi_setup(state) or state.manual_device_entry is not None:
        return False
    if state.box_has_saved_device(box_num) and not panel.active:
        return False
    if box_num == 2:
        panel_open = bool(state.show_box2_panel or state.box2_devices.active)
    else:
        panel_open = bool(state.show_box3_panel or state.box3_devices.active)
    if panel.active:
        return False
    return panel_open


def _box_location_text_bounds_svg(box_num: int) -> tuple[float, float]:
    return _box_column_inner_svg(box_num)


def _box_location_label_for_slot(state: MainSettingsState, box_num: int) -> str:
    """Label shown inside a box location group (picker slots or current nest)."""
    default = _LOCATION_SLOT_DEFAULT_NAMES[max(0, min(2, int(box_num) - 1))]
    if state.show_location_picker:
        slot = state.location_slot(box_num)
        if slot is not None:
            return location_room_label(str(slot[1] or "").strip() or default, slot_index=box_num)
        return default
    return location_room_label(
        str(state.location_name or default).strip() or default, slot_index=box_num
    )


def _apply_box_location_group_labels(
    root: ET.Element,
    state: MainSettingsState,
    box_num: int,
) -> None:
    """Center and truncate nest/location label inside box1–3 column chrome."""
    if box_num not in (1, 2, 3):
        return
    group = _find_by_logical_id(root, f"main_box{box_num}_location_group")
    if group is None:
        return
    label = _box_location_label_for_slot(state, box_num)
    x0, x1 = _box_location_text_bounds_svg(box_num)
    center_svg = (x0 + x1) * 0.5
    y_svg = _BOX_LOCATION_TEXT_Y_SVG.get(box_num, 325.7)
    max_w = max(24, int(round((x1 - x0 - 8.0) * DESIGN_W / 800.0)))
    font_size_px = _field_font_size_px(_BOX_LOCATION_TEXT_FONT_SVG)
    font = _field_font({"font": "digital7"}, font_size_px)
    display = _truncate_text_to_width(label, max_width_px=max_w, font=font)
    for el in group.iter():
        logical = _normalize_logical(el.get("id") or "")
        if not (logical.endswith("_loation1_text") or logical.endswith("_location1_text")):
            continue
        _set_text_content(el, display)
        for node in el.iter():
            if node.tag.endswith("text"):
                _set_svg_text_horiz_centered(node, center_svg, y_svg)


def _apply_box_location_text_contrast(
    root: ET.Element,
    *,
    box_num: int,
    selected: bool,
    theme: SettingsTheme,
) -> None:
    group = _find_by_logical_id(root, f"main_box{box_num}_location_group")
    if group is None:
        return
    for el in group.iter():
        logical = _normalize_logical(el.get("id") or "")
        if el.tag.endswith("text") or logical.endswith("_loation1_text") or logical.endswith(
            "_location1_text"
        ):
            _apply_contrast_paint(el, selected=selected, theme=theme)


def _box_num_from_chrome_logical(logical: str) -> int | None:
    m = _BOX_CHROME_NUM_RE.match(logical)
    return int(m.group(1)) if m else None


def _location_display_text(state: MainSettingsState) -> str:
    """Dual-bar location label; shows pending/selected SSID while entering network password."""
    kb = state.keyboard
    if state.keyboard_open and kb is not None:
        target = str(getattr(kb, "target", "") or "")
        if target == "network":
            ssid = str(state.pending_wifi_ssid or state.selected_wifi_ssid or "").strip()
            if ssid:
                return ssid
    return location_room_label(state.location_name, slot_index=1)


def _force_layer_white(el: ET.Element) -> None:
    tag = el.tag.rsplit("}", 1)[-1]
    if tag not in ("path", "rect", "polygon", "circle", "ellipse", "text"):
        return
    fill, stroke = _iter_style_fill_stroke(el)
    if fill and fill not in ("none", "transparent"):
        _set_paint(el, fill="#ffffff")
    if stroke and stroke not in ("none", "transparent"):
        _set_paint(el, stroke="#ffffff")


def _apply_wifi_search_glyph_layers(search_group: ET.Element) -> None:
    """WiFi search art: ellipse paths are stroke-only; triangles are fill-only."""
    for el in search_group.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        fill, stroke = _iter_style_fill_stroke(el)
        if tag == "polygon":
            _set_paint(el, fill=fill or "#ffffff", stroke="none")
        elif tag in ("circle", "path"):
            _set_paint(el, fill="none", stroke=stroke or "#ffffff")


def _hide_wifi_search_glyphs(root: ET.Element) -> None:
    """Hide only the onboarding search rings (``+`` stays static while scanning)."""
    search_group = _wifi_onboarding_search_group(root)
    if search_group is not None:
        _set_visible(search_group, False)


def _apply_wifi_search_icon_styles(
    root: ET.Element,
    *,
    focused: str,
    theme: SettingsTheme,
) -> None:
    """Onboarding search rings stay stroke-only; ``+`` follows selection contrast."""
    add_group = _find_by_logical_id(root, "main_box2_add_search_icon")
    if add_group is None:
        return
    selected = focused == "main_box2_add_search_icon"
    search_group = _wifi_onboarding_search_group(root)
    if search_group is not None:
        _apply_wifi_search_glyph_layers(search_group)
    _center_wifi_plus_icon(root)
    plus_group = _find_by_logical_id(root, "main_box2_+_icon")
    if plus_group is not None:
        for el in plus_group.iter():
            logical = _normalize_logical(el.get("id") or "")
            if logical.startswith("main_box2_+_icon") or el is plus_group:
                _apply_direct_glyph_contrast(el, selected=selected, theme=theme)


def _apply_picker_network_labels(root: ET.Element, state: MainSettingsState) -> None:
    if not state.show_network_picker:
        return
    names = state.wifi_networks
    scroll = max(0, int(state.network_picker_scroll))
    for i, text_id in enumerate(_PICKER_ROW_TEXTS):
        idx = scroll + i
        label = names[idx] if idx < len(names) else ""
        # Digital-7 has limited lowercase coverage — uppercase keeps SSIDs visible on Pi.
        display = str(label).upper() if label else ""
        for text_el in _find_all_by_logical_id(root, text_id):
            _set_text_content(text_el, display)
            targets = [text_el] if text_el.tag.endswith("text") else [
                n for n in text_el.iter() if n.tag.endswith("text")
            ]
            for target in targets:
                pos = _parse_matrix_translate(target.get("transform"))
                y_svg = pos[1] if pos is not None else 270.3023 + i * 48.0
                _set_svg_text_horiz_centered(target, _PICKER_TEXT_CENTER_X_SVG, y_svg)


def _hide_wifi_onboarding_chrome_for_picker(root: ET.Element) -> None:
    """Hide search/label layers once the network picker replaces onboarding art."""
    for lid in (
        "rename_your_nest_text",
        "main_box2_add_search_icon",
        "main_box1_text",
        "welcome_to_pigeon_find_your_wifi_text",
    ):
        _set_visible(_find_by_logical_id(root, lid), False)


def _hide_all_box_chrome(root: ET.Element) -> None:
    """Hide panel chrome (search results, search icons, etc.) for all three columns."""
    parents = _parent_map(root)
    add_group = _find_by_logical_id(root, "main_box2_add_search_icon")
    for el in root.iter():
        if not el.tag.endswith("g"):
            continue
        logical = _normalize_logical(el.get("id") or "")
        if logical in _BOX_CONTAINER_LOGICALS:
            continue
        if add_group is not None and _is_descendant_of(el, add_group, parents):
            continue
        if _is_box_chrome_logical(logical):
            _set_visible(el, False)
    for gid in _BOX_LOCATION_GROUPS:
        _set_visible(_find_by_logical_id(root, gid), False)


def _network_field_text(state: MainSettingsState) -> str | None:
    """Dual-network label text, or ``None`` to preserve SVG placeholder art."""
    if state.show_location_picker and not _needs_wifi_setup(state):
        return "RENAME"
    if state.wifi_configured:
        return "CONNECTED"
    if state.wifi_connecting or state.keyboard_open:
        return None
    return "CONNECT TO WIFI"


def _network_field_font_size_svg(display: str) -> float | None:
    """Disconnected label uses the same size as the location field."""
    return None


def _dual_bar_pill_center_y_px() -> int:
    from pigeon.settings_layout import DUAL_SLOT_A, dual_slot_design

    _x, y, _w, h = dual_slot_design(DUAL_SLOT_A)
    return y + int(round(h * 0.72))


def _draw_dual_bar_network_prompt(bgra: np.ndarray, state: MainSettingsState) -> None:
    """Paint the disconnected dual-network CTA with Digital-7 sizing and vertical centering."""
    if (
        state.wifi_configured
        or state.wifi_connecting
        or state.keyboard_open
        or state.show_network_picker
    ):
        return
    label = _network_field_text(state)
    if label != "CONNECT TO WIFI":
        return
    net_x0 = int(round(_DUAL_NETWORK_TEXT_X0_SVG * DESIGN_W / 800.0))
    net_x1 = int(round(_DUAL_NETWORK_TEXT_X1_SVG * DESIGN_W / 800.0))
    loc_spec = _TEXT_ENTRY_FIELDS["location"]
    display = label.upper()
    start_px = _field_font_size_px(float(loc_spec["font_size_svg"]))
    size_px, font = _fit_text_font_size(
        display,
        lambda s: _field_font(loc_spec, s),
        max_width_px=max(24, net_x1 - net_x0 - 16),
        start_px=start_px,
    )
    text_y = _dual_bar_pill_center_y_px()
    rgb = cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA)
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)
    _draw_centered_field_text(
        draw,
        x0_px=net_x0,
        x1_px=net_x1,
        baseline_px=text_y,
        text=display,
        font=font,
        fill=_COLOR_GRAY_RGBA,
    )
    bgra[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)


def _apply_wifi_onboarding_visibility(root: ET.Element, state: MainSettingsState) -> None:
    """Hide box columns until WiFi is configured; show instructions search chrome."""
    no_wifi = _needs_wifi_setup(state)

    if no_wifi:
        _set_box_columns_visible(root, False)
        _set_visible(_find_by_logical_id(root, "main_instructions"), False)
        _set_visible(_find_by_logical_id(root, "rename_your_nest_text"), False)
        add_visible = False
        _set_visible(
            _find_by_logical_id(root, "main_box2_add_search_icon"),
            state.wifi_scanning or state.wifi_connecting,
        )
        _hide_all_box_chrome(root)
    else:
        _set_visible(_find_by_logical_id(root, "welcome_to_pigeon_group"), False)
        _set_visible(_find_by_logical_id(root, "welcome_to_pigeon_find_your_wifi_text"), False)
        _set_visible(_find_by_logical_id(root, "main_box2_add_search_icon"), False)
        _set_visible(_find_by_logical_id(root, "main_box1_text"), False)
        show_rename_hint = bool(state.show_instructions or state.show_location_picker)
        nest_el = _find_by_logical_id(root, "rename_your_nest_text")
        if nest_el is not None and state.show_location_picker:
            _set_text_content(nest_el, "select your nest")
            _force_layer_white(nest_el)
        _set_visible(nest_el, show_rename_hint)
        _set_box_columns_visible(root, True)


def _finalize_wifi_onboarding_layers(root: ET.Element, state: MainSettingsState) -> None:
    """Re-apply onboarding chrome after ``main_instructions`` visibility is toggled."""
    if not _needs_wifi_setup(state) or state.show_network_picker:
        return
    _set_visible(_find_by_logical_id(root, "rename_your_nest_text"), False)
    _set_visible(
        _find_by_logical_id(root, "main_box1_text"),
        not (state.wifi_scanning or state.wifi_connecting),
    )
    _apply_wifi_onboarding_search_layers(root, state)


def _apply_scene_layer_visibility(root: ET.Element, state: MainSettingsState) -> None:
    """
    Default view shows only launch layers (exit, dual bar, box device groups, background).

    Location groups, instructions, network picker, and box panel chrome open via state flags.
    """
    focused = "" if state.keyboard_open else state.focused_id
    _apply_wifi_onboarding_visibility(root, state)
    no_wifi = _needs_wifi_setup(state)

    show_search_chrome = no_wifi and (state.wifi_scanning or state.wifi_connecting)
    _set_visible(_find_by_logical_id(root, "main_instructions"), show_search_chrome)
    _set_visible(_find_by_logical_id(root, "welcome_to_pigeon_find_your_wifi_text"), False)
    if not no_wifi:
        _set_visible(_find_by_logical_id(root, "welcome_to_pigeon_group"), False)
        _set_visible(_find_by_logical_id(root, "main_box2_add_search_icon"), False)
    _set_visible(_find_by_logical_id(root, "main_network_picker"), state.show_network_picker)
    _finalize_wifi_onboarding_layers(root, state)

    if state.show_network_picker:
        _hide_wifi_onboarding_chrome_for_picker(root)

    location_picker = bool(state.show_location_picker) and not no_wifi
    # Panel chrome (search / results) — not used for the dual-location rename picker.
    panel_open = {
        1: False if no_wifi else bool(state.show_box1_panel),
        2: False
        if no_wifi or state.manual_device_entry is not None
        else bool(state.show_box2_panel or state.box2_devices.active),
        3: False
        if no_wifi or state.manual_device_entry is not None
        else bool(state.show_box3_panel or state.box3_devices.active),
    }
    for i, gid in enumerate(_BOX_LOCATION_GROUPS, start=1):
        if location_picker:
            show_loc = True
        else:
            show_loc = panel_open.get(i, False)
            if i in (2, 3):
                panel = state._box_panel(i)
                if panel.active:
                    show_loc = False
        _set_visible(_find_by_logical_id(root, gid), show_loc)

    parents = _parent_map(root)
    add_group = _find_by_logical_id(root, "main_box2_add_search_icon")
    # Walk indexed chrome ids only — avoid normalizing every <g> in the 3.7k-node tree.
    for logical, els in _logical_id_index(root).items():
        if logical in _BOX_CONTAINER_LOGICALS:
            show = not no_wifi and state.manual_device_entry is None
            for el in els:
                _set_visible(el, show)
            continue
        if not _is_box_chrome_logical(logical):
            continue
        box_num = _box_num_from_chrome_logical(logical)
        show = False if location_picker else bool(box_num and panel_open.get(box_num, False))
        for el in els:
            if add_group is not None and _is_descendant_of(el, add_group, parents):
                continue
            _set_visible(el, show)

    if location_picker:
        # Match Illustrator dual-location visibility: location + container on; device/search off.
        for box_num in (1, 2, 3):
            _set_visible(_find_by_logical_id(root, _BOX_DEVICE_GROUPS[box_num]), False)
            _set_visible(_find_by_logical_id(root, f"main_box{box_num}_search_icon"), False)
            _set_box_search_results_visible(root, box_num, False)
            _hide_box_search_animation_layers(root, box_num)
            _set_visible(_find_by_logical_id(root, _BOX_LOCATION_GROUPS[box_num - 1]), True)
            _set_visible(
                _find_by_logical_id(root, f"main_box{box_num}_container"),
                True,
            )
    else:
        for box_num in (2, 3):
            _apply_box_device_panel_layers(
                root, state, box_num, theme=state.theme, focused=focused
            )
        # Box1 has no LAN device search — keep its search spinner art permanently off.
        _hide_box_search_animation_layers(root, 1)
        # Restore host device chrome after leaving the location rename picker.
        if not no_wifi and state.manual_device_entry is None:
            _set_visible(_find_by_logical_id(root, "main_box1_device_group"), True)


def _parse_svg_text_y_svg(el: ET.Element) -> float | None:
    """Read the ``y`` translate from a text element's ``transform`` matrix."""
    targets = [el] if el.tag.endswith("text") else [n for n in el.iter() if n.tag.endswith("text")]
    for target in targets:
        transform = target.get("transform") or ""
        m = _MATRIX_RE.search(transform)
        if m:
            return float(m.group(6))
    return None


def _is_box_results_device_logical(logical: str, box_num: int) -> bool:
    prefix = f"main_box{box_num}_device"
    if not logical.startswith(prefix) or "text" not in logical:
        return False
    if any(
        token in logical
        for token in ("device_group", "device_name", "device_ip", "search_results_device")
    ):
        return False
    return True


def _find_box_result_device_layer(
    root: ET.Element,
    box_num: int,
    row: int,
) -> ET.Element | None:
    """Locate the device-name text layer for a results row (1-based)."""
    if row < 1 or row > len(_BOX_RESULT_ROW_Y_SVG):
        return None
    target_y = _BOX_RESULT_ROW_Y_SVG[row - 1]
    best: ET.Element | None = None
    best_dy = 999.0
    for el in root.iter():
        logical = _normalize_logical(el.get("id") or "")
        if not _is_box_results_device_logical(logical, box_num):
            continue
        y = _parse_svg_text_y_svg(el)
        if y is None:
            continue
        dy = abs(y - target_y)
        if dy < best_dy:
            best_dy = dy
            best = el
    return best if best_dy <= 2.5 else None


def _find_box_result_layer(
    root: ET.Element,
    box_num: int,
    kind: str,
    row: int,
) -> ET.Element | None:
    """Find device/ip text or mini button for a results row (1-based)."""
    if kind == "device":
        return _find_box_result_device_layer(root, box_num, row)
    stem = f"main_box{box_num}_{kind}{row}"
    if kind == "mini":
        stem = f"main_box{box_num}_mini{row}_button"
    for el in root.iter():
        logical = _normalize_logical(el.get("id") or "")
        if logical == stem or logical.startswith(f"{stem}_"):
            return el
    return None


def _hide_vertical_scroll_arrows(root: ET.Element) -> None:
    """Up/down scroll glyphs are unused — main settings navigates left/right only."""
    for lid in ("main_network_picker_up_icon", "main_network_picker_down_icon"):
        _set_visible(_find_by_logical_id(root, lid), False)
    for box_num in (2, 3):
        for direction in ("up", "down"):
            _set_visible(_find_box_scroll_arrow(root, box_num, direction), False)


def _set_box_search_results_visible(root: ET.Element, box_num: int, visible: bool) -> None:
    """Toggle the search-results subtree (rows + mini buttons; no scroll arrows)."""
    prefixes = (f"main_box{box_num}_search_results",)
    for el in root.iter():
        logical = _normalize_logical(el.get("id") or "")
        if any(logical.startswith(prefix) for prefix in prefixes):
            _set_visible(el, visible)
    for direction in ("up", "down"):
        _set_visible(_find_box_scroll_arrow(root, box_num, direction), False)


def _apply_box_search_icon_glyph_styles(
    search_icon: ET.Element | None,
    *,
    color: str = "#202020",
) -> None:
    """Ellipses: stroke only. Arrow triangles and ``+``: fill only."""
    if search_icon is None:
        return
    for el in search_icon.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        logical = _normalize_logical(el.get("id") or "")
        if tag in ("circle", "path"):
            _set_paint(el, fill="none", stroke=color)
        elif tag == "polygon" and "triangle" in logical:
            _set_paint(el, fill=color, stroke="none")
        elif tag == "text":
            _set_paint(el, fill=color, stroke="none")


def _set_box_search_plus_visible(search_icon: ET.Element | None, visible: bool) -> None:
    if search_icon is None:
        return
    for el in search_icon.iter():
        if el.tag.endswith("text"):
            _set_visible(el, visible)


def _show_box_search_icon_vectors(search_icon: ET.Element | None) -> None:
    """Show filled triangles/plus and stroke arcs; hide leftover clip-path circles."""
    if search_icon is None:
        return
    for el in search_icon.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("polygon", "path", "text"):
            _set_visible(el, True)
        elif tag == "circle":
            _set_visible(el, False)


def _apply_box_search_icon_variant(
    search_icon: ET.Element | None,
    *,
    selected: bool,
    show_plus: bool = True,
) -> None:
    """Paint box column add/search art (black glyphs on white pill, white on black).

    Plus and triangles are fills; ellipse arcs are strokes. Keep groups present
    and only recolor. Leftover clip-path circles stay hidden.
    """
    if search_icon is None:
        return
    color = "#202020" if selected else "#ffffff"
    _apply_box_search_icon_glyph_styles(search_icon, color=color)
    for el in search_icon.iter():
        if el is search_icon:
            continue
        logical = _normalize_logical(el.get("id") or "")
        tag = el.tag.rsplit("}", 1)[-1]
        if "ellipse" in logical or "eplipse" in logical or tag == "path":
            _set_visible(el, True)
        if tag == "circle":
            _set_visible(el, False)
    _set_box_search_plus_visible(search_icon, bool(show_plus))


def _apply_box_result_text_style(
    el: ET.Element | None,
    *,
    selected: bool,
    theme: SettingsTheme,
) -> None:
    """Selected row: black on white mini; unselected: white on dark column."""
    if el is None:
        return
    fill = theme.deselected if selected else theme.selected
    targets = [el] if el.tag.endswith("text") else [n for n in el.iter() if n.tag.endswith("text")]
    for hit in targets:
        _set_paint(hit, fill=fill)


def _find_box_scroll_arrow(root: ET.Element, box_num: int, direction: str) -> ET.Element | None:
    stem = f"main_box{box_num}_{direction}_icon"
    for el in root.iter():
        logical = _normalize_logical(el.get("id") or "")
        if logical == stem or logical.startswith(f"{stem}_"):
            return el
    return None


def _apply_scroll_arrow_glyph(
    el: ET.Element | None,
    *,
    selected: bool,
    disabled: bool,
    theme: SettingsTheme,
) -> None:
    _apply_direct_glyph_contrast(el, selected=selected, disabled=disabled, theme=theme)


def _apply_network_picker_arrows(
    root: ET.Element,
    state: MainSettingsState,
    *,
    theme: SettingsTheme,
) -> None:
    _hide_vertical_scroll_arrows(root)


def _box_nav_button_selected(
    state: MainSettingsState,
    box_num: int,
    *,
    focused: str,
) -> bool:
    logical = f"main_box{box_num}_button"
    locked = state.box_device_results_locked()
    if locked is not None:
        return False
    if state.manual_device_entry is not None:
        return False
    if box_num in (2, 3):
        panel = state._box_panel(box_num)
        if panel.scanning and panel.active:
            return True
    if state.keyboard_open:
        return False
    if focused == logical:
        return True
    # While picking nests, also highlight the currently active location.
    if state.show_location_picker:
        try:
            from pigeon.app_state import read_current_location_id

            cur = str(read_current_location_id() or "").strip()
        except Exception:
            cur = ""
        if cur:
            slot = state.location_slot(box_num)
            if slot is not None and str(slot[0]) == cur:
                return True
    return False


def _apply_box_column_nav_fills(
    root: ET.Element,
    state: MainSettingsState,
    *,
    focused: str,
    theme: SettingsTheme,
) -> None:
    """Always paint box1–3 nav pills (virtual results focus skips the main ring loop)."""
    scanning_box: int | None = None
    for box_num in (2, 3):
        panel = state._box_panel(box_num)
        if panel.scanning and panel.active:
            scanning_box = box_num
            break
    for box_num in (1, 2, 3):
        logical = f"main_box{box_num}_button"
        if scanning_box is not None:
            selected = box_num == scanning_box
        else:
            selected = _box_nav_button_selected(state, box_num, focused=focused)
        button_el = _find_by_logical_id(root, logical)
        _apply_button_fill(button_el, selected=selected, theme=theme)
        for hit in _find_all_by_logical_id(root, logical):
            _apply_button_fill(hit, selected=selected, theme=theme)
        _apply_box_device_text_contrast(
            root, box_num=box_num, selected=selected, theme=theme
        )
        _apply_box_location_text_contrast(
            root, box_num=box_num, selected=selected, theme=theme
        )


def _apply_dual_bar_nav_fills(
    root: ET.Element,
    state: MainSettingsState,
    *,
    focused: str,
    theme: SettingsTheme,
) -> None:
    """Dual-bar pills stay deselected while browsing box device search results."""
    results_locked = state.box_device_results_locked() is not None
    for logical in ("main_dual_location_button", "main_dual_network_button"):
        if results_locked or state.show_network_picker or state.keyboard_open:
            selected = False
        else:
            selected = focused == logical
        button_el = _find_by_logical_id(root, logical)
        _apply_button_fill(button_el, selected=selected, theme=theme)
        for hit in _find_all_by_logical_id(root, logical):
            _apply_button_fill(hit, selected=selected, theme=theme)
        for assoc in _FOCUS_ASSOCIATED.get(logical, ()):
            for assoc_el in _find_all_by_logical_id(root, assoc):
                cls = _layer_class(_normalize_logical(assoc_el.get("id") or assoc))
                if cls == "_accent":
                    continue
                _apply_contrast_paint(assoc_el, selected=selected, theme=theme)


def _apply_box_device_panel_layers(
    root: ET.Element,
    state: MainSettingsState,
    box_num: int,
    *,
    theme: SettingsTheme,
    focused: str = "",
) -> None:
    panel = state._box_panel(box_num)
    device_group = _find_box_device_group(root, box_num)
    location_group = _find_by_logical_id(root, f"main_box{box_num}_location_group")
    search_icon = _find_box_column_search_icon(root, box_num)
    has_device = state.box_has_saved_device(box_num)
    capture = bool(getattr(state, "spinner_glyph_capture", False))

    if panel.results_locked:
        _set_visible(device_group, False)
        _set_visible(location_group, False)
        _hide_box_search_animation_layers(root, box_num)
        _set_box_search_results_visible(root, box_num, True)

        names = panel.devices
        scroll = max(0, int(panel.scroll))
        row_idx = max(0, min(_BOX_DEVICE_ROW_COUNT - 1, int(panel.row)))

        for i in range(1, _BOX_DEVICE_ROW_COUNT + 1):
            for kind in ("device", "ip", "mini"):
                layer = _find_box_result_layer(root, box_num, kind, i)
                if layer is not None:
                    _set_visible(layer, False)

        for i in range(1, _BOX_DEVICE_ROW_COUNT + 1):
            idx = scroll + (i - 1)
            has_data = 0 <= idx < len(names)
            name, ip = names[idx] if has_data else ("", "")
            show_ip = has_data and name not in (BOX_DEVICE_ROW_ENTER_IP, BOX_DEVICE_ROW_CANCEL)
            selected_row = has_data and (i - 1) == row_idx

            dev_el = _find_box_result_device_layer(root, box_num, i)
            ip_el = _find_box_result_layer(root, box_num, "ip", i)
            mini_el = _find_box_result_layer(root, box_num, "mini", i)

            if dev_el is not None:
                _set_visible(dev_el, has_data)
                if has_data:
                    display_name = name.upper() if name else ""
                    _apply_box_result_row_text_layout(
                        dev_el, ip_el if show_ip else None, name=display_name, ip=ip, row=i, box_num=box_num
                    )
                    _apply_box_result_text_style(dev_el, selected=selected_row, theme=theme)
            if ip_el is not None:
                _set_visible(ip_el, show_ip)
                if show_ip:
                    if dev_el is None:
                        _apply_box_result_row_text_layout(
                            None, ip_el, name=name, ip=ip, row=i, box_num=box_num
                        )
                    _apply_box_result_text_style(ip_el, selected=selected_row, theme=theme)
            if mini_el is not None:
                _set_visible(mini_el, selected_row)
                if selected_row:
                    _apply_button_fill(mini_el, selected=True, theme=theme)
                    for hit in _find_all_by_logical_id(root, mini_el.get("id") or ""):
                        _apply_button_fill(hit, selected=True, theme=theme)

        for direction in ("up", "down"):
            _set_visible(_find_box_scroll_arrow(root, box_num, direction), False)
        return
    elif panel.active and panel.phase == "scanning":
        _set_visible(device_group, False)
        _set_visible(location_group, False)
        _set_box_search_results_visible(root, box_num, False)
        if search_icon is not None:
            _set_visible(search_icon, capture)
            if capture:
                _apply_box_search_icon_variant(search_icon, selected=True, show_plus=False)
            _hide_box_search_icon_vectors(search_icon)
        else:
            _hide_box_search_animation_layers(root, box_num)
        return
    elif has_device:
        show_loc = _box_shows_location_group(state, box_num, panel)
        _set_visible(device_group, True)
        _set_visible(location_group, show_loc)
        _hide_box_search_animation_layers(root, box_num)
        _set_box_search_results_visible(root, box_num, False)
        return
    else:
        show_loc = _box_shows_location_group(state, box_num, panel)
        _set_visible(device_group, False)
        _set_visible(location_group, show_loc)
        _set_box_search_results_visible(root, box_num, False)
        if search_icon is not None:
            _set_visible(search_icon, True)
            icon_selected = focused == f"main_box{box_num}_button" or (
                panel.scanning and panel.active
            )
            _apply_box_search_icon_variant(
                search_icon,
                selected=icon_selected,
                show_plus=not (panel.scanning and panel.active),
            )
            if panel.scanning and panel.active:
                _hide_box_search_icon_vectors(search_icon)
            else:
                _show_box_search_icon_vectors(search_icon)
        return


def _box_button_fill_selected(state: MainSettingsState, box_num: int, focused: str) -> bool:
    return focused == f"main_box{box_num}_button"


def _apply_network_picker_rows(
    root: ET.Element,
    state: MainSettingsState,
    *,
    theme: SettingsTheme,
) -> None:
    """Per-row white/black pills inside the picker (outer container stays dark)."""
    if not state.show_network_picker:
        return
    names = state.wifi_networks
    scroll = max(0, int(state.network_picker_scroll))
    row_idx = max(0, min(len(_PICKER_ROW_MINI_BUTTONS) - 1, int(state.network_picker_row)))
    for i, mini_id in enumerate(_PICKER_ROW_MINI_BUTTONS):
        has_network = (scroll + i) < len(names)
        selected = has_network and i == row_idx
        mini_el = _find_by_logical_id(root, mini_id)
        _set_visible(mini_el, has_network)
        if has_network:
            _apply_button_fill(mini_el, selected=selected, theme=theme)
            for hit in _find_all_by_logical_id(root, mini_id):
                _apply_button_fill(hit, selected=selected, theme=theme)

    for i, text_id in enumerate(_PICKER_ROW_TEXTS):
        has_network = (scroll + i) < len(names)
        selected = has_network and i == row_idx
        for text_el in _find_all_by_logical_id(root, text_id):
            _set_visible(text_el, has_network)
            if has_network:
                _apply_contrast_paint(text_el, selected=selected, theme=theme)

    for i, lock_id in enumerate(_PICKER_ROW_LOCK_GROUPS):
        has_network = (scroll + i) < len(names)
        selected = has_network and i == row_idx
        for lock_el in _find_all_by_logical_id(root, lock_id):
            _set_visible(lock_el, has_network)
            if has_network:
                _apply_contrast_paint(lock_el, selected=selected, theme=theme)


def discover_focus_ring_in_svg(root: ET.Element, state: MainSettingsState) -> tuple[str, ...]:
    """Build a focus ring from candidates that exist in the SVG tree."""
    state.ensure_focus_ring()
    present: list[str] = []
    for logical in state.focus_ring:
        if logical.endswith("_device_results"):
            present.append(logical)
            continue
        if _find_by_logical_id(root, logical) is not None:
            present.append(logical)
    if not present:
        # Absolute fallback.
        for logical in ("main_exit_button", *_PRIMARY_FOCUS_CANDIDATES):
            if _find_by_logical_id(root, logical) is not None and logical not in present:
                present.append(logical)
    return tuple(present) if present else ("main_exit_button",)


def apply_main_settings_svg_state(root: ET.Element, state: MainSettingsState) -> None:
    """Mutate SVG tree: selection fills, contrast text/icons, accents, visibility."""
    theme = state.theme
    state.ensure_focus_ring()

    for hid in _HIDE_ALWAYS_LOGICAL:
        _remove_by_logical_id(root, hid)

    picker = _find_by_logical_id(root, "main_network_picker")
    _set_visible(picker, bool(state.show_network_picker))
    _apply_scene_layer_visibility(root, state)
    _apply_keyboard_layer_visibility(root, state)
    if not state.exit_enabled:
        _set_visible(_find_by_logical_id(root, "main_exit_group"), False)
        _set_visible(_find_by_logical_id(root, "main_exit_button"), False)

    kb_target = ""
    if state.keyboard is not None:
        kb_target = str(getattr(state.keyboard, "target", "") or "")

    if _needs_wifi_setup(state):
        _hide_wifi_onboarding_search_svg_circles(root)

    if state.wifi_scanning:
        _hide_wifi_search_glyphs(root)
        _set_visible(_find_by_logical_id(root, "main_box2_+_icon"), False)
        _set_visible(_find_by_logical_id(root, "welcome_to_pigeon_find_your_wifi_text"), False)

    _apply_picker_network_labels(root, state)
    _apply_box1_host_device_labels(root)
    for box_num in (2, 3):
        _apply_box_device_group_labels(root, state, box_num)
    for box_num in (1, 2, 3):
        _apply_box_location_group_labels(root, state, box_num)

    # Apply theme accent globally to *_accent layers (selection does not change accent).
    # Prefer the logical-id index over a full-tree normalize walk on every paint.
    for logical, els in _logical_id_index(root).items():
        if logical.endswith("_accent") or re.search(r"_accent(_|$)", logical):
            hide = logical in _HIDDEN_MAIN_ACCENT_IDS
            for el in els:
                if hide:
                    _set_visible(el, False)
                else:
                    _apply_accent_paint(el, theme.accent)
        if logical.endswith("_icon") or "_icon_" in logical:
            for el in els:
                _apply_ui_brand_paint(el, theme.ui)

    entry = state.manual_device_entry
    pairing_pin = state.box_pairing is not None and kb_target == "pin"
    wifi_logout_kb = state.keyboard_open and kb_target == "wifi_logout"
    if entry is not None:
        for lid in _DUAL_LOCATION_ICON_IDS:
            _set_visible(_find_by_logical_id(root, lid), False)
        _set_visible(_find_by_logical_id(root, "main_dual_network_wifi_group"), False)
    if pairing_pin or wifi_logout_kb:
        for lid in _DUAL_LOCATION_ICON_IDS:
            _set_visible(_find_by_logical_id(root, lid), False)
        _set_visible(_find_by_logical_id(root, "main_dual_network_wifi_group"), False)
        _hide_add_search_glyphs(root)
    hide_loc_svg = (
        (state.keyboard_open and kb_target in ("location", "network", "device_name", "pin", "wifi_logout"))
        or state.wifi_connecting
        or entry is not None
        or pairing_pin
    )
    if hide_loc_svg:
        _set_visible(_find_by_logical_id(root, "main_dual_location_text"), False)
    else:
        loc_el = _find_by_logical_id(root, "main_dual_location_text")
        _set_text_content(loc_el, state.location_name)
        loc_x0, loc_x1 = _dual_location_text_bounds_svg(root)
        baseline = float(_TEXT_ENTRY_FIELDS["location"]["baseline_y_svg"])
        if loc_el is not None:
            for node in loc_el.iter():
                if node.tag.endswith("text"):
                    _set_svg_text_horiz_centered(node, (loc_x0 + loc_x1) * 0.5, baseline)
        _set_visible(loc_el, True)
    hide_net_svg = (
        (state.keyboard_open and kb_target in ("network", "device_ip", "pin", "location", "wifi_logout"))
        or state.wifi_connecting
        or entry is not None
        or pairing_pin
    )
    if state.show_location_picker and not _needs_wifi_setup(state):
        # Dual-network becomes the RENAME CTA while picking a nest.
        _set_visible(_find_by_logical_id(root, "main_dual_network_wifi_group"), False)
    if hide_net_svg:
        _set_visible(_find_by_logical_id(root, "main_dual_network_name_text"), False)
    else:
        net_el = _find_by_logical_id(root, "main_dual_network_name_text")
        net_text = _network_field_text(state)
        if net_text == "CONNECT TO WIFI":
            _set_visible(net_el, False)
        elif net_text is not None:
            display = net_text.upper() if not state.wifi_configured or net_text == "RENAME" else net_text
            if net_text == "RENAME":
                display = "RENAME"
            _set_text_content(net_el, display)
            cx = (_DUAL_NETWORK_TEXT_X0_SVG + _DUAL_NETWORK_TEXT_X1_SVG) * 0.5
            baseline = float(_TEXT_ENTRY_FIELDS["location"]["baseline_y_svg"])
            for node in net_el.iter():
                if node.tag.endswith("text"):
                    fit_size = _network_field_font_size_svg(display)
                    if fit_size is not None:
                        _set_svg_text_font_size_px(node, _field_font_size_px(fit_size))
                    _set_svg_text_horiz_centered(node, cx, baseline)
                    if state.wifi_configured and display == "CONNECTED":
                        _set_paint(node, fill="#FFFFFF")
                    elif display == "RENAME":
                        _set_paint(node, fill="#FFFFFF")
                    elif not state.wifi_configured:
                        _set_paint(node, fill="#808080")
            _set_visible(net_el, True)
        else:
            _set_visible(net_el, False)
    for ver_id in ("text_pigeonVersion", "main_pigeon_version_text", "pigeon_version_text"):
        ver_el = _find_by_logical_id(root, ver_id)
        if ver_el is not None:
            _set_text_content(ver_el, state.version_string)
            _apply_contrast_paint(ver_el, selected=True, theme=SettingsTheme(
                selected=COLOR_VERSION_TEXT,
                deselected=COLOR_VERSION_TEXT,
            ))
            # Force black regardless of selection.
            for node in ver_el.iter():
                fill, stroke = _iter_style_fill_stroke(node)
                if fill and fill not in ("none", "transparent"):
                    _set_paint(node, fill=COLOR_VERSION_TEXT)
                if stroke and stroke not in ("none", "transparent"):
                    _set_paint(node, stroke=COLOR_VERSION_TEXT)

    focused = "" if state.keyboard_open else state.focused_id
    ring = discover_focus_ring_in_svg(root, state)
    if not state.keyboard_open and focused not in ring and ring:
        # Snap to a ring entry that exists.
        state.focus_ring = ring
        state.focus_index = 0
        focused = state.focused_id

    _apply_background_container(root, state, focused=focused or state.focused_id)
    _hide_vertical_scroll_arrows(root)
    _apply_network_picker_rows(root, state, theme=theme)
    _apply_network_picker_arrows(root, state, theme=theme)

    for logical in ring:
        selected = (not state.keyboard_open) and logical == focused
        if state.show_network_picker and logical in (
            "main_dual_location_button",
            "main_dual_network_button",
        ):
            selected = False
        if logical in ("main_box1_button", "main_box2_button", "main_box3_button"):
            continue
        if logical in ("main_dual_location_button", "main_dual_network_button"):
            continue
        if logical == "main_network_picker_button":
            # Outer picker shell stays dark; row/arrow styling handled separately.
            continue
        if logical == "main_box2_add_search_icon":
            _apply_wifi_search_icon_styles(root, focused=focused, theme=theme)
            continue
        button_el = _find_by_logical_id(root, logical)
        _apply_button_fill(button_el, selected=selected, theme=theme)

        # Also paint direct path children named the same logical button.
        for hit in _find_all_by_logical_id(root, logical):
            _apply_button_fill(hit, selected=selected, theme=theme)

        for assoc in _FOCUS_ASSOCIATED.get(logical, ()):
            for assoc_el in _find_all_by_logical_id(root, assoc):
                cls = _layer_class(_normalize_logical(assoc_el.get("id") or assoc))
                if cls == "_accent":
                    continue
                _apply_contrast_paint(assoc_el, selected=selected, theme=theme)

        # Exit text lives under main_exit_icon; ensure EXIT contrast.
        if logical == "main_exit_button":
            for assoc_el in _find_all_by_logical_id(root, "main_exit_text"):
                _apply_contrast_paint(assoc_el, selected=selected, theme=theme)

    _apply_box_column_nav_fills(root, state, focused=focused, theme=theme)
    _apply_dual_bar_nav_fills(root, state, focused=focused, theme=theme)
