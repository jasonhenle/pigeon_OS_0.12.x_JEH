"""Zone layout selection extracted from view_circles."""

from __future__ import annotations

import os
import sys
import unittest

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import np_zone_layout as lay  # noqa: E402
from pigeon.widgets import view_circles as vc  # noqa: E402

SAVED = ("tt_countdown_16x9", "", "volume", "cast_info", "status_bar")


def _saved(_mode=None):
    return SAVED


class PredicateTests(unittest.TestCase):
    def test_zone_clock_hides_header(self) -> None:
        self.assertTrue(lay.zone_clock_hides_header(("clock", "", "", "", "")))
        self.assertTrue(lay.zone_clock_hides_header(("", "clock_16x9")))
        self.assertFalse(lay.zone_clock_hides_header(SAVED))
        self.assertFalse(lay.zone_clock_hides_header(None))

    def test_layout_is_fullscreen_clock(self) -> None:
        self.assertTrue(lay.layout_is_fullscreen_clock(("", "", "", "", "")))
        self.assertTrue(lay.layout_is_fullscreen_clock(("clock", "", "", "", "")))
        self.assertFalse(lay.layout_is_fullscreen_clock(("clock", "", "volume", "", "")))

    def test_connection_fallbacks_zone3(self) -> None:
        kw = dict(has_title=True, has_audio=True, has_position=True, has_info=True, loading_cast=False)
        z = lay.apply_connection_fallbacks(SAVED, has_receiver=False, **kw)
        self.assertEqual(z[2], "clock")
        z = lay.apply_connection_fallbacks(
            ("", "", "cast_info", "", ""), has_receiver=True, **{**kw, "has_info": False}
        )
        self.assertEqual(z[2], "volume")


class EffectiveZoneTests(unittest.TestCase):
    def test_idle_keeps_only_clock(self) -> None:
        got = lay.effective_zone_widgets(
            has_position=False, content_active=False,
            zone_widgets=("clock", "", "volume", "cast_info", "status_bar"),
            saved_zone_widgets=_saved,
        )
        self.assertEqual(got, ("clock", "", "", "", ""))

    def test_saved_lookup_is_used_when_no_zone_widgets(self) -> None:
        calls = []

        def saved(mode):
            calls.append(mode)
            return SAVED

        got = lay.effective_zone_widgets(has_position=True, content_mode="music", saved_zone_widgets=saved)
        self.assertEqual(calls, ["music"])
        self.assertEqual(len(got), 5)

    def test_no_duplicate_widgets(self) -> None:
        got = lay.effective_zone_widgets(
            has_position=True, cast_count=6,
            zone_widgets=("volume", "volume", "volume", "cast_info", "status_bar"),
            has_volume=True, saved_zone_widgets=_saved,
        )
        self.assertEqual(got.count("volume"), 1)


class ViewCirclesBindingTests(unittest.TestCase):
    def test_aliases_are_same_objects(self) -> None:
        self.assertIs(vc._layout_is_fullscreen_clock, lay.layout_is_fullscreen_clock)
        self.assertIs(vc._zone_clock_hides_header, lay.zone_clock_hides_header)
        self.assertIs(vc._apply_connection_fallbacks, lay.apply_connection_fallbacks)

    def test_patching_vc_seam_still_reaches_effective_zone_widgets(self) -> None:
        saved = vc._default_zone_widget_assignments
        try:
            vc._default_zone_widget_assignments = lambda *a, **k: ("clock", "", "", "", "")
            got = vc._effective_zone_widgets(has_position=True, content_active=False)
        finally:
            vc._default_zone_widget_assignments = saved
        self.assertEqual(got, ("clock", "", "", "", ""))


if __name__ == "__main__":
    unittest.main()
