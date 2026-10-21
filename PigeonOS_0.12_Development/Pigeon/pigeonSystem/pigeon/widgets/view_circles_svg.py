"""
SVG element helpers and clock face painting for the now-playing widgets.

Layer lookup / detach / remove by ``data-name`` key, and the clock-specific SVG edits:
tick fills, seconds wedges and rings, accent fills and the standalone clock tick
groups. Pure ``ElementTree`` manipulation driven by an ``_NpTheme``; rasterizing and
compositing stay in ``view_circles``.

``pigeon.widgets.view_circles`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import numpy as np

from pigeon.np_layout import (
    CLOCK_LOCAL_CX,
    CLOCK_LOCAL_CY,
    CLOCK_VIEW_H,
    CLOCK_VIEW_W,
    VOLUME_LOCAL_CX,
    VOLUME_LOCAL_CY,
    design_xy_from_local,
)
from pigeon.widgets.view_circles_theme import (
    _CLOCK_TICK_OFF_HEX,
    _COLOR_CENTER_BLACK_HEX,
    _NpTheme,
    _darken_hex,
    _visible_on_dark_hex,
    _zone_spec,
    np_theme_from_settings,
)


SVG_NS = "http://www.w3.org/2000/svg"


_CLOCK_EXTERIOR_ACCENT_R = 199.0


_CLOCK_MIDDLE_ACCENT_R = 164.45


_CLOCK_INTERIOR_ACCENT_R = 105.54


_CLOCK_MINUTE_TICK_OPACITY = 0.7  # 30% transparent


# Hour face layers: wall-clock hour → SVG data-name.
_HOUR_FACE_NAMES: dict[int, str] = {
    1: "hours_05_01",
    2: "hours_10_02",
    3: "hours_15_03",
    4: "hours_20_04",
    5: "hours_25_05",
    6: "hours_30_06",
    7: "hours_35_07",
    8: "hours_40_08",
    9: "hours_45_09",
    10: "hours_50_10",
    11: "hours_55_11",
    12: "hours_60_12",
}


def _layer_key(el: ET.Element) -> str:
    """Prefer data-name; strip Illustrator ``-N`` id suffixes; normalize spaces."""
    dn = (el.get("data-name") or "").strip()
    raw = dn if dn else (el.get("id") or "").strip()
    if not dn and raw:
        raw = re.sub(r"-\d+$", "", raw)
    return re.sub(r"\s+", "_", raw)


def _find_by_id(root: ET.Element, layer_id: str) -> ET.Element | None:
    for el in root.iter():
        if el.get("id") == layer_id:
            return el
    return None


def _find_by_key(scope: ET.Element, name: str) -> ET.Element | None:
    want = re.sub(r"\s+", "_", str(name or "").strip())
    if not want:
        return None
    for el in scope.iter():
        if _layer_key(el) == want or el.get("id") == want:
            return el
    return None


def _find_direct_child_by_key(parent: ET.Element, name: str) -> ET.Element | None:
    want = re.sub(r"\s+", "_", str(name or "").strip())
    for el in list(parent):
        if _layer_key(el) == want or el.get("id") == want:
            return el
    return None


def _detach_element(root: ET.Element, el: ET.Element | None) -> bool:
    """Remove ``el`` from its parent. PyMuPDF ignores ``display:none`` on SVG groups."""
    if el is None:
        return False
    for parent in root.iter():
        for child in list(parent):
            if child is el:
                parent.remove(child)
                return True
    return False


def _remove_element_by_id(root: ET.Element, element_id: str) -> None:
    for parent in root.iter():
        for child in list(parent):
            if child.get("id") == element_id:
                parent.remove(child)
                return


def _remove_by_key(root: ET.Element, name: str) -> bool:
    """Remove every element whose canonical key or id matches ``name``."""
    want = re.sub(r"\s+", "_", str(name or "").strip())
    if not want:
        return False
    removed = False
    # Restart scan after each removal — tree mutates under iter().
    while True:
        hit = None
        for el in root.iter():
            if _layer_key(el) == want or el.get("id") == want:
                hit = el
                break
        if hit is None:
            break
        if not _detach_element(root, hit):
            break
        removed = True
    return removed


def _clock_group_for_zone(root: ET.Element, zone: int) -> ET.Element | None:
    return _find_by_key(root, f"zone{zone}_clock_group")


def _seconds_group(clock_group: ET.Element) -> ET.Element | None:
    for el in list(clock_group):
        key = _layer_key(el)
        if "seconds" in key and "group" in key:
            return el
    return _find_by_key(clock_group, "zone1_clock_seconds_group")


def _minutes_group(clock_group: ET.Element) -> ET.Element | None:
    for el in list(clock_group):
        key = _layer_key(el)
        if "minutes" in key and "group" in key:
            return el
    return None


def _hours_group(clock_group: ET.Element) -> ET.Element | None:
    for el in list(clock_group):
        key = _layer_key(el)
        if "hours" in key and "group" in key:
            return el
    return None


def _iter_named_children(group: ET.Element | None):
    if group is None:
        return
    for el in list(group):
        yield el, _layer_key(el)


def _fix_seconds_08_label(seconds_group: ET.Element | None) -> None:
    """SVG ships a mislabeled duplicate ``seconds_60`` where ``seconds_08`` should be."""
    if seconds_group is None:
        return
    if _find_direct_child_by_key(seconds_group, "seconds_08") is not None:
        return
    kids = list(seconds_group)
    idx09 = idx07 = None
    for i, child in enumerate(kids):
        key = _layer_key(child)
        if key == "seconds_09":
            idx09 = i
        elif key == "seconds_07":
            idx07 = i
    if idx09 is None or idx07 is None:
        return
    lo, hi = (idx09, idx07) if idx09 < idx07 else (idx07, idx09)
    for child in kids[lo + 1 : hi]:
        if _layer_key(child) == "seconds_60":
            child.set("data-name", "seconds_08")
            return


def _resolve_seconds_el(seconds_group: ET.Element | None, second_index: int) -> ET.Element | None:
    """``second_index`` in 1..60."""
    if seconds_group is None:
        return None
    _fix_seconds_08_label(seconds_group)
    name = f"seconds_{second_index:02d}"
    el = _find_direct_child_by_key(seconds_group, name)
    if el is not None:
        return el
    return _find_by_key(seconds_group, name)


def _resolve_hour_face_el(hours_group: ET.Element | None, hour_1_12: int) -> ET.Element | None:
    if hours_group is None:
        return None
    name = _HOUR_FACE_NAMES.get(int(hour_1_12))
    if not name:
        return None
    el = _find_direct_child_by_key(hours_group, name)
    if el is not None:
        return el
    return _find_by_key(hours_group, name)


def _zone_clock_center(zone: int) -> tuple[float, float]:
    return design_xy_from_local(_zone_spec(zone), CLOCK_LOCAL_CX, CLOCK_LOCAL_CY)


def _zone_volume_center(zone: int) -> tuple[float, float]:
    return design_xy_from_local(_zone_spec(zone), VOLUME_LOCAL_CX, VOLUME_LOCAL_CY)


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _set_tick_paint(
    el: ET.Element, *, color: str, opacity: float | None = None
) -> None:
    """Recolor path fills/strokes under ``el``."""
    op: str | None = None
    if opacity is not None:
        op = f"{max(0.0, min(1.0, float(opacity))):.3g}"
        el.set("opacity", op)
    elif "opacity" in el.attrib:
        del el.attrib["opacity"]
    for node in el.iter():
        tag = _local_tag(node.tag)
        if tag not in ("path", "polygon", "polyline", "circle", "ellipse", "rect"):
            continue
        if op is not None:
            node.set("opacity", op)
        elif "opacity" in node.attrib:
            del node.attrib["opacity"]
        fill = (node.get("fill") or "").strip().lower()
        stroke = (node.get("stroke") or "").strip().lower()
        if fill and fill != "none":
            node.set("fill", color)
        if stroke and stroke != "none":
            node.set("stroke", color)
        # Bare paths sometimes omit fill (Illustrator default = black); force paint.
        if not fill and not stroke:
            node.set("fill", color)


def _raise_in_group(group: ET.Element | None, el: ET.Element | None) -> None:
    """Move ``el`` to the end of ``group`` so it paints above siblings."""
    if group is None or el is None:
        return
    kids = list(group)
    if el not in kids:
        return
    group.remove(el)
    group.append(el)


def _accent_circle_r(clock: ET.Element, zone: int, kind: str, default: float) -> float:
    el = _find_by_key(clock, f"zone{zone}_clock_{kind}_accent")
    if el is None:
        return default
    try:
        return float(el.get("r") or default)
    except (TypeError, ValueError):
        return default


def _place_in_group(group: ET.Element | None, el: ET.Element | None, index: int) -> None:
    """Move ``el`` to ``index`` within ``group`` (paint order)."""
    if group is None or el is None:
        return
    kids = list(group)
    if el not in kids:
        return
    group.remove(el)
    group.insert(max(0, min(int(index), len(list(group)))), el)


def _seconds_wedge_path_d(cx: float, cy: float, r: float, fraction: float) -> str | None:
    """SVG pie path from 12 o'clock, clockwise, covering ``fraction`` of the disc.

    Returns None when ``fraction`` is full (caller should use a solid circle fill).
    """
    frac = max(0.0, min(1.0, float(fraction)))
    if frac <= 1e-6:
        return ""
    if frac >= 0.999:
        return None
    sweep = 2.0 * math.pi * frac
    x1 = cx
    y1 = cy - r
    x2 = cx + r * math.sin(sweep)
    y2 = cy - r * math.cos(sweep)
    large = 1 if frac > 0.5 else 0
    return (
        f"M {cx:.4f},{cy:.4f} L {x1:.4f},{y1:.4f} "
        f"A {r:.4f},{r:.4f} 0 {large},1 {x2:.4f},{y2:.4f} Z"
    )


def _svg_parent(root: ET.Element, el: ET.Element) -> ET.Element | None:
    for parent in root.iter():
        if el in list(parent):
            return parent
    return None


def _circle_cx_cy_r(
    el: ET.Element | None,
    *,
    default_cx: float,
    default_cy: float,
    default_r: float,
) -> tuple[float, float, float]:
    if el is None:
        return float(default_cx), float(default_cy), float(default_r)
    try:
        cx = float(el.get("cx") or default_cx)
        cy = float(el.get("cy") or default_cy)
        r = float(el.get("r") or default_r)
    except (TypeError, ValueError):
        return float(default_cx), float(default_cy), float(default_r)
    return cx, cy, r


def _evenodd_ring_d(cx: float, cy: float, r_outer: float, r_inner: float) -> str:
    """Closed outer circle minus inner circle (evenodd)."""
    ro = max(0.5, float(r_outer))
    ri = max(0.0, min(float(r_inner), ro - 0.5))
    return (
        f"M {cx:.4f},{cy - ro:.4f} "
        f"A {ro:.4f},{ro:.4f} 0 1,1 {cx:.4f},{cy + ro:.4f} "
        f"A {ro:.4f},{ro:.4f} 0 1,1 {cx:.4f},{cy - ro:.4f} Z "
        f"M {cx:.4f},{cy - ri:.4f} "
        f"A {ri:.4f},{ri:.4f} 0 1,0 {cx:.4f},{cy + ri:.4f} "
        f"A {ri:.4f},{ri:.4f} 0 1,0 {cx:.4f},{cy - ri:.4f} Z"
    )


def _annulus_wedge_path_d(
    cx: float, cy: float, r_outer: float, r_inner: float, fraction: float
) -> str | None:
    """Outer-ring sector from 12 o'clock clockwise. None = full ring."""
    frac = max(0.0, min(1.0, float(fraction)))
    if frac <= 1e-6:
        return ""
    if frac >= 0.999:
        return None
    ro = max(0.5, float(r_outer))
    ri = max(0.0, min(float(r_inner), ro - 0.5))
    sweep = 2.0 * math.pi * frac
    large = 1 if frac > 0.5 else 0
    x1 = cx
    y1 = cy - ro
    x2 = cx + ro * math.sin(sweep)
    y2 = cy - ro * math.cos(sweep)
    x3 = cx + ri * math.sin(sweep)
    y3 = cy - ri * math.cos(sweep)
    x4 = cx
    y4 = cy - ri
    return (
        f"M {x1:.4f},{y1:.4f} "
        f"A {ro:.4f},{ro:.4f} 0 {large},1 {x2:.4f},{y2:.4f} "
        f"L {x3:.4f},{y3:.4f} "
        f"A {ri:.4f},{ri:.4f} 0 {large},0 {x4:.4f},{y4:.4f} Z"
    )


