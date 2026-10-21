"""
Wifi-icon and search-animation overlay geometry and drawing for the main settings menu.

Finds the wifi icons, onboarding / per-box search rings (arcs, star-masked circles,
triangles) in the settings SVG tree, hides the vector versions, and redraws them as
anti-aliased BGRA overlays so the spinner can rotate. Also owns the small SVG
geometry helpers they share (matrix / points parsing, svg-to-pixel scaling).

``pigeon.widgets.main_settings`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pigeon.design import map_legacy_size, map_legacy_xy
from pigeon.widgets.settings_state import COLOR_UI_DEFAULT, MainSettingsState
from pigeon.widgets.settings_svg_text import _is_hidden as _is_subtree_hidden
from pigeon.widgets.settings_svg_tree import (
    _find_all_by_logical_id,
    _find_by_logical_id,
    _is_descendant_of,
    _iter_style_fill_stroke,
    _normalize_logical,
    _parent_map,
    _set_visible,
)
from pigeon.widgets.settings_theme_background import _transform_rect_corners as _transform_rect_corners_svg


XLINK_NS = "http://www.w3.org/1999/xlink"


_MATRIX_RE = re.compile(
    r"matrix\(\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s*\)",
    re.IGNORECASE,
)


_TRANSLATE_RE = re.compile(
    r"translate\(\s*([-\d.]+)(?:[,\s]+([-\d.]+))?\s*\)",
    re.IGNORECASE,
)


_SEARCH_GLYPH_BGR = (0, 0, 0)


_WIFI_SEARCH_GLYPH_BGR = (255, 255, 255)


_WIFI_RADII_SVG: tuple[float, float, float] = (18.668, 29.008, 39.145)


_WIFI_STROKE_SVG = 5.0


_WIFI_FAIL_SIZE_SVG = 42.0


_COLOR_GRAY_BGR = (128, 128, 128)


# WiFi onboarding (instructions + search glyph under ``main_instructions``).
_WIFI_SEARCH_CENTER_SVG = (400.446, 298.466)


_WIFI_SEARCH_RING_RADIUS_SVG = 32.247


_WIFI_SEARCH_RING_STROKE_SVG = 9.0


_WIFI_SEARCH_PATCH_RADIUS_PX = 52


_DUAL_LOCATION_WIFI_CENTER_SVG = (111.133, 172.5)


@dataclass(frozen=True)
class _WifiIconLayout:
    """Hex clip + ring geometry from ``settings_main.svg`` (PyMuPDF ignores clip-path)."""

    clip_polygon_svg: tuple[tuple[float, float], ...]
    cx_svg: float
    cy_svg: float
    fail_text_xy_svg: tuple[float, float] | None = None
    focus_logical: str = "main_dual_network_button"
    picker_row: bool = False
    picker_slot: int | None = None


def _needs_wifi_setup(state: MainSettingsState) -> bool:
    return state.needs_wifi_setup()


def _wifi_onboarding_add_search_group(root: ET.Element) -> ET.Element | None:
    return _find_by_logical_id(root, "main_box2_add_search_icon")


def _find_box_root_group(root: ET.Element, box_num: int) -> ET.Element | None:
    want = f"main_box{box_num}"
    for el in root.iter():
        if not el.tag.endswith("g"):
            continue
        if _normalize_logical(el.get("id") or "") == want:
            return el
    return None


_SVG_ARC_PATH_RE = re.compile(
    r"M\s*([-\d.]+)(?:\s*,\s*|\s+)([-\d.]+)\s*"
    r"A\s*([-\d.]+)(?:\s*,\s*|\s+)([-\d.]+)\s+"
    r"([-\d.]+)\s+(\d)\s+(\d)\s+"
    r"([-\d.]+)(?:\s*,\s*|\s+)([-\d.]+)",
    re.IGNORECASE,
)


def _svg_arc_center_and_angles(
    x1: float,
    y1: float,
    rx: float,
    ry: float,
    phi_deg: float,
    fa: int,
    fs: int,
    x2: float,
    y2: float,
) -> tuple[float, float, float, float] | None:
    """Endpoint-parameterized SVG arc → center + start/end degrees (0=east, y-down)."""
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-6 or ry < 1e-6:
        return None
    phi = math.radians(phi_deg)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx = (x1 - x2) / 2.0
    dy = (y1 - y2) / 2.0
    x1p = cos_p * dx + sin_p * dy
    y1p = -sin_p * dx + cos_p * dy
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = 0.0 if den <= 1e-12 else math.sqrt(max(0.0, num / den))
    if fa == fs:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = coef * -ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2.0
    start = math.degrees(math.atan2(y1 - cy, x1 - cx)) % 360.0
    end = math.degrees(math.atan2(y2 - cy, x2 - cx)) % 360.0
    return cx, cy, start, end


def _wedge_clip_corners(
    cx: float,
    cy: float,
    radius: float,
    start_deg: float,
    end_deg: float,
    *,
    clockwise: bool,
    pad: float,
) -> tuple[tuple[float, float], ...]:
    """Pie wedge covering a stroked arc so OpenCV can clip a ring to that sweep."""
    sweep = (end_deg - start_deg) % 360.0 if clockwise else (start_deg - end_deg) % 360.0
    if sweep <= 0.0:
        sweep = 360.0
    n = max(12, int(sweep / 4.0) + 1)
    outer = radius + pad
    pts: list[tuple[float, float]] = [(cx, cy)]
    step = sweep / n if clockwise else -sweep / n
    for i in range(n + 1):
        ang = math.radians(start_deg + step * i)
        pts.append((cx + outer * math.cos(ang), cy + outer * math.sin(ang)))
    return tuple(pts)


def _path_stroke_width(el: ET.Element) -> float:
    style = el.get("style") or ""
    sw_m = re.search(r"stroke-width\s*:\s*([-\d.]+)", style, re.IGNORECASE)
    if sw_m:
        return float(sw_m.group(1))
    try:
        return float(el.get("stroke-width") or 8.0)
    except ValueError:
        return 8.0


def _arc_spec_from_search_path(el: ET.Element) -> _OnboardingSearchArcSpec | None:
    """Stroke-only ellipse arc path (no clip-path) → spinner overlay spec."""
    parsed = _SVG_ARC_PATH_RE.search(el.get("d") or "")
    if parsed is None:
        return None
    x1, y1 = float(parsed.group(1)), float(parsed.group(2))
    rx, ry = float(parsed.group(3)), float(parsed.group(4))
    phi = float(parsed.group(5))
    fa, fs = int(parsed.group(6)), int(parsed.group(7))
    x2, y2 = float(parsed.group(8)), float(parsed.group(9))
    converted = _svg_arc_center_and_angles(x1, y1, rx, ry, phi, fa, fs, x2, y2)
    if converted is None:
        return None
    cx, cy, start_deg, end_deg = converted
    radius = (abs(rx) + abs(ry)) / 2.0
    stroke_w = _path_stroke_width(el)
    corners = _wedge_clip_corners(
        cx,
        cy,
        radius,
        start_deg,
        end_deg,
        clockwise=bool(fs),
        pad=stroke_w,
    )
    return _OnboardingSearchArcSpec(
        cx_svg=cx,
        cy_svg=cy,
        radius_svg=radius,
        stroke_svg=stroke_w,
        clip_corners_svg=corners,
    )


def _discover_search_arc_specs_in_group(
    root: ET.Element,
    search_group: ET.Element,
) -> tuple[_OnboardingSearchArcSpec, ...]:
    """Ring arcs from a search-icon subtree (path strokes, or legacy clip-path circles)."""
    parents = _parent_map(root)
    if _is_subtree_hidden(search_group, parents):
        return ()
    specs: list[_OnboardingSearchArcSpec] = []
    for el in search_group.iter():
        if not el.tag.endswith("g"):
            continue
        logical = _normalize_logical(el.get("id") or "")
        if "eplipse" not in logical and "ellipse" not in logical:
            continue
        rect_el: ET.Element | None = None
        circle_el: ET.Element | None = None
        path_el: ET.Element | None = None
        for node in el.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "rect" and node.get("width") and node.get("height"):
                rect_el = node
            if tag == "circle" and node.get("cx") and node.get("r"):
                circle_el = node
            if tag == "path" and "A" in (node.get("d") or "").upper():
                path_el = node
        if path_el is not None:
            spec = _arc_spec_from_search_path(path_el)
            if spec is not None:
                specs.append(spec)
            continue
        if rect_el is None or circle_el is None:
            continue
        try:
            x = float(rect_el.get("x") or 0.0)
            y = float(rect_el.get("y") or 0.0)
            w = float(rect_el.get("width") or 0.0)
            h = float(rect_el.get("height") or 0.0)
        except ValueError:
            continue
        matrix = _parse_svg_matrix(rect_el.get("transform"))
        if matrix is None:
            corners = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
        else:
            corners = _transform_rect_corners_svg(x, y, w, h, matrix)
        cx, cy, radius, stroke_w, _ = _circle_stroke_from_element(circle_el)
        specs.append(
            _OnboardingSearchArcSpec(
                cx_svg=cx,
                cy_svg=cy,
                radius_svg=radius,
                stroke_svg=stroke_w,
                clip_corners_svg=corners,
            )
        )
    return tuple(specs)


def _discover_onboarding_search_arc_specs(root: ET.Element) -> tuple[_OnboardingSearchArcSpec, ...]:
    """Clip-masked ring arcs for onboarding ``main_box2_search_icon``."""
    search_group = _wifi_onboarding_search_group(root)
    if search_group is None:
        return ()
    return _discover_search_arc_specs_in_group(root, search_group)


def _find_box_column_search_icon(root: ET.Element, box_num: int) -> ET.Element | None:
    """Column ``main_box{N}_search_icon`` (skip WiFi onboarding art under add-search)."""
    parents = _parent_map(root)
    add_group = _wifi_onboarding_add_search_group(root)
    box_root = _find_box_root_group(root, box_num)
    want = f"main_box{box_num}_search_icon"
    for el in _find_all_by_logical_id(root, want):
        if add_group is not None and _is_descendant_of(el, add_group, parents):
            continue
        if box_root is not None and not _is_descendant_of(el, box_root, parents):
            continue
        return el
    for el in _find_all_by_logical_id(root, want):
        if add_group is not None and _is_descendant_of(el, add_group, parents):
            continue
        return el
    return None


def _discover_box_search_arc_specs(
    root: ET.Element,
    box_num: int,
) -> tuple[_OnboardingSearchArcSpec, ...]:
    """Clip-masked ring arcs for ``main_box{N}_search_icon`` column spinners."""
    search_group = _find_box_column_search_icon(root, box_num)
    if search_group is None:
        return ()
    return _discover_search_arc_specs_in_group(root, search_group)


def _discover_onboarding_search_triangle_specs(
    root: ET.Element,
) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Filled arrow triangles for onboarding ``main_box2_search_icon``."""
    search_group = _wifi_onboarding_search_group(root)
    if search_group is None:
        return ()
    parents = _parent_map(root)
    if _is_subtree_hidden(search_group, parents):
        return ()
    specs: list[tuple[tuple[float, float], ...]] = []
    for el in search_group.iter():
        if not el.tag.endswith("polygon"):
            continue
        pts = _parse_svg_points(el.get("points") or "")
        if pts:
            specs.append(pts)
    return tuple(specs)


