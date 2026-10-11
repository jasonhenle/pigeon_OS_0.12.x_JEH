"""Zone-4 meter: a pair of L/R level meters in zone 4, in place of the multi-band EQ.

The zone-4 visualizer used to be the multi-band EQ (:mod:`pigeon.zone4_eq`).
From across the room that much spectral detail reads as noise; a level meter
reads as what matters: signal, no signal, signal. Both styles reuse a
fullscreen preset's analysis (:class:`pigeon.fullscreen_viz.Analysis`), so
they move exactly like their fullscreen versions.

* ``sweep`` (default) — the "Sweep VU" pair: a spot of light riding an arched
  band on VU (RMS) ballistics, with a peak-hold marker. The arches are flattened
  to fit the strip.
* ``ladder`` — the "Meter Bridge": L/R peak LED ladders with thin RMS rows,
  laid flat (``layout`` ``mirror`` / ``split`` / ``stacked``).

``zone4_eq.json`` picks the visualizer (``"visualizer": "meters" | "eq"``) and
tunes this one under its ``"meter"`` key, hot-reloaded like the EQ params::

    {"visualizer": "meters", "meter": {"style": "sweep", "mode": "spot + fill"}}

Sweep keys default to the fullscreen ``sweep_vu`` style's (colors, ``mode``,
``spotDeg``, ``peakHold``, ballistics); ``spotDeg`` is relative to that style's
110° sweep, so the spot covers the same share of the scale here.
"""

from __future__ import annotations

import json
import math
import time

import cv2
import numpy as np

from pigeon import fullscreen_viz as _fv
from pigeon import zone4_eq as _audio

STYLES = ("sweep", "ladder")
LAYOUTS = ("mirror", "split", "stacked")

# Shared by both styles.
COMMON_DEFAULTS: dict[str, object] = {
    "style": "sweep",
    "insetPx": 10.0,  # track edge → meters
    "centerGap": 20.0,  # px between L and R
}

SWEEP_DEFAULTS: dict[str, object] = {
    "bandW": 22.0,  # arc band thickness, px
}

LADDER_DEFAULTS: dict[str, object] = {
    "layout": "mirror",
    "segments": 24,  # per channel
    "segGap": 4.0,  # px between segments
    "radius": 3.0,  # segment corner radius, px
    "showRms": True,
    "rmsFrac": 0.28,  # RMS row height / channel height
    "rowGap": 5.0,  # px between a channel's peak and RMS rows
    "scale": "IEC",
    "floorDbfs": -60.0,
    "warnDb": -18.0,
    "dangerDb": -6.0,
    "colSafe": "#3DDC84",
    "colWarn": "#F5C518",
    "colDanger": "#FF3B30",
    "rmsColor": "#4EA6F7",
    "unlit": 0.14,
    "peakHold": True,
    # Ballistics (fullscreen_viz.LEVEL_PARAMS)
    "holdMs": 1500.0,
    "fallDbS": 20.0,
}

# The fullscreen style's own 110° default sweep (``spotDeg`` is relative to it).
_SWEEP_REF_DEG = 110.0


def params() -> dict[str, object]:
    raw = _audio.params().get("meter")
    raw = raw if isinstance(raw, dict) else {}
    style = str(raw.get("style", COMMON_DEFAULTS["style"]))
    if style not in STYLES:
        style = str(COMMON_DEFAULTS["style"])
    if style == "sweep":
        p = _fv.complete_preset({"style": "sweep_vu"})
        p.update(COMMON_DEFAULTS)
        p.update(SWEEP_DEFAULTS)
    else:
        p = dict(COMMON_DEFAULTS)
        p.update(LADDER_DEFAULTS)
    p.update(raw)
    p["style"] = style
    if style == "ladder" and str(p.get("layout")) not in LAYOUTS:
        p["layout"] = LADDER_DEFAULTS["layout"]
    return p