def _clock_accent_key(zone: int | None, kind: str) -> str:
    if zone is None:
        return f"clock_{kind}_accent"
    return f"zone{int(zone)}_clock_{kind}_accent"


def _apply_clock_black_rings(clock: ET.Element, *, zone: int | None = None) -> None:
    """Black outer ring (exterior minus middle hole) + black interior disc.

    Middle stays unfilled so the backdrop shows through that band.
    """
    exterior = _find_by_key(clock, _clock_accent_key(zone, "exterior"))
    middle = _find_by_key(clock, _clock_accent_key(zone, "middle"))
    interior = _find_by_key(clock, _clock_accent_key(zone, "interior"))
    ring_id = (
        "clock_outer_ring_fill"
        if zone is None
        else f"zone{int(zone)}_clock_outer_band_fill"
    )
    disc_id = (
        "clock_interior_disc_fill"
        if zone is None
        else f"zone{int(zone)}_clock_disc_fill"
    )
    _remove_by_key(clock, ring_id)
    _remove_by_key(clock, disc_id)
    if exterior is not None:
        exterior.set("fill", "none")
    if middle is not None:
        middle.set("fill", "none")
    if interior is not None:
        interior.set("fill", "none")
    host = _svg_parent(clock, exterior) if exterior is not None else clock
    if host is None:
        host = clock
    cx, cy, r_out = _circle_cx_cy_r(
        exterior,
        default_cx=CLOCK_LOCAL_CX,
        default_cy=CLOCK_LOCAL_CY,
        default_r=_CLOCK_EXTERIOR_ACCENT_R,
    )
    _mx, _my, r_mid = _circle_cx_cy_r(
        middle,
        default_cx=cx,
        default_cy=cy,
        default_r=_CLOCK_MIDDLE_ACCENT_R,
    )
    icx, icy, r_in = _circle_cx_cy_r(
        interior,
        default_cx=cx,
        default_cy=cy,
        default_r=_CLOCK_INTERIOR_ACCENT_R,
    )
    ring = ET.Element(f"{{{SVG_NS}}}path")
    ring.set("id", ring_id)
    ring.set("data-name", ring_id)
    ring.set("d", _evenodd_ring_d(cx, cy, r_out, r_mid))
    ring.set("fill", _COLOR_CENTER_BLACK_HEX)
    ring.set("fill-rule", "evenodd")
    host.insert(0, ring)
    disc = ET.Element(f"{{{SVG_NS}}}circle")
    disc.set("id", disc_id)
    disc.set("data-name", disc_id)
    disc.set("cx", f"{icx:.4f}")
    disc.set("cy", f"{icy:.4f}")
    disc.set("r", f"{r_in:.4f}")
    disc.set("fill", _COLOR_CENTER_BLACK_HEX)
    host.insert(1, disc)


