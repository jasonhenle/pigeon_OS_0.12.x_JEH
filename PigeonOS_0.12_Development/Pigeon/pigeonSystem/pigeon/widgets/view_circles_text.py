"""
Date, clock-day and volume readout text for the now-playing widgets.

Zone-0 date alignment / ordinal formatting, baseline lookups for the clock day and
volume lines, and the cached volume / disc-clock / volume-input text patches. Time
values are passed in; nothing here reads the wall clock.

``pigeon.widgets.view_circles`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import math
from datetime import datetime
from functools import lru_cache

import numpy as np

from pigeon.np_layout import (
    CLOCK_DAY_LOCAL,
    CLOCK_VIEW_H,
    CLOCK_VIEW_W,
    NOW_PLAYING_ZONES,
    NP_HEADER_CLOCK_SIZE_PX,
    VOLUME_FORMAT_SIZE_PX,
    design_xy_from_local,
)
from pigeon.widgets.view_circles_draw import (
    _RING_INNER_R,
    _RING_OUTER_R,
    _WIDGET_LABEL_BASELINE_GAP_PX,
    _load_sharp_extrabold,
    _text_patch_digital7,
    _text_patch_font,
)
from pigeon.widgets.view_circles_svg import _CLOCK_EXTERIOR_ACCENT_R


# Usable radius as a fraction of the inner disc — leaves padding around the number.
_VOLUME_TEXT_INNER_FIT = 0.88


def _zone0_date_align(
    assignments: tuple[str, str, str, str, str] | None = None,
) -> str | None:
    """``left`` / ``center`` / ``right``, or ``None`` when the header is off."""
    try:
        from pigeon.np_zone_config import zone0_date_align

        return zone0_date_align(assignments)
    except Exception:
        return "left"


def _ordinal_day(day: int) -> str:
    d = int(day)
    if 11 <= (d % 100) <= 13:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
    return f"{d}{suf}"


def _format_zone0_date(now: datetime) -> str:
    """``SAT, AUG 15`` — abbreviated weekday and month, all caps."""
    return f"{now.strftime('%a')}, {now.strftime('%b')} {int(now.day)}".upper()


def _zone3_clock_day_baseline_y() -> float:
    """Design-Y baseline of the zone-3 clock's day / date line (``Monday Sep 7``)."""
    _x, y = design_xy_from_local(
        NOW_PLAYING_ZONES[3],
        CLOCK_DAY_LOCAL[0],
        CLOCK_DAY_LOCAL[1],
        view_w=CLOCK_VIEW_W,
        view_h=CLOCK_VIEW_H,
    )
    return float(y)


# Zone-6 receiver volume: margin above its ink and at the zone sides.
_ZONE6_VOLUME_MARGIN_PX = 14.0


@lru_cache(maxsize=1)
def _zone6_volume_font_px() -> int:
    """Largest Sharp Sans size whose widest readout fits over zone 6: from the
    screen-top margin down to the zone-3 date baseline, zone 6 wide."""
    z6 = NOW_PLAYING_ZONES[6]
    margin = float(_ZONE6_VOLUME_MARGIN_PX)
    max_w = float(z6.w) - 2.0 * margin
    max_h = _zone3_clock_day_baseline_y() - margin
    template = "-88.8 dB"
    size = int(NP_HEADER_CLOCK_SIZE_PX)
    for trial in range(size, 400):
        patch, pw, _ph = _text_patch_font(template, font=_load_sharp_extrabold(trial), fill_rgb=(255, 255, 255))
        rows = np.where(patch[:, :, 3].max(axis=1) > 8)[0]
        ink_h = float(rows.max() - rows.min() + 1) if rows.size else 0.0
        if pw > max_w or ink_h > max_h:
            break
        size = trial
    return size


def _clock_date_baseline_y(cy: float) -> float:
    """Baseline for the date line: 20px above the clock exterior top."""
    return float(cy) - float(_CLOCK_EXTERIOR_ACCENT_R) - float(_WIDGET_LABEL_BASELINE_GAP_PX)


