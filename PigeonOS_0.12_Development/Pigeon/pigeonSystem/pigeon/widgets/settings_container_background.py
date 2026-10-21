"""
Settings menu container background plate.

Finds the striped container artwork in the settings SVG, hides the vector stripes and
embedded backgrounds, and draws the rounded, cached BGRA plate (plus BGRA-over-BGRA
compositing) used behind the menu.

``pigeon.widgets.main_settings`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from pigeon.design import DESIGN_H, DESIGN_W
from pigeon.widgets.settings_search_overlays import _TRANSLATE_RE, _parse_svg_matrix
from pigeon.widgets.settings_state import COLOR_UI_DEFAULT
from pigeon.widgets.settings_svg_text import _style_prop
from pigeon.widgets.settings_svg_tree import (
    _find_by_logical_id,
    _norm_hex,
    _normalize_logical,
    _parent_map,
    _set_visible,
    _style_has_display_none,
)


# Baked stripe groups in settings_main (containerN) and settings_pigeon (menu_container_N).
_BACKGROUND_CONTAINERS: tuple[str, ...] = tuple(
    [f"container{i}" for i in range(1, 8)]
    + [f"menu_container_{i}" for i in range(1, 7)]
)


# Rounded menu container from ``settings_main.svg`` clip path (800×480 artboard).
_MENU_CONTAINER_BBOX: tuple[int, int, int, int] = (22, 110, 777, 426)


_MENU_CONTAINER_RADIUS_PX: int = 20


@dataclass(frozen=True)
class _ContainerStripeSpec:
    x_svg: float
    y_svg: float
    width_svg: float
    height_svg: float
    matrix: tuple[float, float, float, float, float, float]
    fill_hex: str


@lru_cache(maxsize=1)
def _menu_container_mask() -> np.ndarray:
    """Inside=255 mask for the red menu container (PyMuPDF inverts SVG clip-path)."""
    from PIL import Image, ImageDraw

    mask = Image.new("L", (DESIGN_W, DESIGN_H), 0)
    draw = ImageDraw.Draw(mask)
    x0, y0, x1, y1 = _MENU_CONTAINER_BBOX
    draw.rounded_rectangle((x0, y0, x1, y1), radius=_MENU_CONTAINER_RADIUS_PX, fill=255)
    return np.asarray(mask, dtype=np.uint8)


_CONTAINER_BG_PLATE_CACHE: dict[tuple[object, ...], np.ndarray] = {}


def _container_stripe_cache_key(stripes: tuple[_ContainerStripeSpec, ...]) -> tuple[object, ...]:
    return tuple(
        (
            round(s.x_svg, 3),
            round(s.y_svg, 3),
            round(s.width_svg, 3),
            round(s.height_svg, 3),
            tuple(round(v, 5) for v in s.matrix),
            s.fill_hex,
        )
        for s in stripes
    )


def _draw_container_background_bgra(
    bgra: np.ndarray,
    stripes: tuple[_ContainerStripeSpec, ...] | None = None,
    *,
    ui_hex: str | None = None,
    assets_dir: Path | str | None = None,
) -> None:
    """Paint black frame + UI-tinted theme slants (shared settings_background.svg).

    ``stripes`` is ignored (legacy baked SVG discovery); kept for call-site compat.
    """
    del stripes  # embedded chrome SVG stripes are no longer used
    from pigeon.widgets.settings_theme_background import (
        draw_settings_theme_background_bgra,
    )

    draw_settings_theme_background_bgra(
        bgra,
        ui_hex=ui_hex or COLOR_UI_DEFAULT,
        clip_mask=_menu_container_mask(),
        assets_dir=assets_dir,
    )


def _disable_embedded_settings_background_layers(root: ET.Element) -> None:
    """Hide/remove baked stripe + canvas background groups from chrome SVGs.

    All settings menus paint the shared ``settings_background.svg`` plate in code;
    embedded Illustrator stripe/background layers must never rasterize.
    """
    for cid in _BACKGROUND_CONTAINERS:
        el = _find_by_logical_id(root, cid)
        if el is not None:
            _set_visible(el, False)
    # Catch any leftover stripe groups by logical id prefix.
    for el in root.iter():
        logical = _normalize_logical(el.get("id") or "")
        if logical in ("background", "settings_background") or logical.startswith(
            ("container", "menu_container_")
        ):
            if el.tag.endswith("g") or el.tag.endswith("rect"):
                _set_visible(el, False)
    _hide_container_stripe_rects(root)
    _remove_canvas_background_rect(root)
    # Illustrator exports sometimes bake the canvas + diagonal stripes into
    # plain ``Layer_NN`` groups (e.g. settings_pigeon_ui_color 0815): sweep the
    # whole tree for slanted stripe rects and full-canvas plates so the shared
    # code-drawn theme background stays visible underneath.
    parents = _parent_map(root)
    for el in list(root.iter()):
        if not el.tag.endswith("rect"):
            continue
        transform = el.get("transform") or _style_prop(el.get("style") or "", "transform")
        is_slant_stripe = _parse_svg_slant_transform(transform) is not None
        try:
            w = float(el.get("width") or 0.0)
            h = float(el.get("height") or 0.0)
        except ValueError:
            w = h = 0.0
        is_canvas_plate = w >= 790.0 and h >= 470.0
        if is_slant_stripe or is_canvas_plate:
            parent = parents.get(el)
            if parent is not None:
                parent.remove(el)
    for lid in ("settings_background", "background"):
        el = _find_by_logical_id(root, lid)
        if el is not None:
            _set_visible(el, False)


def _composite_bgra_over_bgra(base: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    """Alpha-composite overlay onto base. Fast paths for empty / fully opaque pixels."""
    a = overlay[:, :, 3]
    if not np.any(a):
        return base
    out = base.copy()
    opaque = a == 255
    if np.any(opaque):
        out[opaque, :3] = overlay[opaque, :3]
        out[opaque, 3] = 255
    partial = (a > 0) & (a < 255)
    if np.any(partial):
        fg = overlay[partial].astype(np.float32)
        bg = out[partial].astype(np.float32)
        alpha = fg[:, 3:4] * (1.0 / 255.0)
        inv = 1.0 - alpha
        blended = fg[:, :3] * alpha + bg[:, :3] * inv
        out_a = np.clip(fg[:, 3] + bg[:, 3] * inv[:, 0], 0, 255)
        out[partial, :3] = blended
        out[partial, 3] = out_a
    return out.astype(np.uint8)


def _discover_container_stripe_specs(root: ET.Element, container_id: str) -> tuple[_ContainerStripeSpec, ...]:
    container = _find_by_logical_id(root, container_id)
    if container is None:
        return ()
    specs: list[_ContainerStripeSpec] = []
    for el in container.iter():
        if not el.tag.endswith("rect"):
            continue
        style = el.get("style") or ""
        if _style_has_display_none(style) or el.get("display") == "none":
            continue
        transform = el.get("transform") or _style_prop(style, "transform")
        matrix = _parse_svg_matrix(transform)
        if matrix is None:
            continue
        fill = _style_prop(style, "fill") or el.get("fill") or COLOR_UI_DEFAULT
        if not fill.startswith("#"):
            continue
        try:
            specs.append(
                _ContainerStripeSpec(
                    x_svg=float(el.get("x") or 0.0),
                    y_svg=float(el.get("y") or 0.0),
                    width_svg=float(el.get("width") or 0.0),
                    height_svg=float(el.get("height") or 0.0),
                    matrix=matrix,
                    fill_hex=fill.lower(),
                )
            )
        except (TypeError, ValueError):
            continue
    return tuple(specs)


def _parse_svg_slant_transform(
    transform: str | None,
) -> tuple[float, float, float, float, float, float] | None:
    """Parse ``matrix(...)`` or Illustrator ``translate(...) rotate(...)`` CTMs."""
    matrix = _parse_svg_matrix(transform)
    if matrix is not None:
        return matrix
    if not transform:
        return None
    m = _TRANSLATE_RE.search(transform)
    if not m:
        return None
    rot = re.search(r"rotate\(\s*([-\d.]+)\s*\)", transform, re.IGNORECASE)
    if rot is None:
        return None
    import math

    tx = float(m.group(1))
    ty = float(m.group(2) or 0.0)
    rad = math.radians(float(rot.group(1)))
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    return (cos_a, sin_a, -sin_a, cos_a, tx, ty)


def _hide_container_stripe_rects(
    root: ET.Element,
    container_ids: tuple[str, ...] | None = None,
) -> None:
    """Remove diagonal stripe rects and dim overlay plates before rasterize."""
    for cid in container_ids if container_ids is not None else _BACKGROUND_CONTAINERS:
        container = _find_by_logical_id(root, cid)
        if container is None:
            continue
        parents = _parent_map(root)
        for el in list(container.iter()):
            if not el.tag.endswith("rect"):
                continue
            style = el.get("style") or ""
            transform = el.get("transform") or _style_prop(style, "transform")
            if _parse_svg_slant_transform(transform) is not None:
                parent = parents.get(el)
                if parent is not None:
                    parent.remove(el)
                continue
            fill = _style_prop(style, "fill") or el.get("fill") or ""
            opacity = _style_prop(style, "opacity") or ""
            if _norm_hex(fill) == "#202020" or opacity.startswith("0.5"):
                parent = parents.get(el)
                if parent is not None:
                    parent.remove(el)


def _remove_canvas_background_rect(root: ET.Element) -> None:
    """Drop the full-canvas rect so PyMuPDF leaves transparency for compositing."""
    bg_group = _find_by_logical_id(root, "background")
    if bg_group is None:
        return
    parents = _parent_map(root)
    for el in list(bg_group.iter()):
        if el.tag.endswith("rect"):
            parent = parents.get(el)
            if parent is not None:
                parent.remove(el)