def _punch_clock_open_ring_white(
    bgra: np.ndarray, *, view_h: float = CLOCK_VIEW_H
) -> np.ndarray:
    """Knock out trapped page-white in the middle (open) clock band."""
    if bgra is None or bgra.size == 0 or bgra.ndim < 3 or bgra.shape[2] < 4:
        return bgra
    h, w = int(bgra.shape[0]), int(bgra.shape[1])
    sx = float(w) / CLOCK_VIEW_W
    sy = float(h) / float(view_h)
    cx = CLOCK_LOCAL_CX * sx
    cy = CLOCK_LOCAL_CY * sy
    yy, xx = np.ogrid[:h, :w]
    dx = (xx - cx) / max(sx, 1e-6)
    dy = (yy - cy) / max(sy, 1e-6)
    d = np.sqrt(dx * dx + dy * dy)
    band = (d > (_CLOCK_INTERIOR_ACCENT_R + 3.0)) & (
        d < (_CLOCK_MIDDLE_ACCENT_R - 3.0)
    )
    rgb = bgra[:, :, :3]
    white = (
        (rgb[:, :, 0] >= 252)
        & (rgb[:, :, 1] >= 252)
        & (rgb[:, :, 2] >= 252)
    )
    bgra[band & white, 3] = 0
    return bgra


