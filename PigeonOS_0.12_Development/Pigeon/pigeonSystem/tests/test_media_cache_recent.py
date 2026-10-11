"""Render-path TMDb asset lookups: remembered briefly, forgotten on write."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import media_cache as mc  # noqa: E402


class RecentLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        mc.forget_recent_asset_lookups()
        self._patch = mock.patch.object(mc, "_asset_dir_for_type", return_value=self.dir)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        mc.forget_recent_asset_lookups()
        self._tmp.cleanup()

    def test_miss_is_remembered_until_a_write(self) -> None:
        self.assertIsNone(mc.find_cached_reformatted_asset_recent("Film", mc.ASSET_POSTER_ART))
        (self.dir / f"Film_{mc.ASSET_POSTER_ART}.png").write_bytes(b"x")
        # Still the remembered miss (no write went through media_cache).
        self.assertIsNone(mc.find_cached_reformatted_asset_recent("Film", mc.ASSET_POSTER_ART))
        src = self.dir / "pulled.png"
        src.write_bytes(b"y")
        with mock.patch.object(mc, "ensure_reformatted_media_dir"), mock.patch.object(mc, "trim_dir_to_max_files"):
            mc.copy_pulled_to_reformatted(src, "Other", mc.ASSET_POSTER_ART)
        found = mc.find_cached_reformatted_asset_recent("Film", mc.ASSET_POSTER_ART)
        self.assertEqual(found, self.dir / f"Film_{mc.ASSET_POSTER_ART}.png")

    def test_expires(self) -> None:
        self.assertIsNone(mc.find_cached_reformatted_asset_recent("Film", mc.ASSET_POSTER_ART))
        (self.dir / f"Film_{mc.ASSET_POSTER_ART}.jpg").write_bytes(b"x")
        with mock.patch.object(mc.time, "monotonic", return_value=mc.time.monotonic() + mc.RECENT_LOOKUP_S + 0.1):
            self.assertIsNotNone(mc.find_cached_reformatted_asset_recent("Film", mc.ASSET_POSTER_ART))

    def test_uncached_lookup_sees_deletes_immediately(self) -> None:
        p = self.dir / f"Film_{mc.ASSET_LOGO_EN}.png"
        p.write_bytes(b"x")
        self.assertEqual(mc.find_cached_reformatted_asset("Film", mc.ASSET_LOGO_EN), p)
        p.unlink()
        self.assertIsNone(mc.find_cached_reformatted_asset("Film", mc.ASSET_LOGO_EN))


if __name__ == "__main__":
    unittest.main()
