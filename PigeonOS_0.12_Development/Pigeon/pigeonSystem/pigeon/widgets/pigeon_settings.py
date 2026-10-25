"""
Pigeon device settings — ``settings/pigeon/settings_pigeon.svg`` (0.12).

One page, three sections. ``section1`` is the working area: six tiles that are
plain buttons or two-way toggles depending on the menu it shows. ``section2``
and ``section3`` are the big buttons that pick that menu::

    section1 shows   section2   section3
    general          theme      clock        (default on entry)
    theme            general    clock
    clock            theme      general

Activating a big button loads its menu into section1 and turns that button
into the way back to ``general``. Focus order::

    EXIT → the focusable tiles of the open menu → section2 → section3

Tiles that are "TBD" are drawn dim and skipped by focus. The clock, version,
and the wifi / metadata / audio lights are not selectable. Moving focus across
the theme tiles previews that color live; activating one commits it, and
leaving the menu falls back to the committed color.

The HH:MM:SS clock ticks every second, so it is drawn by
:func:`draw_pigeon_settings_clock` on top of the cached page instead of being
baked into it.
"""

from __future__ import annotations

import copy
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from pigeon.design import DESIGN_H, DESIGN_W
from pigeon.settings_layout import SETTINGS_BACKGROUND_SHIFT_Y, SETTINGS_CANVAS_ORIGIN
from pigeon.version import version_string
from pigeon.widgets.settings_svg_text import center_label_on_pill
from pigeon.widgets.main_settings import (
    MainSettingsState,
    _composite_bgra_over_bgra,
    _disable_embedded_settings_background_layers,
    _draw_container_background_bgra,
    _prune_display_none,
    _set_paint,
    _set_text_content,
    _set_visible,
)

# Crop the Illustrator board to the 1280×800 canvas; y follows the settings
# plate nudge so the page sits on the shifted theme background.
_PIGEON_VIEWBOX = (
    SETTINGS_CANVAS_ORIGIN[0],
    SETTINGS_CANVAS_ORIGIN[1] - SETTINGS_BACKGROUND_SHIFT_Y,
    1280.0,
    800.0,
)

_COLOR_WHITE = "#FFFFFF"
_COLOR_BLACK = "#000000"
_COLOR_BUTTON = "#231F20"
_COLOR_STATUS_OK = "#58FF00"
_COLOR_STATUS_BAD = "#FF0000"
# White fills vanish on a white theme, so the white theme borrows grey's.
_COLOR_WELL_ON_WHITE = "#777777"
# "TBD" tiles: same dark tile, greyed-out ink.
_COLOR_TBD_INK = "#6E6E6E"
_COLOR_TBD_WELL = "#3A3A3A"

THEME_KEYS: tuple[str, ...] = ("blue", "green", "yellow", "pink", "red")
VIEWS: tuple[str, ...] = ("general", "theme", "clock")
DEFAULT_VIEW = "general"

# Option numbers (see :mod:`pigeon.widgets.options_settings`).
OPT_TIME = 1
OPT_TEMP = 2
OPT_NP_LAYOUT = 5
OPT_CLOCK_FORMAT = 6
OPT_UI_STYLE = 7


@dataclass(frozen=True)
class Slot:
    """One of section1's six tiles."""

    kind: str  # toggle | button | color | tbd_toggle | tbd_button
    focus_id: str = ""  # "" = not focusable
    label: str = ""  # button text / color key
    choices: tuple[str, str] = ("", "")  # toggle labels, option A on top


_GENERAL_SLOTS: tuple[Slot, ...] = (
    Slot("button", "update", "UPDATE"),
    Slot("button", "reset", "RESET"),
    Slot("button", "restart", "RESTART"),
    Slot("toggle", f"option:{OPT_TEMP}", choices=("°F", "°C")),
    Slot("toggle", f"option:{OPT_NP_LAYOUT}", choices=("ZONE 11", "ZONE 6,3")),
    Slot("tbd_toggle", choices=("TBD", "TBD")),
)
_THEME_SLOTS: tuple[Slot, ...] = tuple(
    Slot("color", f"color:{k}", k) for k in THEME_KEYS
) + (Slot("toggle", f"option:{OPT_UI_STYLE}", choices=("STANDARD", "SIMPLE")),)
_CLOCK_SLOTS: tuple[Slot, ...] = (
    Slot("toggle", f"option:{OPT_TIME}", choices=("12 HR", "24 HR")),
    Slot("button", "zipcode", "ZIP"),
    Slot("button", "timezone", "TIME ZONE"),
    Slot("toggle", f"option:{OPT_CLOCK_FORMAT}", choices=("DIGITAL", "ANALOG")),
    Slot("tbd_button", label="TBD"),
    Slot("tbd_button", label="TBD"),
)
_SLOTS: dict[str, tuple[Slot, ...]] = {
    "general": _GENERAL_SLOTS,
    "theme": _THEME_SLOTS,
    "clock": _CLOCK_SLOTS,
}

# Right edge of the status-light row; the version string right-aligns to it
# so longer versions never run off the plate.
_VERSION_RIGHT_X_SVG = 1795.59

# Clock: glyph baseline and the span it may use, right-aligned (SVG board
# units, drawn 1:1 on the 1280×800 canvas). Locked digit cells run wider than
# the authored proportional "10:06:15".
_CLOCK_LEFT_SVG = 1125.0
_CLOCK_RIGHT_SVG = 1316.0
_CLOCK_BASELINE_SVG = 830.09
_CLOCK_FONT_PX = 60

# Timezone dropdown: a list laid over section2 (the TIME ZONE tile stays visible).
_DROPDOWN_ANCHOR_SVG = (1185.0, 985.0)
_DROPDOWN_ROW_W = 240
_DROPDOWN_ROW_H = 52
_DROPDOWN_ROW_GAP = 6
_DROPDOWN_RADIUS = 18
_DROPDOWN_FONT_PX = 44
_DROPDOWN_MAX_ROWS = 7

# Tile text (SVG board units).
_TOGGLE_LABEL_PX = 22
_BUTTON_LABEL_PX = 27
_CAPTION_PX = 20
_VALUE_PX = 46
_COLOR_DOT_R = 40.0