def _apply_exterior_seconds_fill(
    clock: ET.Element,
    zone: int | None,
    *,
    sec_idx: int,
    theme: _NpTheme | None = None,
) -> None:
    """Accent wedge on the outer black ring only (middle band stays open)."""
    th = theme or np_theme_from_settings()
    exterior = _find_by_key(clock, _clock_accent_key(zone, "exterior"))
    middle = _find_by_key(clock, _clock_accent_key(zone, "middle"))
    fill_name = (
        "clock_exterior_seconds_fill"
        if zone is None
        else f"zone{int(zone)}_clock_exterior_seconds_fill"
    )
    _remove_by_key(clock, fill_name)
    if exterior is None:
        return
    if zone is None:
        default_cx, default_cy = CLOCK_LOCAL_CX, CLOCK_LOCAL_CY
    else:
        default_cx, default_cy = _zone_clock_center(int(zone))
    cx, cy, r_out = _circle_cx_cy_r(
        exterior,
        default_cx=default_cx,
        default_cy=default_cy,
        default_r=_CLOCK_EXTERIOR_ACCENT_R,
    )
    _mx, _my, r_mid = _circle_cx_cy_r(
        middle,
        default_cx=cx,
        default_cy=cy,
        default_r=_CLOCK_MIDDLE_ACCENT_R,
    )
    idx = max(1, min(60, int(sec_idx)))
    frac = idx / 60.0
    d = _annulus_wedge_path_d(cx, cy, r_out, r_mid, frac)
    if d is None:
        d = _evenodd_ring_d(cx, cy, r_out, r_mid)
    if not d:
        return
    wedge = ET.Element(f"{{{SVG_NS}}}path")
    wedge.set("id", fill_name)
    wedge.set("data-name", fill_name)
    wedge.set("d", d)
    # A white accent (the default) reads as dark gray on the clock, not bright white.
    accent = str(th.accent_hex or "").strip().lower()
    wedge.set("fill", _CLOCK_TICK_OFF_HEX if accent in ("#fff", "#ffffff", "white") else th.accent_hex)
    wedge.set("fill-rule", "evenodd")
    host = _svg_parent(clock, exterior)
    if host is None:
        host = clock
    # Sit above the black outer ring, under tick groups.
    host.insert(2, wedge)


