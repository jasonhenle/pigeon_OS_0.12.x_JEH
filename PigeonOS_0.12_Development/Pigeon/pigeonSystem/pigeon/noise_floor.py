"""Input noise floor: learned from the capture while it sits quiet, subtracted by every reader.

The hum and rumble filters (:mod:`pigeon.hum_filter`) take out what they can,
but an analog input still carries some floor (on the Pi, 20–55 Hz rumble at
about -44 dBFS), and the meters' calibration is sensitive enough to light up
on it.

:class:`NoiseProfiler` watches the filtered capture. Once the input has been
steady and low for :data:`QUIET_S`, the last :data:`CLIP_S` of it becomes the
noise profile: the first quiet stretch after boot, then again on a later
quiet stretch at most every :data:`REFRESH_S`. Anything louder than
:data:`MAX_DBFS` or with more than :data:`MAX_SPREAD_DB` of movement is never
taken for noise, and neither is a clip whose spectrum changes from one
:data:`SEG_S` to the next (:func:`spectrum_steady`): quiet music can hold a
steady level (a zone 2 output turned down), but its notes keep moving, while
hiss and rumble keep the same spectrum. Such a stretch is noted as program
(:func:`steady_program_within`), so the hiss check doesn't take it either.

Readers subtract noise *power* (with :data:`MARGIN_DB` of over-subtraction so
the floor sits at zero instead of flickering; :data:`SPECTRUM_MARGIN_DB` for
spectra). Each spectrum asks for the
noise in its own FFT size, window and scaling, and the visualizers through
their own cell aggregation (:func:`clean_cells_db`), so the subtraction lines
up with what they draw. With no profile everything passes
through unchanged (the Mac lab, or before the first quiet stretch).
"""

from __future__ import annotations

import math
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

QUIET_S = 8.0
CLIP_S = 3.0
BLOCK_S = 0.25
MAX_DBFS = -30.0
MAX_SPREAD_DB = 6.0
REFRESH_S = 600.0
MARGIN_DB = 2.0
# One FFT frame's bins swing well above their mean, so spectra over-subtract more.
SPECTRUM_MARGIN_DB = 6.0
CELLS_MARGIN_DB = 9.0
# Spectrum steadiness: band levels over SEG_S slices; noise moves well under this.
SEG_S = 0.25
STEADY_BANDS = 16
MAX_BAND_STD_DB = 2.0
STEADY_CHECK_S = 1.0  # the check costs a few ms on a Pi 5; reuse its verdict this long
_K = 10.0 ** (MARGIN_DB / 10.0)
_K_SPECTRUM = 10.0 ** (SPECTRUM_MARGIN_DB / 10.0)
_K_CELLS = 10.0 ** (CELLS_MARGIN_DB / 10.0)


@dataclass(frozen=True)
class Profile:
    clip: np.ndarray  # (frames, 2) float32, filtered capture
    rate: float
    ms: np.ndarray  # mean square per channel [L, R]
    lfe_ms: float  # mean square of the meter's LFE lowpass output
    taken_mono: float
    _bins: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def dbfs(self) -> float:
        return 10.0 * math.log10(float(np.max(self.ms)) + 1e-12)


_profile: Profile | None = None
_lock = threading.Lock()
_steady_program_mono = 0.0  # last time a steady, quiet stretch turned out to be program


def spectrum_steady(clip: np.ndarray, rate: float) -> bool:
    """True when ``clip``'s spectrum holds still: median band-level spread over :data:`SEG_S` slices."""
    x = np.asarray(clip, dtype=np.float64)
    x = x.mean(axis=1) if x.ndim == 2 else x
    n = int(float(rate) * SEG_S)
    segs = x.size // max(1, n)
    if n < 64 or segs < 4:
        return True
    frames = x[: segs * n].reshape(segs, n).astype(np.float32) * np.hanning(n).astype(np.float32)
    spec = np.fft.rfft(frames, axis=1)
    power = spec.real ** 2 + spec.imag ** 2
    edges = np.geomspace(60.0, min(16_000.0, 0.45 * float(rate)), STEADY_BANDS + 1)
    bins = np.unique(np.clip(np.round(edges * n / float(rate)).astype(int), 0, power.shape[1]))
    bands = np.add.reduceat(power, bins, axis=1)[:, : bins.size - 1]
    db = 10.0 * np.log10(bands.astype(np.float64) + 1e-20)
    return float(np.median(db.std(axis=0))) <= MAX_BAND_STD_DB