def _draw_onboarding_search_triangle_overlays(
    bgra: np.ndarray,
    specs: tuple[tuple[tuple[float, float], ...], ...],
) -> None:
    for pts in specs:
        px_pts = np.array([_svg_to_px(x, y) for x, y in pts], dtype=np.int32)
        mask = np.zeros(bgra.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [px_pts], 255)
        _composite_stroke_mask(bgra, mask, _SEARCH_GLYPH_BGR)


def _draw_onboarding_search_arc_stroke(
    bgra: np.ndarray,
    spec: _OnboardingSearchArcSpec,
    *,
    color_bgr: tuple[int, int, int],
) -> None:
    cx, cy = _svg_to_px(spec.cx_svg, spec.cy_svg)
    radius = _svg_radius_to_px(spec.radius_svg)
    stroke = max(1, int(round(_svg_scale(spec.stroke_svg))))
    clip_pts = np.array(
        [_svg_to_px(x, y) for x, y in spec.clip_corners_svg],
        dtype=np.int32,
    )
    clip_mask = np.zeros(bgra.shape[:2], dtype=np.uint8)
    cv2.fillPoly(clip_mask, [clip_pts], 255)
    ring_mask = np.zeros(bgra.shape[:2], dtype=np.uint8)
    cv2.circle(ring_mask, (cx, cy), radius, 255, stroke, lineType=cv2.LINE_AA)
    ring_mask = cv2.bitwise_and(ring_mask, clip_mask)
    _composite_stroke_mask(bgra, ring_mask, color_bgr)


