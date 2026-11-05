"""Mains hum removal for the meter / visualizer capture.

A ground loop on the analog input puts a steady 60 Hz tone and its harmonics
into the capture (measured on the Pi: about -29 dBFS with nothing playing),
which lit the meters to ~40% at idle.

:class:`HumCanceller` fits sine / cosine pairs at the mains frequency and its
harmonics over a sliding window and subtracts that fit from each new chunk.
The window holds a whole number of cycles of every harmonic, so the pairs are
orthogonal and each coefficient is one dot product. Only about ±1/window Hz
around each hum line is removed (±4 Hz for 0.25 s), so program bass survives.

:class:`RumbleFilter` is the usual phono subsonic filter: what's left at idle
after the hum is mostly 10–30 Hz rumble.

``PIGEON_HUM_HZ`` sets the mains frequency (default 60; 50 in Europe; 0 turns
both filters off).
"""

from __future__ import annotations

import os

import numpy as np

HUM_HZ = 60
HARMONICS = 5  # 60 … 300 Hz
WINDOW_S = 0.25
REFIT_CHUNKS = 4  # hum is stationary: refit every ~32 ms of 8 ms chunks
RUMBLE_HZ = 25.0
# Matrix block: three per 8 ms chunk. Smaller blocks do less math than one
# 384×384 matmul (11 vs 31 ms of CPU per second of audio on a Pi 5).
RUMBLE_BLOCK = 128


def hum_hz_from_env() -> int:
    try:
        hz = int(float(os.environ.get("PIGEON_HUM_HZ", "") or HUM_HZ))
    except ValueError:
        return HUM_HZ
    return hz if hz in (0, 50, 60) else HUM_HZ


class HumCanceller:
    """Subtract a fitted mains hum from ``(frames, channels)`` float chunks."""

    def __init__(
        self,
        rate: int,
        channels: int,
        *,
        hum_hz: int = HUM_HZ,
        harmonics: int = HARMONICS,
        window_s: float = WINDOW_S,
        refit_chunks: int = REFIT_CHUNKS,
    ) -> None:
        self.rate = int(rate)
        self.hum_hz = int(hum_hz) if int(hum_hz) > 0 and self.rate % int(hum_hz) == 0 else 0
        period = self.rate // self.hum_hz if self.hum_hz else 1
        # A whole number of mains cycles: the sin / cos pairs stay orthogonal and
        # the table repeats every window, so the buffer is indexed by time mod n.
        self.n = max(1, int(round(float(window_s) * self.hum_hz))) * period
        freqs = self.hum_hz * np.arange(1, int(harmonics) + 1, dtype=np.float64)
        ph = 2.0 * np.pi * np.outer(np.arange(self.n, dtype=np.float64) / self.rate, freqs)
        self._basis = np.concatenate([np.sin(ph), np.cos(ph)], axis=1)  # (n, 2H)
        self._buf = np.zeros((self.n, int(channels)), dtype=np.float64)
        self._filled = 0
        self._pos = 0  # sample time of the next frame, mod n
        self._coef = np.zeros((self._basis.shape[1], int(channels)), dtype=np.float64)
        self._fitted = False
        self._refit = max(1, int(refit_chunks))
        self._since_fit = 0

    @property
    def enabled(self) -> bool:
        return self.hum_hz > 0

    def _slots(self, start: int, m: int) -> list[tuple[int, int, int]]:
        """``(slot, chunk offset, length)`` runs covering ``m`` frames from time ``start``."""
        out = []
        off = 0
        while off < m:
            slot = (start + off) % self.n
            k = min(m - off, self.n - slot)
            out.append((slot, off, k))
            off += k
        return out

    def process(self, x: np.ndarray) -> np.ndarray:
        """``x`` minus the hum fit; unchanged until the first full window."""
        if not self.enabled:
            return x
        m = int(x.shape[0])
        if m == 0:
            return x
        start = self._pos
        runs = self._slots(start, m)
        for slot, off, k in runs:
            self._buf[slot:slot + k] = x[off:off + k]
        self._pos = (start + m) % self.n
        self._filled = min(self.n, self._filled + m)
        if self._filled < self.n:
            return x
        self._since_fit += 1
        if not self._fitted or self._since_fit >= self._refit:
            self._coef = (2.0 / self.n) * (self._basis.T @ self._buf)
            self._fitted = True
            self._since_fit = 0
        out = np.empty_like(x, dtype=np.float64)
        for slot, off, k in runs:
            out[off:off + k] = x[off:off + k] - self._basis[slot:slot + k] @ self._coef
        return out


