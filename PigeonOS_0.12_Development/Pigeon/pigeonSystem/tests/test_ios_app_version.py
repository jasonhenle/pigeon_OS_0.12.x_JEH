"""The iOS app's version is bumped with Pigeon's: Info.plist must match version.py."""

from __future__ import annotations

import os
import plistlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pigeon.version import PATCH, version_string  # noqa: E402

_PLIST = Path(__file__).resolve().parents[4] / "PigeonApp" / "Pigeon" / "Info.plist"


class IosAppVersionTests(unittest.TestCase):
    def test_info_plist_matches_pigeon_version(self) -> None:
        if not _PLIST.is_file():
            self.skipTest("PigeonApp not in this checkout")
        info = plistlib.loads(_PLIST.read_bytes())
        self.assertEqual(info["CFBundleShortVersionString"], version_string())
        self.assertEqual(info["CFBundleVersion"], str(PATCH))


if __name__ == "__main__":
    unittest.main()