def _draw_onboarding_search_arc_overlays(
    bgra: np.ndarray,
    specs: tuple[_OnboardingSearchArcSpec, ...],
) -> None:
    for spec in specs:
        _draw_onboarding_search_arc_stroke(bgra, spec, color_bgr=_SEARCH_GLYPH_BGR)


def _draw_onboarding_search_arc_overlays_on_patch(
    patch: np.ndarray,
    specs: tuple[_OnboardingSearchArcSpec, ...],
    *,
    origin_x0: int,
    origin_y0: int,
    color_bgr: tuple[int, int, int] = _SEARCH_GLYPH_BGR,
) -> None:
    """Draw clipped arcs into a cropped glyph patch (offset-local coordinates)."""
    if patch.size == 0:
        return
    for spec in specs:
        cx, cy = _svg_to_px(spec.cx_svg, spec.cy_svg)
        cx -= origin_x0
        cy -= origin_y0
        radius = _svg_radius_to_px(spec.radius_svg)
        stroke = max(1, int(round(_svg_scale(spec.stroke_svg))))
        clip_pts = np.array(
            [(_svg_to_px(x, y)[0] - origin_x0, _svg_to_px(x, y)[1] - origin_y0) for x, y in spec.clip_corners_svg],
            dtype=np.int32,
        )
        clip_mask = np.zeros(patch.shape[:2], dtype=np.uint8)
        cv2.fillPoly(clip_mask, [clip_pts], 255)
        ring_mask = np.zeros(patch.shape[:2], dtype=np.uint8)
        cv2.circle(ring_mask, (cx, cy), radius, 255, stroke, lineType=cv2.LINE_AA)
        ring_mask = cv2.bitwise_and(ring_mask, clip_mask)
        _composite_stroke_mask(patch, ring_mask, color_bgr)


def _mask_wifi_search_glyph_patch(patch: np.ndarray) -> np.ndarray:
    """Keep glyph pixels (black fill/stroke) so rotation never includes background art."""
    out = patch.copy()
    out[:, :, 3] = np.where(out[:, :, 3] > 0, 255, 0).astype(np.uint8)
    return out


def _mask_search_glyph_patch(patch: np.ndarray, *, include_dark: bool) -> np.ndarray:
    """Isolate spinner glyph pixels (stroked rings and filled arrow triangles)."""
    out = patch.copy()
    b = out[:, :, 0].astype(np.int16)
    g = out[:, :, 1].astype(np.int16)
    r = out[:, :, 2].astype(np.int16)
    mx = np.maximum(np.maximum(r, g), b)
    bright = (b > 180) & (g > 180) & (r > 180)
    if include_dark:
        is_glyph = bright | ((mx > 18) & (mx < 210))
    else:
        is_glyph = bright
    out[:, :, 3] = np.where(is_glyph, 255, 0).astype(np.uint8)
    return out


def _wifi_onboarding_search_group(root: ET.Element) -> ET.Element | None:
    """Search rings nested under ``main_box2_add_search_icon`` (WiFi onboarding art)."""
    add_group = _find_by_logical_id(root, "main_box2_add_search_icon")
    if add_group is None:
        return None
    for child in add_group:
        if not child.tag.endswith("g"):
            continue
        logical = _normalize_logical(child.get("id") or "")
        if logical == "main_box2_search_icon" or logical.startswith("main_box2_search_icon_"):
            return child
    return None


