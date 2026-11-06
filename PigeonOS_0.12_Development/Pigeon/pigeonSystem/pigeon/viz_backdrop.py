"""Visualizer over the clocksaver while program audio plays.

When the meter capture hears program audio on the clocksaver, the screen runs
a timeline forward, one phase after another:

1. the date, weather, volume and seconds bar fade out, leaving the time;
2. the time glides up towards the top of the screen;
3. the time dims to :data:`CLOCK_DIM`;
4. the active :mod:`pigeon.fullscreen_viz` preset fades in full screen on top
   of it (unlit cells off, so the bars cover the time only where they are lit).

When the audio stops, or a long press turns visualizer mode off, the timeline
runs back: the bars fall to rest (the visualizer analyses silence), the time
brightens, glides back down, and the other clocksaver elements fade back in.
:mod:`pigeon.visualizer_mode` holds the layout until that exit has finished.

The analog clock option has no separate time layer, so the whole face moves
and dims and nothing fades.

Compose paths call :func:`active` and, while it is true, hand their canvas to
:func:`compose` instead of drawing the clocksaver themselves. The full face
costs ~100 ms to render on a Pi 5, so faces are rendered once a second on a
worker thread (like the Now Playing reveal page), keyed (:func:`key_page`: the
digital face is an opaque frame whose dark page would cover the visualizer)
and flattened so each frame only touches the clock's own pixels.
"""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np

from pigeon.design import DESIGN_H, DESIGN_W

CLOCK_DIM = 0.30
CLOCK_TOP_PX = 48  # where the time's top edge ends up
# Phase lengths (s), in entering order; leaving runs them backwards.
EXTRAS_S = 0.6
MOVE_S = 1.0
DIM_S = 0.6
VIZ_S = 1.4  # leaving: the bars fall to rest, then the last VIZ_FADE fades out
VIZ_FADE = 0.25
# The backdrop draws only what is lit: unlit cells / slots go to the page black.
_FLAT = {"unlit": 0.0, "showSlots": False}
# Brightest channel below this is the digital face's page, not clock ink
# (the page is ~#0F0F10; see clock_saver._CLOCK_INK_MIN_CHANNEL).
_PAGE_MAX = 32
_INK_MIN = 56
# A visualizer pixel this bright covers the time under it.
_COVER_MIN = 24
_ROTATE_WINDOW_S = 1.0
_TOTAL = EXTRAS_S + MOVE_S + DIM_S + VIZ_S

_viz = None
_t = 0.0  # position on the timeline, 0 .. _TOTAL
_last_mono: float | None = None
_painted_mono = 0.0
_exit_cb = None  # called once the timeline is back at 0 (long press off)
_suppressed = False  # long press dismissed the automatic visualizer until audio stops


def wanted() -> bool:
    """True while program audio is coming in on the meter capture."""
    try:
        from pigeon.widgets.audio_meter_saver import program_audio_present

        return bool(program_audio_present())
    except Exception:
        return False


def _target() -> float:
    return _TOTAL if (_exit_cb is None and not _suppressed and wanted()) else 0.0


def active() -> bool:
    """True while the timeline is anywhere but at rest (or audio wants it to start)."""
    return _t > 0.0 or _target() > 0.0


def leave_then(callback) -> bool:
    """Run the timeline back to rest, then call ``callback``. False when already at rest."""
    global _exit_cb
    if _t <= 0.0:
        return False
    _exit_cb = callback
    return True


def suppress() -> None:
    """Run the timeline back to rest and keep it there until the audio stops."""
    global _suppressed
    _suppressed = True


def cancel_leave() -> bool:
    """Undo :func:`leave_then` / :func:`suppress` (a press during the exit). False when neither."""
    global _exit_cb, _suppressed
    if _exit_cb is None and not _suppressed:
        return False
    _exit_cb = None
    _suppressed = False
    return True


