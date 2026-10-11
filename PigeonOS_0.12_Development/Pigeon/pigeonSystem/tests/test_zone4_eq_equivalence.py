"""Zone-4 EQ: the vectorised renderer (5f376a3) must match the old one pixel for pixel.

5f376a3 replaced one ``_fill`` per bar / peak with ``Zone4EQ._fill_many`` and
added an opaque-pixel fast path to the composite in ``render_into``. The
reference below is the pre-5f376a3 ``_draw_set`` and ``render_into``, copied
verbatim except that ``params()`` / ``want_mic_capture()`` are called through
the ``zone4_eq`` module so the test can drive them. It lives here, not in
production code.

Every mismatch names its case (style, mode, peaks, gap, radius, track, levels,
geometry) with the largest channel difference, how many pixels differ and the
first one. ``PIGEON_Z4_EXHAUSTIVE=1`` runs the full cross product instead of
the default covering subset.
"""

from __future__ import annotations

import itertools
import math
import os
import sys
import unittest
from unittest import mock

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import zone4_eq  # noqa: E402
from pigeon.zone4_eq import GRID, _STEREO_SPLIT, _f, _hex_bgr, target_bands  # noqa: E402,F401

time = zone4_eq.time  # the reference's time.monotonic() is patched with zone4_eq's


