"""Full-screen visualizer behind the clocksaver while program audio plays.

The clocksaver (analog or digital, per the clock option) stays the screen;
when the meter capture hears program audio, the active
:mod:`pigeon.fullscreen_viz` preset fills the frame underneath it, dimmed to
:data:`DIM` so the clock still reads, with its unlit cells off (flat black). A long encoder press forces the
clocksaver (see :mod:`pigeon.visualizer_mode`), so it is also the way into the
visualizer while a player is showing Now Playing.

Compose paths call :func:`paint` on their canvas right before the clocksaver
layers, and blit those layers through :func:`clock_overlay`. The clocksaver
frame costs ~200 ms to rasterize on a Pi 5 and normally redraws about once a
second; behind a 30 fps visualizer it is rendered once per second on a worker
thread (like the Now Playing reveal page), keyed with :func:`key_page` (the
digital face is an opaque full frame whose near-black page would hide the
visualizer) and flattened so each frame only touches the clock's own pixels.
"""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np

from pigeon.design import DESIGN_H, DESIGN_W

DIM = 0.30
# The backdrop draws only what is lit: unlit cells / slots go to the page black.
_FLAT = {"unlit": 0.0, "showSlots": False}
# Brightest channel below this is the digital face's page, not clock ink
# (the page is ~#0F0F10; see clock_saver._CLOCK_INK_MIN_CHANNEL).
_PAGE_MAX = 32
_INK_MIN = 56
_ROTATE_WINDOW_S = 1.0

_viz = None
_buf: np.ndarray | None = None
_painted_mono = 0.0
_clock_lock = threading.Lock()
_clock_key: object = None
_clock_val = None
_clock_busy = False


def wanted() -> bool:
    """True while program audio is coming in on the meter capture."""
    try:
        from pigeon.widgets.audio_meter_saver import program_audio_present

        return bool(program_audio_present())
    except Exception:
        return False


def _instance():
    global _viz
    if _viz is None:
        from pigeon.fullscreen_viz import FullscreenViz

        class _Flat(FullscreenViz):
            def preset(self) -> dict[str, object]:
                p = dict(super().preset())
                p.update({k: v for k, v in _FLAT.items() if k in p})
                return p

        _viz = _Flat(remember=True)
    return _viz


def paint(canvas: np.ndarray) -> bool:
    """Draw the dimmed visualizer over all of ``canvas`` (BGR). False when no audio."""
    global _buf, _painted_mono
    if not wanted():
        return False
    h, w = canvas.shape[:2]
    if _buf is None or _buf.shape[:2] != (h, w):
        _buf = np.zeros((h, w, 3), np.uint8)
    try:
        _instance().render(_buf)
    except Exception:
        return False
    if canvas.ndim == 3 and canvas.shape[2] == 3 and canvas.flags.c_contiguous:
        cv2.convertScaleAbs(_buf, dst=canvas, alpha=DIM)
    else:
        canvas[:, :, :3] = cv2.convertScaleAbs(_buf, alpha=DIM)
    _painted_mono = time.monotonic()
    return True


def showing(within_s: float = _ROTATE_WINDOW_S) -> bool:
    return (time.monotonic() - _painted_mono) < float(within_s)


def rotate(step: int) -> bool:
    """Encoder turn while the backdrop shows: next / previous preset. False when it isn't up."""
    if not showing():
        return False
    try:
        _instance().rotate(1 if step > 0 else -1)
    except Exception:
        return False
    return True


def key_page(bgra: np.ndarray) -> np.ndarray:
    """An opaque clocksaver frame with its dark page made transparent (others unchanged)."""
    if bgra is None or bgra.ndim != 3 or bgra.shape[2] < 4:
        return bgra
    a = bgra[:, :, 3]
    if float(np.mean(a > 250)) < 0.9:
        return bgra  # already has real transparency (analog widget)
    ink = bgra[:, :, :3].max(axis=2).astype(np.float32)
    keep = np.clip((ink - _PAGE_MAX) / float(_INK_MIN - _PAGE_MAX), 0.0, 1.0)
    out = bgra.copy()
    out[:, :, 3] = (a.astype(np.float32) * keep).astype(np.uint8)
    return out


