"""Pausesaver full-frame plate + zone-6 scale."""

from __future__ import annotations

import os
import sys
import unittest

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.design import DESIGN_H, DESIGN_W  # noqa: E402
from pigeon.np_layout import NOW_PLAYING_ZONES  # noqa: E402
from pigeon.paused_screen import (  # noqa: E402
    PAUSED_SCREEN_TEXT,
    compose_pausesaver_backdrop_bgr,
    compose_pausesaver_bgr,
    render_pausesaver_bgra,
    render_pausesaver_plate_bgra,
)


class PausesaverTests(unittest.TestCase):
    def test_full_frame_matches_design(self) -> None:
        backdrop = np.full((400, 700, 3), 80, dtype=np.uint8)
        frame = compose_pausesaver_bgr(DESIGN_W, DESIGN_H, backdrop)
        self.assertEqual(frame.shape, (DESIGN_H, DESIGN_W, 3))
        self.assertGreater(int(frame.max()), 0)

    def test_zone6_scale_fits(self) -> None:
        z = NOW_PLAYING_ZONES[6]
        backdrop = np.full((400, 700, 3), 90, dtype=np.uint8)
        patch = render_pausesaver_bgra(int(z.w), int(z.h), backdrop)
        self.assertEqual(patch.shape[1], int(round(z.w)))
        self.assertEqual(patch.shape[0], int(round(z.h)))
        self.assertEqual(patch.shape[2], 4)
        self.assertEqual(PAUSED_SCREEN_TEXT, "paused")

    def test_zone4_plate_fits_and_backdrop_has_no_plate(self) -> None:
        z4 = NOW_PLAYING_ZONES[4]
        plate = render_pausesaver_plate_bgra(int(round(z4.w)), int(round(z4.h)))
        self.assertEqual(plate.shape[1], int(round(z4.w)))
        self.assertEqual(plate.shape[0], int(round(z4.h)))
        self.assertEqual(plate.shape[2], 4)
        self.assertGreater(int(plate[:, :, 3].max()), 200)
        # Plate is centered, so the zone corners stay empty.
        self.assertLess(int(plate[2, 2, 3]), 16)
        self.assertLess(int(plate[2, -3, 3]), 16)
        backdrop = np.full((400, 700, 3), (40, 80, 160), dtype=np.uint8)
        bare = compose_pausesaver_backdrop_bgr(DESIGN_W, DESIGN_H, backdrop)
        with_plate = compose_pausesaver_bgr(DESIGN_W, DESIGN_H, backdrop)
        self.assertEqual(bare.shape, (DESIGN_H, DESIGN_W, 3))
        # Bottom-centered plate is only on the zone-6 source frame, not the backdrop.
        self.assertGreater(
            int(np.abs(with_plate.astype(np.int16) - bare.astype(np.int16)).sum()),
            0,
        )

    def test_empty_backdrop_update_keeps_last_still(self) -> None:
        from pigeon.paused_screen import (
            pausesaver_backdrop,
            pausesaver_has_art,
            set_pausesaver_backdrop,
        )

        still = np.full((20, 30, 3), 90, dtype=np.uint8)
        set_pausesaver_backdrop(still)
        self.assertTrue(pausesaver_has_art())
        set_pausesaver_backdrop(None)
        self.assertIsNotNone(pausesaver_backdrop())
        set_pausesaver_backdrop(None, clear=True)
        self.assertFalse(pausesaver_has_art())

    def test_black_or_other_title_still_is_not_art(self) -> None:
        from pigeon.paused_screen import (
            pausesaver_art_usable,
            pausesaver_has_art,
            set_pausesaver_backdrop,
        )

        set_pausesaver_backdrop(None, clear=True)
        self.assertFalse(pausesaver_art_usable(None))
        self.assertFalse(pausesaver_art_usable(np.zeros((20, 30, 3), dtype=np.uint8)))
        still = np.full((20, 30, 3), 90, dtype=np.uint8)
        self.assertTrue(pausesaver_art_usable(still))
        set_pausesaver_backdrop(still, content_key="movie")
        self.assertTrue(pausesaver_has_art())
        set_pausesaver_backdrop(None, content_key="youtube-clip")
        self.assertFalse(pausesaver_has_art())

    def test_same_pixels_keep_live_backdrop_identity(self) -> None:
        from pigeon.paused_screen import pausesaver_backdrop, set_pausesaver_backdrop

        set_pausesaver_backdrop(None, clear=True)
        still = np.full((20, 30, 3), 90, dtype=np.uint8)
        set_pausesaver_backdrop(still, content_key="song")
        first = pausesaver_backdrop()
        set_pausesaver_backdrop(still.copy(), content_key="song")
        self.assertIs(pausesaver_backdrop(), first)
        set_pausesaver_backdrop(None, clear=True)

    def test_status_bar_overlay_omits_paused_word(self) -> None:
        from pigeon.widgets.playback_overlay import AudioConfig

        overlay = AudioConfig(assets_dir="")
        overlay.overlay_flags["show_paused_row"] = True
        layers = [getattr(blit, "layer", "") for blit in overlay.design_blits()]
        self.assertNotIn("paused_row", layers)


if __name__ == "__main__":
    unittest.main()