def _svg_scale(value: float) -> float:
    return map_legacy_size(value)


def _svg_to_px(x_svg: float, y_svg: float) -> tuple[int, int]:
    x, y = map_legacy_xy(x_svg, y_svg)
    return int(round(x)), int(round(y))


def _svg_radius_to_px(radius_svg: float) -> int:
    return max(1, int(round(_svg_scale(radius_svg))))


def _hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#").lower()
    if len(h) == 3:
        h = f"{h[0]}{h[0]}{h[1]}{h[1]}{h[2]}{h[2]}"
    if len(h) != 6:
        return (255, 255, 255)
    return (int(h[2:4], 16), int(h[4:6], 16), int(h[0:2], 16))


def _hide_svg_wifi_icons(root: ET.Element) -> None:
    """Remove WiFi circles / fail badge from SVG (redrawn with star clip after rasterize)."""
    parents = _parent_map(root)
    to_remove: list[ET.Element] = []
    for el in root.iter():
        logical = _normalize_logical(el.get("id") or "")
        if re.search(r"wifi[123]_icon", logical) or "wifi_fail_icon" in logical:
            to_remove.append(el)
    for el in to_remove:
        parent = parents.get(el)
        if parent is not None:
            parent.remove(el)


def _hide_box_column_search_svg_circles(root: ET.Element) -> None:
    """Hide leftover clip-path ring circles. Stroke arc paths rasterize correctly."""
    parents = _parent_map(root)
    for box_num in (1, 2, 3):
        search_icon = _find_box_column_search_icon(root, box_num)
        if search_icon is None or _is_subtree_hidden(search_icon, parents):
            continue
        for el in search_icon.iter():
            if el.tag.endswith("circle"):
                _set_visible(el, False)


def _collect_box_search_arc_overlays(
    root: ET.Element,
    state: MainSettingsState,
    *,
    focused_logical: str,
) -> list[_BoxSearchArcOverlay]:
    """Arc specs + stroke colors for visible idle box search icons.

    Path-stroked ellipses rasterize correctly; only legacy clip-path circles
    need an OpenCV redraw. Skip entirely while a keyboard overlay is up so the
    add/search arrows cannot bleed through the PIN pad.
    """
    if state.keyboard_open:
        return []
    parents = _parent_map(root)
    overlays: list[_BoxSearchArcOverlay] = []
    for box_num in (1, 2, 3):
        search_icon = _find_box_column_search_icon(root, box_num)
        if search_icon is None or _is_subtree_hidden(search_icon, parents):
            continue
        if not any(el.tag.endswith("circle") for el in search_icon.iter()):
            continue
        panel = state._box_panel(box_num) if box_num in (2, 3) else None
        scanning = bool(panel is not None and panel.scanning and panel.active)
        # Rotating spinner path draws its own glyph; skip static arcs.
        if scanning and not bool(getattr(state, "spinner_glyph_capture", False)):
            continue
        specs = _discover_search_arc_specs_in_group(root, search_icon)
        if not specs:
            continue
        selected = focused_logical == f"main_box{box_num}_button" or scanning
        color_bgr = _hex_to_bgr("#202020" if selected else "#ffffff")
        overlays.append(_BoxSearchArcOverlay(specs=specs, color_bgr=color_bgr))
    return overlays


def _draw_box_search_arc_overlays(
    bgra: np.ndarray,
    overlays: list[_BoxSearchArcOverlay],
) -> None:
    for overlay in overlays:
        for spec in overlay.specs:
            _draw_onboarding_search_arc_stroke(bgra, spec, color_bgr=overlay.color_bgr)


def _svg_id_index(root: ET.Element) -> dict[str, ET.Element]:
    return {raw: el for el in root.iter() if (raw := el.get("id"))}


def _parse_matrix_translate(transform: str | None) -> tuple[float, float] | None:
    if not transform:
        return None
    m = _MATRIX_RE.search(transform)
    if m:
        return float(m.group(5)), float(m.group(6))
    t = _TRANSLATE_RE.search(transform)
    if t:
        return float(t.group(1)), float(t.group(2) or 0.0)
    return None


def _wifi_star_clip_polygon(group: ET.Element, id_index: dict[str, ET.Element]) -> tuple[tuple[float, float], ...]:
    """Illustrator ``<Star>`` clip mask → polygon points (the visible wifi wedge)."""
    xlink = f"{{{XLINK_NS}}}"
    for cp in group.iter():
        if not cp.tag.endswith("clipPath"):
            continue
        for child in cp:
            if child.tag.endswith("use"):
                href = child.get(f"{xlink}href") or child.get("href") or ""
                ref = href.lstrip("#")
                target = id_index.get(ref)
                if target is not None and target.get("points"):
                    pts = _parse_svg_points(target.get("points"))
                    if pts:
                        return pts
            if child.tag.endswith("polygon") and child.get("points"):
                pts = _parse_svg_points(child.get("points"))
                if pts:
                    return pts
    for poly in group.iter():
        if poly.tag.endswith("polygon") and poly.get("points"):
            pts = _parse_svg_points(poly.get("points"))
            if len(pts) >= 3:
                return pts
    return ()