def selected() -> bool:
    """``zone4_eq.json`` ``visualizer``: ``"meters"`` (default) or ``"eq"``."""
    return str(_audio.params().get("visualizer", "meters")).strip().lower() != "eq"


class _PxXf(_fv.Xf):
    """:class:`fullscreen_viz.Xf` without the 1280×800 design space: units are pixels × ``scale``."""

    def __init__(self, scale: float = 1.0) -> None:
        self.s, self.ox, self.oy = float(scale), 0.0, 0.0


class _Sweep(_fv.SweepVU):
    """The fullscreen Sweep VU, drawn on zone-4 arcs instead of its 1280×800 layout."""

    def __init__(self, meters: list[tuple[float, float, float, float, int]]) -> None:
        self._m = meters

    def _meters(self, p: dict) -> list[tuple[float, float, float, float, int]]:  # type: ignore[override]
        return self._m

    @staticmethod
    def _arc(img: np.ndarray, xf: _fv.Xf, cx: float, cy: float, r: float, t0: float, t1: float, color: tuple,
             w: float) -> None:
        """:meth:`SweepVU._arc` sampled every ~0.5°: cv2.ellipse steps 5° on big radii, which shows as facets here."""
        if t1 - t0 < 0.05:
            t1 = t0 + 0.05
        th = np.radians(np.linspace(t0, t1, max(2, int(math.ceil((t1 - t0) / 0.5)) + 1)))
        pts = np.stack(((xf.x(cx) + xf.l(r) * np.sin(th) - 0.5) * _fv._ONE,
                        (xf.y(cy) - xf.l(r) * np.cos(th) - 0.5) * _fv._ONE), axis=1)
        cv2.polylines(img, [np.round(pts).astype(np.int32)], False, color, xf.th(w), cv2.LINE_AA, _fv.SHIFT)


def sweep_geometry(p: dict, w: int, h: int) -> tuple[list[tuple[float, float, float, float, int]], float]:
    """``([(pivot x, pivot y, radius, band width, channel)], sweep°)`` for L and R in a ``w×h`` track.

    Each arc spans its half of the track: band ends touch the bottom inset and
    the sides of the half, the crown touches the top inset.
    """
    ins = max(0.0, _fv._f(p, "insetPx", 10.0))
    cg = max(0.0, _fv._f(p, "centerGap", 20.0))
    bw = max(2.0, _fv._f(p, "bandW", 22.0))
    hw = (w - 2.0 * ins - cg) / 2.0
    span = max(1.0, hw / 2.0 - bw / 2.0)  # crown → end, horizontally (band centerline)
    rise = max(1.0, h - 2.0 * ins - bw)  # crown → end, vertically
    half = 2.0 * math.atan(rise / span)
    R = span / math.sin(half)
    cy = ins + bw / 2.0 + R
    xs = (ins + hw / 2.0, ins + hw + cg + hw / 2.0)
    return [(xs[0], cy, R, bw, 0), (xs[1], cy, R, bw, 1)], math.degrees(2.0 * half)


class _Run:
    """``n`` segments along x from ``origin`` in direction ``sign`` (+1 → right), rows ``y0..y1``."""

    def __init__(self, origin: float, length: float, sign: int, y0: float, y1: float, n: int, gap: float) -> None:
        self.origin, self.sign, self.y0, self.y1 = origin, sign, y0, y1
        self.n, self.gap = n, gap
        self.pitch = (length + gap) / n

    def seg(self, k: int) -> tuple[float, float, float, float]:
        a = self.origin + self.sign * k * self.pitch
        b = a + self.sign * (self.pitch - self.gap)
        return min(a, b), self.y0, max(a, b), self.y1

    def _cut(self, k: int) -> float:
        """Boundary in the gap before segment ``k`` (k = n → past the far end)."""
        return self.origin + self.sign * (k * self.pitch - self.gap / 2.0)

    def reveal(self, img: np.ndarray, on: np.ndarray, k0: int, k1: int) -> None:
        """Copy segments ``k0..k1-1`` from the lit layer."""
        k0, k1 = max(0, k0), min(self.n, k1)
        if k1 <= k0:
            return
        a, b = self._cut(k0), self._cut(k1)
        c0, c1 = max(0, int(round(min(a, b)))), max(0, int(round(max(a, b))))
        r0, r1 = max(0, int(math.floor(self.y0))), max(0, int(math.ceil(self.y1)))
        img[r0:r1, c0:c1] = on[r0:r1, c0:c1]


