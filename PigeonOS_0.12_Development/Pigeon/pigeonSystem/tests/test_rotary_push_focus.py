"""Encoder push that opens main settings lands focus on box1 (settings_pigeon)."""

from __future__ import annotations

import enum
import os
import sys
import unittest
from types import SimpleNamespace

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.core.input_keys import _on_rotary_action  # noqa: E402
from pigeon.widgets.main_settings import MainSettingsState  # noqa: E402


class _Phase(enum.Enum):
    OFF = 0
    MAIN_SETTINGS = 1


class _Widget:
    def __init__(self) -> None:
        self.state = MainSettingsState()
        self.activated = 0
        self.navigated = 0

    def invalidate(self) -> None:
        pass

    def activate(self) -> str:
        self.activated += 1
        return ""

    def navigate(self, *, forward: bool) -> None:
        self.navigated += 1


def _run(action: str, widget: _Widget, dev_phase: list) -> None:
    def enter() -> bool:
        dev_phase[0] = _Phase.MAIN_SETTINGS
        return True

    _on_rotary_action(
        action,
        DevPhase=_Phase,
        _bump_pigeon_user_activity=lambda *a: None,
        _enter_main_settings_for_rotary=enter,
        _handle_main_settings_action=lambda a: None,
        _nav_request=[None],
        dev_phase=dev_phase,
        main_settings_widget=widget,
        render_once=lambda: None,
        root=SimpleNamespace(),
        skip_cache=[object()],
        sync_developer_chrome=lambda: None,
    )


class RotaryPushFocusTests(unittest.TestCase):
    def test_push_opening_settings_focuses_box1_without_activating(self) -> None:
        w, phase = _Widget(), [_Phase.OFF]
        w.state.focus_main_button("main_exit_button")
        _run("activate", w, phase)
        self.assertEqual(phase[0], _Phase.MAIN_SETTINGS)
        self.assertEqual(w.state.focused_id, "main_box1_button")
        self.assertEqual(w.activated, 0)

    def test_push_inside_settings_still_activates(self) -> None:
        w, phase = _Widget(), [_Phase.MAIN_SETTINGS]
        w.state.focus_main_button("main_exit_button")
        _run("activate", w, phase)
        self.assertEqual(w.activated, 1)
        self.assertEqual(w.state.focused_id, "main_exit_button")

    def test_turn_opening_settings_keeps_focus(self) -> None:
        w, phase = _Widget(), [_Phase.OFF]
        w.state.focus_main_button("main_box2_button")
        _run("forward", w, phase)
        self.assertEqual(w.navigated, 1)
        self.assertNotEqual(w.state.focused_id, "main_box1_button")


if __name__ == "__main__":
    unittest.main()