def _wifi_circle_center(group: ET.Element) -> tuple[float, float] | None:
    for el in group.iter():
        if not el.tag.endswith("circle") or not el.get("cx"):
            continue
        logical = _normalize_logical(el.get("id") or "")
        if re.search(r"wifi[123]_icon", logical) or "wifi" in logical:
            return float(el.get("cx")), float(el.get("cy"))
    for el in group.iter():
        if el.tag.endswith("circle") and el.get("cx"):
            return float(el.get("cx")), float(el.get("cy"))
    return None


def _wifi_fail_text_xy(group: ET.Element) -> tuple[float, float] | None:
    for el in group.iter():
        logical = _normalize_logical(el.get("id") or "")
        if "wifi_fail_icon" not in logical:
            continue
        for text in el.iter():
            if text.tag.endswith("text"):
                pos = _parse_matrix_translate(text.get("transform"))
                if pos is not None:
                    return pos
    return None


def _discover_wifi_icon_layouts(root: ET.Element) -> list[_WifiIconLayout]:
    """Parse each wifi stack's star clip + circle center from ``settings_main.svg``."""
    id_index = _svg_id_index(root)
    parents = _parent_map(root)
    layouts: list[_WifiIconLayout] = []
    for group in root.iter():
        if not group.tag.endswith("g"):
            continue
        if _is_subtree_hidden(group, parents):
            continue
        logical = _normalize_logical(group.get("id") or "")
        is_dual = logical.endswith("_wifi_group")
        is_picker = "wifi_info" in logical and "network_picker" in logical
        if not is_dual and not is_picker:
            continue
        clip = _wifi_star_clip_polygon(group, id_index)
        center = _wifi_circle_center(group)
        if not clip or center is None:
            continue
        cx, cy = center
        if is_dual:
            cy -= 3.0
            focus_logical = "main_dual_network_button"
            picker_row = False
            picker_slot = None
        else:
            focus_logical = "main_network_picker_button"
            picker_row = True
            picker_slot = None
            m = re.search(r"network_picker_row(\d+)_wifi", logical)
            if m:
                picker_slot = int(m.group(1)) - 1
        layouts.append(
            _WifiIconLayout(
                clip_polygon_svg=clip,
                cx_svg=cx,
                cy_svg=cy,
                fail_text_xy_svg=_wifi_fail_text_xy(group),
                focus_logical=focus_logical,
                picker_row=picker_row,
                picker_slot=picker_slot,
            )
        )
    return layouts


def _composite_stroke_mask(
    dst: np.ndarray,
    mask: np.ndarray,
    color_bgr: tuple[int, int, int],
) -> None:
    """Paint ``color_bgr`` where ``mask`` is non-zero (opaque). Avoids full-frame float blends."""
    sel = mask > 0
    if not np.any(sel):
        return
    dst[sel, 0] = color_bgr[0]
    dst[sel, 1] = color_bgr[1]
    dst[sel, 2] = color_bgr[2]
    dst[sel, 3] = 255


@lru_cache(maxsize=4)
def _load_wifi_fail_font(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    from pigeon.font_paths import resolve_ui_font_extrabold

    path = resolve_ui_font_extrabold()
    if not path:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, max(8, size_px))
    except OSError:
        return ImageFont.load_default()


def _draw_wifi_fail_badge(
    bgra: np.ndarray,
    layout: _WifiIconLayout,
    *,
    color_bgr: tuple[int, int, int],
    clip_mask: np.ndarray,
) -> None:
    if layout.fail_text_xy_svg is None:
        return
    x, y = _svg_to_px(*layout.fail_text_xy_svg)
    size_px = max(8, int(round(_svg_scale(_WIFI_FAIL_SIZE_SVG))))
    font = _load_wifi_fail_font(size_px)
    text = "!"

    pad = max(48, size_px * 2)
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(bgra.shape[1], x + pad)
    y1 = min(bgra.shape[0], y + pad)
    patch_h, patch_w = y1 - y0, x1 - x0
    if patch_h <= 0 or patch_w <= 0:
        return

    rgb = np.zeros((patch_h, patch_w, 4), dtype=np.uint8)
    img = Image.fromarray(rgb, mode="RGBA")
    draw = ImageDraw.Draw(img)
    r, g, b = color_bgr[2], color_bgr[1], color_bgr[0]
    draw.text((x - x0, y - y0), text, font=font, fill=(r, g, b, 255), anchor="ls")
    glyph = np.asarray(img)
    glyph_mask = glyph[:, :, 3]

    region_clip = clip_mask[y0:y1, x0:x1]
    combined = cv2.bitwise_and(glyph_mask, region_clip)
    if not np.any(combined > 0):
        return

    sub = bgra[y0:y1, x0:x1]
    alpha = combined.astype(np.float32) / 255.0
    alpha3 = alpha[..., np.newaxis]
    fg = np.array(color_bgr, dtype=np.float32)
    bg = sub[:, :, :3].astype(np.float32)
    sub[:, :, :3] = np.clip(fg * alpha3 + bg * (1.0 - alpha3), 0, 255).astype(np.uint8)
    sub[:, :, 3] = 255


