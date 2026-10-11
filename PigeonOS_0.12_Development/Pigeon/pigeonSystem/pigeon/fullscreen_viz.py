"""Fullscreen visualizer: encoder-selectable presets drawn for the 1280×800 canvas.

Each preset is a *style* plus that style's parameters. Some styles borrow
from studio hardware (digital, pixel and sweep VU pairs, LED meter bridge,
RTA, spectrum bars) and some don't (skyline, dot matrix, bounce, fireflies). Presets live
in ``fullscreen_viz.json`` in the Pigeon state dir and are re-read when the
file changes, the same way ``zone4_eq.json`` is; the lab in
``testingEnvironments/fullscreen_viz_lab.py`` edits and saves them.

Audio comes from the zone-4 EQ PCM ring (:mod:`pigeon.zone4_eq`), so the Pi's
ALSA meter capture and the macOS mic fallback feed both visualizers.

Rendering is size-independent: every style lays itself out in 1280×800 design
units and scales uniformly (letterboxed) into whatever box it is given, so the
same preset can later fill zone 6 (793×488). Per size, a style's static art
(faces, scales, labels, unlit LED segments) is drawn once at 2× and
area-downsampled into cached layers; a frame is one copy of that layer plus
the moving parts. LED styles also cache a fully-lit layer and reveal it with
slice copies, so their per-frame cost is almost nothing. Flat colors only.

Styles that print numbers (dB scales, readouts, frequencies) have a
``showText`` switch, off by default: the numbers only mean something once the
input level is calibrated.
"""

from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from pigeon import zone4_eq as _audio
from pigeon.font_cache import load_font
from pigeon.font_paths import resolve_digital7_font, resolve_ui_font_bold, resolve_ui_font_medium
from pigeon.runtime_paths import pigeon_state_dir

DESIGN_W = 1280
DESIGN_H = 800
CONFIG_NAME = "fullscreen_viz.json"
GRID = 512
SS = 2  # static layers are drawn at 2× then area-downsampled (anti-aliasing)
SHIFT = 4  # cv2 fixed-point bits for sub-pixel drawing
_ONE = float(1 << SHIFT)
TOAST_S = 1.6
_CONFIG_POLL_S = 0.5
_LAYER_CACHE = 24
STATE_KEY = "fullscreen_viz_preset"  # app state: preset last picked with the encoder
REMEMBER_AFTER_S = 2.0

# Set on a preset copy while building alpha-matted layers (``render(clear=True)``).
MATTE_BG_KEY = "_matte_bg"

# Zone 6 on the now-playing canvas (design px); the eventual zone-6 visualizer
# is a preset rendered into this box.
ZONE6_RECT = (44, 34, 793, 488, 13)

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
# Spec kinds (used by the lab to build its controls):
#   ("num", lo, hi, step) · ("color",) · ("bool",) · ("choice", options)


def _n(lo: float, hi: float, step: float = 1.0) -> tuple:
    return ("num", lo, hi, step)


_C = ("color",)
_B = ("bool",)


def _ch(*opts: object) -> tuple:
    return ("choice", opts)


# Spectrum analysis, shared by every style that shows a spectrum.
ANALYSIS_PARAMS: dict[str, tuple[object, tuple]] = {
    "fftSize": (4096, _ch(2048, 4096, 8192, 16384)),
    "fMin": (30.0, _n(10, 200, 1)),
    "fMax": (16000.0, _n(2000, 22000, 100)),
    "floorDb": (-80.0, _n(-120, -30, 1)),
    "ceilDb": (-15.0, _n(-40, 0, 1)),
    "tilt": (3.0, _n(-6, 9, 0.5)),
    "attackMs": (25.0, _n(0, 300, 5)),
    "releaseMs": (250.0, _n(20, 2000, 10)),
    "peakHoldMs": (500.0, _n(0, 3000, 50)),
    "peakFall": (0.6, _n(0.05, 3.0, 0.05)),
}

# Level metering (VU needles, PPM ladders).
LEVEL_PARAMS: dict[str, tuple[object, tuple]] = {
    "refDbfs": (-18.0, _n(-30, -6, 1)),  # 0 VU
    "riseMs": (300.0, _n(50, 1000, 10)),  # VU: 99 % of a step
    "damping": (0.8, _n(0.3, 1.5, 0.05)),  # needle ζ (0.8 ≈ 1.5 % overshoot)
    "holdMs": (1500.0, _n(0, 5000, 100)),  # PPM peak hold
    "fallDbS": (20.0, _n(3, 60, 1)),  # PPM return, dB/s
}

STYLES: dict[str, dict[str, object]] = {
    "arc_vu": {
        "label": "Digital VU pair (LED arc)",
        "needs": ("vu", "ppm"),
        "params": {
            "bg": ("#000000", _C),
            "face": ("#EDE6D3", _C),
            "ink": ("#1A1A1A", _C),
            "segColor": ("#1A1A1A", _C),
            "red": ("#D9412B", _C),
            "cover": ("#1A1A1A", _C),
            "coverText": ("#EDE6D3", _C),
            "showText": (False, _B),
            "label": ("VU", ("text",)),
            "segments": (36.0, _n(8, 80, 1)),
            "segGapPct": (35.0, _n(0, 80, 1)),
            "segLen": (38.0, _n(8, 120, 1)),
            "unlit": (0.12, _n(0, 0.6, 0.01)),
            "peakHold": (True, _B),
            "peakLed": (True, _B),
            "peakLedColor": ("#FF3B30", _C),
            "peakLedDbfs": (-3.0, _n(-12, 0, 0.5)),
            "sweepDeg": (90.0, _n(60, 110, 1)),
            "faceRadius": (24.0, _n(0, 80, 1)),
            "meterW": (580.0, _n(400, 620, 2)),
            "meterH": (420.0, _n(300, 560, 2)),
        },
    },
    "pixel_vu": {
        "label": "Pixel VU pair (lo-fi)",
        "needs": ("vu", "ppm"),
        "params": {
            "palette": ("cream", _ch("cream", "gameboy", "amber", "night", "custom")),
            "bg": ("#000000", _C),
            "face": ("#EDE6D3", _C),
            "ink": ("#1A1A1A", _C),
            "red": ("#D9412B", _C),
            "cover": ("#1A1A1A", _C),
            "showText": (False, _B),
            "pixel": (8.0, _n(3, 20, 1)),
            "needlePx": (1, _ch(1, 2)),
            "peakLed": (True, _B),
            "peakLedColor": ("#FF3B30", _C),
            "peakLedDbfs": (-3.0, _n(-12, 0, 0.5)),
            "sweepDeg": (90.0, _n(60, 110, 1)),
            "meterW": (580.0, _n(400, 620, 2)),
            "meterH": (420.0, _n(300, 560, 2)),
        },
    },
    "sweep_vu": {
        "label": "Sweep VU (arched light, no needle)",
        "needs": ("vu", "ppm"),
        "params": {
            "bg": ("#000000", _C),
            "track": ("#4D4D4D", _C),  # groove gray, matches the volume ring's unfilled track
            "lit": ("#4EA6F7", _C),
            "fillColor": ("#1F4F7A", _C),
            "red": ("#FF3B30", _C),
            "redTint": (0.3, _n(0, 1, 0.01)),
            "text": ("#8A8A8A", _C),
            "showText": (False, _B),
            "showTicks": (True, _B),
            "layout": ("pair", _ch("pair", "single")),
            "mode": ("spot", _ch("spot", "fill", "spot + fill")),
            "spotDeg": (8.0, _n(1, 40, 0.5)),
            "peakHold": (True, _B),
            "sweepDeg": (110.0, _n(60, 180, 1)),
            "arcR": (290.0, _n(120, 320, 2)),
            "bandW": (64.0, _n(8, 120, 1)),
            "inset": (0.72, _n(0.2, 1.0, 0.01)),
        },
    },
    "bars": {
        "label": "Spectrum bars",
        "needs": ("spectrum",),
        "params": {
            "bg": ("#000000", _C),
            "colA": ("#4EA6F7", _C),
            "colB": ("#FF6A00", _C),
            "peakColor": ("#FFFFFF", _C),
            "slotColor": ("#141414", _C),
            "showSlots": (False, _B),  # no dark slot tracks behind the bars
            "bands": (64.0, _n(8, 160, 1)),
            "gapPct": (30.0, _n(0, 80, 1)),
            "minGapPx": (2.0, _n(0, 12, 1)),
            "radius": (8.0, _n(0, 40, 1)),
            "layout": ("up", _ch("up", "mirror", "split stereo")),
            "colorMode": ("solid", _ch("solid", "band hue", "channel", "two-tone")),
            "twoToneAt": (0.75, _n(0.3, 0.95, 0.01)),
            "hueStart": (200.0, _n(0, 360, 1)),
            "hueSpan": (240.0, _n(0, 360, 1)),
            "peaks": (True, _B),
            "peakH": (6.0, _n(1, 20, 1)),
            "minLevel": (0.02, _n(0, 0.3, 0.01)),
            "insetX": (56.0, _n(0, 240, 2)),
            "top": (96.0, _n(0, 380, 2)),
            "bottom": (704.0, _n(420, 800, 2)),
        },
    },
    "led_ladder": {
        "label": "LED meter bridge",
        "needs": ("ppm",),
        "params": {
            "bg": ("#000000", _C),
            "orientation": ("vertical", _ch("vertical", "horizontal")),
            "segments": (48.0, _n(12, 120, 1)),
            "segGap": (3.0, _n(0, 12, 0.5)),
            "barW": (130.0, _n(40, 240, 2)),
            "scale": ("IEC", _ch("IEC", "linear")),
            "floorDbfs": (-60.0, _n(-90, -20, 1)),
            "warnDb": (-18.0, _n(-40, 0, 1)),
            "dangerDb": (-6.0, _n(-20, 0, 1)),
            "colSafe": ("#3DDC84", _C),
            "colWarn": ("#F5C518", _C),
            "colDanger": ("#FF3B30", _C),
            "unlit": (0.14, _n(0, 0.6, 0.01)),
            "showRms": (True, _B),
            "rmsColor": ("#4EA6F7", _C),
            "showText": (False, _B),
            "panel": ("#161616", _C),
            "text": ("#8A8A8A", _C),
        },
    },
    "rta": {
        "label": "1/3-octave RTA",
        "needs": ("spectrum",),
        "params": {
            "bg": ("#000000", _C),
            "bandSet": ("31 (1/3 oct)", _ch("10 (octave)", "20 (1/2 oct)", "31 (1/3 oct)", "61 (1/6 oct)")),
            "squareCells": (True, _B),  # segment count follows column width so cells stay 1:1
            "segments": (24.0, _n(4, 60, 1)),
            "segGap": (3.0, _n(0, 12, 0.5)),
            "colGapPct": (26.0, _n(0, 70, 1)),
            "segColor": ("#4EA6F7", _C),
            "zoneColors": (False, _B),
            "colWarn": ("#F5C518", _C),
            "colDanger": ("#FF3B30", _C),
            "warnAt": (0.75, _n(0.3, 1.0, 0.01)),
            "dangerAt": (0.92, _n(0.3, 1.0, 0.01)),
            "peakColor": ("#FFFFFF", _C),
            "unlit": (0.14, _n(0, 0.6, 0.01)),
            "showText": (False, _B),
            "labels": ("octaves", _ch("octaves", "all", "none")),
            "showScale": (True, _B),
            "text": ("#8A8A8A", _C),
        },
    },
    "skyline": {
        "label": "Skyline (city windows)",
        "needs": ("spectrum",),
        "params": {
            "bg": ("#000000", _C),
            "building": ("#1A1A1A", _C),
            "backColor": ("#0E0E0E", _C),
            "window": ("#FFC04D", _C),
            "peakColor": ("#FFFFFF", _C),
            "unlit": (0.10, _n(0, 0.6, 0.01)),
            "seed": (7.0, _n(0, 99, 1)),
            "minH": (200.0, _n(60, 500, 2)),
            "maxH": (560.0, _n(200, 700, 2)),
            "windowW": (10.0, _n(4, 30, 1)),
            "windowH": (13.0, _n(4, 30, 1)),
            "peaks": (True, _B),
            "showBack": (True, _B),
            "moon": (True, _B),
            "moonColor": ("#E8E4D8", _C),
            "moonR": (44.0, _n(10, 150, 1)),
            "moonX": (1060.0, _n(60, 1220, 2)),
            "moonY": (150.0, _n(40, 500, 2)),
        },
    },
    "dots": {
        "label": "Dot matrix",
        "needs": ("spectrum",),
        "params": {
            "bg": ("#000000", _C),
            "colA": ("#4EA6F7", _C),
            "colB": ("#FF6A00", _C),
            "peakColor": ("#FFFFFF", _C),
            "unlit": (0.12, _n(0, 0.6, 0.01)),
            "cols": (40.0, _n(8, 96, 1)),
            "rows": (22.0, _n(6, 60, 1)),
            "dotScale": (0.7, _n(0.2, 1.0, 0.01)),
            "shape": ("circle", _ch("circle", "square")),
            "layout": ("up", _ch("up", "mirror")),
            "colorMode": ("solid", _ch("solid", "two-tone", "band hue")),
            "twoToneAt": (0.75, _n(0.3, 0.95, 0.01)),
            "hueStart": (200.0, _n(0, 360, 1)),
            "hueSpan": (240.0, _n(0, 360, 1)),
            "peaks": (True, _B),
            "insetX": (90.0, _n(0, 300, 2)),
            "top": (90.0, _n(0, 380, 2)),
            "bottom": (710.0, _n(420, 800, 2)),
        },
    },
    "bounce": {
        "label": "Bounce (ball per band)",
        "needs": ("spectrum",),
        "params": {
            "bg": ("#000000", _C),
            "colA": ("#4EA6F7", _C),
            "colorMode": ("solid", _ch("solid", "band hue")),
            "hueStart": (200.0, _n(0, 360, 1)),
            "hueSpan": (240.0, _n(0, 360, 1)),
            "shadow": (True, _B),
            "shadowColor": ("#1A1A1A", _C),
            "showFloor": (False, _B),
            "floorColor": ("#1A1A1A", _C),
            "balls": (16.0, _n(3, 48, 1)),
            "ballScale": (0.62, _n(0.2, 1.0, 0.01)),
            "gravity": (2.6, _n(0.5, 10, 0.1)),
            "bounce": (0.35, _n(0, 0.9, 0.01)),
            "sensitivity": (0.03, _n(0, 0.3, 0.01)),
            "insetX": (90.0, _n(0, 300, 2)),
            "top": (110.0, _n(0, 400, 2)),
            "floorY": (690.0, _n(400, 780, 2)),
        },
    },
    "fireflies": {
        "label": "Fireflies (drifting lights)",
        "needs": ("spectrum",),
        "params": {
            "bg": ("#000000", _C),
            "colorMode": ("by band", _ch("by band", "solid")),
            "colLow": ("#FF6A00", _C),
            "colMid": ("#FFC04D", _C),
            "colHigh": ("#4EA6F7", _C),
            "colA": ("#FFC04D", _C),
            "dim": (0.2, _n(0, 0.8, 0.01)),
            "count": (160.0, _n(10, 500, 1)),
            "size": (4.0, _n(1, 20, 0.5)),
            "grow": (7.0, _n(0, 30, 0.5)),
            "drift": (50.0, _n(0, 200, 2)),
            "speed": (0.35, _n(0, 3, 0.05)),
            "seed": (3.0, _n(0, 99, 1)),
        },
    },
}

