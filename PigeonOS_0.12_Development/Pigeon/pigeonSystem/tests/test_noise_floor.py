"""Noise floor: learned from quiet capture, subtracted by the meters and spectra."""

from __future__ import annotations

import os
import sys
import unittest

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import noise_floor as nf  # noqa: E402

RATE = 48_000
CHUNK = 384


def _noise(seconds: float, dbfs: float, seed: int = 0) -> np.ndarray:
    x = np.random.default_rng(seed).normal(size=(int(RATE * seconds), 2))
    return x / np.sqrt(np.mean(x * x)) * 10 ** (dbfs / 20)


def _feed(prof: nf.NoiseProfiler, x: np.ndarray) -> bool:
    took = False
    for i in range(0, x.shape[0] - CHUNK + 1, CHUNK):
        took = prof.feed(x[i:i + CHUNK], 1e-6) or took
    return took


class _Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class ProfilerTests(unittest.TestCase):
    def setUp(self) -> None:
        nf.set_profile(None)

    def tearDown(self) -> None:
        nf.set_profile(None)

    def test_learns_steady_quiet_input(self) -> None:
        prof = nf.NoiseProfiler(RATE, 2, clock=_Clock())
        self.assertTrue(_feed(prof, _noise(nf.QUIET_S + 1, -45)))
        p = nf.profile()
        assert p is not None
        self.assertAlmostEqual(p.dbfs, -45, delta=0.5)
        self.assertEqual(p.clip.shape[0], int(RATE * nf.CLIP_S))

    def test_needs_the_full_quiet_stretch(self) -> None:
        prof = nf.NoiseProfiler(RATE, 2, clock=_Clock())
        self.assertFalse(_feed(prof, _noise(nf.QUIET_S - 1, -45)))
        self.assertIsNone(nf.profile())

    def test_never_takes_loud_input(self) -> None:
        prof = nf.NoiseProfiler(RATE, 2, clock=_Clock())
        self.assertFalse(_feed(prof, _noise(nf.QUIET_S + 2, nf.MAX_DBFS + 3)))
        self.assertIsNone(nf.profile())

    def test_never_takes_moving_input(self) -> None:
        quiet, loud = _noise(1.0, -55), _noise(1.0, -40, seed=1)
        prof = nf.NoiseProfiler(RATE, 2, clock=_Clock())
        self.assertFalse(_feed(prof, np.concatenate([quiet, loud] * 6)))
        self.assertIsNone(nf.profile())

    def test_refreshes_only_after_refresh_interval(self) -> None:
        clock = _Clock()
        prof = nf.NoiseProfiler(RATE, 2, clock=clock)
        _feed(prof, _noise(nf.QUIET_S + 1, -45))
        first = nf.profile()
        clock.t += nf.REFRESH_S / 2
        self.assertFalse(_feed(prof, _noise(nf.QUIET_S + 1, -50, seed=2)))
        self.assertIs(nf.profile(), first)
        clock.t += nf.REFRESH_S
        self.assertTrue(_feed(prof, _noise(nf.QUIET_S + 1, -50, seed=3)))
        p = nf.profile()
        assert p is not None
        self.assertAlmostEqual(p.dbfs, -50, delta=0.5)


class SubtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        nf.set_profile(None)
        prof = nf.NoiseProfiler(RATE, 2, clock=_Clock())
        _feed(prof, _noise(nf.QUIET_S + 1, -45))

    def tearDown(self) -> None:
        nf.set_profile(None)

    def test_meter_floor_reads_zero_and_program_keeps_its_level(self) -> None:
        noise_ms = 10 ** (-45 / 10)
        self.assertEqual(nf.clean_ms(noise_ms, 0), 0.0)
        program_ms = 10 ** (-30 / 10)
        cleaned = nf.clean_ms(program_ms + noise_ms, 1)
        self.assertAlmostEqual(10 * np.log10(cleaned), -30, delta=0.2)

    def test_reader_gain_scales_the_floor(self) -> None:
        loud_noise = np.full(2, 10 ** ((-45 + 12) / 10))
        np.testing.assert_array_equal(nf.clean_ms_lr(loud_noise, gain_db=12.0), np.zeros(2))

    def test_cells_drop_noise_keep_a_tone(self) -> None:
        n_fft = 4096
        win = np.blackman(n_fft)
        b0 = np.arange(0, n_fft // 2 + 1, 64)

        def cells(m: np.ndarray) -> np.ndarray:
            return np.maximum.reduceat(20 * np.log10(m + 1e-12), b0)

        t = np.arange(n_fft) / RATE
        tone = 10 ** (-20 / 20) * np.sin(2 * np.pi * 1000 * t)
        noise = _noise(n_fft / RATE, -45, seed=4)[:, 0]
        quiet = cells(np.abs(np.fft.rfft(noise * win)) * 4 / n_fft)
        loud = cells(np.abs(np.fft.rfft((noise + tone) * win)) * 4 / n_fft)
        clean_q = nf.clean_cells_db(quiet, cells, ("t",), n_fft, win, 4 / n_fft, "L")
        clean_l = nf.clean_cells_db(loud, cells, ("t",), n_fft, win, 4 / n_fft, "L")
        self.assertLess(float(np.max(clean_q)), -100)
        k = int(np.argmax(loud))
        self.assertAlmostEqual(float(clean_l[k]), float(loud[k]), delta=0.5)

    def test_no_profile_passes_through(self) -> None:
        nf.set_profile(None)
        self.assertEqual(nf.clean_ms(0.01, 0), 0.01)
        cell = np.array([-40.0, -50.0])
        self.assertIs(nf.clean_cells_db(cell, lambda m: m, ("x",), 1024, np.hanning(1024), 1.0, "M"), cell)


if __name__ == "__main__":
    unittest.main()
