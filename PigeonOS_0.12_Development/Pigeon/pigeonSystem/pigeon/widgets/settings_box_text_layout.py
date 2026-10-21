"""
Text layout for the settings box columns (device names, IPs, result rows).

Centres / aligns SVG text layers, measures and truncates strings with Pillow fonts,
and lays out the device name / IP labels and search-result rows inside each box column.

``pigeon.widgets.main_settings`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

from pigeon.design import DESIGN_W
from pigeon.widgets.settings_search_overlays import _svg_scale
from pigeon.widgets.settings_svg_tree import _find_by_logical_id, _normalize_logical, _rewrite_style_prop, _set_text_content
from pigeon.widgets.settings_text_entry import _field_font, _field_font_size_px, _fit_text_font_size


# Illustrator export quirk: row 2 device art is named ``device1_text_<suffix>`` at y≈290.
_BOX_RESULT_ROW_Y_SVG: tuple[float, ...] = (264.0, 290.0, 316.0, 342.0, 368.0)


_BOX_RESULT_ROW_FONT_SIZE_SVG = 20.0


_BOX_RESULT_ROW_GAP_SVG = 6.0


_BOX_COLUMN_INNER_SVG: dict[int, tuple[float, float]] = {
    1: (60.0, 250.0),
    2: (310.0, 495.0),
    3: (555.0, 740.0),
}


_BOX_DEVICE_NAME_Y_SVG = 319.8984


_BOX_DEVICE_IP_Y_SVG = 359.6094


_BOX_DEVICE_NAME_FONT_SVG = 48.1346


_BOX_DEVICE_IP_FONT_SVG = 42.1177


_BOX_DEVICE_GROUPS: dict[int, str] = {
    1: "main_box1_device_group",
    2: "main_box2_device_group",
    3: "main_box3_device_group",
}


def _set_svg_text_centered(el: ET.Element, x_svg: float, y_svg: float) -> None:
    """Place SVG ``<text>`` at ``(x, y)`` with middle/middle anchoring for rasterize."""
    el.set("transform", f"matrix(1 0 0 1 {x_svg} {y_svg})")
    el.set("text-anchor", "middle")
    el.set("dominant-baseline", "middle")
    style = el.get("style") or ""
    style = re.sub(r"text-anchor\s*:\s*[^;]+;?\s*", "", style, flags=re.IGNORECASE)
    style = re.sub(r"dominant-baseline\s*:\s*[^;]+;?\s*", "", style, flags=re.IGNORECASE)
    style = style.strip().rstrip(";")
    if style:
        el.set("style", style)
    elif "style" in el.attrib:
        el.attrib.pop("style")


def _set_svg_text_horiz_centered(el: ET.Element, x_svg: float, y_svg: float) -> None:
    """Horizontally center text while preserving the original SVG baseline ``y``."""
    el.set("transform", f"matrix(1 0 0 1 {x_svg} {y_svg})")
    el.set("text-anchor", "middle")
    el.attrib.pop("dominant-baseline", None)
    style = el.get("style") or ""
    style = re.sub(r"text-anchor\s*:\s*[^;]+;?\s*", "", style, flags=re.IGNORECASE)
    style = re.sub(r"dominant-baseline\s*:\s*[^;]+;?\s*", "", style, flags=re.IGNORECASE)
    style = style.strip().rstrip(";")
    if style:
        el.set("style", style)
    elif "style" in el.attrib:
        el.attrib.pop("style")


def _set_svg_text_right_aligned(el: ET.Element, x_svg: float, y_svg: float) -> None:
    el.set("transform", f"matrix(1 0 0 1 {x_svg} {y_svg})")
    el.set("text-anchor", "end")
    el.attrib.pop("dominant-baseline", None)
    style = el.get("style") or ""
    style = re.sub(r"text-anchor\s*:\s*[^;]+;?\s*", "", style, flags=re.IGNORECASE)
    style = style.strip().rstrip(";")
    if style:
        el.set("style", style)
    elif "style" in el.attrib:
        el.attrib.pop("style")


def _set_svg_text_left_aligned(el: ET.Element, x_svg: float, y_svg: float) -> None:
    el.set("transform", f"matrix(1 0 0 1 {x_svg} {y_svg})")
    el.set("text-anchor", "start")
    el.attrib.pop("dominant-baseline", None)
    style = el.get("style") or ""
    style = re.sub(r"text-anchor\s*:\s*[^;]+;?\s*", "", style, flags=re.IGNORECASE)
    style = style.strip().rstrip(";")
    if style:
        el.set("style", style)
    elif "style" in el.attrib:
        el.attrib.pop("style")


def _result_row_font_size_px() -> int:
    return max(8, int(round(_svg_scale(_BOX_RESULT_ROW_FONT_SIZE_SVG))))


def _truncate_text_to_width(text: str, *, max_width_px: int, font: ImageFont.FreeTypeFont) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    if probe.textlength(raw, font=font) <= max_width_px:
        return raw
    ell = "..."
    if probe.textlength(ell, font=font) >= max_width_px:
        return ell
    lo, hi = 0, len(raw)
    best = ell
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = raw[:mid].rstrip() + ell
        if probe.textlength(cand, font=font) <= max_width_px:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _result_row_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _field_font({"font": "digital7"}, _result_row_font_size_px())


def _text_width_px(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> float:
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    return float(probe.textlength(str(text or ""), font=font))


def _px_to_svg_x(px: float) -> float:
    from pigeon.design import legacy_fit_origin, legacy_fit_scale

    ox, _oy = legacy_fit_origin()
    s = legacy_fit_scale()
    if s <= 1e-6:
        return 0.0
    return (float(px) - ox) / s


def _format_box_result_device_name(name: str, *, box_num: int, ip_width_svg: float = 0.0) -> str:
    bounds = _BOX_COLUMN_INNER_SVG.get(box_num)
    if bounds is None:
        bounds = (280.0, 418.0)
    x0, x1 = bounds
    gap_svg = _BOX_RESULT_ROW_GAP_SVG if ip_width_svg > 0.0 else 0.0
    max_w_svg = max(8.0, (x1 - x0) - gap_svg - ip_width_svg - 8.0)
    max_w = max(24, int(round(max_w_svg * DESIGN_W / 800.0)))
    font = _result_row_font()
    return _truncate_text_to_width(name, max_width_px=max_w, font=font)


def _apply_box_result_row_text_layout(
    dev_el: ET.Element | None,
    ip_el: ET.Element | None,
    *,
    name: str,
    ip: str,
    row: int,
    box_num: int,
) -> None:
    if row < 1 or row > len(_BOX_RESULT_ROW_Y_SVG):
        return
    bounds = _BOX_COLUMN_INNER_SVG.get(box_num)
    if bounds is None:
        return
    x0, x1 = bounds
    center_svg = (x0 + x1) * 0.5
    y_svg = _BOX_RESULT_ROW_Y_SVG[row - 1]
    font = _result_row_font()
    gap_svg = _BOX_RESULT_ROW_GAP_SVG

    if ip_el is None or not str(ip or "").strip():
        display = _format_box_result_device_name(name, box_num=box_num)
        if dev_el is not None:
            _set_text_content(dev_el, display)
            _set_svg_text_horiz_centered(dev_el, center_svg, y_svg)
        return

    ip_display = str(ip)
    ip_w_svg = _px_to_svg_x(_text_width_px(ip_display, font))
    dev_display = _format_box_result_device_name(name, box_num=box_num, ip_width_svg=ip_w_svg)
    dev_w_svg = _px_to_svg_x(_text_width_px(dev_display, font))
    total_svg = dev_w_svg + gap_svg + ip_w_svg
    start_svg = center_svg - total_svg * 0.5
    dev_right_svg = start_svg + dev_w_svg
    ip_left_svg = dev_right_svg + gap_svg

    if dev_el is not None:
        _set_text_content(dev_el, dev_display)
        _set_svg_text_right_aligned(dev_el, dev_right_svg, y_svg)
    if ip_el is not None:
        _set_text_content(ip_el, ip_display)
        _set_svg_text_left_aligned(ip_el, ip_left_svg, y_svg)


def _set_svg_text_font_size_px(el: ET.Element, size_px: int) -> None:
    targets = [el] if el.tag.endswith("text") else [n for n in el.iter() if n.tag.endswith("text")]
    for node in targets:
        style = node.get("style") or ""
        node.set("style", _rewrite_style_prop(style, "font-size", f"{max(6, int(size_px))}px"))


def _box_column_inner_svg(box_num: int) -> tuple[float, float]:
    return _BOX_COLUMN_INNER_SVG.get(box_num, (310.0, 495.0))


def _layout_box_device_label(
    el: ET.Element | None,
    *,
    text: str,
    box_num: int,
    kind: str,
) -> None:
    """Center device name/IP inside a box column and shrink to fit."""
    raw = str(text or "").strip()
    if el is None or not raw:
        return
    x0, x1 = _box_column_inner_svg(box_num)
    center_svg = (x0 + x1) * 0.5
    y_svg = _BOX_DEVICE_NAME_Y_SVG if kind == "name" else _BOX_DEVICE_IP_Y_SVG
    font_svg = _BOX_DEVICE_NAME_FONT_SVG if kind == "name" else _BOX_DEVICE_IP_FONT_SVG
    max_w = max(24, int(round((x1 - x0 - 8.0) * DESIGN_W / 800.0)))
    start_px = _field_font_size_px(font_svg)
    size_px, font = _fit_text_font_size(
        raw,
        lambda px: _field_font({"font": "digital7"}, px),
        max_width_px=max_w,
        start_px=start_px,
    )
    display = _truncate_text_to_width(raw, max_width_px=max_w, font=font)
    _set_text_content(el, display)
    for node in el.iter():
        if not node.tag.endswith("text"):
            continue
        _set_svg_text_horiz_centered(node, center_svg, y_svg)
        _set_svg_text_font_size_px(node, size_px)


def _apply_box_device_group_layout(
    root: ET.Element,
    box_num: int,
    *,
    name: str = "",
    ip: str = "",
) -> None:
    group = _find_box_device_group(root, box_num)
    if group is None:
        return
    name_el: ET.Element | None = None
    ip_el: ET.Element | None = None
    for el in group.iter():
        logical = _normalize_logical(el.get("id") or "")
        if not _is_device_label_logical(logical):
            continue
        if logical.endswith("_device_name_text"):
            name_el = el
        elif logical.endswith("_device_ip_text"):
            ip_el = el
    if name:
        _layout_box_device_label(name_el, text=name, box_num=box_num, kind="name")
    if ip:
        _layout_box_device_label(ip_el, text=ip, box_num=box_num, kind="ip")


def _is_device_label_logical(logical: str) -> bool:
    """Primary device name / IP labels inside a box column."""
    if not logical:
        return False
    if logical.endswith("_device_name_text") or logical.endswith("_device_ip_text"):
        return True
    return logical in ("main_device_name_text", "main_device_ip_text")


def _find_box_device_group(root: ET.Element, box_num: int) -> ET.Element | None:
    want = _BOX_DEVICE_GROUPS.get(box_num, "")
    if not want:
        return None
    hit = _find_by_logical_id(root, want)
    if hit is not None:
        return hit
    prefix = f"main_box{box_num}_device_group"
    for el in root.iter():
        logical = _normalize_logical(el.get("id") or "")
        if logical == prefix or logical.startswith(f"{prefix}_"):
            return el
    return None