class ClockOverlay:
    """One clocksaver frame, keyed and flattened for a cheap per-frame blit.

    The generic full-frame alpha blend costs ~50 ms on a Pi 5; the clock only
    changes once a second, so the pixels it covers are found once: opaque ones
    are copied, edge ones blended, the rest of the frame is left alone.
    """

    def __init__(self, layers) -> None:
        self._layers = [(key_page(patch), rect) for patch, rect in _iter_layers(layers)]
        self._prepped: dict[tuple[int, int], tuple] = {}

    def prep(self, h: int, w: int) -> tuple:
        hit = self._prepped.get((h, w))
        if hit is not None:
            return hit
        real = [(p, r) for p, r in self._layers if p.shape[0] >= 2 and p.shape[1] >= 2]
        if len(real) == 1 and real[0][0].shape[:2] == (h, w) and tuple(real[0][1][:2]) == (0, 0):
            # The usual case: one full-frame clocksaver layer at canvas size.
            out = self._prep_flat(real[0][0].reshape(-1, 4))
            self._prepped[(h, w)] = out
            return out
        full = np.zeros((h, w, 4), np.float32)
        sx, sy = w / float(DESIGN_W), h / float(DESIGN_H)
        for patch, (x, y, pw, ph) in self._layers:
            if patch.shape[0] < 2 or patch.shape[1] < 2:
                continue
            x0, y0 = int(round(x * sx)), int(round(y * sy))
            tw, th = max(1, int(round(pw * sx))), max(1, int(round(ph * sy)))
            if (patch.shape[1], patch.shape[0]) != (tw, th):
                patch = cv2.resize(patch, (tw, th), interpolation=cv2.INTER_AREA)
            x1, y1 = min(w, x0 + tw), min(h, y0 + th)
            if x1 <= x0 or y1 <= y0:
                continue
            src = patch[: y1 - y0, : x1 - x0].astype(np.float32)
            a = src[:, :, 3:4] / 255.0
            dst = full[y0:y1, x0:x1]
            dst[:, :, :3] = src[:, :, :3] * a + dst[:, :, :3] * (1.0 - a)
            dst[:, :, 3:4] = a * 255.0 + dst[:, :, 3:4] * (1.0 - a)
        flat = full.reshape(-1, 4)
        alpha = flat[:, 3]
        opaque = np.flatnonzero(alpha >= 254.5)
        partial = np.flatnonzero((alpha > 0.5) & (alpha < 254.5))
        af = (alpha[partial] / 255.0)[:, None].astype(np.float32)
        out = (
            opaque,
            flat[opaque, :3].astype(np.uint8),
            partial,
            flat[partial, :3].astype(np.float32),  # premultiplied by the compositing above
            (1.0 - af).astype(np.float32),
        )
        self._prepped[(h, w)] = out
        return out

    @staticmethod
    def _prep_flat(flat: np.ndarray) -> tuple:
        """``(opaque, colors, partial, premultiplied colors, 1 - alpha)`` from straight-alpha BGRA rows."""
        alpha = flat[:, 3]
        opaque = np.flatnonzero(alpha == 255)
        partial = np.flatnonzero((alpha > 0) & (alpha < 255))
        af = (alpha[partial].astype(np.float32) / 255.0)[:, None]
        return (
            opaque,
            flat[opaque, :3].copy(),
            partial,
            flat[partial, :3].astype(np.float32) * af,
            1.0 - af,
        )

    def blit(self, canvas: np.ndarray) -> None:
        h, w = canvas.shape[:2]
        opaque, op_px, partial, pt_fg, pt_inv = self.prep(h, w)
        target = canvas if canvas.flags.c_contiguous else np.ascontiguousarray(canvas)
        flat = target.reshape(-1, target.shape[2])
        flat[opaque, :3] = op_px
        if partial.size:
            flat[partial, :3] = (pt_fg + flat[partial, :3].astype(np.float32) * pt_inv).astype(np.uint8)
        if target is not canvas:
            canvas[:] = target


def _iter_layers(layers):
    (frame, rect), (date, drect) = layers
    yield date, drect
    yield frame, rect


def clock_overlay(key: object, render, *, size: tuple[int, int] = (800, 1280)) -> ClockOverlay:
    """The clocksaver for ``key`` (changes about once a second), ready to blit.

    The first call renders inline; after that the previous overlay is returned
    while a worker renders and preps the new ``key``, so the visualizer never
    waits on the clock.
    """
    global _clock_key, _clock_val, _clock_busy
    with _clock_lock:
        have, val, busy = _clock_key, _clock_val, _clock_busy
        start = have != key and val is not None and not busy
        if start:
            _clock_busy = True
    if have == key and val is not None:
        return val
    if val is None:
        val = ClockOverlay(render())
        with _clock_lock:
            _clock_key, _clock_val = key, val
        return val
    if start:

        def _work() -> None:
            global _clock_key, _clock_val, _clock_busy
            try:
                fresh = ClockOverlay(render())
                fresh.prep(*size)
                with _clock_lock:
                    _clock_key, _clock_val = key, fresh
            except Exception:
                pass
            finally:
                with _clock_lock:
                    _clock_busy = False

        threading.Thread(target=_work, name="pigeon-viz-backdrop-clock", daemon=True).start()
    return val
