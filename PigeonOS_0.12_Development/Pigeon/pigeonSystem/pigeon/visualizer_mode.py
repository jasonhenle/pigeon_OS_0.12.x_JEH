"""Visualizer mode: a long press on the navigation encoder forces Clocksaver.

While it is on, :mod:`pigeon.auto_widgets` shows the full-frame Clocksaver
(analog or digital, per the clock option) over whatever is playing, and
:mod:`pigeon.viz_backdrop` draws the full-screen visualizer behind it while
program audio comes in. Another long press returns to the automatic layout.
settings_pigeon option5 picks the state Pigeon starts in.

Audio with no player metadata gets the same visualizer Clocksaver without the
long press. The zone-6 badge below belongs to the older zone-6 layout.
"""

from __future__ import annotations

import time
from functools import lru_cache

import cv2
import numpy as np

GREEN_HOLD_S = 3.0
FADE_S = 0.6
# Capture needs a moment to start after the mode turns on; don't flash red first.
STARTUP_GRACE_S = 1.5
BADGE_PX = 40
BADGE_INSET_PX = 16
_OK_BGR = (0x00, 0xFF, 0x58)  # settings_pigeon _COLOR_STATUS_OK #58FF00
_BAD_BGR = (0x00, 0x00, 0xFF)  # _COLOR_STATUS_BAD #FF0000

_active: bool | None = None
_changed_mono = 0.0


def is_active() -> bool:
    """True in visualizer mode (first call reads the option5 default)."""
    global _active
    if _active is None:
        try:
            from pigeon.widgets.options_settings import zone6_visualizer_default

            _active = bool(zone6_visualizer_default())
        except Exception:
            _active = False
    return bool(_active)


def set_active(on: bool) -> None:
    global _active, _changed_mono
    _active = bool(on)
    _changed_mono = time.monotonic()
    _badge.reset()


def toggle() -> bool:
    """Flip the mode (long encoder press). Returns the new state."""
    set_active(not is_active())
    return bool(_active)


class AudioBadge:
    """Red while audio is missing; green for a while once it returns, then gone."""

    def __init__(self) -> None:
        self._missing = False
        self._found_at: float | None = None

    def reset(self) -> None:
        self._missing = False
        self._found_at = None

    def update(self, audio: bool, now: float) -> tuple[bool, float] | None:
        """``(audio ok?, opacity)`` to draw, or None for no badge."""
        if not audio:
            if now - _changed_mono < STARTUP_GRACE_S and not self._missing:
                return None
            self._missing, self._found_at = True, None
            return (False, 1.0)
        if self._missing:
            self._missing, self._found_at = False, now
        if self._found_at is None:
            return None
        t = now - self._found_at
        if t < GREEN_HOLD_S:
            return (True, 1.0)
        if t < GREEN_HOLD_S + FADE_S:
            return (True, 1.0 - (t - GREEN_HOLD_S) / FADE_S)
        self._found_at = None
        return None


_badge = AudioBadge()


def badge_state(audio: bool, now: float | None = None) -> tuple[bool, float] | None:
    return _badge.update(bool(audio), time.monotonic() if now is None else float(now))


@lru_cache(maxsize=4)
def _badge_sprite(ok: bool, size: int) -> tuple[np.ndarray, np.ndarray]:
    """``(bgr float32, alpha float32)``: the settings audio tile (rounded square + ring glyph)."""
    k = 4
    s = size * k
    col = np.zeros((s, s, 3), np.uint8)
    alpha = np.zeros((s, s), np.uint8)
    tile = _OK_BGR if ok else _BAD_BGR
    r = int(round(s * 10.35 / 39.95))
    for img, c in ((col, tile), (alpha, 255)):
        cv2.rectangle(img, (r, 0), (s - 1 - r, s - 1), c, -1)
        cv2.rectangle(img, (0, r), (s - 1, s - 1 - r), c, -1)
        for cx, cy in ((r, r), (s - 1 - r, r), (r, s - 1 - r), (s - 1 - r, s - 1 - r)):
            cv2.circle(img, (cx, cy), r, c, -1)
    c0 = (s // 2, s // 2)
    unit = s / 39.95
    cv2.circle(col, c0, int(round(12.13 * unit)), (0, 0, 0), -1)
    cv2.circle(col, c0, int(round(7.53 * unit)), tile, -1)
    cv2.circle(col, c0, int(round(5.95 * unit)), (0, 0, 0), -1)
    bgr = cv2.resize(col, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32)
    a = cv2.resize(alpha, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    return bgr, a[:, :, None]


def draw_badge(out: np.ndarray, zone_xywh: tuple[float, float, float, float],
               state: tuple[bool, float] | None) -> None:
    """Blend the badge into the top-right corner of ``zone_xywh`` (BGR or BGRA ``out``)."""
    if state is None:
        return
    ok, opacity = state
    if opacity <= 0.0:
        return
    zx, zy, zw, _zh = zone_xywh
    x = int(round(zx + zw - BADGE_INSET_PX - BADGE_PX))
    y = int(round(zy + BADGE_INSET_PX))
    bgr, a = _badge_sprite(bool(ok), BADGE_PX)
    H, W = out.shape[:2]
    if x < 0 or y < 0 or x + BADGE_PX > W or y + BADGE_PX > H:
        return
    a = a * float(opacity)
    dst = out[y : y + BADGE_PX, x : x + BADGE_PX]
    dst[:, :, :3] = (dst[:, :, :3].astype(np.float32) * (1.0 - a) + bgr * a).astype(np.uint8)
    if out.shape[2] >= 4:
        dst[:, :, 3] = np.maximum(dst[:, :, 3], (a[:, :, 0] * 255.0).astype(np.uint8))
