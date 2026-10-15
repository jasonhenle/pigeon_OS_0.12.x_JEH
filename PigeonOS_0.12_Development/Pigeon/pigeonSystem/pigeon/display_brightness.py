"""User display brightness (companion-app slider).

Two ways to dim, picked automatically:

* **backlight** - a panel that exposes ``/sys/class/backlight/*`` (the official
  Pi display, most DSI panels) is dimmed in hardware, which also saves power;
* **software** - anything else (HDMI monitors) gets a gain applied to every
  frame on its way to the screen, via :func:`apply`.

The level is a percentage persisted as ``display_brightness``. It never goes
below :data:`MIN_PERCENT`, so a stray slider can't leave the screen unreadable.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import numpy as np

MIN_PERCENT = 10
MAX_PERCENT = 100
_STATE_KEY = "display_brightness"

_LOCK = threading.Lock()
_PERCENT: int | None = None      # cached level; None until first read
_HW_APPLIED = False              # hardware level pushed since this level last changed
_HW_FAILED = False               # a hardware write failed: stay on software dimming
_BL_UNSET = object()
_BL_DEVICE: Any = _BL_UNSET      # discovered once; the frame path asks every frame


def _backlight_root() -> Path:
    return Path(os.environ.get("PIGEON_BACKLIGHT_DIR") or "/sys/class/backlight")


def _backlight_device() -> Path | None:
    """First backlight whose ``brightness`` file we may write (looked up once)."""
    global _BL_DEVICE
    if _BL_DEVICE is _BL_UNSET:
        _BL_DEVICE = _find_backlight()
    return _BL_DEVICE


def _find_backlight() -> Path | None:
    root = _backlight_root()
    try:
        names = sorted(p for p in root.iterdir() if p.is_dir() or p.is_symlink())
    except OSError:
        return None
    for d in names:
        b, m = d / "brightness", d / "max_brightness"
        if b.exists() and m.exists() and os.access(b, os.W_OK):
            return d
    return None


def mode() -> str:
    """``backlight`` when hardware dimming works, else ``software``."""
    if _HW_FAILED:
        return "software"
    return "backlight" if _backlight_device() is not None else "software"


def clamp(value: Any) -> int:
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        raise ValueError("brightness must be a number") from None
    return max(MIN_PERCENT, min(MAX_PERCENT, v))


def get_percent() -> int:
    global _PERCENT
    with _LOCK:
        if _PERCENT is None:
            try:
                from pigeon.app_state import read_app_state

                raw = read_app_state().get(_STATE_KEY)
                _PERCENT = clamp(raw) if raw is not None else MAX_PERCENT
            except Exception:
                _PERCENT = MAX_PERCENT
        return _PERCENT


def _write_backlight(percent: int) -> bool:
    global _HW_FAILED
    dev = _backlight_device()
    if dev is None:
        return False
    try:
        mx = int((dev / "max_brightness").read_text().strip())
        (dev / "brightness").write_text(str(max(1, int(round(mx * percent / 100.0)))))
        return True
    except (OSError, ValueError):
        _HW_FAILED = True
        return False


def set_percent(value: Any) -> int:
    """Persist and apply a level. Returns the level actually stored."""
    global _PERCENT, _HW_APPLIED
    pct = clamp(value)
    with _LOCK:
        _PERCENT = pct
    try:
        from pigeon.app_state import write_app_state

        write_app_state(**{_STATE_KEY: pct})
    except Exception:
        pass
    _HW_APPLIED = _write_backlight(pct)
    return pct


def reset_cache() -> None:
    """Forget the cached level and hardware state (tests)."""
    global _PERCENT, _HW_APPLIED, _HW_FAILED, _BL_DEVICE
    with _LOCK:
        _PERCENT = None
    _HW_APPLIED = False
    _HW_FAILED = False
    _BL_DEVICE = _BL_UNSET


def software_gain() -> float:
    """Gain the frame path must apply: 1.0 when the hardware backlight does the work."""
    if mode() == "backlight":
        return 1.0
    return get_percent() / 100.0


def apply(frame_bgr: np.ndarray) -> np.ndarray:
    """Final step of the frame path. Cheap no-op at 100 % or with a backlight."""
    global _HW_APPLIED
    if not _HW_APPLIED and not _HW_FAILED and _backlight_device() is not None:
        # first frame of this run: put the saved level on the panel once
        _HW_APPLIED = _write_backlight(get_percent())
    gain = software_gain()
    if gain >= 0.999 or frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return frame_bgr
    import cv2

    return cv2.convertScaleAbs(frame_bgr, alpha=gain, beta=0)
