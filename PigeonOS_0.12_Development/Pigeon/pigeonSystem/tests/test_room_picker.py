"""Room picker: renamed rooms return to settings_main, placeholder rooms stay."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import runtime_paths  # noqa: E402
from pigeon.widgets.main_settings import (  # noqa: E402
    MainSettingsWidget,
    location_name_is_default,
)

ASSETS = Path(__file__).resolve().parents[2] / "pigeonAssets"


class LocationNameTests(unittest.TestCase):
    def test_placeholder_names(self) -> None:
        for name in ("", "ROOM 1", "Room 3", "nest 2", "room", "Nest"):
            self.assertTrue(location_name_is_default(name), name)
        for name in ("THEATER", "Family Room", "Den"):
            self.assertFalse(location_name_is_default(name), name)


class RoomPickerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = runtime_paths._CACHED
        runtime_paths._CACHED = Path(self._tmp.name)
        from pigeon import app_state

        self.app_state = app_state
        # Slot 1 renamed (current), slot 2 renamed, slot 3 still a placeholder.
        locs = app_state.read_all_locations_v2()  # a fresh state dir seeds one "Room"
        for nm in ("DEN", "ROOM 3"):
            if len(locs) < 3:
                app_state.add_empty_location_v2(nm)
                locs = app_state.read_all_locations_v2()
        for loc, nm in zip(locs[:3], ("THEATER", "DEN", "ROOM 3")):
            app_state.rename_location_v2(str(loc["id"]), nm)
        self.locs = app_state.read_all_locations_v2()
        app_state.set_current_location_id(str(self.locs[0]["id"]))
        self.w = MainSettingsWidget(assets_dir=ASSETS)
        st = self.w.state
        st.selected_wifi_ssid = st.live_wifi_ssid = "HomeNet"
        st.enter_location_picker()

    def tearDown(self) -> None:
        runtime_paths._CACHED = self._prev
        self._tmp.cleanup()

    def _names(self) -> list[str]:
        return [str(n) for _i, n in self.w.state.location_slots]

    def test_renamed_room_switches_and_returns_to_main(self) -> None:
        st = self.w.state
        self.assertEqual(self._names()[:3], ["THEATER", "DEN", "ROOM 3"])
        self.assertTrue(st.show_location_picker)
        action = self.w._activate_location_picker_slot(2)
        self.assertEqual(action, "location_switch")
        self.assertFalse(st.show_location_picker)  # no BACK needed
        self.assertEqual(
            self.app_state.read_current_location_id(), str(self.locs[1]["id"])
        )
        self.assertEqual(st.focused_id, "main_dual_location_button")

    def test_placeholder_room_switches_but_stays_for_renaming(self) -> None:
        st = self.w.state
        self.assertTrue(location_name_is_default(self._names()[2]))
        action = self.w._activate_location_picker_slot(3)
        self.assertEqual(action, "location_switch")
        self.assertTrue(st.show_location_picker)
        self.assertEqual(
            self.app_state.read_current_location_id(), str(self.locs[2]["id"])
        )
        # Activating it again (now current) opens the rename keyboard.
        self.assertEqual(
            self.w._activate_location_picker_slot(3), "keyboard_open:location"
        )

    def test_activating_current_renamed_room_still_renames(self) -> None:
        st = self.w.state
        self.assertEqual(
            self.w._activate_location_picker_slot(1), "keyboard_open:location"
        )
        self.assertTrue(st.keyboard_open)


if __name__ == "__main__":
    unittest.main()