def _draw_wifi_icon_overlay(
    bgra: np.ndarray,
    layout: _WifiIconLayout,
    *,
    level: int,
    active_bgr: tuple[int, int, int],
) -> None:
    cx, cy = _svg_to_px(layout.cx_svg, layout.cy_svg)
    radii = [_svg_radius_to_px(r) for r in _WIFI_RADII_SVG]
    stroke = max(1, int(round(_svg_scale(_WIFI_STROKE_SVG))))

    clip_pts = np.array(
        [_svg_to_px(x, y) for x, y in layout.clip_polygon_svg],
        dtype=np.int32,
    )
    clip_mask = np.zeros(bgra.shape[:2], dtype=np.uint8)
    cv2.fillPoly(clip_mask, [clip_pts], 255)

    if level == 0:
        _draw_wifi_fail_badge(bgra, layout, color_bgr=active_bgr, clip_mask=clip_mask)
        return

    for i, radius in enumerate(radii):
        color = active_bgr if i < level else _COLOR_GRAY_BGR
        ring_mask = np.zeros(bgra.shape[:2], dtype=np.uint8)
        cv2.circle(ring_mask, (cx, cy), radius, 255, stroke, lineType=cv2.LINE_AA)
        ring_mask = cv2.bitwise_and(ring_mask, clip_mask)
        _composite_stroke_mask(bgra, ring_mask, color)


def _draw_wifi_overlays(
    bgra: np.ndarray,
    state: MainSettingsState,
    layouts: list[_WifiIconLayout],
    *,
    focused_logical: str,
) -> None:
    del focused_logical  # WiFi icons stay brand red regardless of nav focus.
    default_level = max(0, min(3, int(state.wifi_level)))
    active_bgr = _hex_to_bgr(state.theme.ui)
    scroll = max(0, int(state.network_picker_scroll))
    kb_target = ""
    if state.keyboard is not None:
        kb_target = str(getattr(state.keyboard, "target", "") or "")
    kb_network = state.keyboard_open and kb_target == "network"
    kb_logout = state.keyboard_open and kb_target == "wifi_logout"
    dual_layout: _WifiIconLayout | None = None
    for layout in layouts:
        if layout.focus_logical == "main_dual_network_button":
            dual_layout = layout
            break
    # Dual-network CTA shows "RENAME" while picking nests — hide the Wi‑Fi logo
    # (SVG group is already display:none; overlays must skip too).
    rename_mode = bool(state.show_location_picker) and not _needs_wifi_setup(state)
    for layout in layouts:
        if layout.picker_row and not state.show_network_picker:
            continue
        if layout.focus_logical == "main_dual_network_button":
            if kb_logout or rename_mode:
                continue
            if not state.wifi_configured and not state.wifi_connecting:
                continue
            if kb_network:
                continue
        level = default_level
        if layout.picker_row and layout.picker_slot is not None:
            abs_idx = scroll + int(layout.picker_slot)
            if abs_idx >= len(state.wifi_networks):
                continue
            level = max(1, min(3, 3 - abs_idx))
        _draw_wifi_icon_overlay(bgra, layout, level=level, active_bgr=active_bgr)
    if (kb_network or kb_logout) and dual_layout is not None:
        loc_layout = _WifiIconLayout(
            clip_polygon_svg=dual_layout.clip_polygon_svg,
            cx_svg=_DUAL_LOCATION_WIFI_CENTER_SVG[0],
            cy_svg=_DUAL_LOCATION_WIFI_CENTER_SVG[1],
            fail_text_xy_svg=(
                _DUAL_LOCATION_WIFI_CENTER_SVG[0],
                _DUAL_LOCATION_WIFI_CENTER_SVG[1] - 18.0,
            ),
            focus_logical="main_dual_location_button",
            picker_row=False,
        )
        _draw_wifi_icon_overlay(bgra, loc_layout, level=default_level, active_bgr=active_bgr)


@dataclass(frozen=True)
class _OnboardingSearchArcSpec:
    """Single clipped ring arc from search-icon art (box columns + onboarding)."""

    cx_svg: float
    cy_svg: float
    radius_svg: float
    stroke_svg: float
    clip_corners_svg: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class _BoxSearchArcOverlay:
    """Idle box2/box3 search arcs redrawn after rasterize (PyMuPDF drops clip-path)."""

    specs: tuple[_OnboardingSearchArcSpec, ...]
    color_bgr: tuple[int, int, int]


@dataclass(frozen=True)
class _StarMaskedCircleSpec:
    """Circle stroke clipped by a hex/star polygon from the SVG (search + pigeon logo)."""

    mask_polygon_svg: tuple[tuple[float, float], ...]
    cx_svg: float
    cy_svg: float
    radius_svg: float
    stroke_svg: float
    default_stroke_hex: str
    focus_button: str | None = None
    circle_el_id: int | None = None


def _parse_svg_points(raw: str) -> tuple[tuple[float, float], ...]:
    nums = [float(x) for x in re.split(r"[\s,]+", raw.strip()) if x]
    if len(nums) < 6:
        return ()
    return tuple((nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2))


def _circle_stroke_from_element(el: ET.Element) -> tuple[float, float, float, float, str]:
    cx = float(el.get("cx") or 0.0)
    cy = float(el.get("cy") or 0.0)
    radius = float(el.get("r") or 0.0)
    _, stroke = _iter_style_fill_stroke(el)
    style = el.get("style") or ""
    sw_m = re.search(r"stroke-width\s*:\s*([-\d.]+)", style, re.IGNORECASE)
    if sw_m:
        stroke_w = float(sw_m.group(1))
    else:
        try:
            stroke_w = float(el.get("stroke-width") or 1.0)
        except ValueError:
            stroke_w = 1.0
    stroke_hex = stroke if stroke and stroke.startswith("#") else "#202020"
    return cx, cy, radius, stroke_w, stroke_hex


