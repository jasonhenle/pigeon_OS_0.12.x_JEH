"""Episode-only title follows the series the service was just playing, offline."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import tmdb_poster as tp  # noqa: E402

_PEACOCK = frozenset({386, 387})
_SHOW = {"id": 8592, "name": "Parks and Recreation", "poster_path": "/p.jpg"}
_OTHER = {"id": 64185, "name": "Win, Lose or Draw"}


class RecentSeriesEpisodeTests(unittest.TestCase):
    def setUp(self) -> None:
        tp.clear_recent_episode_series()
        tp._SERIES_EPISODE_NORMS_CACHE.clear()

    def _swap(self, best):
        with mock.patch.object(
            tp, "_tmdb_watch_provider_ids", side_effect=lambda k, i: _PEACOCK if i == 8592 else None
        ), mock.patch.object(
            tp, "_series_episode_title_norms", return_value=frozenset({"win lose or draw"})
        ), mock.patch.object(tp, "_tmdb_tv_detail", return_value=_SHOW), mock.patch.object(
            tp, "_episode_title_series_fallback", return_value=(None, None)
        ):
            return tp._episode_series_on_service_instead(
                "Win, Lose or Draw", best, _PEACOCK, require_poster=True, service="Peacock"
            )

    def test_unlisted_hit_swaps_to_recent_series_with_that_episode(self) -> None:
        self.assertIsNone(self._swap((_SHOW, "tv")))  # on service: remembered
        swap = self._swap((_OTHER, "tv"))
        self.assertEqual(swap[0]["id"], 8592)

    def test_no_recent_series_keeps_hit(self) -> None:
        self.assertIsNone(self._swap((_OTHER, "tv")))


if __name__ == "__main__":
    unittest.main()
