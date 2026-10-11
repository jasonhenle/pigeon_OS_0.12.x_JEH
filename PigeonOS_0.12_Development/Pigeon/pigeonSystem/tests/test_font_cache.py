"""Shared font cache returns one object per (path, size) and falls back cleanly."""

from __future__ import annotations

import os
import sys
import unittest

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)


class FontCacheTests(unittest.TestCase):
    def test_same_path_and_size_is_shared(self) -> None:
        from pigeon.font_cache import load_font
        from pigeon.font_paths import resolve_digital7_font

        path = resolve_digital7_font()
        if not path:
            self.skipTest("Digital-7 font not found")
        a = load_font(path, 40)
        self.assertIs(a, load_font(str(path), 40))
        self.assertIsNot(a, load_font(path, 41))

    def test_missing_or_empty_path_falls_back_to_default(self) -> None:
        from pigeon.font_cache import default_font, load_font

        self.assertIs(load_font(None, 20), default_font())
        self.assertIs(load_font("", 20), default_font())
        self.assertIs(load_font("/no/such/font.ttf", 20), default_font())

    def test_truetype_raises_oserror_like_pillow(self) -> None:
        from pigeon.font_cache import truetype

        with self.assertRaises(OSError):
            truetype("/no/such/font.ttf", 20)


if __name__ == "__main__":
    unittest.main()
