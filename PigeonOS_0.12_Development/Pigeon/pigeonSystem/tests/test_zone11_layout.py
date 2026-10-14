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

    def test_clock_top_left_and_volume_top_right(self) -> None:
        frame = self._frame(self._widget())
        left = self._ink(frame, 0, 0, DESIGN_W // 2, 70)
        right = self._ink(frame, DESIGN_W // 2, 0, DESIGN_W, 70)
        self.assertTrue(left.any(), "clock missing top-left")
        self.assertTrue(right.any(), "volume missing top-right")
        lx0, _ = self._cols(left, 0)
        _, rx1 = self._cols(right, DESIGN_W // 2)
        self.assertLess(lx0, 80)
        self.assertGreater(rx1, DESIGN_W - 80)
        # The old center-ish clock slot is empty.
        mid = self._ink(frame, 400, 0, 900, 70)
        self.assertFalse(mid.any())

    def test_app_id_sits_under_the_volume(self) -> None:
        frame = self._frame(self._widget())
        vol = self._ink(frame, 900, 0, DESIGN_W, 66)
        app = self._ink(frame, 900, 70, DESIGN_W, 120)
        self.assertTrue(vol.any() and app.any())
        vy = np.where(vol.any(axis=1))[0].max()
        ay = np.where(app.any(axis=1))[0].min() + 70
        self.assertGreater(ay, vy)
        self.assertLess(ay - vy, 40)

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

    def test_elapsed_uses_the_volume_gray_and_size(self) -> None:
        frame = self._frame(self._widget_at(0.30))
        vol = frame[0:66, 900:DESIGN_W].astype(int)
        el = frame[540:640, 60:870].astype(int)
        vol_mask = vol.max(axis=2) > 90
        el_mask = (el.max(axis=2) > 90) & ((el.max(axis=2) - el.min(axis=2)) < 25)
        self.assertTrue(vol_mask.any() and el_mask.any())
        self.assertLessEqual(abs(int(vol[vol_mask].max()) - int(el[el_mask].max())), 12)
        vh = np.where(vol_mask.any(axis=1))[0]
        eh = np.where(el_mask.any(axis=1))[0]
        self.assertLessEqual(abs(int(vh.max() - vh.min()) - int(eh.max() - eh.min())), 4)

    def test_input_id_stacks_under_app_id_and_takes_its_place_when_missing(self) -> None:
        def rows(frame: np.ndarray) -> list[int]:
            reg = frame[66:200, 1000:DESIGN_W].astype(int)
            band = reg.max(axis=2) > 90
            ys = np.where(band.any(axis=1))[0]
            groups: list[int] = []
            prev = -10
            for y in ys:
                if y - prev > 3:
                    groups.append(int(y) + 66)
                prev = int(y)
            return groups

        both = rows(self._frame(self._widget_at(0.3, "peacock")))
        only_input = rows(self._frame(self._widget_at(0.3, "")))
        self.assertEqual(len(both), 2, both)  # app id, then input id
        self.assertEqual(len(only_input), 1, only_input)  # input id, no gap
        self.assertLessEqual(abs(only_input[0] - both[0]), 3)
        # Nothing is drawn under the status bar any more.
        self.assertFalse(self._ink(self._frame(self._widget_at(0.3)), 40, 716, DESIGN_W, 790).any())

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
