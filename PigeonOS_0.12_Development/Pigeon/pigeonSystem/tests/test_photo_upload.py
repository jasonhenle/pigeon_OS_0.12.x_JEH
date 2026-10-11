"""Partial Tk photo uploads: changed-band detection and a real-Tk round trip."""

from __future__ import annotations

import os
import sys
import unittest

from unittest import mock

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.core.photo_upload import changed_bands  # noqa: E402


def _covers(bands, a: np.ndarray, b: np.ndarray) -> bool:
    mask = np.zeros(a.shape[:2], dtype=bool)
    for y0, y1, x0, x1 in bands:
        mask[y0:y1, x0:x1] = True
    diff = np.any(a != b, axis=2)
    return bool(np.all(mask[diff]))


class ChangedBandsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.a = np.random.default_rng(0).integers(0, 255, (1080, 1920, 3), dtype=np.uint8)

    def test_identical_is_empty(self) -> None:
        self.assertEqual(changed_bands(self.a, self.a.copy()), [])

    def test_viz_and_status_bar_are_two_tight_bands(self) -> None:
        b = self.a.copy()
        b[536:636, 113:1180] ^= 1
        b[1040:1070, 100:1800] ^= 1
        bands = changed_bands(self.a, b)
        self.assertEqual(len(bands), 2)
        self.assertTrue(_covers(bands, self.a, b))
        (y0, y1, x0, x1), (v0, v1, u0, u1) = bands
        self.assertEqual((y0, y1), (536, 636))
        self.assertEqual((v0, v1), (1040, 1070))
        self.assertLessEqual(x0, 113)
        self.assertGreaterEqual(x0, 110)
        self.assertGreaterEqual(x1, 1180)
        self.assertLessEqual(x1, 1183)

    def test_single_pixel_edges_are_covered(self) -> None:
        for y, x in ((0, 0), (0, 1919), (1079, 0), (1079, 1919), (500, 7), (500, 8)):
            b = self.a.copy()
            b[y, x, 2] ^= 0x80
            bands = changed_bands(self.a, b)
            self.assertTrue(bands and _covers(bands, self.a, b), (y, x, bands))

    def test_nearby_rows_merge(self) -> None:
        b = self.a.copy()
        b[100, 50] ^= 1
        b[110, 60] ^= 1
        self.assertEqual(len(changed_bands(self.a, b)), 1)

    def test_big_or_scattered_change_uploads_everything(self) -> None:
        b = self.a.copy()
        b[:800] ^= 1
        self.assertIsNone(changed_bands(self.a, b))
        c = self.a.copy()
        c[::100, 5] ^= 1
        self.assertIsNone(changed_bands(self.a, c))

    def test_shape_change_uploads_everything(self) -> None:
        self.assertIsNone(changed_bands(self.a, self.a[:, :960].copy()))


class TkRoundTripTests(unittest.TestCase):
    """Random frame sequences through the real upload path; photo must match."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            import tkinter as tk

            cls.root = tk.Tk()
            cls.root.withdraw()
        except Exception as exc:  # no display
            raise unittest.SkipTest(f"Tk unavailable: {exc}")
        import pigeon_0_12

        cls.app = pigeon_0_12

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()

    def _photo_bgr(self, photo, h: int, w: int) -> np.ndarray:
        rows = self.root.tk.splitlist(self.root.tk.call(str(photo), "data"))
        out = np.zeros((h, w, 3), dtype=np.uint8)
        for y, row in enumerate(rows):
            for x, px in enumerate(self.root.tk.splitlist(row)):
                v = int(str(px)[1:], 16)
                out[y, x] = (v & 255, (v >> 8) & 255, v >> 16)
        return out

    def test_photo_matches_every_frame(self) -> None:
        import tkinter as tk

        app = self.app
        label = tk.Label(self.root)
        holder = [None]
        rng = np.random.default_rng(1)
        h, w = 96, 128
        frame = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
        for step in range(40):
            frame = frame.copy()
            for _ in range(int(rng.integers(0, 3))):
                y, x = int(rng.integers(0, h - 4)), int(rng.integers(0, w - 4))
                frame[y : y + int(rng.integers(1, 4)), x : x + int(rng.integers(1, 4))] = rng.integers(0, 255, 3)
            if step == 20:
                frame = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)  # full change
            with mock.patch("pigeon.widgets.options_settings.apply_ui_look_bgr", side_effect=lambda f: f):
                app._update_label_photo_from_bgr(label, frame, holder)
            with self.subTest(step=step):
                np.testing.assert_array_equal(self._photo_bgr(holder[0], h, w), frame)
        self.assertIs(app._TK_SHOWN["photo"], holder[0])
        self.assertIsNotNone(app._TK_SHOWN["scratch"])  # partial path ran


if __name__ == "__main__":
    unittest.main()
