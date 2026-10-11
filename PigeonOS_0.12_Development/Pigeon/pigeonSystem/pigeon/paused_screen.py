"""Pausesaver: dimmed TMDb backdrop + “paused” label plate.

Zone 10 is the full display. The same frame letterboxes into zone 6.
When audio is gone, zone 10 is backdrop-only: the plate sits in zone 4
and the zone 5 status bar stays on top.
"""

from __future__ import annotations

import weakref

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pigeon.compositing import cv_resize_interp, scale_uniform_letterbox
from pigeon.design import DESIGN_H, DESIGN_W

PAUSED_SCREEN_TEXT = "paused"
PAUSESAVER_BACKDROP_DIM = 0.72
_LIVE_BACKDROP: np.ndarray | None = None
_LIVE_BACKDROP_KEY = ""
# Reject all-black arrays so a missing still cannot count as “art”.
_ART_MIN_PEAK = 12
_ART_CHECK_CACHE: list[tuple[weakref.ref, bytes, bool]] = []
_ART_CHECK_CACHE_SIZE = 4
# Design-space (1280×800) inset from the frame bottom to the plate.
PAUSED_SCREEN_BAR_BOTTOM_PX = 50
PAUSED_SCREEN_BAR_PAD_X_PX = 48
PAUSED_SCREEN_BAR_PAD_Y_PX = 22
PAUSED_SCREEN_BAR_RADIUS_PX = 28


