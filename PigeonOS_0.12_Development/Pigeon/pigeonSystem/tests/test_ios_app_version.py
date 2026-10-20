"""The iOS app (Pigeon Remote) versions itself, independent of PigeonOS.

project.yml holds the only literal (MARKETING_VERSION / CURRENT_PROJECT_VERSION);
Info.plist reads them as build variables, and the checked-in Xcode project agrees.
"""

from __future__ import annotations

import plistlib
import re
import unittest
from pathlib import Path

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

    def test_versions_are_well_formed(self) -> None:
        self.assertRegex(_yml_value("MARKETING_VERSION"), r"^\d+\.\d+\.\d+$")
        self.assertRegex(_yml_value("CURRENT_PROJECT_VERSION"), r"^\d+$")

    def test_info_plist_reads_the_build_settings(self) -> None:
        info = plistlib.loads(_PLIST.read_bytes())
        self.assertEqual(info["CFBundleShortVersionString"], "$(MARKETING_VERSION)")
        self.assertEqual(info["CFBundleVersion"], "$(CURRENT_PROJECT_VERSION)")
        self.assertIsNone(re.search(r"CFBundle(ShortVersionString|Version):\s*\"?\d", _YML.read_text()))

    def test_generated_project_matches_project_yml(self) -> None:
        if not _PBXPROJ.is_file():
            self.skipTest("Xcode project not generated")
        text = _PBXPROJ.read_text()
        self.assertEqual(set(re.findall(r"MARKETING_VERSION = ([^;]+);", text)), {_yml_value("MARKETING_VERSION")})
        self.assertEqual(set(re.findall(r"CURRENT_PROJECT_VERSION = ([^;]+);", text)), {_yml_value("CURRENT_PROJECT_VERSION")})

    def test_ipad_is_supported(self) -> None:
        self.assertIn('TARGETED_DEVICE_FAMILY: "1,2"', _YML.read_text())
        if _PBXPROJ.is_file():
            self.assertEqual(set(re.findall(r"TARGETED_DEVICE_FAMILY = ([^;]+);", _PBXPROJ.read_text())), {'"1,2"'})


if __name__ == "__main__":
    unittest.main()
