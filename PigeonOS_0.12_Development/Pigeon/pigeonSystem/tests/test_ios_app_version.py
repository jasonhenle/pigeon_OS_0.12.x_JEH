"""The iOS app (Pigeon Remote) versions itself, independent of PigeonOS.

project.yml holds the only literal (MARKETING_VERSION / CURRENT_PROJECT_VERSION);
Info.plist reads them as build variables, and the checked-in Xcode project agrees.
"""

from __future__ import annotations

import plistlib
import re
import subprocess
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
        self.assertRegex(_yml_value("MARKETING_VERSION"), r"^0\.1\.\d+$")
        # Build number = the patch of 0.1.N, so the two always move together.
        self.assertEqual(_yml_value("CURRENT_PROJECT_VERSION"), _yml_value("MARKETING_VERSION").split(".")[2])

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

    def test_app_changes_bump_the_version(self) -> None:
        """Changing anything under PigeonApp/Pigeon needs a new version vs the main branch."""
        root = _APP.parent

        def git(*args: str) -> str | None:
            r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
            return r.stdout.strip() if r.returncode == 0 else None

        base = next((b for b in ("origin2/main", "origin/main", "main") if git("rev-parse", "--verify", b)), None)
        merge_base = base and git("merge-base", "HEAD", base)
        if not merge_base:
            self.skipTest("no main branch to compare against")
        changed = git("diff", "--name-only", merge_base, "--", "PigeonApp/Pigeon")
        if not changed:
            return
        old = git("show", f"{merge_base}:PigeonApp/project.yml") or ""

        def old_value(key: str) -> str | None:
            m = re.search(rf'^\s*{key}:\s*"?([^"\s#]+)"?', old, re.M)
            return m.group(1) if m else None

        self.assertNotEqual(
            (old_value("MARKETING_VERSION"), old_value("CURRENT_PROJECT_VERSION")),
            (_yml_value("MARKETING_VERSION"), _yml_value("CURRENT_PROJECT_VERSION")),
            f"PigeonApp/Pigeon changed ({changed.splitlines()[0]}, ...) but the version in "
            "PigeonApp/project.yml did not: bump MARKETING_VERSION 0.1.N and CURRENT_PROJECT_VERSION N.",
        )


if __name__ == "__main__":
    unittest.main()
