"""Apple TV duration vs TMDb runtime should steer title picks."""

from __future__ import annotations

import os
import sys
import unittest
import unittest.mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import tmdb_poster as tp  # noqa: E402
from pigeon.display_confidence import TRT_AGREE, TRT_REJECT  # noqa: E402


def _long_parody() -> dict:
    return {
        "id": 900002,
        "title": "It",
        "original_language": "en",
        "popularity": 90.0,
        "runtime": 105,
    }


def _parody() -> dict:
    return {
        "id": 900001,
        "title": "It",
        "original_language": "en",
        "popularity": 80.0,
        "runtime": 4,
    }


def _film_2017() -> dict:
    return {
        "id": 346364,
        "title": "It",
        "original_language": "en",
        "popularity": 60.0,
        "runtime": 135,
        "release_date": "2017-09-08",
    }


def _mini_1990() -> dict:
    return {
        "id": 19614,
        "name": "It",
        "original_language": "en",
        "popularity": 20.0,
        "episode_run_time": [96],
        "number_of_episodes": 2,
        "first_air_date": "1990-11-18",
    }


class TmdbRuntimeOptionsTests(unittest.TestCase):
    def test_miniseries_includes_episode_and_series_length(self) -> None:
        opts = tp.tmdb_runtime_seconds_options(_mini_1990())
        self.assertIn(96 * 60, opts)
        self.assertIn(192 * 60, opts)

    def test_movie_runtime_is_minutes(self) -> None:
        self.assertEqual(tp.tmdb_runtime_seconds_options(_film_2017()), [135 * 60])

    def test_seasons_count_as_series_length(self) -> None:
        item = {
            "name": "It",
            "episode_run_time": [105],
            "seasons": [
                {"season_number": 0, "episode_count": 3},
                {"season_number": 1, "episode_count": 2},
            ],
        }
        opts = tp.tmdb_runtime_seconds_options(item)
        self.assertIn(105 * 60, opts)
        self.assertIn(210 * 60, opts)


class TmdbTrtRerankTests(unittest.TestCase):
    def tearDown(self) -> None:
        tp.set_player_duration_hint(None)
        tp.remember_trt_comparison(player_s=None, tmdb_s=None, similarity=None)

    def test_rejects_parody_when_player_is_feature_length(self) -> None:
        with tp.player_duration_hint(192 * 60):
            picked = tp._best_from_results(
                "It",
                [_parody()],
                forgiving=False,
                media_kind="movie",
            )
        self.assertIsNone(picked)

    def test_prefers_closer_movie_runtime_over_parody(self) -> None:
        with tp.player_duration_hint(135 * 60):
            picked = tp._best_from_results(
                "It",
                [_parody(), _film_2017()],
                forgiving=False,
                media_kind="movie",
            )
        self.assertIsNotNone(picked)
        self.assertEqual(picked["id"], 346364)

    def test_1990_miniseries_beats_2017_and_parody_for_long_player(self) -> None:
        with tp.player_duration_hint(192 * 60):
            item, kind = tp._prefer_duration_match(_film_2017(), _mini_1990())
            item2, kind2 = tp._prefer_duration_match(_parody(), _mini_1990())
        self.assertEqual(kind, "tv")
        self.assertEqual(item["id"], 19614)
        self.assertEqual(kind2, "tv")
        self.assertEqual(item2["id"], 19614)

    def test_2017_film_wins_when_player_matches_135(self) -> None:
        with tp.player_duration_hint(135 * 60):
            item, kind = tp._prefer_duration_match(_film_2017(), _mini_1990())
        self.assertEqual(kind, "movie")
        self.assertEqual(item["id"], 346364)

    def test_one_episode_still_matches_miniseries(self) -> None:
        with tp.player_duration_hint(96 * 60):
            item, kind = tp._prefer_duration_match(_film_2017(), _mini_1990())
        self.assertEqual(kind, "tv")
        self.assertEqual(item["id"], 19614)

    def test_no_duration_keeps_movie_first(self) -> None:
        tp.set_player_duration_hint(None)
        item, kind = tp._prefer_duration_match(_film_2017(), _mini_1990())
        self.assertEqual(kind, "movie")
        self.assertEqual(item["id"], 346364)

    def test_music_track_can_still_match_short_tmdb(self) -> None:
        with tp.player_duration_hint(4 * 60):
            picked = tp._best_from_results(
                "It",
                [_parody(), _film_2017()],
                forgiving=False,
                media_kind="movie",
            )
        self.assertIsNotNone(picked)
        self.assertEqual(picked["id"], 900001)

    def test_forced_movie_is_dropped_on_hard_mismatch(self) -> None:
        with tp.player_duration_hint(192 * 60):
            self.assertIsNone(tp._forced_movie_survives_trt(_parody()))
            self.assertIsNone(tp._forced_movie_survives_trt(_long_parody()))
            self.assertIsNone(tp._forced_movie_survives_trt(_film_2017()))

    def test_hour_forty_five_loses_to_three_hour_miniseries(self) -> None:
        with tp.player_duration_hint(190 * 60):
            picked = tp._best_from_results(
                "It",
                [_long_parody()],
                forgiving=False,
                media_kind="movie",
            )
            item, kind = tp._prefer_duration_match(_long_parody(), _mini_1990())
        self.assertIsNone(picked)
        self.assertEqual(kind, "tv")
        self.assertEqual(item["id"], 19614)


class TmdbTrtSearchTests(unittest.TestCase):
    def tearDown(self) -> None:
        tp.set_player_duration_hint(None)

    def test_auto_search_uses_trt_when_duration_known(self) -> None:
        def fake_movie(q, **_kwargs):
            return _parody() if "it" in q.casefold() else None

        def fake_tv(q, **_kwargs):
            return _mini_1990() if "it" in q.casefold() else None

        with tp.player_duration_hint(192 * 60):
            with unittest.mock.patch.object(tp, "search_movie_best", side_effect=fake_movie):
                with unittest.mock.patch.object(tp, "search_tv_best", side_effect=fake_tv):
                    item, kind = tp._search_best_media_one(
                        "It",
                        prefer="auto",
                        forgiving=False,
                    )
        self.assertEqual(kind, "tv")
        self.assertEqual(item["id"], 19614)

    def test_auto_search_stays_movie_first_without_duration(self) -> None:
        def fake_movie(q, **_kwargs):
            return _parody() if "it" in q.casefold() else None

        def fake_tv(q, **_kwargs):
            raise AssertionError("TV search should not run when a movie hit exists")

        tp.set_player_duration_hint(None)
        with unittest.mock.patch.object(tp, "search_movie_best", side_effect=fake_movie):
            with unittest.mock.patch.object(tp, "search_tv_best", side_effect=fake_tv):
                item, kind = tp._search_best_media_one(
                    "It",
                    prefer="auto",
                    forgiving=False,
                )
        self.assertEqual(kind, "movie")
        self.assertEqual(item["id"], 900001)


if __name__ == "__main__":
    unittest.main()
