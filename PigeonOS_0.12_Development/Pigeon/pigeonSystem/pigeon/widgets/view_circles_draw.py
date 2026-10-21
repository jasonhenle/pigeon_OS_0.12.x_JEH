"""
Raster drawing helpers for the now-playing widgets.

Font loaders, text / timecode patch builders, BGRA paste / restore / fade helpers,
rounded rects and bars, shimmer and candy-stripe fills, annular sectors, progress rings
and circle pairs. Functions take explicit arguments (frames, patches, themes); none read
widget state, so the SVG widget in ``view_circles`` composes them.

``pigeon.widgets.view_circles`` re-exports every name here for existing importers
(``clock_saver``, ``update_popup``, ``preferences_settings``, ``vu_meters``, tests).
"""

from __future__ import annotations

import math
import weakref
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pigeon.compositing import alpha_blend_bgra_over_bgr, blend_bgra_over_bgr_u8
from pigeon.design import DESIGN_H, DESIGN_W
from pigeon.font_paths import (
    resolve_digital7_font,
    resolve_ui_font_extrabold,
    resolve_ui_font_extrabold_italic,
    resolve_ui_font_light_italic,
    resolve_ui_font_medium_italic,
    resolve_ui_font_semibold,
    resolve_ui_font_semibold_italic,
)
from pigeon.np_layout import (
    STATUS_BAR_TRACK,
    STATUS_BAR_VIEW_H,
    STATUS_BAR_VIEW_W,
    TT_COUNTDOWN_TEXT_SIZE_PX,
    VOLUME_INNER_R,
    VOLUME_OUTER_R,
    design_rect_from_local,
    tabular_time_layout,
    WIDGET_SHIMMER_BAND_FRAC,
    WIDGET_SHIMMER_OPACITY,
)
from pigeon.widgets.view_circles_theme import (
    _COLOR_ACCENT_BGR,
    _COLOR_CENTER_BLACK_BGR,
    _COLOR_CHROME_BGR,
    _COLOR_UNFILLED_BGR,
    _NpTheme,
    _look_chrome_rgb,
    _look_is_bright,
    _zone_spec,
    np_theme_from_settings,
)


_RING_OUTER_R = VOLUME_OUTER_R


_RING_INNER_R = VOLUME_INNER_R


_ACCENT_OPACITY = 0.70


_ACCENT_STROKE_PX = 2


_ACCENT_STROKE_OPACITY = 0.12


# Date / audio-config baselines sit this many px above the widget exterior top.
_WIDGET_LABEL_BASELINE_GAP_PX = 20.0


