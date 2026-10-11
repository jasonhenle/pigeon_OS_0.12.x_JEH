"""TMDb match rules from real misses: long TV episodes, creator possessives, loose hits."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import accuracy_report as ar  # noqa: E402
from pigeon import tmdb_poster as tp  # noqa: E402


class TrtRejectTests(unittest.TestCase):
    def test_long_tv_episode_is_never_rejected(self) -> None:
        # IT: Welcome to Derry lists 54 min; a 1:17:42 episode must not drop it.
        derry = {"episode_run_time": [54]}
        self.assertFalse(tp._trt_rejects(4662.0, derry, "tv"))

    def test_movie_runtime_mismatch_still_rejects(self) -> None:
        self.assertTrue(tp._trt_rejects(4662.0, {"runtime": 180}, "movie"))
        self.assertFalse(tp._trt_rejects(8093.0, {"runtime": 135}, "movie"))


class CreatorPossessiveTests(unittest.TestCase):
    def test_creator_possessive_scores_bare_title_at_tier_4(self) -> None:
        tier, _ = tp._match_rank("Stephen King's It", {"name": "It"})
        self.assertEqual(tier, 4)
        self.assertGreaterEqual(tier, tp._literal_min_acceptable_tier("Stephen King's It"))

    def test_exact_full_title_still_wins(self) -> None:
        full = tp._match_rank("Stephen King's It", {"name": "Stephen King's It"})
        bare = tp._match_rank("Stephen King's It", {"name": "It"})
        self.assertGreater(full, bare)

    def test_one_word_possessive_titles_are_left_alone(self) -> None:
        for q in ("Grey's Anatomy", "Schitt's Creek", "Bob's Burgers"):
            self.assertIsNone(tp._creator_possessive_title(q), q)
        tier, _ = tp._match_rank("Grey's Anatomy", {"name": "Anatomy"})
        self.assertLess(tier, tp._literal_min_acceptable_tier("Grey's Anatomy"))

    def test_unrelated_title_is_below_threshold(self) -> None:
        q = "IT: Welcome to Derry"
        tier, _ = tp._match_rank(q, {"name": "It Sounds Incredible"})
        self.assertLess(tier, tp._literal_min_acceptable_tier(q))


class LooseRejectReportTests(unittest.TestCase):
    def test_loose_rejection_is_reported_as_such(self) -> None:
        sent = []
        msg = "Loose match rejected: 'It Sounds Incredible' (tier 0) for 'IT: Welcome to Derry'"
        with mock.patch.object(ar, "_enqueue", lambda k, p: sent.append(p)):
            ar.report_fetch_event(
                metadata={"title": "Winter Fire"},
                streaming_service="Max",
                query_in="IT: Welcome to Derry",
                refined_query="IT: Welcome to Derry",
                used_query="IT: Welcome to Derry",
                prefer="tv",
                trigger="auto",
                ok=False,
                message=msg,
                match_tier=0,
                tier_ok=False,
                attempts=[{"query": "IT: Welcome to Derry", "outcome": "match",
                           "display_title": "It Sounds Incredible"}],
                tt_source="text_fallback",
                backdrop_source="none",
            )
        p = sent[0]
        self.assertEqual(p["outcome"], "loose_match_rejected")
        self.assertEqual(p["failure"], msg)
        self.assertEqual(p["assumed_title"], "")
        self.assertIsNone(p["poster_path"])


if __name__ == "__main__":
    unittest.main()