def _apply_clock_accent_fills(root: ET.Element, *, theme: _NpTheme | None = None) -> None:
    """Black outer ring, open middle band, black interior disc."""
    del theme
    for zone in (1, 2, 3):
        clock = _clock_group_for_zone(root, zone)
        if clock is None:
            continue
        for child in list(clock):
            key = _layer_key(child)
            if key in (
                f"zone{zone}_clock_disc_fill",
                f"zone{zone}_clock_outer_band_fill",
                f"zone{zone}_clock_exterior_seconds_fill",
            ):
                clock.remove(child)
        _apply_clock_black_rings(clock, zone=zone)


def _seconds_alternate_colors(
    now: datetime, *, ui_hex: str, white_hex: str = "#FFFFFF"
) -> tuple[str, str, int]:
    """Incoming color, outgoing color, and how many ticks have flipped.

    The seconds ring is never empty. Even minutes start fully white and paint
    UI-color ticks one per second. Odd minutes start fully UI-color and paint
    white ticks one per second. At ``:00`` all 60 ticks are the outgoing color
    (the color that finished filling on the previous minute).
    """
    ui = str(ui_hex or "#FFFFFF")
    white = str(white_hex or "#FFFFFF")
    if int(now.minute) % 2 == 0:
        incoming, outgoing = ui, white
    else:
        incoming, outgoing = white, ui
    return incoming, outgoing, max(0, min(59, int(now.second)))