class _ReferenceZone4EQ(zone4_eq.Zone4EQ):
    """Pre-5f376a3 renderer: one ``_fill`` per shape, full-patch float composite."""

    # -- verbatim from 5f376a3^ ----------------------------------------------
    @staticmethod
    def _blend(col: np.ndarray, alpha: np.ndarray, r0: int, c0: int, a: np.ndarray, bgr: np.ndarray) -> None:
        h, w = a.shape
        sub_c = col[r0 : r0 + h, c0 : c0 + w]
        sub_a = alpha[r0 : r0 + h, c0 : c0 + w]
        sub_c *= (1.0 - a)[:, :, None]
        sub_c += a[:, :, None] * bgr
        sub_a *= 1.0 - a
        sub_a += a

    @classmethod
    def _fill(cls, col: np.ndarray, alpha: np.ndarray, x0: float, x1: float, y0: float, y1: float,
              bgr: np.ndarray, radius: float = 0.0, opacity: float = 1.0) -> None:
        """Anti-aliased (optionally rounded) rect over ``col``/``alpha`` (patch-local)."""
        h, w = alpha.shape
        cx0, cx1 = max(0.0, x0), min(float(w), x1)
        cy0, cy1 = max(0.0, y0), min(float(h), y1)
        if cx1 - cx0 <= 1e-3 or cy1 - cy0 <= 1e-3:
            return
        c0, c1 = int(math.floor(cx0)), int(math.ceil(cx1))
        r0, r1 = int(math.floor(cy0)), int(math.ceil(cy1))
        r = min(float(radius), (x1 - x0) / 2.0, (y1 - y0) / 2.0)
        if r < 0.75 or x1 - x0 < 2.0:
            # Box coverage: exact for thin bars and square corners.
            cx = np.minimum(np.arange(c0, c1) + 1.0, cx1) - np.maximum(np.arange(c0, c1), cx0)
            ry = np.minimum(np.arange(r0, r1) + 1.0, cy1) - np.maximum(np.arange(r0, r1), cy0)
            a = ry[:, None] * cx[None, :]
        else:
            # Signed distance to the rounded rect, sampled at pixel centers.
            px = np.arange(c0, c1) + 0.5
            py = np.arange(r0, r1) + 0.5
            qx = np.abs(px - (x0 + x1) / 2.0) - ((x1 - x0) / 2.0 - r)
            qy = np.abs(py - (y0 + y1) / 2.0) - ((y1 - y0) / 2.0 - r)
            ox, oy = np.maximum(qx, 0.0)[None, :], np.maximum(qy, 0.0)[:, None]
            d = np.hypot(ox, oy) + np.minimum(np.maximum(qx[None, :], qy[:, None]), 0.0) - r
            a = np.clip(0.5 - d, 0.0, 1.0)
        cls._blend(col, alpha, r0, c0, (a * opacity).astype(np.float32), bgr)

    def _draw_set(self, col: np.ndarray, alpha: np.ndarray, p: dict[str, object], o: dict) -> None:
        """Bars for one channel. Band i covers grid range i/nF..(i+1)/nF (see the lab's drawSet)."""
        n_f = o["nF"]
        slot = o["w"] / n_f
        gap = max(_f(p, "minGapPx"), slot * _f(p, "gapPct") / 100.0)
        bw = max(0.5, slot - gap)
        count = int(math.ceil(n_f - 1e-3))
        span = count * slot
        anchor = o.get("anchor", "start")
        if anchor == "center":
            origin = o["x0"] + (o["w"] - span) / 2.0
        elif anchor == "end":
            origin = o["x0"] + o["w"] - span
        else:
            origin = o["x0"]
        style = str(p.get("style"))
        direction = "mid" if style == "mirror" else o.get("dir", "up")
        top, H = o["top"], o["h"]
        sub_w = bw * o.get("sub_w", 1.0)
        sub_off = bw * o.get("sub_off", 0.0)
        radius = _f(p, "barRadius")
        opacity = o.get("opacity", 1.0)
        agg = str(p.get("agg"))
        min_lvl = _f(p, "minLevel")
        peak_h = _f(p, "peakH")
        led_h, led_gap = _f(p, "ledH"), _f(p, "ledGap")
        col_pk = _hex_bgr(p.get("colPeak"), "#ffffff")
        ch = o["ch"]

        def run_y(d: float, length: float) -> float:
            if direction == "up":
                return top + H - d - length
            if direction == "down":
                return top + d
            return top + (H - length) / 2.0

        for i in range(count):
            g0 = i / n_f * GRID
            g1 = min(float(GRID), (i + 1) / n_f * GRID)
            lvl = max(min_lvl, self._sample(ch.level, g0, g1, agg))
            pk = self._sample(ch.peak, g0, g1, "max")
            if o.get("reverse"):
                slot_x = (o["x0"] + o["w"] - (i + 1) * slot) if anchor == "start" else origin + (count - 1 - i) * slot
            else:
                slot_x = origin + i * slot
            x = slot_x + gap / 2.0 + sub_off
            cx = x + sub_w / 2.0
            bal = None
            if o.get("balance"):
                bl, br = o["balance"]
                lv = self._sample(bl.level, g0, g1, agg)
                rv = self._sample(br.level, g0, g1, agg)
                bal = (rv - lv) / max(1e-3, rv + lv)
            c = self._bar_color(p, i, count, lvl, cx, o, bal)
            h = lvl * H
            if style == "led":
                seg = led_h + led_gap
                lit = int(round(h / seg))
                y_mid = top + (H - lit * seg + led_gap) / 2.0
                for k in range(lit):
                    y = y_mid + k * seg if direction == "mid" else run_y(k * seg, led_h)
                    self._fill(col, alpha, x, x + sub_w, y, y + led_h, c, radius, opacity)
            elif style == "dots":
                d = min(sub_w, H * 0.25)
                y = run_y(lvl * (H - d), d)
                self._fill(col, alpha, cx - d / 2.0, cx + d / 2.0, y, y + d, c, d / 2.0, opacity)
            else:  # bars / mirror (line falls back to bars)
                y = run_y(0.0, h)
                self._fill(col, alpha, x, x + sub_w, y, y + h, c, radius, opacity)
            if p.get("peaks", True) and style not in ("line", "dots"):
                dist = pk * H
                if direction == "up":
                    py = top + H - dist - peak_h
                elif direction == "down":
                    py = top + dist
                else:
                    py = top + (H - dist) / 2.0 - peak_h
                py = max(top, min(top + H - peak_h, py))
                self._fill(col, alpha, x, x + sub_w, py, py + peak_h, col_pk,
                           min(radius, peak_h / 2.0), opacity)

    def render_into(
        self,
        out: np.ndarray,
        track: tuple[int, int, int, int, int],
        progress: float,
        track_bgr: tuple[int, int, int] = (35, 35, 35),
    ) -> None:
        """Paint the visualizer into the rounded rect ``(x, y, w, h, r)``.

        ``track_bgr`` fills the container behind the bars.
        """
        p = zone4_eq.params()
        now = time.monotonic()
        dt = 1.0 / 30.0 if self._last_t is None else max(1e-3, min(0.1, now - self._last_t))
        self._last_t = now
        zone4_eq.want_mic_capture()
        mode = str(p.get("stereoMode") or "mono")
        if mode == "mono":
            names: tuple[str, ...] = ("M",)
        elif mode == "mid + balance color":
            names = ("M", "L", "R")
        else:
            names = ("L", "R")
        self._analyse(p, dt, names)

        prog = max(0.0, min(1.0, float(progress)))
        target = target_bands(p, prog)
        if self._bands is None:
            self._bands = target
        morph = _f(p, "morphS")
        k = 1.0 - math.exp(-dt / (morph / 3.0)) if morph > 0 else 1.0
        self._bands += (target - self._bands) * k
        n_f = max(1.0, self._bands)

        tx, ty, tw, th, tr = (int(v) for v in track)
        oh, ow = out.shape[:2]
        if tw < 2 or th < 2 or tx >= ow or ty >= oh:
            return
        col = np.zeros((th, tw, 3), dtype=np.float32)
        alpha = np.zeros((th, tw), dtype=np.float32)
        if p.get("showTrack", True):
            col[:] = np.array(track_bgr, dtype=np.float32)
            alpha[:] = 1.0

        ins = _f(p, "insetPx")
        ax, ay, aw, ah = ins, ins, tw - 2 * ins, th - 2 * ins
        play_x = tw * prog
        ch_l, ch_r = self._ch["L"], self._ch["R"]
        if p.get("swapLR"):
            ch_l, ch_r = ch_r, ch_l
        anchor = {"left": "start", "center": "center", "right": "end"}.get(str(p.get("anchor")), "start")
        base = {"top": ay, "h": ah, "dir": "up", "ax": ax, "aw": aw, "play_x": play_x}
        left = dict(base, ch=ch_l, name="L")
        right = dict(base, ch=ch_r, name="R")
        gap_c = _f(p, "splitGapPx")
        half_w = (aw - gap_c) / 2.0
        n_side = n_f if p.get("bandsPerSide", True) or mode not in _STEREO_SPLIT else max(1.0, n_f / 2.0)
        draw = lambda o: self._draw_set(col, alpha, p, o)  # noqa: E731
        if mode in _STEREO_SPLIT:
            draw(dict(left, x0=ax, w=half_w, nF=n_side, reverse=mode == "butterfly (bass center)"))
            draw(dict(right, x0=ax + half_w + gap_c, w=half_w, nF=n_side, reverse=mode == "bass at edges"))
        elif mode == "top/bottom":
            g = min(gap_c, ah * 0.3)
            hh = (ah - g) / 2.0
            draw(dict(left, x0=ax, w=aw, nF=n_f, anchor=anchor, top=ay, h=hh, dir="up"))
            draw(dict(right, x0=ax, w=aw, nF=n_f, anchor=anchor, top=ay + hh + g, h=hh, dir="down"))
        elif mode == "interleave":
            draw(dict(left, x0=ax, w=aw, nF=n_f, anchor=anchor, sub_off=0.0, sub_w=0.48))
            draw(dict(right, x0=ax, w=aw, nF=n_f, anchor=anchor, sub_off=0.52, sub_w=0.48))
        elif mode == "overlay":
            # The lab uses a "screen" blend; plain alpha is close enough here.
            op = max(0.05, min(1.0, _f(p, "overlayAlpha")))
            draw(dict(left, x0=ax, w=aw, nF=n_f, anchor=anchor, opacity=op))
            draw(dict(right, x0=ax, w=aw, nF=n_f, anchor=anchor, opacity=op))
        elif mode == "mid + balance color":
            draw(dict(base, ch=self._ch["M"], name="M", x0=ax, w=aw, nF=n_f, anchor=anchor,
                      balance=(ch_l, ch_r)))
        else:
            draw(dict(base, ch=self._ch["M"], name="M", x0=ax, w=aw, nF=n_f, anchor=anchor))

        alpha *= self._round_mask(tw, th, tr)
        x1, y1 = min(ow, tx + tw), min(oh, ty + th)
        x0, y0 = max(0, tx), max(0, ty)
        pa = alpha[y0 - ty : y1 - ty, x0 - tx : x1 - tx, None]
        pc = col[y0 - ty : y1 - ty, x0 - tx : x1 - tx]
        dst = out[y0:y1, x0:x1]
        dst[:, :, :3] = (dst[:, :, :3].astype(np.float32) * (1.0 - pa) + pc * pa).astype(np.uint8)
        if dst.shape[2] >= 4:
            dst[:, :, 3] = np.maximum(dst[:, :, 3], (pa[:, :, 0] * 255.0).astype(np.uint8))
    # -- end verbatim --------------------------------------------------------