DEFAULT_PRESETS: list[dict[str, object]] = [
    {"name": "Pixel VU", "style": "pixel_vu"},
    {"name": "Sweep VU", "style": "sweep_vu"},
    {"name": "Spectrum", "style": "bars"},
    {"name": "Meter Bridge", "style": "led_ladder"},
    {"name": "RTA 31", "style": "rta", "fftSize": 8192, "floorDb": -84.0, "ceilDb": -12.0,
     "attackMs": 20.0, "releaseMs": 320.0, "peakHoldMs": 900.0, "peakFall": 0.4,
     "segments": 10.0, "segGap": 10.0, "colGapPct": 7.0, "zoneColors": True, "showScale": False},
    {"name": "Dot Matrix", "style": "dots", "cols": 14.0, "rows": 8.0, "dotScale": 0.99, "shape": "square",
     "colorMode": "band hue"},
    {"name": "Bounce", "style": "bounce"},
    {"name": "Fireflies", "style": "fireflies", "dim": 0.8, "count": 239.0, "size": 20.0, "grow": 30.0,
     "drift": 58.0, "speed": 1.25, "seed": 0.0},
    # Not in the default rotation, still selectable in the lab's tuner: arc_vu (digital VU), skyline.
]


def style_specs(style: str) -> dict[str, tuple[object, tuple]]:
    """``{key: (default, spec)}`` for a style, including shared analysis/level params."""
    st = STYLES.get(style) or STYLES["bars"]
    out: dict[str, tuple[object, tuple]] = dict(st["params"])  # type: ignore[arg-type]
    needs = st["needs"]
    if "spectrum" in needs:  # type: ignore[operator]
        out.update(ANALYSIS_PARAMS)
    if "vu" in needs or "ppm" in needs:  # type: ignore[operator]
        out.update(LEVEL_PARAMS)
    return out


# Defaults that changed, by (style, key): the old value. The lab saves every key,
# so a saved preset still holding an old default picks up the new one; a value
# someone actually tuned is kept.
RETIRED_DEFAULTS: dict[tuple[str, str], object] = {
    ("sweep_vu", "track"): "#1A1A1A",
    ("bars", "showSlots"): True,
}


def complete_preset(raw: dict[str, object]) -> dict[str, object]:
    """``raw`` over its style's defaults (unknown style → bars); keys the style doesn't use are dropped."""
    style = str(raw.get("style", "bars"))
    if style not in STYLES:
        style = "bars"
    specs = style_specs(style)
    p: dict[str, object] = {k: v[0] for k, v in specs.items()}
    p.update({
        k: v for k, v in raw.items()
        if (k in specs or k == "name")
        and not (
            (style, k) in RETIRED_DEFAULTS
            and str(v).strip().lower() == str(RETIRED_DEFAULTS[(style, k)]).lower()
        )
    })
    p["style"] = style
    p.setdefault("name", STYLES[style]["label"])
    return p


def default_presets() -> list[dict[str, object]]:
    return [complete_preset(dict(p)) for p in DEFAULT_PRESETS]


# ---------------------------------------------------------------------------
# Config (hot-reloaded)
# ---------------------------------------------------------------------------
_cfg_lock = threading.Lock()
_cfg: tuple[list[dict[str, object]], int] = (default_presets(), 0)
_cfg_mtime: int | None = None
_cfg_checked = 0.0
_override: list[dict[str, object]] | None = None


def config_path() -> Path:
    return pigeon_state_dir() / CONFIG_NAME


def _read_config() -> tuple[list[dict[str, object]], int]:
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_presets(), 0
    except (OSError, ValueError) as exc:
        print(f"pigeon: fullscreen_viz: bad {CONFIG_NAME}: {exc}", file=sys.stderr)
        return default_presets(), 0
    items = raw.get("presets") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not items:
        return default_presets(), 0
    # Presets of a retired style (e.g. the old scope) are dropped.
    presets = [complete_preset(dict(p)) for p in items if isinstance(p, dict) and p.get("style") in STYLES]
    if not presets:
        return default_presets(), 0
    try:
        active = int(raw.get("active", 0)) % len(presets)
    except (TypeError, ValueError):
        active = 0
    return presets, active


def load_config() -> tuple[list[dict[str, object]], int]:
    """``(presets, active index)``; re-reads the file at most twice a second."""
    global _cfg, _cfg_mtime, _cfg_checked
    now = time.monotonic()
    if now - _cfg_checked < _CONFIG_POLL_S:
        return _cfg
    with _cfg_lock:
        _cfg_checked = now
        try:
            mtime: int | None = config_path().stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime != _cfg_mtime:
            _cfg_mtime = mtime
            _cfg = _read_config()
    return _cfg


def presets() -> list[dict[str, object]]:
    return _override if _override is not None else load_config()[0]


def set_presets(items: list[dict[str, object]] | None) -> None:
    """Use an in-memory preset list instead of the file (``None`` returns to the file)."""
    global _override
    _override = items


def save_config(items: list[dict[str, object]], active: int = 0) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"active": int(active), "presets": [complete_preset(dict(p)) for p in items]}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    global _cfg_checked
    _cfg_checked = 0.0
    return path


