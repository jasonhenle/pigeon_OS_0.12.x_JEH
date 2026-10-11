"""
Pigeon device settings — ``settings/pigeon/settings_pigeon.svg`` (0.11).

One flat page opened from main settings box1. Everything is edited in place;
nothing opens a sub-page except the zip keyboard, the timezone dropdown and
the update popup. Focus order (spec "settings_pigeon_0.11")::

    EXIT → ZIP → TIMEZONE → 7 UI colors → 5 options → RESET → UPDATE

The clock, version, and the wifi / metadata / audio lights are not selectable.
Moving focus across the color row previews that theme live; activating a
color commits it, and leaving the row falls back to the committed color.

The HH:MM:SS clock ticks every second, so it is drawn by
:func:`draw_pigeon_settings_clock` on top of the cached page instead of being
baked into it.
"""

from __future__ import annotations

import copy
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import numpy as np

from pigeon.design import DESIGN_H, DESIGN_W
from pigeon.settings_layout import SETTINGS_BACKGROUND_SHIFT_Y, SETTINGS_CANVAS_ORIGIN
from pigeon.version import version_string
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
# White knobs vanish in a white well, so the white theme borrows grey's fill.
_COLOR_TOGGLE_WELL_ON_WHITE = "#777777"

UI_COLOR_KEYS: tuple[str, ...] = (
    "blue",
    "green",
    "yellow",
    "orange",
    "red",
    "grey",
    "white",
)
OPTION_NUMBERS: tuple[int, ...] = (1, 2, 3, 4, 5)

_FOCUS_RING: tuple[str, ...] = (
    ("exit", "zipcode", "timezone")
    + tuple(f"color:{k}" for k in UI_COLOR_KEYS)
    + tuple(f"option:{n}" for n in OPTION_NUMBERS)
    + ("reset", "update")
)

# Right edge of the status-light row; the version string right-aligns to it
# so longer versions never run off the plate.
_VERSION_RIGHT_X_SVG = 1795.59

# Clock: glyph baseline and the span it may use, right-aligned beside the
# timezone pill (SVG board units, drawn 1:1 on the 1280×800 canvas). Locked
# digit cells run wider than the authored proportional "10:06:15" (starts at
# 1163.81), so the span reaches back to the middle of the gap after the zip
# pill (ends 1086.03).
_CLOCK_LEFT_SVG = 1125.0
_CLOCK_RIGHT_SVG = 1316.0
_CLOCK_BASELINE_SVG = 830.09
_CLOCK_FONT_PX = 60

# Timezone dropdown, hung under the timezone pill.
_DROPDOWN_ROW_W = 240
_DROPDOWN_ROW_H = 52
_DROPDOWN_ROW_GAP = 6
_DROPDOWN_TOP_GAP = 8
_DROPDOWN_RADIUS = 18
_DROPDOWN_FONT_PX = 44
_DROPDOWN_MAX_ROWS = 8

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


def pigeon_focus_ring() -> tuple[str, ...]:
    return _FOCUS_RING


def normalize_pigeon_focus_id(focus_id: str) -> str:
    return str(focus_id or "").strip()


def color_key_for_focus(focus_id: str) -> str | None:
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


def _child_with(group: ET.Element | None, *fragments: str) -> ET.Element | None:
    """First descendant of ``group`` whose id contains one of ``fragments``.

    The Illustrator export mislabels some layers (the grey group's button is
    ``ui_color_red_button``; green's is ``ui_color_green_butto``), so lookups
    are scoped to the group and match on the role fragment.
    """
    if group is None:
        return None
    for el in group.iter():
        if el is group:
            continue
        name = f"{el.get('id') or ''} {el.get('data-name') or ''}"
        if any(frag in name for frag in fragments):
            return el
    return None


def _option_group(root: ET.Element, n: int) -> ET.Element | None:
    """Option ``n``'s tile group, by group id or (``optionv_visualizer_grpup``
    for option 4) by its ``option{n}_`` children."""
    container = _by_id(root, "settings_option_group", "settings_options_group")
    if container is None:
        return None
    prefix = f"option{n}_"
    for el in container:
        if str(el.get("id") or "").startswith(prefix):
            return el
    for el in container:
        if any(str(c.get("id") or "").startswith(prefix) for c in el):
            return el
    return None


def _paint_text(el: ET.Element | None, color: str) -> None:
    if el is None:
        return
    for node in el.iter():
        if node.tag.endswith(("text", "tspan")):
            _set_paint(node, fill=color)


# --- state → SVG ------------------------------------------------------------


def _sync_pill(
    root: ET.Element, *, button_id: str, text_id: str, selected: bool
) -> None:
    """EXIT / ZIP / TIMEZONE: dark pill + white text, inverted when selected."""
    button = _by_id(root, button_id)
    if button is not None:
        _set_paint(button, fill=_COLOR_WHITE if selected else _COLOR_BUTTON)
    _paint_text(_by_id(root, text_id), _COLOR_BLACK if selected else _COLOR_WHITE)


