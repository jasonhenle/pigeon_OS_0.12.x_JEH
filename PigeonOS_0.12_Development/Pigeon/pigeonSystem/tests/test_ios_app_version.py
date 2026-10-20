"""The iOS app's version is bumped with Pigeon's.

project.yml holds the only literal (MARKETING_VERSION / CURRENT_PROJECT_VERSION);
Info.plist reads them as build variables so no second copy can drift.
"""

from __future__ import annotations

import os
import plistlib
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pigeon.version import PATCH, version_string  # noqa: E402

_APP = Path(__file__).resolve().parents[4] / "PigeonApp"
_PLIST = _APP / "Pigeon" / "Info.plist"
_YML = _APP / "project.yml"
_PBXPROJ = _APP / "Pigeon.xcodeproj" / "project.pbxproj"


def _yml_value(key: str) -> str:
    m = re.search(rf'^\s*{key}:\s*"?([^"\s#]+)"?', _YML.read_text(), re.M)
    assert m, f"{key} missing from project.yml"
    return m.group(1)


class IosAppVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        if not _YML.is_file():
            self.skipTest("PigeonApp not in this checkout")

    def test_project_yml_matches_pigeon_version(self) -> None:
        self.assertEqual(_yml_value("MARKETING_VERSION"), version_string())
        self.assertEqual(_yml_value("CURRENT_PROJECT_VERSION"), str(PATCH))

    def test_info_plist_reads_the_build_settings(self) -> None:
        info = plistlib.loads(_PLIST.read_bytes())
        self.assertEqual(info["CFBundleShortVersionString"], "$(MARKETING_VERSION)")
        self.assertEqual(info["CFBundleVersion"], "$(CURRENT_PROJECT_VERSION)")
        self.assertIsNone(re.search(r"CFBundle(ShortVersionString|Version):\s*\"?\d", _YML.read_text()))

    def test_generated_project_matches_pigeon_version(self) -> None:
        if not _PBXPROJ.is_file():
            self.skipTest("Xcode project not generated")
        text = _PBXPROJ.read_text()
        self.assertEqual(set(re.findall(r"MARKETING_VERSION = ([^;]+);", text)), {version_string()})
        self.assertEqual(set(re.findall(r"CURRENT_PROJECT_VERSION = ([^;]+);", text)), {str(PATCH)})

    def test_ipad_is_supported(self) -> None:
        self.assertIn('TARGETED_DEVICE_FAMILY: "1,2"', _YML.read_text())
        if _PBXPROJ.is_file():
            self.assertEqual(set(re.findall(r"TARGETED_DEVICE_FAMILY = ([^;]+);", _PBXPROJ.read_text())), {'"1,2"'})


if __name__ == "__main__":
    unittest.main()