def _advance() -> None:
    global _t, _last_mono, _exit_cb, _suppressed
    if _suppressed and not wanted():
        _suppressed = False
    now = time.monotonic()
    dt = 0.0 if _last_mono is None or now - _last_mono > 0.5 else now - _last_mono
    _last_mono = now
    goal = _target()
    if _t < goal:
        _t = min(goal, _t + dt)
    elif _t > goal:
        _t = max(goal, _t - dt)
    if _t <= 0.0 and _exit_cb is not None:
        cb, _exit_cb = _exit_cb, None
        try:
            cb()
        except Exception:
            pass


def _phase(start: float, length: float) -> float:
    return min(1.0, max(0.0, (_t - start) / length))


def _ease(x: float) -> float:
    return x * x * (3.0 - 2.0 * x)


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


def showing(within_s: float = _ROTATE_WINDOW_S) -> bool:
    return (time.monotonic() - _painted_mono) < float(within_s)


def rotate(step: int) -> bool:
    """Encoder turn while the visualizer shows: next / previous preset. False when it isn't up."""
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
    ink = np.maximum(np.maximum(bgra[:, :, 0], bgra[:, :, 1]), bgra[:, :, 2]).astype(np.float32)
    keep = np.clip((ink - _PAGE_MAX) / float(_INK_MIN - _PAGE_MAX), 0.0, 1.0)
    out = bgra.copy()
    out[:, :, 3] = (a.astype(np.float32) * keep).astype(np.uint8)
    return out


class ClockOverlay:
    """One clocksaver frame, keyed and cropped to the box its pixels cover.

    A full-frame alpha blend costs ~50 ms on a Pi 5 in numpy; the face only
    changes once a second, so its box and straight colour are worked out once
    and each frame blends just that box with uint8 OpenCV ops (~2 ms).
    """

    def __init__(self, frame: np.ndarray) -> None:
        self._frame = key_page(frame)
        self._prepped: dict[tuple[int, int], tuple] = {}
        self._scaled: tuple[float, np.ndarray] | None = None

    def prep(self, h: int, w: int) -> tuple:
        """``(y0, x0, colour, alpha)``: the box's corner, straight BGR and 1-channel alpha (uint8)."""
        hit = self._prepped.get((h, w))
        if hit is not None:
            return hit
        f = self._frame
        if f.shape[:2] != (h, w):
            f = cv2.resize(f, (w, h), interpolation=cv2.INTER_AREA)
        a = f[:, :, 3]
        rows = np.flatnonzero(a.max(axis=1))
        cols = np.flatnonzero(a.max(axis=0))
        if rows.size == 0:
            out = (0, 0, np.zeros((0, 0, 3), np.uint8), np.zeros((0, 0), np.uint8))
        else:
            y0, y1, x0, x1 = int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1
            out = (y0, x0, np.ascontiguousarray(f[y0:y1, x0:x1, :3]), np.ascontiguousarray(a[y0:y1, x0:x1]))
        self._prepped[(h, w)] = out
        return out

    def top(self, h: int, w: int) -> int:
        return self.prep(h, w)[0]

    def _colour(self, colour: np.ndarray, gain: float) -> np.ndarray:
        g = round(float(gain), 3)
        hit = self._scaled
        if hit is None or hit[0] != g or hit[1].shape != colour.shape:
            hit = (g, colour if g >= 1.0 else cv2.convertScaleAbs(colour, alpha=g))
            self._scaled = hit
        return hit[1]

    def blit(self, canvas: np.ndarray, *, opacity: float = 1.0, gain: float = 1.0, dy: int = 0,
             under: bool = False) -> None:
        """Blend onto ``canvas``: ``gain`` scales brightness, ``dy`` moves it down (px),
        ``under`` keeps whatever bright pixels ``canvas`` already has on top."""
        if opacity <= 0.0:
            return
        h, w = canvas.shape[:2]
        y0, x0, colour, alpha = self.prep(h, w)
        bh, bw = alpha.shape
        top = y0 + int(dy)
        r0, r1 = max(0, top), min(h, top + bh)
        if r1 <= r0 or bw == 0:
            return
        colour = self._colour(colour, gain)[r0 - top : r1 - top]
        k = alpha[r0 - top : r1 - top]
        dst = canvas[r0:r1, x0 : x0 + bw]
        cur = dst[:, :, :3]
        if opacity < 1.0:
            k = cv2.convertScaleAbs(k, alpha=float(opacity))
        if under:
            lit = cv2.max(cv2.max(cur[:, :, 0], cur[:, :, 1]), cur[:, :, 2])
            cover = cv2.bitwise_not(cv2.convertScaleAbs(lit, alpha=255.0 / _COVER_MIN))  # 255 - lit*k, floored at 0
            k = cv2.multiply(k, cover, scale=1.0 / 255.0)
        k3 = cv2.merge((k, k, k))
        # colour * k + what was there * (1 - k), k in 0..255.
        out = cv2.add(
            cv2.multiply(colour, k3, scale=1.0 / 255.0),
            cv2.multiply(cur, cv2.bitwise_not(k3), scale=1.0 / 255.0),
        )
        cur[...] = out


