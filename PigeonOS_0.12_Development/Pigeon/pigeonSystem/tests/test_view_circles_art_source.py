"""ViewCircles poster / TT setters: same-array fast path."""

from __future__ import annotations

import os
import sys
import unittest

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.widgets.view_circles import _same_source_art, _weak_or_none  # noqa: E402


class SameSourceArtTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = np.random.default_rng(0).integers(0, 255, (300, 200, 4), dtype=np.uint8)
        self.kept = self.src.copy()
        self.ref = _weak_or_none(self.src)

    def test_same_array_unchanged_is_same(self) -> None:
        self.assertTrue(_same_source_art(self.ref, self.src, self.kept))

    def test_equal_copy_is_not_assumed_same(self) -> None:
        self.assertFalse(_same_source_art(self.ref, self.src.copy(), self.kept))

    def test_in_place_repaint_is_caught(self) -> None:
        self.src[:] = 0
        self.assertFalse(_same_source_art(self.ref, self.src, self.kept))

    def test_nothing_kept_or_no_ref(self) -> None:
        self.assertFalse(_same_source_art(None, self.src, self.kept))
        self.assertFalse(_same_source_art(self.ref, self.src, None))


if __name__ == "__main__":
    unittest.main()