def _diff_report(label: str, ref: np.ndarray, got: np.ndarray) -> str | None:
    """None when equal, else a one-line description of the mismatch."""
    if ref.shape != got.shape:
        return f"{label}: shape {got.shape} != reference {ref.shape}"
    d = np.abs(ref.astype(np.int32) - got.astype(np.int32))
    if d.ndim == 3:
        d = d.max(axis=2)
    bad = np.argwhere(d > 0)
    if bad.size == 0:
        return None
    y, x = (int(v) for v in bad[0])
    return (
        f"{label}: max diff {int(d.max())}, {len(bad)} px differ, "
        f"first at (y={y}, x={x}) ref={ref[y, x].tolist()} got={got[y, x].tolist()}"
    )


# ---------------------------------------------------------------------------
# Primitive: _fill_many == one reference _fill per rect, in order
# ---------------------------------------------------------------------------
_PATCH_H, _PATCH_W = 40, 160


def _canvas(seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    col = rng.random((_PATCH_H, _PATCH_W, 3), dtype=np.float32) * 255.0
    alpha = rng.random((_PATCH_H, _PATCH_W), dtype=np.float32)
    return col, alpha


def _rect(x0, x1, y0, y1, radius=0.0, opacity=1.0, bgr=(10.0, 200.0, 90.0)):
    return (float(x0), float(x1), float(y0), float(y1), np.array(bgr, dtype=np.float32), float(radius), float(opacity))


def _row_of_bars(rng: np.random.Generator, n: int, slot: float, gap: float, radius: float,
                 x_off: float = 0.0, h_range: tuple[float, float] = (0.0, _PATCH_H)) -> list:
    rects = []
    for i in range(n):
        x = x_off + i * slot + gap / 2.0
        h = float(rng.uniform(*h_range))
        y1 = float(rng.uniform(h, _PATCH_H + 4.0))
        rects.append(_rect(x, x + slot - gap, y1 - h, y1, radius, float(rng.choice([1.0, 0.6])),
                           tuple(float(v) for v in rng.uniform(0, 255, 3))))
    return rects


class FillManyMatchesPerRectFillTests(unittest.TestCase):
    """``Zone4EQ._fill_many`` against the reference ``_fill`` loop."""

    def _check(self, label: str, rects: list, seed: int = 0) -> None:
        ref_col, ref_alpha = _canvas(seed)
        got_col, got_alpha = ref_col.copy(), ref_alpha.copy()
        for r in rects:
            _ReferenceZone4EQ._fill(ref_col, ref_alpha, *r)
        zone4_eq.Zone4EQ._fill_many(got_col, got_alpha, rects)
        problems = [p for p in (
            _diff_report(f"{label} col", ref_col, got_col),
            _diff_report(f"{label} alpha", ref_alpha, got_alpha),
        ) if p]
        if problems:
            self.fail("\n".join(problems) + "\nrects=" + repr([r[:4] + r[5:] for r in rects]))

    def test_column_disjoint_rows_every_radius_and_gap(self) -> None:
        rng = np.random.default_rng(1)
        for radius, gap, slot in itertools.product((0.0, 0.5, 1.0, 3.0, 30.0), (1.5, 3.2, 6.0), (6.0, 11.9, 17.3)):
            with self.subTest(radius=radius, gap=gap, slot=slot):
                n = int(_PATCH_W // slot)
                self._check(f"radius={radius} gap={gap} slot={slot}", _row_of_bars(rng, n, slot, gap, radius, 0.37))

    def test_very_short_and_thin_bars(self) -> None:
        rng = np.random.default_rng(2)
        for radius, h_max in itertools.product((0.0, 3.0, 30.0), (0.2, 0.9, 1.4, 1.6, 3.0)):
            with self.subTest(radius=radius, h_max=h_max):
                self._check(f"short radius={radius} h<={h_max}",
                            _row_of_bars(rng, 14, 11.0, 3.0, radius, 0.61, (0.0, h_max)))
        for w in (0.3, 0.9, 1.5, 1.99, 2.0, 2.5):
            with self.subTest(width=w):
                rects = [_rect(3 + i * 7.3, 3 + i * 7.3 + w, 5.25, 33.75, 3.0) for i in range(18)]
                self._check(f"thin w={w}", rects)

    def test_clipped_and_degenerate_rects(self) -> None:
        rects = [
            _rect(-6.4, 3.1, 4.0, 30.0, 3.0),                     # off the left edge
            _rect(10.2, 18.9, -9.5, 12.0, 30.0),                   # off the top
            _rect(25.5, 33.0, 30.0, _PATCH_H + 7.0, 3.0),          # off the bottom
            _rect(_PATCH_W - 4.0, _PATCH_W + 9.0, 2.0, 20.0, 2.0),  # off the right edge
            _rect(40.0, 48.0, 50.0, 60.0, 3.0),                    # entirely below
            _rect(-20.0, -10.0, 5.0, 25.0, 3.0),                   # entirely left
            _rect(60.0, 60.0005, 5.0, 25.0, 3.0),                  # zero width
            _rect(70.0, 78.0, 12.0, 12.0005, 3.0),                 # zero height
            _rect(90.0, 98.0, -3.0, _PATCH_H + 3.0, 30.0),         # taller than the patch
        ]
        self._check("clipped", rects)
        self._check("nothing", [])
        self._check("all outside", [_rect(-9, -1, 0, 10), _rect(0, 10, -30, -1)])

    def test_overlapping_columns_fall_back_in_input_order(self) -> None:
        # Shared pixel columns need ordered blending; input order must win,
        # even when the rects are not sorted left to right.
        rng = np.random.default_rng(3)
        cases = {
            "touching, gapless": _row_of_bars(rng, 16, 10.0, 0.0, 3.0, 0.4),
            "bar with its peak": [_rect(10.3, 18.7, 10.0, 38.0, 3.0), _rect(10.3, 18.7, 6.0, 9.0, 1.5, bgr=(255, 255, 255))],
            "unsorted overlap": [_rect(30.2, 44.9, 5.0, 35.0, 3.0, 0.6, (0, 0, 255)),
                                 _rect(20.1, 34.8, 10.0, 30.0, 30.0, 0.6, (255, 0, 0))],
            "sub-pixel neighbours": [_rect(5.2, 9.6, 0, 40), _rect(9.4, 13.9, 0, 40, 0, 0.5, (0, 255, 0))],
        }
        for label, rects in cases.items():
            with self.subTest(case=label):
                self._check(label, rects)

    def test_random_disjoint_sets(self) -> None:
        rng = np.random.default_rng(4)
        for k in range(60):
            slot = float(rng.uniform(4.0, 20.0))
            gap = float(rng.uniform(1.01, slot * 0.6))
            radius = float(rng.choice([0.0, 0.7, 2.0, 5.0, 30.0]))
            with self.subTest(k=k, slot=slot, gap=gap, radius=radius):
                self._check(f"random k={k}", _row_of_bars(rng, int(_PATCH_W // slot), slot, gap, radius,
                                                           float(rng.uniform(-3, 3))), seed=k)


# ---------------------------------------------------------------------------
# Whole render: render_into == reference render_into
# ---------------------------------------------------------------------------
_MODES = ("mono", "split", "butterfly (bass center)", "bass at edges", "top/bottom",
          "interleave", "overlay", "mid + balance color")
_STYLES = ("bars", "mirror", "led", "dots", "line")
_RADII = (0.0, 1.0, 3.0, 30.0)
_GAPS = ((22.0, 2.0), (27.0, 0.0), (0.0, 0.0), (4.0, 0.5))  # (gapPct, minGapPx); 0/0 overlaps columns
_LEVELS = ("random", "very short", "full")
_RECT = (113, 536, 1067, 100, 13)                          # live zone-4 geometry
_OUT_H, _OUT_W = 700, 1280


def _levels(kind: str, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    if kind == "very short":  # under a pixel .. a couple of pixels on a 88 px track
        lvl = rng.uniform(0.0, 0.025, GRID).astype(np.float32)
    elif kind == "full":
        lvl = np.ones(GRID, dtype=np.float32)
    else:
        lvl = (rng.random(GRID).astype(np.float32)) ** 2
    pk = np.minimum(1.0, lvl + rng.random(GRID).astype(np.float32) * 0.2).astype(np.float32)
    return lvl, pk


_BACKGROUNDS: dict[int, np.ndarray] = {}


def _background(channels: int) -> np.ndarray:
    """Random stand-in for the screen under zone 4 (shared; callers copy it)."""
    if channels not in _BACKGROUNDS:
        _BACKGROUNDS[channels] = np.random.default_rng(99).integers(0, 255, (_OUT_H, _OUT_W, channels), dtype=np.uint8)
    return _BACKGROUNDS[channels]


def _render(cls, p: dict, rect: tuple, levels: str, channels: int, frames: int = 2) -> np.ndarray:
    eq = cls()
    eq._analyse = lambda *a, **k: None
    for n, ch in enumerate(eq._ch.values()):
        ch.level[:], ch.peak[:] = _levels(levels, 10 + n)
    out = _background(channels).copy()
    clock = iter([100.0 + i / 30.0 for i in range(frames + 1)])
    with mock.patch.object(zone4_eq, "params", return_value=p), \
         mock.patch.object(zone4_eq, "want_mic_capture"), \
         mock.patch.object(zone4_eq.time, "monotonic", side_effect=lambda: next(clock)):
        for f in range(frames):
            eq.render_into(out, rect, 0.37 + f * 0.01, track_bgr=(35, 35, 35))
    return out


def _render_cases():
    """Every style x mode x peaks x track (160 cases), each with one radius /
    gap / levels choice. The four peaks x track cases of a style x mode pair
    get all four radii and all four gaps, and the shift between them changes
    from pair to pair, so every radius x gap combination occurs. With
    ``PIGEON_Z4_EXHAUSTIVE=1`` each case runs every radius x gap x levels."""
    exhaustive = os.environ.get("PIGEON_Z4_EXHAUSTIVE", "").strip() == "1"
    base = itertools.product(_STYLES, _MODES, (True, False), (True, False))
    for n, (style, mode, peaks, track) in enumerate(base):
        if exhaustive:
            extras = itertools.product(_RADII, _GAPS, _LEVELS)
        else:
            pair, j = divmod(n, 4)
            extras = [(_RADII[j], _GAPS[(j + pair) % len(_GAPS)], _LEVELS[n % len(_LEVELS)])]
        for radius, gap, levels in extras:
            yield dict(style=style, stereoMode=mode, peaks=peaks, showTrack=track, barRadius=radius,
                       gapPct=gap[0], minGapPx=gap[1], levels=levels)


class RenderMatchesReferenceTests(unittest.TestCase):
    """``Zone4EQ.render_into`` (vectorised fills + composite fast path) vs the reference."""

    def _compare(self, case: dict, *, rect: tuple = _RECT, channels: int = 4, extra: dict | None = None,
                 frames: int = 2) -> str | None:
        levels = case["levels"]
        p = dict(zone4_eq.DEFAULT_PARAMS)
        p.update({k: v for k, v in case.items() if k != "levels"})
        p.update(extra or {})
        ref = _render(_ReferenceZone4EQ, p, rect, levels, channels, frames)
        got = _render(zone4_eq.Zone4EQ, p, rect, levels, channels, frames)
        label = ", ".join(f"{k}={v!r}" for k, v in {**case, **(extra or {}), "rect": rect, "channels": channels}.items())
        return _diff_report(label, ref, got)

    def test_styles_modes_peaks_gaps_radii_track(self) -> None:
        cases = list(_render_cases())
        combos = {(c["barRadius"], c["gapPct"], c["minGapPx"]) for c in cases}
        self.assertEqual(len(combos), len(_RADII) * len(_GAPS))  # covering subset really covers
        failures = [r for r in (self._compare(c, frames=1) for c in cases) if r]
        if failures:
            self.fail(f"{len(failures)} case(s) differ:\n" + "\n".join(failures[:25]))

    def test_live_config_butterfly(self) -> None:
        live = dict(minBands=41, maxBands=41, gamma=2.05, fMax=5200, autoGain=True, gapPct=27, minGapPx=0,
                    barRadius=30, ledH=8.5, peaks=False, stereoMode="butterfly (bass center)", splitGapPx=80,
                    colL="#ffffff", colR="#939393", colA="#00364a", colB="#232323", colPeak="#606060")
        for levels in _LEVELS:
            with self.subTest(levels=levels):
                self.assertIsNone(self._compare({"levels": levels}, extra=live))

    def test_clipped_geometry_and_bgr_output(self) -> None:
        cases = [
            ("inset pushes bars past the track", _RECT, 4, {"insetPx": -12.0}),
            ("track off the right edge", (_OUT_W - 400, 300, 1067, 100, 13), 4, {}),
            ("track off the bottom and left", (-150, _OUT_H - 60, 1067, 100, 13), 4, {}),
            ("3-channel BGR output", _RECT, 3, {}),
            ("tiny track", (40, 40, 60, 12, 5), 4, {}),
        ]
        for label, rect, channels, extra in cases:
            for style, peaks in (("bars", True), ("mirror", False), ("led", True)):
                with self.subTest(case=label, style=style):
                    report = self._compare({"style": style, "peaks": peaks, "levels": "random",
                                            "stereoMode": "butterfly (bass center)"},
                                           rect=rect, channels=channels, extra=extra)
                    self.assertIsNone(report, report)


if __name__ == "__main__":
    unittest.main()