def _sync_stroke_button(el: ET.Element | None, *, selected: bool) -> None:
    """Color / option / reset / update tiles: 3 pt stroke goes white when selected."""
    if el is None:
        return
    _set_paint(el, stroke=_COLOR_WHITE if selected else _COLOR_BUTTON)
    el.set("stroke-width", "3")


def _fit_text_in_pill(root: ET.Element, *, text_id: str, button_id: str) -> None:
    """Shrink a pill label only when it would overrun the pill (e.g. ``ENTER``, ``AKDT``).

    Text keeps its authored left inset; the font size drops just enough for
    the string to end the same inset short of the pill's right edge.
    """
    text = _by_id(root, text_id)
    button = _by_id(root, button_id)
    if text is None or button is None:
        return
    content = "".join(text.itertext()).strip()
    m = re.search(r"translate\(\s*([-\d.]+)", text.get("transform") or "")
    try:
        x = float(m.group(1)) if m else None
        bx = float(button.get("x"))
        bw = float(button.get("width"))
        size = float(text.get("font-size") or 0)
    except (TypeError, ValueError):
        return
    if not content or x is None or size <= 0:
        return
    avail = (bx + bw) - x - max(0.0, x - bx)
    width = _digital7_width(content, size)
    if width > avail > 0:
        text.set("font-size", f"{size * avail / width:.2f}")


def _digital7_width(content: str, size: float) -> float:
    from PIL import ImageFont

    from pigeon.font_paths import resolve_digital7_font

    path = resolve_digital7_font()
    if not path:
        return 0.0
    try:
        font = ImageFont.truetype(path, max(6, int(round(size))))
    except OSError:
        return 0.0
    return float(font.getlength(content)) * size / max(6, int(round(size)))


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


def _option_label(group: ET.Element, side: str) -> ET.Element | None:
    for el in group.iter():
        name = str(el.get("id") or "")
        if el.tag.endswith("text") and f"_{side}_" in name:
            return el
    return None


def _sync_toggle_knob(group: ET.Element, *, is_b: bool) -> None:
    """Show the knob circle that sits beside the active option's label.

    In the 0.11 export ``toggle_a`` sits beside the B label and vice versa,
    so the knob is picked by position, not by layer name.
    """
    knob_a = _child_with(group, "toggle_a_shape")
    knob_b = _child_with(group, "toggle_b_shape")
    label_y = _svg_y(_option_label(group, "b" if is_b else "a"))
    ya, yb = _svg_y(knob_a), _svg_y(knob_b)
    if label_y is None or ya is None or yb is None:
        show_a = not is_b
    else:
        show_a = abs(ya - label_y) <= abs(yb - label_y)
    _set_visible(knob_a, show_a)
    _set_visible(knob_b, not show_a)


def apply_pigeon_settings_svg_state(root: ET.Element, state: MainSettingsState) -> None:
    from pigeon.pigeon_locale import timezone_abbrev
    from pigeon.widgets.options_settings import option_is_b

    kb_open = getattr(state, "keyboard", None) is not None
    focused = "" if kb_open else normalize_pigeon_focus_id(state.pigeon_focused_id)
    kb_zip = kb_open and str(getattr(state.keyboard, "target", "") or "") == "zipcode"
    # Update screen: EXIT becomes the system BACK button and is the only page
    # control that can carry focus.
    update_screen = bool(getattr(state, "show_update_popup", False))
    if update_screen:
        focused = "exit" if state.update_popup_focused_choice == "back" else ""

    _sync_pill(root, button_id="exit_button", text_id="exit_text", selected=focused == "exit")
    _set_text_content(_by_id(root, "exit_text"), "BACK" if update_screen else "EXIT")
    if update_screen:
        _fit_text_in_pill(root, text_id="exit_text", button_id="exit_button")
    _sync_pill(
        root,
        button_id="zipcode_button",
        text_id="zipcode_00000_text",
        selected=focused == "zipcode" or kb_zip,
    )
    _sync_pill(
        root,
        button_id="settings_timezone_button",
        text_id="settings_timezone_text",
        selected=focused == "timezone",
    )
    _paint_text(_by_id(root, "zipcode_zip_text"), _COLOR_WHITE)
    _set_text_content(_by_id(root, "zipcode_00000_text"), _zipcode_text(state))
    _set_text_content(_by_id(root, "settings_timezone_text"), timezone_abbrev())
    _fit_text_in_pill(root, text_id="zipcode_00000_text", button_id="zipcode_button")
    _fit_text_in_pill(
        root, text_id="settings_timezone_text", button_id="settings_timezone_button"
    )
    # Live HH:MM:SS is painted per second by draw_pigeon_settings_clock().
    _set_visible(_by_id(root, "settings_timezoe_clock", "settings_timezone_clock"), False)

    _sync_version_text(root, state)
    _sync_status_lights(root, state)

    for key in UI_COLOR_KEYS:
        group = _by_id(root, f"ui_color_{key}_group")
        _sync_stroke_button(_child_with(group, "_butt"), selected=focused == f"color:{key}")

    ui_hex = str(getattr(state.theme, "ui", "") or _COLOR_WHITE)
    well_hex = _COLOR_TOGGLE_WELL_ON_WHITE if ui_hex.upper() == _COLOR_WHITE else ui_hex
    values = getattr(state, "options_values", None) or None
    for n in OPTION_NUMBERS:
        group = _option_group(root, n)
        if group is None:
            continue
        _sync_stroke_button(_child_with(group, "_button"), selected=focused == f"option:{n}")
        shape = _child_with(group, "shape_ui_color")
        if shape is not None:
            _set_paint(shape, fill=well_hex)
        _sync_toggle_knob(group, is_b=option_is_b(n, values))

    _sync_stroke_button(_by_id(root, "settings_reset_button"), selected=focused == "reset")
    _sync_stroke_button(
        _by_id(root, "settings_update_button", "setting_update_button"),
        selected=focused == "update",
    )


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