class Zone4Meter:
    def __init__(self) -> None:
        self.analysis = _fv.Analysis()
        self._last_t: float | None = None
        self._layers_key: tuple | None = None
        self._layers: dict[str, object] = {}

    # -- sweep ------------------------------------------------------------------
    @staticmethod
    def _sweep_p(p: dict, sweep: float) -> dict:
        """``p`` with the arc's real sweep, and the spot scaled to keep its share of the scale."""
        spot = _fv._f(p, "spotDeg", 8.0) * sweep / _SWEEP_REF_DEG
        return dict(p, sweepDeg=sweep, spotDeg=spot)

    def _sweep_layers(self, p: dict, w: int, h: int, track: tuple[int, int, int]) -> dict[str, object]:
        ss = _fv.SS
        meters, sweep = sweep_geometry(p, w, h)
        ps = self._sweep_p(p, sweep)
        style = _Sweep(meters)
        base = np.empty((h * ss, w * ss, 3), np.uint8)
        base[:] = track
        xf = _PxXf(ss)
        groove = _fv._bgr(p["track"])
        red_groove = _fv._mix(groove, _fv._bgr(p["red"]), _fv._f(p, "redTint", 0.3))
        z = style._theta(ps, 1.0 / 1.4125)  # 0 VU
        for cx, cy, R, bw, _ch in meters:
            style._arc(base, xf, cx, cy, R, style._theta(ps, 0.0), style._theta(ps, 1.0), groove, bw)
            style._arc(base, xf, cx, cy, R, z, style._theta(ps, 1.0), red_groove, bw)
        return {"base": cv2.resize(base, (w, h), interpolation=cv2.INTER_AREA), "style": style, "p": ps}

    # -- geometry / static art ------------------------------------------------
    @staticmethod
    def _defl(p: dict, db: float) -> float:
        return _fv.LedLadder._defl(p, db)

    @staticmethod
    def _runs(p: dict, w: int, h: int) -> list[tuple[str, int, _Run]]:
        """``(kind, channel, run)`` in pixel space of the ``w×h`` track."""
        ins = max(0.0, _fv._f(p, "insetPx", 10.0))
        ax0, ax1, ay0, ay1 = ins, w - ins, ins, h - ins
        n = max(4, int(_fv._f(p, "segments", 24)))
        gap = max(0.0, _fv._f(p, "segGap", 4.0))
        cg = max(0.0, _fv._f(p, "centerGap", 20.0))
        rms = bool(p.get("showRms", True))
        rg = max(0.0, _fv._f(p, "rowGap", 5.0))
        frac = min(0.6, max(0.1, _fv._f(p, "rmsFrac", 0.28)))
        layout = str(p.get("layout"))

        def rows(top: float, bot: float, rms_below: bool = True) -> tuple[tuple[float, float], tuple[float, float] | None]:
            if not rms:
                return (top, bot), None
            rh = (bot - top - rg) * frac
            if rms_below:
                return (top, bot - rh - rg), (bot - rh, bot)
            return (top + rh + rg, bot), (top, top + rh)

        out: list[tuple[str, int, _Run]] = []
        if layout == "stacked":
            mid = (ay0 + ay1) / 2.0
            # RMS rows meet in the middle; peak rows sit on the outside.
            for ch, (top, bot, below) in enumerate(((ay0, mid - cg / 4.0, True), (mid + cg / 4.0, ay1, False))):
                pk, rr = rows(top, bot, below)
                out.append(("peak", ch, _Run(ax0, ax1 - ax0, 1, *pk, n, gap)))
                if rr:
                    out.append(("rms", ch, _Run(ax0, ax1 - ax0, 1, *rr, n, gap)))
            return out
        half = (ax1 - ax0 - cg) / 2.0
        pk, rr = rows(ay0, ay1)
        if layout == "split":
            starts = ((ax0, 1), (ax0 + half + cg, 1))
        else:  # mirror
            cx = (ax0 + ax1) / 2.0
            starts = ((cx - cg / 2.0, -1), (cx + cg / 2.0, 1))
        for ch, (origin, sign) in enumerate(starts):
            out.append(("peak", ch, _Run(origin, half, sign, *pk, n, gap)))
            if rr:
                out.append(("rms", ch, _Run(origin, half, sign, *rr, n, gap)))
        return out

    def _colors(self, p: dict, n: int, kind: str) -> list[tuple[int, int, int]]:
        if kind == "rms":
            return [_fv._bgr(p["rmsColor"])] * n
        warn = self._defl(p, _fv._f(p, "warnDb", -18.0))
        danger = self._defl(p, _fv._f(p, "dangerDb", -6.0))
        safe, wc, dc = _fv._bgr(p["colSafe"]), _fv._bgr(p["colWarn"]), _fv._bgr(p["colDanger"])
        return [dc if (k + 0.5) / n >= danger else wc if (k + 0.5) / n >= warn else safe for k in range(n)]

    def _layers_for(self, p: dict, w: int, h: int, r: int, track: tuple[int, int, int] | None) -> dict[str, object]:
        """Static art. ``track`` None → no plate: ``base`` / ``on`` are premultiplied
        on black, with ``base_a`` / ``on_a`` alpha mattes (rendered on black and white)."""
        key = (w, h, r, track, json.dumps(p, sort_keys=True, default=str))
        if key == self._layers_key:
            return self._layers
        ss = _fv.SS
        m = np.zeros((h * ss, w * ss), np.uint8)
        _fv._rrect(m, 0, 0, w * ss, h * ss, r * ss, 255)
        mask = cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        build = self._sweep_layers if p.get("style") == "sweep" else self._ladder_layers
        if track is None:
            black, white = build(p, w, h, (0, 0, 0)), build(p, w, h, (255, 255, 255))
            layers = dict(black, mask=mask)
            for name in ("base", "on"):
                if name in black:
                    k = black[name].astype(np.float32)  # type: ignore[union-attr]
                    wh = white[name].astype(np.float32)  # type: ignore[union-attr]
                    a = 1.0 - (wh - k).mean(axis=2) / 255.0
                    layers[name + "_a"] = np.clip(a, 0.0, 1.0)[:, :, None]
            self._layers = layers
        else:
            self._layers = dict(build(p, w, h, track), mask=mask)
        self._layers_key = key
        return self._layers

    def _ladder_layers(self, p: dict, w: int, h: int, track: tuple[int, int, int]) -> dict[str, object]:
        ss = _fv.SS
        base = np.empty((h * ss, w * ss, 3), np.uint8)
        base[:] = track
        on = base.copy()
        unlit = _fv._f(p, "unlit", 0.14)
        rad = int(round(max(0.0, _fv._f(p, "radius", 3.0)) * ss))
        runs = self._runs(p, w, h)
        for kind, _ch, run in runs:
            cols = self._colors(p, run.n, kind)
            for k in range(run.n):
                x0, y0, x1, y1 = (int(round(v * ss)) for v in run.seg(k))
                _fv._rrect(base, x0, y0, x1, y1, rad, _fv._mix(track, cols[k], unlit))
                _fv._rrect(on, x0, y0, x1, y1, rad, cols[k])
        down = lambda a: cv2.resize(a, (w, h), interpolation=cv2.INTER_AREA)  # noqa: E731
        return {"base": down(base), "on": down(on), "runs": runs}

    # -- frame ----------------------------------------------------------------
    def render_into(
        self,
        out: np.ndarray,
        track: tuple[int, int, int, int, int],
        track_bgr: tuple[int, int, int] | None = (35, 35, 35),
        *,
        capture: bool = True,
    ) -> None:
        """Paint both meters into the rounded rect ``(x, y, w, h, r)`` of ``out`` (BGR or BGRA).

        ``track_bgr`` fills the rect; None draws the meters straight over ``out``.
        """
        p = params()
        now = time.monotonic()
        dt = 1.0 / 30.0 if self._last_t is None else max(1e-3, min(0.1, now - self._last_t))
        self._last_t = now
        if capture:
            _audio.want_mic_capture()
        sweep = p.get("style") == "sweep"
        self.analysis.update(p, dt, ("vu", "ppm") if sweep else ("ppm",))

        tx, ty, tw, th, tr = (int(v) for v in track)
        oh, ow = out.shape[:2]
        if tw < 8 or th < 8 or tx >= ow or ty >= oh:
            return
        tr = max(0, min(tr, tw // 2, th // 2))
        clear = track_bgr is None
        if clear and (tx < 0 or ty < 0 or tx + tw > ow or ty + th > oh):
            return
        L = self._layers_for(p, tw, th, tr, None if clear else tuple(int(c) for c in track_bgr))
        if clear:
            dst = out[ty : ty + th, tx : tx + tw]
            under = dst[:, :, :3].astype(np.float32)

            def over(name: str) -> np.ndarray:
                lay = L[name].astype(np.float32)  # type: ignore[union-attr]
                return np.clip(under * (1.0 - L[name + "_a"]) + lay, 0, 255).astype(np.uint8)  # type: ignore[operator]

            img = over("base")
            on = over("on") if "on" in L else None
        else:
            img = L["base"].copy()  # type: ignore[union-attr]
            on = L.get("on")
        a = self.analysis
        if not sweep:
            for kind, ch, run in L["runs"]:  # type: ignore[union-attr]
                lvl = a.ppm[ch] if kind == "peak" else a.rms[ch]
                k = int(round(self._defl(p, float(lvl)) * run.n))
                run.reveal(img, on, 0, k)  # type: ignore[arg-type]
                if kind == "peak" and p.get("peakHold", True):
                    kh = int(round(self._defl(p, float(a.hold[ch])) * run.n))
                    if kh > k:
                        run.reveal(img, on, kh - 1, kh)  # type: ignore[arg-type]
        else:
            L["style"].draw(img, _PxXf(1.0), L["p"], a, L)  # type: ignore[union-attr]
        if clear:
            dst[:, :, :3] = img
            if dst.shape[2] >= 4:
                ink = (L["base_a"][:, :, 0] * 255.0).astype(np.uint8)  # type: ignore[index]
                dst[:, :, 3] = np.maximum(dst[:, :, 3], ink)
            return
        self._composite(out, img, L["mask"], tx, ty, tw, th)  # type: ignore[arg-type]

    @staticmethod
    def _composite(out: np.ndarray, img: np.ndarray, mask: np.ndarray, x: int, y: int, w: int, h: int) -> None:
        oh, ow = out.shape[:2]
        x0, y0, x1, y1 = max(0, x), max(0, y), min(ow, x + w), min(oh, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        src = img[y0 - y : y1 - y, x0 - x : x1 - x]
        mk = mask[y0 - y : y1 - y, x0 - x : x1 - x]
        dst = out[y0:y1, x0:x1]
        # Only the rounded corners are see-through; blend just those pixels.
        see = mk < 1.0
        a = mk[see][:, None]
        under = dst[:, :, :3][see].astype(np.float32)
        blended = (under * (1.0 - a) + src[see].astype(np.float32) * a).astype(np.uint8)
        dst[:, :, :3] = src
        dst[:, :, :3][see] = blended
        if dst.shape[2] >= 4:
            dst[:, :, 3] = np.maximum(dst[:, :, 3], (mk * 255.0).astype(np.uint8))