def _f(p: dict[str, object], key: str, default: float = 0.0) -> float:
    try:
        return float(p.get(key, default))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float(default)


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
@lru_cache(maxsize=256)
def _bgr(h: object, fallback: str = "#FFFFFF") -> tuple[int, int, int]:
    s = str(h or fallback).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        v = int(s[:6], 16)
    except ValueError:
        v = int(fallback.lstrip("#"), 16)
    return (v & 255, (v >> 8) & 255, (v >> 16) & 255)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Flat color ``t`` of the way from ``a`` to ``b``."""
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))  # type: ignore[return-value]


def _hsl_bgr(hue: float, s: float = 0.85, lum: float = 0.6) -> tuple[int, int, int]:
    c = (1 - abs(2 * lum - 1)) * s
    hp = (hue % 360.0) / 60.0
    x = c * (1 - abs(hp % 2 - 1))
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(hp) % 6]
    m = lum - c / 2
    return (int((b + m) * 255), int((g + m) * 255), int((r + m) * 255))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
class Analysis:
    """Everything the styles read, updated once per frame from the PCM ring."""

    def __init__(self) -> None:
        self.level = {k: np.zeros(GRID, np.float32) for k in "MLR"}
        self.peak = {k: np.zeros(GRID, np.float32) for k in "MLR"}
        self._age = {k: np.zeros(GRID, np.float32) for k in "MLR"}
        self._grid_key: tuple | None = None
        self._grid: tuple[np.ndarray, ...] = ()
        self._win_n = 0
        self._win = np.zeros(0, np.float32)
        # Levels, per channel [L, R].
        self.vu = np.zeros(2)  # needle position, linear volts re 0 VU
        self._vu_v = np.zeros(2)
        self.ppm = np.full(2, -120.0)  # dBFS
        self.hold = np.full(2, -120.0)
        self._hold_age = np.zeros(2)
        self.rms = np.full(2, -120.0)  # dBFS, 300 ms smoothed
        self.max_peak = np.full(2, -120.0)  # since reset_max()
        self.clip_age = np.full(2, 99.0)  # s since the last full-scale sample
        self.led_age = np.full(2, 99.0)  # s since peakLedDbfs was crossed
        self.dt = 1.0 / 30.0
        self.state: dict[str, dict] = {}  # per-style animation state (e.g. ripple rings)

    def reset_max(self) -> None:
        self.max_peak[:] = -120.0

    # -- spectrum ---------------------------------------------------------
    def _grid_for(self, p: dict, n_fft: int, sr: float) -> tuple[np.ndarray, ...]:
        f_min = max(10.0, _f(p, "fMin", 30.0))
        f_max = max(f_min + 10.0, min(_f(p, "fMax", 16000.0), sr * 0.5 - 1.0))
        key = (f_min, f_max, n_fft, sr)
        if key != self._grid_key:
            edges = np.exp(np.linspace(math.log(f_min), math.log(f_max), GRID + 1))
            bin_hz = sr / n_fft
            lo, hi = edges[:-1], edges[1:]
            b0 = np.clip(np.floor(lo / bin_hz).astype(np.int64), 0, n_fft // 2)
            narrow = (hi - lo) / bin_hz < 1.0
            fc = np.sqrt(lo * hi)
            self._grid = (fc / bin_hz, narrow | (np.diff(np.append(b0, n_fft // 2 + 1)) <= 1), b0,
                          np.log2(fc / 1000.0).astype(np.float32))
            self._grid_key = key
        return self._grid

    def _spectrum(self, p: dict, frames: np.ndarray, sr: float, names: tuple[str, ...], dt: float) -> None:
        n_fft = int(frames.shape[0])
        if self._win_n != n_fft:
            self._win = np.blackman(n_fft).astype(np.float32)
            self._win_n = n_fft
        pos, narrow, b0, tilt_oct = self._grid_for(p, n_fft, sr)
        floor, ceil = _f(p, "floorDb", -80), _f(p, "ceilDb", -15)
        a_ms, r_ms = _f(p, "attackMs", 25), _f(p, "releaseMs", 250)
        k_a = 1.0 - math.exp(-dt * 1000.0 / a_ms) if a_ms > 0 else 1.0
        k_r = 1.0 - math.exp(-dt * 1000.0 / r_ms) if r_ms > 0 else 1.0
        hold_ms, fall = _f(p, "peakHoldMs", 500), _f(p, "peakFall", 0.6)
        gain = _f(p, "tilt", 3.0) * tilt_oct
        for name in names:
            x = frames.mean(axis=1) if name == "M" else frames[:, 0 if name == "L" else 1]
            mag = np.abs(np.fft.rfft(x * self._win)) * (4.0 / n_fft)  # full-scale sine ≈ 0 dB
            db = 20.0 * np.log10(mag + 1e-12)
            cell = np.where(narrow, np.interp(pos, np.arange(db.size), db), np.maximum.reduceat(db, b0))
            v = np.clip((cell + gain - floor) / max(1.0, ceil - floor), 0.0, 1.0).astype(np.float32)
            lvl, pk, age = self.level[name], self.peak[name], self._age[name]
            lvl += (v - lvl) * np.where(v > lvl, k_a, k_r).astype(np.float32)
            up = lvl >= pk
            pk[up] = lvl[up]
            age[up] = 0.0
            age[~up] += dt * 1000.0
            falling = (~up) & (age > hold_ms)
            pk[falling] = np.maximum(lvl[falling], pk[falling] - fall * dt)

    def bands(self, name: str, n: int, which: str = "level") -> np.ndarray:
        """``n`` equal slices of the (log-spaced) grid, max-aggregated."""
        arr = (self.level if which == "level" else self.peak)[name]
        n = max(1, min(GRID, int(n)))
        idx = np.floor(np.linspace(0, GRID, n + 1)[:-1]).astype(np.intp)
        return np.maximum.reduceat(arr, idx)

    # -- levels -----------------------------------------------------------
    def _levels(self, p: dict, blk: np.ndarray, dt: float, needs: tuple[str, ...]) -> None:
        pk = np.abs(blk).max(axis=0) if blk.size else np.zeros(2)
        ms = (blk * blk).mean(axis=0) if blk.size else np.zeros(2)
        pk_db = 20.0 * np.log10(pk + 1e-9)
        rms_db = 10.0 * np.log10(ms + 1e-12)
        fall = _f(p, "fallDbS", 20.0) * dt
        self.ppm = np.maximum(pk_db, self.ppm - fall)
        up = self.ppm >= self.hold
        self.hold[up] = self.ppm[up]
        self._hold_age[up] = 0.0
        self._hold_age[~up] += dt
        dropping = (~up) & (self._hold_age * 1000.0 > _f(p, "holdMs", 1500))
        self.hold[dropping] = np.maximum(self.ppm[dropping], self.hold[dropping] - fall)
        self.max_peak = np.maximum(self.max_peak, pk_db)
        self.clip_age = np.where(pk >= 0.999, 0.0, self.clip_age + dt)
        self.led_age = np.where(pk_db >= _f(p, "peakLedDbfs", -3.0), 0.0, self.led_age + dt)
        self.rms += (rms_db - self.rms) * (1.0 - math.exp(-dt / 0.3))
        if "vu" not in needs:
            return
        # VU needle: 2nd-order movement driven by RMS re refDbfs (1.0 = 0 VU).
        target = np.minimum(10.0 ** ((rms_db - _f(p, "refDbfs", -18.0)) / 20.0), 1.6)
        zeta = max(0.05, _f(p, "damping", 0.8))
        wn = 4.6 / (zeta * max(0.02, _f(p, "riseMs", 300.0) / 1000.0))
        steps = max(1, int(math.ceil(dt / 0.004)))
        h = dt / steps
        x, v = self.vu, self._vu_v
        for _ in range(steps):
            v += (wn * wn * (target - x) - 2.0 * zeta * wn * v) * h
            x += v * h
        pinned = (x < -0.02) | (x > 1.62)
        x[:] = np.clip(x, -0.02, 1.62)
        v[pinned] = 0.0

    def update(self, p: dict, dt: float, needs: tuple[str, ...], names: tuple[str, ...] = ("M",)) -> None:
        sr = _audio.sample_rate()
        fresh = _audio.audio_fresh()
        n_blk = int(min(8192, max(256, dt * sr)))
        n_fft = 0
        if "spectrum" in needs:
            n_fft = int(2 ** round(math.log2(max(1024, min(16384, _f(p, "fftSize", 4096))))))
        self.dt = dt
        n = max(n_blk, n_fft)
        frames = _audio.latest_samples(n) if fresh else np.zeros((n, 2), np.float32)
        self._levels(p, frames[-n_blk:], dt, needs)
        if n_fft:
            self._spectrum(p, frames[-n_fft:], sr, names, dt)


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
class Xf:
    """Design (1280×800) → pixel mapping, uniform scale, centered."""

    def __init__(self, w: int, h: int) -> None:
        self.w, self.h = int(w), int(h)
        self.s = min(w / DESIGN_W, h / DESIGN_H)
        self.ox = (w - DESIGN_W * self.s) / 2.0
        self.oy = (h - DESIGN_H * self.s) / 2.0

    def x(self, v: float) -> float:
        return self.ox + v * self.s

    def y(self, v: float) -> float:
        return self.oy + v * self.s

    def l(self, v: float) -> float:
        return v * self.s

    def p(self, x: float, y: float) -> tuple[int, int]:
        """Fixed-point point for cv2 ``shift=SHIFT`` (pixel centers at .5)."""
        return (int(round((self.x(x) - 0.5) * _ONE)), int(round((self.y(y) - 0.5) * _ONE)))

    def px(self, x: float, y: float) -> tuple[int, int]:
        return (int(round(self.x(x))), int(round(self.y(y))))

    def th(self, v: float) -> int:
        return max(1, int(round(self.l(v))))


@lru_cache(maxsize=512)
def _cap(w: int, r: int) -> np.ndarray:
    """Coverage ``(r, w, 1)`` of the top ``r`` rows of a ``w``-wide rect with corner radius ``r``."""
    k = 4
    m = np.zeros((2 * r * k + 2, w * k), np.uint8)
    _rrect(m, 0, 0, w * k, 2 * r * k + 2, r * k, 255)
    return (cv2.resize(m[: r * k], (w, r), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0)[:, :, None]


def _blend_cap(img: np.ndarray, x0: int, y0: int, cap: np.ndarray, color: tuple) -> None:
    h, w = cap.shape[:2]
    H, W = img.shape[:2]
    cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    a = cap[cy0 - y0 : cy1 - y0, cx0 - x0 : cx1 - x0]
    sub = img[cy0:cy1, cx0:cx1]
    sub[:] = (sub * (1.0 - a) + np.asarray(color, np.float32) * a).astype(np.uint8)


def _rrect(img: np.ndarray, x0: int, y0: int, x1: int, y1: int, r: int, color: tuple, aa: bool = False) -> None:
    """Filled rounded rect covering pixels ``[x0, x1) × [y0, y1)``.

    ``aa`` blends cached coverage masks for the rounded ends (per-frame use at
    1×); without it corners are hard-edged circles (static layers drawn at 2×).
    """
    if x1 <= x0 or y1 <= y0:
        return
    r = max(0, min(int(r), (x1 - x0) // 2, (y1 - y0) // 2))
    if r < 1:
        img[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = color
        return
    img[max(0, y0 + r):max(0, y1 - r), max(0, x0):max(0, x1)] = color
    if aa:
        cap = _cap(x1 - x0, r)
        _blend_cap(img, x0, y0, cap, color)
        _blend_cap(img, x0, y1 - r, cap[::-1], color)
        return
    img[max(0, y0):max(0, y0 + r), max(0, x0 + r):max(0, x1 - r)] = color
    img[max(0, y1 - r):max(0, y1), max(0, x0 + r):max(0, x1 - r)] = color
    rr = int(round(r * _ONE))
    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
        c = (int(round((cx - 0.5) * _ONE)), int(round((cy - 0.5) * _ONE)))
        cv2.circle(img, c, rr, color, -1, cv2.LINE_8, SHIFT)


class Canvas:
    """A static layer drawn at ``SS``× with cv2 shapes then PIL text."""

    def __init__(self, w: int, h: int, bg: tuple[int, int, int]) -> None:
        self.w, self.h = w, h
        self.img = np.empty((h * SS, w * SS, 3), np.uint8)
        self.img[:] = bg
        self.xf = Xf(w * SS, h * SS)
        self._texts: list[tuple] = []

    def rrect(self, x0: float, y0: float, x1: float, y1: float, r: float, color: tuple) -> None:
        xf = self.xf
        _rrect(self.img, int(round(xf.x(x0))), int(round(xf.y(y0))), int(round(xf.x(x1))),
               int(round(xf.y(y1))), int(round(xf.l(r))), color)

    def line(self, x0: float, y0: float, x1: float, y1: float, color: tuple, w: float) -> None:
        cv2.line(self.img, self.xf.p(x0, y0), self.xf.p(x1, y1), color, self.xf.th(w), cv2.LINE_AA, SHIFT)

    def arc(self, cx: float, cy: float, r: float, a0: float, a1: float, color: tuple, w: float) -> None:
        """Arc between cv2 angles ``a0..a1`` (deg, 0 = +x, clockwise), stroke width ``w``."""
        xf = self.xf
        rr = int(round(xf.l(r) * _ONE))
        cv2.ellipse(self.img, xf.p(cx, cy), (rr, rr), 0.0, a0, a1, color, xf.th(w), cv2.LINE_AA, SHIFT)

    def circle(self, cx: float, cy: float, r: float, color: tuple, w: int = -1) -> None:
        cv2.circle(self.img, self.xf.p(cx, cy), int(round(self.xf.l(r) * _ONE)), color,
                   w if w < 0 else self.xf.th(w), cv2.LINE_AA, SHIFT)

    def text(self, s: str, x: float, y: float, size: float, color: tuple, font: str = "medium",
             anchor: str = "mm") -> None:
        self._texts.append((s, x, y, size, color, font, anchor))

    def finish(self) -> np.ndarray:
        if self._texts:
            pil = Image.fromarray(self.img[:, :, ::-1])
            d = ImageDraw.Draw(pil)
            for s, x, y, size, color, font, anchor in self._texts:
                f = load_font(_font_path(font), max(6, int(round(self.xf.l(size)))))
                d.text((self.xf.x(x), self.xf.y(y)), s, fill=color[::-1], font=f, anchor=anchor)
            self.img = np.asarray(pil)[:, :, ::-1]
        return cv2.resize(self.img, (self.w, self.h), interpolation=cv2.INTER_AREA)


@lru_cache(maxsize=8)
def _font_path(kind: str) -> str | None:
    if kind == "digital":
        return resolve_digital7_font()
    if kind == "bold":
        return resolve_ui_font_bold()
    return resolve_ui_font_medium()


@lru_cache(maxsize=512)
def text_patch(s: str, px: int, fg: tuple, bg: tuple, font: str = "medium") -> np.ndarray:
    """Pre-composited ``(h, w, 3)`` text on a flat ``bg`` (for per-frame readouts)."""
    f = load_font(_font_path(font), max(6, int(px)))
    l, t, r, b = f.getbbox(s or " ")
    pil = Image.new("RGB", (max(1, r - l + 2), max(1, b - t + 2)), tuple(bg[::-1]))
    ImageDraw.Draw(pil).text((1 - l, 1 - t), s, fill=tuple(fg[::-1]), font=f)
    return np.ascontiguousarray(np.asarray(pil)[:, :, ::-1])


def _blit(img: np.ndarray, patch: np.ndarray, x: int, y: int) -> None:
    h, w = patch.shape[:2]
    H, W = img.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 > x0 and y1 > y0:
        img[y0:y1, x0:x1] = patch[y0 - y : y1 - y, x0 - x : x1 - x]


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
class Style:
    needs: tuple[str, ...] = ()

    def analysis_params(self, p: dict) -> dict:
        return p

    def channels(self, p: dict) -> tuple[str, ...]:
        """Spectra this preset reads: ``("M",)`` or ``("L", "R")``."""
        return ("M",)

    def layers(self, p: dict, w: int, h: int) -> dict[str, object]:
        raise NotImplementedError

    def draw(self, img: np.ndarray, xf: Xf, p: dict, a: Analysis, L: dict[str, object]) -> None:
        raise NotImplementedError


# -- VU pair geometry (the retired analog style; the digital and pixel VUs build on it) ----
_VU_MAJOR = (-20, -10, -7, -5, -3, -2, -1, 0, 1, 2, 3)
_VU_MINOR = (-15, -6, -4, -0.5, 0.5, 1.5, 2.5)
_VU_PCT = (20, 40, 60, 80, 100)


class AnalogVU(Style):
    needs = ("vu", "ppm")

    @staticmethod
    def _geo(p: dict) -> dict[str, float]:
        W, H = _f(p, "meterW", 580), _f(p, "meterH", 420)
        gap = max(24.0, (DESIGN_W - 2 * W) / 3.0)
        R = W * 0.55
        # Pivot sits in the bottom cover so only the needle's upper part shows.
        return {"W": W, "H": H, "gap": gap, "x0": (DESIGN_W - 2 * W - gap) / 2.0,
                "y0": (DESIGN_H - H) / 2.0, "R": R, "piv": R + H * 0.226, "cover": H * 0.26}

    @staticmethod
    def _theta(p: dict, pos: float) -> float:
        sw = _f(p, "sweepDeg", 90)
        return -sw / 2.0 + pos * sw

    def layers(self, p: dict, w: int, h: int) -> dict[str, object]:
        g = self._geo(p)
        cv = Canvas(w, h, _bgr(p["bg"]))
        face, ink, red = _bgr(p["face"]), _bgr(p["ink"]), _bgr(p["red"])
        text = bool(p.get("showText"))
        W, H, R = g["W"], g["H"], g["R"]
        for m in range(2):
            ox, oy = g["x0"] + m * (W + g["gap"]), g["y0"]
            cx, cy = ox + W / 2.0, oy + g["piv"]
            cv.rrect(ox, oy, ox + W, oy + H, _f(p, "faceRadius", 24), face)

            def ang(pos: float) -> float:
                return -90.0 + self._theta(p, pos)

            def at(pos: float, r: float) -> tuple[float, float]:
                a = math.radians(self._theta(p, pos))
                return cx + r * math.sin(a), cy - r * math.cos(a)

            vpos = lambda db: (10.0 ** (db / 20.0)) / 1.4125  # noqa: E731
            cv.arc(cx, cy, R, ang(vpos(-20)), ang(vpos(0)), ink, 3)
            cv.arc(cx, cy, R + 5, ang(vpos(0)), ang(1.0), red, 12)
            for db in _VU_MAJOR:
                col = red if db > 0 else ink
                (x0, y0), (x1, y1) = at(vpos(db), R), at(vpos(db), R + 24)
                cv.line(x0, y0, x1, y1, col, 3)
                lx, ly = at(vpos(db), R + 46)
                if text:
                    cv.text(f"+{db}" if db > 0 else str(db), lx, ly, 24 if abs(db) != 20 else 22, col)
            for db in _VU_MINOR:
                col = red if db > 0 else ink
                (x0, y0), (x1, y1) = at(vpos(db), R), at(vpos(db), R + 13)
                cv.line(x0, y0, x1, y1, col, 2)
            if p.get("showPercent", True):
                for pct in _VU_PCT:
                    pos = pct / 141.25
                    (x0, y0), (x1, y1) = at(pos, R - 3), at(pos, R - 13)
                    cv.line(x0, y0, x1, y1, ink, 2)
                    lx, ly = at(pos, R - 32)
                    if text:
                        cv.text(str(pct), lx, ly, 15, ink)
            if text:
                cv.text(str(p.get("label", "VU")), cx, oy + H - g["cover"] - 58, 46, ink, "bold")
            # Bottom cover the needle rises from behind (flat band, square top).
            r = _f(p, "faceRadius", 24)
            cv.rrect(ox, oy + H - g["cover"], ox + W, oy + H, r, _bgr(p["cover"]))
            cv.rrect(ox, oy + H - g["cover"], ox + W, oy + H - g["cover"] + r + 1, 0, _bgr(p["cover"]))
            if text:
                cv.text("L" if m == 0 else "R", cx, oy + H - g["cover"] / 2.0, 30, _bgr(p["coverText"]), "bold")
            if p.get("peakLed", True):
                cv.circle(ox + W - 40, oy + 40, 11, _mix(face, ink, 0.18))
                if text:
                    cv.text("PEAK", ox + W - 40, oy + 68, 13, ink)
        return {"base": cv.finish(), "geo": g}

    def draw(self, img: np.ndarray, xf: Xf, p: dict, a: Analysis, L: dict[str, object]) -> None:
        g = L["geo"]  # type: ignore[assignment]
        W, H, R = g["W"], g["H"], g["R"]
        col = _bgr(p["needle"])
        lim = _f(p, "sweepDeg", 90) / 2.0 + 4.0
        for m in range(2):
            ox, oy = g["x0"] + m * (W + g["gap"]), g["y0"]
            cx, cy = ox + W / 2.0, oy + g["piv"]
            th = math.radians(max(-lim, min(lim, self._theta(p, float(a.vu[m]) / 1.4125))))
            sx, cz = math.sin(th), math.cos(th)
            y_cov = oy + H - g["cover"]
            t0 = (cy - y_cov) / max(0.2, cz)
            t1 = R + 16
            cv2.line(img, xf.p(cx + sx * t0, cy - cz * t0), xf.p(cx + sx * t1, cy - cz * t1), col,
                     xf.th(_f(p, "needleW", 3)), cv2.LINE_AA, SHIFT)
            if p.get("peakLed", True) and a.led_age[m] < 0.15:
                cv2.circle(img, xf.p(ox + W - 40, oy + 40), int(round(xf.l(11) * _ONE)),
                           _bgr(p["peakLedColor"]), -1, cv2.LINE_AA, SHIFT)


# -- 1b. digital VU pair: LED wedges on the analog face ----------------------------
class ArcVU(AnalogVU):
    """The analog VU pair's face and ballistics, with lit LED wedges in place of the needle."""

    @staticmethod
    def _segs(p: dict, g: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
        """``(quads, pos)``: wedge corners relative to the pivot (design units), and each wedge's scale position."""
        n = max(4, int(_f(p, "segments", 36)))
        sw = math.radians(_f(p, "sweepDeg", 90))
        half = sw / n / 2.0 * (1.0 - _f(p, "segGapPct", 35) / 100.0)
        r_out = g["R"] + 6.0
        r_in = r_out - _f(p, "segLen", 38)
        pos = (np.arange(n) + 0.5) / n
        th = -sw / 2.0 + pos * sw
        quads = np.empty((n, 4, 2))
        for j, (d, r) in enumerate(((-half, r_in), (half, r_in), (half, r_out), (-half, r_out))):
            quads[:, j, 0] = r * np.sin(th + d)
            quads[:, j, 1] = -r * np.cos(th + d)
        return quads, pos

    @staticmethod
    def _polys(xf: Xf, cx: float, cy: float, q: np.ndarray) -> list[np.ndarray]:
        pts = np.empty_like(q)
        pts[..., 0] = (xf.ox + (cx + q[..., 0]) * xf.s - 0.5) * _ONE
        pts[..., 1] = (xf.oy + (cy + q[..., 1]) * xf.s - 0.5) * _ONE
        return list(pts.astype(np.int32))

    def layers(self, p: dict, w: int, h: int) -> dict[str, object]:
        g = self._geo(p)
        cv = Canvas(w, h, _bgr(p["bg"]))
        face, ink, red_c, seg_c = _bgr(p["face"]), _bgr(p["ink"]), _bgr(p["red"]), _bgr(p["segColor"])
        text = bool(p.get("showText"))
        quads, pos = self._segs(p, g)
        red = pos >= 1.0 / 1.4125  # 0 VU and up
        unlit = _f(p, "unlit", 0.12)
        W, H, R = g["W"], g["H"], g["R"]
        vpos = lambda db: (10.0 ** (db / 20.0)) / 1.4125  # noqa: E731
        for m in range(2):
            ox, oy = g["x0"] + m * (W + g["gap"]), g["y0"]
            cx, cy = ox + W / 2.0, oy + g["piv"]
            cv.rrect(ox, oy, ox + W, oy + H, _f(p, "faceRadius", 24), face)
            for k, poly in enumerate(self._polys(cv.xf, cx, cy, quads)):
                cv2.fillPoly(cv.img, [poly], _mix(face, red_c if red[k] else seg_c, unlit), cv2.LINE_AA, SHIFT)

            def at(pos_: float, r: float) -> tuple[float, float]:
                a = math.radians(self._theta(p, pos_))
                return cx + r * math.sin(a), cy - r * math.cos(a)

            for db in _VU_MAJOR:
                col = red_c if db > 0 else ink
                (x0, y0), (x1, y1) = at(vpos(db), R + 16), at(vpos(db), R + 32)
                cv.line(x0, y0, x1, y1, col, 3)
                if text:
                    lx, ly = at(vpos(db), R + 54)
                    cv.text(f"+{db}" if db > 0 else str(db), lx, ly, 24 if abs(db) != 20 else 22, col)
            if text:
                cv.text(str(p.get("label", "VU")), cx, oy + H - g["cover"] - 58, 46, ink, "bold")
            r = _f(p, "faceRadius", 24)
            cv.rrect(ox, oy + H - g["cover"], ox + W, oy + H, r, _bgr(p["cover"]))
            cv.rrect(ox, oy + H - g["cover"], ox + W, oy + H - g["cover"] + r + 1, 0, _bgr(p["cover"]))
            if text:
                cv.text("L" if m == 0 else "R", cx, oy + H - g["cover"] / 2.0, 30, _bgr(p["coverText"]), "bold")
            if p.get("peakLed", True):
                cv.circle(ox + W - 40, oy + 40, 11, _mix(face, ink, 0.18))
                if text:
                    cv.text("PEAK", ox + W - 40, oy + 68, 13, ink)
        return {"base": cv.finish(), "geo": g, "quads": quads, "pos": pos, "red": red}

    def draw(self, img: np.ndarray, xf: Xf, p: dict, a: Analysis, L: dict[str, object]) -> None:
        g = L["geo"]  # type: ignore[assignment]
        quads, pos, red = L["quads"], L["pos"], L["red"]  # type: ignore[assignment]
        st = a.state.setdefault("arc_vu", {"hold": [0.0, 0.0], "age": [0.0, 0.0]})
        seg_c, red_c = _bgr(p["segColor"]), _bgr(p["red"])
        W = g["W"]
        for m in range(2):
            ox, oy = g["x0"] + m * (W + g["gap"]), g["y0"]
            cx, cy = ox + W / 2.0, oy + g["piv"]
            v = float(a.vu[m]) / 1.4125
            if v >= st["hold"][m]:
                st["hold"][m], st["age"][m] = v, 0.0
            else:
                st["age"][m] += a.dt
                if st["age"][m] * 1000.0 > _f(p, "holdMs", 1500):
                    st["hold"][m] = max(v, st["hold"][m] - 0.5 * a.dt)
            k = int(np.searchsorted(pos, v, side="right"))  # wedges whose centre the level has reached
            idx = list(range(k))
            kh = int(np.searchsorted(pos, st["hold"][m], side="right"))
            if p.get("peakHold", True) and kh > k:
                idx.append(kh - 1)
            if idx:
                polys = self._polys(xf, cx, cy, quads[idx])
                for col, want in ((seg_c, False), (red_c, True)):
                    sel = [polys[j] for j, i in enumerate(idx) if bool(red[i]) == want]
                    if sel:
                        cv2.fillPoly(img, sel, col, cv2.LINE_AA, SHIFT)
            if p.get("peakLed", True) and a.led_age[m] < 0.15:
                _disc(img, xf, ox + W - 40, oy + 40, 11, _bgr(p["peakLedColor"]))


# -- 1c. pixel VU: the analog pair as lo-fi pixel art ------------------------------
_PIX_FONT = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
    "-": ("000", "000", "111", "000", "000"), "+": ("000", "010", "111", "010", "000"),
    "V": ("101", "101", "101", "101", "010"), "U": ("101", "101", "101", "101", "111"),
    "L": ("100", "100", "100", "100", "111"), "R": ("110", "101", "110", "101", "101"),
}