_SVG_TREE_TEMPLATES: dict[tuple[str, int], ET.Element] = {}
_SVG_TREE_TEMPLATE_MAX = 4
_THEME_BG_CACHE: dict[tuple[str, str, int, int], np.ndarray] = {}
_THEME_BG_CACHE_MAX = 8
_CLIP_LAYER_CACHE: dict[str, np.ndarray] = {}
_CLIP_LAYER_CACHE_MAX = 16


def default_pigeon_settings_svg_path(assets_dir: Path | str | None = None) -> Path:
    env = os.environ.get("PIGEON_PIGEON_SETTINGS_SVG", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    from pigeon.settings_layout import settings_widget_path

    return settings_widget_path("pigeon_page", assets_dir=assets_dir)


# --- views, focus -------------------------------------------------------------


def normalize_view(view: object) -> str:
    v = str(view or "").strip().lower()
    return v if v in VIEWS else DEFAULT_VIEW


def view_slots(view: object) -> tuple[Slot, ...]:
    return _SLOTS[normalize_view(view)]


def pigeon_focus_ring(view: object = DEFAULT_VIEW) -> tuple[str, ...]:
    tiles = tuple(s.focus_id for s in view_slots(view) if s.focus_id)
    return ("exit", *tiles, "section2", "section3")


def section_targets(view: object) -> tuple[str, str]:
    """Menu that (section2, section3) open from ``view``."""
    v = normalize_view(view)
    return ("general" if v == "theme" else "theme", "general" if v == "clock" else "clock")


def view_for_section(view: object, focus_id: str) -> str | None:
    """Menu opened by activating ``section2`` / ``section3``; None for other ids."""
    sec2, sec3 = section_targets(view)
    return {"section2": sec2, "section3": sec3}.get(normalize_pigeon_focus_id(focus_id))


def normalize_pigeon_focus_id(focus_id: str) -> str:
    return str(focus_id or "").strip()


def color_key_for_focus(focus_id: str) -> str | None:
    """UI color key to preview/commit for a ``color:`` focus id; None otherwise."""
    fid = normalize_pigeon_focus_id(focus_id)
    return fid.split(":", 1)[1] if fid.startswith("color:") else None


def option_for_focus(focus_id: str) -> int | None:
    fid = normalize_pigeon_focus_id(focus_id)
    if not fid.startswith("option:"):
        return None
    try:
        return int(fid.split(":", 1)[1])
    except ValueError:
        return None


# --- SVG lookup -------------------------------------------------------------


def _by_id(root: ET.Element | None, *ids: str) -> ET.Element | None:
    """First element whose ``id`` or ``data-name`` matches one of ``ids``."""
    if root is None:
        return None
    want = set(ids)
    for el in root.iter():
        if el.get("id") in want:
            return el
    for el in root.iter():
        if el.get("data-name") in want:
            return el
    return None


def _local(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _sibling_tag(el: ET.Element, name: str) -> str:
    """Tag ``name`` in the same namespace as ``el``."""
    return f"{el.tag.rsplit('}', 1)[0]}}}{name}" if "}" in el.tag else name


def _paint_text(el: ET.Element | None, color: str) -> None:
    if el is None:
        return
    for node in el.iter():
        if node.tag.endswith(("text", "tspan")):
            _set_paint(node, fill=color)


def _ui_hex(state: MainSettingsState) -> str:
    """Theme color for filled shapes (white borrows grey so white knobs show)."""
    hexv = str(getattr(state.theme, "ui", "") or "#4B9EEC")
    return _COLOR_WELL_ON_WHITE if hexv.upper() in ("#FFFFFF", "#FFF") else hexv


# --- state → SVG ------------------------------------------------------------


def _sync_pill(
    root: ET.Element, *, button_id: str, text_id: str, selected: bool
) -> None:
    """EXIT: dark pill + white text, inverted when selected."""
    button = _by_id(root, button_id)
    if button is not None:
        _set_paint(button, fill=_COLOR_WHITE if selected else _COLOR_BUTTON)
    _paint_text(_by_id(root, text_id), _COLOR_BLACK if selected else _COLOR_WHITE)


def _sync_stroke_button(el: ET.Element | None, *, selected: bool) -> None:
    """Tiles / section buttons: 3 pt stroke goes white when selected."""
    if el is None:
        return
    _set_paint(el, stroke=_COLOR_WHITE if selected else _COLOR_BUTTON)
    el.set("stroke-width", "3")


def _zipcode_text(state: MainSettingsState) -> str:
    kb = getattr(state, "keyboard", None)
    if kb is not None and str(getattr(kb, "target", "") or "") == "zipcode":
        return "".join(c for c in str(getattr(kb, "buffer", "") or "") if c.isdigit())[:5]
    from pigeon.pigeon_locale import zipcode_display_text

    return zipcode_display_text()


def version_label(state: MainSettingsState | None = None) -> str:
    ver = str(getattr(state, "version_string", "") or version_string()).strip()
    if ver.lower().startswith("v"):
        ver = ver[1:].lstrip()
    return f"PIGEON {ver}" if ver else "PIGEON"


def _sync_version_text(root: ET.Element, state: MainSettingsState) -> None:
    text = _by_id(root, "settings_pigeon_version_text")
    if text is None:
        return
    _set_text_content(text, version_label(state))
    for tspan in text.iter():
        if tspan.tag.endswith("tspan"):
            tspan.attrib.pop("x", None)
            tspan.attrib.pop("y", None)
    m = re.search(r"translate\(\s*[-\d.]+[,\s]+([-\d.]+)", text.get("transform") or "")
    y = float(m.group(1)) if m else _CLOCK_BASELINE_SVG
    text.set("transform", f"translate({_VERSION_RIGHT_X_SVG:.2f} {y:.4f})")
    text.set("text-anchor", "end")


def _sync_status_lights(root: ET.Element, state: MainSettingsState) -> None:
    """Wifi / metadata / audio tiles: green = working, red = not. Glyphs are
    always black (the audio glyph's middle ring shows the tile color)."""
    wifi_ok = not bool(getattr(state, "wifi_logged_out", False)) and (
        bool(str(getattr(state, "live_wifi_ssid", "") or "").strip())
        or bool(getattr(state, "pigeon_network_ok", False))
    )
    meta_ok = bool(getattr(state, "pigeon_metadata_ok", False))
    audio_ok = bool(getattr(state, "pigeon_audio_ok", False))

    def _tile(ok: bool) -> str:
        return _COLOR_STATUS_OK if ok else _COLOR_STATUS_BAD

    wifi = _by_id(root, "settings_input_wifi_button")
    if wifi is not None:
        _set_paint(wifi, fill=_tile(wifi_ok), stroke="none")
    meta = _by_id(root, "settings_input_metadata_button")
    if meta is not None:
        _set_paint(meta, fill=_tile(meta_ok), stroke="none")
    # Text with no fill rasterizes white; the </> glyph is black.
    _paint_text(_by_id(root, "settings_input_metadata_icon"), _COLOR_BLACK)
    audio = _by_id(root, "settings_pigeon_09_audio_button", "settings_input_audio_button")
    if audio is not None:
        _set_paint(audio, fill=_tile(audio_ok), stroke="none")
    for dot, fill in (
        ("settings_input_audio_dot_outter", _COLOR_BLACK),
        ("settings_input_audio_dot_middle", _tile(audio_ok)),
        ("settings_input_audio_dot_inner", _COLOR_BLACK),
    ):
        el = _by_id(root, dot)
        if el is not None:
            _set_paint(el, fill=fill, stroke=_COLOR_BLACK if dot.endswith("inner") else "none")


def _svg_y(el: ET.Element | None) -> float | None:
    """Vertical anchor of a knob (path start / circle center) or label (translate y)."""
    if el is None:
        return None
    if el.get("cy") is not None:
        try:
            return float(el.get("cy"))
        except ValueError:
            return None
    m = re.match(r"\s*M\s*[-\d.]+[,\s]+([-\d.]+)", el.get("d") or "")
    if m:
        return float(m.group(1))
    m = re.search(r"translate\(\s*[-\d.]+[,\s]+([-\d.]+)", el.get("transform") or "")
    return float(m.group(1)) if m else None


def _bbox(el: ET.Element) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) of a tile / container shape (rect or Illustrator pill path)."""
    if _local(el) == "rect":
        x, y = float(el.get("x") or 0), float(el.get("y") or 0)
        return x, y, x + float(el.get("width") or 0), y + float(el.get("height") or 0)
    from pigeon.widgets.settings_keyboard import _path_bbox

    return _path_bbox(el.get("d") or "")


def _set_label(
    el: ET.Element,
    text: str,
    *,
    cx: float,
    y: float | None = None,
    size: float,
    color: str = _COLOR_WHITE,
) -> None:
    """Center ``text`` on ``cx`` (keeping the authored baseline unless ``y``).

    The export splits some labels into one ``tspan`` per letter; those are
    flattened so the whole string is one run.
    """
    if y is None:
        y = _svg_y(el) or 0.0
    for span in list(el):
        if span.tag.endswith("tspan"):
            el.remove(span)
    el.text = text
    el.attrib.pop("letter-spacing", None)
    el.set("transform", f"translate({cx:.2f} {y:.2f})")
    el.set("text-anchor", "middle")
    el.set("font-size", f"{size:.2f}")
    _set_paint(el, fill=color)


def _add_text(
    parent: ET.Element,
    text: str,
    *,
    cx: float,
    y: float,
    size: float,
    digital: bool = False,
    color: str = _COLOR_WHITE,
) -> None:
    el = ET.SubElement(parent, _sibling_tag(parent, "text"))
    el.text = text
    el.set("transform", f"translate({cx:.2f} {y:.2f})")
    el.set("font-family", "Digital-7, Digital-7" if digital else "SharpSans-Bold, 'Sharp Sans'")
    if not digital:
        el.set("font-weight", "700")
    el.set("font-size", f"{size:.2f}")
    el.set("text-anchor", "middle")
    el.set("fill", color)


def _toggle_parts(
    graphics: ET.Element,
) -> tuple[ET.Element | None, list[ET.Element], list[ET.Element]]:
    """(container pill, knobs top→bottom, labels top→bottom) of a tile's toggle art.

    The export names these inconsistently from tile to tile (``switch`` vs
    ``text`` ids swap between rows), so parts are told apart by element type.
    """
    container = None
    knobs: list[ET.Element] = []
    labels: list[ET.Element] = []
    for el in graphics:
        tag = _local(el)
        if tag == "text":
            labels.append(el)
        elif tag == "path":
            if (el.get("fill") or "").lower() in ("#fff", "#ffffff"):
                knobs.append(el)
            else:
                container = el
    knobs.sort(key=lambda e: _svg_y(e) or 0.0)
    labels.sort(key=lambda e: _svg_y(e) or 0.0)
    return container, knobs, labels


def _fill_toggle(
    graphics: ET.Element,
    *,
    cx: float,
    choices: tuple[str, str],
    is_b: bool,
    well: str,
    ink: str = _COLOR_WHITE,
    knob: str | None = None,
    well_stroke: str | None = None,
) -> None:
    container, knobs, labels = _toggle_parts(graphics)
    if container is not None:
        _set_paint(container, fill=well)
        if well_stroke is not None:
            _set_paint(container, stroke=well_stroke)
            container.set("stroke-width", "3")
    if len(knobs) == 2:
        _set_visible(knobs[0], not is_b)
        _set_visible(knobs[1], is_b)
        for k in knobs:
            _set_paint(k, fill=knob or ink)
    for label, text in zip(labels, choices):
        _set_label(label, text, cx=cx, size=_TOGGLE_LABEL_PX, color=ink)


def _simple_dim(ui_hex: str) -> str:
    """UI color at ~45 % toward black: the SIMPLE look's greyed-out ink."""
    h = ui_hex.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return ui_hex
    return f"#{int(r * 0.45):02X}{int(g * 0.45):02X}{int(b * 0.45):02X}"


def _sync_slot(
    root: ET.Element,
    n: int,
    slot: Slot,
    state: MainSettingsState,
    *,
    selected: bool,
    ui_hex: str,
    simple: bool = False,
) -> None:
    group = _by_id(root, f"toggle_0{n}_group")
    if group is None:
        return
    button = next((c for c in group if _local(c) in ("rect", "path")), None)
    graphics = next((c for c in group if _local(c) == "g"), None)
    if button is None or graphics is None:
        return
    x0, y0, x1, y1 = _bbox(button)
    cx, cy = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    dim = slot.kind.startswith("tbd")
    if simple:
        # Selected: UI-color fill, black text. Otherwise black fill, UI stroke + text.
        _set_paint(button, fill=ui_hex if selected else _COLOR_BLACK, stroke=ui_hex)
        button.set("stroke-width", "3")
        text_ink = _COLOR_BLACK if selected else (_simple_dim(ui_hex) if dim else ui_hex)
        knob_ink = _simple_dim(ui_hex) if dim else ui_hex
    else:
        _sync_stroke_button(button, selected=selected)
        text_ink = _COLOR_TBD_INK if dim else _COLOR_WHITE
        knob_ink = None

    if slot.kind in ("toggle", "tbd_toggle"):
        from pigeon.widgets.options_settings import option_is_b

        n_opt = option_for_focus(slot.focus_id)
        is_b = bool(n_opt and option_is_b(n_opt, getattr(state, "options_values", None) or None))
        _fill_toggle(
            graphics,
            cx=cx,
            choices=slot.choices,
            is_b=is_b,
            well=_COLOR_BLACK if simple else (_COLOR_TBD_WELL if dim else ui_hex),
            ink=text_ink,
            knob=knob_ink,
            well_stroke=knob_ink,
        )
        return

    _set_visible(graphics, False)
    if slot.kind == "color":
        _add_color_dot(group, cx, cy, slot.label)
        if simple and selected:
            # UI-colored dot on a UI-colored tile: ring it in black.
            group[-1].set("stroke", _COLOR_BLACK)
            group[-1].set("stroke-width", "4")
    elif slot.focus_id == "zipcode":
        _add_text(group, slot.label, cx=cx, y=cy - 22, size=_CAPTION_PX, color=text_ink)
        _add_text(
            group, _zipcode_text(state), cx=cx, y=cy + 36, size=_VALUE_PX, digital=True, color=text_ink
        )
    elif slot.focus_id == "timezone":
        from pigeon.pigeon_locale import timezone_abbrev

        _add_text(group, slot.label, cx=cx, y=cy - 22, size=_CAPTION_PX, color=text_ink)
        _add_text(
            group, timezone_abbrev(), cx=cx, y=cy + 36, size=_VALUE_PX, digital=True, color=text_ink
        )
    else:
        _add_text(
            group,
            slot.label,
            cx=cx,
            y=cy + 9,
            size=_BUTTON_LABEL_PX,
            color=text_ink,
        )
        if slot.focus_id == "update" and bool(getattr(state, "update_available", False)):
            dot = ET.SubElement(group, _sibling_tag(group, "circle"))
            dot.set("cx", f"{x1 - 22:.2f}")
            dot.set("cy", f"{y0 + 22:.2f}")
            dot.set("r", "9")
            dot.set("fill", _COLOR_STATUS_OK)


def _add_color_dot(group: ET.Element, cx: float, cy: float, key: str) -> None:
    from pigeon.widgets.ui_color_settings import hex_for_color_key

    dot = ET.SubElement(group, _sibling_tag(group, "circle"))
    dot.set("cx", f"{cx:.2f}")
    dot.set("cy", f"{cy:.2f}")
    dot.set("r", f"{_COLOR_DOT_R:.2f}")
    dot.set("fill", hex_for_color_key("ui", key))
    dot.set("stroke", _COLOR_BUTTON)


def _first_rect(el: ET.Element) -> ET.Element | None:
    return next((n for n in el.iter() if _local(n) == "rect"), None)


def _first_text(el: ET.Element) -> ET.Element | None:
    return next((n for n in el.iter() if _local(n) == "text"), None)


def _circularize(root: ET.Element) -> None:
    """Swap fully-rounded rects for true circles.

    The section2/3 discs are rects with ``rx`` ≥ half the side, and the two
    sides differ by a point or two, so they rasterize as a lopsided squircle.
    """
    parents = {c: p for p in root.iter() for c in p}
    for rect in [e for e in root.iter() if _local(e) == "rect"]:
        try:
            x, y = float(rect.get("x") or 0), float(rect.get("y") or 0)
            w, h = float(rect.get("width") or 0), float(rect.get("height") or 0)
            rx = float(rect.get("rx") or 0)
        except ValueError:
            continue
        side = min(w, h)
        if side <= 0 or rx < side * 0.49 or w > side * 1.1 or h > side * 1.1:
            continue
        circle = ET.Element(_sibling_tag(rect, "circle"))
        for key, val in rect.attrib.items():
            if key not in ("x", "y", "width", "height", "rx", "ry"):
                circle.set(key, val)
        circle.set("cx", f"{x + w / 2:.2f}")
        circle.set("cy", f"{y + h / 2:.2f}")
        circle.set("r", f"{side / 2:.2f}")
        parent = parents[rect]
        parent.insert(list(parent).index(rect), circle)
        parent.remove(rect)
        parents[circle] = parent


def _shift_x(group: ET.Element, dx: float) -> None:
    """Move a group's rects and texts right by ``dx`` in place.

    Not a ``transform`` on the group: the text overlay reads each text's own
    ``translate`` and ignores its parents'.
    """
    for el in group.iter():
        tag = _local(el)
        if tag == "rect":
            el.set("x", f"{float(el.get('x') or 0) + dx:.2f}")
        elif tag == "circle":
            el.set("cx", f"{float(el.get('cx') or 0) + dx:.2f}")
        elif tag == "text":
            m = re.search(r"translate\(\s*([-\d.]+)[,\s]+([-\d.]+)", el.get("transform") or "")
            if m:
                el.set("transform", f"translate({float(m.group(1)) + dx:.2f} {m.group(2)})")


_ROT_RE = re.compile(
    r"translate\(\s*([-\d.]+)[,\s]+([-\d.]+)\s*\)\s*rotate\(\s*([-\d.]+)\s*\)"
)


def _clock_hands_to_polygons(root: ET.Element) -> None:
    """Redraw the clock icon's rotated hand rects as polygons.

    The background sweep deletes every rotated ``rect`` (they look like slanted
    theme stripes), hands included.
    """
    import math

    parents = {c: p for p in root.iter() for c in p}
    for hid in ("clock_hand_minute", "clock_hand_hour", "clock_hand_second"):
        rect = _by_id(root, hid)
        parent = parents.get(rect) if rect is not None else None
        m = _ROT_RE.search(rect.get("transform") or "") if rect is not None else None
        if rect is None or parent is None or m is None:
            continue
        tx, ty, deg = float(m.group(1)), float(m.group(2)), float(m.group(3))
        x, y = float(rect.get("x")), float(rect.get("y"))
        w, h = float(rect.get("width")), float(rect.get("height"))
        r = float(rect.get("rx") or 0)
        # Inset by half the corner radius, then stroke with round joins.
        x, y, w, h = x + r / 2, y + r / 2, w - r, h - r
        c, sn = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        pts = [
            (tx + px * c - py * sn, ty + px * sn + py * c)
            for px, py in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
        ]
        poly = ET.Element(_sibling_tag(rect, "polygon"))
        poly.set("id", hid)
        poly.set("points", " ".join(f"{a:.2f},{b:.2f}" for a, b in pts))
        poly.set("fill", rect.get("fill") or _COLOR_WHITE)
        poly.set("stroke", rect.get("fill") or _COLOR_WHITE)
        poly.set("stroke-width", f"{r:.2f}")
        poly.set("stroke-linejoin", "round")
        parent.insert(list(parent).index(rect), poly)
        parent.remove(rect)


def _theme_ramp_hex(original: str, ui_hex: str) -> str:
    """Re-tint one of the theme icon's red stripes with the live UI color,
    keeping its brightness step (the same ramp the page background uses)."""
    from pigeon.widgets.settings_theme_background import scale_ui_hex

    try:
        step = int(original.lstrip("#")[:2], 16) / 0xD6
    except ValueError:
        return ui_hex
    return scale_ui_hex(ui_hex, min(1.0, step))


def _sync_sections(
    root: ET.Element,
    state: MainSettingsState,
    *,
    focused: str,
    ui_hex: str,
    simple: bool = False,
) -> None:
    view = normalize_view(getattr(state, "pigeon_view", DEFAULT_VIEW))
    sec2_view, sec3_view = section_targets(view)

    theme2 = _by_id(root, "section2_theme")
    general2 = _by_id(root, "section2_general")
    clock3 = _by_id(root, "section3_clock")
    container3 = _by_id(root, "clock_container")
    if theme2 is None or general2 is None or clock3 is None or container3 is None:
        return
    rect2 = _first_rect(general2)
    if rect2 is None:
        return

    # section3 has no "general" art: borrow section2's, shifted onto section3.
    parent = next((p for p in root.iter() if clock3 in list(p)), root)
    for stale in [c for c in parent if c.get("id") == "section3_general"]:
        parent.remove(stale)
    general3 = copy.deepcopy(general2)
    general3.set("id", "section3_general")
    _shift_x(general3, float(container3.get("x") or 0) - float(rect2.get("x") or 0))
    parent.insert(list(parent).index(clock3) + 1, general3)

    # The theme icon is the page background's stripes: tint them live.
    for stripe in theme2.iter():
        fill = (stripe.get("fill") or "").lower()
        if (
            _local(stripe) == "rect"
            and "rotate" in (stripe.get("transform") or "")
            and fill.startswith("#")
        ):
            _set_paint(stripe, fill=_theme_ramp_hex(fill, ui_hex))
    for node in (general2, general3):
        disc = next(
            (n for n in node.iter() if _local(n) in ("rect", "circle") and (n.get("fill") or "").lower() == "#b00"),
            None,
        )
        if disc is not None:
            _set_paint(disc, fill=ui_hex)
            if simple:
                _paint_text(node, _COLOR_BLACK)
    for cid in ("clock_face", "clock_center"):
        el = _by_id(root, cid)
        if el is not None:
            _set_paint(el, fill=ui_hex)
    _clock_hands_to_polygons(root)

    _set_visible(theme2, sec2_view == "theme")
    _set_visible(general2, sec2_view == "general")
    _set_visible(clock3, sec3_view == "clock")
    _set_visible(general3, sec3_view == "general")

    for node, name, section in (
        (theme2, "theme", "section2"),
        (general2, "general", "section2"),
        (general3, "general", "section3"),
        (clock3, "clock", "section3"),
    ):
        rect = _first_rect(node)
        sel = focused == section
        _sync_stroke_button(rect, selected=sel)
        label_ink = _COLOR_WHITE
        if simple and rect is not None:
            # The name sits below the button, on black: always UI-colored.
            _set_paint(rect, fill=ui_hex if sel else _COLOR_BLACK, stroke=ui_hex)
            label_ink = ui_hex
        label = next((n for n in node.iter() if _local(n) == "text"), None)
        if label is not None and rect is not None:
            x0, _, x1, _ = _bbox(rect)
            _set_label(label, name, cx=(x0 + x1) * 0.5, size=36, color=label_ink)


def apply_pigeon_settings_svg_state(root: ET.Element, state: MainSettingsState) -> None:
    kb_open = getattr(state, "keyboard", None) is not None
    focused = "" if kb_open else normalize_pigeon_focus_id(state.pigeon_focused_id)
    kb_zip = kb_open and str(getattr(state.keyboard, "target", "") or "") == "zipcode"
    # Update screen: EXIT becomes the system BACK button and is the only page
    # control that can carry focus.
    update_screen = bool(getattr(state, "show_update_popup", False))
    if update_screen:
        focused = "exit" if state.update_popup_focused_choice == "back" else ""
    view = normalize_view(getattr(state, "pigeon_view", DEFAULT_VIEW))
    ui_hex = _ui_hex(state)
    from pigeon.widgets.options_settings import ui_is_simple

    simple = ui_is_simple(state)
    _circularize(root)

    _sync_pill(root, button_id="exit_button", text_id="exit_text", selected=focused == "exit")
    if simple:
        exit_sel = focused == "exit"
        exit_button = _by_id(root, "exit_button")
        if exit_button is not None:
            _set_paint(exit_button, fill=ui_hex if exit_sel else _COLOR_BLACK, stroke=ui_hex)
            exit_button.set("stroke-width", "3")
        _paint_text(_by_id(root, "exit_text"), _COLOR_BLACK if exit_sel else ui_hex)
    _set_text_content(_by_id(root, "exit_text"), "BACK" if update_screen else "EXIT")
    center_label_on_pill(_by_id(root, "exit_text"), _by_id(root, "exit_button"))

    _sync_version_text(root, state)
    if simple:
        _paint_text(_by_id(root, "settings_pigeon_version_text"), ui_hex)
    _sync_status_lights(root, state)

    # section1: the open menu's six tiles on a UI-colored plate, named below.
    panel = _by_id(root, "toggle_01_button")
    if panel is not None:
        if simple:
            _set_paint(panel, fill=_COLOR_BLACK, stroke="none")
        else:
            _set_paint(panel, fill=ui_hex)
    for n, slot in enumerate(view_slots(view), start=1):
        selected = bool(slot.focus_id) and (
            focused == slot.focus_id or (kb_zip and slot.focus_id == "zipcode")
        )
        _sync_slot(root, n, slot, state, selected=selected, ui_hex=ui_hex, simple=simple)
    section1 = _by_id(root, "section1_togles")
    if section1 is not None and panel is not None:
        title = next((c for c in section1 if _local(c) == "text"), None)
        if title is not None:
            x0, _, x1, _ = _bbox(panel)
            _set_label(
                title, view, cx=(x0 + x1) * 0.5, size=36, color=ui_hex if simple else _COLOR_WHITE
            )

    _sync_sections(root, state, focused=focused, ui_hex=ui_hex, simple=simple)
    if simple:
        container = _by_id(root, "clock_container")
        if container is not None:
            _set_paint(container, fill=_COLOR_BLACK, stroke=ui_hex)
            container.set("stroke-width", "3")
        for hid in ("clock_hand_minute", "clock_hand_hour", "clock_hand_second"):
            hand = _by_id(root, hid)
            if hand is not None:
                _set_paint(hand, fill=_COLOR_BLACK, stroke=_COLOR_BLACK)


# --- clip-path (PyMuPDF ignores it) -----------------------------------------


def _clip_ref(el: ET.Element) -> str:
    m = re.search(r"url\(#([^)]+)\)", el.get("clip-path") or "")
    return m.group(1) if m else ""


def _raster_alone(root: ET.Element, nodes: list[ET.Element]) -> np.ndarray:
    from pigeon.widgets.settings_svg_text import rasterize_settings_svg_bgra

    doc = ET.Element(root.tag, dict(root.attrib))
    for node in nodes:
        doc.append(node)
    return rasterize_settings_svg_bgra(doc, width=DESIGN_W, height=DESIGN_H)


def _clipped_layer_bgra(root: ET.Element, layer: ET.Element, clip: ET.Element) -> np.ndarray:
    key = ET.tostring(layer) + ET.tostring(clip) + (root.get("viewBox") or "").encode()
    cache_key = str(hash(key))
    hit = _CLIP_LAYER_CACHE.get(cache_key)
    if hit is not None:
        return hit
    art = _raster_alone(root, [layer])
    shapes = []
    for shape in clip:
        s = copy.deepcopy(shape)
        _set_paint(s, fill=_COLOR_WHITE, stroke="none")
        shapes.append(s)
    mask = _raster_alone(root, shapes)[:, :, 3]
    out = art.copy()
    out[:, :, 3] = (art[:, :, 3].astype(np.uint16) * mask // 255).astype(np.uint8)
    if len(_CLIP_LAYER_CACHE) >= _CLIP_LAYER_CACHE_MAX:
        _CLIP_LAYER_CACHE.clear()
    _CLIP_LAYER_CACHE[cache_key] = out
    return out


def _extract_clipped_layers(root: ET.Element) -> list[np.ndarray]:
    """Pull every ``clip-path`` subtree out of ``root`` and raster it masked.

    Layers are composited back on top of the page, which is correct for this
    art: nothing drawn later in the SVG overlaps a clipped layer.
    """
    clips = {
        el.get("id"): el
        for el in root.iter()
        if el.tag.endswith("clipPath") and el.get("id")
    }
    parents = {child: parent for parent in root.iter() for child in parent}
    patches: list[np.ndarray] = []
    for el in list(root.iter()):
        ref = _clip_ref(el)
        clip = clips.get(ref)
        parent = parents.get(el)
        if clip is None or parent is None:
            continue
        layer = copy.deepcopy(el)
        layer.attrib.pop("clip-path", None)
        parent.remove(el)
        patches.append(_clipped_layer_bgra(root, layer, clip))
    return patches


# --- rendering --------------------------------------------------------------


def _svg_tree_from_path(path: Path) -> ET.Element:
    path = Path(path)
    key = (str(path.resolve()), path.stat().st_mtime_ns)
    template = _SVG_TREE_TEMPLATES.get(key)
    if template is None:
        root = ET.parse(path).getroot()
        x, y, w, h = _PIGEON_VIEWBOX
        root.set("viewBox", f"{x} {y} {w} {h}")
        root.set("width", str(DESIGN_W))
        root.set("height", str(DESIGN_H))
        if len(_SVG_TREE_TEMPLATES) >= _SVG_TREE_TEMPLATE_MAX:
            _SVG_TREE_TEMPLATES.clear()
        _SVG_TREE_TEMPLATES[key] = root
        template = root
    return copy.deepcopy(template)


def _full_theme_bgra(
    state: MainSettingsState,
    *,
    assets_dir: Path | str | None,
    path: Path,
) -> np.ndarray:
    ui_hex = str(getattr(state.theme, "ui", "#4B9EEC") or "#4B9EEC")
    adir = str(assets_dir if assets_dir is not None else path.parent.parent)
    key = (ui_hex, adir, int(DESIGN_W), int(DESIGN_H))
    cached = _THEME_BG_CACHE.get(key)
    if cached is not None:
        return cached
    bg_bgra = np.zeros((DESIGN_H, DESIGN_W, 4), dtype=np.uint8)
    bg_bgra[:, :, 3] = 255
    _draw_container_background_bgra(bg_bgra, ui_hex=ui_hex, assets_dir=adir)
    while len(_THEME_BG_CACHE) >= _THEME_BG_CACHE_MAX:
        _THEME_BG_CACHE.pop(next(iter(_THEME_BG_CACHE)))
    _THEME_BG_CACHE[key] = bg_bgra
    return bg_bgra


def _svg_to_px(x: float, y: float) -> tuple[float, float]:
    vb_x, vb_y, vb_w, vb_h = _PIGEON_VIEWBOX
    return ((x - vb_x) * DESIGN_W / vb_w, (y - vb_y) * DESIGN_H / vb_h)


def timezone_dropdown_rows(state: MainSettingsState) -> tuple[list[str], int, int]:
    """(labels on screen, index of the first visible choice, focused choice)."""
    from pigeon.pigeon_locale import timezone_choices, timezone_dropdown_label

    choices = timezone_choices()
    if not choices:
        return [], 0, 0
    focus = int(getattr(state, "tz_dropdown_index", 0)) % len(choices)
    visible = min(_DROPDOWN_MAX_ROWS, len(choices))
    first = max(0, min(focus - visible // 2, len(choices) - visible))
    labels = [timezone_dropdown_label(name) for name in choices[first : first + visible]]
    return labels, first, focus


def _draw_timezone_dropdown(frame: np.ndarray, state: MainSettingsState) -> None:
    from PIL import Image, ImageDraw

    from pigeon.font_paths import resolve_digital7_font, resolve_ui_font_bold
    from pigeon.widgets.settings_svg_text import _load_font

    labels, first, focus = timezone_dropdown_rows(state)
    if not labels:
        return
    bx, by = _DROPDOWN_ANCHOR_SVG
    x0, y0 = _svg_to_px(bx, by)
    x0 = int(round(x0))
    y0 = int(round(y0))
    h = len(labels) * (_DROPDOWN_ROW_H + _DROPDOWN_ROW_GAP) - _DROPDOWN_ROW_GAP
    patch = Image.new("RGBA", (_DROPDOWN_ROW_W, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(patch)
    font_path = resolve_digital7_font() or resolve_ui_font_bold()
    font = _load_font(font_path, _DROPDOWN_FONT_PX) if font_path else None
    for i, label in enumerate(labels):
        top = i * (_DROPDOWN_ROW_H + _DROPDOWN_ROW_GAP)
        selected = first + i == focus
        fill = (255, 255, 255, 255) if selected else (0, 0, 0, 255)
        ink = (0, 0, 0, 255) if selected else (255, 255, 255, 255)
        draw.rounded_rectangle(
            (0, top, _DROPDOWN_ROW_W - 1, top + _DROPDOWN_ROW_H - 1),
            radius=_DROPDOWN_RADIUS,
            fill=fill,
            outline=(255, 255, 255, 255),
            width=2,
        )
        draw.text(
            (_DROPDOWN_ROW_W // 2, top + _DROPDOWN_ROW_H // 2),
            label,
            font=font,
            fill=ink,
            anchor="mm",
        )
    import cv2

    bgra = cv2.cvtColor(np.asarray(patch), cv2.COLOR_RGBA2BGRA)
    overlay = np.zeros_like(frame)
    x1 = min(DESIGN_W, x0 + bgra.shape[1])
    y1 = min(DESIGN_H, y0 + bgra.shape[0])
    overlay[y0:y1, x0:x1] = bgra[: y1 - y0, : x1 - x0]
    frame[:] = _composite_bgra_over_bgra(frame, overlay)


def render_pigeon_settings_bgra(
    state: MainSettingsState | None = None,
    *,
    svg_path: Path | str | None = None,
    assets_dir: Path | str | None = None,
    clock: bool = False,
) -> np.ndarray:
    """Render the page. ``clock=True`` also paints the live HH:MM:SS."""
    path = Path(svg_path) if svg_path is not None else default_pigeon_settings_svg_path(assets_dir)
    if not path.is_file():
        raise FileNotFoundError(f"pigeon settings SVG not found: {path}")
    st = state if state is not None else MainSettingsState()
    root = _svg_tree_from_path(path)
    apply_pigeon_settings_svg_state(root, st)
    # The export bakes clipped stripes into ``background``; hide them before
    # the clip pass, which would otherwise lift them on top of the page.
    _set_visible(_by_id(root, "background"), False)
    _prune_display_none(root)
    # Before the background sweep: it hides rotated rects, which would empty
    # the reset icon's rotated clip rectangle.
    clipped = _extract_clipped_layers(root)
    _disable_embedded_settings_background_layers(root)
    _prune_display_none(root)
    from pigeon.widgets.settings_svg_text import rasterize_settings_svg_bgra

    ui_bgra = rasterize_settings_svg_bgra(
        root,
        width=DESIGN_W,
        height=DESIGN_H,
        font_mode="preferences",
    )
    for patch in clipped:
        ui_bgra = _composite_bgra_over_bgra(ui_bgra, patch)
    from pigeon.widgets.options_settings import ui_is_simple

    if ui_is_simple(st):
        # SIMPLE: no background layer, just black under the UI.
        bg = np.zeros((DESIGN_H, DESIGN_W, 4), dtype=np.uint8)
        bg[:, :, 3] = 255
    else:
        bg = _full_theme_bgra(st, assets_dir=assets_dir, path=path)
    frame = _composite_bgra_over_bgra(bg, ui_bgra)
    if frame is bg:
        frame = bg.copy()
    if getattr(st, "tz_dropdown_open", False):
        _draw_timezone_dropdown(frame, st)
    if clock:
        frame = draw_pigeon_settings_clock(frame, ink=page_ink_rgb(st))
    return frame


def pigeon_clock_label(now: datetime | None = None) -> str:
    """HH:MM:SS in Pigeon's timezone, 12/24 h per option1 (clocksaver rules)."""
    from pigeon.pigeon_locale import pigeon_now
    from pigeon.widgets.clock_saver import _time_label

    return _time_label(now if now is not None else pigeon_now())


def page_ink_rgb(state: MainSettingsState | None = None) -> tuple[int, int, int]:
    """Ink for the live clock / app code: white, or the UI color in SIMPLE."""
    from pigeon.widgets.options_settings import ui_is_simple

    if state is None or not ui_is_simple(state):
        return (255, 255, 255)
    h = _ui_hex(state).lstrip("#")
    try:
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (255, 255, 255)


def draw_pigeon_settings_clock(
    frame: np.ndarray,
    now: datetime | None = None,
    ink: tuple[int, int, int] = (255, 255, 255),
) -> np.ndarray:
    """Return a copy of ``frame`` with the live clock in locked digit cells."""
    from PIL import Image

    from pigeon.font_paths import resolve_digital7_font, resolve_ui_font_bold
    from pigeon.widgets.clock_saver import (
        _HHMMSS_CHAR_SET,
        _HHMMSS_MATCHING_UNITS,
        _cell_metrics,
        _draw_hhmmss_matching_run,
        _fit_digital7_fixed_cells,
        _hhmmss_scaffold_width,
    )

    x0f, _ = _svg_to_px(_CLOCK_LEFT_SVG, _CLOCK_BASELINE_SVG)
    x1f, baseline = _svg_to_px(_CLOCK_RIGHT_SVG, _CLOCK_BASELINE_SVG)
    x1 = int(round(x1f))
    span = max(1, x1 - int(round(x0f)))
    font = _fit_digital7_fixed_cells(
        resolve_digital7_font() or resolve_ui_font_bold(),
        _HHMMSS_MATCHING_UNITS,
        max_w=span,
        max_h=_CLOCK_FONT_PX,
        prefer_sz=_CLOCK_FONT_PX,
    )
    from PIL import ImageDraw

    matching_w, _ = _cell_metrics(ImageDraw.Draw(Image.new("RGBA", (4, 4))), font, _HHMMSS_CHAR_SET)
    w = min(span, _hhmmss_scaffold_width(matching_w))
    x0 = x1 - w
    top = max(0, int(round(baseline)) - _CLOCK_FONT_PX)
    bottom = min(DESIGN_H, int(round(baseline)) + _CLOCK_FONT_PX // 3)
    h = max(1, bottom - top)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    _draw_hhmmss_matching_run(
        img,
        text=pigeon_clock_label(now),
        matching_w=matching_w,
        cy=int(round(baseline)) - top,
        font=font,
        color=(*ink, 255),
        canvas_w=w,
    )
    patch = np.asarray(img)[:, :, [2, 1, 0, 3]]
    out = frame.copy()
    out[top:bottom, x0 : x0 + w] = _composite_bgra_over_bgra(
        frame[top:bottom, x0 : x0 + w], patch
    )
    return out


# Free strip under the section names (design px on the 1280x800 page).
_COMPANION_CODE_XY = (70, 668)
_COMPANION_CODE_FONT_PX = 34


def draw_companion_code(
    frame: np.ndarray,
    code: str | None = None,
    ink: tuple[int, int, int] = (255, 255, 255),
) -> np.ndarray:
    """Paint ``APP CODE 123456`` while the companion app can claim this device.

    ``code=None`` asks :mod:`pigeon.control_api`; empty means nothing to show
    and ``frame`` is returned untouched.
    """
    if code is None:
        try:
            from pigeon.control_api import claim_code_to_show

            code = claim_code_to_show()
        except Exception:
            code = ""
    code = str(code or "").strip()
    if not code:
        return frame
    from PIL import Image, ImageDraw, ImageFont

    from pigeon.font_paths import resolve_digital7_font, resolve_ui_font_bold

    path = resolve_digital7_font() or resolve_ui_font_bold()
    try:
        font = ImageFont.truetype(str(path), _COMPANION_CODE_FONT_PX)
    except Exception:
        font = ImageFont.load_default()
    text = f"APP CODE {code}"
    x, y = _COMPANION_CODE_XY
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font)
    w, h = r - l + 4, b - t + 4
    if y < 0 or x < 0 or y + h > frame.shape[0] or x + w > frame.shape[1]:
        return frame
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((2 - l, 2 - t), text, font=font, fill=(*ink, 255))
    patch = np.asarray(img)[:, :, [2, 1, 0, 3]]
    out = frame.copy()
    out[y : y + h, x : x + w] = _composite_bgra_over_bgra(out[y : y + h, x : x + w], patch)
    return out


def clear_pigeon_settings_render_caches() -> None:
    _SVG_TREE_TEMPLATES.clear()
    _THEME_BG_CACHE.clear()
    _CLIP_LAYER_CACHE.clear()


def factory_reset_pigeon_persisted_state() -> None:
    """Erase persisted customizations / pairings and restore defaults on disk."""
    from pigeon.app_state import (
        clear_all_persisted_devices_and_targets,
        clear_last_apple_tv,
        clear_last_receiver,
        pop_app_state_keys,
    )
    from pigeon.media_folders import (
        pigeon_pulled_media_dir,
        pigeon_reformatted_media_dir,
        purge_directory_contents,
    )
    from pigeon.pigeon_locale import clear_location
    from pigeon.runtime_paths import pigeon_state_dir
    from pigeon.widgets.preferences_settings import (
        DEFAULT_MUSIC_ZONE_WIDGETS,
        DEFAULT_ZONE_WIDGETS,
        NP_ZONE_LAYOUT_GENERATION,
        write_np_header_clock,
        write_now_playing_zone_widgets,
    )
    from pigeon.widgets.ui_color_settings import write_ui_color_keys

    clear_all_persisted_devices_and_targets()
    try:
        clear_last_apple_tv()
    except Exception:
        pass
    try:
        clear_last_receiver()
    except Exception:
        pass
    pop_app_state_keys(
        "settings_ui_colors",
        "now_playing_zone_widgets",
        "now_playing_zone_widgets_music",
        "np_header_clock",
        "np_zone_layout_generation",
        "display_par_mode",
        "roku_ecp_base_url",
        "tmdb_quality_ok_count",
        "tmdb_quality_fail_count",
        "source_toggles",
        "settings_options",
        "clock_12h_default_generation",
    )
    clear_location()
    write_ui_color_keys(
        {"accent": "white", "ui": "blue", "button": "black"},
        persist=True,
    )
    write_now_playing_zone_widgets(DEFAULT_ZONE_WIDGETS)
    write_now_playing_zone_widgets(
        DEFAULT_MUSIC_ZONE_WIDGETS, content_mode="music"
    )
    write_np_header_clock(True)
    try:
        from pigeon.app_state import write_app_state

        write_app_state(np_zone_layout_generation=int(NP_ZONE_LAYOUT_GENERATION))
    except Exception:
        pass
    try:
        purge_directory_contents(pigeon_pulled_media_dir())
    except Exception:
        pass
    try:
        purge_directory_contents(pigeon_reformatted_media_dir())
    except Exception:
        pass
    for name in ("pyatv_credentials",):
        try:
            p = pigeon_state_dir() / name
            if p.is_file():
                p.unlink()
        except OSError:
            pass


__all__ = [
    "OPT_CLOCK_FORMAT",
    "OPT_NP_LAYOUT",
    "OPT_TEMP",
    "OPT_TIME",
    "Slot",
    "THEME_KEYS",
    "VIEWS",
    "apply_pigeon_settings_svg_state",
    "clear_pigeon_settings_render_caches",
    "color_key_for_focus",
    "default_pigeon_settings_svg_path",
    "draw_pigeon_settings_clock",
    "draw_companion_code",
    "page_ink_rgb",
    "factory_reset_pigeon_persisted_state",
    "normalize_pigeon_focus_id",
    "normalize_view",
    "option_for_focus",
    "pigeon_clock_label",
    "pigeon_focus_ring",
    "render_pigeon_settings_bgra",
    "section_targets",
    "timezone_dropdown_rows",
    "version_label",
    "view_for_section",
    "view_slots",
]
