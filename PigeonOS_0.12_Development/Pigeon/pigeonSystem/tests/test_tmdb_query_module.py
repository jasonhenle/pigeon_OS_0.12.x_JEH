"""tmdb_query / tmdb_match_mode extracted from tmdb_poster."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import tmdb_match_mode as mode  # noqa: E402
from pigeon import tmdb_poster as poster  # noqa: E402
from pigeon import tmdb_query as q  # noqa: E402


class QueryRuleTests(unittest.TestCase):
    def test_year_and_parenthetical(self) -> None:
        self.assertEqual(q.split_query_and_year("Dune (2021)"), ("Dune", 2021))
        self.assertEqual(q.strip_trailing_parenthetical("Show (US)"), "Show")

    def test_norm_query(self) -> None:
        self.assertEqual(q._norm_query("The  Office: Pilot!"), "the office pilot")

    def test_degenerate(self) -> None:
        self.assertTrue(q.is_degenerate_tmdb_query(""))
        self.assertFalse(q.is_degenerate_tmdb_query("Dune"))

    def test_colon_episode_splits_to_show(self) -> None:
        self.assertEqual(q.refine_tmdb_search_query("Severance: Hello, Ms. Cobel"), "Severance")

    def test_canonical_short_show(self) -> None:
        self.assertEqual(q.canonical_tv_display_name_for_search_query("snl"), "Saturday Night Live")

    def test_unicode_dash_normalized(self) -> None:
        self.assertEqual(q._normalize_unicode_dashes_for_episode_titles("A – B"), "A - B")


class MatchModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = mode._tmdb_match_runtime_forgiving
        mode._tmdb_match_runtime_forgiving = None

    def tearDown(self) -> None:
        mode._tmdb_match_runtime_forgiving = self._saved

    def test_env_and_override(self) -> None:
        with mock.patch.dict(os.environ, {"PIGEON_TMDB_MATCH_MODE": "forgiving"}):
            self.assertTrue(mode.tmdb_match_forgiving())
            self.assertFalse(mode.tmdb_match_forgiving(override=False))
        with mock.patch.dict(os.environ, {"PIGEON_TMDB_MATCH_MODE": "literal"}):
            self.assertFalse(mode.tmdb_match_forgiving())

    def test_toggle_is_seen_through_tmdb_poster(self) -> None:
        with mock.patch.dict(os.environ, {"PIGEON_TMDB_MATCH_MODE": "literal"}):
            self.assertEqual(poster.toggle_tmdb_match_mode(), "forgiving")
            self.assertTrue(mode.tmdb_match_forgiving())
            self.assertTrue(poster.tmdb_match_forgiving())
            self.assertEqual(poster.toggle_tmdb_match_mode(), "literal")
            self.assertFalse(q.tmdb_match_forgiving())


class CompatTests(unittest.TestCase):
    def test_tmdb_poster_re_exports_same_objects(self) -> None:
        for name in (
            "_norm_query", "split_query_and_year", "strip_trailing_parenthetical",
            "is_degenerate_tmdb_query", "colon_prefix_show_query", "refine_tmdb_search_query",
            "resolve_tmdb_query_from_now_playing_fields", "equivalent_tmdb_search_queries",
            "_tmdb_query_variants", "_SHORT_SHOW_CANONICAL_QUERIES", "_sketch_show_dash_pair",
            "compound_title_streaming_series_fix", "canonical_tv_title_if_sketch_show_compound",
        ):
            self.assertIs(getattr(poster, name), getattr(q, name), name)
        self.assertIs(poster.tmdb_match_forgiving, mode.tmdb_match_forgiving)


if __name__ == "__main__":
    unittest.main()