def _draw_timezone_dropdown(frame: np.ndarray, state: MainSettingsState, root: ET.Element) -> None:
    from PIL import Image, ImageDraw

    from pigeon.font_paths import resolve_digital7_font, resolve_ui_font_bold
    from pigeon.widgets.settings_svg_text import _load_font

    labels, first, focus = timezone_dropdown_rows(state)
    if not labels:
        return
    button = _by_id(root, "settings_timezone_button")
    try:
        bx = float(button.get("x")) if button is not None else 1323.43
        by = float(button.get("y")) + float(button.get("height")) if button is not None else 838.61
    except (TypeError, ValueError):
        bx, by = 1323.43, 838.61
    x0, y0 = _svg_to_px(bx, by)
    x0 = int(round(x0))
    y0 = int(round(y0)) + _DROPDOWN_TOP_GAP
    h = len(labels) * (_DROPDOWN_ROW_H + _DROPDOWN_ROW_GAP) - _DROPDOWN_ROW_GAP
    patch = Image.new("RGBA", (_DROPDOWN_ROW_W, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(patch)
    font_path = resolve_digital7_font() or resolve_ui_font_bold()
    font = _load_font(font_path, _DROPDOWN_FONT_PX) if font_path else None
    for i, label in enumerate(labels):
        top = i * (_DROPDOWN_ROW_H + _DROPDOWN_ROW_GAP)
        selected = first + i == focus
        fill = (255, 255, 255, 255) if selected else (0x23, 0x1F, 0x20, 255)
        ink = (0, 0, 0, 255) if selected else (255, 255, 255, 255)
        draw.rounded_rectangle(
            (0, top, _DROPDOWN_ROW_W - 1, top + _DROPDOWN_ROW_H - 1),
            radius=_DROPDOWN_RADIUS,
            fill=fill,
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
    dropdown_root = copy.deepcopy(root) if getattr(st, "tz_dropdown_open", False) else None
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
    bg = _full_theme_bgra(st, assets_dir=assets_dir, path=path)
    frame = _composite_bgra_over_bgra(bg, ui_bgra)
    if frame is bg:
        frame = bg.copy()
    if dropdown_root is not None:
        _draw_timezone_dropdown(frame, st, dropdown_root)
    if clock:
        frame = draw_pigeon_settings_clock(frame)
    return frame


def pigeon_clock_label(now: datetime | None = None) -> str:
    """HH:MM:SS in Pigeon's timezone, 12/24 h per option1 (clocksaver rules)."""
    from pigeon.pigeon_locale import pigeon_now
    from pigeon.widgets.clock_saver import _time_label

    return _time_label(now if now is not None else pigeon_now())


def draw_pigeon_settings_clock(frame: np.ndarray, now: datetime | None = None) -> np.ndarray:
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
        color=(255, 255, 255, 255),
        canvas_w=w,
    )
    patch = np.asarray(img)[:, :, [2, 1, 0, 3]]
    out = frame.copy()
    out[top:bottom, x0 : x0 + w] = _composite_bgra_over_bgra(
        frame[top:bottom, x0 : x0 + w], patch
    )
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
    "OPTION_NUMBERS",
    "UI_COLOR_KEYS",
    "apply_pigeon_settings_svg_state",
    "clear_pigeon_settings_render_caches",
    "color_key_for_focus",
    "default_pigeon_settings_svg_path",
    "draw_pigeon_settings_clock",
    "factory_reset_pigeon_persisted_state",
    "normalize_pigeon_focus_id",
    "option_for_focus",
    "pigeon_clock_label",
    "pigeon_focus_ring",
    "render_pigeon_settings_bgra",
    "timezone_dropdown_rows",
    "version_label",
]