# Faces, rendered once a second off the frame loop.
_lock = threading.Lock()
_faces: dict[str, tuple[object, ClockOverlay | None]] = {}
_busy: set[str] = set()


def _face(name: str, key: object, render, size: tuple[int, int]) -> ClockOverlay | None:
    """The overlay for ``name`` at ``key``: inline the first time, then a worker keeps it fresh."""
    with _lock:
        have, val = _faces.get(name, (None, None))
        start = have != key and val is not None and name not in _busy
        if start:
            _busy.add(name)
    if val is None:
        val = ClockOverlay(render())
        with _lock:
            _faces[name] = (key, val)
        return val
    if start:

        def _work() -> None:
            try:
                fresh = ClockOverlay(render())
                fresh.prep(*size)
                with _lock:
                    _faces[name] = (key, fresh)
            except Exception:
                pass
            finally:
                with _lock:
                    _busy.discard(name)

        threading.Thread(target=_work, name=f"pigeon-viz-backdrop-{name}", daemon=True).start()
    return val


def _digital_face() -> bool:
    try:
        from pigeon.auto_widgets import auto_clocksaver_wants_digital

        return bool(auto_clocksaver_wants_digital())
    except Exception:
        return False


def _render_digits() -> np.ndarray:
    from pigeon.widgets.clock_saver import render_clock_saver_bgra

    return render_clock_saver_bgra(prefer_digital=True, digits_only=True)


def compose(canvas: np.ndarray, key: object, render_full) -> None:
    """Draw this frame of the clocksaver / visualizer timeline into ``canvas`` (BGR, black).

    ``render_full()`` returns the regular clocksaver layers ``((frame, rect), date)``.
    """
    global _painted_mono
    _advance()
    h, w = canvas.shape[:2]
    extras = _ease(_phase(0.0, EXTRAS_S))  # 1 = date / weather / volume / seconds gone
    move = _ease(_phase(EXTRAS_S, MOVE_S))
    dim = _ease(_phase(EXTRAS_S + MOVE_S, DIM_S))
    viz = _phase(EXTRAS_S + MOVE_S + DIM_S, VIZ_S)
    leaving = _target() < _t
    digital = _digital_face()

    if viz > 0.0:
        try:
            _instance().render(canvas, silent=leaving)
            fade = min(1.0, viz / VIZ_FADE)
            if fade < 1.0:
                cv2.convertScaleAbs(canvas, dst=canvas, alpha=fade)
            _painted_mono = time.monotonic()
        except Exception:
            pass

    full_key = ("full", key)
    if extras < 1.0 or not digital:
        full = _face("full", full_key, lambda: render_full()[0][0], (h, w))
    else:
        full = None
    clock = (
        _face("digits", (int(time.time()),), _render_digits, (h, w)) if digital else full
    )
    if clock is None:
        return
    if digital and full is not None and extras < 1.0:
        # Fading phase: the time is still in place, the rest of the face fades.
        full.blit(canvas, opacity=1.0 - extras)
    dy = int(round((CLOCK_TOP_PX - clock.top(h, w)) * move)) if move > 0.0 else 0
    gain = 1.0 - (1.0 - CLOCK_DIM) * dim
    clock.blit(canvas, gain=gain, dy=dy, under=viz > 0.0)
