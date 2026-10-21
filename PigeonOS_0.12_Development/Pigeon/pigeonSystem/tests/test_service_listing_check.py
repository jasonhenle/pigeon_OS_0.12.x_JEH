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


if __name__ == "__main__":
    unittest.main()
