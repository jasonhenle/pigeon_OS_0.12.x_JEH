"""Linux SSID probes must report the radio SSID, not a generic NM profile name."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import wifi_scan as ws  # noqa: E402


def _run(stdout: str, returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


class LinuxConnectedSsidTests(unittest.TestCase):
    def setUp(self) -> None:
        ws.clear_connected_ssid_cache()

    def test_active_wifi_list_wins(self) -> None:
        def fake_run(cmd, **_kwargs):
            if cmd[:6] == ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"]:
                return _run("no:Guest\nyes:Skynet\n")
            raise AssertionError(cmd)

        with patch.object(ws.shutil, "which", return_value="/usr/bin/nmcli"):
            with patch.object(ws.subprocess, "run", side_effect=fake_run):
                self.assertEqual(ws._current_connected_ssid_linux(), "Skynet")

    def test_preconfigured_profile_uses_stored_ssid(self) -> None:
        def fake_run(cmd, **_kwargs):
            if cmd[:6] == ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"]:
                return _run("")
            if cmd[:6] == ["nmcli", "-t", "-f", "IN-USE,SSID", "dev", "wifi"]:
                return _run("")
            if cmd[:5] == ["nmcli", "-t", "-f", "NAME,TYPE", "con"]:
                return _run("preconfigured:802-11-wireless\nlo:loopback\n")
            if cmd[:5] == ["nmcli", "-t", "-f", "802-11-wireless.ssid", "connection"]:
                self.assertEqual(cmd[-1], "preconfigured")
                return _run("802-11-wireless.ssid:Skynet\n")
            raise AssertionError(cmd)

        with patch.object(ws.shutil, "which", return_value="/usr/bin/nmcli"):
            with patch.object(ws.subprocess, "run", side_effect=fake_run):
                self.assertEqual(ws._current_connected_ssid_linux(), "Skynet")

    def test_preconfigured_without_ssid_property_is_blank(self) -> None:
        def fake_which(name: str) -> str:
            return "/usr/bin/nmcli" if name == "nmcli" else ""

        def fake_run(cmd, **_kwargs):
            if "dev" in cmd and "wifi" in cmd:
                return _run("")
            if cmd[:5] == ["nmcli", "-t", "-f", "NAME,TYPE", "con"]:
                return _run("preconfigured:802-11-wireless\n")
            if "802-11-wireless.ssid" in cmd:
                return _run("", returncode=0)
            raise AssertionError(cmd)

        with patch.object(ws.shutil, "which", side_effect=fake_which):
            with patch.object(ws.subprocess, "run", side_effect=fake_run):
                self.assertEqual(ws._current_connected_ssid_linux(), "")

    def test_profile_named_after_ssid_is_used_when_property_missing(self) -> None:
        def fake_run(cmd, **_kwargs):
            if "dev" in cmd and "wifi" in cmd:
                return _run("")
            if cmd[:5] == ["nmcli", "-t", "-f", "NAME,TYPE", "con"]:
                return _run("Skynet:802-11-wireless\n")
            if "802-11-wireless.ssid" in cmd:
                return _run("")
            raise AssertionError(cmd)

        with patch.object(ws.shutil, "which", return_value="/usr/bin/nmcli"):
            with patch.object(ws.subprocess, "run", side_effect=fake_run):
                self.assertEqual(ws._current_connected_ssid_linux(), "Skynet")

    def test_in_use_column_is_accepted(self) -> None:
        def fake_run(cmd, **_kwargs):
            if cmd[:6] == ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"]:
                return _run("")
            if cmd[:6] == ["nmcli", "-t", "-f", "IN-USE,SSID", "dev", "wifi"]:
                return _run(" :Guest\n*:Skynet\n")
            raise AssertionError(cmd)

        with patch.object(ws.shutil, "which", return_value="/usr/bin/nmcli"):
            with patch.object(ws.subprocess, "run", side_effect=fake_run):
                self.assertEqual(ws._current_connected_ssid_linux(), "Skynet")


class RequiredAssetPathsTests(unittest.TestCase):
    def test_required_assets_include_logo_and_splash(self) -> None:
        from pigeon.update_assets import REQUIRED_ASSET_PATHS

        self.assertIn("pigeonAssets/App logos/AppLogo_Pigeon.png", REQUIRED_ASSET_PATHS)
        self.assertIn(
            "pigeonAssets/pigeonSplash/widget_pigeon_splash_00251.png",
            REQUIRED_ASSET_PATHS,
        )


if __name__ == "__main__":
    unittest.main()
