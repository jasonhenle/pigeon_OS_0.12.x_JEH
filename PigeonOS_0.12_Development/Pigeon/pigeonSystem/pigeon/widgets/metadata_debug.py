"""
Metadata inspector — ``settings_0.8/pigeon_metadata.svg``.

Three stacked variants of one screen (player / hdmi / pigeon) that show, per
source, what Pigeon knows about the current title. Opened with [4]; forward /
backward steps player → hdmi → pigeon (no wrap); EXIT returns to the pigeon
settings grid; [4] again jumps to the legacy metadata view.

Data comes from a provider callback registered by ``pigeon_0_12`` (the widget
layer has no access to pyatv / HDMI state).
"""

from __future__ import annotations

import copy
import os
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import ImageFont

from pigeon.design import DESIGN_H, DESIGN_W
from pigeon.widgets.main_settings import (
    MainSettingsState,
    _MENU_CONTAINER_BBOX,
    _composite_bgra_over_bgra,
    _disable_embedded_settings_background_layers,
    _find_by_logical_id,
    _prune_display_none,
    _set_paint,
    _set_text_content,
    _set_visible,
    _truncate_text_to_width,
)
from pigeon.settings_layout import SETTINGS_BACKGROUND_SHIFT_Y, SETTINGS_CANVAS_ORIGIN
from pigeon.widgets.settings_svg_text import center_label_on_pill

# Same Illustrator board crop as settings_pigeon.svg so the panel lines up
# with the shared code-drawn theme background.
# 800×500 matches the 1280×800 canvas aspect (1.6). The old 800×480 box made
# PyMuPDF letterbox the shapes (uniform 1.6, +16 px) while the Pillow text
# overlay stretched y by 1.667, so labels drifted up to ~10 px off their pills
# (visible on EXIT). y0 moves up 10 units so shapes stay exactly where they were.
_METADATA_VIEWBOX = (363.7, 431.8, 800.0, 500.0)

_COLOR_STATUS_OK = "#0DFF00"
_COLOR_STATUS_BAD = "#FF0013"

# Page order for forward/backward stepping.
METADATA_DEBUG_PAGES: tuple[str, ...] = ("player", "hdmi", "pigeon")

# Row order matches the five field labels in the SVG (top → bottom).
_ROW_KEYS: tuple[str, ...] = ("service", "series", "title", "episode", "year")

# Artboard x of ``metadata_results`` (leaves a column for the % scores).
_RESULT_X_WITH_CONF_SVG = 860.24
# Artboard x of ``metadata_confidence`` — sit results here when % is hidden.
_RESULT_X_FLUSH_SVG = 801.09
# Keep italic values inside the shared red plate (bbox x1 = 777 design px).
_RESULT_RIGHT_PAD_SVG = 14.0
_RESULT_FONT_SIZE_PX = 24

_TRANSLATE_RE = re.compile(
    r"translate\(\s*([-\d.]+)(?:[,\s]+([-\d.]+))?\s*\)",
    re.IGNORECASE,
)

# (path, mtime_ns) → parsed template; deepcopy on return (callers mutate).
_SVG_TREE_TEMPLATES: dict[tuple[str, int], ET.Element] = {}
_SVG_TREE_TEMPLATE_MAX = 2

_THEME_BG_CACHE: dict[tuple[object, ...], np.ndarray] = {}
_THEME_BG_CACHE_MAX = 4

# Registered by pigeon_0_12; returns the live per-source rows + active flags.
_DATA_PROVIDER: Callable[[], dict[str, Any]] | None = None


def set_metadata_debug_data_provider(fn: Callable[[], dict[str, Any]] | None) -> None:
    global _DATA_PROVIDER
    _DATA_PROVIDER = fn


