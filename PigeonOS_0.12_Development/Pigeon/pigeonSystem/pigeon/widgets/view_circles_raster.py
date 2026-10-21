"""
SVG parse cache and rasterizer for the now-playing widgets.

Loads widget SVGs into a small template cache (``_SVG_TEMPLATE_CACHE``, one deep copy per
call), rasterizes an ``ElementTree`` to BGRA at design scale, and un-canvases white
backgrounds. Owns the template cache; no widget state.

``pigeon.widgets.view_circles`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import copy
import io
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np

from pigeon.design import DESIGN_H, DESIGN_W


_SVG_W = 398.0


_SVG_H = 488.0


# (path, mtime_ns) → parsed template. Chrome rasters miss every second, so
# without this the SVG is re-read and re-parsed from disk once per tick.
_SVG_TEMPLATE_CACHE: dict[tuple[str, int], ET.Element] = {}


def _svg_tree_from_path(path: Path) -> ET.Element:
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = -1
    key = (str(path), mtime)
    template = _SVG_TEMPLATE_CACHE.get(key)
    if template is None:
        tree = ET.parse(path)
        template = tree.getroot()
        while len(_SVG_TEMPLATE_CACHE) >= 12:  # one slot per now-playing widget SVG
            _SVG_TEMPLATE_CACHE.pop(next(iter(_SVG_TEMPLATE_CACHE)))
        _SVG_TEMPLATE_CACHE[key] = template
    # Callers mutate the tree (strip layers, set text), so hand out a copy.
    return copy.deepcopy(template)


def _scale_raster_to_design(bgra: np.ndarray, src_w: int, src_h: int) -> np.ndarray:
    if bgra.shape[0] != src_h or bgra.shape[1] != src_w:
        bgra = cv2.resize(bgra, (src_w, src_h), interpolation=cv2.INTER_AREA)
    return cv2.resize(bgra, (int(DESIGN_W), int(DESIGN_H)), interpolation=cv2.INTER_AREA)


def _svg_viewbox_wh(root: ET.Element) -> tuple[int, int]:
    raw = (root.get("viewBox") or "").replace(",", " ").split()
    if len(raw) == 4:
        try:
            return max(1, int(round(float(raw[2])))), max(1, int(round(float(raw[3]))))
        except (TypeError, ValueError):
            pass
    return int(_SVG_W), int(_SVG_H)


def _rasterize_svg_tree(
    root: ET.Element, *, dest_w: int | None = None, dest_h: int | None = None
) -> np.ndarray:
    svg_bytes = ET.tostring(root, encoding="utf-8")
    vw, vh = _svg_viewbox_wh(root)
    src_w = int(dest_w) if dest_w is not None else vw
    src_h = int(dest_h) if dest_h is not None else vh
    last_err: Exception | None = None

    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=svg_bytes, filetype="svg")
        page = doc[0]
        pix = page.get_pixmap(
            matrix=fitz.Matrix(src_w / max(1e-6, page.rect.width), src_h / max(1e-6, page.rect.height)),
            alpha=True,
        )
        rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            bgra = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGRA)
        else:
            bgra = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGRA)
        if bgra.shape[1] != src_w or bgra.shape[0] != src_h:
            bgra = cv2.resize(bgra, (src_w, src_h), interpolation=cv2.INTER_AREA)
        return bgra
    except ImportError as exc:
        last_err = exc
    except Exception as exc:
        last_err = exc

    try:
        import cairosvg

        out = io.BytesIO()
        cairosvg.svg2png(
            bytestring=svg_bytes,
            write_to=out,
            output_width=src_w,
            output_height=src_h,
        )
        data = np.frombuffer(out.getvalue(), dtype=np.uint8)
        raw = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if raw is None:
            raise RuntimeError("SVG raster decode failed")
        if raw.ndim == 2:
            bgra = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGRA)
        elif raw.shape[2] == 3:
            bgra = cv2.cvtColor(raw, cv2.COLOR_BGR2BGRA)
        else:
            bgra = raw
        if bgra.shape[1] != src_w or bgra.shape[0] != src_h:
            bgra = cv2.resize(bgra, (src_w, src_h), interpolation=cv2.INTER_AREA)
        return bgra
    except ImportError as exc:
        last_err = exc
    except OSError as exc:
        last_err = exc
    except Exception as exc:
        last_err = exc

    msg = "view_circles needs PyMuPDF (pip install pymupdf) or cairosvg with system cairo."
    if last_err is not None:
        raise RuntimeError(msg) from last_err
    raise RuntimeError(msg)


def _decanvas_white_bgra(src: np.ndarray, *, threshold: int = 252) -> np.ndarray:
    """Punch out Illustrator page white, keeping intentional interior white fills.

    Only near-white pixels connected to the image border become transparent so
    solid white discs (e.g. ``zone*_clock_exterior_accent``) stay opaque.
    """
    if src is None or src.size == 0 or src.ndim != 3 or src.shape[2] < 4:
        return src
    out = src.copy()
    rgb = out[:, :, :3]
    white = (
        (rgb[:, :, 0] >= threshold)
        & (rgb[:, :, 1] >= threshold)
        & (rgb[:, :, 2] >= threshold)
    )
    if not bool(np.any(white)):
        return out
    h, w = white.shape
    # cv2.floodFill needs a 2-pixel border mask.
    flood_mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
    seed = (white.astype(np.uint8) * 255)
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if not white[y, x]:
            continue
        cv2.floodFill(
            seed,
            flood_mask,
            (int(x), int(y)),
            128,
            loDiff=0,
            upDiff=0,
            flags=cv2.FLOODFILL_FIXED_RANGE,
        )
    edge_white = seed == 128
    # Also treat any border white that flood missed (non-corner border seeds).
    if not bool(np.any(edge_white)):
        edge_white = white & False
        edge_white[0, :] = white[0, :]
        edge_white[-1, :] = white[-1, :]
        edge_white[:, 0] = white[:, 0]
        edge_white[:, -1] = white[:, -1]
    out[edge_white, 3] = 0
    return out