@lru_cache(maxsize=32)
def _load_digital7(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    px = max(6, int(size))
    path = resolve_digital7_font()
    candidates: list[str] = []
    if path:
        candidates.append(str(path))
    for fallback in (
        "/usr/share/fonts/truetype/digital-7/digital-7.ttf",
        "/Library/Fonts/Digital-7.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if fallback not in candidates:
            candidates.append(fallback)
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, px)
        except OSError:
            continue
    return ImageFont.load_default()


@lru_cache(maxsize=32)
def _load_sharp_extrabold(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    px = max(6, int(size))
    path = resolve_ui_font_extrabold()
    if path:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            pass
    return _load_sharp_italic(px)


# Zone 6/7 TT slot when TMDb found no TT and no poster (instead of the typed title).
NP_PIGEON_LOGO_FILENAME = "pigeon_logo_np.png"


@lru_cache(maxsize=2)
def _load_np_pigeon_logo_bgra(path: str) -> np.ndarray | None:
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None or img.ndim != 3 or img.shape[2] != 4:
        return None
    return img


@lru_cache(maxsize=8)
def _load_sharp_semibold(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    px = max(6, int(size))
    path = resolve_ui_font_semibold()
    if path:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            pass
    return _load_sharp_extrabold(px)


@lru_cache(maxsize=8)
def _load_sharp_italic(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    px = max(6, int(size))
    path = resolve_ui_font_extrabold_italic()
    if path:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            pass
    return _load_digital7(px)


@lru_cache(maxsize=8)
def _load_sharp_medium_italic(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    px = max(6, int(size))
    path = resolve_ui_font_medium_italic()
    if path:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            pass
    return _load_sharp_italic(px)


@lru_cache(maxsize=8)
def _load_sharp_light_italic(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    px = max(6, int(size))
    path = resolve_ui_font_light_italic()
    if path:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            pass
    return _load_sharp_italic(px)


# Synthetic oblique slant (tan 12°) when no Semibold Italic cut is installed.
_TT_ITALIC_SHEAR = 0.2126


@lru_cache(maxsize=8)
def _load_sharp_semibold_italic(
    size: int,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    """(font, needs_synthetic_shear) for the countdown's Semibold Italic."""
    px = max(6, int(size))
    path = resolve_ui_font_semibold_italic()
    if path:
        try:
            return ImageFont.truetype(path, px), False
        except OSError:
            pass
    return _load_sharp_semibold(px), True


def _shear_italic_bgra(patch: np.ndarray, shear: float = _TT_ITALIC_SHEAR) -> np.ndarray:
    """Lean a rendered text patch to the right (synthetic oblique)."""
    if patch is None or patch.size == 0:
        return patch
    h, w = patch.shape[:2]
    extra = int(math.ceil(float(shear) * h))
    if extra <= 0:
        return patch
    # x' = x + shear * (h - y): baseline stays put, the top leans right.
    m = np.array([[1.0, -float(shear), float(shear) * h], [0.0, 1.0, 0.0]], dtype=np.float32)
    return cv2.warpAffine(
        patch,
        m,
        (w + extra, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )


def _tt_countdown_time_patch(
    text: str,
    *,
    size_px: int = TT_COUNTDOWN_TEXT_SIZE_PX,
    fill_rgb: tuple[int, int, int] = (255, 255, 255),
) -> np.ndarray:
    """Countdown readout in Sharp Sans Semibold Italic with tabular digits.

    Every digit is drawn centered inside an equal-width cell (the widest
    digit's advance) so the readout stays perfectly column-aligned while it
    counts down. When no true italic cut exists, the roman Semibold is
    sheared into a synthetic oblique.
    """
    label = str(text or "")
    if not label:
        return np.zeros((1, 1, 4), dtype=np.uint8)
    font, synthetic = _load_sharp_semibold_italic(int(size_px))
    probe = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    digit_cell = max(float(draw.textlength(d, font=font)) for d in "0123456789")
    char_widths = {ch: float(draw.textlength(ch, font=font)) for ch in set(label)}
    cells, total_w = tabular_time_layout(
        label, digit_cell_w=digit_cell, char_widths=char_widths
    )
    try:
        ascent, descent = font.getmetrics()
    except AttributeError:
        ascent, descent = int(size_px), max(2, int(size_px) // 4)
    pad = 2
    img = Image.new(
        "RGBA",
        (int(math.ceil(total_w)) + pad * 2, int(ascent + descent) + pad * 2),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(img)
    for ch, cell_x, cell_w in cells:
        natural = char_widths.get(ch, cell_w)
        gx = pad + cell_x + (cell_w - natural) / 2.0
        draw.text((gx, pad), ch, font=font, fill=(*fill_rgb, 255))
    arr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)
    if synthetic:
        arr = _shear_italic_bgra(arr)
    return arr


def _text_patch_digital7(
    text: str,
    *,
    size_px: int,
    fill_rgb: tuple[int, int, int] | None = None,
    max_width_px: int | None = None,
) -> tuple[np.ndarray, int, int]:
    if fill_rgb is None:
        fill_rgb = _look_chrome_rgb()
    draw_text = str(text or "")
    if not draw_text:
        return np.zeros((1, 1, 4), dtype=np.uint8), 0, 0
    font = _load_digital7(size_px)
    pad = 2
    probe = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)

    def _measure(s: str) -> tuple[int, int, int, int]:
        return draw.textbbox((0, 0), s, font=font)

    if max_width_px is not None and max_width_px > 0:
        l, t, r, b = _measure(draw_text)
        if (r - l) > max_width_px:
            ell = "..."
            for n in range(len(draw_text), 0, -1):
                candidate = draw_text[:n].rstrip() + ell
                l2, t2, r2, b2 = _measure(candidate)
                if (r2 - l2) <= max_width_px:
                    draw_text = candidate
                    break

    l, t, r, b = _measure(draw_text)
    tw, th = max(1, r - l), max(1, b - t)
    img = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((pad - l, pad - t), draw_text, font=font, fill=(*fill_rgb, 255))
    arr = np.asarray(img)
    return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGRA), tw + pad * 2, th + pad * 2


def _text_patch_font(
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill_rgb: tuple[int, int, int] | None = None,
) -> tuple[np.ndarray, int, int]:
    if fill_rgb is None:
        fill_rgb = _look_chrome_rgb()
    draw_text = str(text or "")
    if not draw_text:
        return np.zeros((1, 1, 4), dtype=np.uint8), 0, 0
    pad = 2
    probe = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    l, t, r, b = draw.textbbox((0, 0), draw_text, font=font)
    tw, th = max(1, r - l), max(1, b - t)
    img = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((pad - l, pad - t), draw_text, font=font, fill=(*fill_rgb, 255))
    arr = np.asarray(img)
    return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGRA), tw + pad * 2, th + pad * 2


def _fade_bgra(patch: np.ndarray, opacity: float) -> np.ndarray:
    """Return a copy with alpha multiplied by ``opacity`` (clamped to 0..1)."""
    if patch is None or patch.size == 0 or patch.ndim < 3 or patch.shape[2] < 4:
        return patch
    o = max(0.0, min(1.0, float(opacity)))
    if o >= 0.999:
        return patch
    out = patch.copy()
    out[:, :, 3] = np.clip(
        out[:, :, 3].astype(np.float32) * o, 0.0, 255.0
    ).astype(np.uint8)
    return out


def _black_rounded_plate(w: int, h: int) -> np.ndarray:
    """Opaque black rounded rectangle (BGRA), anti-aliased by 4x supersampling."""
    import cv2

    w, h = max(2, int(w)), max(2, int(h))
    k = 4
    big = np.zeros((h * k, w * k), np.uint8)
    r = int(min(w, h) * 0.5 * 0.7) * k
    cv2.rectangle(big, (r, 0), (w * k - 1 - r, h * k - 1), 255, -1)
    cv2.rectangle(big, (0, r), (w * k - 1, h * k - 1 - r), 255, -1)
    for cx, cy in ((r, r), (w * k - 1 - r, r), (r, h * k - 1 - r), (w * k - 1 - r, h * k - 1 - r)):
        cv2.circle(big, (cx, cy), r, 255, -1)
    alpha = cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA)
    out = np.zeros((h, w, 4), np.uint8)
    out[:, :, 3] = alpha
    return out


def _paste_patch_bgra(canvas: np.ndarray, patch: np.ndarray, x: int, y: int) -> None:
    if patch is None or patch.size == 0 or canvas is None or canvas.size == 0:
        return
    ph, pw = patch.shape[:2]
    if pw < 1 or ph < 1:
        return
    x0 = int(x)
    y0 = int(y)
    x1 = x0 + pw
    y1 = y0 + ph
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1 = min(int(canvas.shape[1]), x1)
    cy1 = min(int(canvas.shape[0]), y1)
    if cx0 >= cx1 or cy0 >= cy1:
        return
    sx0 = cx0 - x0
    sy0 = cy0 - y0
    src = patch[sy0 : sy0 + (cy1 - cy0), sx0 : sx0 + (cx1 - cx0)]
    roi = canvas[cy0:cy1, cx0:cx1]
    if roi.ndim == 3 and roi.shape[2] == 3:
        if src.shape[2] < 4:
            roi[:] = src[:, :, :3]
            return
        alpha_u8 = src[:, :, 3]
        if int(alpha_u8.max()) <= 0:
            return
        if int(alpha_u8.min()) >= 255:
            roi[:] = src[:, :, :3]
            return
        roi[:] = blend_bgra_over_bgr_u8(roi, src)
    elif roi.ndim == 3 and roi.shape[2] >= 4:
        blended = alpha_blend_bgra_over_bgr(roi[:, :, :3], src)
        roi[:, :, :3] = blended
        roi[:, :, 3] = np.maximum(roi[:, :, 3], src[:, :, 3])


def _restore_masked_region(
    canvas: np.ndarray,
    under: np.ndarray,
    mask: np.ndarray,
    *,
    x: int,
    y: int,
) -> None:
    if (
        canvas is None
        or canvas.size == 0
        or under is None
        or under.size == 0
        or mask is None
        or mask.size == 0
    ):
        return
    mh, mw = mask.shape[:2]
    if under.shape[0] != mh or under.shape[1] != mw:
        return
    x0 = int(x)
    y0 = int(y)
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1 = min(int(canvas.shape[1]), x0 + mw)
    cy1 = min(int(canvas.shape[0]), y0 + mh)
    if cx0 >= cx1 or cy0 >= cy1:
        return
    sx0, sy0 = cx0 - x0, cy0 - y0
    m = mask[sy0 : sy0 + (cy1 - cy0), sx0 : sx0 + (cx1 - cx0)] > 0
    if not np.any(m):
        return
    src = under[sy0 : sy0 + (cy1 - cy0), sx0 : sx0 + (cx1 - cx0)]
    roi = canvas[cy0:cy1, cx0:cx1]
    roi[m] = src[m]


def _restore_from_backdrop_abs(
    canvas: np.ndarray,
    mask: np.ndarray,
    *,
    x: int,
    y: int,
    backdrop: np.ndarray,
    backdrop_x: int,
    backdrop_y: int,
) -> None:
    if (
        canvas is None
        or canvas.size == 0
        or backdrop is None
        or backdrop.size == 0
        or mask is None
        or mask.size == 0
    ):
        return
    mh, mw = mask.shape[:2]
    bh, bw = int(backdrop.shape[0]), int(backdrop.shape[1])
    x0, y0 = int(x), int(y)
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1 = min(int(canvas.shape[1]), x0 + mw)
    cy1 = min(int(canvas.shape[0]), y0 + mh)
    if cx0 >= cx1 or cy0 >= cy1:
        return
    sx0, sy0 = cx0 - x0, cy0 - y0
    roi_h, roi_w = cy1 - cy0, cx1 - cx0
    m = mask[sy0 : sy0 + roi_h, sx0 : sx0 + roi_w] > 0
    if not np.any(m):
        return
    yy, xx = np.nonzero(m)
    by = (cy0 - int(backdrop_y)) + yy
    bx = (cx0 - int(backdrop_x)) + xx
    valid = (by >= 0) & (by < bh) & (bx >= 0) & (bx < bw)
    if not np.any(valid):
        return
    yy, xx, by, bx = yy[valid], xx[valid], by[valid], bx[valid]
    canvas[cy0 + yy, cx0 + xx] = backdrop[by, bx]


def _paste_stroke_over_blur(
    canvas: np.ndarray,
    stroke_patch: np.ndarray,
    x: int,
    y: int,
    *,
    backdrop: np.ndarray | None,
    backdrop_x: int,
    backdrop_y: int,
    opacity: float,
) -> None:
    if stroke_patch is None or stroke_patch.size == 0:
        return
    coverage = stroke_patch[:, :, 3]
    if not np.any(coverage):
        return
    if backdrop is not None:
        _restore_from_backdrop_abs(
            canvas,
            coverage,
            x=x,
            y=y,
            backdrop=backdrop,
            backdrop_x=backdrop_x,
            backdrop_y=backdrop_y,
        )
    sop = max(0.0, min(1.0, float(opacity)))
    if sop >= 1.0 - 1e-6:
        _paste_patch_bgra(canvas, stroke_patch, x, y)
        return
    patch = stroke_patch.copy()
    patch[:, :, 3] = np.clip(patch[:, :, 3].astype(np.float32) * sop, 0, 255).astype(
        np.uint8
    )
    _paste_patch_bgra(canvas, patch, x, y)


def _ink_crop_bgra(patch: np.ndarray, *, pad: int = 1) -> np.ndarray:
    """Trim transparent padding so centering uses the visible ink box."""
    if patch is None or patch.size == 0 or patch.ndim < 3 or patch.shape[2] < 4:
        return patch
    ys, xs = np.where(patch[:, :, 3] > 8)
    if ys.size == 0:
        return patch
    y0 = max(0, int(ys.min()) - pad)
    x0 = max(0, int(xs.min()) - pad)
    y1 = min(int(patch.shape[0]), int(ys.max()) + 1 + pad)
    x1 = min(int(patch.shape[1]), int(xs.max()) + 1 + pad)
    return patch[y0:y1, x0:x1]


def _paste_ink_centered(
    canvas: np.ndarray, patch: np.ndarray, cx: float, top_y: float
) -> None:
    """Paste ``patch`` horizontally centered on ``cx`` with its top at ``top_y``."""
    if patch is None or patch.size == 0:
        return
    ph, pw = patch.shape[:2]
    _paste_patch_bgra(
        canvas, patch, int(round(float(cx) - pw / 2.0)), int(round(float(top_y)))
    )


def _cast_line_patch(text: str, *, size_px: int, max_width_px: int) -> np.ndarray | None:
    label = str(text or "").strip()
    if not label:
        return None
    patch, tw, _th = _text_patch_digital7(
        label.upper(), size_px=size_px, max_width_px=max_width_px
    )
    if tw < 1:
        return None
    return _ink_crop_bgra(patch)


ZONE4_VISUALIZER_WIDGET = "visualizer"


# Wide zone-6 visualizer (pigeon.fullscreen_viz presets scaled into zone 6).
ZONE6_VISUALIZER_WIDGET = "visualizer_zone6"


def _weak_or_none(arr: object) -> weakref.ref | None:
    try:
        return weakref.ref(arr)
    except TypeError:
        return None


def _same_source_art(src_ref: weakref.ref | None, arr: object, kept: np.ndarray | None) -> bool:
    """True when *arr* is the array last copied into *kept*, pixels unchanged.

    Callers pass the same cached poster / TT array every frame; a full
    ``array_equal`` against the private copy cost ~10% of the Pi 5 render
    thread. A sparse sample guards against an in-place repaint.
    """
    if src_ref is None or kept is None or src_ref() is not arr:
        return False
    a = arr  # type: ignore[assignment]
    if getattr(a, "dtype", None) != np.uint8 or getattr(a, "shape", None) != kept.shape:
        return False
    return bool(np.array_equal(a[::23, ::19], kept[::23, ::19]))  # type: ignore[index]


def zone4_visualizer_rect() -> tuple[int, int, int, int, int]:
    """``(x, y, w, h, r)`` for the zone-4 EQ: the status-bar track's columns
    and corner radius, from the track's inset below zone 4's top down to the
    same gap above the zone-5 track (zone 4's box overlaps zone 5)."""
    tx, ty, tw, _th, tr = design_rect_from_local(
        _zone_spec(5),
        STATUS_BAR_TRACK,
        view_w=STATUS_BAR_VIEW_W,
        view_h=STATUS_BAR_VIEW_H,
    )
    zone = _zone_spec(4)
    inset = float(STATUS_BAR_TRACK[1]) * float(zone.h) / float(STATUS_BAR_VIEW_H)
    top = int(round(float(zone.y) + inset))
    bottom = int(round(float(ty) - inset))
    return (int(tx), top, int(tw), max(2, bottom - top), int(tr))


def _zone4_title_xywh() -> tuple[int, int, int, int]:
    """Zone 4 box clipped so titles stay above zone 5 (the strips overlap in spec)."""
    z4 = _zone_spec(4)
    z5 = _zone_spec(5)
    x = int(round(z4.x))
    y = int(round(z4.y))
    w = max(1, int(round(z4.w)))
    gap = 12.0
    h = min(float(z4.h), float(z5.y) - float(z4.y) - gap)
    return x, y, w, max(8, int(round(h)))


# Line 2 starts here so artist/album sit under the title and use the rest of
# the strip (down to the status bar gap).
_ZONE4_SUBTITLE_TOP_FRAC = 0.40


def _draw_stacked_cast_pair(
    canvas: np.ndarray,
    *,
    actor: str,
    character: str,
    cx: float,
    max_width_px: int,
    actor_px: int,
    char_px: int,
    gap_px: int,
    mid_y: float | None = None,
    actor_top: float | None = None,
    char_top: float | None = None,
) -> None:
    """Actor over character, both horizontally centered on ``cx``.

    Either ``mid_y`` (v-center the stack) or explicit ``actor_top`` / ``char_top``.
    """
    ap = _cast_line_patch(actor, size_px=actor_px, max_width_px=max_width_px)
    cp = _cast_line_patch(character, size_px=char_px, max_width_px=max_width_px)
    ah = int(ap.shape[0]) if ap is not None else 0
    ch = int(cp.shape[0]) if cp is not None else 0
    gap = int(gap_px) if ap is not None and cp is not None else 0
    if mid_y is not None:
        total = ah + gap + ch
        top = float(mid_y) - total * 0.5
        if ap is not None:
            _paste_ink_centered(canvas, ap, cx, top)
        if cp is not None:
            _paste_ink_centered(canvas, cp, cx, top + ah + gap)
        return
    if ap is not None and actor_top is not None:
        _paste_ink_centered(canvas, ap, cx, float(actor_top))
    if cp is not None and char_top is not None:
        _paste_ink_centered(canvas, cp, cx, float(char_top))


def _paste_left_vcenter(canvas: np.ndarray, patch: np.ndarray, x: float, cy: float) -> None:
    """Paste left-aligned with the patch's vertical center on ``cy``."""
    if patch is None or patch.size == 0:
        return
    ph, _pw = patch.shape[:2]
    _paste_patch_bgra(canvas, patch, int(round(float(x))), int(round(float(cy) - ph / 2.0)))


def _paste_centered(canvas: np.ndarray, patch: np.ndarray, cx: float, cy: float) -> None:
    if patch is None or patch.size == 0:
        return
    ph, pw = patch.shape[:2]
    _paste_patch_bgra(canvas, patch, int(round(cx - pw / 2.0)), int(round(cy - ph / 2.0)))


def _paste_baseline_centered(
    canvas: np.ndarray,
    patch: np.ndarray,
    cx: float,
    baseline_y: float,
    *,
    bbox_top: float,
    pad: int = 2,
) -> None:
    """Paste a text patch so its typographic baseline sits on ``baseline_y``.

    Patches from :func:`_text_patch_font` / :func:`_text_patch_digital7` are built
    with Pillow's default (non-``ls``) metrics. For those, the ink bottom is the
    practical baseline for caps-only strings — place the patch so its bottom edge
    lands on ``baseline_y`` (keeps labels clear of circular widgets).
    """
    if patch is None or patch.size == 0:
        return
    ph, pw = patch.shape[:2]
    paste_x = int(round(cx - pw / 2.0))
    # Default Pillow metrics (SharpSans/Digital-7): positive bbox top means the
    # old ``pad - t`` baseline formula pushed ink into the widget. Prefer ink
    # bottom == baseline for label clearance above rings.
    if float(bbox_top) >= 0:
        paste_y = int(round(float(baseline_y) - float(ph)))
    else:
        paste_y = int(round(float(baseline_y) - (float(pad) - float(bbox_top))))
    _paste_patch_bgra(canvas, patch, paste_x, paste_y)


def _paste_baseline_left(
    canvas: np.ndarray,
    patch: np.ndarray,
    x: float,
    baseline_y: float,
    *,
    bbox_top: float,
    pad: int = 2,
) -> None:
    """Paste a text patch left-aligned with its ink bottom on ``baseline_y``."""
    if patch is None or patch.size == 0:
        return
    ph, _pw = patch.shape[:2]
    paste_x = int(round(float(x)))
    if float(bbox_top) >= 0:
        paste_y = int(round(float(baseline_y) - float(ph)))
    else:
        paste_y = int(round(float(baseline_y) - (float(pad) - float(bbox_top))))
    _paste_patch_bgra(canvas, patch, paste_x, paste_y)


def _paste_label_above_widget(
    canvas: np.ndarray,
    patch: np.ndarray,
    cx: float,
    *,
    widget_top_y: float,
    gap_px: float = _WIDGET_LABEL_BASELINE_GAP_PX,
) -> None:
    """Paste so the patch bottom (≈ baseline) is ``gap_px`` above the widget top."""
    if patch is None or patch.size == 0:
        return
    ph, pw = patch.shape[:2]
    paste_x = int(round(cx - pw / 2.0))
    paste_y = int(round(float(widget_top_y) - float(gap_px) - float(ph)))
    _paste_patch_bgra(canvas, patch, paste_x, paste_y)


def _paste_label_above_circle_curved(
    canvas: np.ndarray,
    patch: np.ndarray,
    cx: float,
    *,
    widget_cy: float,
    widget_r: float,
    gap_px: float = _WIDGET_LABEL_BASELINE_GAP_PX,
) -> None:
    """Paste label in a flat-top / curved-bottom envelope above a circular widget.

    Same width and topline as the flat paste. Each column is scaled uniformly so
    the bottom edge rides the concentric arc ``widget_r + gap`` (Illustrator-style
    envelope distort — not a bottom-only stretch, which causes spike artifacts).
    """
    if patch is None or patch.size == 0 or canvas is None or canvas.size == 0:
        return
    src_full = np.asarray(patch)
    if src_full.ndim != 3 or src_full.shape[2] < 4:
        return

    # Tight-crop to opaque ink so the glyph body fills the cap (pad would
    # leave the curved baseline sitting in empty space).
    alpha = src_full[:, :, 3]
    rows = np.where(alpha.max(axis=1) > 8)[0]
    cols = np.where(alpha.max(axis=0) > 8)[0]
    if rows.size < 1 or cols.size < 1:
        return
    r0, r1 = int(rows[0]), int(rows[-1]) + 1
    c0, c1 = int(cols[0]), int(cols[-1]) + 1
    src = np.ascontiguousarray(src_full[r0:r1, c0:c1])
    ph, pw = int(src.shape[0]), int(src.shape[1])
    if ph < 1 or pw < 1:
        return

    full_h, full_w = int(src_full.shape[0]), int(src_full.shape[1])
    r_arc = float(widget_r) + float(gap_px)
    if r_arc <= 1.0:
        _paste_label_above_widget(
            canvas,
            src_full,
            cx,
            widget_top_y=float(widget_cy) - float(widget_r),
            gap_px=gap_px,
        )
        return

    widget_top = float(widget_cy) - float(widget_r)
    # Match the previous flat paste's ink topline (skip transparent pad above glyphs).
    top_y = widget_top - float(gap_px) - float(full_h) + float(r0)
    x0_full = float(cx) - float(full_w) / 2.0
    x0 = x0_full + float(c0)

    xs = (x0 + 0.5) + np.arange(pw, dtype=np.float64)
    dx = xs - float(cx)
    inside = np.abs(dx) < (r_arc - 1e-3)
    # Default to a rectangular bottom; replace with the circle arc where valid.
    bottoms = np.full(pw, top_y + float(ph), dtype=np.float64)
    bottoms[inside] = float(widget_cy) - np.sqrt(
        np.maximum(0.0, r_arc * r_arc - dx[inside] * dx[inside])
    )
    # Never crush below the natural glyph height (keeps center from squashing).
    heights = np.maximum(bottoms - top_y, float(ph))
    dest_h = int(math.ceil(float(np.max(heights)))) + 1
    if dest_h < 1:
        return

    yy = np.arange(dest_h, dtype=np.float64)[:, None]
    xx = np.arange(pw, dtype=np.float64)[None, :]
    valid = yy < heights[None, :]

    # Uniform vertical envelope: each column maps [0, h) → full source [0, ph).
    h = np.maximum(heights[None, :], 1e-3)
    if ph <= 1:
        v_src = np.zeros((dest_h, pw), dtype=np.float64)
    else:
        v_src = (yy + 0.5) / h * float(ph) - 0.5
        v_src = np.clip(v_src, 0.0, float(ph - 1))

    map_x = np.broadcast_to(xx.astype(np.float32), (dest_h, pw)).copy()
    map_y = v_src.astype(np.float32)
    map_x = np.where(valid, map_x, np.float32(-1.0))
    map_y = np.where(valid, map_y, np.float32(-1.0))

    warped = cv2.remap(
        src,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    if warped.dtype != np.uint8:
        warped = np.clip(warped, 0, 255).astype(np.uint8)
    warped = np.ascontiguousarray(warped)
    if warped.shape[2] >= 4:
        warped[~valid, :] = 0

    _paste_patch_bgra(
        canvas,
        warped,
        int(round(x0)),
        int(round(top_y)),
    )


def _font_bbox_top(text: str, font: ImageFont.ImageFont) -> float:
    probe = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    _l, t, _r, _b = draw.textbbox((0, 0), str(text or ""), font=font)
    return float(t)


def _rounded_rect_mask(w: int, h: int, radius: int) -> np.ndarray:
    if w < 1 or h < 1:
        return np.zeros((max(0, h), max(0, w)), dtype=np.uint8)
    r = max(0, min(radius, min(w, h) // 2))
    mask = np.zeros((h, w), dtype=np.uint8)
    if r <= 0:
        mask[:, :] = 255
        return mask
    cv2.rectangle(mask, (r, 0), (w - r - 1, h - 1), 255, -1)
    cv2.rectangle(mask, (0, r), (w - 1, h - r - 1), 255, -1)
    cv2.circle(mask, (r, r), r, 255, -1, lineType=cv2.LINE_AA)
    cv2.circle(mask, (w - r - 1, r), r, 255, -1, lineType=cv2.LINE_AA)
    cv2.circle(mask, (r, h - r - 1), r, 255, -1, lineType=cv2.LINE_AA)
    cv2.circle(mask, (w - r - 1, h - r - 1), r, 255, -1, lineType=cv2.LINE_AA)
    return mask


def _shimmer_colors_bgr() -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if _look_is_bright():
        return (214, 214, 214), (246, 246, 246)
    return (38, 38, 38), (86, 86, 86)


def _shimmer_base_patch_bgra(w: int, h: int, *, radius: int) -> np.ndarray:
    """Static skeleton plate (no highlight) for the cached NP frame."""
    w = max(1, int(w))
    h = max(1, int(h))
    mask = _rounded_rect_mask(w, h, max(1, int(radius)))
    base, _hi = _shimmer_colors_bgr()
    patch = np.zeros((h, w, 4), dtype=np.uint8)
    patch[:, :, 0] = base[0]
    patch[:, :, 1] = base[1]
    patch[:, :, 2] = base[2]
    patch[:, :, 3] = np.minimum(
        mask,
        np.uint8(int(round(255.0 * float(WIDGET_SHIMMER_OPACITY)))),
    )
    return patch


def _shimmer_patch_bgra(
    w: int,
    h: int,
    *,
    radius: int,
    phase: float,
    colors_bgr: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None,
) -> np.ndarray:
    """Rounded skeleton plate with a left-to-right highlight sweep."""
    w = max(1, int(w))
    h = max(1, int(h))
    mask = _rounded_rect_mask(w, h, max(1, int(radius)))
    base, hi = colors_bgr or _shimmer_colors_bgr()
    xs = np.arange(w, dtype=np.float32)
    band = max(12.0, float(w) * float(WIDGET_SHIMMER_BAND_FRAC))
    center = float(phase) * (float(w) + band) - band * 0.5
    t = np.clip(1.0 - np.abs(xs - center) / (band * 0.5), 0.0, 1.0)
    t = t * t * (3.0 - 2.0 * t)
    mix = np.broadcast_to(t, (h, w))
    patch = np.zeros((h, w, 4), dtype=np.uint8)
    for i, (b, hlt) in enumerate(zip(base, hi)):
        patch[:, :, i] = np.clip(
            np.rint(b + (hlt - b) * mix), 0, 255
        ).astype(np.uint8)
    alpha = np.minimum(
        mask,
        np.uint8(int(round(255.0 * float(WIDGET_SHIMMER_OPACITY)))),
    )
    patch[:, :, 3] = alpha
    return patch


_CANDY_U_CACHE: dict[tuple[int, int], np.ndarray] = {}


_CANDY_STEPS = 48


@lru_cache(maxsize=_CANDY_STEPS * 2)
def _candy_stripe_step_bgra(
    w: int, h: int, radius: int, step: int, color_bgr: tuple[int, int, int]
) -> np.ndarray:
    return _candy_stripe_patch_bgra(
        w, h, radius=radius, phase=step / float(_CANDY_STEPS), color_bgr=color_bgr
    )


def _candy_stripe_patch_bgra(
    w: int,
    h: int,
    *,
    radius: int,
    phase: float,
    color_bgr: tuple[int, int, int],
) -> np.ndarray:
    """Rounded bar of diagonal hard-edged stripes (UI color / a darker shade) scrolling right."""
    w = max(1, int(w))
    h = max(1, int(h))
    u = _CANDY_U_CACHE.get((w, h))
    if u is None:
        u = (np.arange(w, dtype=np.float32)[None, :] + np.arange(h, dtype=np.float32)[:, None])
        if len(_CANDY_U_CACHE) >= 4:
            _CANDY_U_CACHE.clear()
        _CANDY_U_CACHE[(w, h)] = u
    period = max(8.0, float(h) * 1.1)
    d = np.mod(u - float(phase) * period, period)
    half = period * 0.5
    # Signed distance to the nearest stripe edge (+ inside the light stripe), antialiased.
    e = np.where(d < half, np.minimum(d, half - d), -np.minimum(d - half, period - d))
    mix = np.clip(e * 0.7 + 0.5, 0.0, 1.0)[:, :, None]
    light = np.array(color_bgr, dtype=np.float32)
    dark = light * 0.55
    rgb = dark + (light - dark) * mix
    patch = np.empty((h, w, 4), dtype=np.uint8)
    patch[:, :, :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)
    patch[:, :, 3] = _rounded_rect_mask(w, h, max(1, int(radius)))
    return patch


def _draw_shimmer_rounded_rect(
    out: np.ndarray,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    radius: int,
    phase: float | None = None,
    recorder: object | None = None,
    colors_bgr: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None,
) -> None:
    if w < 2 or h < 2:
        return
    if recorder is not None:
        recorder(int(x), int(y), int(w), int(h), int(max(1, radius)))
    patch = (
        _shimmer_patch_bgra(w, h, radius=radius, phase=float(phase), colors_bgr=colors_bgr)
        if phase is not None
        else _shimmer_base_patch_bgra(w, h, radius=radius)
    )
    _paste_patch_bgra(out, patch, int(x), int(y))


def _draw_rounded_bar_bgra(
    bgra: np.ndarray,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    fill_bgr: tuple[int, int, int],
    radius: int,
    stroke_bgr: tuple[int, int, int] | None = None,
    stroke: int = 2,
    fill_opacity: float = 1.0,
    stroke_opacity: float = 1.0,
    stroke_backdrop: np.ndarray | None = None,
    stroke_backdrop_x: int = 0,
    stroke_backdrop_y: int = 0,
) -> None:
    if w < 1 or h < 1:
        return
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(int(DESIGN_W), x + w), min(int(DESIGN_H), y + h)
    if x0 >= x1 or y0 >= y1:
        return
    lw, lh = x1 - x0, y1 - y0
    pad = max(0, int(stroke) + 1) if stroke_bgr is not None and stroke > 0 else 0
    mw, mh = lw + pad * 2, lh + pad * 2
    mask = np.zeros((mh, mw), dtype=np.uint8)
    inner = _rounded_rect_mask(lw, lh, min(radius, lw // 2, lh // 2))
    mask[pad : pad + lh, pad : pad + lw] = inner
    fill_a = int(round(255.0 * max(0.0, min(1.0, float(fill_opacity)))))
    fill = np.zeros((mh, mw, 4), dtype=np.uint8)
    fill[mask > 0, :3] = fill_bgr
    fill[mask > 0, 3] = fill_a
    _paste_patch_bgra(bgra, fill, x0 - pad, y0 - pad)
    if stroke_bgr is not None and stroke > 0:
        stroke_patch = np.zeros((mh, mw, 4), dtype=np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            cv2.drawContours(
                stroke_patch,
                contours,
                -1,
                (*stroke_bgr, 255),
                thickness=max(1, int(stroke)),
                lineType=cv2.LINE_AA,
            )
            _paste_stroke_over_blur(
                bgra,
                stroke_patch,
                x0 - pad,
                y0 - pad,
                backdrop=stroke_backdrop,
                backdrop_x=stroke_backdrop_x,
                backdrop_y=stroke_backdrop_y,
                opacity=stroke_opacity,
            )


def annular_sector_mask(
    size: int,
    *,
    outer_r: float,
    inner_r: float,
    fraction: float,
    start_deg: float = -90.0,
    round_end: bool = False,
) -> np.ndarray:
    """Filled annulus from ``start_deg`` clockwise by ``fraction`` of a turn.

    ``round_end`` caps the leading edge with a near-semicircle (the origin edge
    stays straight).
    """
    s = max(1, int(size))
    mask = np.zeros((s, s), dtype=np.uint8)
    frac = max(0.0, min(1.0, float(fraction)))
    if frac <= 1e-6:
        return mask
    cx_i = (s - 1) // 2
    cy_i = (s - 1) // 2
    outer = max(1, int(round(outer_r)))
    inner = max(0, min(int(round(inner_r)), outer - 1))
    cv2.circle(mask, (cx_i, cy_i), outer, 255, -1, lineType=cv2.LINE_AA)
    if inner > 0:
        cv2.circle(mask, (cx_i, cy_i), inner, 0, -1, lineType=cv2.LINE_AA)
    if frac >= 0.999:
        return mask
    sweep = 360.0 * frac
    start = float(start_deg)
    end = start + sweep
    arc = cv2.ellipse2Poly(
        (cx_i, cy_i),
        (outer + 2, outer + 2),
        0,
        int(round(start)),
        int(round(end)),
        1,
    )
    wedge = np.zeros((s, s), dtype=np.uint8)
    poly = np.vstack([[[cx_i, cy_i]], arc])
    cv2.fillPoly(wedge, [poly], 255)
    sector = cv2.bitwise_and(mask, wedge)
    if round_end and outer - inner >= 2:
        _add_round_sector_end(sector, cx=cx_i, cy=cy_i, outer=outer, inner=inner, start=start, sweep=sweep)
    return sector


# Cap radius vs. half the band width: just under 1 so the cap reads as "almost"
# a semicircle and stays inside the track rims.
_ROUND_END_CAP_SCALE = 0.96


def _add_round_sector_end(
    sector: np.ndarray,
    *,
    cx: int,
    cy: int,
    outer: int,
    inner: int,
    start: float,
    sweep: float,
) -> None:
    """Union a disc at the sector's leading edge into ``sector`` (in place).

    Only the half ahead of the end line is new ink; the trailing half is
    clipped so it can't poke behind the straight origin at tiny fractions.
    """
    mid_r = (outer + inner) / 2.0
    cap_r = (outer - inner) / 2.0 * _ROUND_END_CAP_SCALE
    end_rad = math.radians(start + sweep)
    shift = 4
    one = 1 << shift
    centre = (
        int(round((cx + mid_r * math.cos(end_rad)) * one)),
        int(round((cy + mid_r * math.sin(end_rad)) * one)),
    )
    cap = np.zeros_like(sector)
    cv2.circle(cap, centre, int(round(cap_r * one)), 255, -1, lineType=cv2.LINE_AA, shift=shift)
    ys, xs = np.nonzero(cap)
    if xs.size == 0:
        return
    rel = (np.degrees(np.arctan2(ys - cy, xs - cx)) - start) % 360.0
    cap_deg = math.degrees(math.asin(min(1.0, cap_r / max(mid_r, 1e-6))))
    keep = rel <= sweep + cap_deg + 1.0
    ys, xs = ys[keep], xs[keep]
    sector[ys, xs] = np.maximum(sector[ys, xs], cap[ys, xs])


def _draw_filled_circle_bgra(
    bgra: np.ndarray,
    *,
    cx: float,
    cy: float,
    r: float,
    fill_bgr: tuple[int, int, int],
    stroke_bgr: tuple[int, int, int] = _COLOR_CHROME_BGR,
    stroke: int = 2,
    fill_opacity: float = 1.0,
) -> None:
    radius = max(1, int(round(r)))
    pad = stroke + 2
    size = radius * 2 + pad * 2
    center = (size // 2, size // 2)
    mask = np.zeros((size, size), dtype=np.uint8)
    cv2.circle(mask, center, radius, 255, -1, lineType=cv2.LINE_AA)
    op = max(0.0, min(1.0, float(fill_opacity)))
    patch = np.zeros((size, size, 4), dtype=np.uint8)
    patch[:, :, 0] = fill_bgr[0]
    patch[:, :, 1] = fill_bgr[1]
    patch[:, :, 2] = fill_bgr[2]
    patch[:, :, 3] = np.clip(mask.astype(np.float32) * op, 0, 255).astype(np.uint8)
    x = int(round(cx - size / 2.0))
    y = int(round(cy - size / 2.0))
    _paste_patch_bgra(bgra, patch, x, y)
    if stroke > 0:
        stroke_patch = np.zeros((size, size, 4), dtype=np.uint8)
        cv2.circle(
            stroke_patch, center, radius, (*stroke_bgr, 255), stroke, lineType=cv2.LINE_AA
        )
        _paste_patch_bgra(bgra, stroke_patch, x, y)


def _draw_progress_ring(
    bgra: np.ndarray,
    *,
    cx: float,
    cy: float,
    outer_r: float,
    inner_r: float,
    fraction: float,
    fill_bgr: tuple[int, int, int] = _COLOR_ACCENT_BGR,
    stroke_bgr: tuple[int, int, int] = _COLOR_CHROME_BGR,
    stroke: int = _ACCENT_STROKE_PX,
    fill_opacity: float = _ACCENT_OPACITY,
    stroke_opacity: float = _ACCENT_STROKE_OPACITY,
    stroke_backdrop: np.ndarray | None = None,
    stroke_backdrop_x: int = 0,
    stroke_backdrop_y: int = 0,
    round_end: bool = False,
) -> None:
    frac = max(0.0, min(1.0, float(fraction)))
    if frac <= 1e-6:
        return
    pad = max(4, stroke + 2)
    size = int(math.ceil(outer_r * 2)) + pad * 2
    mask = annular_sector_mask(
        size,
        outer_r=outer_r,
        inner_r=inner_r,
        fraction=frac,
        round_end=round_end,
    )
    fill_a = int(round(255.0 * max(0.0, min(1.0, float(fill_opacity)))))
    fill = np.zeros((size, size, 4), dtype=np.uint8)
    fill[mask > 0, :3] = fill_bgr
    fill[mask > 0, 3] = fill_a
    x = int(round(cx - size / 2.0))
    y = int(round(cy - size / 2.0))
    _paste_patch_bgra(bgra, fill, x, y)
    if stroke > 0:
        stroke_patch = np.zeros((size, size, 4), dtype=np.uint8)
        cx_i = cy_i = size // 2
        outer = max(1, int(round(outer_r)))
        inner = max(0, min(int(round(inner_r)), outer - 1))
        start = -90.0
        end = start + 360.0 * frac
        thick = max(1, int(stroke))
        color = (*stroke_bgr, 255)
        if frac >= 0.999:
            cv2.circle(stroke_patch, (cx_i, cy_i), outer, color, thick, lineType=cv2.LINE_AA)
            if inner > 0:
                cv2.circle(stroke_patch, (cx_i, cy_i), inner, color, thick, lineType=cv2.LINE_AA)
        else:
            cv2.ellipse(
                stroke_patch,
                (cx_i, cy_i),
                (outer, outer),
                0,
                start,
                end,
                color,
                thick,
                lineType=cv2.LINE_AA,
            )
            if inner > 0:
                cv2.ellipse(
                    stroke_patch,
                    (cx_i, cy_i),
                    (inner, inner),
                    0,
                    start,
                    end,
                    color,
                    thick,
                    lineType=cv2.LINE_AA,
                )
            for ang in (start, end):
                rad = math.radians(ang)
                x_o = int(round(cx_i + outer * math.cos(rad)))
                y_o = int(round(cy_i + outer * math.sin(rad)))
                x_i = int(round(cx_i + inner * math.cos(rad)))
                y_i = int(round(cy_i + inner * math.sin(rad)))
                cv2.line(
                    stroke_patch, (x_i, y_i), (x_o, y_o), color, thick, lineType=cv2.LINE_AA
                )
        _paste_stroke_over_blur(
            bgra,
            stroke_patch,
            x,
            y,
            backdrop=stroke_backdrop,
            backdrop_x=stroke_backdrop_x,
            backdrop_y=stroke_backdrop_y,
            opacity=stroke_opacity,
        )


def _draw_circle_pair(
    bgra: np.ndarray,
    *,
    cx: float,
    cy: float,
    fraction: float,
    show_accent: bool,
    theme: _NpTheme | None = None,
) -> None:
    """Volume / circular-NP ring: grey track, UI-color level, black center.

    Pure-black track on the black stage reads as a "blacked out" zone once the
    TMDb intro spin stops (especially at low / zero volume). Chrome-grey empty
    track + edge strokes keep the widget present; theme.ui shows level. Center
    disc stays pure black (not the settings button swatch).
    """
    del show_accent  # track always drawn; UI overlay follows fraction
    th = theme or np_theme_from_settings()
    frac = max(0.0, min(1.0, float(fraction)))
    # Empty headroom — opaque enough to read on black / blurred artwork.
    _draw_progress_ring(
        bgra,
        cx=cx,
        cy=cy,
        outer_r=_RING_OUTER_R,
        inner_r=_RING_INNER_R,
        fraction=1.0,
        fill_bgr=_COLOR_UNFILLED_BGR,
        fill_opacity=1.0,
        stroke=0,
    )
    if frac > 1e-6:
        _draw_progress_ring(
            bgra,
            cx=cx,
            cy=cy,
            outer_r=_RING_OUTER_R,
            inner_r=_RING_INNER_R,
            fraction=frac,
            fill_bgr=th.ui_bgr,
            fill_opacity=1.0,
            stroke=0,
        )
    # Outer / inner rim so the annulus stays defined even at 0% volume.
    _draw_progress_ring(
        bgra,
        cx=cx,
        cy=cy,
        outer_r=_RING_OUTER_R,
        inner_r=_RING_INNER_R,
        fraction=1.0,
        fill_bgr=_COLOR_UNFILLED_BGR,
        fill_opacity=0.0,
        stroke=2,
        stroke_bgr=_COLOR_UNFILLED_BGR,
        stroke_opacity=0.85,
    )
    _draw_filled_circle_bgra(
        bgra,
        cx=cx,
        cy=cy,
        r=_RING_INNER_R,
        fill_bgr=_COLOR_CENTER_BLACK_BGR,
        fill_opacity=1.0,
    )