def cover_scale_and_crop(
    frame_bgr: np.ndarray, target_w: int, target_h: int
) -> np.ndarray:
    """Scale so *frame_bgr* fills ``target_w``×``target_h``, then center-crop.

    Square album art on a wide display is cropped top/bottom instead of
    pillarboxed. Landscape TMDb backdrops crop the sides the same way.
    """
    tw = max(1, int(target_w))
    th = max(1, int(target_h))
    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return np.zeros((th, tw, 3), dtype=np.uint8)
    src = np.ascontiguousarray(frame_bgr)
    if src.ndim == 2:
        src = cv2.cvtColor(src, cv2.COLOR_GRAY2BGR)
    elif src.ndim == 3 and src.shape[2] > 3:
        src = src[:, :, :3]
    src_h, src_w = int(src.shape[0]), int(src.shape[1])
    if src_h < 1 or src_w < 1:
        return np.zeros((th, tw, 3), dtype=np.uint8)
    scale = max(tw / float(src_w), th / float(src_h))
    nw = max(1, int(round(src_w * scale)))
    nh = max(1, int(round(src_h * scale)))
    resized = cv2.resize(
        src, (nw, nh), interpolation=cv_resize_interp(src_w, src_h, nw, nh)
    )
    x0 = max(0, (nw - tw) // 2)
    y0 = max(0, (nh - th) // 2)
    crop = resized[y0 : y0 + th, x0 : x0 + tw]
    ch, cw = int(crop.shape[0]), int(crop.shape[1])
    if ch == th and cw == tw:
        return crop
    out = np.zeros((th, tw, 3), dtype=np.uint8)
    out[: min(ch, th), : min(cw, tw)] = crop[: min(ch, th), : min(cw, tw)]
    return out


def paused_screen_scale(cap_h: int, *, design_h: int = DESIGN_H) -> float:
    return float(max(1, int(cap_h))) / float(max(1, int(design_h)))


def paused_screen_bar_rect(
    cap_w: int,
    cap_h: int,
    text_w: int,
    text_h: int,
    *,
    design_h: int = DESIGN_H,
) -> tuple[int, int, int, int, int]:
    """Return ``(x, y, w, h, radius)`` for the label plate in output pixels."""
    s = paused_screen_scale(cap_h, design_h=design_h)
    pad_x = max(8, int(round(PAUSED_SCREEN_BAR_PAD_X_PX * s)))
    pad_y = max(6, int(round(PAUSED_SCREEN_BAR_PAD_Y_PX * s)))
    bottom = max(8, int(round(PAUSED_SCREEN_BAR_BOTTOM_PX * s)))
    radius = max(8, int(round(PAUSED_SCREEN_BAR_RADIUS_PX * s)))
    bw = int(text_w) + 2 * pad_x
    bh = int(text_h) + 2 * pad_y
    max_w = max(1, int(cap_w) - 2 * bottom)
    if bw > max_w:
        bw = max_w
    bw = max(1, bw)
    bh = max(1, bh)
    x = (int(cap_w) - bw) // 2
    y = int(cap_h) - bottom - bh
    if y < 0:
        y = 0
        bh = min(bh, int(cap_h) - bottom)
    radius = min(radius, bw // 2, bh // 2)
    return (x, y, bw, bh, radius)


def _draw_paused_plate(
    image: Image.Image,
    *,
    text: str,
    font: ImageFont.ImageFont,
    x: int,
    y: int,
    bw: int,
    bh: int,
    radius: int,
    bbox: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    draw = ImageDraw.Draw(image)
    box = [x, y, x + bw, y + bh]
    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(box, radius=radius, fill=(0, 0, 0))
    else:
        draw.rectangle(box, fill=(0, 0, 0))
    tw = int(bbox[2] - bbox[0])
    th = int(bbox[3] - bbox[1])
    tx = x + (bw - tw) // 2 - int(bbox[0])
    ty = y + (bh - th) // 2 - int(bbox[1])
    draw.text((tx, ty), text, font=font, fill=(255, 255, 255))
    return (x, y, bw, bh)


def paint_paused_screen_label(
    image: Image.Image,
    *,
    text: str = PAUSED_SCREEN_TEXT,
    font: ImageFont.ImageFont,
    design_h: int = DESIGN_H,
) -> tuple[int, int, int, int]:
    """Draw a rounded black plate with *text*, 50 design-px above the frame bottom.

    Returns the plate ``(x, y, w, h)``.
    """
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = int(bbox[2] - bbox[0])
    th = int(bbox[3] - bbox[1])
    x, y, bw, bh, radius = paused_screen_bar_rect(
        image.width, image.height, tw, th, design_h=design_h
    )
    return _draw_paused_plate(
        image, text=text, font=font, x=x, y=y, bw=bw, bh=bh, radius=radius, bbox=bbox
    )


def paint_paused_screen_label_in_rect(
    image: Image.Image,
    rect_xywh: tuple[float, float, float, float],
    *,
    text: str = PAUSED_SCREEN_TEXT,
    font: ImageFont.ImageFont | None = None,
) -> tuple[int, int, int, int]:
    """Center the paused plate inside ``rect_xywh`` (image-pixel space)."""
    rx, ry, rw, rh = (int(round(v)) for v in rect_xywh)
    rw = max(1, rw)
    rh = max(1, rh)
    used = font if font is not None else _pausesaver_font(max(28, int(round(rh * 0.42))))
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), text, font=used)
    tw = int(bbox[2] - bbox[0])
    th = int(bbox[3] - bbox[1])
    pad_x = max(8, min(PAUSED_SCREEN_BAR_PAD_X_PX, max(8, rw // 8)))
    pad_y = max(6, min(PAUSED_SCREEN_BAR_PAD_Y_PX, max(6, rh // 6)))
    bw = min(rw, tw + 2 * pad_x)
    bh = min(rh, th + 2 * pad_y)
    bw = max(1, bw)
    bh = max(1, bh)
    x = rx + (rw - bw) // 2
    y = ry + (rh - bh) // 2
    radius = min(PAUSED_SCREEN_BAR_RADIUS_PX, bw // 2, bh // 2)
    return _draw_paused_plate(
        image, text=text, font=used, x=x, y=y, bw=bw, bh=bh, radius=radius, bbox=bbox
    )


def pausesaver_art_usable(frame_bgr: np.ndarray | None) -> bool:
    """True when *frame_bgr* is a real still, not an empty or all-black frame.

    Called several times per rendered frame on the same backdrop, so the
    answer is cached per array object. A sparse pixel sample guards against
    an array being repainted in place.
    """
    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return False
    try:
        probe = np.ascontiguousarray(frame_bgr[::37, ::53]).tobytes()
    except Exception:
        return _art_peak_ok(frame_bgr)
    for ref, cached_probe, ok in _ART_CHECK_CACHE:
        if ref() is frame_bgr and cached_probe == probe:
            return ok
    ok = _art_peak_ok(frame_bgr)
    try:
        _ART_CHECK_CACHE.insert(0, (weakref.ref(frame_bgr), probe, ok))
        del _ART_CHECK_CACHE[_ART_CHECK_CACHE_SIZE:]
    except TypeError:
        pass
    return ok


def _art_peak_ok(frame_bgr: np.ndarray) -> bool:
    src = np.ascontiguousarray(frame_bgr)
    if src.ndim == 2:
        peak = int(src.max())
    elif src.ndim == 3 and src.shape[2] >= 1:
        peak = int(src[:, :, : min(3, src.shape[2])].max())
    else:
        return False
    return peak >= _ART_MIN_PEAK


def set_pausesaver_backdrop(
    frame_bgr: np.ndarray | None,
    *,
    clear: bool = False,
    content_key: str = "",
) -> None:
    """Remember the last usable still. Empty updates do not wipe it unless ``clear``.

    A different ``content_key`` drops the previous title's still so YouTube /
    a new show cannot inherit a blank or leftover backdrop.
    """
    global _LIVE_BACKDROP, _LIVE_BACKDROP_KEY
    if clear:
        _LIVE_BACKDROP = None
        _LIVE_BACKDROP_KEY = ""
        return
    key = str(content_key or "").strip()
    has_frame = pausesaver_art_usable(frame_bgr)
    if key and _LIVE_BACKDROP_KEY and key != _LIVE_BACKDROP_KEY and not has_frame:
        _LIVE_BACKDROP = None
        _LIVE_BACKDROP_KEY = key
        return
    if not has_frame:
        return
    if _LIVE_BACKDROP is frame_bgr:
        if key:
            _LIVE_BACKDROP_KEY = key
        return
    prev = _LIVE_BACKDROP
    if (
        prev is not None
        and getattr(prev, "shape", None) == getattr(frame_bgr, "shape", None)
        and getattr(prev, "dtype", None) == getattr(frame_bgr, "dtype", None)
        and np.array_equal(prev, frame_bgr)
    ):
        if key:
            _LIVE_BACKDROP_KEY = key
        return
    _LIVE_BACKDROP = frame_bgr
    if key:
        _LIVE_BACKDROP_KEY = key


def pausesaver_backdrop() -> np.ndarray | None:
    return _LIVE_BACKDROP


def pausesaver_has_art() -> bool:
    return pausesaver_art_usable(_LIVE_BACKDROP)


def pausesaver_has_usable_art() -> bool:
    return pausesaver_art_usable(_LIVE_BACKDROP)


def _pausesaver_font(px: int, font: ImageFont.ImageFont | None = None) -> ImageFont.ImageFont:
    if font is not None:
        return font
    try:
        from pigeon.font_paths import resolve_ui_font_bold

        path = resolve_ui_font_bold()
        if path:
            return ImageFont.truetype(str(path), size=max(24, int(px)))
    except Exception:
        pass
    return ImageFont.load_default()


def compose_pausesaver_backdrop_bgr(
    width: int,
    height: int,
    backdrop_bgr: np.ndarray | None = None,
    *,
    dim: float = PAUSESAVER_BACKDROP_DIM,
) -> np.ndarray:
    """Dimmed TMDb backdrop covering ``width``×``height`` (no paused plate)."""
    tw = max(1, int(width))
    th = max(1, int(height))
    src = backdrop_bgr if backdrop_bgr is not None else _LIVE_BACKDROP
    if src is None or getattr(src, "size", 0) == 0:
        return np.zeros((th, tw, 3), dtype=np.uint8)
    lit = src
    d = max(0.0, min(1.0, float(dim)))
    if d < 0.999:
        lit = np.clip(lit.astype(np.float32) * d, 0, 255).astype(np.uint8)
    return cover_scale_and_crop(lit, tw, th)


def compose_pausesaver_bgr(
    width: int,
    height: int,
    backdrop_bgr: np.ndarray | None = None,
    *,
    font: ImageFont.ImageFont | None = None,
    dim: float = PAUSESAVER_BACKDROP_DIM,
    text: str = PAUSED_SCREEN_TEXT,
) -> np.ndarray:
    """Full-frame Pausesaver in BGR (zone 6 scale source: backdrop + bottom plate)."""
    tw = max(1, int(width))
    th = max(1, int(height))
    base = compose_pausesaver_backdrop_bgr(tw, th, backdrop_bgr, dim=dim)
    img = Image.fromarray(cv2.cvtColor(base, cv2.COLOR_BGR2RGB))
    used = _pausesaver_font(max(52, int(round(float(th) * 0.13))), font)
    paint_paused_screen_label(img, text=text, font=used)
    return cv2.cvtColor(np.asarray(img, dtype=np.uint8), cv2.COLOR_RGB2BGR)


def render_pausesaver_plate_bgra(
    width: int,
    height: int,
    *,
    font: ImageFont.ImageFont | None = None,
    text: str = PAUSED_SCREEN_TEXT,
) -> np.ndarray:
    """Black rounded “paused” plate centered in a transparent zone-sized patch."""
    tw = max(1, int(width))
    th = max(1, int(height))
    img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    used = font if font is not None else _pausesaver_font(max(28, int(round(th * 0.42))))
    paint_paused_screen_label_in_rect(img, (0, 0, tw, th), text=text, font=used)
    rgba = np.asarray(img, dtype=np.uint8)
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)


def render_pausesaver_bgra(
    width: int,
    height: int,
    backdrop_bgr: np.ndarray | None = None,
    *,
    font: ImageFont.ImageFont | None = None,
) -> np.ndarray:
    """Zone-10 Pausesaver letterboxed into ``width``×``height`` (zone 6)."""
    tw = max(1, int(width))
    th = max(1, int(height))
    full = compose_pausesaver_bgr(
        int(DESIGN_W), int(DESIGN_H), backdrop_bgr, font=font
    )
    scaled = scale_uniform_letterbox(full, tw, th)
    if scaled.ndim == 2:
        scaled = cv2.cvtColor(scaled, cv2.COLOR_GRAY2BGR)
    bgra = np.zeros((int(scaled.shape[0]), int(scaled.shape[1]), 4), dtype=np.uint8)
    bgra[:, :, :3] = scaled[:, :, :3]
    bgra[:, :, 3] = 255
    return bgra
