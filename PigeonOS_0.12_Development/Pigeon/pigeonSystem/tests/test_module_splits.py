"""Compatibility of the large-module splits.

Each ``(old, new)`` pair says: everything defined at the top level of ``new`` was
extracted from ``old`` and must still be importable from it as the *same object*, so
existing ``from old import _private_name`` callers keep working.
"""

from __future__ import annotations

import ast
import importlib
import os
import sys
import unittest
from pathlib import Path

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

SPLITS = (
    ("pigeon.widgets.main_settings", "pigeon.widgets.settings_svg_tree"),
    ("pigeon.widgets.main_settings", "pigeon.widgets.settings_state"),
    ("pigeon.widgets.main_settings", "pigeon.widgets.settings_text_entry"),
    ("pigeon.widgets.main_settings", "pigeon.widgets.settings_search_overlays"),
    ("pigeon.widgets.main_settings", "pigeon.widgets.settings_container_background"),
    ("pigeon.widgets.main_settings", "pigeon.widgets.settings_paint"),
    ("pigeon.widgets.main_settings", "pigeon.widgets.settings_box_text_layout"),
    ("pigeon.widgets.main_settings", "pigeon.widgets.settings_scene"),
    ("pigeon.widgets.view_circles", "pigeon.widgets.view_circles_theme"),
    ("pigeon.widgets.view_circles", "pigeon.widgets.view_circles_draw"),
    ("pigeon.widgets.view_circles", "pigeon.widgets.view_circles_svg"),
    ("pigeon.widgets.view_circles", "pigeon.widgets.view_circles_text"),
    ("pigeon.widgets.view_circles", "pigeon.widgets.view_circles_raster"),
    ("pigeon.widgets.view_circles", "pigeon.widgets.view_circles_state"),
    ("pigeon.widgets.view_circles", "pigeon.widgets.view_circles_timecode"),
    ("pigeon.widgets.preferences_settings", "pigeon.np_zone_config"),
    ("pigeon.widgets.preferences_settings", "pigeon.widgets.preferences_overlays"),
    ("pigeon.tmdb_poster", "pigeon.tmdb_query"),
    ("pigeon.tmdb_poster", "pigeon.tmdb_match_mode"),
    ("pigeon.tmdb_poster", "pigeon.tmdb_match_rank"),
    ("pigeon.tmdb_poster", "pigeon.tmdb_http"),
    ("pigeon.tmdb_poster", "pigeon.tmdb_cast_cache"),
    ("pigeon.tmdb_poster", "pigeon.tmdb_streaming"),
    ("pigeon.core.settings_ui", "pigeon.core.settings_devices_panel"),
    ("pigeon.core.settings_ui", "pigeon.core.settings_updates"),
    ("pigeon.core.settings_ui", "pigeon.core.settings_locations"),
    ("pigeon.core.settings_ui", "pigeon.core.settings_reset"),
)


# Rebound at runtime by ``toggle_tmdb_match_mode``: a re-exported copy would go stale, so
# the mode state lives only in ``tmdb_match_mode`` (nothing outside read it directly).
NOT_RE_EXPORTED = {"_tmdb_match_runtime_forgiving"}


def _defined_names(module) -> list[str]:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names: list[str] = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            names.append(n.name)
        elif isinstance(n, ast.Assign):
            names += [t.id for t in n.targets if isinstance(t, ast.Name)]
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.append(n.target.id)
    return names


class ReExportTests(unittest.TestCase):
    def test_old_module_exposes_the_same_objects(self) -> None:
        for old_name, new_name in SPLITS:
            old, new = importlib.import_module(old_name), importlib.import_module(new_name)
            with self.subTest(old=old_name, new=new_name):
                names = _defined_names(new)
                self.assertTrue(names, "split module defines nothing")
                for name in (n for n in names if n not in NOT_RE_EXPORTED):
                    self.assertTrue(hasattr(old, name), f"{old_name} lost {name}")
                    self.assertIs(getattr(old, name), getattr(new, name), name)

    def test_split_modules_do_not_import_their_origin_at_module_level(self) -> None:
        # A module-level import back into the origin would be an import cycle.
        for old_name, new_name in SPLITS:
            new = importlib.import_module(new_name)
            tree = ast.parse(Path(new.__file__).read_text(encoding="utf-8"))
            for n in tree.body:
                if isinstance(n, ast.ImportFrom):
                    with self.subTest(new=new_name):
                        self.assertNotEqual(n.module, old_name)


class SettingsStateTests(unittest.TestCase):
    def test_location_helpers(self) -> None:
        from pigeon.widgets.settings_state import location_name_is_default, location_room_label

        self.assertTrue(location_name_is_default("Room 2"))
        self.assertFalse(location_name_is_default("Den"))
        self.assertIsInstance(location_room_label("Den"), str)

    def test_state_constructs_with_defaults(self) -> None:
        from pigeon.widgets.settings_state import MainSettingsFocus, MainSettingsState, SettingsTheme

        st = MainSettingsState()
        self.assertIsInstance(st, MainSettingsState)
        self.assertTrue(len(list(MainSettingsFocus)) > 0)
        self.assertTrue(SettingsTheme().selected)


class ViewCirclesStateTests(unittest.TestCase):
    def test_content_mode_normalization(self) -> None:
        from pigeon.widgets.view_circles_state import ViewCirclesState, _normalize_content_mode

        self.assertEqual(_normalize_content_mode(" MUSIC "), "music")
        self.assertEqual(_normalize_content_mode("anything"), "video")
        self.assertEqual(ViewCirclesState().content_mode, "video")


class TmdbMatchRankTests(unittest.TestCase):
    def test_subsequence_and_titles(self) -> None:
        from pigeon.tmdb_match_rank import _result_titles, _tokens_subsequence

        # Despite the name: needle must appear as *consecutive* tokens.
        self.assertTrue(_tokens_subsequence(["b", "c"], ["a", "b", "c"]))
        self.assertFalse(_tokens_subsequence(["a", "c"], ["a", "b", "c"]))
        self.assertTrue(_tokens_subsequence([], ["a"]))
        self.assertIn("Dune", _result_titles({"title": "Dune"}))


class TmdbCastCacheTests(unittest.TestCase):
    def test_cache_round_trip_without_touching_disk(self) -> None:
        from unittest import mock

        from pigeon import tmdb_cast_cache as cc

        with mock.patch.object(cc, "_save_cast_to_disk"), mock.patch.object(
            cc, "_load_cast_from_disk", return_value=[]
        ):
            cc.clear_cached_tmdb_cast()
            cc._CAST_CACHE["k"] = [("Actor", "Role")]
            self.assertEqual(cc.get_cached_tmdb_cast("k"), [("Actor", "Role")])
            cc.clear_cached_tmdb_cast("k")
            self.assertNotIn("k", cc._CAST_CACHE)


if __name__ == "__main__":
    unittest.main()