def _pix_text(img: np.ndarray, s: str, cx: float, cy: float, color: tuple) -> None:
    """3×5 pixel font, centred on ``(cx, cy)`` in grid pixels."""
    w = 4 * len(s) - 1
    x0, y0 = int(round(cx - w / 2.0)), int(round(cy - 2.5))
    H, W = img.shape[:2]
    for n, ch in enumerate(s):
        for r, row in enumerate(_PIX_FONT.get(ch, ("000",) * 5)):
            for c, bit in enumerate(row):
                x, y = x0 + 4 * n + c, y0 + r
                if bit == "1" and 0 <= x < W and 0 <= y < H:
                    img[y, x] = color


class PixelVU(AnalogVU):
    """The analog pair drawn on a coarse pixel grid (needle and all), then scaled up with hard edges."""

    PALETTES = {  # bg, face, ink, red, cover
        "cream": ("#000000", "#EDE6D3", "#1A1A1A", "#D9412B", "#1A1A1A"),
        "gameboy": ("#0F380F", "#9BBC0F", "#0F380F", "#306230", "#306230"),
        "amber": ("#000000", "#1A1200", "#FFB000", "#FF3B30", "#0D0900"),
        "night": ("#000000", "#101820", "#4EA6F7", "#FF6A00", "#0A0F14"),
    }

    def _cols(self, p: dict) -> tuple[tuple[int, int, int], ...]:
        pal = self.PALETTES.get(str(p.get("palette")))
        if pal:
            if MATTE_BG_KEY in p:  # matte pass: the palette's page goes clear too
                pal = (str(p[MATTE_BG_KEY]),) + tuple(pal[1:])
            return tuple(_bgr(c) for c in pal)
        return tuple(_bgr(p[k]) for k in ("bg", "face", "ink", "red", "cover"))

    @staticmethod
    def _pix(p: dict) -> float:
        return max(2.0, _f(p, "pixel", 8))

    def _meter(self, p: dict, g: dict, m: int) -> tuple[float, ...]:
        """Grid-space ``(left, top, width, height, pivot x, pivot y, radius, cover height)``."""
        k = 1.0 / self._pix(p)
        ox, oy = (g["x0"] + m * (g["W"] + g["gap"])) * k, g["y0"] * k
        return (ox, oy, g["W"] * k, g["H"] * k, ox + g["W"] * k / 2.0, oy + g["piv"] * k, g["R"] * k,
                g["cover"] * k)

    def layers(self, p: dict, w: int, h: int) -> dict[str, object]:
        g = self._geo(p)
        pix = self._pix(p)
        gw, gh = int(round(DESIGN_W / pix)), int(round(DESIGN_H / pix))
        bg, face, ink, red, cover = self._cols(p)
        lo = np.empty((gh, gw, 3), np.uint8)
        lo[:] = bg
        text = bool(p.get("showText"))
        vpos = lambda db: (10.0 ** (db / 20.0)) / 1.4125  # noqa: E731
        for m in range(2):
            ox, oy, W, H, cx, cy, R, cov = self._meter(p, g, m)
            x0, y0, x1, y1 = int(round(ox)), int(round(oy)), int(round(ox + W)), int(round(oy + H))
            lo[y0:y1, x0:x1] = face
            lo[int(round(oy + H - cov)):y1, x0:x1] = cover
            for yy, xx in ((y0, x0), (y0, x1 - 1), (y1 - 1, x0), (y1 - 1, x1 - 1)):  # notched corners
                lo[yy, xx] = bg
            c = (int(round(cx)), int(round(cy)))

            def ang(pos: float) -> float:
                return -90.0 + self._theta(p, pos)

            def at(pos: float, r: float) -> tuple[int, int]:
                a = math.radians(self._theta(p, pos))
                return int(round(cx + r * math.sin(a))), int(round(cy - r * math.cos(a)))

            rr = int(round(R))
            cv2.ellipse(lo, c, (rr, rr), 0, ang(vpos(-20)), ang(vpos(0)), ink, 1, cv2.LINE_8)
            cv2.ellipse(lo, c, (rr + 1, rr + 1), 0, ang(vpos(0)), ang(1.0), red, 2, cv2.LINE_8)
            for db in _VU_MAJOR:
                cv2.line(lo, at(vpos(db), R + 1), at(vpos(db), R + 3), red if db > 0 else ink, 1, cv2.LINE_8)
                if text and db in (-20, -10, -5, -3, 0, 3):
                    lx, ly = at(vpos(db), R + 8)
                    _pix_text(lo, f"+{db}" if db > 0 else str(db), lx, ly, red if db > 0 else ink)
            if text:
                _pix_text(lo, "VU", cx, oy + H - cov - 7, ink)
                _pix_text(lo, "LR"[m], cx, oy + H - cov / 2.0, face)
            if p.get("peakLed", True):
                lx, ly = int(round(ox + W - 5)), int(round(oy + 3))
                lo[ly : ly + 2, lx : lx + 2] = _mix(face, ink, 0.2)
        base = np.empty((h, w, 3), np.uint8)
        base[:] = bg
        return {"base": base, "lo": lo, "geo": g}

    def draw(self, img: np.ndarray, xf: Xf, p: dict, a: Analysis, L: dict[str, object]) -> None:
        lo = L["lo"].copy()  # type: ignore[union-attr]
        g = L["geo"]  # type: ignore[assignment]
        _bg, _face, ink, _red, _cov = self._cols(p)
        lim = _f(p, "sweepDeg", 90) / 2.0 + 4.0
        for m in range(2):
            ox, oy, W, H, cx, cy, R, cov = self._meter(p, g, m)
            th = math.radians(max(-lim, min(lim, self._theta(p, float(a.vu[m]) / 1.4125))))
            sx, cz = math.sin(th), math.cos(th)
            t0 = (cy - (oy + H - cov)) / max(0.2, cz) + 0.5
            t1 = R + 2
            p0 = (int(round(cx + sx * t0)), int(round(cy - cz * t0)))
            p1 = (int(round(cx + sx * t1)), int(round(cy - cz * t1)))
            cv2.line(lo, p0, p1, ink, int(_f(p, "needlePx", 1)), cv2.LINE_8)
            if p.get("peakLed", True) and a.led_age[m] < 0.15:
                lx, ly = int(round(ox + W - 5)), int(round(oy + 3))
                lo[ly : ly + 2, lx : lx + 2] = _bgr(p["peakLedColor"])
        # Scale the grid up with hard pixel edges into the (letterboxed) design area.
        x0, y0 = int(round(xf.ox)), int(round(xf.oy))
        ww, hh = int(round(DESIGN_W * xf.s)), int(round(DESIGN_H * xf.s))
        up = cv2.resize(lo, (ww, hh), interpolation=cv2.INTER_NEAREST)
        H_, W_ = img.shape[:2]
        dst = img[y0 : min(H_, y0 + hh), x0 : min(W_, x0 + ww)]
        src = up[: H_ - y0, : W_ - x0]
        if MATTE_BG_KEY in p:  # no page: leave the background pixels showing through
            keep = np.any(lo != np.array(_bg, np.uint8), axis=2).astype(np.uint8)
            keep = cv2.resize(keep, (ww, hh), interpolation=cv2.INTER_NEAREST)[: H_ - y0, : W_ - x0]
            cv2.copyTo(src, keep, dst)
        else:
            dst[:] = src