def _ancestor_search_icon(el: ET.Element, parents: dict[ET.Element, ET.Element]) -> ET.Element | None:
    cur: ET.Element | None = el
    while cur is not None:
        logical = _normalize_logical(cur.get("id") or "")
        if logical.endswith("_search_icon"):
            return cur
        cur = parents.get(cur)
    return None


def _box_focus_button(el: ET.Element, parents: dict[ET.Element, ET.Element]) -> str | None:
    cur: ET.Element | None = el
    while cur is not None:
        logical = _normalize_logical(cur.get("id") or "")
        for box in ("main_box1", "main_box2", "main_box3"):
            if logical == box:
                return f"{box}_button"
            if logical.startswith(f"{box}_"):
                if (
                    logical.startswith(f"{box}_search_icon")
                    or logical.startswith(f"{box}_search_results")
                    or logical.startswith(f"{box}_container")
                    or logical == f"{box}_add_search_icon"
                ):
                    break
                return f"{box}_button"
        cur = parents.get(cur)
    return None


def _discover_star_masked_circles(root: ET.Element) -> list[_StarMaskedCircleSpec]:
    """Pair pigeon-logo hex clips with circle strokes (search spinners use a separate path)."""
    parents = _parent_map(root)
    specs: list[_StarMaskedCircleSpec] = []

    for el in root.iter():
        logical = _normalize_logical(el.get("id") or "")
        if not logical.endswith("_pigeon_logo_icon"):
            continue
        if _is_subtree_hidden(el, parents):
            continue
        hex_pts: tuple[tuple[float, float], ...] | None = None
        circles: list[ET.Element] = []
        for sub in el.iter():
            if sub.tag.endswith("polygon") and sub.get("points"):
                pts = _parse_svg_points(sub.get("points") or "")
                if len(pts) == 6:
                    hex_pts = pts
            if sub.tag.endswith("circle") and sub.get("cx") and sub.get("r"):
                fill, stroke = _iter_style_fill_stroke(sub)
                if stroke in ("none", "transparent") and fill in ("none", "transparent"):
                    continue
                circles.append(sub)
        if hex_pts is None or not circles:
            continue
        focus_button = _box_focus_button(el, parents)
        for circle_el in circles:
            cx, cy, radius, stroke_w, stroke_hex = _circle_stroke_from_element(circle_el)
            specs.append(
                _StarMaskedCircleSpec(
                    mask_polygon_svg=hex_pts,
                    cx_svg=cx,
                    cy_svg=cy,
                    radius_svg=radius,
                    stroke_svg=stroke_w,
                    default_stroke_hex=stroke_hex,
                    focus_button=focus_button,
                    circle_el_id=id(circle_el),
                )
            )
    return specs


def _hide_star_masked_svg_circles(root: ET.Element, specs: list[_StarMaskedCircleSpec]) -> None:
    """Hide circle strokes replaced by star/hex clip overlays.

    Prefer live element ids from this render's discover pass. Also hide every
    stroked circle under ``*_pigeon_logo_icon`` when any star specs exist for
    that focus button, so a stale/cross-tree id never leaves unclipped rings.
    """
    hide_ids = {spec.circle_el_id for spec in specs if spec.circle_el_id is not None}
    focus_buttons = {spec.focus_button for spec in specs if spec.focus_button}
    for el in root.iter():
        if el.tag.endswith("circle") and id(el) in hide_ids:
            _set_visible(el, False)
    if not specs:
        return
    parents = _parent_map(root)
    for el in root.iter():
        logical = _normalize_logical(el.get("id") or "")
        if not logical.endswith("_pigeon_logo_icon"):
            continue
        focus = _box_focus_button(el, parents)
        if focus_buttons and focus not in focus_buttons:
            continue
        for sub in el.iter():
            if not sub.tag.endswith("circle"):
                continue
            fill, stroke = _iter_style_fill_stroke(sub)
            if stroke in ("none", "transparent") and fill in ("none", "transparent"):
                continue
            _set_visible(sub, False)


def _hide_box_search_animation_layers(root: ET.Element, box_num: int) -> None:
    """Force-hide search spinner art for a column (SVG vectors + group)."""
    search_icon = _find_box_column_search_icon(root, box_num)
    if search_icon is not None:
        _set_visible(search_icon, False)
        _hide_box_search_icon_vectors(search_icon)
    # Belt-and-suspenders: hide any leftover search triangle/ellipse under this box.
    prefix = f"main_box{box_num}_search_"
    for el in root.iter():
        logical = _normalize_logical(el.get("id") or "")
        if not logical.startswith(prefix):
            continue
        if "results" in logical:
            continue
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("circle", "polygon", "g") or "triangle" in logical or "eplipse" in logical or "ellipse" in logical:
            _set_visible(el, False)


def _stroke_bgr_for_star_spec(
    spec: _StarMaskedCircleSpec,
    *,
    state: MainSettingsState,
    focused_logical: str,
) -> tuple[int, int, int]:
    theme = state.theme
    if spec.focus_button and len(spec.mask_polygon_svg) == 6:
        m = re.match(r"main_box([23])_button", spec.focus_button)
        if m is not None:
            panel = state._box_panel(int(m.group(1)))
            if not panel.scanning and not panel.active:
                return _hex_to_bgr(theme.ui or COLOR_UI_DEFAULT)
    if spec.focus_button:
        m = re.match(r"main_box([23])_button", spec.focus_button)
        if m is not None:
            panel = state._box_panel(int(m.group(1)))
            if panel.scanning or panel.active:
                return _hex_to_bgr(theme.selected)
        selected = focused_logical == spec.focus_button
        contrast = theme.selected if selected else theme.deselected
        return _hex_to_bgr(contrast)
    return _hex_to_bgr(spec.default_stroke_hex)


