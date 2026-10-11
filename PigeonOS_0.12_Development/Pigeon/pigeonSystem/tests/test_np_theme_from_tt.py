"""Now-playing UI color: TMDb TT, then poster (album art in music), then the settings color — never the backdrop."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.widgets.view_circles import ViewCirclesWidget, np_theme_from_settings  # noqa: E402

_ASSETS = Path(__file__).resolve().parents[2] / "pigeonAssets"


def _logo(bgr: tuple[int, int, int]) -> np.ndarray:
    tt = np.zeros((120, 400, 4), dtype=np.uint8)
    tt[20:100, 20:380, :3] = bgr
    tt[20:100, 20:380, 3] = 255
    return tt


def _widget(**state) -> ViewCirclesWidget:
    w = ViewCirclesWidget(assets_dir=_ASSETS)
    w.update_state(
        progress=0.3,
        elapsed_text="0:10:00",
        remaining_text="0:40:00",
        volume_text="-25.0 dB",
        content_active=True,
        content_mode="video",
        **state,
    )
    return w


class NpThemeFromTtTests(unittest.TestCase):
    def test_colored_tt_sets_ui_color(self) -> None:
        # Red logotype on a green backdrop: the UI turns red, not green.
        w = _widget(tt_bgra=_logo((20, 20, 220)))
        w.set_backdrop_bgr(np.full((90, 160, 3), (0, 200, 0), dtype=np.uint8))
        b, g, r = w._effective_np_theme().ui_bgr
        self.assertGreater(r, 150)
        self.assertLess(g, 110)

    def test_white_tt_falls_back_to_poster(self) -> None:
        # White logotype, blue poster, green backdrop: the poster wins.
        w = _widget(
            tt_bgra=_logo((255, 255, 255)),
            poster_bgra=np.full((90, 60, 3), (220, 60, 20), dtype=np.uint8),
        )
        w.set_backdrop_bgr(np.full((90, 160, 3), (0, 200, 0), dtype=np.uint8))
        b, g, r = w._effective_np_theme().ui_bgr
        self.assertGreater(b, 150)
        self.assertLess(g, 110)

    def test_colorless_art_keeps_settings_color(self) -> None:
        w = _widget(
            tt_bgra=_logo((255, 255, 255)),
            poster_bgra=np.full((90, 60, 3), 90, dtype=np.uint8),
        )
        w.set_backdrop_bgr(np.full((90, 160, 3), (0, 200, 0), dtype=np.uint8))
        self.assertEqual(w._effective_np_theme().ui_hex, np_theme_from_settings().ui_hex)

    def test_settings_color_holds_while_searching_tmdb(self) -> None:
        # A red TT is on screen from the last title; the new one is still being
        # searched, so the settings color holds until the art arrives.
        w = _widget(tt_bgra=_logo((20, 20, 220)))
        w.set_backdrop_bgr(np.full((90, 160, 3), (0, 200, 0), dtype=np.uint8))
        self.assertNotEqual(w._effective_np_theme().ui_hex, np_theme_from_settings().ui_hex)
        w.update_state(
            progress=0.3,
            elapsed_text="0:10:00",
            remaining_text="0:40:00",
            volume_text="-25.0 dB",
            content_active=True,
            content_mode="video",
            searching=True,
        )
        self.assertEqual(w._effective_np_theme().ui_hex, np_theme_from_settings().ui_hex)
        w.update_state(
            progress=0.3,
            elapsed_text="0:10:00",
            remaining_text="0:40:00",
            volume_text="-25.0 dB",
            content_active=True,
            content_mode="video",
            searching=False,
            tt_bgra=_logo((20, 20, 220)),
        )
        self.assertNotEqual(w._effective_np_theme().ui_hex, np_theme_from_settings().ui_hex)

    def _music(self, **state) -> ViewCirclesWidget:
        w = ViewCirclesWidget(assets_dir=_ASSETS)
        w.update_state(
            progress=0.3,
            elapsed_text="1:00",
            remaining_text="2:00",
            volume_text="-25.0 dB",
            content_active=True,
            content_mode="music",
            **state,
        )
        return w

    def test_music_album_art_sets_color(self) -> None:
        # Blue album art; a leftover red video TT is ignored in music.
        w = self._music(
            tt_bgra=_logo((20, 20, 220)),
            poster_bgra=np.full((90, 90, 3), (220, 60, 20), dtype=np.uint8),
        )
        b, g, r = w._effective_np_theme().ui_bgr
        self.assertGreater(b, 150)
        self.assertLess(r, 110)

    def test_colorless_album_art_keeps_settings_color(self) -> None:
        w = self._music(poster_bgra=np.full((90, 90, 3), 90, dtype=np.uint8))
        self.assertEqual(w._effective_np_theme().ui_hex, np_theme_from_settings().ui_hex)

if __name__ == "__main__":
    unittest.main()