def metadata_debug_data() -> dict[str, Any]:
    """Snapshot from the registered provider (empty when unavailable)."""
    fn = _DATA_PROVIDER
    if fn is None:
        return {}
    try:
        data = fn()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def default_metadata_debug_svg_path(assets_dir: Path | str | None = None) -> Path:
    env = os.environ.get("PIGEON_METADATA_DEBUG_SVG", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if assets_dir is not None:
        return Path(assets_dir) / "settings_0.8" / "pigeon_metadata.svg"
    pigeon_root = Path(__file__).resolve().parents[3]
    return pigeon_root / "pigeonAssets" / "settings_0.8" / "pigeon_metadata.svg"


def _svg_tree_from_path(path: Path) -> ET.Element:
    path = Path(path)
    key = (str(path.resolve()), path.stat().st_mtime_ns)
    template = _SVG_TREE_TEMPLATES.get(key)
    if template is None:
        tree = ET.parse(path)
        root = tree.getroot()
        x, y, w, h = _METADATA_VIEWBOX
        root.set("viewBox", f"{x} {y} {w} {h}")
        root.set("width", str(DESIGN_W))
        root.set("height", str(DESIGN_H))
        if len(_SVG_TREE_TEMPLATES) >= _SVG_TREE_TEMPLATE_MAX:
            _SVG_TREE_TEMPLATES.clear()
        _SVG_TREE_TEMPLATES[key] = root
        template = root
    return copy.deepcopy(template)


def _group_texts(root: ET.Element, logical_id: str) -> list[ET.Element]:
    """Direct <text> children of a group, in document (top → bottom) order."""
    group = _find_by_logical_id(root, logical_id)
    if group is None:
        return []
    return [el for el in group if el.tag.endswith("text")]


def _set_flat_text(text_el: ET.Element | None, value: str) -> None:
    """Replace an Illustrator per-glyph-tspan text with one flat string."""
    if text_el is None:
        return
    for child in list(text_el):
        text_el.remove(child)
    text_el.text = value


def _row_value(rows: dict[str, Any], key: str) -> str:
    val = str(rows.get(key) or "").strip()
    return val if val else "—"


def _result_x_svg(*, show_confidence: bool) -> float:
    return _RESULT_X_WITH_CONF_SVG if show_confidence else _RESULT_X_FLUSH_SVG


def _result_max_right_svg() -> float:
    vb_x = _METADATA_VIEWBOX[0]
    return vb_x + float(_MENU_CONTAINER_BBOX[2]) - _RESULT_RIGHT_PAD_SVG


def _set_translate_x(el: ET.Element, x: float) -> None:
    transform = el.get("transform") or ""
    match = _TRANSLATE_RE.search(transform)
    y = float(match.group(2) or 0.0) if match else 0.0
    next_t = f"translate({x:.2f} {y:.2f})"
    if match:
        el.set("transform", _TRANSLATE_RE.sub(next_t, transform, count=1))
    else:
        el.set("transform", next_t)


@lru_cache(maxsize=1)
def _result_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    from pigeon.font_paths import resolve_ui_font_extrabold, resolve_ui_font_extrabold_italic

    path = resolve_ui_font_extrabold_italic() or resolve_ui_font_extrabold()
    if path:
        try:
            return ImageFont.truetype(str(path), _RESULT_FONT_SIZE_PX)
        except OSError:
            pass
    return ImageFont.load_default()


def _fit_result_text(value: str, *, x_svg: float) -> str:
    if value == "—":
        return value
    max_w_svg = max(8.0, _result_max_right_svg() - x_svg)
    max_w_px = max(8, int(round(max_w_svg * DESIGN_W / _METADATA_VIEWBOX[2])))
    fitted = _truncate_text_to_width(value, max_width_px=max_w_px, font=_result_font())
    return fitted or "—"


def _confidence_label(conf: dict[str, Any], key: str) -> str:
    raw = conf.get(key)
    if raw is None:
        return "—"
    try:
        pct = max(0.0, min(1.0, float(raw))) * 100.0
    except (TypeError, ValueError):
        return "—"
    return f"{int(round(pct))}%"


def _status_fill(el: ET.Element | None, ok: bool) -> None:
    if el is None:
        return
    _set_paint(el, fill=_COLOR_STATUS_OK if ok else _COLOR_STATUS_BAD)


def apply_metadata_debug_svg_state(
    root: ET.Element,
    state: MainSettingsState,
    data: dict[str, Any],
) -> None:
    page_idx = max(0, min(len(METADATA_DEBUG_PAGES) - 1, int(state.metadata_debug_page)))
    page = METADATA_DEBUG_PAGES[page_idx]

    player_active = bool(data.get("player_active"))
    hdmi_active = bool(data.get("hdmi_active"))
    pigeon_active = player_active or hdmi_active

    # The three icon tiles are stacked at the same spot — show the current one.
    icon_ids = {
        "player": "metadata_player_icon",
        "hdmi": "metadata_hdmi_icon",
        "pigeon": "metadata_pigeon_icon",
    }
    for name, lid in icon_ids.items():
        _set_visible(_find_by_logical_id(root, lid), name == page)

    # Status LEDs inside the player / hdmi tiles.
    _status_fill(
        _find_by_logical_id(root, "settings_pigeon_07_player_status_icon"),
        player_active,
    )
    _status_fill(
        _find_by_logical_id(root, "settings_pigeon_08_hdmi_status_icon"),
        hdmi_active,
    )
    # Pigeon differentiates itself with a colored stroke instead of an LED.
    _set_visible(
        _find_by_logical_id(root, "settings_pigeon_07_metadata_status_icon"), False
    )
    pigeon_btn = _find_by_logical_id(root, "settings_pigeon_07_metadata_button")
    if pigeon_btn is not None:
        _set_paint(
            pigeon_btn,
            stroke=_COLOR_STATUS_OK if pigeon_active else _COLOR_STATUS_BAD,
        )
        pigeon_btn.set("stroke-width", "5")

    # Duplicate results block from the export — always drive ``metadata_results``.
    _set_visible(_find_by_logical_id(root, "metadata_results_player"), False)

    rows = data.get(page)
    rows = rows if isinstance(rows, dict) else {}
    show_confidence = page == "pigeon"
    result_x = _result_x_svg(show_confidence=show_confidence)
    field_texts = _group_texts(root, "metadata_fields")
    result_texts = _group_texts(root, "metadata_results")
    for i, key in enumerate(_ROW_KEYS):
        show_row = not (page == "player" and key == "year")
        if i < len(field_texts):
            _set_visible(field_texts[i], show_row)
        if i < len(result_texts):
            _set_visible(result_texts[i], show_row)
            if show_row:
                _set_translate_x(result_texts[i], result_x)
                _set_flat_text(
                    result_texts[i],
                    _fit_result_text(_row_value(rows, key), x_svg=result_x),
                )

    # Per-row confidence column: pigeon page only.
    conf_group = _find_by_logical_id(root, "metadata_confidence")
    if show_confidence:
        _set_visible(conf_group, True)
        conf = rows.get("confidence")
        conf = conf if isinstance(conf, dict) else {}
        conf_texts = _group_texts(root, "metadata_confidence")
        for i, key in enumerate(_ROW_KEYS):
            if i < len(conf_texts):
                _set_flat_text(conf_texts[i], _confidence_label(conf, key))
    else:
        _set_visible(conf_group, False)

    # EXIT is the only actionable control on this screen — always highlighted.
    _sync_back_button(root, selected=True)
    _sync_version_text(root, state)


# EXIT / version chrome shared with the 0.8 settings_pigeon layers (the
# inspector art still uses them; the 0.11 settings_pigeon page does not).
_COLOR_WHITE = "#FFFFFF"
_COLOR_BLACK = "#000000"
_COLOR_BACK_FILL = "#202020"
# Board crop the version string is placed against (0.8 settings_pigeon).
_VERSION_VIEWBOX_XY = (
    SETTINGS_CANVAS_ORIGIN[0],
    SETTINGS_CANVAS_ORIGIN[1] - SETTINGS_BACKGROUND_SHIFT_Y,
)


def _paint_text(el: ET.Element | None, color: str) -> None:
    if el is None:
        return
    nodes = [el] if el.tag.endswith("text") else [
        n for n in el.iter() if n.tag.endswith("text") or n.tag.endswith("tspan")
    ]
    for node in nodes or [el]:
        _set_paint(node, fill=color)


def _sync_back_button(root: ET.Element, *, selected: bool) -> None:
    group = _find_by_logical_id(root, "settings_pigeon_back_group")
    scope = group if group is not None else root
    button = _find_by_logical_id(scope, "settings_pigeon_back_button")
    accent = _find_by_logical_id(scope, "settings_pigeon_back_accent")
    text = _find_by_logical_id(scope, "settings_pigeon_back_text")
    if button is not None:
        _set_paint(
            button,
            fill=_COLOR_WHITE if selected else _COLOR_BACK_FILL,
            stroke=_COLOR_BLACK,
        )
    if accent is not None:
        _set_paint(accent, fill="none", stroke=_COLOR_BLACK if selected else _COLOR_WHITE)
    _paint_text(text, _COLOR_BLACK if selected else _COLOR_WHITE)
    center_label_on_pill(text, button)


def _sync_version_text(root: ET.Element, state: MainSettingsState) -> None:
    from pigeon.version import version_string

    ver = str(getattr(state, "version_string", "") or version_string()).strip()
    if ver.lower().startswith("v"):
        ver = ver[1:].lstrip()
    label = f"PIGEON V {ver}" if ver else "PIGEON"
    text = _find_by_logical_id(root, "settings_pigeon_version_text")
    if text is None:
        return
    if not text.tag.endswith("text"):
        nested = next(
            (n for n in text.iter() if n is not text and n.tag.endswith("text")), None
        )
        text = nested if nested is not None else text
    _set_text_content(text, label)
    _paint_text(text, _COLOR_WHITE)
    vb_x, vb_y = _VERSION_VIEWBOX_XY
    text.set("transform", f"translate({vb_x + 1180.0:.2f} {vb_y + 159.0:.2f})")
    text.set("text-anchor", "end")
    text.attrib.pop("style", None)


def _full_theme_bgra(
    state: MainSettingsState,
    *,
    assets_dir: Path | str | None,
    path: Path,
) -> np.ndarray:
    from pigeon.widgets.main_settings import _draw_container_background_bgra

    ui_hex = str(getattr(state.theme, "ui", "#4EA6F7") or "#4EA6F7")
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


def render_metadata_debug_bgra(
    state: MainSettingsState | None = None,
    *,
    svg_path: Path | str | None = None,
    assets_dir: Path | str | None = None,
    data: dict[str, Any] | None = None,
) -> np.ndarray:
    path = (
        Path(svg_path)
        if svg_path is not None
        else default_metadata_debug_svg_path(assets_dir)
    )
    if not path.is_file():
        raise FileNotFoundError(f"metadata debug SVG not found: {path}")
    st = state if state is not None else MainSettingsState()
    payload = data if data is not None else metadata_debug_data()
    root = _svg_tree_from_path(path)
    apply_metadata_debug_svg_state(root, st, payload)
    _disable_embedded_settings_background_layers(root)
    _prune_display_none(root)
    from pigeon.widgets.settings_svg_text import rasterize_settings_svg_bgra

    ui_bgra = rasterize_settings_svg_bgra(
        root,
        width=DESIGN_W,
        height=DESIGN_H,
        font_mode="preferences",
    )
    bg = _full_theme_bgra(st, assets_dir=assets_dir, path=path)
    return _composite_bgra_over_bgra(bg, ui_bgra)


def clear_metadata_debug_render_caches() -> None:
    _SVG_TREE_TEMPLATES.clear()
    _THEME_BG_CACHE.clear()
