"""Zone 11 now-playing layout: corner clock / volume / app id, strip, status bar."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.design import DESIGN_H, DESIGN_W  # noqa: E402
from pigeon.widgets import view_circles as vc  # noqa: E402

ASSETS = Path(__file__).resolve().parents[2] / "pigeonAssets"
_ZONE11 = ("tt_zone11", "", "", "zone11_info", "status_bar")


class Zone11LayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = (vc._default_zone_widget_assignments, vc._header_clock_enabled)
        vc._default_zone_widget_assignments = lambda *a, **k: _ZONE11  # type: ignore[assignment]
        vc._header_clock_enabled = lambda: True  # type: ignore[assignment]

    def tearDown(self) -> None:
        vc._default_zone_widget_assignments, vc._header_clock_enabled = self._saved  # type: ignore[assignment]

    def _widget(self) -> vc.ViewCirclesWidget:
        import cv2

        w = vc.ViewCirclesWidget(assets_dir=ASSETS)
        tt = np.zeros((160, 900, 4), np.uint8)
        cv2.putText(tt, "TITLE", (10, 120), cv2.FONT_HERSHEY_DUPLEX, 4, (255, 255, 255, 255), 8)
        w.update_state(
            progress=0.4,
            elapsed_text="0:41:12",
            remaining_text="1:12:30",
            volume_text="-22.5 dB",
            incoming_audio="DOLBY",
            playback_config="X",
            has_now_playing=True,
            has_position=True,
            content_active=True,
            paused=False,
            service_name="peacock",
            content_mode="video",
            tt_bgra=tt,
            tt_title="Title",
            receiver_name="DENON",
            receiver_input="APPLE TV",
            has_receiver=True,
        )
        return w

    def _frame(self, w: vc.ViewCirclesWidget) -> np.ndarray:
        canvas = np.zeros((DESIGN_H, DESIGN_W, 3), np.uint8)
        w.render(canvas)
        return canvas

    @staticmethod
    def _ink(frame: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
        reg = frame[y0:y1, x0:x1].astype(int)
        return reg.max(axis=2) > 90

    def _cols(self, mask: np.ndarray, x0: int) -> tuple[int, int]:
        xs = np.where(mask.any(axis=0))[0]
        return int(xs.min()) + x0, int(xs.max()) + x0

    def test_clock_top_center_volume_top_right_labels_top_left(self) -> None:
        frame = self._frame(self._widget())
        clock = self._ink(frame, 470, 0, 930, 140)
        vol = self._ink(frame, 930, 0, DESIGN_W, 140)
        labels = self._ink(frame, 0, 0, 470, 140)
        self.assertTrue(clock.any(), "clock missing top-center")
        self.assertTrue(vol.any(), "volume missing top-right")
        self.assertTrue(labels.any(), "labels missing top-left")
        cx0, cx1 = self._cols(clock, 470)
        self.assertLess(abs((cx0 + cx1) / 2.0 - DESIGN_W / 2.0), 20)
        _, vx1 = self._cols(vol, 930)
        self.assertGreater(vx1, DESIGN_W - 80)
        self.assertLess(vx1, DESIGN_W - 46)  # padded in from the zone edge

    def test_clock_and_volume_are_the_same_size(self) -> None:
        frame = self._frame(self._widget())
        ch = np.where(self._ink(frame, 470, 0, 930, 140).any(axis=1))[0]
        vh = np.where(self._ink(frame, 930, 0, DESIGN_W, 140).any(axis=1))[0]
        self.assertLessEqual(abs(int(ch.max() - ch.min()) - int(vh.max() - vh.min())), 12)
        self.assertLessEqual(abs(int(ch.min()) - int(vh.min())), 4)  # shared top

    def test_label_stack_is_comparable_in_height_to_the_clock(self) -> None:
        frame = self._frame(self._widget())
        labels = np.where(self._ink(frame, 0, 0, 470, 140).any(axis=1))[0]
        clock = np.where(self._ink(frame, 470, 0, 930, 140).any(axis=1))[0]
        lh, ch = int(labels.max() - labels.min()), int(clock.max() - clock.min())
        self.assertLess(abs(lh - ch), ch * 0.25)
        self.assertLessEqual(abs(int(labels.min()) - int(clock.min())), 6)

    def test_volume_is_enlarged_alone_top_right(self) -> None:
        frame = self._frame(self._widget())
        vol = self._ink(frame, 930, 0, DESIGN_W, 200)
        ys = np.where(vol.any(axis=1))[0]
        self.assertGreater(int(ys.max() - ys.min()), 60)

    def test_volume_readout_has_no_db_unit(self) -> None:
        frame = self._frame(self._widget())
        vol = self._ink(frame, 930, 0, DESIGN_W, 200)
        # "-22.5" alone is ~345 px wide at this size; with " DB" it was ~420.
        x0, x1 = self._cols(vol, 930)
        self.assertLess(x1 - x0, 380)

    def test_art_top_leaves_room_for_the_volume(self) -> None:
        import cv2

        w = self._widget()
        tt = np.zeros((600, 400, 4), np.uint8)
        cv2.rectangle(tt, (0, 0), (399, 599), (200, 120, 60, 255), -1)
        w.update_state(
            progress=0.4,
            elapsed_text="0:41:12",
            remaining_text="1:12:30",
            volume_text="-22.5 dB",
            tt_bgra=tt,
            tt_title="x",
        )
        frame = self._frame(w)
        vol = self._ink(frame, 930, 0, DESIGN_W, 200)
        vol_bottom = int(np.where(vol.any(axis=1))[0].max())
        art = frame[:, 300:900].astype(int)
        colored = (art[:, :, 0] - art[:, :, 2]) > 60  # blue-ish art, BGR
        art_top = int(np.where(colored[:500].any(axis=1))[0].min())
        self.assertGreaterEqual(art_top, vol_bottom + 10)  # padding below the header text

    def _widget_at(self, progress: float, service: str = "peacock") -> vc.ViewCirclesWidget:
        w = self._widget()
        w.update_state(
            progress=progress,
            elapsed_text="0:41:12",
            remaining_text="1:12:30",
            volume_text="-22.5 dB",
            has_now_playing=True,
            has_position=True,
            content_active=True,
            service_name=service,
            content_mode="video",
            receiver_input="APPLE TV",
            has_receiver=True,
        )
        return w

    def _elapsed_cols(self, frame: np.ndarray) -> tuple[int, int] | None:
        # Gray ink (not the UI-colored TRT) in the strip's left/middle, above the bar.
        reg = frame[540:640, 60:870].astype(int)
        gray = (reg.max(axis=2) > 90) & ((reg.max(axis=2) - reg.min(axis=2)) < 25)
        if not gray.any():
            return None
        xs = np.where(gray.any(axis=0))[0]
        return int(xs.min()) + 60, int(xs.max()) + 60

    def test_elapsed_rides_the_playhead_and_fades_before_the_trt(self) -> None:
        early = self._elapsed_cols(self._frame(self._widget_at(0.10)))
        mid = self._elapsed_cols(self._frame(self._widget_at(0.45)))
        self.assertIsNotNone(early)
        self.assertIsNotNone(mid)
        assert early is not None and mid is not None
        self.assertGreater(mid[0], early[0] + 200)  # moved right with the bar
        # Near the end it would collide with the TRT: gone.
        self.assertIsNone(self._elapsed_cols(self._frame(self._widget_at(0.97))))

    def test_elapsed_uses_the_header_gray(self) -> None:
        frame = self._frame(self._widget_at(0.30))
        vol = frame[0:140, 930:DESIGN_W].astype(int)  # volume readout
        el = frame[540:640, 60:870].astype(int)
        vol_mask = vol.max(axis=2) > 90
        el_mask = (el.max(axis=2) > 90) & ((el.max(axis=2) - el.min(axis=2)) < 25)
        self.assertTrue(vol_mask.any() and el_mask.any())
        self.assertLessEqual(abs(int(vol[vol_mask].max()) - int(el[el_mask].max())), 12)

    def test_input_id_top_left_and_app_id_under_status_bar(self) -> None:
        def top_left_rows(frame: np.ndarray) -> list[int]:
            band = self._ink(frame, 0, 0, 470, 150)
            return [int(y) for y in np.where(band.any(axis=1))[0]]

        with_app = self._frame(self._widget_at(0.3, "peacock"))
        no_app = self._frame(self._widget_at(0.3, ""))
        rows = top_left_rows(with_app)
        self.assertTrue(rows, "input id missing top-left")
        # Single line (no stacked app id), at the clock's top and size.
        clock = np.where(self._ink(with_app, 470, 0, 930, 140).any(axis=1))[0]
        self.assertLessEqual(abs(rows[0] - int(clock.min())), 4)
        self.assertLess(abs((rows[-1] - rows[0]) - int(clock.max() - clock.min())), 12)
        self.assertEqual(top_left_rows(no_app), rows)
        # App id sits just under the status bar, left-aligned to it; gone when unset.
        under = self._ink(with_app, 40, 716, DESIGN_W, 790)
        self.assertTrue(under.any(), "app id missing under the status bar")
        self.assertFalse(self._ink(no_app, 40, 716, DESIGN_W, 790).any())

    def _loading_widget(self) -> vc.ViewCirclesWidget:
        w = self._widget()
        w._state.searching = True
        w._tt_bgra = None
        return w

    def test_loading_shows_header_and_a_shimmering_status_bar_only(self) -> None:
        w = self._loading_widget()
        canvas = np.zeros((DESIGN_H, DESIGN_W, 3), np.uint8)
        w.render(canvas)
        self.assertEqual(w._shimmer_rects, [])  # no skeleton boxes
        bar = w._loading_bar_rect()
        self.assertIsNotNone(bar)
        assert bar is not None
        bx, by, bw, bh, _r = bar
        self.assertTrue(self._ink(canvas, 0, 0, DESIGN_W, 140).any(), "header missing")
        self.assertFalse(self._ink(canvas, 0, 160, DESIGN_W, by - 90).any(), "middle not empty")
        first = canvas[by : by + bh, bx : bx + bw].copy()
        w._shimmer_phase = lambda: 0.9  # type: ignore[method-assign]
        w.render(canvas)
        self.assertFalse(np.array_equal(first, canvas[by : by + bh, bx : bx + bw]))

    def test_reveal_wipes_left_to_right_then_settles(self) -> None:
        import time

        w = self._widget()
        tt = w._tt_bgra
        w._state.searching = True
        w._tt_bgra = None
        canvas = np.zeros((DESIGN_H, DESIGN_W, 3), np.uint8)
        w.render(canvas)
        w.update_state(
            progress=0.4, elapsed_text="0:41:12", remaining_text="1:12:30",
            volume_text="-22.5 dB", incoming_audio="DOLBY", playback_config="X",
            has_now_playing=True, has_position=True, content_active=True,
            paused=False, service_name="peacock", content_mode="video",
            tt_bgra=tt, tt_title="Title", receiver_name="DENON",
            receiver_input="APPLE TV", has_receiver=True, searching=False,
        )
        self.assertTrue(w.reveal_active())
        w._reveal_t0 = time.monotonic() - 0.15
        w.render(canvas)
        title = self._ink(canvas, 0, 200, DESIGN_W, 360)
        self.assertTrue(title[:, :300].any(), "left side should be revealed")
        w._reveal_t0 = time.monotonic() - 1.0
        w.render(canvas)
        self.assertFalse(w.reveal_active())

    def test_volume_adjustment_never_brings_up_zone3_volume(self) -> None:
        w = self._widget()
        before = w._assignments()
        w.note_volume_adjustment()
        self.assertTrue(w.volume_takeover_active())
        self.assertEqual(w._assignments(), before)
        self.assertNotIn("volume", w._assignments())


class ArtworkBackdropTests(unittest.TestCase):
    def test_artwork_backdrop_is_less_dim_than_before(self) -> None:
        self.assertGreaterEqual(vc._ARTWORK_BG_OPACITY, 0.35)


if __name__ == "__main__":
    unittest.main()
