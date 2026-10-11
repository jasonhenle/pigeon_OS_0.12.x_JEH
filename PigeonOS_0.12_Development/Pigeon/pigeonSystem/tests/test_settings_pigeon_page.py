"""settings_pigeon 0.11: one flat page (zip, timezone, colors, options, reset, update)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import app_state, pigeon_locale  # noqa: E402
from pigeon.widgets import pigeon_settings as ps  # noqa: E402
from pigeon.widgets import ui_color_settings as ucs  # noqa: E402
from pigeon.widgets.main_settings import MainSettingsState, MainSettingsWidget  # noqa: E402


class _IsolatedStateTest(unittest.TestCase):
    """Temp state.json and no network lookups."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "state.json"
        patches = [
            mock.patch.object(app_state, "state_file", return_value=path),
            # Cache keys are (mtime, size) only; restore the caller's entries after.
            mock.patch.object(app_state, "_STATE_TEXT_CACHE", None),
            mock.patch.object(app_state, "_STATE_PARSED_CACHE", None),
            mock.patch.object(pigeon_locale, "_lookup_ip_location", return_value=("", "")),
            mock.patch.object(pigeon_locale, "_lookup_zip_timezone", return_value=""),
            mock.patch("pigeon.weather.refresh_weather", return_value=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        ucs._LIVE_UI_KEY = None
        self.addCleanup(setattr, ucs, "_LIVE_UI_KEY", None)

    def _root(self, state: MainSettingsState) -> ET.Element:
        root = ps._svg_tree_from_path(ps.default_pigeon_settings_svg_path())
        ps.apply_pigeon_settings_svg_state(root, state)
        return root

    def _widget(self) -> MainSettingsWidget:
        w = MainSettingsWidget()
        with mock.patch.object(MainSettingsState, "refresh_network_ssid"):
            w.state.enter_pigeon_settings()
        return w

    def _focus(self, w: MainSettingsWidget, fid: str) -> None:
        for _ in range(len(ps.pigeon_focus_ring())):
            if w.state.pigeon_focused_id == fid:
                return
            w.navigate(forward=True)
        self.fail(f"{fid} not reachable")


class FocusRingTests(unittest.TestCase):
    def test_navigation_order_matches_spec(self) -> None:
        self.assertEqual(
            ps.pigeon_focus_ring(),
            (
                "exit",
                "zipcode",
                "timezone",
                "color:blue",
                "color:green",
                "color:yellow",
                "color:orange",
                "color:red",
                "color:grey",
                "color:white",
                "option:1",
                "option:2",
                "option:3",
                "option:4",
                "option:5",
                "reset",
                "update",
            ),
        )

    def test_swatch_hexes_are_the_svg_icon_fills(self) -> None:
        def full_hex(value: str) -> str:
            h = value.strip().lower().lstrip("#")
            return "#" + ("".join(c * 2 for c in h) if len(h) == 3 else h)

        root = ET.parse(ps.default_pigeon_settings_svg_path()).getroot()
        for key in ps.UI_COLOR_KEYS:
            group = ps._by_id(root, f"ui_color_{key}_group")
            icon = ps._child_with(group, "_icon")
            self.assertIsNotNone(icon, key)
            self.assertEqual(
                full_hex(ucs.hex_for_color_key("ui", key)), full_hex(icon.get("fill")), key
            )


class IsolatedStateFixtureTests(unittest.TestCase):
    def test_state_caches_restored_after_cleanup(self) -> None:
        text_sentinel = (1, 2, "outer")
        parsed_sentinel = (1, 2, {"outer": True})
        with (
            mock.patch.object(app_state, "_STATE_TEXT_CACHE", text_sentinel),
            mock.patch.object(app_state, "_STATE_PARSED_CACHE", parsed_sentinel),
        ):
            inner = _IsolatedStateTest("run")
            inner.setUp()
            self.assertIsNone(app_state._STATE_TEXT_CACHE)
            self.assertIsNone(app_state._STATE_PARSED_CACHE)
            app_state.write_app_state(zipcode="21710")
            app_state.read_app_state()
            app_state.read_app_state_shared()
            self.assertIsNotNone(app_state._STATE_TEXT_CACHE)
            self.assertIsNotNone(app_state._STATE_PARSED_CACHE)
            inner.doCleanups()
            self.assertIs(app_state._STATE_TEXT_CACHE, text_sentinel)
            self.assertIs(app_state._STATE_PARSED_CACHE, parsed_sentinel)


class PageStateTests(_IsolatedStateTest):
    def test_status_lights(self) -> None:
        st = MainSettingsState(live_wifi_ssid="HomeNet", pigeon_metadata_ok=False, pigeon_audio_ok=True)
        root = self._root(st)
        self.assertEqual(ps._by_id(root, "settings_input_wifi_button").get("fill"), "#58FF00")
        self.assertEqual(ps._by_id(root, "settings_input_metadata_button").get("fill"), "#FF0000")
        self.assertEqual(ps._by_id(root, "settings_pigeon_09_audio_button").get("fill"), "#58FF00")
        self.assertEqual(ps._by_id(root, "settings_input_audio_dot_middle").get("fill"), "#58FF00")
        st = MainSettingsState(live_wifi_ssid="", pigeon_metadata_ok=True, pigeon_audio_ok=False)
        root = self._root(st)
        self.assertEqual(ps._by_id(root, "settings_input_wifi_button").get("fill"), "#FF0000")
        self.assertEqual(ps._by_id(root, "settings_input_metadata_button").get("fill"), "#58FF00")
        # Audio off: red tile; the middle ring follows the tile, not black.
        self.assertEqual(ps._by_id(root, "settings_pigeon_09_audio_button").get("fill"), "#FF0000")
        self.assertEqual(ps._by_id(root, "settings_input_audio_dot_middle").get("fill"), "#FF0000")

    def test_wifi_light_uses_network_route_when_ssid_hidden(self) -> None:
        # macOS hides the SSID from apps; wired links have none.
        root = self._root(MainSettingsState(live_wifi_ssid="", pigeon_network_ok=True))
        self.assertEqual(ps._by_id(root, "settings_input_wifi_button").get("fill"), "#58FF00")
        root = self._root(
            MainSettingsState(live_wifi_ssid="", pigeon_network_ok=True, wifi_logged_out=True)
        )
        self.assertEqual(ps._by_id(root, "settings_input_wifi_button").get("fill"), "#FF0000")

    def test_status_glyphs_are_black(self) -> None:
        for ok in (True, False):
            root = self._root(MainSettingsState(pigeon_metadata_ok=ok, pigeon_audio_ok=ok))
            icon = ps._by_id(root, "settings_input_metadata_icon")
            self.assertEqual(icon.get("fill"), "#000000")
            for dot in ("settings_input_audio_dot_outter", "settings_input_audio_dot_inner"):
                self.assertEqual(ps._by_id(root, dot).get("fill"), "#000000", dot)

    def test_rendered_status_glyphs_have_no_white(self) -> None:
        st = MainSettingsState(pigeon_network_ok=True, pigeon_metadata_ok=True, pigeon_audio_ok=True)
        frame = ps.render_pigeon_settings_bgra(st)
        x0, _ = ps._svg_to_px(1652.62, 0)
        x1, _ = ps._svg_to_px(1795.59, 0)
        _, y0 = ps._svg_to_px(0, 723.31)
        _, y1 = ps._svg_to_px(0, 763.26)
        tiles = frame[int(y0) : int(y1), int(x0) : int(x1), :3].astype(int)
        whiteish = (tiles.min(axis=2) > 200).sum()
        self.assertEqual(int(whiteish), 0)

    def test_version_text_is_right_aligned_pigeon_version(self) -> None:
        root = self._root(MainSettingsState(version_string="0.11.40"))
        text = ps._by_id(root, "settings_pigeon_version_text")
        self.assertEqual("".join(text.itertext()).strip(), "PIGEON 0.11.40")
        self.assertEqual(text.get("text-anchor"), "end")

    def test_zip_placeholder_and_saved_zip(self) -> None:
        root = self._root(MainSettingsState())
        self.assertEqual("".join(ps._by_id(root, "zipcode_00000_text").itertext()), "ENTER")
        pigeon_locale._write(zip="21710", zip_source="manual")
        root = self._root(MainSettingsState())
        self.assertEqual("".join(ps._by_id(root, "zipcode_00000_text").itertext()), "21710")

    def test_toggle_knob_sits_beside_active_label(self) -> None:
        root = self._root(
            MainSettingsState(options_values={"time_format": "24", "zone4_mode": "visualizer"})
        )
        for n, is_b in ((1, True), (2, False), (3, False), (4, True)):
            group = ps._option_group(root, n)
            knobs = [
                ps._child_with(group, "toggle_a_shape"),
                ps._child_with(group, "toggle_b_shape"),
            ]
            shown = [k for k in knobs if k.get("display") != "none"]
            self.assertEqual(len(shown), 1, n)
            label_y = ps._svg_y(ps._option_label(group, "b" if is_b else "a"))
            nearest = min(knobs, key=lambda k: abs(ps._svg_y(k) - label_y))
            self.assertIs(shown[0], nearest, n)

    def test_toggle_wells_stay_grey_on_white_theme(self) -> None:
        for key, well in (("white", "#777777"), ("grey", "#777777"), ("blue", "#4B9EEC")):
            theme = ucs.theme_from_color_keys({"accent": "white", "ui": key, "button": "black"})
            root = self._root(MainSettingsState(theme=theme))
            for n in ps.OPTION_NUMBERS:
                shape = ps._child_with(ps._option_group(root, n), "shape_ui_color")
                self.assertEqual(shape.get("fill", "").upper(), well, (key, n))

    def test_selected_tile_gets_white_stroke(self) -> None:
        st = MainSettingsState()
        st.pigeon_focus_index = ps.pigeon_focus_ring().index("color:grey")
        root = self._root(st)
        # The export names the grey button ``ui_color_red_button``; lookup is group-scoped.
        grey = ps._child_with(ps._by_id(root, "ui_color_grey_group"), "_butt")
        red = ps._child_with(ps._by_id(root, "ui_color_red_group"), "_butt")
        self.assertEqual(grey.get("stroke"), "#FFFFFF")
        self.assertEqual(red.get("stroke"), "#231F20")


class NavigationTests(_IsolatedStateTest):
    def test_color_row_previews_then_restores_committed(self) -> None:
        w = self._widget()
        self.assertEqual(w.state.ui_color_committed_key, "blue")
        self._focus(w, "color:red")
        self.assertEqual(w.state.theme.ui.upper(), "#FB0000")
        self._focus(w, "option:1")
        self.assertEqual(w.state.theme.ui.upper(), "#4B9EEC")
        self.assertEqual(ucs.read_ui_color_keys()["ui"], "blue")

    def test_activating_color_commits(self) -> None:
        w = self._widget()
        self._focus(w, "color:orange")
        self.assertEqual(w.activate(), "ui_color_swatch:ui:orange")
        self._focus(w, "reset")
        self.assertEqual(w.state.theme.ui.upper(), "#E39F00")
        self.assertEqual(ucs.read_ui_color_keys()["ui"], "orange")

    def test_option_activation_persists(self) -> None:
        w = self._widget()
        self._focus(w, "option:2")
        self.assertEqual(w.activate(), "options_toggle:2")
        from pigeon.widgets.options_settings import read_options

        self.assertEqual(read_options()["temp_format"], "c")

    def test_option4_toggles_zone4_visualizer(self) -> None:
        from pigeon.widgets.options_settings import zone4_visualizer_on

        w = self._widget()
        self.assertFalse(zone4_visualizer_on())
        self._focus(w, "option:4")
        self.assertEqual(w.activate(), "options_toggle:4")
        self.assertTrue(zone4_visualizer_on())
        w.activate()
        self.assertFalse(zone4_visualizer_on())

    def test_option5_sets_the_starting_mode_and_flips_it_now(self) -> None:
        from pigeon import visualizer_mode
        from pigeon.widgets.options_settings import zone6_visualizer_default

        w = self._widget()
        self.assertFalse(zone6_visualizer_default())
        self._focus(w, "option:5")
        self.assertEqual(w.activate(), "options_toggle:5")
        self.assertTrue(zone6_visualizer_default())
        self.assertTrue(visualizer_mode.is_active())
        w.activate()
        self.assertFalse(visualizer_mode.is_active())

    def test_timezone_dropdown_sets_manual_zone(self) -> None:
        pigeon_locale._write(timezone="America/New_York", tz_source="auto")
        w = self._widget()
        self._focus(w, "timezone")
        self.assertEqual(w.activate(), "timezone_dropdown_open")
        choices = pigeon_locale.timezone_choices()
        self.assertEqual(choices[w.state.tz_dropdown_index], "America/New_York")
        w.navigate(forward=False)
        self.assertEqual(w.activate(), "timezone_set:America/Chicago")
        self.assertFalse(w.state.tz_dropdown_open)
        self.assertEqual(pigeon_locale.read_timezone(), "America/Chicago")

    def test_zip_keyboard_saves_manual_zip(self) -> None:
        w = self._widget()
        self._focus(w, "zipcode")
        self.assertEqual(w.activate(), "keyboard_open:zipcode")
        w.state.keyboard.buffer = "21710"
        with mock.patch(
            "pigeon.widgets.settings_keyboard.activate_key", return_value="go"
        ), mock.patch("threading.Thread"):
            self.assertEqual(w.activate(), "keyboard_go:zipcode")
        self.assertIsNone(w.state.keyboard)
        self.assertEqual(pigeon_locale.read_zipcode(), "21710")

    def test_exit_returns_to_now_playing(self) -> None:
        w = self._widget()
        self._focus(w, "exit")
        self.assertEqual(w.activate(), "exit")
        self.assertFalse(w.state.show_pigeon_settings)


class LocaleTests(_IsolatedStateTest):
    def test_dropdown_label_is_offset_from_current(self) -> None:
        label = pigeon_locale.timezone_dropdown_label(
            "America/Chicago", relative_to="America/New_York"
        )
        self.assertRegex(label, r"^C[DS]T -1:00$")

    def test_auto_detect_never_replaces_manual_zip(self) -> None:
        pigeon_locale._write(zip="21710", zip_source="manual")
        with mock.patch.object(
            pigeon_locale, "_lookup_ip_location", return_value=("90210", "America/Los_Angeles")
        ):
            self.assertFalse(pigeon_locale.detect_location_blocking())
        self.assertEqual(pigeon_locale.read_zipcode(), "21710")

    def test_auto_detect_fills_zip_and_timezone(self) -> None:
        with mock.patch.object(
            pigeon_locale, "_lookup_ip_location", return_value=("90210", "America/Los_Angeles")
        ):
            self.assertTrue(pigeon_locale.detect_location_blocking())
        self.assertEqual(pigeon_locale.read_zipcode(), "90210")
        self.assertEqual(pigeon_locale.read_timezone(), "America/Los_Angeles")


class RetiredCustomizationTests(_IsolatedStateTest):
    def test_saved_zone_layout_is_ignored(self) -> None:
        from pigeon.widgets.preferences_settings import (
            DEFAULT_ZONE_WIDGETS,
            read_now_playing_zone_widgets,
        )

        app_state.write_app_state(
            now_playing_zone_widgets={"1": "", "2": "", "3": "cast_info", "4": "volume", "5": ""}
        )
        self.assertEqual(read_now_playing_zone_widgets(), DEFAULT_ZONE_WIDGETS)

    def test_retired_options_read_as_defaults(self) -> None:
        from pigeon.widgets.options_settings import (
            clock_saver_enabled,
            clock_saver_idle_s,
            write_options,
        )

        write_options({"clock_saver": "off", "idle_standby": 120})
        self.assertTrue(clock_saver_enabled())
        self.assertEqual(clock_saver_idle_s(), 60.0)

    def test_legacy_ui_keys(self) -> None:
        app_state.write_app_state(settings_ui_colors={"ui": "bright"})
        self.assertEqual(ucs.read_ui_color_keys()["ui"], "white")
        app_state.write_app_state(settings_ui_colors={"ui": "dark"})
        self.assertEqual(ucs.read_ui_color_keys()["ui"], "blue")
        app_state.write_app_state(settings_ui_colors={"ui": "gray"})
        self.assertEqual(ucs.read_ui_color_keys()["ui"], "grey")


class RenderTests(_IsolatedStateTest):
    def test_clip_paths_are_applied(self) -> None:
        frame = ps.render_pigeon_settings_bgra(MainSettingsState())
        self.assertEqual(frame.shape, (800, 1280, 4))
        # Reset arc (circle clipped by a rotated rect): white ink on the tile.
        reset = frame[465:545, 920:1025, :3]
        self.assertGreater(int(np.count_nonzero(np.all(reset > 200, axis=2))), 300)
        # Update bar: gray only on the clipped right end, white on the left.
        self.assertTrue(np.all(frame[515, 1100, :3] > 200))
        self.assertTrue(np.all(np.abs(frame[515, 1175, :3].astype(int) - 0x4A) < 12))

    def test_clock_overlay_draws_in_its_span(self) -> None:
        from datetime import datetime

        base = np.zeros((800, 1280, 4), dtype=np.uint8)
        out = ps.draw_pigeon_settings_clock(base, now=datetime(2026, 9, 26, 10, 6, 15))
        ys, xs = np.nonzero(out[:, :, 3])
        self.assertGreater(len(xs), 0)
        self.assertGreaterEqual(int(xs.min()), int(1125.0 - ps._PIGEON_VIEWBOX[0]))
        self.assertLessEqual(int(xs.max()), int(1316.0 - ps._PIGEON_VIEWBOX[0]))


if __name__ == "__main__":
    unittest.main()