def _volume_audio_cfg_baseline_y(cy: float) -> float:
    """Baseline for audio-config: 20px above the volume ring exterior top."""
    return float(cy) - float(_RING_OUTER_R) - float(_WIDGET_LABEL_BASELINE_GAP_PX)


# Widest readout the disc has to hold; every level is drawn at the size that fits it.
_VOLUME_SIZE_REFERENCE_TEXT = "-88.8"


@lru_cache(maxsize=16)
def _volume_readout_size_px(usable_r: float, hi: int) -> int:
    """Largest Digital-7 size whose widest readout fits the disc (same for every level)."""
    pad = 2  # matches ``_text_patch_digital7``
    lo = 16
    best = 16
    while lo <= hi:
        mid = (lo + hi) // 2
        _patch, w, h = _text_patch_digital7(_VOLUME_SIZE_REFERENCE_TEXT, size_px=mid, fill_rgb=None)
        ink_w = max(0.0, float(w) - 2.0 * pad)
        ink_h = max(0.0, float(h) - 2.0 * pad)
        if (ink_w * 0.5) ** 2 + (ink_h * 0.5) ** 2 <= usable_r ** 2:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _volume_readout_patch(
    text: str,
    *,
    inner_r: float = _RING_INNER_R,
    max_size_px: int | None = None,
    fill_rgb: tuple[int, int, int] | None = None,
) -> tuple[np.ndarray, int, int]:
    """Digital-7 volume number inside the inner disc.

    The size is fitted once to the widest readout, not to each string, so a step
    from ``-22`` to ``-21.5`` does not change the font size or move the labels
    placed from its height.
    """
    label = str(text or "").strip()
    if not label:
        return np.zeros((1, 1, 4), dtype=np.uint8), 0, 0
    usable_r = max(12.0, float(inner_r) * float(_VOLUME_TEXT_INNER_FIT))
    hi = int(max_size_px) if max_size_px is not None else int(round(usable_r * 2.0))
    size = _volume_readout_size_px(round(usable_r, 3), max(18, hi))
    return _text_patch_digital7(label, size_px=size, fill_rgb=fill_rgb)


def _disc_clock_patch(label: str, fill_rgb: tuple[int, int, int]) -> np.ndarray:
    """Disc clock text in the volume input label's font and size, ink-cropped."""
    patch, _w, _h = _text_patch_font(
        label,
        font=_load_sharp_extrabold(int(VOLUME_FORMAT_SIZE_PX)),
        fill_rgb=fill_rgb,
    )
    rows = np.where(patch[:, :, 3] > 8)[0]
    if rows.size == 0:
        return patch[:0]
    return patch[int(rows.min()) : int(rows.max()) + 1]


@lru_cache(maxsize=1)
def _disc_clock_ink_h() -> int:
    """Ink height of the disc clock (same font and size as the input label)."""
    return int(_disc_clock_patch("0:00PM", (255, 255, 255)).shape[0])


def _volume_input_patch(
    label: str,
    *,
    top_dy: float,
    inner_r: float,
    max_h: int,
    fill_rgb: tuple[int, int, int] | None = None,
) -> tuple[np.ndarray, int, int]:
    """AVR input label fitted under the volume number, inside the disc.

    ``top_dy`` is the label's top edge below the disc center; the width is
    clipped to the disc chord at the label's bottom edge.
    """
    text = str(label or "").strip().upper()
    empty = (np.zeros((1, 1, 4), dtype=np.uint8), 0, 0)
    if not text or int(max_h) < 10:
        return empty
    r = float(inner_r)
    size = int(VOLUME_FORMAT_SIZE_PX)
    while size >= 12:
        patch, w, h = _text_patch_font(
            text, font=_load_sharp_extrabold(size), fill_rgb=fill_rgb
        )
        dy = float(top_dy) + float(h)
        chord = 2.0 * math.sqrt(max(0.0, r * r - dy * dy))
        if h <= int(max_h) and w <= chord:
            return patch, w, h
        size -= 2
    return empty
