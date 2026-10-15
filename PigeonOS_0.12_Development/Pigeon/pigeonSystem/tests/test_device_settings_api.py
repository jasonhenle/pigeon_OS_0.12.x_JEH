"""Rooms and Pigeon-page settings over the Control API."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import app_state, pigeon_locale, runtime_paths  # noqa: E402
from pigeon.control_api import device_settings as ds  # noqa: E402
from pigeon.control_api.server import ControlService  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = runtime_paths._CACHED
        runtime_paths._CACHED = Path(self._tmp.name)
        # app_state caches parsed state by file signature; point it at the temp dir
        app_state._STATE_TEXT_CACHE = None
        app_state._STATE_PARSED_CACHE = None
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: setattr(runtime_paths, "_CACHED", self._prev))
        self.applied: list[str] = []
        self.svc = ControlService(
            run_on_ui=lambda fn: fn(),
            apply_location=lambda: self.applied.append("location"),
            apply_settings=lambda: self.applied.append("settings"),
        )
        self.token = self.svc.auth.claim(self.svc.auth.pairing_code, "t", "c1")

    def call(self, method, path, body=None):
        return self.svc.handle(method, "/api/v1" + path, {}, self.token, body)


class RoomTests(_Base):
    def test_list_has_presets_and_one_current(self) -> None:
        st, d = self.call("GET", "/rooms")
        self.assertEqual(st, 200)
        self.assertEqual(len(d["rooms"]), 3)  # same three slots the screens offer
        self.assertEqual(sum(1 for r in d["rooms"] if r["current"]), 1)
        self.assertIn("Theater", d["presets"])
        self.assertEqual(d["current"], next(r["id"] for r in d["rooms"] if r["current"]))

    def test_rename_current_room_persists_and_refreshes_ui(self) -> None:
        rid = self.call("GET", "/rooms")[1]["current"]
        st, d = self.call("PATCH", f"/rooms/{rid}", {"name": "  Theater  "})
        self.assertEqual(st, 200)
        self.assertEqual(next(r for r in d["rooms"] if r["id"] == rid)["name"], "Theater")
        self.assertEqual(app_state.read_current_location_name(), "Theater")
        self.assertEqual(self.applied, ["location"])

    def test_rename_validation(self) -> None:
        rid = self.call("GET", "/rooms")[1]["current"]
        self.assertEqual(self.call("PATCH", f"/rooms/{rid}", {"name": "   "})[0], 400)
        self.assertEqual(self.call("PATCH", f"/rooms/{rid}", {"name": "x" * 40})[0], 400)
        self.assertEqual(self.call("PATCH", "/rooms/nope", {"name": "Den"})[0], 404)
        self.assertEqual(self.call("PATCH", f"/rooms/{rid}", {})[0], 400)
        self.assertEqual(self.applied, [])

    def test_switch_room(self) -> None:
        rooms = self.call("GET", "/rooms")[1]["rooms"]
        other = next(r for r in rooms if not r["current"])
        st, d = self.call("PUT", "/rooms/current", {"id": other["id"]})
        self.assertEqual((st, d["current"]), (200, other["id"]))
        self.assertEqual(self.applied, ["location"])
        self.assertEqual(self.call("PUT", "/rooms/current", {"id": "nope"})[0], 404)
        self.assertEqual(self.call("PUT", "/rooms/current", {})[0], 400)


class PigeonSettingsTests(_Base):
    def test_read_shape(self) -> None:
        st, d = self.call("GET", "/pigeon-settings")
        self.assertEqual(st, 200)
        self.assertEqual(set(d["options"]), set(ds.OPTION_VALUES))
        self.assertIn("blue", d["ui_color_choices"])
        self.assertTrue(d["timezone_choices"])
        self.assertRegex(d["version"], r"^\d+\.\d+\.\d+$")

    def test_patch_options_and_color_persist_and_refresh_ui(self) -> None:
        st, d = self.call("PATCH", "/pigeon-settings",
                          {"options": {"time_format": "24", "temp_format": "c"}, "ui_color": "green"})
        self.assertEqual(st, 200)
        self.assertEqual(d["options"]["time_format"], "24")
        self.assertEqual(d["options"]["temp_format"], "c")
        self.assertEqual(d["options"]["zone6_mode"], "now_playing")  # untouched
        self.assertEqual(d["ui_color"], "green")
        self.assertEqual(self.applied, ["settings"])
        # survives a fresh read from disk
        app_state._STATE_TEXT_CACHE = None
        app_state._STATE_PARSED_CACHE = None
        self.assertEqual(self.call("GET", "/pigeon-settings")[1]["options"]["time_format"], "24")

    def test_timezone_and_zip(self) -> None:
        tz = ds.read_pigeon_settings()["timezone_choices"][0]

        class _Sync:  # run the zip worker inline so it can never outlive the temp state dir
            def __init__(self, target=None, **_kw):
                self._t = target

            def start(self):
                self._t()

        with mock.patch.object(pigeon_locale, "_lookup_zip_timezone", return_value=tz), \
             mock.patch.object(pigeon_locale.threading, "Thread", _Sync), \
             mock.patch("pigeon.weather.refresh_weather", create=True):
            st, d = self.call("PATCH", "/pigeon-settings", {"timezone": tz, "zip": "21710"})
        self.assertEqual(st, 200)
        self.assertEqual(d["timezone"], tz)
        self.assertEqual(d["zip"], "21710")

    def test_zip_must_be_exactly_five_digits(self) -> None:
        before = ds.read_pigeon_settings()["zip"]
        for bad in ("123456", "abc12345", "1234", "12345-6789", "12 345", "", None, True, 12.5):
            st, d = self.call("PATCH", "/pigeon-settings", {"zip": bad})
            self.assertEqual(st, 400, bad)
            self.assertEqual(d["error"]["details"]["fields"], ["zip"], bad)
        self.assertEqual(ds.read_pigeon_settings()["zip"], before)
        self.assertEqual(self.applied, [])

    def test_zip_accepts_five_digits_with_surrounding_space(self) -> None:
        with mock.patch.object(pigeon_locale, "set_zipcode_manual", return_value=True) as m:
            st, _ = self.call("PATCH", "/pigeon-settings", {"zip": " 21710 "})
        self.assertEqual(st, 200)
        self.assertEqual(m.call_args.args[0].strip(), "21710")

    def _patch_with_blocked_lookup(self, body, lookup_tz):
        """PATCH while the zip->timezone lookup is parked; release it afterwards."""
        gate = threading.Event()
        threads: list[threading.Thread] = []
        real_thread = threading.Thread

        class _Recorded(real_thread):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                threads.append(self)

        def slow_lookup(_zip):
            gate.wait(5)
            return lookup_tz

        with mock.patch.object(pigeon_locale, "_lookup_zip_timezone", side_effect=slow_lookup), \
             mock.patch.object(pigeon_locale.threading, "Thread", _Recorded), \
             mock.patch("pigeon.weather.refresh_weather", create=True):
            st, d = self.call("PATCH", "/pigeon-settings", body)
            gate.set()  # the background lookup now finishes *after* the PATCH returned
            for t in threads:
                t.join(5)
        return st, d

    def test_manual_timezone_beats_late_zip_lookup(self) -> None:
        choices = ds.read_pigeon_settings()["timezone_choices"]
        manual, looked_up = choices[0], choices[1]
        st, _ = self._patch_with_blocked_lookup({"zip": "21710", "timezone": manual}, looked_up)
        self.assertEqual(st, 200)
        d = ds.read_pigeon_settings()
        self.assertEqual(d["zip"], "21710")
        self.assertEqual(d["timezone"], manual)
        self.assertEqual(pigeon_locale._read().get("tz_source"), "manual")

    def test_zip_alone_sets_location_timezone(self) -> None:
        choices = ds.read_pigeon_settings()["timezone_choices"]
        looked_up = choices[1]
        st, _ = self._patch_with_blocked_lookup({"zip": "21710"}, looked_up)
        self.assertEqual(st, 200)
        self.assertEqual(ds.read_pigeon_settings()["timezone"], looked_up)
        self.assertEqual(pigeon_locale._read().get("tz_source"), "zip")

    def test_validation_is_all_or_nothing(self) -> None:
        before = self.call("GET", "/pigeon-settings")[1]["options"]
        st, d = self.call("PATCH", "/pigeon-settings",
                          {"options": {"time_format": "24", "temp_format": "kelvin"}, "ui_color": "purple"})
        self.assertEqual(st, 400)
        self.assertEqual(set(d["error"]["details"]["fields"]), {"options.temp_format", "ui_color"})
        self.assertEqual(self.call("GET", "/pigeon-settings")[1]["options"], before)
        self.assertEqual(self.applied, [])

    def test_bad_zip_timezone_and_unknown_fields(self) -> None:
        for body in ({"zip": "12"}, {"timezone": "Mars/Phobos"}, {"volume": 11}, {}, {"options": "x"}):
            self.assertEqual(self.call("PATCH", "/pigeon-settings", body)[0], 400, body)


if __name__ == "__main__":
    unittest.main()