# -- 1d. sweep VU: no needle; light travels along an arched track ------------------------
class SweepVU(Style):
    needs = ("vu", "ppm")

    @staticmethod
    def _meters(p: dict) -> list[tuple[float, float, float, float, int]]:
        """``(pivot x, pivot y, radius, band width, channel)``; channel −1 = louder of L/R."""
        R, bw = _f(p, "arcR", 290), _f(p, "bandW", 64)
        if str(p.get("layout")) == "single":
            return [(DESIGN_W / 2.0, 680.0, R * 1.65, bw * 1.5, -1)]
        return [(DESIGN_W * 0.25, 640.0, R, bw, 0), (DESIGN_W * 0.75, 640.0, R, bw, 1)]

    @staticmethod
    def _theta(p: dict, pos: float) -> float:
        sw = _f(p, "sweepDeg", 110)
        return -sw / 2.0 + max(0.0, min(1.0, pos)) * sw

    @staticmethod
    def _arc(img: np.ndarray, xf: Xf, cx: float, cy: float, r: float, t0: float, t1: float, color: tuple,
             w: float) -> None:
        """Arc stroke between needle angles ``t0..t1`` (deg from vertical), round ends."""
        if t1 - t0 < 0.05:
            t1 = t0 + 0.05
        rr = int(round(xf.l(r) * _ONE))
        cv2.ellipse(img, xf.p(cx, cy), (rr, rr), 0.0, -90.0 + t0, -90.0 + t1, color, xf.th(w), cv2.LINE_AA, SHIFT)

    def layers(self, p: dict, w: int, h: int) -> dict[str, object]:
        cv = Canvas(w, h, _bgr(p["bg"]))
        track = _bgr(p["track"])
        red_track = _mix(track, _bgr(p["red"]), _f(p, "redTint", 0.3))
        z = self._theta(p, 1.0 / 1.4125)  # 0 VU
        text, ink = bool(p.get("showText")), _bgr(p["text"])
        vpos = lambda db: (10.0 ** (db / 20.0)) / 1.4125  # noqa: E731
        for cx, cy, R, bw, _chn in self._meters(p):
            self._arc(cv.img, cv.xf, cx, cy, R, self._theta(p, 0.0), self._theta(p, 1.0), track, bw)
            self._arc(cv.img, cv.xf, cx, cy, R, z, self._theta(p, 1.0), red_track, bw)
            if p.get("showTicks", True) or text:
                for db in _VU_MAJOR:
                    a = math.radians(self._theta(p, vpos(db)))
                    r0, r1 = R + bw / 2 + 10, R + bw / 2 + 22
                    if p.get("showTicks", True):
                        cv.line(cx + r0 * math.sin(a), cy - r0 * math.cos(a), cx + r1 * math.sin(a),
                                cy - r1 * math.cos(a), ink, 3)
                    if text:
                        rl = R + bw / 2 + 44
                        cv.text(f"+{db}" if db > 0 else str(db), cx + rl * math.sin(a), cy - rl * math.cos(a), 20, ink)
        return {"base": cv.finish()}

    def draw(self, img: np.ndarray, xf: Xf, p: dict, a: Analysis, L: dict[str, object]) -> None:
        st = a.state.setdefault("sweep_vu", {"hold": [0.0, 0.0, 0.0], "age": [0.0, 0.0, 0.0]})
        mode = str(p.get("mode", "spot"))
        z = self._theta(p, 1.0 / 1.4125)
        lo = self._theta(p, 0.0)
        red, lit, dim = _bgr(p["red"]), _bgr(p["lit"]), _bgr(p["fillColor"])
        inner = _f(p, "inset", 0.72)
        half = _f(p, "spotDeg", 8) / 2.0
        for k, (cx, cy, R, bw, chn) in enumerate(self._meters(p)):
            v = float(a.vu.max() if chn < 0 else a.vu[chn]) / 1.4125
            t = self._theta(p, v)
            if v >= st["hold"][k]:
                st["hold"][k], st["age"][k] = v, 0.0
            else:
                st["age"][k] += a.dt
                if st["age"][k] * 1000.0 > _f(p, "holdMs", 1500):
                    st["hold"][k] = max(v, st["hold"][k] - 0.5 * a.dt)
            wl = bw * inner
            if mode in ("fill", "spot + fill"):
                fill = lit if mode == "fill" else dim
                self._arc(img, xf, cx, cy, R, lo, min(t, z), fill, wl)
                if t > z:
                    self._arc(img, xf, cx, cy, R, z, t, red if mode == "fill" else _mix(dim, red, 0.5), wl)
            if mode in ("spot", "spot + fill"):
                self._arc(img, xf, cx, cy, R, max(lo, t - half), min(self._theta(p, 1.0), t + half),
                          red if t > z else lit, wl)
            if p.get("peakHold", True) and st["hold"][k] > v + 0.02:
                th = self._theta(p, st["hold"][k])
                self._arc(img, xf, cx, cy, R, th - 0.6, th + 0.6, red if th > z else lit, wl)


