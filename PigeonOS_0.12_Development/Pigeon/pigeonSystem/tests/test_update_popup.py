"""settings_pigeon update screen: focus ring, activation, layer visibility."""

from __future__ import annotations

import os
import sys
import unittest
import xml.etree.ElementTree as ET

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.widgets.main_settings import (  # noqa: E402
    MainSettingsState,
    _find_by_logical_id,
)
from pigeon.widgets.update_popup import (  # noqa: E402
    ID_ARROW,
    ID_CURRENT_CONTAINER,
    ID_UPDATE_CONTAINER_TYPO,
    apply_update_popup_svg_state,
    default_update_popup_svg_path,
    update_popup_focus_ring,
    update_status_cells,
)


def _hidden(el: ET.Element | None) -> bool:
    return el is not None and el.get("display") == "none"


def _state(*, available: bool, focus: str = "update") -> MainSettingsState:
    st = MainSettingsState()
    st.show_pigeon_settings = True
    st.show_update_popup = True
    st.update_local_version = "0.11.67"
    st.update_available = available
    st.update_remote_version = "0.11.68" if available else "0.11.67"
    st.set_update_popup_focus(focus)
    return st


def _tree(st: MainSettingsState) -> ET.Element:
    path = default_update_popup_svg_path()
    root = ET.parse(path).getroot()
    apply_update_popup_svg_state(root, st)
    return root


class UpdatePopupFocusTests(unittest.TestCase):
    def test_svg_ships(self) -> None:
        self.assertTrue(default_update_popup_svg_path().is_file())

    def test_current_skipped_without_update(self) -> None:
        self.assertEqual(update_popup_focus_ring(update_available=False), ("back", "update"))
        self.assertEqual(
            update_popup_focus_ring(update_available=True), ("back", "current", "update")
        )

    def test_back_reachable_while_checking(self) -> None:
        self.assertIn("back", update_popup_focus_ring(update_available=False, checking=True))

    def test_no_focus_while_applying(self) -> None:
        self.assertEqual(update_popup_focus_ring(update_available=True, applying=True), ())

    def test_latest_pulls_update_until_reopen(self) -> None:
        self.assertEqual(
            update_popup_focus_ring(update_available=False, latest=True), ("back",)
        )
        st = _state(available=False)
        st.update_latest_confirmed = True
        st.set_update_popup_focus("update")
        self.assertEqual(st.update_popup_focused_choice, "back")
        root = _tree(st)
        self.assertTrue(_hidden(_find_by_logical_id(root, ID_UPDATE_CONTAINER_TYPO)))
        st.close_update_popup()
        st.open_update_popup()
        self.assertFalse(st.update_latest_confirmed)
        self.assertEqual(st.update_popup_focused_choice, "update")

    def test_open_lands_on_update(self) -> None:
        st = MainSettingsState()
        st.open_update_popup()
        self.assertTrue(st.update_checking)
        self.assertEqual(st.update_popup_focused_choice, "update")

    def test_open_with_known_update_skips_check_and_empties_bar(self) -> None:
        from pigeon.widgets.update_popup import update_status_cells

        st = MainSettingsState()
        st.update_available = True
        st.update_remote_version = "0.11.99"
        st.open_update_popup()
        self.assertFalse(st.update_checking)
        self.assertEqual(st.update_popup_focused_choice, "update")
        self.assertEqual(update_status_cells(st)[0], 0)
        # Not checking + update known: the next click on UPDATE installs it
        # (``activate`` returns ``update_popup:now``) instead of re-checking.
        self.assertTrue(st.update_available)

    def test_open_after_failed_check_checks_again(self) -> None:
        st = MainSettingsState()
        st.update_available = True
        st.update_error = "Could not reach GitHub"
        st.open_update_popup()
        self.assertTrue(st.update_checking)


class UpdatePopupLayerTests(unittest.TestCase):
    def test_update_container_follows_focus(self) -> None:
        root = _tree(_state(available=True, focus="update"))
        self.assertFalse(_hidden(_find_by_logical_id(root, ID_UPDATE_CONTAINER_TYPO)))
        self.assertTrue(_hidden(_find_by_logical_id(root, ID_CURRENT_CONTAINER)))

    def test_current_container_follows_focus(self) -> None:
        root = _tree(_state(available=True, focus="current"))
        self.assertTrue(_hidden(_find_by_logical_id(root, ID_UPDATE_CONTAINER_TYPO)))
        self.assertFalse(_hidden(_find_by_logical_id(root, ID_CURRENT_CONTAINER)))

    def test_badge_and_arrow_only_with_update(self) -> None:
        root = _tree(_state(available=True))
        self.assertIsNotNone(_find_by_logical_id(root, "version_update_badge"))
        self.assertFalse(_hidden(_find_by_logical_id(root, ID_ARROW)))
        root = _tree(_state(available=False))
        self.assertIsNone(_find_by_logical_id(root, "version_update_badge"))
        self.assertTrue(_hidden(_find_by_logical_id(root, ID_ARROW)))

    def test_status_cells(self) -> None:
        st = _state(available=True)
        st.update_applying = True
        st.update_progress = 0.5
        self.assertEqual(update_status_cells(st), (30, "ui"))
        st = _state(available=False)
        st.update_error = "offline"
        self.assertEqual(update_status_cells(st), (60, "error"))


if __name__ == "__main__":
    unittest.main()