def _draw_star_masked_circle_stroke(
    bgra: np.ndarray,
    spec: _StarMaskedCircleSpec,
    *,
    color_bgr: tuple[int, int, int],
) -> None:
    cx, cy = _svg_to_px(spec.cx_svg, spec.cy_svg)
    radius = _svg_radius_to_px(spec.radius_svg)
    stroke = max(1, int(round(_svg_scale(spec.stroke_svg))))
    clip_pts = np.array(
        [_svg_to_px(x, y) for x, y in spec.mask_polygon_svg],
        dtype=np.int32,
    )
    clip_mask = np.zeros(bgra.shape[:2], dtype=np.uint8)
    cv2.fillPoly(clip_mask, [clip_pts], 255)
    ring_mask = np.zeros(bgra.shape[:2], dtype=np.uint8)
    cv2.circle(ring_mask, (cx, cy), radius, 255, stroke, lineType=cv2.LINE_AA)
    ring_mask = cv2.bitwise_and(ring_mask, clip_mask)
    _composite_stroke_mask(bgra, ring_mask, color_bgr)


def _draw_star_masked_circle_overlays(
    bgra: np.ndarray,
    state: MainSettingsState,
    specs: list[_StarMaskedCircleSpec],
    *,
    focused_logical: str,
) -> None:
    if state.keyboard_open or state.manual_device_entry is not None:
        return
    for spec in specs:
        if spec.focus_button:
            m = re.match(r"main_box([23])_button", spec.focus_button)
            if m is not None:
                panel = state._box_panel(int(m.group(1)))
                if panel.scanning or panel.results_locked:
                    continue
        color = _stroke_bgr_for_star_spec(spec, state=state, focused_logical=focused_logical)
        _draw_star_masked_circle_stroke(bgra, spec, color_bgr=color)


def _parse_svg_matrix(transform: str | None) -> tuple[float, float, float, float, float, float] | None:
    if not transform:
        return None
    m = _MATRIX_RE.search(transform)
    if not m:
        return None
    return tuple(float(m.group(i)) for i in range(1, 7))


def _discover_box_search_triangle_specs(
    root: ET.Element,
    box_num: int,
) -> tuple[tuple[tuple[float, float], ...], ...]:
    search_icon = _find_box_column_search_icon(root, box_num)
    if search_icon is None:
        return ()
    specs: list[tuple[tuple[float, float], ...]] = []
    for el in search_icon.iter():
        if not el.tag.endswith("polygon"):
            continue
        logical = _normalize_logical(el.get("id") or "")
        if "triangle" not in logical:
            continue
        pts = _parse_svg_points(el.get("points") or "")
        if pts:
            specs.append(pts)
    return tuple(specs)


def _draw_star_spec_on_patch(
    patch: np.ndarray,
    spec: _StarMaskedCircleSpec,
    *,
    origin_x0: int,
    origin_y0: int,
    color_bgr: tuple[int, int, int],
) -> None:
    cx, cy = _svg_to_px(spec.cx_svg, spec.cy_svg)
    cx -= origin_x0
    cy -= origin_y0
    radius = _svg_radius_to_px(spec.radius_svg)
    stroke = max(1, int(round(_svg_scale(spec.stroke_svg))))
    clip_pts = np.array(
        [(_svg_to_px(x, y)[0] - origin_x0, _svg_to_px(x, y)[1] - origin_y0) for x, y in spec.mask_polygon_svg],
        dtype=np.int32,
    )
    clip_mask = np.zeros(patch.shape[:2], dtype=np.uint8)
    cv2.fillPoly(clip_mask, [clip_pts], 255)
    ring_mask = np.zeros(patch.shape[:2], dtype=np.uint8)
    cv2.circle(ring_mask, (cx, cy), radius, 255, stroke, lineType=cv2.LINE_AA)
    ring_mask = cv2.bitwise_and(ring_mask, clip_mask)
    _composite_stroke_mask(patch, ring_mask, color_bgr)


def _draw_triangle_specs_on_patch(
    patch: np.ndarray,
    specs: tuple[tuple[tuple[float, float], ...], ...],
    *,
    origin_x0: int,
    origin_y0: int,
    color_bgr: tuple[int, int, int],
) -> None:
    for pts in specs:
        px_pts = np.array(
            [(_svg_to_px(x, y)[0] - origin_x0, _svg_to_px(x, y)[1] - origin_y0) for x, y in pts],
            dtype=np.int32,
        )
        mask = np.zeros(patch.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [px_pts], 255)
        _composite_stroke_mask(patch, mask, color_bgr)


def _box_search_star_specs(
    specs: list[_StarMaskedCircleSpec],
    box_num: int,
) -> list[_StarMaskedCircleSpec]:
    want = f"main_box{box_num}_button"
    return [spec for spec in specs if spec.focus_button == want]


def _hide_box_search_icon_vectors(search_icon: ET.Element | None) -> None:
    """Hide raw SVG vectors; spinner/search art is drawn as overlays."""
    if search_icon is None:
        return
    for el in search_icon.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("circle", "polygon", "path"):
            _set_visible(el, False)