def _paint_seconds_ticks_alternating(
    seconds_g: ET.Element | None,
    now: datetime,
    *,
    ui_hex: str,
    white_hex: str = "#FFFFFF",
) -> None:
    """Keep every second tick box filled; flip white ↔ UI one tick per second."""
    if seconds_g is None:
        return
    _fix_seconds_08_label(seconds_g)
    incoming, outgoing, incoming_count = _seconds_alternate_colors(
        now, ui_hex=ui_hex, white_hex=white_hex
    )
    current: ET.Element | None = None
    for el, key in list(_iter_named_children(seconds_g)):
        if not key.startswith("seconds_"):
            continue
        m = re.fullmatch(r"seconds_(\d{2})", key)
        if not m:
            continue
        idx = int(m.group(1))
        if not (1 <= idx <= 60):
            continue
        _set_tick_paint(el, color=incoming if idx <= incoming_count else outgoing)
        if incoming_count > 0 and idx == incoming_count:
            current = el
        elif incoming_count == 0 and idx == 60:
            current = el
    _raise_in_group(seconds_g, current)


def _apply_clock_ticks(
    root: ET.Element,
    zone: int,
    now: datetime,
    *,
    theme: _NpTheme | None = None,
) -> None:
    """Drive clock tick layers for the active zone.

    Hours: original geometry; only the current face layer is kept.
    Minutes: keep layers 1..current (0 → 60); prior ticks dim UI,
    current full UI and raised above siblings.
    Seconds: every tick box stays filled and alternates white ↔ UI color.
    """
    th = theme or np_theme_from_settings()
    clock = _clock_group_for_zone(root, zone)
    if clock is None:
        return
    hours_g = _hours_group(clock)
    minutes_g = _minutes_group(clock)
    seconds_g = _seconds_group(clock)
    _fix_seconds_08_label(seconds_g)

    h12 = now.hour % 12
    if h12 == 0:
        h12 = 12
    minute = int(now.minute)
    second = int(now.second)
    # Ring index: 0 → layer 60; 1..59 → matching index.
    min_idx = 60 if minute == 0 else minute
    sec_idx = 60 if second == 0 else second

    # Exterior: button base + accent sector under seconds 1..current.
    _apply_exterior_seconds_fill(clock, zone, sec_idx=sec_idx, theme=th)

    # Hours: only the matching face layer (original SVG shape), painted UI.
    face_name = _HOUR_FACE_NAMES.get(h12, "")
    for el, key in list(_iter_named_children(hours_g)):
        if not key.startswith("hours_"):
            continue
        # hours_61 maps to missing hours_51 — never a face hour for display.
        if key != face_name:
            _detach_element(root, el)
            continue
        _set_tick_paint(el, color=th.tick_active)

    # Minutes: layers 1..current; dim priors, highlight current.
    current_min: ET.Element | None = None
    for el, key in list(_iter_named_children(minutes_g)):
        m = re.fullmatch(r"minutes_(\d{2})", key)
        if not m:
            continue
        idx = int(m.group(1))
        if not (1 <= idx <= min_idx):
            _detach_element(root, el)
            continue
        if idx == min_idx:
            current_min = el
            _set_tick_paint(el, color=th.tick_active, opacity=_CLOCK_MINUTE_TICK_OPACITY)
        else:
            _set_tick_paint(el, color=th.tick_dim, opacity=_CLOCK_MINUTE_TICK_OPACITY)
    _raise_in_group(minutes_g, current_min)

    _paint_seconds_ticks_alternating(
        seconds_g,
        now,
        ui_hex=_visible_on_dark_hex(th.tick_active),
        white_hex=_CLOCK_TICK_OFF_HEX,
    )


