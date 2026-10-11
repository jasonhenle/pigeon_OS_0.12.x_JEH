"""Zone-4 EQ visualizer: a multi-band spectrum whose band count follows playback.

Takes zone 4's place (instead of cast / track info) when settings_pigeon
option4 is set to "visualizer"; ``PIGEON_ZONE4_EQ=0|1`` overrides the toggle.
Ported from the browser "Zone 5 Viz Lab"; parameter names match that page's
JSON so a look can be copied straight into ``zone4_eq.json`` in the Pigeon
state dir. The file is re-read when it changes, so edits show up live.

Audio: the ALSA meter capture feeds :func:`feed_pcm` on the Pi. Where
``arecord`` is missing (macOS dev), a ``sounddevice`` mic stream is opened on
demand and closed again shortly after the visualizer stops drawing.

Analysis keeps a fixed 512-point log/mel/linear spectrum with its own
attack / release / peak state; bars sample that grid, so smoothing and peaks
survive band-count changes.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import numpy as np

from pigeon.runtime_paths import pigeon_state_dir

CONFIG_NAME = "zone4_eq.json"

DEFAULT_PARAMS: dict[str, object] = {
    # "meters": L/R peak + RMS ladders (pigeon.zone4_meter, tuned under "meter");
    # "eq": the multi-band spectrum below.
    "visualizer": "meters",
    # Visualizer input gain: scales the PCM every visualizer reads (zone-4
    # meters / EQ, fullscreen presets; not the meter-face screensaver). Auto
    # gain steers program loudness toward ``inputTargetDb``; the trim adds on top.
    "inputAutoGain": True,
    "inputTrimDb": 0.0,
    "inputTargetDb": -20.0,  # program RMS the auto gain aims for (dBFS)
    "inputMaxBoostDb": 30.0,
    "inputMaxCutDb": 12.0,
    "inputGateDb": -60.0,  # quieter blocks (silence, hiss) hold the gain
    "inputRiseS": 0.5,  # loudness estimate follows louder program this fast (gain drops)
    "inputFallS": 6.0,  # ...and quieter program this slowly (gain climbs)
    # Position → band count
    "minBands": 4,
    "maxBands": 48,
    "shape": "ramp up",
    "cycles": 4,
    "gamma": 1.0,
    "quantize": "integer",
    "qStep": 4,
    "morphS": 0.6,
    "anchor": "left",
    # Audio analysis
    "fftSize": 4096,
    "fMin": 40.0,
    "fMax": 14000.0,
    "scale": "log",
    "agg": "max",
    "gainDb": 0.0,
    "floorDb": -85.0,
    "ceilDb": -20.0,
    "tilt": 3.0,
    "autoGain": False,
    "attackMs": 25.0,
    "releaseMs": 220.0,
    # Bars
    "style": "bars",
    "barRadius": 3.0,
    "gapPct": 22.0,
    "minGapPx": 2.0,
    "ledH": 6.0,
    "ledGap": 2.0,
    "minLevel": 0.04,
    "insetPx": 6.0,
    "peaks": True,
    "peakHoldMs": 400.0,
    "peakFall": 0.8,
    "peakH": 3.0,
    # Stereo
    "stereoMode": "mono",
    "bandsPerSide": True,
    "splitGapPx": 10.0,
    "stereoColor": "channel colors",
    "colL": "#4EA6F7",
    "colR": "#ff6a00",
    "overlayAlpha": 0.75,
    "balanceGain": 2.0,
    "swapLR": False,
    # Color
    "colorMode": "elapsed/remaining",
    "colA": "#4EA6F7",
    "colB": "#4d4d4d",
    "colPeak": "#ffffff",
    "hueSpan": 240.0,
    # The container is always the volume widget's grey (caller's
    # ``track_bgr``); the lab's ``trackFill`` is ignored. Progress / playhead
    # (``progressBg``, ``showPlayhead``) belong to the zone-5 status bar only.
    "showTrack": True,
}

GRID = 512
RING_SIZE = 32768
MAX_FFT = 16384
MIC_IDLE_CLOSE_S = 3.0
_CONFIG_POLL_S = 0.5

# ---------------------------------------------------------------------------
# Config (hot-reloaded)
# ---------------------------------------------------------------------------
_cfg_lock = threading.Lock()
_cfg: dict[str, object] = dict(DEFAULT_PARAMS)
_cfg_mtime: int | None = None
_cfg_checked = 0.0


def config_path() -> Path:
    return pigeon_state_dir() / CONFIG_NAME


def params() -> dict[str, object]:
    """Current parameters; re-reads ``zone4_eq.json`` at most twice a second."""
    global _cfg, _cfg_mtime, _cfg_checked
    now = time.monotonic()
    if now - _cfg_checked < _CONFIG_POLL_S:
        return _cfg
    with _cfg_lock:
        _cfg_checked = now
        try:
            mtime = config_path().stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime == _cfg_mtime:
            return _cfg
        _cfg_mtime = mtime
        merged = dict(DEFAULT_PARAMS)
        if mtime is not None:
            try:
                raw = json.loads(config_path().read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    merged.update(raw)
            except (OSError, ValueError) as exc:
                print(f"pigeon: zone4_eq: bad {CONFIG_NAME}: {exc}", file=sys.stderr)
        _cfg = merged
    return _cfg


def enabled() -> bool:
    """settings_pigeon option4; ``PIGEON_ZONE4_EQ=0|1`` overrides it."""
    env = os.environ.get("PIGEON_ZONE4_EQ", "").strip()
    if env in ("0", "1"):
        return env == "1"
    from pigeon.widgets.options_settings import zone4_visualizer_on

    return zone4_visualizer_on()


def _f(p: dict[str, object], key: str) -> float:
    try:
        return float(p.get(key, DEFAULT_PARAMS[key]))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float(DEFAULT_PARAMS[key])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PCM ring
# ---------------------------------------------------------------------------
_ring_lock = threading.Lock()
_ring = np.zeros((RING_SIZE, 2), dtype=np.float32)  # columns: L, R
_ring_pos = 0
_sample_rate = 48_000.0
_last_feed_mono = 0.0


# Visualizer input gain (see the ``input*`` params). The ring keeps the raw
# capture; readers get it scaled by ``input_gain_db()``.
_agc_loud_db: float | None = None  # slow program-loudness estimate, dBFS
_agc_db = 0.0


def _track_input_level(x: np.ndarray, dt: float) -> None:
    """Update the auto gain from one fed block (feeding thread)."""
    global _agc_loud_db, _agc_db
    p = params()
    ms = float((x * x).mean(axis=0).max())  # louder channel
    db = 10.0 * math.log10(ms + 1e-12)
    if db < _f(p, "inputGateDb"):
        return  # silence / hiss between tracks: hold
    if _agc_loud_db is None:
        _agc_loud_db = db
    else:
        tau = _f(p, "inputRiseS") if db > _agc_loud_db else _f(p, "inputFallS")
        k = 1.0 - math.exp(-dt / tau) if tau > 0 else 1.0
        _agc_loud_db += (db - _agc_loud_db) * k
    want = _f(p, "inputTargetDb") - _agc_loud_db
    _agc_db = max(-abs(_f(p, "inputMaxCutDb")), min(abs(_f(p, "inputMaxBoostDb")), want))


def input_gain_db() -> float:
    """Gain applied to the PCM visualizers read: auto (when on) + trim."""
    p = params()
    auto = _agc_db if p.get("inputAutoGain", True) else 0.0
    return auto + _f(p, "inputTrimDb")


def reset_input_gain() -> None:
    global _agc_loud_db, _agc_db
    _agc_loud_db, _agc_db = None, 0.0


def feed_pcm_stereo(left: np.ndarray, right: np.ndarray, sample_rate: float) -> None:
    """Append L/R samples in ``[-1, 1]`` (any thread)."""
    global _ring_pos, _sample_rate, _last_feed_mono
    x = np.stack(
        (np.asarray(left, dtype=np.float32).reshape(-1), np.asarray(right, dtype=np.float32).reshape(-1)),
        axis=1,
    )
    n = int(x.shape[0])
    if n < 1:
        return
    _track_input_level(x, n / float(sample_rate))
    with _ring_lock:
        _sample_rate = float(sample_rate)
        if n >= RING_SIZE:
            _ring[:] = x[-RING_SIZE:]
            _ring_pos = 0
        else:
            end = _ring_pos + n
            if end <= RING_SIZE:
                _ring[_ring_pos:end] = x
            else:
                first = RING_SIZE - _ring_pos
                _ring[_ring_pos:] = x[:first]
                _ring[: n - first] = x[first:]
            _ring_pos = end % RING_SIZE
        _last_feed_mono = time.monotonic()


def feed_pcm(mono: np.ndarray, sample_rate: float) -> None:
    """Append mono samples (both channels get the same signal)."""
    feed_pcm_stereo(mono, mono, sample_rate)


def _latest_samples(n: int) -> np.ndarray:
    """Most recent ``n`` frames as ``(n, 2)``, scaled by :func:`input_gain_db` (clipped to ±1)."""
    with _ring_lock:
        pos = _ring_pos
        if pos >= n:
            out = _ring[pos - n : pos].copy()
        else:
            out = np.concatenate((_ring[RING_SIZE - (n - pos) :], _ring[:pos]))
    g_db = input_gain_db()
    if abs(g_db) > 0.01:
        out *= np.float32(10.0 ** (g_db / 20.0))
        np.clip(out, -1.0, 1.0, out=out)
    return out


def latest_samples(n: int) -> np.ndarray:
    """Most recent ``n`` (≤ ``RING_SIZE``) frames as ``(n, 2)`` L/R (shared with the fullscreen visualizer)."""
    return _latest_samples(max(1, min(RING_SIZE, int(n))))


def sample_rate() -> float:
    return _sample_rate


def audio_fresh(max_age_s: float = 0.5) -> bool:
    return time.monotonic() - _last_feed_mono <= max_age_s


# ---------------------------------------------------------------------------
# macOS / no-ALSA mic capture
# ---------------------------------------------------------------------------
_mic_lock = threading.Lock()
_mic_stream = None
_mic_failed = False
_mic_last_want = 0.0


def _mic_watchdog() -> None:
    global _mic_stream
    while True:
        time.sleep(1.0)
        with _mic_lock:
            if _mic_stream is None:
                return
            if time.monotonic() - _mic_last_want < MIC_IDLE_CLOSE_S:
                continue
            try:
                _mic_stream.stop()
                _mic_stream.close()
            except Exception:
                pass
            _mic_stream = None
            print("pigeon: zone4_eq: mic capture closed (idle)", file=sys.stderr)
            return


def feed_wanted(max_idle_s: float = 2.0) -> bool:
    """Should the ALSA meter thread feed the PCM ring? Yes while the zone-4 EQ
    is on, or while any visualizer drew recently (it calls :func:`want_mic_capture`)."""
    if time.monotonic() - _mic_last_want < max_idle_s:
        return True
    try:
        return enabled()
    except Exception:
        return False


def stop_mic_capture() -> None:
    """Close the local mic stream now (e.g. a test harness switching to a synthetic feed)."""
    global _mic_stream
    with _mic_lock:
        if _mic_stream is None:
            return
        try:
            _mic_stream.stop()
            _mic_stream.close()
        except Exception:
            pass
        _mic_stream = None


def want_mic_capture() -> None:
    """Keep a local mic stream open while drawing, unless ALSA feeds us."""
    global _mic_stream, _mic_failed, _mic_last_want
    _mic_last_want = time.monotonic()
    if _mic_stream is not None or _mic_failed:
        return
    if shutil.which("arecord") is not None:
        return
    with _mic_lock:
        if _mic_stream is not None:
            return
        try:
            import sounddevice as sd  # type: ignore[import-not-found]

            chans = 2 if int(sd.query_devices(kind="input")["max_input_channels"]) >= 2 else 1

            def _cb(indata, _frames, _t, _status) -> None:
                feed_pcm_stereo(indata[:, 0], indata[:, chans - 1], 48_000.0)

            stream = sd.InputStream(
                samplerate=48_000, channels=chans, dtype="float32", blocksize=512, callback=_cb
            )
            stream.start()
        except Exception as exc:
            _mic_failed = True
            print(f"pigeon: zone4_eq: mic capture unavailable: {exc}", file=sys.stderr)
            return
        _mic_stream = stream
        print(f"pigeon: zone4_eq: mic capture opened ({chans} ch)", file=sys.stderr)
        threading.Thread(target=_mic_watchdog, name="zone4-eq-mic", daemon=True).start()


# ---------------------------------------------------------------------------
# Position → band count
# ---------------------------------------------------------------------------
def _hash01(i: int) -> float:
    s = math.sin(i * 127.1 + 311.7) * 43758.5453
    return s - math.floor(s)


def shape_t(p: dict[str, object], progress: float) -> float:
    c = max(1.0, _f(p, "cycles"))
    x = progress
    shape = str(p.get("shape"))
    if shape == "ramp down":
        return 1.0 - x
    if shape == "arc":
        return math.sin(math.pi * x)
    if shape == "valley":
        return 1.0 - math.sin(math.pi * x)
    if shape == "breathe":
        return 0.5 - 0.5 * math.cos(2.0 * math.pi * c * x)
    if shape == "sawtooth":
        return (x * c) % 1.0
    if shape == "random chapters":
        return _hash01(int(min(c - 1, math.floor(x * c))))
    return x


def target_bands(p: dict[str, object], progress: float) -> float:
    a, b = _f(p, "minBands"), _f(p, "maxBands")
    lo, hi = min(a, b), max(a, b)
    t = max(0.0, min(1.0, shape_t(p, max(0.0, min(1.0, progress)))))
    n = lo + (hi - lo) * (t ** max(0.05, _f(p, "gamma")))
    q = str(p.get("quantize"))
    if q == "integer":
        n = float(round(n))
    elif q == "step":
        step = max(1.0, _f(p, "qStep"))
        n = max(lo, round(n / step) * step)
    elif q == "powers of 2":
        n = float(2 ** round(math.log2(max(1.0, n))))
    return max(1.0, n)


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
def _hex_bgr(h: object, fallback: str = "#ffffff") -> np.ndarray:
    s = str(h or fallback).lstrip("#")
    try:
        v = int(s[:6], 16)
    except ValueError:
        v = int(fallback.lstrip("#"), 16)
    return np.array([v & 255, (v >> 8) & 255, (v >> 16) & 255], dtype=np.float32)


def _hsl_bgr(hue: float, s: float = 0.85, lum: float = 0.6) -> np.ndarray:
    c = (1 - abs(2 * lum - 1)) * s
    hp = (hue % 360.0) / 60.0
    x = c * (1 - abs(hp % 2 - 1))
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(hp) % 6]
    m = lum - c / 2
    return np.array([(b + m) * 255, (g + m) * 255, (r + m) * 255], dtype=np.float32)


# ---------------------------------------------------------------------------
# Visualizer
# ---------------------------------------------------------------------------
_STEREO_SPLIT = ("split", "butterfly (bass center)", "bass at edges")


class _Chan:
    """Smoothed 512-point spectrum + peak state for one channel (M, L or R)."""

    def __init__(self) -> None:
        self.level = np.zeros(GRID, dtype=np.float32)
        self.peak = np.zeros(GRID, dtype=np.float32)
        self.age = np.zeros(GRID, dtype=np.float32)

    def decay(self, dt: float) -> None:
        k = math.exp(-dt * 3.0)
        self.level *= k
        self.peak *= k


class Zone4EQ:
    def __init__(self) -> None:
        self._ch = {"M": _Chan(), "L": _Chan(), "R": _Chan()}
        self._agc_ref = 0.0
        self._bands: float | None = None
        self._last_t: float | None = None
        self._grid_key: tuple[object, ...] | None = None
        self._grid: tuple[np.ndarray, ...] = ()
        self._window_key = 0
        self._window = np.zeros(0, dtype=np.float32)
        self._mask_key: tuple[int, int, int] | None = None
        self._mask = np.zeros((0, 0), dtype=np.float32)

    # -- analysis ---------------------------------------------------------
    def _grid_for(self, p: dict[str, object], n_fft: int, sr: float) -> tuple[np.ndarray, ...]:
        scale = str(p.get("scale"))
        f_min = max(10.0, _f(p, "fMin"))
        f_max = max(f_min + 10.0, min(_f(p, "fMax"), sr * 0.5 - 1.0))
        key = (scale, f_min, f_max, n_fft, sr)
        if key == self._grid_key:
            return self._grid
        if scale == "mel":
            to_s = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)  # noqa: E731
            to_f = lambda s: 700.0 * (10.0 ** (s / 2595.0) - 1.0)  # noqa: E731
        elif scale == "linear":
            to_s = to_f = lambda v: v  # noqa: E731
        else:
            to_s, to_f = np.log, np.exp
        edges = to_f(np.linspace(to_s(f_min), to_s(f_max), GRID + 1))
        bin_hz = sr / n_fft
        lo, hi = edges[:-1], edges[1:]
        fc = np.sqrt(lo * hi)
        narrow = (hi - lo) / bin_hz < 1.0
        b0 = np.clip(np.floor(lo / bin_hz).astype(np.int64), 0, n_fft // 2)
        b1 = np.clip(np.ceil(hi / bin_hz).astype(np.int64), 0, n_fft // 2 + 1)
        b1 = np.maximum(b1, b0 + 1)
        tilt_oct = np.log2(fc / 1000.0).astype(np.float32)
        self._grid_key = key
        self._grid = (fc / bin_hz, narrow, b0, b1, tilt_oct)
        return self._grid

    def _raw(self, p: dict[str, object], x: np.ndarray, n_fft: int, sr: float) -> np.ndarray:
        """0..1+ (pre-AGC) grid levels for one windowed channel."""
        mag = np.abs(np.fft.rfft(x * self._window)) / float(n_fft)
        db = 20.0 * np.log10(mag + 1e-12)
        pos, narrow, b0, b1, tilt_oct = self._grid_for(p, n_fft, sr)
        # Wide cells: max over their bins (cells are contiguous, so reduceat works).
        wide_db = np.maximum.reduceat(db, b0)
        if str(p.get("agg")) in ("mean", "rms"):
            cnt = np.maximum(1, np.diff(np.append(b0, db.size)))
            wide_db = np.add.reduceat(db, b0) / cnt
        interp_db = np.interp(pos, np.arange(db.size), db)
        cell_db = np.where(narrow | (b1 - b0 <= 1), interp_db, wide_db).astype(np.float32)
        cell_db += _f(p, "gainDb") + _f(p, "tilt") * tilt_oct
        floor, ceil = _f(p, "floorDb"), _f(p, "ceilDb")
        return np.clip((cell_db - floor) / max(1.0, ceil - floor), 0.0, None)

    def _analyse(self, p: dict[str, object], dt: float, names: tuple[str, ...]) -> None:
        if not audio_fresh():
            for ch in self._ch.values():
                ch.decay(dt)
            return
        try:
            n_fft = int(p.get("fftSize", 4096))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            n_fft = 4096
        n_fft = int(2 ** round(math.log2(max(256, min(MAX_FFT, n_fft)))))
        if self._window_key != n_fft:
            self._window = np.blackman(n_fft).astype(np.float32)
            self._window_key = n_fft
        frames = _latest_samples(n_fft)
        sig = {"L": frames[:, 0], "R": frames[:, 1]}
        if "M" in names:
            sig["M"] = frames.mean(axis=1)
        raws = {k: self._raw(p, sig[k], n_fft, _sample_rate) for k in names}
        # One AGC for all channels so the L/R balance is preserved.
        frame_max = max(float(r.max()) for r in raws.values()) if raws else 0.0
        self._agc_ref = max(frame_max, self._agc_ref * math.exp(-dt / 4.0))
        agc = 0.9 / self._agc_ref if p.get("autoGain") and self._agc_ref > 0.05 else 1.0
        a_ms, r_ms = _f(p, "attackMs"), _f(p, "releaseMs")
        k_a = 1.0 - math.exp(-dt * 1000.0 / a_ms) if a_ms > 0 else 1.0
        k_r = 1.0 - math.exp(-dt * 1000.0 / r_ms) if r_ms > 0 else 1.0
        hold, fall = _f(p, "peakHoldMs"), _f(p, "peakFall")
        for name, raw in raws.items():
            ch = self._ch[name]
            v = np.minimum(raw * agc, 1.0)
            lvl = ch.level
            lvl += (v - lvl) * np.where(v > lvl, k_a, k_r).astype(np.float32)
            up = lvl >= ch.peak
            ch.peak[up] = lvl[up]
            ch.age[up] = 0.0
            ch.age[~up] += dt * 1000.0
            falling = (~up) & (ch.age > hold)
            ch.peak[falling] = np.maximum(0.0, ch.peak[falling] - fall * dt)

    @staticmethod
    def _sample(arr: np.ndarray, g0: float, g1: float, mode: str) -> float:
        i0 = max(0, int(math.floor(g0)))
        i1 = min(GRID, max(i0 + 1, int(math.ceil(g1))))
        seg = arr[i0:i1]
        if mode == "mean":
            return float(seg.mean())
        if mode == "rms":
            return float(np.sqrt(np.mean(seg * seg)))
        return float(seg.max())

    # -- drawing primitives -----------------------------------------------
    def _round_mask(self, w: int, h: int, r: int) -> np.ndarray:
        key = (w, h, r)
        if key != self._mask_key:
            import cv2

            m = np.zeros((h, w), dtype=np.uint8)
            r = max(0, min(r, w // 2, h // 2))
            if r <= 0:
                m[:] = 255
            else:
                cv2.rectangle(m, (r, 0), (w - 1 - r, h - 1), 255, -1)
                cv2.rectangle(m, (0, r), (w - 1, h - 1 - r), 255, -1)
                for cx, cy in ((r, r), (w - 1 - r, r), (r, h - 1 - r), (w - 1 - r, h - 1 - r)):
                    cv2.circle(m, (cx, cy), r, 255, -1, lineType=cv2.LINE_AA)
            self._mask = m.astype(np.float32) / 255.0
            self._mask_key = key
        return self._mask

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

    @classmethod
    def _fill_many(cls, col: np.ndarray, alpha: np.ndarray,
                   rects: list[tuple[float, float, float, float, np.ndarray, float, float]]) -> None:
        """:meth:`_fill` for many ``(x0, x1, y0, y1, bgr, radius, opacity)`` rects in one pass.

        Same coverage math per pixel. Rects that share a pixel column would need
        ordered blending, so those fall back to one ``_fill`` each.
        """
        h, w = alpha.shape
        keep = []
        for rect in rects:
            x0, x1, y0, y1 = rect[:4]
            cx0, cx1 = max(0.0, x0), min(float(w), x1)
            cy0, cy1 = max(0.0, y0), min(float(h), y1)
            if cx1 - cx0 > 1e-3 and cy1 - cy0 > 1e-3:
                keep.append((int(math.floor(cx0)), int(math.ceil(cx1)), cx0, cx1, cy0, cy1, rect))
        if not keep:
            return
        keep.sort(key=lambda k: k[0])
        if any(keep[j][0] < keep[j - 1][1] for j in range(1, len(keep))):
            # Blend order matters where rects overlap: keep the caller's order.
            for rect in rects:
                cls._fill(col, alpha, *rect)
            return
        n = len(keep)
        # Work only inside the rects' bounding box.
        bc0, bc1 = keep[0][0], max(k[1] for k in keep)
        br0 = int(math.floor(min(k[4] for k in keep)))
        br1 = int(math.ceil(max(k[5] for k in keep)))
        # Column → rect index; index n is an empty sentinel (zero coverage).
        owner = np.full(bc1 - bc0, n, dtype=np.intp)
        for k, (c0, c1, *_rest) in enumerate(keep):
            owner[c0 - bc0 : c1 - bc0] = k
        x0 = np.array([k[6][0] for k in keep] + [0.0])
        x1 = np.array([k[6][1] for k in keep] + [0.0])
        y0 = np.array([k[6][2] for k in keep] + [0.0])
        y1 = np.array([k[6][3] for k in keep] + [0.0])
        cx0 = np.array([k[2] for k in keep] + [0.0])
        cx1 = np.array([k[3] for k in keep] + [0.0])
        cy0 = np.array([k[4] for k in keep] + [0.0])
        cy1 = np.array([k[5] for k in keep] + [0.0])
        op = np.array([float(k[6][6]) for k in keep] + [0.0])
        bgr = np.stack([np.asarray(k[6][4], dtype=np.float32) for k in keep]
                       + [np.zeros(3, dtype=np.float32)])
        r = np.minimum(np.array([float(k[6][5]) for k in keep] + [0.0]),
                       np.minimum((x1 - x0) / 2.0, (y1 - y0) / 2.0))
        box = (r < 0.75) | (x1 - x0 < 2.0)
        r[box] = 0.0

        o = owner
        valid = o != n
        cols = np.arange(bc0, bc1, dtype=np.float64)
        row_i = np.arange(br0, br1)[:, None]
        # Column profile: what every pixel in a bar's straight middle gets.
        cxc = np.minimum(cols + 1.0, cx1[o]) - np.maximum(cols, cx0[o])
        qx = np.abs(cols + 0.5 - (x0 + x1)[o] / 2.0) - ((x1 - x0)[o] / 2.0 - r[o])
        rnd = ~box[o]
        prof = np.where(rnd, np.clip(0.5 - (qx - r[o]), 0.0, 1.0), cxc)
        # Rows of each rect, and its straight middle: rows whose centers sit at
        # least half the bar width inside both ends (rounded; there qy <= qx for
        # every column, so the signed distance reduces to qx - r), or rows
        # fully inside (box). Bounds are pulled in a row so rounding can only
        # send a middle row down the exact path, never the reverse.
        r0 = np.floor(cy0).astype(np.intp)
        r1 = np.ceil(cy1).astype(np.intp)
        ymid, hh, bwh = (y0 + y1) / 2.0, (y1 - y0) / 2.0, (x1 - x0) / 2.0
        lim = hh - bwh
        with np.errstate(invalid="ignore"):
            m_lo = np.where(box, np.ceil(cy0), np.ceil(ymid - lim - 0.5)) + 1
            m_hi = np.where(box, np.floor(cy1), np.floor(ymid + lim - 0.5) + 1) - 1
        no_mid = (~box & (lim < 0)) | (m_hi <= m_lo)
        m_lo = np.where(no_mid, r1, np.clip(m_lo, r0, r1)).astype(np.intp)
        m_hi = np.where(no_mid, r1, np.clip(m_hi, m_lo, r1)).astype(np.intp)
        r0[n] = r1[n] = m_lo[n] = m_hi[n] = br0
        a = np.where((row_i >= m_lo[o]) & (row_i < m_hi[o]), prof[None, :], 0.0)
        # Ends of each bar (and all of a short one): the full coverage math.
        ci = np.arange(bc1 - bc0)
        for z_start, z_len in ((r0, m_lo - r0), (m_hi, r1 - m_hi)):
            ln = np.where(valid, z_len[o], 0)
            k = int(ln.max(initial=0))
            if k <= 0:
                continue
            kk = np.arange(k)[:, None]
            rr = z_start[o][None, :] + kk
            ok = kk < ln[None, :]
            rrf = rr.astype(np.float64)
            ry = np.minimum(rrf + 1.0, cy1[o][None, :]) - np.maximum(rrf, cy0[o][None, :])
            val = np.maximum(ry, 0.0) * cxc[None, :]
            if rnd.any():
                qy = np.abs(rrf + 0.5 - ymid[o][None, :]) - (hh - r)[o][None, :]
                d = (np.hypot(np.maximum(qx, 0.0)[None, :], np.maximum(qy, 0.0))
                     + np.minimum(np.maximum(qx[None, :], qy), 0.0) - r[o][None, :])
                val = np.where(rnd[None, :], np.clip(0.5 - d, 0.0, 1.0), val)
            a[(rr - br0)[ok], np.broadcast_to(ci, rr.shape)[ok]] = val[ok]
        a[:, o == n] = 0.0
        a = (a * op[o][None, :]).astype(np.float32)
        cls._blend(col, alpha, br0, bc0, a, bgr[o][None, :, :])

    # -- colors -----------------------------------------------------------
    @staticmethod
    def _base_color(p: dict[str, object], i: int, count: int, lvl: float, cx: float, o: dict) -> np.ndarray:
        mode = str(p.get("colorMode"))
        col_a = _hex_bgr(p.get("colA"), "#4EA6F7")
        col_b = _hex_bgr(p.get("colB"), "#4d4d4d")
        if mode == "solid":
            return col_a
        if mode == "level gradient":
            return col_a + (col_b - col_a) * lvl
        if mode == "track gradient":
            return col_a + (col_b - col_a) * max(0.0, min(1.0, (cx - o["ax"]) / o["aw"]))
        if mode == "band hue":
            return _hsl_bgr(200.0 + (i / max(1, count - 1)) * _f(p, "hueSpan"))
        return col_a if cx <= o["play_x"] else col_b

    def _bar_color(self, p: dict[str, object], i: int, count: int, lvl: float, cx: float,
                   o: dict, bal: float | None) -> np.ndarray:
        col_l = _hex_bgr(p.get("colL"), "#4EA6F7")
        col_r = _hex_bgr(p.get("colR"), "#ff6a00")
        chan = None
        if bal is not None:
            t = max(0.0, min(1.0, 0.5 + bal * _f(p, "balanceGain") / 2.0))
            chan = col_l + (col_r - col_l) * t
        elif o["name"] == "L":
            chan = col_l
        elif o["name"] == "R":
            chan = col_r
        stereo_color = str(p.get("stereoColor"))
        if chan is None or stereo_color == "color mode":
            return self._base_color(p, i, count, lvl, cx, o)
        if stereo_color == "channel colors (played only)" and cx > o["play_x"]:
            return _hex_bgr(p.get("colB"), "#4d4d4d")
        return chan

    # -- one row of bars ----------------------------------------------------
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

        bars: list[tuple[float, float, float, float, np.ndarray, float, float]] = []
        peaks: list[tuple[float, float, float, float, np.ndarray, float, float]] = []
        in_order: list[tuple[float, float, float, float, np.ndarray, float, float]] = []
        slot_cols: list[tuple[int, int]] = []
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
            slot_cols.append((int(math.floor(x)), int(math.ceil(x + sub_w))))
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
                bars.append((x, x + sub_w, y, y + h, c, radius, opacity))
                in_order.append(bars[-1])
            if p.get("peaks", True) and style not in ("line", "dots"):
                dist = pk * H
                if direction == "up":
                    py = top + H - dist - peak_h
                elif direction == "down":
                    py = top + dist
                else:
                    py = top + (H - dist) / 2.0 - peak_h
                py = max(top, min(top + H - peak_h, py))
                pk_rect = (x, x + sub_w, py, py + peak_h, col_pk, min(radius, peak_h / 2.0), opacity)
                if style == "led":
                    self._fill(col, alpha, *pk_rect)
                else:
                    peaks.append(pk_rect)
                    in_order.append(pk_rect)
        if not in_order:
            return
        slot_cols.sort()
        if any(slot_cols[j][0] < slot_cols[j - 1][1] for j in range(1, len(slot_cols))):
            # Slots share a pixel column (no gap): keep bar/peak blend order.
            for rect in in_order:
                self._fill(col, alpha, *rect)
            return
        # Slots are column-disjoint, so bars-then-peaks blends the same as
        # bar/peak interleaved, and each pass is one vectorised fill.
        self._fill_many(col, alpha, bars)
        self._fill_many(col, alpha, peaks)

    # -- frame ------------------------------------------------------------
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
        p = params()
        now = time.monotonic()
        dt = 1.0 / 30.0 if self._last_t is None else max(1e-3, min(0.1, now - self._last_t))
        self._last_t = now
        want_mic_capture()
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
        see_through = pa[:, :, 0] < 1.0
        if np.count_nonzero(see_through) * 4 < see_through.size:
            # Opaque track: only the rounded corners need a real blend.
            under = dst[:, :, :3][see_through].astype(np.float32)
            a_st = pa[see_through]
            blended = (under * (1.0 - a_st) + pc[see_through] * a_st).astype(np.uint8)
            dst[:, :, :3] = pc.astype(np.uint8)
            dst[:, :, :3][see_through] = blended
        else:
            dst[:, :, :3] = (dst[:, :, :3].astype(np.float32) * (1.0 - pa) + pc * pa).astype(np.uint8)
        if dst.shape[2] >= 4:
            dst[:, :, 3] = np.maximum(dst[:, :, 3], (pa[:, :, 0] * 255.0).astype(np.uint8))
