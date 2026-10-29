"""Rounded display corners: the last step of every displayed frame."""

from __future__ import annotations

import os
import sys
import unittest

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.widgets import options_settings as opts  # noqa: E402

R = opts.DISPLAY_CORNER_RADIUS_PX


class DisplayCornerTests(unittest.TestCase):
    def _frame(self) -> np.ndarray:
        return np.full((800, 1280, 3), 200, np.uint8)

    def test_corner_pixels_go_black_and_the_middle_is_untouched(self) -> None:
        out = opts.apply_display_corners_bgr(self._frame())
        for y, x in ((0, 0), (0, 1279), (799, 0), (799, 1279)):
            self.assertEqual(int(out[y, x].max()), 0, (y, x))
        self.assertTrue((out[R:-R, :] == 200).all())
        self.assertTrue((out[:, R:-R] == 200).all())

    def test_edges_stay_lit_past_the_curve(self) -> None:
        out = opts.apply_display_corners_bgr(self._frame())
        self.assertEqual(int(out[0, R].max()), 200)
        self.assertEqual(int(out[R, 0].max()), 200)

    def test_curve_is_anti_aliased(self) -> None:
        out = opts.apply_display_corners_bgr(self._frame())
        diag = [int(out[i, i, 0]) for i in range(R)]
        self.assertTrue(any(0 < v < 200 for v in diag), diag)

    def test_corners_are_symmetric(self) -> None:
        out = opts.apply_display_corners_bgr(self._frame())
        tl = out[:R, :R]
        self.assertTrue(np.array_equal(tl, out[:R, -R:][:, ::-1]))
        self.assertTrue(np.array_equal(tl, out[-R:, :R][::-1, :]))
        self.assertTrue(np.array_equal(tl, out[-R:, -R:][::-1, ::-1]))

    def test_input_frame_is_not_modified(self) -> None:
        # Callers pass cached pages; rounding them in place would darken the
        # anti-aliased edge a little more every frame.
        frame = self._frame()
        opts.apply_display_corners_bgr(frame)
        self.assertTrue((frame == 200).all())

    def test_runs_in_the_ui_look_path(self) -> None:
        out = opts.apply_ui_look_bgr(self._frame())
        self.assertEqual(int(out[0, 0].max()), 0)
        self.assertEqual(int(out[400, 640].max()), 200)

    def test_tiny_frames_are_left_alone(self) -> None:
        frame = np.full((10, 10, 3), 50, np.uint8)
        self.assertIs(opts.apply_display_corners_bgr(frame), frame)


if __name__ == "__main__":
    unittest.main()
