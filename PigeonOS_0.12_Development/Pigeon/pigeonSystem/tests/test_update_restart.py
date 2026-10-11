"""After an in-app update, Pigeon must come back under pigeon.service (Restart=on-failure)."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import github_update as gu  # noqa: E402


class ExitCodeAfterUpdateTests(unittest.TestCase):
    def _cgroup(self, text: str):
        return mock.patch.object(gu.Path, "read_text", return_value=text)

    def test_inside_pigeon_service_exits_failed_so_systemd_restarts(self) -> None:
        with mock.patch.object(gu.sys, "platform", "linux"), self._cgroup("0::/system.slice/pigeon.service\n"):
            self.assertTrue(gu.running_under_pigeon_service())
            self.assertEqual(gu.exit_code_after_update(), gu.UPDATE_RESTART_EXIT_CODE)
            self.assertNotEqual(gu.UPDATE_RESTART_EXIT_CODE, 0)

    def test_desktop_launch_exits_cleanly(self) -> None:
        with mock.patch.object(gu.sys, "platform", "linux"), \
                self._cgroup("0::/user.slice/user-1000.slice/session-3.scope\n"):
            self.assertEqual(gu.exit_code_after_update(), 0)
        with mock.patch.object(gu.sys, "platform", "darwin"):
            self.assertEqual(gu.exit_code_after_update(), 0)

    def test_update_script_queues_a_systemd_restart_inside_the_unit(self) -> None:
        script = gu.Path(_SYS_ROOT).parent / "installer" / "pigeon_github_update.sh"
        text = script.read_text(encoding="utf-8")
        body = text[text.index("schedule_in_app_relaunch() {"):]
        self.assertLess(body.index("pigeon.service\" /proc/self/cgroup"), body.index("nohup bash -c"))
        self.assertIn('restart pigeon.service >/dev/null 2>&1 &', body)


if __name__ == "__main__":
    unittest.main()
