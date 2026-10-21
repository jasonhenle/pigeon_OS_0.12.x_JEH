"""
Theme paint / contrast helpers for the settings SVG.

Applies the selected / deselected / accent / UI-brand colours to button groups, glyphs
and text layers of the settings SVG tree, and decides which colours count as UI-brand.

``pigeon.widgets.main_settings`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from pigeon.widgets.settings_state import (
    COLOR_ACCENT_DEFAULT,
    COLOR_DESELECTED,
    COLOR_INACTIVE,
    COLOR_SELECTED,
    COLOR_UI_DEFAULT,
    SettingsTheme,
)
from pigeon.widgets.settings_svg_tree import _iter_style_fill_stroke, _normalize_logical, _set_paint


COLOR_LEGACY_GREEN = "#02e900"


_BUTTON_FILL_CANDIDATES = frozenset(
    {
        COLOR_SELECTED.lower(),
        COLOR_DESELECTED.lower(),
        COLOR_LEGACY_GREEN.lower(),
        "#ffffff",
        "#000013",
        "#000000",
        "#202020",
        "#231f20",  # Illustrator keyboard button default
        "white",
        "black",
    }
)


_CONTRAST_SWAP_CANDIDATES = frozenset(
    {
        COLOR_SELECTED.lower(),
        COLOR_DESELECTED.lower(),
        COLOR_INACTIVE.lower(),
        COLOR_LEGACY_GREEN.lower(),
        "#ffffff",
        "#000013",
        "#000000",
        "#202020",
        "#404040",
        "white",
        "black",
    }
)


_UI_BRAND_COLORS = frozenset(
    {COLOR_UI_DEFAULT.lower(), "#4ea6f7", "#ff0013"}
)


def _theme_swatch_hexes() -> frozenset[str]:
    """Lazy import — ui_color palette expands button/accent swap candidates."""
    try:
        from pigeon.widgets.ui_color_settings import THEME_SWATCH_HEXES

        return THEME_SWATCH_HEXES
    except Exception:
        return frozenset()


def _is_ui_brand_color(hex_color: str | None) -> bool:
    if not hex_color:
        return False
    return hex_color.lower() in (_UI_BRAND_COLORS | _ui_recolor_hexes())


def _apply_button_fill(group: ET.Element | None, *, selected: bool, theme: SettingsTheme) -> None:
    if group is None:
        return
    fill = theme.selected if selected else theme.deselected
    for node in group.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in ("path", "rect", "polygon", "circle", "ellipse"):
            continue
        # Skip nested accent strokes that live under a *_button group by mistake.
        nid = _normalize_logical(node.get("id") or "")
        if nid.endswith("_accent") or "_accent_" in nid:
            continue
        cur_fill, _ = _iter_style_fill_stroke(node)
        if cur_fill is None or cur_fill in ("none", "transparent"):
            # Dual location/network use filled paths; still paint if attribute missing but path exists.
            if tag == "path" and (node.get("d") or "d" in (node.attrib or {})):
                if cur_fill in ("none", "transparent"):
                    continue
            else:
                continue
        if cur_fill in _BUTTON_FILL_CANDIDATES or cur_fill in (
            theme.selected.lower(),
            theme.deselected.lower(),
        ) or cur_fill in _theme_swatch_hexes():
            _set_paint(node, fill=fill)


def _apply_direct_glyph_contrast(
    group: ET.Element | None,
    *,
    selected: bool,
    theme: SettingsTheme,
    disabled: bool = False,
) -> None:
    """Paint glyphs directly: white selected, black deselected, gray disabled."""
    if group is None:
        return
    if disabled:
        color = theme.inactive
    else:
        color = theme.selected if selected else theme.deselected
    for node in group.iter():
        nid = _normalize_logical(node.get("id") or "")
        if nid.endswith("_accent") or "_accent_" in nid:
            continue
        tag = node.tag.rsplit("}", 1)[-1]
        fill, stroke = _iter_style_fill_stroke(node)
        if tag.endswith("text") and fill in (None, "none", "transparent"):
            fill = "#ffffff"
        swap = _CONTRAST_SWAP_CANDIDATES | _theme_swatch_hexes()
        if (
            fill
            and fill not in ("none", "transparent")
            and fill in swap
            and not _is_ui_brand_color(fill)
        ):
            _set_paint(node, fill=color)
        if (
            stroke
            and stroke not in ("none", "transparent")
            and stroke in swap
            and not _is_ui_brand_color(stroke)
        ):
            _set_paint(node, stroke=color)


def _apply_contrast_paint(
    group: ET.Element | None,
    *,
    selected: bool,
    theme: SettingsTheme,
    muted_deselected: bool = False,
) -> None:
    """Contrasting text/icons on buttons (white on black, black on white). Leaves accent alone.

    When ``muted_deselected`` is True (binary yes/no / later/now choices), deselected
    labels use grey (``theme.inactive``) on the black button instead of white.
    """
    if group is None:
        return
    if selected:
        contrast = theme.deselected
    elif muted_deselected:
        contrast = theme.inactive
    else:
        contrast = theme.selected
    swap = _CONTRAST_SWAP_CANDIDATES | _theme_swatch_hexes()
    for node in group.iter():
        nid = _normalize_logical(node.get("id") or "")
        if nid.endswith("_accent") or "_accent_" in nid:
            continue
        tag = node.tag.rsplit("}", 1)[-1]
        fill, stroke = _iter_style_fill_stroke(node)
        if tag.endswith("text") and fill in (None, "none", "transparent"):
            fill = "#ffffff"
        if (
            fill
            and fill not in ("none", "transparent")
            and fill in swap
            and not _is_ui_brand_color(fill)
        ):
            _set_paint(node, fill=contrast)
        if (
            stroke
            and stroke not in ("none", "transparent")
            and stroke in swap
            and not _is_ui_brand_color(stroke)
        ):
            _set_paint(node, stroke=contrast)


def _apply_accent_paint(group: ET.Element | None, accent: str) -> None:
    if group is None:
        return
    accent_swap = frozenset(
        {
            "#ffffff",
            "white",
            COLOR_ACCENT_DEFAULT.lower(),
            accent.lower(),
        }
    ) | _theme_swatch_hexes()
    for node in group.iter():
        fill, stroke = _iter_style_fill_stroke(node)
        if fill and fill not in ("none", "transparent"):
            if fill in accent_swap:
                _set_paint(node, fill=accent)
        if stroke and stroke not in ("none", "transparent"):
            if stroke in accent_swap:
                _set_paint(node, stroke=accent)


def _ui_recolor_hexes() -> frozenset[str]:
    """Hexes that count as the configurable UI/brand color on icon layers."""
    try:
        from pigeon.widgets.ui_color_settings import UI_SWATCH_HEXES

        return _UI_BRAND_COLORS | UI_SWATCH_HEXES
    except Exception:
        return _UI_BRAND_COLORS | {"red"}


def _apply_ui_brand_paint(group: ET.Element | None, ui_hex: str) -> None:
    """Recolor UI/brand fills/strokes under an icon group to ``theme.ui``.

    Child geometry often has no id (e.g. box2 play triangle polygon) — paint by
    current brand/swatch hex, not by requiring each node to be named ``*_icon``.
    """
    if group is None:
        return
    ui = (ui_hex or COLOR_UI_DEFAULT).lower()
    candidates = _ui_recolor_hexes() | {ui}
    for node in group.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in ("path", "rect", "polygon", "polyline", "circle", "ellipse", "line"):
            continue
        fill, stroke = _iter_style_fill_stroke(node)
        if fill and fill not in ("none", "transparent") and fill in candidates and fill != ui:
            _set_paint(node, fill=ui_hex)
        if (
            stroke
            and stroke not in ("none", "transparent")
            and stroke in candidates
            and stroke != ui
        ):
            _set_paint(node, stroke=ui_hex)
