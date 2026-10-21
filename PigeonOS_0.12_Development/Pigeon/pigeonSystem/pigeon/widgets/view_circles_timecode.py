"""
Timecode formatting and header time patches for the now-playing widgets.

Header digital-7 / TRT size lookups, the matched ``HH:MM`` patch, the status-bar and
countdown timecode formatters and the selected-volume pie. Pure functions of their
arguments; the wall-clock read (``_clock_hhmm``) stays in ``view_circles``, where tests
patch ``pigeon_now``.

``pigeon.widgets.view_circles`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import re
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw

from pigeon.np_layout import NP_HEADER_CLOCK_SIZE_PX, VOLUME_INNER_R, VOLUME_OUTER_R
from pigeon.widgets.view_circles_draw import _draw_progress_ring, _load_digital7, _load_sharp_extrabold
from pigeon.widgets.view_circles_theme import _NpTheme, np_theme_from_settings


@lru_cache(maxsize=1)
def _header_digital7_size_px() -> int:
    """Digital-7 size for the header clock / TRT: digit ink as tall as the
    Sharp Sans header chrome (music album title) it shares the band with."""
    draw = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    _l, t, _r, b = draw.textbbox((0, 0), "0", font=_load_sharp_extrabold(int(NP_HEADER_CLOCK_SIZE_PX)))
    _l, t7, _r, b7 = draw.textbbox((0, 0), "0", font=_load_digital7(100))
    return max(12, int(round(100.0 * (b - t) / max(1, b7 - t7))))


@lru_cache(maxsize=8)
def _header_trt_size_px(template: str, max_w: int, max_h: int) -> int:
    """Largest Digital-7 size whose ``template`` ink fits ``max_w``×``max_h``.

    Callers pass the label with every digit as ``8`` so the size only changes
    when the readout drops a field (e.g. under an hour), not every second.
    """

    def ink(size: int) -> tuple[int, int]:
        a = _matching_hhmm_patch(template, size_px=size, pad_y=size // 2)[:, :, 3] > 8
        rows, cols = np.where(a.any(axis=1))[0], np.where(a.any(axis=0))[0]
        if rows.size == 0:
            return (0, 0)
        return (int(cols.max() - cols.min() + 1), int(rows.max() - rows.min() + 1))

    probe = 200
    w, h = ink(probe)
    if w <= 0 or h <= 0:
        return 12
    size = int(probe * min(max_w / w, max_h / h))
    while size > 12:
        w, h = ink(size)
        if w <= max_w and h <= max_h:
            break
        size -= 1
    return max(12, size)


def _matching_hhmm_patch(
    text: str,
    *,
    size_px: int,
    fill_rgb: tuple[int, int, int] = (255, 255, 255),
    pad_y: int = 10,
) -> np.ndarray:
    """Digital-7 time using clock-saver matching-cell spacing (skinny ``1`` / ``:`` / ``-``).

    Large sizes need a bigger ``pad_y``: Digital-7 ink overhangs its cell."""
    from pigeon.widgets.clock_saver import (
        _HHMMSS_CHAR_SET,
        _cell_metrics,
        _hhmmss_advance,
    )

    label = str(text or "").strip()
    if not label:
        return np.zeros((1, 1, 4), dtype=np.uint8)
    font = _load_digital7(size_px)
    probe = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    charset = _HHMMSS_CHAR_SET + "-"
    matching_w, cell_h = _cell_metrics(draw, font, charset)
    total_w = 0
    advances: list[int] = []
    for ch in label:
        if ch == "-":
            adv = max(1, int(round(0.5 * matching_w)))
        else:
            adv = _hhmmss_advance(matching_w, ch)
        advances.append(adv)
        total_w += adv
    pad_x = 4
    img = Image.new(
        "RGBA",
        (max(1, total_w + pad_x * 2), max(1, cell_h + pad_y * 2)),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(img)
    x = pad_x
    cy = pad_y + cell_h // 2
    color = (*fill_rgb, 255)
    for ch, adv in zip(label, advances):
        draw.text((x + adv // 2, cy), ch, font=font, fill=color, anchor="mm")
        x += adv
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)


def format_status_bar_timecode(raw: str, *, remaining: bool = False) -> str:
    """Clock-saver duration: drop hours when they are 00; remaining is ``-MM:SS``."""
    s = str(raw or "").strip()
    if not s:
        return ""
    if s.upper() == "LIVE":
        return "LIVE"
    sign = s.startswith("-")
    body = s[1:] if sign else s
    parts = [p for p in re.split(r"[:.]", body) if p != ""]
    try:
        nums = [max(0, int(p)) for p in parts]
    except ValueError:
        return s
    hours = minutes = seconds = 0
    if len(nums) >= 3:
        hours, minutes, seconds = nums[0], nums[1], nums[2]
    elif len(nums) == 2:
        minutes, seconds = nums[0], nums[1]
    elif len(nums) == 1:
        seconds = nums[0]
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
    if hours > 0:
        out = f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        out = f"{minutes:02d}:{seconds:02d}"
    if remaining or sign:
        out = "-" + out.lstrip("-")
    return out


def format_countdown_timecode(raw: str) -> str:
    """TT-countdown remaining clock: never a leading-zero field, always ``-``.

    Hours drop off the left when they hit 0 (``-1:00:00`` → ``-59:59``). The
    new leftmost number is not zero-padded, so the string shortens by one
    digit at each decade (``-10:00`` → ``-9:59``, ``-1:00`` → ``-59``).
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    if s.upper() == "LIVE":
        return "LIVE"
    body = s[1:] if s.startswith("-") else s
    parts = [p for p in re.split(r"[:.]", body) if p != ""]
    try:
        nums = [max(0, int(p)) for p in parts]
    except ValueError:
        return "-" + body if not s.startswith("-") else s
    hours = minutes = seconds = 0
    if len(nums) >= 3:
        hours, minutes, seconds = nums[0], nums[1], nums[2]
    elif len(nums) == 2:
        minutes, seconds = nums[0], nums[1]
    elif len(nums) == 1:
        seconds = nums[0]
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
    if hours > 0:
        out = f"{hours}:{minutes:02d}:{seconds:02d}"
    elif minutes > 0:
        out = f"{minutes}:{seconds:02d}"
    else:
        out = f"{seconds}"
    return "-" + out


def _draw_volume_selected_pie(
    bgra: np.ndarray,
    *,
    cx: float,
    cy: float,
    fraction: float,
    theme: _NpTheme | None = None,
) -> None:
    """UI-color volume pie from 12 o'clock clockwise; SVG already paints the grey track."""
    th = theme or np_theme_from_settings()
    frac = max(0.0, min(1.0, float(fraction)))
    if frac <= 1e-6:
        return
    _draw_progress_ring(
        bgra,
        cx=cx,
        cy=cy,
        outer_r=VOLUME_OUTER_R,
        inner_r=VOLUME_INNER_R,
        fraction=frac,
        fill_bgr=th.ui_bgr,
        fill_opacity=1.0,
        stroke=0,
        round_end=True,
    )