def _butter_hp_sections(cutoff_hz: float, rate: float) -> list[tuple[tuple[float, float, float], tuple[float, float]]]:
    """4th-order Butterworth highpass as two RBJ biquads ``((b0, b1, b2), (a1, a2))``."""
    out = []
    w0 = 2.0 * np.pi * float(cutoff_hz) / float(rate)
    cw, sw = float(np.cos(w0)), float(np.sin(w0))
    for q in (0.5411961, 1.3065630):
        alpha = sw / (2.0 * q)
        a0 = 1.0 + alpha
        b = ((1.0 + cw) / 2.0 / a0, -(1.0 + cw) / a0, (1.0 + cw) / 2.0 / a0)
        out.append((b, (-2.0 * cw / a0, (1.0 - alpha) / a0)))
    return out


def _run_sections(sections, x: np.ndarray, state: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Plain-Python biquad cascade (direct form II transposed) on one channel."""
    st = [float(v) for v in state]
    y = np.empty(x.size, dtype=np.float64)
    for i in range(x.size):
        v = float(x[i])
        for s, ((b0, b1, b2), (a1, a2)) in enumerate(sections):
            z1, z2 = st[2 * s], st[2 * s + 1]
            out = b0 * v + z1
            st[2 * s] = b1 * v - a1 * out + z2
            st[2 * s + 1] = b2 * v - a2 * out
            v = out
        y[i] = v
    return y, np.array(st, dtype=np.float64)


class RumbleFilter:
    """Subsonic highpass (4th-order Butterworth, 25 Hz) for ``(frames, channels)`` chunks.

    The cascade is linear, so for a fixed block length its output is
    ``T @ x + O @ state`` and the next state ``P @ x + Q @ state``. Those
    matrices are worked out once, which turns each block into two small
    matmuls instead of a per-sample Python loop.
    """

    def __init__(self, rate: int, channels: int, *, cutoff_hz: float = RUMBLE_HZ, frames: int = RUMBLE_BLOCK) -> None:
        self._sections = _butter_hp_sections(cutoff_hz, rate)
        n_state = 2 * len(self._sections)
        self.frames = int(frames)
        m = self.frames
        zero_s = np.zeros(n_state)
        cols_y, cols_s = [], []
        for j in range(m):
            e = np.zeros(m)
            e[j] = 1.0
            y, s = _run_sections(self._sections, e, zero_s)
            cols_y.append(y)
            cols_s.append(s)
        self._T = np.stack(cols_y, axis=1)  # (m, m)
        self._P = np.stack(cols_s, axis=1)  # (n_state, m)
        cols_y, cols_s = [], []
        for k in range(n_state):
            e = np.zeros(n_state)
            e[k] = 1.0
            y, s = _run_sections(self._sections, np.zeros(m), e)
            cols_y.append(y)
            cols_s.append(s)
        self._O = np.stack(cols_y, axis=1)  # (m, n_state)
        self._Q = np.stack(cols_s, axis=1)  # (n_state, n_state)
        self._state = np.zeros((n_state, int(channels)), dtype=np.float64)

    def _loop(self, x: np.ndarray) -> np.ndarray:
        out = np.empty_like(x, dtype=np.float64)
        for c in range(x.shape[1]):
            out[:, c], self._state[:, c] = _run_sections(self._sections, x[:, c], self._state[:, c])
        return out

    def process(self, x: np.ndarray) -> np.ndarray:
        """Whole blocks of :attr:`frames` go through the matrices; a remainder runs per sample."""
        m = int(x.shape[0])
        b = self.frames
        out = np.empty_like(x, dtype=np.float64)
        whole = (m // b) * b
        for i in range(0, whole, b):
            blk = x[i:i + b]
            out[i:i + b] = self._T @ blk + self._O @ self._state
            self._state = self._P @ blk + self._Q @ self._state
        if whole < m:
            out[whole:] = self._loop(x[whole:])
        return out
