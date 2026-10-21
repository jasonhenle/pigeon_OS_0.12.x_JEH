"""Now-playing zone widget config extracted from preferences_settings."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import np_zone_config as cfg  # noqa: E402
from pigeon.widgets import preferences_settings as prefs  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_none_gives_defaults(self) -> None:
        self.assertEqual(cfg._normalize_zone_widgets(None), cfg.DEFAULT_ZONE_WIDGETS)

    def test_unknown_widget_falls_back_to_zone_default(self) -> None:
        out = cfg._normalize_zone_widgets({3: "not_a_widget"})
        self.assertEqual(out[2], cfg.DEFAULT_ZONE_WIDGETS[2])

    def test_every_default_is_in_catalog_or_off(self) -> None:
        for defaults in (cfg.DEFAULT_ZONE_WIDGETS, cfg.DEFAULT_MUSIC_ZONE_WIDGETS):
            norm = cfg._normalize_zone_widgets(defaults, defaults=defaults)
            self.assertEqual(norm, defaults)

    def test_mode_selects_defaults_and_state_key(self) -> None:
        self.assertIs(cfg._defaults_for_mode("music"), cfg.DEFAULT_MUSIC_ZONE_WIDGETS)
        self.assertIs(cfg._defaults_for_mode("video"), cfg.DEFAULT_ZONE_WIDGETS)
        self.assertEqual(cfg._state_key_for_mode("MUSIC"), "now_playing_zone_widgets_music")
        self.assertEqual(cfg._state_key_for_mode(None), "now_playing_zone_widgets")


class ZoneDateAlignTests(unittest.TestCase):
    def test_alignment_by_poster_zones(self) -> None:
        self.assertEqual(cfg.zone0_date_align(), "left")
        self.assertEqual(cfg.zone0_date_align({1: "poster"}), "center")
        self.assertEqual(cfg.zone0_date_align({1: "poster", 2: "poster"}), "right")
        self.assertIsNone(cfg.zone0_date_align({1: "poster", 2: "poster", 3: "poster"}))


class PersistenceTests(unittest.TestCase):
    def test_no_persist_does_not_touch_app_state(self) -> None:
        with mock.patch("pigeon.app_state.write_app_state") as w:
            cfg.write_now_playing_zone_widgets(cfg.DEFAULT_ZONE_WIDGETS, persist=False)
            cfg.write_np_header_clock(False, persist=False)
        w.assert_not_called()

    def test_header_clock_defaults_on(self) -> None:
        with mock.patch("pigeon.app_state.read_app_state", return_value={}):
            self.assertTrue(cfg.read_np_header_clock())
        with mock.patch("pigeon.app_state.read_app_state", return_value={"np_header_clock": False}):
            self.assertFalse(cfg.read_np_header_clock())


class CompatTests(unittest.TestCase):
    def test_preferences_settings_re_exports_same_objects(self) -> None:
        for name in (
            "DEFAULT_ZONE_WIDGETS", "DEFAULT_MUSIC_ZONE_WIDGETS", "ZONE_WIDGET_CATALOG",
            "NP_ZONE_LAYOUT_GENERATION", "_normalize_zone_widgets", "zone0_date_align",
            "read_now_playing_zone_widgets", "write_now_playing_zone_widgets",
            "read_np_header_clock", "write_np_header_clock", "ensure_now_playing_layout_defaults",
        ):
            self.assertIs(getattr(prefs, name), getattr(cfg, name), name)

    def test_focus_ring_still_uses_catalog(self) -> None:
        ring = prefs.preferences_widget_focus_ring(1)
        self.assertEqual(ring[0], "exit")
        self.assertTrue(set(ring[1:]) <= set(cfg.ZONE_WIDGET_CATALOG[1]))


if __name__ == "__main__":
    unittest.main()