# -- 2. spectrum bars --------------------------------------------------------
class Bars(Style):
    needs = ("spectrum",)

    def channels(self, p: dict) -> tuple[str, ...]:
        return ("L", "R") if str(p.get("layout")) == "split stereo" else ("M",)

    @staticmethod
    def _slots(p: dict, xf: Xf, n: int, x_l: float, x_r: float) -> list[tuple[int, int]]:
        xl, xr = xf.x(x_l), xf.x(x_r)
        slot = (xr - xl) / n
        gap = max(xf.l(_f(p, "minGapPx", 2)), slot * _f(p, "gapPct", 30) / 100.0)
        out = []
        for i in range(n):
            a = int(round(xl + i * slot + gap / 2.0))
            b = int(round(xl + (i + 1) * slot - gap / 2.0))
            out.append((a, max(a + 1, b)))
        return out

    def _columns(self, p: dict, xf: Xf) -> list[tuple[str, int, list[tuple[int, int]]]]:
        """``(channel, bands, slots)`` per band set; split stereo puts bass in the middle."""
        n = max(1, int(_f(p, "bands", 64)))
        ins = _f(p, "insetX", 56)
        if str(p.get("layout")) == "split stereo":
            half = max(1, n // 2)
            mid = DESIGN_W / 2.0
            gap = 12.0
            left = self._slots(p, xf, half, ins, mid - gap)[::-1]
            right = self._slots(p, xf, half, mid + gap, DESIGN_W - ins)
            return [("L", half, left), ("R", half, right)]
        return [("M", n, self._slots(p, xf, n, ins, DESIGN_W - ins))]

    def layers(self, p: dict, w: int, h: int) -> dict[str, object]:
        base = np.empty((h, w, 3), np.uint8)
        base[:] = _bgr(p["bg"])
        xf = Xf(w, h)
        if p.get("showSlots", True):
            # Drawn at 1× with AA corners so slots line up with the live bars exactly.
            y0, y1 = int(round(xf.y(_f(p, "top", 96)))), int(round(xf.y(_f(p, "bottom", 704))))
            r = int(round(xf.l(_f(p, "radius", 8))))
            for _ch_name, _n_b, slots in self._columns(p, xf):
                for a, b in slots:
                    _rrect(base, a, y0, b, y1, r, _bgr(p["slotColor"]), aa=True)
        return {"base": base}

    def _colors(self, p: dict, ch: str, n: int, lv: np.ndarray) -> list[tuple[int, int, int]]:
        mode = str(p.get("colorMode"))
        a, b = _bgr(p["colA"]), _bgr(p["colB"])
        if mode == "band hue":
            span = _f(p, "hueSpan", 240)
            return [_hsl_bgr(_f(p, "hueStart", 200) + span * i / max(1, n - 1)) for i in range(n)]
        if mode == "channel":
            return [b if ch == "R" else a] * n
        if mode == "two-tone":
            t = _f(p, "twoToneAt", 0.75)
            return [b if v >= t else a for v in lv]
        return [a] * n

    def draw(self, img: np.ndarray, xf: Xf, p: dict, a: Analysis, L: dict[str, object]) -> None:
        top, bot = xf.y(_f(p, "top", 96)), xf.y(_f(p, "bottom", 704))
        H = bot - top
        mirror = str(p.get("layout")) == "mirror"
        r_px = int(round(xf.l(_f(p, "radius", 8))))
        min_lvl = _f(p, "minLevel", 0.02)
        pk_h = max(1, int(round(xf.l(_f(p, "peakH", 6)))))
        pk_col = _bgr(p["peakColor"])
        show_pk = bool(p.get("peaks", True))
        for ch, n, slots in self._columns(p, xf):
            lv = np.maximum(a.bands(ch, n), min_lvl)
            pk = a.bands(ch, n, "peak")
            cols = self._colors(p, ch, n, lv)
            for i, (x0, x1) in enumerate(slots):
                hh = float(lv[i]) * H
                if mirror:
                    y0, y1 = top + (H - hh) / 2.0, top + (H + hh) / 2.0
                else:
                    y0, y1 = bot - hh, bot
                _rrect(img, x0, int(round(y0)), x1, int(round(y1)), r_px, cols[i], aa=True)
                if show_pk:
                    d = float(pk[i]) * H
                    if mirror:
                        for py in (top + (H - d) / 2.0 - pk_h, top + (H + d) / 2.0):
                            _rrect(img, x0, int(round(py)), x1, int(round(py)) + pk_h,
                                   min(r_px, pk_h // 2), pk_col, aa=True)
                    else:
                        py = int(round(max(top, bot - d - pk_h - xf.l(2))))
                        _rrect(img, x0, py, x1, py + pk_h, min(r_px, pk_h // 2), pk_col, aa=True)


# -- LED ladder helpers ---------------------------------------------------------
def _iec_defl(db: float) -> float:
    """IEC 60268-18 style deflection, 0..1 (more resolution near the top)."""
    if db < -70.0:
        return 0.0
    if db < -60.0:
        v = (db + 70.0) * 0.25
    elif db < -50.0:
        v = (db + 60.0) * 0.5 + 2.5
    elif db < -40.0:
        v = (db + 50.0) * 0.75 + 7.5
    elif db < -30.0:
        v = (db + 40.0) * 1.5 + 15.0
    elif db < -20.0:
        v = (db + 30.0) * 2.0 + 30.0
    elif db < 0.0:
        v = (db + 20.0) * 2.5 + 50.0
    else:
        v = 100.0
    return v / 100.0


class _Ladder:
    """Segment geometry for one meter column/row in pixel space."""

    def __init__(self, x0: float, y0: float, x1: float, y1: float, n: int, gap: float, vertical: bool) -> None:
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.n, self.gap, self.vertical = n, gap, vertical
        length = (y1 - y0) if vertical else (x1 - x0)
        self.pitch = (length + gap) / n

    def seg(self, k: int) -> tuple[float, float, float, float]:
        """Segment ``k`` (0 = floor end) as ``(x0, y0, x1, y1)``."""
        if self.vertical:
            b = self.y1 - k * self.pitch
            return self.x0, b - self.pitch + self.gap, self.x1, b
        a = self.x0 + k * self.pitch
        return a, self.y0, a + self.pitch - self.gap, self.y1

    def cut(self, k: int) -> int:
        """Pixel boundary in the gap below segment ``k`` (k = n → past the top)."""
        if self.vertical:
            return int(round(self.y1 - k * self.pitch + self.gap / 2.0))
        return int(round(self.x0 + k * self.pitch - self.gap / 2.0))

    def reveal(self, img: np.ndarray, on: np.ndarray, k0: int, k1: int) -> None:
        """Copy segments ``k0..k1-1`` from the lit layer."""
        k0, k1 = max(0, k0), min(self.n, k1)
        if k1 <= k0:
            return
        if self.vertical:
            r0, r1 = self.cut(k1), self.cut(k0)
            c0, c1 = int(math.floor(self.x0)), int(math.ceil(self.x1))
        else:
            c0, c1 = self.cut(k0), self.cut(k1)
            r0, r1 = int(math.floor(self.y0)), int(math.ceil(self.y1))
        H, W = img.shape[:2]
        r0, r1, c0, c1 = max(0, r0), min(H, r1), max(0, c0), min(W, c1)
        img[r0:r1, c0:c1] = on[r0:r1, c0:c1]


def _paint_ladder(base: Canvas, on: Canvas, lad_ss: _Ladder, colors: list[tuple[int, int, int]],
                  unlit: float, bg: tuple[int, int, int], radius_px: float) -> None:
    for k in range(lad_ss.n):
        x0, y0, x1, y1 = lad_ss.seg(k)
        box = (int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)))
        _rrect(base.img, *box, int(round(radius_px)), _mix(bg, colors[k], unlit))
        _rrect(on.img, *box, int(round(radius_px)), colors[k])


# -- 3. LED meter bridge --------------------------------------------------------
class LedLadder(Style):
    needs = ("ppm",)

    @staticmethod
    def _defl(p: dict, db: float) -> float:
        floor = _f(p, "floorDbfs", -60)
        if str(p.get("scale")) == "IEC":
            return max(0.0, min(1.0, (_iec_defl(db) - _iec_defl(floor)) / (1.0 - _iec_defl(floor))))
        return max(0.0, min(1.0, (db - floor) / -floor))

    def _geo(self, p: dict) -> dict[str, object]:
        vert = str(p.get("orientation")) != "horizontal"
        bw = _f(p, "barW", 130)
        rms = bool(p.get("showRms", True))
        rw = bw * 0.32
        cols: list[tuple[str, int, tuple[float, float, float, float]]] = []
        if vert:
            y0, y1 = 190.0, 720.0
            gap_mid = 200.0
            lx1, rx0 = DESIGN_W / 2 - gap_mid / 2, DESIGN_W / 2 + gap_mid / 2
            cols.append(("peak", 0, (lx1 - bw, y0, lx1, y1)))
            cols.append(("peak", 1, (rx0, y0, rx0 + bw, y1)))
            if rms:
                cols.append(("rms", 0, (lx1 - bw - 24 - rw, y0, lx1 - bw - 24, y1)))
                cols.append(("rms", 1, (rx0 + bw + 24, y0, rx0 + bw + 24 + rw, y1)))
            ro = [(lx1 - bw / 2, 128.0), (rx0 + bw / 2, 128.0)]
        else:
            x0, x1 = (250.0 if p.get("showText") else 80.0), 1200.0
            bw = min(bw, 150.0)
            gap_mid = 90.0
            ty1, by0 = DESIGN_H / 2 - gap_mid / 2, DESIGN_H / 2 + gap_mid / 2
            cols.append(("peak", 0, (x0, ty1 - bw, x1, ty1)))
            cols.append(("peak", 1, (x0, by0, x1, by0 + bw)))
            if rms:
                cols.append(("rms", 0, (x0, ty1 - bw - 18 - rw, x1, ty1 - bw - 18)))
                cols.append(("rms", 1, (x0, by0 + bw + 18, x1, by0 + bw + 18 + rw)))
            ro = [(110.0, ty1 - bw / 2), (110.0, by0 + bw / 2)]
        return {"vert": vert, "cols": cols, "readouts": ro}

    def _seg_colors(self, p: dict, n: int, kind: str) -> list[tuple[int, int, int]]:
        if kind == "rms":
            return [_bgr(p["rmsColor"])] * n
        warn, danger = self._defl(p, _f(p, "warnDb", -18)), self._defl(p, _f(p, "dangerDb", -6))
        out = []
        for k in range(n):
            c = (k + 0.5) / n
            out.append(_bgr(p["colDanger"]) if c >= danger else _bgr(p["colWarn"]) if c >= warn
                       else _bgr(p["colSafe"]))
        return out

    def layers(self, p: dict, w: int, h: int) -> dict[str, object]:
        g = self._geo(p)
        bg = _bgr(p["bg"])
        base, on = Canvas(w, h, bg), Canvas(w, h, bg)
        n = max(4, int(_f(p, "segments", 48)))
        xs = base.xf
        vert = bool(g["vert"])
        for kind, _chn, (x0, y0, x1, y1) in g["cols"]:  # type: ignore[union-attr]
            lad = _Ladder(xs.x(x0), xs.y(y0), xs.x(x1), xs.y(y1), n, xs.l(_f(p, "segGap", 3)), vert)
            _paint_ladder(base, on, lad, self._seg_colors(p, n, kind), _f(p, "unlit", 0.14), bg, xs.l(2))
        # Scale between the two peak meters.
        txt = _bgr(p["text"])
        floor = _f(p, "floorDbfs", -60)
        marks = [0, -3, -6, -9, -12, -18, -24, -30, -40, -50, -60, -70, -80]
        (_k, _c, pl), (_k2, _c2, pr) = g["cols"][0], g["cols"][1]  # type: ignore[index]
        text = bool(p.get("showText"))
        for db in (m for m in marks if m >= floor):
            d = self._defl(p, db)
            if vert:
                y = pl[3] - d * (pl[3] - pl[1])
                if text:
                    base.text(str(db), DESIGN_W / 2, y, 20, txt)
                base.line(pl[2] + 8, y, pl[2] + 22, y, txt, 2)
                base.line(pr[0] - 22, y, pr[0] - 8, y, txt, 2)
            else:
                x = pl[0] + d * (pl[2] - pl[0])
                if text:
                    base.text(str(db), x, DESIGN_H / 2, 20, txt)
                else:
                    base.line(x, DESIGN_H / 2 - 7, x, DESIGN_H / 2 + 7, txt, 2)
        for i, (x, y) in enumerate(g["readouts"] if text else []):  # type: ignore[union-attr]
            if vert:
                base.text("LR"[i], x, 740 + 18, 26, txt, "bold")
            else:
                base.text("LR"[i], 222, y, 26, txt, "bold")
        base_img, on_img = base.finish(), on.finish()
        xf = Xf(w, h)
        ladders = []
        for kind, chn, (x0, y0, x1, y1) in g["cols"]:  # type: ignore[union-attr]
            ladders.append((kind, chn, _Ladder(xf.x(x0), xf.y(y0), xf.x(x1), xf.y(y1), n,
                                               xf.l(_f(p, "segGap", 3)), vert)))
        return {"base": base_img, "on": on_img, "ladders": ladders, "geo": g}

    def draw(self, img: np.ndarray, xf: Xf, p: dict, a: Analysis, L: dict[str, object]) -> None:
        on = L["on"]  # type: ignore[assignment]
        for kind, chn, lad in L["ladders"]:  # type: ignore[union-attr]
            lvl = a.ppm[chn] if kind == "peak" else a.rms[chn]
            k = int(round(self._defl(p, float(lvl)) * lad.n))
            lad.reveal(img, on, 0, k)
            if kind == "peak":
                kh = int(round(self._defl(p, float(a.hold[chn])) * lad.n))
                if kh > k:
                    lad.reveal(img, on, kh - 1, kh)
        if not p.get("showText"):
            return
        panel, txt = _bgr(p["panel"]), _bgr(p["colSafe"])
        px = max(8, int(round(xf.l(58))))
        bw, bh = xf.l(150), xf.l(70)
        for i, (x, y) in enumerate(L["geo"]["readouts"]):  # type: ignore[index]
            clip = a.clip_age[i] < 1.5
            box_c = _bgr(p["colDanger"]) if clip else panel
            fg = (255, 255, 255) if clip else txt
            v = float(a.max_peak[i])
            s = "-inf" if v < -99 else f"{v:+.1f}" if v >= 0.05 else f"{v:.1f}"
            cx, cy = xf.x(x), xf.y(y)
            _rrect(img, int(round(cx - bw / 2)), int(round(cy - bh / 2)), int(round(cx + bw / 2)),
                   int(round(cy + bh / 2)), int(round(xf.l(10))), box_c, aa=True)
            patch = text_patch(s, px, fg, box_c, "digital")
            _blit(img, patch, int(round(cx + bw / 2 - xf.l(14) - patch.shape[1])), int(round(cy - patch.shape[0] / 2)))


# -- 4. 1/3-octave RTA ------------------------------------------------------------
_RTA31 = ("20", "25", "31.5", "40", "50", "63", "80", "100", "125", "160", "200", "250", "315", "400",
          "500", "630", "800", "1k", "1.25k", "1.6k", "2k", "2.5k", "3.15k", "4k", "5k", "6.3k", "8k",
          "10k", "12.5k", "16k", "20k")
_RTA_OCT = dict(zip(range(-5, 5), ("31.5", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k")))
_RTA_TITLE = {1: "OCTAVE", 2: "1/2 OCT", 3: "1/3 OCT", 6: "1/6 OCT"}


class RTA(Style):
    needs = ("spectrum",)

    @staticmethod
    def _per_octave(p: dict) -> int:
        return {"10": 1, "20": 2, "31": 3, "61": 6}.get(str(p.get("bandSet", "31")).split(" ")[0], 3)

    @classmethod
    def _bands(cls, p: dict) -> tuple[int, list[str], list[bool], float, float]:
        """``(count, labels, is-octave-centre, low edge Hz, high edge Hz)`` on the ISO grid around 1 kHz."""
        per = cls._per_octave(p)
        if per == 1:
            ks = list(range(-5, 5))  # 31.5 Hz … 16 kHz
        else:
            ks = [k for k in range(-12 * per, 12 * per) if 19.5 <= 1000.0 * 2 ** (k / per) <= 20500.0]
        octave = [k % per == 0 and k // per in _RTA_OCT for k in ks]
        if per == 3:
            labels = list(_RTA31)
        else:
            labels = [_RTA_OCT[k // per] if o else "" for k, o in zip(ks, octave)]
        half = 2 ** (1 / (2 * per))
        return len(ks), labels, octave, 1000.0 * 2 ** (ks[0] / per) / half, 1000.0 * 2 ** (ks[-1] / per) * half

    def analysis_params(self, p: dict) -> dict:
        _n, _lab, _oct, lo, hi = self._bands(p)
        return dict(p, fMin=lo, fMax=hi)

    _X1, _Y0, _Y1 = 1210.0, 110.0, 650.0

    @staticmethod
    def _x0(p: dict) -> float:
        return 150.0 if p.get("showText") else 70.0  # no scale labels: centered

    def _cells(self, p: dict) -> tuple[int, float]:
        """``(segments, top y)``. With ``squareCells``, as many 1:1 cells as fit the column (bottom-aligned)."""
        if not p.get("squareCells", True):
            return max(4, int(_f(p, "segments", 24))), self._Y0
        col_w = (self._X1 - self._x0(p)) / self._bands(p)[0] * (1.0 - _f(p, "colGapPct", 26) / 100.0)
        sg = _f(p, "segGap", 3)
        n = max(4, int((self._Y1 - self._Y0 + sg) // (col_w + sg)))
        return n, self._Y1 - (n * (col_w + sg) - sg)

    def _ladders(self, p: dict, xf: Xf) -> list[_Ladder]:
        n_b = self._bands(p)[0]
        slot = xf.l(self._X1 - self._x0(p)) / n_b
        gap = slot * _f(p, "colGapPct", 26) / 100.0
        n, top = self._cells(p)
        out = []
        for i in range(n_b):
            x0 = xf.x(self._x0(p)) + i * slot + gap / 2
            out.append(_Ladder(round(x0), xf.y(top), round(x0 + slot - gap), xf.y(self._Y1), n,
                               xf.l(_f(p, "segGap", 3)), True))
        return out

    def layers(self, p: dict, w: int, h: int) -> dict[str, object]:
        bg = _bgr(p["bg"])
        base, on = Canvas(w, h, bg), Canvas(w, h, bg)
        n_b, labels, octave, _lo, _hi = self._bands(p)
        n, top = self._cells(p)
        seg = _bgr(p["segColor"])
        colors = []
        for k in range(n):
            c = (k + 0.5) / n
            if p.get("zoneColors") and c >= _f(p, "dangerAt", 0.92):
                colors.append(_bgr(p["colDanger"]))
            elif p.get("zoneColors") and c >= _f(p, "warnAt", 0.75):
                colors.append(_bgr(p["colWarn"]))
            else:
                colors.append(seg)
        for lad in self._ladders(p, base.xf):
            _paint_ladder(base, on, lad, colors, _f(p, "unlit", 0.14), bg, base.xf.l(1.5))
        txt = _bgr(p["text"])
        slot = (self._X1 - self._x0(p)) / n_b
        text = bool(p.get("showText"))
        mode = str(p.get("labels")) if text else "none"
        for i, s in enumerate(labels):
            if mode == "none" or not s or (mode == "octaves" and not octave[i]):
                continue
            base.text(s, self._x0(p) + (i + 0.5) * slot, self._Y1 + 30, 17 if n_b > 12 else 20, txt)
        if p.get("showScale", True) and text:
            floor, ceil = _f(p, "floorDb", -84), _f(p, "ceilDb", -12)
            span = ceil - floor
            step = 6 if span <= 60 else 12
            db = 0.0
            while db >= -span - 1e-6:
                y = top + (-db / span) * (self._Y1 - top)
                base.text(f"{int(db)}" if db else "0", self._x0(p) - 40, y, 17, txt, anchor="rm")
                base.line(self._x0(p) - 30, y, self._x0(p) - 18, y, txt, 2)
                db -= step
            base.text("dB", self._x0(p) - 40, self._Y1 + 30, 17, txt, anchor="rm")
        if text:
            base.text(_RTA_TITLE[self._per_octave(p)], self._x0(p), top - 42, 17, txt, "bold", "lm")
        return {"base": base.finish(), "on": on.finish(), "ladders": self._ladders(p, Xf(w, h))}

    def draw(self, img: np.ndarray, xf: Xf, p: dict, a: Analysis, L: dict[str, object]) -> None:
        lads: list[_Ladder] = L["ladders"]  # type: ignore[assignment]
        n_b = len(lads)
        lv, pk = a.bands("M", n_b), a.bands("M", n_b, "peak")
        on = L["on"]  # type: ignore[assignment]
        pk_col = _bgr(p["peakColor"])
        for i, lad in enumerate(lads):
            k = int(round(float(lv[i]) * lad.n))
            lad.reveal(img, on, 0, k)
            kp = int(round(float(pk[i]) * lad.n))
            if kp > k and kp > 0:
                x0, y0, x1, y1 = lad.seg(kp - 1)
                _rrect(img, int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)),
                       int(round(xf.l(1.5))), pk_col, aa=True)


# -- non-hardware styles ---------------------------------------------------------
def _disc(img: np.ndarray, xf: Xf, x: float, y: float, r: float, color: tuple, w: float = -1.0) -> None:
    """Filled (``w < 0``) or stroked circle in design units."""
    if r <= 0:
        return
    cv2.circle(img, xf.p(x, y), int(round(xf.l(r) * _ONE)), color, -1 if w < 0 else xf.th(w), cv2.LINE_AA, SHIFT)


# -- 5. skyline: a night city whose windows follow the spectrum ----------------------------
class Skyline(Style):
    """One building per band, bass on the left; its windows light floor by floor with the level."""

    needs = ("spectrum",)
    GROUND = 770.0
    MARGIN = 10.0

    @staticmethod
    def _city(p: dict) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
        """``(front, back)`` buildings as ``(x0, x1, top)`` in design units, laid out from ``seed``."""
        rng = np.random.default_rng(int(_f(p, "seed", 7)))
        lo, hi = sorted((_f(p, "minH", 200), _f(p, "maxH", 560)))
        g = Skyline.GROUND
        front: list[tuple[float, float, float]] = []
        x = 30.0
        while True:
            bw = float(rng.uniform(56, 120))
            if x + bw > DESIGN_W - 30:
                break
            front.append((x, x + bw, g - float(rng.uniform(lo, hi))))
            x += bw + float(rng.uniform(8, 16))
        off = (DESIGN_W - 30 - front[-1][1]) / 2.0 if front else 0.0
        front = [(a + off, b + off, t) for a, b, t in front]
        back: list[tuple[float, float, float]] = []
        x = 0.0
        while x < DESIGN_W:
            bw = float(rng.uniform(40, 110))
            back.append((x, x + bw, g - float(rng.uniform(lo * 0.9, hi * 1.12))))
            x += bw + float(rng.uniform(0, 6))
        return front, back

    @staticmethod
    def _windows(p: dict, b: tuple[float, float, float]) -> tuple[list[float], list[float], list[float]]:
        """Window column lefts, floor bottoms (floor 0 at street level) and the cuts between floors."""
        ww, wh = _f(p, "windowW", 10), _f(p, "windowH", 13)
        gx, gy = ww * 0.8, wh * 0.7
        x0, x1, top = b
        m = Skyline.MARGIN
        ncol = max(1, int((x1 - x0 - 2 * m + gx) // (ww + gx)))
        span = ncol * ww + (ncol - 1) * gx
        xs = [x0 + (x1 - x0 - span) / 2.0 + i * (ww + gx) for i in range(ncol)]
        nrow = max(1, int((Skyline.GROUND - top - 2 * m + gy) // (wh + gy)))
        ys = [Skyline.GROUND - m - k * (wh + gy) for k in range(nrow)]
        # cuts[j]: boundary below floor j (cuts[0] is the street, cuts[n] above the top floor)
        cuts = [Skyline.GROUND] + [y - wh - gy / 2.0 for y in ys]
        return xs, ys, cuts

    def layers(self, p: dict, w: int, h: int) -> dict[str, object]:
        bg = _bgr(p["bg"])
        base, on, pk = Canvas(w, h, bg), Canvas(w, h, bg), Canvas(w, h, bg)
        front, back = self._city(p)
        bld, win = _bgr(p["building"]), _bgr(p["window"])
        if p.get("moon", True):
            base.circle(_f(p, "moonX", 1060), _f(p, "moonY", 150), _f(p, "moonR", 44), _bgr(p["moonColor"]))
        if p.get("showBack", True):
            for x0, x1, top in back:
                base.rrect(x0, top, x1, DESIGN_H, 0, _bgr(p["backColor"]))
        base.rrect(0, self.GROUND, DESIGN_W, DESIGN_H, 0, bld)
        ww, wh = _f(p, "windowW", 10), _f(p, "windowH", 13)
        out = []
        for b in front:
            xs, ys, cuts = self._windows(p, b)
            for cvs, col in ((base, _mix(bld, win, _f(p, "unlit", 0.10))), (on, win), (pk, _bgr(p["peakColor"]))):
                cvs.rrect(b[0], b[2], b[1], DESIGN_H, 0, bld)
                for y in ys:
                    for x in xs:
                        cvs.rrect(x, y - wh, x + ww, y, 1.5, col)
            out.append((b[0], b[1], cuts))
        return {"base": base.finish(), "on": on.finish(), "pk": pk.finish(), "front": out}

    def draw(self, img: np.ndarray, xf: Xf, p: dict, a: Analysis, L: dict[str, object]) -> None:
        front = L["front"]  # type: ignore[assignment]
        n = len(front)
        if not n:
            return
        lv, pkv = a.bands("M", n), a.bands("M", n, "peak")
        on, pk = L["on"], L["pk"]  # type: ignore[assignment]
        H, W = img.shape[:2]
        for i, (x0, x1, cuts) in enumerate(front):
            floors = len(cuts) - 1
            k, kp = int(round(float(lv[i]) * floors)), int(round(float(pkv[i]) * floors))
            ca, cb = max(0, int(round(xf.x(x0)))), min(W, int(round(xf.x(x1))))

            def copy(src: np.ndarray, j0: int, j1: int) -> None:  # floors j0..j1-1
                ya, yb = max(0, int(round(xf.y(cuts[j1])))), min(H, int(round(xf.y(cuts[j0]))))
                if yb > ya:
                    img[ya:yb, ca:cb] = src[ya:yb, ca:cb]

            if k > 0:
                copy(on, 0, k)
            if p.get("peaks", True) and kp > k:
                copy(pk, kp - 1, kp)


# -- 6. dot matrix ------------------------------------------------------------------
class DotMatrix(Style):
    needs = ("spectrum",)

    @staticmethod
    def _grid(p: dict, xf: Xf) -> tuple[int, int, float, float, float, float]:
        cols, rows = max(1, int(_f(p, "cols", 40))), max(1, int(_f(p, "rows", 22)))
        ins = _f(p, "insetX", 90)
        x0, x1 = xf.x(ins), xf.x(DESIGN_W - ins)
        y0, y1 = xf.y(_f(p, "top", 90)), xf.y(_f(p, "bottom", 710))
        return cols, rows, x0, (x1 - x0) / cols, y0, (y1 - y0) / rows

    def layers(self, p: dict, w: int, h: int) -> dict[str, object]:
        bg = _bgr(p["bg"])
        base, on, pk = Canvas(w, h, bg), Canvas(w, h, bg), Canvas(w, h, bg)
        cols, rows, x0, px, y0, py = self._grid(p, base.xf)
        d = min(px, py) * _f(p, "dotScale", 0.7)
        rad = int(round(d * 0.18)) if str(p.get("shape")) == "square" else int(round(d / 2))
        mode = str(p.get("colorMode"))
        mirror = str(p.get("layout")) == "mirror"
        unlit, pk_c = _f(p, "unlit", 0.12), _bgr(p["peakColor"])
        for c in range(cols):
            hue = _hsl_bgr(_f(p, "hueStart", 200) + _f(p, "hueSpan", 240) * c / max(1, cols - 1))
            for r in range(rows):
                # How far up this dot sits, 0..1 (from the middle when mirrored).
                lvl = abs(r + 0.5 - rows / 2) / (rows / 2) if mirror else (rows - r - 0.5) / rows
                if mode == "band hue":
                    col = hue
                elif mode == "two-tone" and lvl >= _f(p, "twoToneAt", 0.75):
                    col = _bgr(p["colB"])
                else:
                    col = _bgr(p["colA"])
                cx, cy = x0 + (c + 0.5) * px, y0 + (r + 0.5) * py
                box = (int(round(cx - d / 2)), int(round(cy - d / 2)), int(round(cx + d / 2)), int(round(cy + d / 2)))
                _rrect(base.img, *box, rad, _mix(bg, col, unlit))
                _rrect(on.img, *box, rad, col)
                _rrect(pk.img, *box, rad, pk_c)
        return {"base": base.finish(), "on": on.finish(), "pk": pk.finish()}

    def draw(self, img: np.ndarray, xf: Xf, p: dict, a: Analysis, L: dict[str, object]) -> None:
        cols, rows, x0, px, y0, py = self._grid(p, xf)
        lv, pkv = a.bands("M", cols), a.bands("M", cols, "peak")
        on, pk = L["on"], L["pk"]  # type: ignore[assignment]
        H, W = img.shape[:2]
        mirror = str(p.get("layout")) == "mirror"
        peaks = bool(p.get("peaks", True))

        def copy(src: np.ndarray, ca: int, cb: int, r0: int, r1: int) -> None:
            ya, yb = max(0, int(round(y0 + r0 * py))), min(H, int(round(y0 + r1 * py)))
            if yb > ya:
                img[ya:yb, ca:cb] = src[ya:yb, ca:cb]

        mid = rows / 2.0
        for c in range(cols):
            ca, cb = max(0, int(round(x0 + c * px))), min(W, int(round(x0 + (c + 1) * px)))
            if mirror:
                n, n_p = int(round(float(lv[c]) * mid)), int(round(float(pkv[c]) * mid))
                ra, rb = int(math.floor(mid - n)), int(math.ceil(mid + n))
                copy(on, ca, cb, ra, rb)
                if peaks and n_p > n:
                    pa, pb = int(math.floor(mid - n_p)), int(math.ceil(mid + n_p))
                    copy(pk, ca, cb, pa, pa + 1)
                    copy(pk, ca, cb, pb - 1, pb)
            else:
                k, kp = int(round(float(lv[c]) * rows)), int(round(float(pkv[c]) * rows))
                copy(on, ca, cb, rows - k, rows)
                if peaks and kp > k:
                    copy(pk, ca, cb, rows - kp, rows - kp + 1)


# -- bounce: a ball per band, thrown up by its level --------------------------------------
class Bounce(Style):
    needs = ("spectrum",)

    def _slots(self, p: dict) -> tuple[int, float, float, float, float, float]:
        n = max(2, int(_f(p, "balls", 16)))
        ins = _f(p, "insetX", 90)
        slot = (DESIGN_W - 2 * ins) / n
        r = min(slot * _f(p, "ballScale", 0.62) / 2.0, 46.0)
        return n, ins, slot, r, _f(p, "top", 110), _f(p, "floorY", 690)

    def layers(self, p: dict, w: int, h: int) -> dict[str, object]:
        cv = Canvas(w, h, _bgr(p["bg"]))
        if p.get("showFloor", True):
            _n, ins, _s, _r, _t, fy = self._slots(p)
            cv.rrect(ins - 20, fy + 14, DESIGN_W - ins + 20, fy + 20, 3, _bgr(p["floorColor"]))
        return {"base": cv.finish()}

    def draw(self, img: np.ndarray, xf: Xf, p: dict, a: Analysis, L: dict[str, object]) -> None:
        n, ins, slot, r, top, fy = self._slots(p)
        lv = a.bands("M", n)
        st = a.state.get("bounce")
        if st is None or st["h"].size != n:
            st = {"h": np.zeros(n), "v": np.zeros(n)}
            a.state["bounce"] = st
        g = _f(p, "gravity", 2.6)
        h, v = st["h"], st["v"]
        # Throw a ball when its band goes higher than the ball is about to reach.
        apex = h + np.maximum(v, 0.0) ** 2 / (2.0 * g)
        up = lv > apex + _f(p, "sensitivity", 0.03)
        v[up] = np.sqrt(2.0 * g * np.maximum(lv[up] - h[up], 0.0))
        v -= g * a.dt
        h += v * a.dt
        down = h <= 0.0
        h[down] = 0.0
        v[down] = np.where(v[down] < -0.25, -v[down] * _f(p, "bounce", 0.35), 0.0)
        span = fy - top - 2 * r
        if str(p.get("colorMode")) == "band hue":
            cols = [_hsl_bgr(_f(p, "hueStart", 200) + _f(p, "hueSpan", 240) * i / max(1, n - 1)) for i in range(n)]
        else:
            cols = [_bgr(p["colA"])] * n
        shadow = _bgr(p["shadowColor"])
        for i in range(n):
            x = ins + (i + 0.5) * slot
            if p.get("shadow", True):
                sw = r * (1.0 - 0.6 * min(1.0, h[i]))
                cv2.ellipse(img, xf.p(x, fy + 6), (int(round(xf.l(sw) * _ONE)), int(round(xf.l(r * 0.22) * _ONE))),
                            0.0, 0.0, 360.0, shadow, -1, cv2.LINE_AA, SHIFT)
            _disc(img, xf, x, fy - r - min(1.0, h[i]) * span, r, cols[i])


# -- fireflies: drifting lights that glow with their band -----------------------------------
class Fireflies(Style):
    needs = ("spectrum",)
    BANDS = 12

    @staticmethod
    @lru_cache(maxsize=8)
    def _swarm(count: int, seed: int) -> tuple[np.ndarray, ...]:
        """``(x, y, band, phase x, phase y, rate x, rate y, threshold)`` per firefly."""
        rng = np.random.default_rng(seed)
        return (rng.uniform(60, DESIGN_W - 60, count), rng.uniform(70, DESIGN_H - 70, count),
                rng.integers(0, Fireflies.BANDS, count), rng.uniform(0, 2 * math.pi, count),
                rng.uniform(0, 2 * math.pi, count), rng.uniform(0.25, 0.9, count), rng.uniform(0.2, 0.7, count),
                rng.uniform(0.15, 0.65, count))

    def layers(self, p: dict, w: int, h: int) -> dict[str, object]:
        base = np.empty((h, w, 3), np.uint8)
        base[:] = _bgr(p["bg"])
        return {"base": base}

    def draw(self, img: np.ndarray, xf: Xf, p: dict, a: Analysis, L: dict[str, object]) -> None:
        st = a.state.setdefault("fireflies", {"t": 0.0})
        st["t"] += a.dt * _f(p, "speed", 0.35)
        t = st["t"]
        bx, by, band, phx, phy, rx, ry, thr = self._swarm(int(_f(p, "count", 160)), int(_f(p, "seed", 3)))
        drift = _f(p, "drift", 50)
        x = bx + drift * np.sin(rx * t + phx)
        y = by + drift * 0.7 * np.sin(ry * t + phy)
        lv = a.bands("M", self.BANDS)[band]
        bg = _bgr(p["bg"])
        if str(p.get("colorMode")) == "solid":
            pal = [_bgr(p["colA"])] * 3
        else:
            pal = [_bgr(p["colLow"]), _bgr(p["colMid"]), _bgr(p["colHigh"])]
        group = np.minimum(2, band * 3 // self.BANDS)
        lit = lv > thr
        size, grow, dim = _f(p, "size", 4), _f(p, "grow", 7), _f(p, "dim", 0.2)
        for i in np.flatnonzero(~lit):
            _disc(img, xf, float(x[i]), float(y[i]), size * 0.6, _mix(bg, pal[group[i]], dim))
        for i in np.flatnonzero(lit):
            glow = float(lv[i] - thr[i]) / max(0.05, 1.0 - float(thr[i]))
            _disc(img, xf, float(x[i]), float(y[i]), size + grow * glow, pal[group[i]])


STYLE_IMPLS: dict[str, Style] = {
    "arc_vu": ArcVU(),
    "pixel_vu": PixelVU(),
    "sweep_vu": SweepVU(),
    "bars": Bars(),
    "led_ladder": LedLadder(),
    "rta": RTA(),
    "skyline": Skyline(),
    "dots": DotMatrix(),
    "bounce": Bounce(),
    "fireflies": Fireflies(),
}


# ---------------------------------------------------------------------------
# Toast (preset name on an encoder turn)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=32)
def _toast(name: str, index: int, count: int, w: int, h: int) -> tuple[np.ndarray, np.ndarray, int, int]:
    """``(bgr, alpha, row, col)`` for the pill: preset name over one dot per preset."""
    f = load_font(_font_path("medium"), 30)
    pw = max(260.0, f.getlength(name) + 80.0)
    x0, y0 = (DESIGN_W - pw) / 2.0, DESIGN_H - 150.0
    x1, y1 = x0 + pw, y0 + 96.0
    shape = Canvas(w, h, (0, 0, 0))
    shape.rrect(x0, y0, x1, y1, 48, (255, 255, 255))
    alpha = shape.finish()[:, :, 0].astype(np.float32) / 255.0
    col = Canvas(w, h, (0x23, 0x23, 0x23))
    col.text(name, DESIGN_W / 2.0, y0 + 38, 30, (255, 255, 255))
    step = 22.0
    dx0 = DESIGN_W / 2.0 - step * (count - 1) / 2.0
    for i in range(count):
        col.circle(dx0 + i * step, y0 + 72, 5, (0xF7, 0xA6, 0x4E) if i == index else (0x5A, 0x5A, 0x5A))
    bgr = col.finish()
    xf = Xf(w, h)
    r0, r1 = max(0, int(math.floor(xf.y(y0)))), min(h, int(math.ceil(xf.y(y1))))
    c0, c1 = max(0, int(math.floor(xf.x(x0)))), min(w, int(math.ceil(xf.x(x1))))
    return bgr[r0:r1, c0:c1].astype(np.float32), alpha[r0:r1, c0:c1, None], r0, c0


# ---------------------------------------------------------------------------
# Visualizer
# ---------------------------------------------------------------------------
class FullscreenViz:
    """Owns analysis state, the active preset and the per-size layer cache."""

    def __init__(self, index: int | None = None, *, remember: bool = False) -> None:
        """``remember``: start on, and keep, the preset last picked with the encoder (app state)."""
        self.analysis = Analysis()
        self._remember = bool(remember)
        self._save_at: float | None = None
        if index is None:
            index = self._remembered_index() if remember else None
        self._index = load_config()[1] if index is None else int(index)
        self._layers: OrderedDict[tuple, dict[str, object]] = OrderedDict()
        self._layers_lock = threading.Lock()  # prewarm() may run on another thread
        self._toast_until = 0.0
        self._last_t: float | None = None
        self._work: np.ndarray | None = None
        self._mask_key: tuple | None = None
        self._mask = np.zeros((0, 0, 1), np.float32)
        self._matte: tuple[tuple, dict[str, object]] | None = None
        self._matte_over: tuple[tuple, dict[str, object]] | None = None
        self.last_render_ms = 0.0

    # -- presets / encoder ----------------------------------------------------
    @property
    def index(self) -> int:
        n = len(presets())
        return self._index % n if n else 0

    def preset(self) -> dict[str, object]:
        items = presets()
        return items[self.index] if items else complete_preset({"style": "bars"})

    def rotate(self, steps: int) -> None:
        """Encoder turn: move ``steps`` presets (wraps) and show the name toast."""
        n = len(presets())
        if n:
            self.set_index((self.index + int(steps)) % n)
            if self._remember:
                self._save_at = time.monotonic() + REMEMBER_AFTER_S  # once the knob settles

    @staticmethod
    def _remembered_index() -> int | None:
        try:
            from pigeon.app_state import read_app_state_shared

            raw = read_app_state_shared().get(STATE_KEY)
            return None if raw is None else int(raw)
        except Exception:
            return None

    def _save_index(self) -> None:
        self._save_at = None
        try:
            from pigeon.app_state import write_app_state

            write_app_state(**{STATE_KEY: self.index})
        except Exception:
            pass

    def set_index(self, i: int, toast: bool = True) -> None:
        self._index = int(i)
        self.analysis.reset_max()
        if toast:
            self._toast_until = time.monotonic() + TOAST_S

    def show_toast(self) -> None:
        self._toast_until = time.monotonic() + TOAST_S

    # -- layers ---------------------------------------------------------------
    def _layers_for(self, p: dict, w: int, h: int) -> dict[str, object]:
        key = (w, h, json.dumps(p, sort_keys=True, default=str))
        with self._layers_lock:
            got = self._layers.get(key)
            if got is not None:
                self._layers.move_to_end(key)
                return got
        # Built outside the lock so a background prewarm never stalls a frame.
        got = STYLE_IMPLS[str(p["style"])].layers(p, w, h)
        with self._layers_lock:
            self._layers[key] = got
            while len(self._layers) > _LAYER_CACHE:
                self._layers.popitem(last=False)
        return got

    def _matte_layers_for(self, p: dict, w: int, h: int) -> dict[str, object]:
        """Layers with no page: each image layer premultiplied on black plus a
        ``<name>_a`` alpha matte (static art built on black and on white)."""
        black = self._layers_for(dict(p, bg="#000000", **{MATTE_BG_KEY: "#000000"}), w, h)
        white = self._layers_for(dict(p, bg="#FFFFFF", **{MATTE_BG_KEY: "#FFFFFF"}), w, h)
        key = (w, h, json.dumps(p, sort_keys=True, default=str))
        if self._matte is not None and self._matte[0] == key:
            return self._matte[1]
        out: dict[str, object] = dict(black)
        for name, k in black.items():
            wh = white.get(name)
            if isinstance(k, np.ndarray) and isinstance(wh, np.ndarray) and k.shape == (h, w, 3) == wh.shape:
                a = 1.0 - (wh.astype(np.float32) - k.astype(np.float32)).mean(axis=2) / 255.0
                out[name + "_a"] = np.clip(a, 0.0, 1.0)[:, :, None]
        self._matte = (key, out)
        self._matte_over = None
        return out

    def _over(self, L: dict[str, object], under: np.ndarray) -> dict[str, object]:
        """``L`` with every matted image layer composited over ``under`` (cached per background)."""
        fp = (self._matte[0] if self._matte else None, under.shape, hash(under[::8, ::8].tobytes()))
        if self._matte_over is not None and self._matte_over[0] == fp:
            return self._matte_over[1]
        u = under.astype(np.float32)
        out = dict(L)
        for name, a in L.items():
            if name.endswith("_a") and isinstance(a, np.ndarray):
                lay = L[name[:-2]].astype(np.float32)  # type: ignore[union-attr]
                out[name[:-2]] = np.clip(u * (1.0 - a) + lay, 0, 255).astype(np.uint8)
        self._matte_over = (fp, out)
        return out

    def prewarm(self, w: int = DESIGN_W, h: int = DESIGN_H, *, clear: bool = False) -> None:
        """Build every preset's static layers for ``w×h`` (e.g. on a background thread).

        ``clear`` builds the black / white pair :meth:`render` mattes with ``clear=True``."""
        for p in presets():
            if clear:
                for bg in ("#000000", "#FFFFFF"):
                    self._layers_for(dict(p, bg=bg, **{MATTE_BG_KEY: bg}), w, h)
            else:
                self._layers_for(p, w, h)

    # -- frame --------------------------------------------------------------------
    def render(self, out: np.ndarray, rect: tuple[int, ...] | None = None, *, capture: bool = True,
               toast: bool = True, clear: bool = False) -> None:
        """Draw the active preset into ``out`` (BGR or BGRA), or into ``rect = (x, y, w, h[, r])``.

        ``clear``: no page fill — the art draws straight over what ``rect`` already
        holds (``rect`` must lie inside ``out``).
        """
        t_start = time.perf_counter()
        p = self.preset()
        style = STYLE_IMPLS[str(p["style"])]
        now = time.monotonic()
        dt = 1.0 / 30.0 if self._last_t is None else max(1e-3, min(0.1, now - self._last_t))
        self._last_t = now
        if capture:
            _audio.want_mic_capture()
        self.analysis.update(style.analysis_params(p), dt, style.needs, style.channels(p))

        oh, ow = out.shape[:2]
        if rect is None:
            x, y, w, h, r = 0, 0, ow, oh, 0
        else:
            x, y, w, h = (int(v) for v in rect[:4])
            r = int(rect[4]) if len(rect) > 4 else 0
        if w < 16 or h < 16:
            return
        if clear:
            if x < 0 or y < 0 or x + w > ow or y + h > oh:
                return
            dst = out[y : y + h, x : x + w]
            L = self._over(self._matte_layers_for(p, w, h), np.ascontiguousarray(dst[:, :, :3]))
            img = L["base"].copy()  # type: ignore[union-attr]
            # Same black page the matte's ``base`` layer was built on.
            style.draw(img, Xf(w, h), dict(p, bg="#000000", **{MATTE_BG_KEY: "#000000"}), self.analysis, L)
            if toast and now < self._toast_until:
                self._draw_toast(img, w, h)
            dst[:, :, :3] = img
            if dst.shape[2] >= 4:
                ink = (L["base_a"][:, :, 0] * 255.0).astype(np.uint8)  # type: ignore[index]
                dst[:, :, 3] = np.maximum(dst[:, :, 3], ink)
            if self._save_at is not None and now >= self._save_at:
                self._save_index()
            self.last_render_ms = (time.perf_counter() - t_start) * 1000.0
            return
        direct = rect is None and out.ndim == 3 and out.shape[2] == 3 and out.flags.c_contiguous
        if direct:
            img = out
        else:
            if self._work is None or self._work.shape[:2] != (h, w):
                self._work = np.empty((h, w, 3), np.uint8)
            img = self._work
        L = self._layers_for(p, w, h)
        np.copyto(img, L["base"])  # type: ignore[arg-type]
        xf = Xf(w, h)
        style.draw(img, xf, p, self.analysis, L)
        if toast and now < self._toast_until:
            self._draw_toast(img, w, h)
        if not direct:
            self._composite(out, img, x, y, w, h, r)
        if self._save_at is not None and now >= self._save_at:
            self._save_index()
        self.last_render_ms = (time.perf_counter() - t_start) * 1000.0

    def _draw_toast(self, img: np.ndarray, w: int, h: int) -> None:
        items = presets()
        bgr, a, r0, c0 = _toast(str(self.preset().get("name", "")), self.index, len(items), w, h)
        th, tw = a.shape[:2]
        sub = img[r0 : r0 + th, c0 : c0 + tw]
        if sub.shape[:2] != (th, tw):
            return
        sub[:] = (sub.astype(np.float32) * (1.0 - a) + bgr * a).astype(np.uint8)

    def _composite(self, out: np.ndarray, img: np.ndarray, x: int, y: int, w: int, h: int, r: int) -> None:
        oh, ow = out.shape[:2]
        x0, y0, x1, y1 = max(0, x), max(0, y), min(ow, x + w), min(oh, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        r = max(0, min(r, w // 2, h // 2))
        corners = []
        if r > 0:
            # Keep what is under the four r×r corners, then blend it back
            # through the rounded mask (the only see-through pixels).
            if self._mask_key != (w, h, r):
                m = np.zeros((h * SS, w * SS), np.uint8)
                _rrect(m, 0, 0, w * SS, h * SS, r * SS, 255)
                self._mask = (cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA)
                              .astype(np.float32) / 255.0)[:, :, None]
                self._mask_key = (w, h, r)
            for ry, rx in ((0, 0), (0, w - r), (h - r, 0), (h - r, w - r)):
                if y + ry >= y0 and x + rx >= x0 and y + ry + r <= y1 and x + rx + r <= x1:
                    corners.append((ry, rx, out[y + ry : y + ry + r, x + rx : x + rx + r, :3].astype(np.float32)))
        src = img[y0 - y : y1 - y, x0 - x : x1 - x]
        if out.shape[2] == 4:
            # One SIMD conversion beats a strided 3-of-4-channel copy.
            src = cv2.cvtColor(np.ascontiguousarray(src), cv2.COLOR_BGR2BGRA)
        out[y0:y1, x0:x1] = src
        for ry, rx, under in corners:
            mk = self._mask[ry : ry + r, rx : rx + r]
            src = img[ry : ry + r, rx : rx + r].astype(np.float32)
            out[y + ry : y + ry + r, x + rx : x + rx + r, :3] = (src * mk + under * (1.0 - mk)).astype(np.uint8)
