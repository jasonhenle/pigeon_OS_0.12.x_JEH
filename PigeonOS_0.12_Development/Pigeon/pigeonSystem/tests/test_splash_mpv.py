"""mpv splash: enable switch, command line, and the shipped video asset."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.splash_mpv import (  # noqa: E402
    SPLASH_MPV_VIDEO_RELPATH,
    mpv_command,
    splash_mpv_enabled,
    splash_mpv_video_path,
)
from pigeon.splash_sequence import find_splash_video_path  # noqa: E402

_APP_ROOT = Path(_SYS_ROOT).parent


class SplashMpvEnableTests(unittest.TestCase):
    def test_default_follows_platform(self) -> None:
        with mock.patch.dict(os.environ, {"PIGEON_SPLASH_MPV": ""}):
            with mock.patch.object(sys, "platform", "linux"):
                self.assertTrue(splash_mpv_enabled())
            with mock.patch.object(sys, "platform", "darwin"):
                self.assertFalse(splash_mpv_enabled())

    def test_env_overrides(self) -> None:
        with mock.patch.object(sys, "platform", "linux"):
            with mock.patch.dict(os.environ, {"PIGEON_SPLASH_MPV": "0"}):
                self.assertFalse(splash_mpv_enabled())
        with mock.patch.object(sys, "platform", "darwin"):
            with mock.patch.dict(os.environ, {"PIGEON_SPLASH_MPV": "1"}):
                self.assertTrue(splash_mpv_enabled())


class SplashMpvCommandTests(unittest.TestCase):
    def _cmd(self, platform: str) -> list[str]:
        with mock.patch.dict(os.environ, {"PIGEON_SPLASH_MPV_ARGS": ""}):
            return mpv_command(
                Path("/x/splash.mp4"), wid=1234, ipc_path="/tmp/s.sock", hold_end_s=4.95, platform=platform
            )

    def test_embeds_and_holds(self) -> None:
        cmd = self._cmd("linux")
        self.assertIn("--wid=1234", cmd)
        self.assertIn("--end=4.9500", cmd)
        self.assertIn("--keep-open=yes", cmd)
        self.assertIn("--input-vo-keyboard=no", cmd)
        self.assertEqual(cmd[-2:], ["--", "/x/splash.mp4"])

    def test_x11_context_on_linux_only(self) -> None:
        self.assertIn("--gpu-context=x11egl", self._cmd("linux"))
        self.assertNotIn("--gpu-context=x11egl", self._cmd("darwin"))


class SplashMpvAssetTests(unittest.TestCase):
    def test_video_ships(self) -> None:
        self.assertEqual(splash_mpv_video_path(_APP_ROOT), _APP_ROOT / SPLASH_MPV_VIDEO_RELPATH)

    def test_not_mistaken_for_full_splash_video(self) -> None:
        found = find_splash_video_path(_APP_ROOT / "pigeonAssets")
        self.assertNotEqual(found, _APP_ROOT / SPLASH_MPV_VIDEO_RELPATH)


if __name__ == "__main__":
    unittest.main()
