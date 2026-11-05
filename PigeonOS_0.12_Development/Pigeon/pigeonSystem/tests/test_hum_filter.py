"""Mains hum + rumble removal on the meter capture."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import hum_filter as hf  # noqa: E402

RATE = 48_000
CHUNK = 384


def _tone(hz: float, amp: float, seconds: float = 1.0, phase: float = 0.0) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    return amp * np.sin(2 * np.pi * hz * t + phase)


def _stereo(x: np.ndarray) -> np.ndarray:
    return np.stack([x, x], axis=1)


def _run(filt, x: np.ndarray) -> np.ndarray:
    n = (x.shape[0] // CHUNK) * CHUNK
    return np.concatenate([filt.process(x[i:i + CHUNK]) for i in range(0, n, CHUNK)])


def _db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(x[:, 0] ** 2)) + 1e-12))


class HumCancellerTests(unittest.TestCase):
    def test_removes_hum_and_harmonics(self) -> None:
        hum = _tone(60, 0.03, phase=0.4) + _tone(180, 0.01, phase=1.1) + _tone(300, 0.004)
        out = _run(hf.HumCanceller(RATE, 2), _stereo(hum))
        settled = out[int(RATE * hf.WINDOW_S):]
        self.assertLess(_db(settled), _db(_stereo(hum)) - 40)

    def test_removes_50_hz_mains(self) -> None:
        hum = _tone(50, 0.03, phase=0.7) + _tone(150, 0.01, phase=0.2)
        h = hf.HumCanceller(RATE, 2, hum_hz=50)
        self.assertEqual(h.n % (RATE // 50), 0)
        out = _run(h, _stereo(hum))
        self.assertLess(_db(out[h.n:]), _db(_stereo(hum)) - 40)

    def test_chunks_straddling_the_window_edge(self) -> None:
        hum = _stereo(_tone(60, 0.03, seconds=2.0, phase=0.4))
        h = hf.HumCanceller(RATE, 2)
        sizes = [500, 333, 1000, 47] * 60
        out, i = [], 0
        for k in sizes:
            if i + k > hum.shape[0]:
                break
            out.append(h.process(hum[i:i + k]))
            i += k
        y = np.concatenate(out)
        self.assertLess(_db(y[RATE:]), _db(hum) - 40)

    def test_keeps_program_off_the_hum_lines(self) -> None:
        tone = _tone(440, 0.3)
        out = _run(hf.HumCanceller(RATE, 2), _stereo(tone + _tone(60, 0.03)))
        settled = out[int(RATE * hf.WINDOW_S):]
        self.assertAlmostEqual(_db(settled), _db(_stereo(tone)), delta=0.1)

    def test_passes_input_until_window_fills(self) -> None:
        x = _stereo(_tone(60, 0.03, seconds=0.05))
        h = hf.HumCanceller(RATE, 2)
        np.testing.assert_array_equal(h.process(x[:CHUNK]), x[:CHUNK])

    def test_zero_hz_disables(self) -> None:
        x = _stereo(_tone(60, 0.03, seconds=0.5))
        out = _run(hf.HumCanceller(RATE, 2, hum_hz=0), x)
        np.testing.assert_array_equal(out, x[: out.shape[0]])

    def test_env_picks_mains_frequency(self) -> None:
        for raw, want in (("", 60), ("50", 50), ("0", 0), ("75", 60), ("x", 60)):
            with mock.patch.dict(os.environ, {"PIGEON_HUM_HZ": raw}):
                self.assertEqual(hf.hum_hz_from_env(), want)


class RumbleFilterTests(unittest.TestCase):
    def test_matches_per_sample_cascade(self) -> None:
        x = np.random.default_rng(1).normal(0, 0.1, (CHUNK * 5, 2))
        r = hf.RumbleFilter(RATE, 2)
        block = _run(r, x)
        loop, _ = hf._run_sections(r._sections, x[:, 0], np.zeros(4))
        np.testing.assert_allclose(block[:, 0], loop, atol=1e-9)

    def test_odd_chunk_length_continues_state(self) -> None:
        x = np.random.default_rng(2).normal(0, 0.1, (CHUNK * 3, 2))
        a = _run(hf.RumbleFilter(RATE, 2), x)
        r = hf.RumbleFilter(RATE, 2)
        b = np.concatenate([r.process(x[:CHUNK]), r.process(x[CHUNK:CHUNK + 100]), r.process(x[CHUNK + 100:])])
        np.testing.assert_allclose(a, b, atol=1e-9)

    def test_cuts_rumble_keeps_bass(self) -> None:
        level = _db(_stereo(_tone(80, 0.1)))
        rumble = _run(hf.RumbleFilter(RATE, 2), _stereo(_tone(10, 0.1, seconds=2.0)))[RATE:]
        self.assertLess(_db(rumble), level - 30)
        bass = _run(hf.RumbleFilter(RATE, 2), _stereo(_tone(80, 0.1, seconds=2.0)))[RATE:]
        self.assertAlmostEqual(_db(bass), level, delta=0.2)


if __name__ == "__main__":
    unittest.main()
