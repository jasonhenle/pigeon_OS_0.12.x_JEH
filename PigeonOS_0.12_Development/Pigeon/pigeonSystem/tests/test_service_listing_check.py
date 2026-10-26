import os
import unittest
from unittest import mock

from pigeon import tmdb_poster

DISNEY = frozenset({337})
HULU = frozenset({15})


class ListedOnlyElsewhereTests(unittest.TestCase):
    def _check(self, listed, wanted=DISNEY):
        with mock.patch.object(tmdb_poster, "_tmdb_watch_provider_ids", return_value=listed):
            return tmdb_poster._listed_only_elsewhere({"id": 1}, "tv", wanted)

    def test_rejects_when_listed_only_on_other_services(self):
        self.assertTrue(self._check(HULU))

    def test_accepts_when_listed_on_the_service(self):
        self.assertFalse(self._check(frozenset({337, 15})))

    def test_unknown_listing_never_rejects(self):
        self.assertFalse(self._check(None))
        self.assertFalse(self._check(frozenset()))

    def test_app_without_provider_ids_never_rejects(self):
        self.assertFalse(self._check(HULU, wanted=frozenset()))

    def test_env_switch_disables_the_check(self):
        with mock.patch.dict(os.environ, {"PIGEON_TMDB_SERVICE_CHECK": "off"}):
            self.assertFalse(self._check(HULU))


class RuntimeVouchesForServiceTests(unittest.TestCase):
    def test_exact_title_and_close_runtime_vouch(self):
        self.assertTrue(tmdb_poster._runtime_vouches_for_service(0.95, 5))

    def test_close_runtime_alone_does_not_vouch(self):
        self.assertFalse(tmdb_poster._runtime_vouches_for_service(0.95, 4))
        self.assertFalse(tmdb_poster._runtime_vouches_for_service(1.0, 2))

    def test_loose_or_unknown_runtime_does_not_vouch(self):
        self.assertFalse(tmdb_poster._runtime_vouches_for_service(0.85, 5))
        self.assertFalse(tmdb_poster._runtime_vouches_for_service(None, 5))


class RerankPrefersServiceTests(unittest.TestCase):
    def test_listed_title_beats_closer_runtime(self):
        disney_frozen = {"id": 1, "title": "Frozen"}
        horror_frozen = {"id": 2, "title": "Frozen"}
        scored = [(disney_frozen, (5, -6)), (horror_frozen, (5, -6))]
        trt = {1: 0.8, 2: 0.95}
        listed = {1: DISNEY, 2: None}
        with (
            mock.patch.object(tmdb_poster, "_PLAYER_DURATION_S", 6406.0),
            mock.patch.object(tmdb_poster, "enrich_item_runtime", side_effect=lambda it, k: it),
            mock.patch.object(tmdb_poster, "_trt_score_for_item", side_effect=lambda it: trt[it["id"]]),
            mock.patch.object(tmdb_poster, "_trt_rejects", return_value=False),
            mock.patch.object(tmdb_poster, "_tmdb_watch_provider_ids", side_effect=lambda k, i: listed[i]),
        ):
            pick = tmdb_poster._rerank_scored_by_trt(
                scored, media_kind="movie", title_pick=horror_frozen, watch_provider_ids=DISNEY
            )
        self.assertEqual(pick["id"], 1)


if __name__ == "__main__":
    unittest.main()
