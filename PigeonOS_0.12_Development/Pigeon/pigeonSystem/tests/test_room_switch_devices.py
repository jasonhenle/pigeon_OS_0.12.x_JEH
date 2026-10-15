"""Switching rooms must not keep showing the previous room's player/receiver."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.widgets.main_settings import MainSettingsState  # noqa: E402

_STREAM = {"name": "Apple TV", "address": "10.0.0.5"}
_AVR = {"name": "Denon", "address": "10.0.0.6"}


def _load(state, stream, avr) -> None:
    with mock.patch("pigeon.app_state.read_saved_streaming_device", return_value=stream), \
         mock.patch("pigeon.app_state.read_saved_av_receiver", return_value=avr):
        state.load_saved_box_devices()


class LoadSavedBoxDevicesTests(unittest.TestCase):
    def test_loads_saved_devices(self) -> None:
        st = MainSettingsState()
        _load(st, _STREAM, _AVR)
        self.assertEqual(st.box2_devices.picked, ("Apple TV", "10.0.0.5"))
        self.assertEqual(st.box3_devices.picked, ("Denon", "10.0.0.6"))

    def test_room_without_devices_clears_previous_room(self) -> None:
        st = MainSettingsState()
        _load(st, _STREAM, _AVR)
        st.box2_ip_invalid = st.box3_ip_invalid = True
        _load(st, None, None)  # switch to an empty room
        self.assertIsNone(st.box2_devices.picked)
        self.assertIsNone(st.box3_devices.picked)
        self.assertFalse(st.box2_ip_invalid)
        self.assertFalse(st.box3_ip_invalid)
        with mock.patch("pigeon.app_state.read_saved_streaming_device", return_value=None), \
             mock.patch("pigeon.app_state.read_saved_av_receiver", return_value=None):
            self.assertFalse(st.box_has_saved_device(2))
            self.assertFalse(st.box_has_saved_device(3))

    def test_clears_only_the_box_that_is_empty(self) -> None:
        st = MainSettingsState()
        _load(st, _STREAM, _AVR)
        _load(st, None, _AVR)
        self.assertIsNone(st.box2_devices.picked)
        self.assertEqual(st.box3_devices.picked, ("Denon", "10.0.0.6"))

    def test_unreadable_state_leaves_display_alone(self) -> None:
        st = MainSettingsState()
        _load(st, _STREAM, _AVR)
        with mock.patch("pigeon.app_state.read_saved_streaming_device", side_effect=OSError):
            st.load_saved_box_devices()
        self.assertEqual(st.box2_devices.picked, ("Apple TV", "10.0.0.5"))


if __name__ == "__main__":
    unittest.main()