def steady_program_within(seconds: float, now: float | None = None) -> bool:
    """True when a steady, quiet stretch was judged program (not noise) in the last ``seconds``."""
    t = time.monotonic() if now is None else float(now)
    return _steady_program_mono > 0.0 and (t - _steady_program_mono) < float(seconds)


def profile() -> Profile | None:
    return _profile


def set_profile(p: Profile | None) -> None:
    global _profile
    _profile = p


def _gain2(gain_db: float) -> float:
    return 10.0 ** (float(gain_db) / 10.0)


def clean_ms(ms: float, chan: int | None) -> float:
    """Mean square minus the floor: ``chan`` 0 / 1 for L / R, ``None`` for the LFE band."""
    p = _profile
    if p is None:
        return float(ms)
    noise = p.lfe_ms if chan is None else float(p.ms[int(chan)])
    return max(0.0, float(ms) - _K * noise)


def clean_ms_lr(ms: np.ndarray, *, gain_db: float = 0.0) -> np.ndarray:
    """``[L, R]`` mean squares minus the floor, for readers that apply ``gain_db``."""
    p = _profile
    if p is None:
        return ms
    return np.maximum(np.asarray(ms, dtype=np.float64) - _K * _gain2(gain_db) * p.ms, 0.0)


def _noise_mean(key: tuple, n_fft: int, window: np.ndarray, scale: float, chan: str, power_fn) -> np.ndarray | None:
    """Mean of ``power_fn(|rfft(x * window) * scale|)`` over the noise clip's frames (cached per profile)."""
    p = _profile
    if p is None:
        return None
    n_fft = int(n_fft)
    key = (key, n_fft, float(scale), str(chan), int(window.size), round(float(np.sum(window)), 6))
    with _lock:
        hit = p._bins.get(key)
    if hit is not None:
        return hit
    clip = p.clip
    x = clip.mean(axis=1) if chan == "M" else clip[:, 0 if chan == "L" else 1]
    x = x.astype(np.float64)
    win = np.asarray(window, dtype=np.float64)
    acc = None
    count = 0
    for s in range(0, x.size - n_fft + 1, max(1, n_fft // 2)):
        v = np.asarray(power_fn(np.abs(np.fft.rfft(x[s:s + n_fft] * win) * float(scale))), dtype=np.float64)
        acc = v if acc is None else acc + v
        count += 1
    if acc is None:
        return None
    out = acc / count
    with _lock:
        p._bins[key] = out
    return out


def noise_power_bins(n_fft: int, window: np.ndarray, scale: float, chan: str) -> np.ndarray | None:
    """Mean ``|rfft(x * window) * scale|²`` of the noise clip, for ``chan`` M / L / R."""
    return _noise_mean(("bins",), n_fft, window, scale, chan, np.square)


def clean_mag(
    mag: np.ndarray, n_fft: int, window: np.ndarray, scale: float, chan: str, *, gain_db: float = 0.0
) -> np.ndarray:
    """Spectrum magnitude ``mag`` (already ``* scale``) with the noise power taken out (for band averages)."""
    noise = noise_power_bins(n_fft, window, scale, chan)
    if noise is None or noise.shape != mag.shape:
        return mag
    return np.sqrt(np.maximum(mag.astype(np.float64) ** 2 - _K_SPECTRUM * _gain2(gain_db) * noise, 0.0)).astype(mag.dtype)


def clean_cells_db(
    cell_db: np.ndarray,
    cells_db_fn,
    cells_key: tuple,
    n_fft: int,
    window: np.ndarray,
    scale: float,
    chan: str,
    *,
    gain_db: float = 0.0,
) -> np.ndarray:
    """Display cells (dB, from ``cells_db_fn(mag)``) with the noise's own cell levels taken out.

    The noise goes through the same cell aggregation (e.g. loudest bin per
    cell), so a wide cell's max-of-many-bins statistic is matched instead of
    the per-bin mean. ``cells_key`` names the aggregation for the cache.
    """
    noise = _noise_mean(
        ("cells", cells_key), n_fft, window, scale, chan, lambda m: 10.0 ** (np.asarray(cells_db_fn(m)) / 10.0)
    )
    if noise is None or noise.shape != cell_db.shape:
        return cell_db
    p = 10.0 ** (np.asarray(cell_db, dtype=np.float64) / 10.0)
    out = 10.0 * np.log10(np.maximum(p - _K_CELLS * _gain2(gain_db) * noise, 1e-12))
    return out.astype(np.asarray(cell_db).dtype)


class NoiseProfiler:
    """Feed it every filtered capture chunk; it sets the profile on a quiet stretch."""

    def __init__(self, rate: int, channels: int = 2, *, clock=time.monotonic) -> None:
        self.rate = int(rate)
        self._clock = clock
        # Ring buffer (write position ``_clip_pos``), put in time order only when a profile is taken.
        self._clip = np.zeros((int(rate * CLIP_S), int(channels)), dtype=np.float32)
        self._clip_pos = 0
        self._clip_fill = 0
        self._block_n = int(rate * BLOCK_S)
        self._blk_ss = np.zeros(int(channels))
        self._blk_lfe = 0.0
        self._blk_frames = 0
        self._blk_chunks = 0
        n_quiet = int(round(QUIET_S / BLOCK_S))
        self._dbs: deque[float] = deque(maxlen=n_quiet)
        self._lfe: deque[float] = deque(maxlen=int(round(CLIP_S / BLOCK_S)))
        self._steady_checked = -1e9
        self._steady = True

    def feed(self, x: np.ndarray, lfe_ms: float) -> bool:
        """One chunk ``(frames, channels)`` plus its LFE mean square. True when a profile was taken."""
        m = int(x.shape[0])
        if m == 0:
            return False
        size = self._clip.shape[0]
        if m >= size:
            self._clip[:] = x[-size:]
            self._clip_pos = 0
        else:
            end = self._clip_pos + m
            if end <= size:
                self._clip[self._clip_pos:end] = x
            else:
                first = size - self._clip_pos
                self._clip[self._clip_pos:] = x[:first]
                self._clip[: m - first] = x[first:]
            self._clip_pos = end % size
        self._clip_fill = min(size, self._clip_fill + m)
        self._blk_ss += (x * x).sum(axis=0)
        self._blk_lfe += float(lfe_ms)
        self._blk_frames += m
        self._blk_chunks += 1
        if self._blk_frames < self._block_n:
            return False
        ms = self._blk_ss / self._blk_frames
        self._dbs.append(10.0 * math.log10(float(ms.max()) + 1e-12))
        self._lfe.append(self._blk_lfe / max(1, self._blk_chunks))
        self._blk_ss[:] = 0.0
        self._blk_lfe = 0.0
        self._blk_frames = 0
        self._blk_chunks = 0
        return self._maybe_take()

    def _maybe_take(self) -> bool:
        if len(self._dbs) < (self._dbs.maxlen or 0) or self._clip_fill < self._clip.shape[0]:
            return False
        if max(self._dbs) >= MAX_DBFS or (max(self._dbs) - min(self._dbs)) > MAX_SPREAD_DB:
            return False
        now = float(self._clock())
        if now - self._steady_checked >= STEADY_CHECK_S:
            self._steady_checked = now
            self._steady = spectrum_steady(self._clip, self.rate)
        if not self._steady:
            global _steady_program_mono
            _steady_program_mono = time.monotonic()
            return False
        cur = _profile
        if cur is not None and (now - cur.taken_mono) < REFRESH_S:
            return False
        clip = np.concatenate((self._clip[self._clip_pos:], self._clip[: self._clip_pos]))
        p = Profile(
            clip=clip,
            rate=float(self.rate),
            ms=(clip.astype(np.float64) ** 2).mean(axis=0),
            lfe_ms=float(np.mean(self._lfe)) if self._lfe else 0.0,
            taken_mono=now,
        )
        set_profile(p)
        self._dbs.clear()
        try:
            sys.stderr.write(f"pigeon: noise floor learned: {p.dbfs:.1f} dBFS (L/R {(10.0 * np.log10(p.ms + 1e-12)).round(1).tolist()})\n")
            sys.stderr.flush()
        except Exception:
            pass
        return True