_FORCE_ANALOG_CLOCK = False


def _clock_widget_is_analog() -> bool:
    if _FORCE_ANALOG_CLOCK:
        return True
    try:
        from pigeon.widgets.options_settings import clock_widget_analog

        return bool(clock_widget_analog())
    except Exception:
        return False


def _clock_include_digital_time() -> bool:
    """Analog uses the radial face; digital HH:MM only belongs on the disc hub."""
    return not _clock_widget_is_analog()


def _raise_clock_tick_groups(root: ET.Element) -> None:
    """Hours / minutes / seconds must sit above the black rings."""
    for key in (
        "clock_hours_group",
        "clock_minutes_group",
        "clock_seconds_group",
    ):
        el = _find_by_key(root, key)
        parent = _svg_parent(root, el) if el is not None else None
        if el is None or parent is None:
            continue
        parent.remove(el)
        parent.append(el)


def _detach_clock_tick_groups(root: ET.Element, *, zone: int | None = None) -> None:
    if zone is None:
        keys = ("clock_hours_group", "clock_minutes_group", "clock_seconds_group")
    else:
        z = int(zone)
        keys = (
            f"zone{z}_clock_hours_group",
            f"zone{z}_clock_minutes_group",
            f"zone{z}_clock_seconds_group",
        )
    for key in keys:
        el = _find_by_key(root, key)
        if el is not None:
            _detach_element(root, el)


def _apply_standalone_clock_ticks(
    root: ET.Element, now: datetime, *, theme: _NpTheme
) -> None:
    """Drive the 1280×800 clock widget (no zone prefix)."""
    _apply_clock_black_rings(root, zone=None)
    second = int(now.second)
    sec_idx = 60 if second == 0 else second
    _apply_exterior_seconds_fill(root, None, sec_idx=sec_idx, theme=theme)
    hours_g = _find_by_key(root, "clock_hours_group")
    minutes_g = _find_by_key(root, "clock_minutes_group")
    seconds_g = _find_by_key(root, "clock_seconds_group")
    _fix_seconds_08_label(seconds_g)

    h12 = now.hour % 12
    if h12 == 0:
        h12 = 12
    minute = int(now.minute)
    min_idx = 60 if minute == 0 else minute
    ui = _visible_on_dark_hex(theme.tick_active)
    minute_ui = _darken_hex(ui, factor=_CLOCK_MINUTE_TICK_OPACITY)

    face_name = _HOUR_FACE_NAMES.get(h12, "")
    for el, key in list(_iter_named_children(hours_g)):
        if not key.startswith("hours_"):
            continue
        if key != face_name:
            _detach_element(root, el)
            continue
        _set_tick_paint(el, color=ui)

    current_min: ET.Element | None = None
    for el, key in list(_iter_named_children(minutes_g)):
        m = re.fullmatch(r"minutes_(\d{2})", key)
        if not m:
            continue
        idx = int(m.group(1))
        if not (1 <= idx <= min_idx):
            _detach_element(root, el)
            continue
        # Solid fill in the shade the 70%-opacity ticks used to read as on black.
        _set_tick_paint(el, color=minute_ui)
        if idx == min_idx:
            current_min = el
    _raise_in_group(minutes_g, current_min)

    _paint_seconds_ticks_alternating(
        seconds_g, now, ui_hex=ui, white_hex=_CLOCK_TICK_OFF_HEX
    )
    _raise_clock_tick_groups(root)

    for name in ("clock_digital_text", "day_text", "month_date_text"):
        _clear_text_content(_find_by_key(root, name))
        el = _find_by_key(root, name)
        if el is not None:
            _detach_element(root, el)


def _clear_text_content(el: ET.Element | None) -> None:
    if el is None:
        return
    el.text = None
    for node in el.iter():
        node.text = None
        node.tail = None
