"""
SVG tree primitives shared by the settings screens.

Illustrator-style layer-id encoding (``_x5F_`` etc.), logical-id lookup over an
``ElementTree`` (with a small per-tree index cache), visibility / pruning helpers
and fill / stroke style editing. Pure ``ElementTree`` + ``re`` helpers: no widget
state, theme, or rasterizer dependencies.

``pigeon.widgets.main_settings`` re-exports these names for existing importers.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from functools import lru_cache

_HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")
_AI_SUFFIX_RE = re.compile(r"_\d{20,}_?$")


def decode_svg_id(raw_id: str) -> str:
    """Decode Illustrator XML id encoding (``_x5F_`` → ``_``, ``_x30_`` → ``0``, …)."""
    if not raw_id:
        return ""
    out: list[str] = []
    i = 0
    n = len(raw_id)
    while i < n:
        if raw_id.startswith("_x5F_", i):
            out.append("_")
            i += 5
            continue
        if i + 5 <= n and raw_id[i] == "_" and raw_id[i + 1] == "x" and raw_id[i + 4] == "_":
            hx = raw_id[i + 2 : i + 4]
            try:
                out.append(chr(int(hx, 16)))
                i += 5
                continue
            except ValueError:
                pass
        out.append(raw_id[i])
        i += 1
    return "".join(out)


def encode_svg_id(logical_id: str) -> str:
    """Encode a logical layer id for Illustrator-style SVG ``id`` attributes."""
    if not logical_id:
        return ""
    body = logical_id
    if body.startswith("0"):
        body = "_x30_" + body[1:]

    def _enc_char(ch: str) -> str:
        if ch.isalnum() or ch in ".-|":
            return ch
        if ch == "_":
            return "_x5F_"
        return f"_x{ord(ch):02X}_"

    return "".join(_enc_char(c) for c in body)


def _strip_ai_uniqueness(decoded_id: str) -> str:
    """Drop Illustrator uniqueness suffixes like ``_0000016089…``."""
    return _AI_SUFFIX_RE.sub("", decoded_id)


@lru_cache(maxsize=16384)
def _normalize_logical(raw_or_logical: str) -> str:
    """Cache Illustrator id decode — each apply/raster normalizes the same ids thousands of times."""
    return _strip_ai_uniqueness(decode_svg_id(raw_or_logical))


def _parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    parents: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in parent:
            parents[child] = parent
    return parents


def _is_descendant_of(el: ET.Element, ancestor: ET.Element, parents: dict[ET.Element, ET.Element]) -> bool:
    cur: ET.Element | None = el
    while cur is not None:
        if cur is ancestor:
            return True
        cur = parents.get(cur)
    return False


def _find_by_id(root: ET.Element, layer_id: str) -> ET.Element | None:
    for el in root.iter():
        if el.get("id") == layer_id:
            return el
    return None


# Per-tree logical-id → elements. Built once; apply_state does hundreds of lookups
# on a ~3.7k-node SVG, and naive O(n) scans made each Pi invalidate multi-second.
_LOGICAL_INDEX_BY_ROOT: dict[int, tuple[ET.Element, dict[str, list[ET.Element]]]] = {}


def _invalidate_logical_index(root: ET.Element) -> None:
    _LOGICAL_INDEX_BY_ROOT.pop(id(root), None)


def _logical_id_index(root: ET.Element) -> dict[str, list[ET.Element]]:
    rid = id(root)
    hit = _LOGICAL_INDEX_BY_ROOT.get(rid)
    if hit is not None and hit[0] is root:
        return hit[1]
    index: dict[str, list[ET.Element]] = {}
    for el in root.iter():
        raw = el.get("id") or ""
        if not raw:
            continue
        index.setdefault(_normalize_logical(raw), []).append(el)
    if len(_LOGICAL_INDEX_BY_ROOT) >= 8:
        _LOGICAL_INDEX_BY_ROOT.clear()
    _LOGICAL_INDEX_BY_ROOT[rid] = (root, index)
    return index


def _find_by_logical_id(root: ET.Element, logical_id: str) -> ET.Element | None:
    """Match exact encoded id, raw logical id, or AI-suffixed variants."""
    want = _normalize_logical(logical_id)
    hits = _logical_id_index(root).get(want)
    if hits:
        return hits[0]
    encoded = encode_svg_id(logical_id)
    for el in root.iter():
        raw = el.get("id") or ""
        if not raw:
            continue
        if raw == encoded or raw == logical_id:
            return el
        if raw.startswith(encoded + "_") and _AI_SUFFIX_RE.search("_" + raw[len(encoded) + 1 :]):
            return el
    return None


def _find_all_by_logical_id(root: ET.Element, logical_id: str) -> list[ET.Element]:
    want = _normalize_logical(logical_id)
    indexed = _logical_id_index(root).get(want)
    if indexed:
        return list(indexed)
    hits: list[ET.Element] = []
    for el in root.iter():
        raw = el.get("id") or ""
        if not raw:
            continue
        decoded = decode_svg_id(raw)
        if decoded.startswith(want + "_") and _AI_SUFFIX_RE.search(decoded[len(want) :]):
            hits.append(el)
    return hits


def _set_visible(el: ET.Element | None, visible: bool) -> None:
    """Toggle visibility on ``el``.

    Hide marks only the subtree root — ``_prune_display_none`` drops the whole
    branch before PyMuPDF (which ignores inherited ``display``).

    Show clears ``display:none`` on the root and descendants that actually have
    it (Illustrator often bakes ``display:none`` into child ``style``). Skipping
    clean nodes keeps focus navigation cheap on Pi.
    """
    if el is None:
        return
    if not visible:
        el.set("display", "none")
        return
    for node in (el, *(child for child in el.iter() if child is not el)):
        had_attr = "display" in node.attrib
        style = node.get("style") or ""
        had_style = "display:" in style
        if not had_attr and not had_style:
            continue
        if had_attr:
            node.attrib.pop("display", None)
        if had_style:
            cleaned = re.sub(r"display\s*:\s*[^;]+;?\s*", "", style, flags=re.IGNORECASE)
            cleaned = cleaned.strip().rstrip(";")
            if cleaned:
                node.set("style", cleaned)
            elif "style" in node.attrib:
                node.attrib.pop("style")


def _prune_display_none(root: ET.Element) -> None:
    """Remove ``display:none`` subtrees before rasterize (PyMuPDF ignores display)."""
    parents = _parent_map(root)
    to_remove = [el for el in root.iter() if el.get("display") == "none"]
    for el in to_remove:
        parent = parents.get(el)
        if parent is not None:
            try:
                parent.remove(el)
            except ValueError:
                pass


def _remove_by_logical_id(root: ET.Element, logical_id: str) -> None:
    """Remove nodes (PyMuPDF ignores display:none on some groups)."""
    parents = _parent_map(root)
    for el in list(_find_all_by_logical_id(root, logical_id)):
        parent = parents.get(el)
        if parent is not None:
            try:
                parent.remove(el)
            except ValueError:
                pass


def _norm_hex(color: str | None) -> str | None:
    if not color:
        return None
    c = color.strip().lower()
    if c in ("none", "transparent"):
        return c
    if c in ("white", "#fff"):
        return "#ffffff"
    if c in ("black", "#000"):
        return "#000000"
    if c.startswith("url("):
        return None
    if not c.startswith("#") and _HEX_RE.match(f"#{c}"):
        c = f"#{c}"
    if c.startswith("#") and len(c) == 4:
        c = f"#{c[1]}{c[1]}{c[2]}{c[2]}{c[3]}{c[3]}"
    if c.startswith("#") and len(c) == 7:
        return c
    return c


def _rewrite_style_prop(style: str, prop: str, value: str) -> str:
    pat = re.compile(rf"{re.escape(prop)}\s*:\s*[^;\"']+", re.IGNORECASE)
    if pat.search(style):
        return pat.sub(f"{prop}:{value}", style)
    if style.strip():
        return f"{style.rstrip().rstrip(';')};{prop}:{value}"
    return f"{prop}:{value}"


def _set_paint(node: ET.Element, *, fill: str | None = None, stroke: str | None = None) -> None:
    style = node.get("style") or ""
    if fill is not None:
        if "fill:" in style:
            style = _rewrite_style_prop(style, "fill", fill)
        node.set("fill", fill)
    if stroke is not None:
        if "stroke:" in style:
            style = _rewrite_style_prop(style, "stroke", stroke)
        node.set("stroke", stroke)
    if style:
        node.set("style", style)


def _iter_style_fill_stroke(node: ET.Element) -> tuple[str | None, str | None]:
    fill = _norm_hex(node.get("fill"))
    stroke = _norm_hex(node.get("stroke"))
    style = node.get("style") or ""
    if style:
        fm = re.search(r"fill\s*:\s*([^;\"']+)", style, re.IGNORECASE)
        sm = re.search(r"stroke\s*:\s*([^;\"']+)", style, re.IGNORECASE)
        if fm:
            fill = _norm_hex(fm.group(1).strip()) or fill
        if sm:
            stroke = _norm_hex(sm.group(1).strip()) or stroke
    return fill, stroke


def _set_text_content(el: ET.Element | None, text: str) -> None:
    if el is None:
        return
    # Prefer nested <text> if this is a group.
    texts = [n for n in el.iter() if n.tag.endswith("text")]
    targets = texts if texts else ([el] if el.tag.endswith("text") else [])
    for t in targets:
        if len(t):
            for child in list(t):
                if child.tag.endswith("tspan"):
                    child.text = text
                    child.tail = None
            if not any(c.tag.endswith("tspan") for c in t):
                t.text = text
        else:
            t.text = text


def _style_has_display_none(style: str | None) -> bool:
    return bool(style and re.search(r"display\s*:\s*none", style, re.IGNORECASE))
