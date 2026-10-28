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
        for _ in range(len(ps.pigeon_focus_ring(w.state.pigeon_view))):
            if w.state.pigeon_focused_id == fid:
                return
            w.navigate(forward=True)
        self.fail(f"{fid} not reachable")


class FocusRingTests(unittest.TestCase):
    def test_navigation_order_per_menu(self) -> None:
        self.assertEqual(
            ps.pigeon_focus_ring("general"),
            (
                "exit",
                "update",
                "reset",
                "restart",
                "option:5",
                "sports",
                "section2",
                "section3",
            ),
        )
        self.assertEqual(
            ps.pigeon_focus_ring("theme"),
            (
                "exit",
                "color:blue",
                "color:green",
                "color:yellow",
                "color:pink",
                "color:red",
                "option:7",
                "section2",
                "section3",
            ),
        )
        self.assertEqual(
            ps.pigeon_focus_ring("clock"),
            ("exit", "option:1", "zipcode", "timezone", "option:6", "option:2", "section2", "section3"),
        )

    def test_default_menu_is_general(self) -> None:
        self.assertEqual(ps.pigeon_focus_ring(), ps.pigeon_focus_ring("general"))
        self.assertEqual(ps.normalize_view("bogus"), "general")

    def test_section_buttons_swap_with_open_menu(self) -> None:
        self.assertEqual(ps.section_targets("general"), ("theme", "clock"))
        self.assertEqual(ps.section_targets("theme"), ("general", "clock"))
        self.assertEqual(ps.section_targets("clock"), ("theme", "general"))
        self.assertEqual(ps.view_for_section("theme", "section2"), "general")
        self.assertEqual(ps.view_for_section("clock", "section3"), "general")
        self.assertIsNone(ps.view_for_section("clock", "zipcode"))

    def test_six_tiles_per_menu_and_tbd_is_not_focusable(self) -> None:
        for view in ps.VIEWS:
            self.assertEqual(len(ps.view_slots(view)), 6, view)
        for slot in ps.view_slots("general") + ps.view_slots("clock"):
            if slot.kind.startswith("tbd"):
                self.assertEqual(slot.focus_id, "")

    def test_only_color_tiles_preview_a_ui_color(self) -> None:
        self.assertIsNone(ps.color_key_for_focus("option:7"))
        self.assertEqual(ps.color_key_for_focus("color:pink"), "pink")

    def test_theme_tiles_have_a_swatch(self) -> None:
        for key in ps.THEME_KEYS:
            self.assertRegex(ucs.hex_for_color_key("ui", key), r"^#[0-9A-Fa-f]{6}$", key)
        self.assertEqual(ucs.hex_for_color_key("ui", "pink").upper(), "#FF5CA8")

    def test_svg_has_the_eight_buttons(self) -> None:
        root = ET.parse(ps.default_pigeon_settings_svg_path()).getroot()
        for n in range(1, 7):
            self.assertIsNotNone(ps._by_id(root, f"toggle_0{n}_group"), n)
        for ident in ("section2_theme", "section2_general", "section3_clock", "exit_button"):
            self.assertIsNotNone(ps._by_id(root, ident), ident)


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

    def _texts(self, root: ET.Element) -> list[str]:
        return ["".join(t.itertext()).strip() for t in root.iter() if t.tag.endswith("text")]

    def _state(self, view: str, focus: str = "", **kw) -> MainSettingsState:
        st = MainSettingsState(**kw)
        st.pigeon_view = view
        ring = ps.pigeon_focus_ring(view)
        st.pigeon_focus_index = ring.index(focus) if focus in ring else 0
        return st

    def _tile_stroke(self, root: ET.Element, n: int) -> str:
        group = ps._by_id(root, f"toggle_0{n}_group")
        return next(c for c in group if ps._local(c) in ("rect", "path")).get("stroke")

    def test_zip_placeholder_and_saved_zip(self) -> None:
        root = self._root(self._state("clock"))
        self.assertIn("ENTER", self._texts(root))
        pigeon_locale._write(zip="21710", zip_source="manual")
        root = self._root(self._state("clock"))
        self.assertIn("21710", self._texts(root))
        self.assertNotIn("ENTER", self._texts(root))

    def test_section_names_follow_the_open_menu(self) -> None:
        for view, names in (
            ("general", ["general", "theme", "clock"]),
            ("theme", ["theme", "general", "clock"]),
            ("clock", ["clock", "theme", "general"]),
        ):
            root = self._root(self._state(view))
            # Hidden section art is pruned at render; the tree still holds it.
            visible = [
                "".join(t.itertext()).strip()
                for t in root.iter()
                if t.tag.endswith("text") and not self._hidden(root, t)
                and "".join(t.itertext()).strip() in ("general", "theme", "clock")
            ]
            self.assertEqual(sorted(visible), sorted(names), view)

    def _hidden(self, root: ET.Element, el: ET.Element) -> bool:
        parents = {c: p for p in root.iter() for c in p}
        while el is not None:
            if el.get("display") == "none":
                return True
            el = parents.get(el)
        return False

    def test_general_tiles(self) -> None:
        root = self._root(self._state("general"))
        texts = self._texts(root)
        for label in ("RESET", "RESTART", "UPDATE", "TBD", "ZONE 11", "SPORTS", "OFF"):
            self.assertIn(label, texts, label)
        self.assertNotIn("°F", texts)  # moved to the clock menu

    def test_clock_tiles(self) -> None:
        root = self._root(self._state("clock"))
        texts = self._texts(root)
        for label in ("12 HR", "24 HR", "ZIP", "TIME ZONE", "DIGITAL", "ANALOG", "°F", "°C", "TBD"):
            self.assertIn(label, texts, label)

    def test_toggle_knob_follows_the_option(self) -> None:
        for values, slot_n, top in (
            ({}, 5, True),
            ({"temp_format": "c"}, 5, False),
        ):
            root = self._root(self._state("clock", options_values=values))
            group = ps._by_id(root, f"toggle_0{slot_n}_group")
            graphics = next(c for c in group if ps._local(c) == "g")
            _c, knobs, _l = ps._toggle_parts(graphics)
            shown = [k for k in knobs if k.get("display") != "none"]
            self.assertEqual(len(shown), 1, (values, slot_n))
            self.assertIs(shown[0], knobs[0] if top else knobs[1], (values, slot_n))

    def test_clock_toggles_follow_options(self) -> None:
        root = self._root(self._state("clock", options_values={"time_format": "24", "clock_format": "analog"}))
        for slot_n in (1, 4):
            graphics = next(c for c in ps._by_id(root, f"toggle_0{slot_n}_group") if ps._local(c) == "g")
            _c, knobs, _l = ps._toggle_parts(graphics)
            self.assertEqual([k.get("display") for k in knobs], ["none", None], slot_n)

    def test_toggle_wells_stay_grey_on_white_theme(self) -> None:
        for key, well in (("white", "#777777"), ("grey", "#777777"), ("blue", "#4B9EEC")):
            theme = ucs.theme_from_color_keys({"accent": "white", "ui": key, "button": "black"})
            root = self._root(self._state("general", theme=theme))
            group = ps._by_id(root, "toggle_05_group")  # ZONE 11 / ZONE 6,3
            container, _k, _l = ps._toggle_parts(next(c for c in group if ps._local(c) == "g"))
            self.assertEqual(container.get("fill", "").upper(), well, key)

    def test_selected_tile_gets_white_stroke(self) -> None:
        root = self._root(self._state("general", "reset"))
        self.assertEqual(self._tile_stroke(root, 2), "#FFFFFF")
        self.assertEqual(self._tile_stroke(root, 3), "#231F20")

    def test_selected_section_button_gets_white_stroke(self) -> None:
        root = self._root(self._state("general", "section3"))
        self.assertEqual(ps._by_id(root, "clock_container").get("stroke"), "#FFFFFF")
        theme_rect = ps._first_rect(ps._by_id(root, "section2_theme"))
        self.assertEqual(theme_rect.get("stroke"), "#231F20")

    def test_theme_tiles_show_color_dots(self) -> None:
        root = self._root(self._state("theme"))
        fills = []
        for n in range(1, 6):
            group = ps._by_id(root, f"toggle_0{n}_group")
            dots = [c for c in group if ps._local(c) == "circle"]
            self.assertEqual(len(dots), 1, n)
            fills.append(dots[0].get("fill").upper())
        self.assertEqual(fills, ["#4B9EEC", "#00A22D", "#E5FF0C", "#FF5CA8", "#FB0000"])
        # Tile 6 is the STANDARD / SIMPLE toggle, not a color.
        group = ps._by_id(root, "toggle_06_group")
        self.assertFalse([c for c in group if ps._local(c) == "circle"])

    def test_update_badge_only_when_an_update_exists(self) -> None:
        def dots(root: ET.Element) -> list[ET.Element]:
            group = ps._by_id(root, "toggle_01_group")
            return [c for c in group if ps._local(c) == "circle"]

        self.assertEqual(dots(self._root(self._state("general"))), [])
        badge = dots(self._root(self._state("general", update_available=True)))
        self.assertEqual(len(badge), 1)
        self.assertEqual(badge[0].get("fill").upper(), "#FF0000")

    def test_clock_hands_survive_the_background_sweep(self) -> None:
        root = self._root(self._state("general"))
        for hand in ("clock_hand_minute", "clock_hand_hour", "clock_hand_second"):
            el = ps._by_id(root, hand)
            self.assertEqual(ps._local(el), "polygon", hand)


class NavigationTests(_IsolatedStateTest):
    def _open_menu(self, w: MainSettingsWidget, view: str) -> None:
        """Activate the section button that loads ``view`` into section1."""
        for _ in range(3):
            if w.state.pigeon_view == view:
                return
            sec = "section2" if ps.section_targets(w.state.pigeon_view)[0] == view else "section3"
            self._focus(w, sec)
            w.activate()
        self.assertEqual(w.state.pigeon_view, view)

    def test_opens_on_general_at_first_tile(self) -> None:
        w = self._widget()
        self.assertEqual(w.state.pigeon_view, "general")
        self.assertEqual(w.state.pigeon_focused_id, "update")

    def test_section_buttons_open_menus_and_turn_into_general(self) -> None:
        w = self._widget()
        self._focus(w, "section2")
        self.assertEqual(w.activate(), "pigeon_view:theme")
        self.assertEqual(w.state.pigeon_view, "theme")
        # Focus stays on the button that was pressed — now the way back.
        self.assertEqual(w.state.pigeon_focused_id, "section2")
        self.assertEqual(w.activate(), "pigeon_view:general")
        self.assertEqual(w.state.pigeon_view, "general")
        self._focus(w, "section3")
        self.assertEqual(w.activate(), "pigeon_view:clock")
        self.assertEqual(w.state.pigeon_focused_id, "section3")
        self.assertEqual(w.activate(), "pigeon_view:general")

    def test_clock_menu_hands_section2_back_to_theme(self) -> None:
        w = self._widget()
        self._open_menu(w, "clock")
        self._focus(w, "section2")
        self.assertEqual(w.activate(), "pigeon_view:theme")

    def test_theme_row_previews_then_restores_committed(self) -> None:
        w = self._widget()
        self._open_menu(w, "theme")
        self.assertEqual(w.state.ui_color_committed_key, "blue")
        self._focus(w, "color:red")
        self.assertEqual(w.state.theme.ui.upper(), "#FB0000")
        self._focus(w, "color:pink")
        self.assertEqual(w.state.theme.ui.upper(), "#FF5CA8")
        self._focus(w, "section3")
        self.assertEqual(w.state.theme.ui.upper(), "#4B9EEC")
        self.assertEqual(ucs.read_ui_color_keys()["ui"], "blue")

    def test_leaving_theme_menu_drops_the_preview(self) -> None:
        w = self._widget()
        self._open_menu(w, "theme")
        self._focus(w, "color:green")
        self._focus(w, "section2")
        self.assertEqual(w.state.theme.ui.upper(), "#4B9EEC")

    def test_activating_color_commits(self) -> None:
        w = self._widget()
        self._open_menu(w, "theme")
        self._focus(w, "color:pink")
        self.assertEqual(w.activate(), "ui_color_swatch:ui:pink")
        self._focus(w, "section2")
        self.assertEqual(w.state.theme.ui.upper(), "#FF5CA8")
        self.assertEqual(ucs.read_ui_color_keys()["ui"], "pink")

    def test_style_toggle_switches_between_standard_and_simple(self) -> None:
        from pigeon.widgets.options_settings import read_options, ui_is_simple

        w = self._widget()
        self._open_menu(w, "theme")
        self.assertFalse(ui_is_simple())
        self._focus(w, "option:7")
        self.assertEqual(w.activate(), "options_toggle:7")
        self.assertTrue(ui_is_simple())
        self.assertEqual(read_options()["ui_style"], "simple")
        # The toggle never re-themes the page.
        self.assertEqual(w.state.theme.ui.upper(), "#4B9EEC")
        self.assertEqual(w.activate(), "options_toggle:7")
        self.assertFalse(ui_is_simple())

    def test_simple_style_is_black_and_the_ui_color_only(self) -> None:
        from pigeon.widgets.options_settings import set_option_value

        w = self._widget()
        self._open_menu(w, "theme")
        w.state.options_values = set_option_value("ui_style", "simple", None)
        frame = ps.render_pigeon_settings_bgra(w.state, assets_dir=None)
        self.assertTrue((frame[5:15, 640:660, :3] == 0).all())  # no background layer
        w.state.options_values = set_option_value("ui_style", "standard", None)
        std = ps.render_pigeon_settings_bgra(w.state, assets_dir=None)
        self.assertFalse((std[200:210, 640:660, :3] == 0).all())

    def test_simple_style_highlights_the_focused_clock_button(self) -> None:
        from pigeon.widgets.options_settings import set_option_value

        def fills(focus: str) -> tuple[str, str]:
            st = MainSettingsState()
            st.options_values = set_option_value("ui_style", "simple", None)
            ring = ps.pigeon_focus_ring("general")
            st.pigeon_focus_index = ring.index(focus)
            root = self._root(st)
            return (
                ps._by_id(root, "clock_container").get("fill").upper(),
                ps._by_id(root, "clock_hand_hour").get("fill").upper(),
            )

        ui = ps._ui_hex(MainSettingsState()).upper()
        # Focused: UI-color fill like section2, hands flipped to the UI color.
        self.assertEqual(fills("section3"), (ui, ui))
        self.assertEqual(fills("section2"), ("#000000", "#000000"))

    def test_color_tiles_preview_in_full_color_while_in_dark_mode(self) -> None:
        from pigeon.widgets.options_settings import set_mono_preview_off, ui_is_monochrome

        self.addCleanup(set_mono_preview_off, False)
        w = self._widget()
        self._open_menu(w, "theme")
        from pigeon.widgets.options_settings import set_option_value

        w.state.options_values = set_option_value("color_format", "dark", None)
        self._focus(w, "color:blue")
        self._focus(w, "color:green")  # preview: not dimmed
        self.assertFalse(ui_is_monochrome())
        self.assertEqual(w.state.theme.ui.upper(), "#00A22D")
        self._focus(w, "option:7")  # off the colors: dark again
        self.assertTrue(ui_is_monochrome())
        self._focus(w, "color:red")
        self.assertFalse(ui_is_monochrome())
        self._focus(w, "section2")  # off the tiles: dark again
        self.assertTrue(ui_is_monochrome())
        self._focus(w, "exit")
        w.activate()
        self.assertTrue(ui_is_monochrome())

    def test_temp_toggle_persists(self) -> None:
        w = self._widget()
        self._open_menu(w, "clock")  # °F / °C lives with the clock settings
        self._focus(w, "option:2")
        self.assertEqual(w.activate(), "options_toggle:2")
        from pigeon.widgets.options_settings import read_options

        self.assertEqual(read_options()["temp_format"], "c")

    def test_auto_update_is_mandatory(self) -> None:
        from pigeon.widgets.options_settings import auto_update_enabled, write_options

        write_options({"auto_update": "manual"})
        self.assertTrue(auto_update_enabled())

    def test_clock_mode_and_format_toggles(self) -> None:
        from pigeon.widgets.options_settings import (
            clock_uses_24h,
            clock_widget_analog,
        )

        w = self._widget()
        self._open_menu(w, "clock")
        self._focus(w, "option:1")
        self.assertEqual(w.activate(), "options_toggle:1")
        self.assertTrue(clock_uses_24h())
        self._focus(w, "option:6")
        self.assertEqual(w.activate(), "options_toggle:6")
        self.assertTrue(clock_widget_analog())
        w.activate()
        self.assertFalse(clock_widget_analog())

    def test_general_buttons_report_their_actions(self) -> None:
        w = self._widget()
        self._focus(w, "reset")
        self.assertEqual(w.activate(), "pigeon_factory_reset")
        self._focus(w, "restart")
        self.assertEqual(w.activate(), "pigeon_restart")
        self._focus(w, "update")
        self.assertEqual(w.activate(), "update_popup:open")

    def test_tbd_tiles_are_skipped_by_focus(self) -> None:
        w = self._widget()
        seen = set()
        for _ in range(len(ps.pigeon_focus_ring("general")) * 2):
            seen.add(w.state.pigeon_focused_id)
            w.navigate(forward=True)
        self.assertEqual(seen, set(ps.pigeon_focus_ring("general")))

    def test_exit_menu_resets_to_general(self) -> None:
        w = self._widget()
        self._open_menu(w, "clock")
        self._focus(w, "exit")
        self.assertEqual(w.activate(), "exit")
        self.assertFalse(w.state.show_pigeon_settings)
        self.assertEqual(w.state.pigeon_view, "general")

    def test_timezone_dropdown_sets_manual_zone(self) -> None:
        pigeon_locale._write(timezone="America/New_York", tz_source="auto")
        w = self._widget()
        self._open_menu(w, "clock")
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
        self._open_menu(w, "clock")
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
    def _frame(self, view: str) -> np.ndarray:
        st = MainSettingsState()
        st.pigeon_view = view
        return ps.render_pigeon_settings_bgra(st)

    def test_every_menu_renders(self) -> None:
        frames = {v: self._frame(v) for v in ps.VIEWS}
        for view, frame in frames.items():
            self.assertEqual(frame.shape, (800, 1280, 4), view)
        self.assertFalse(np.array_equal(frames["general"], frames["theme"]))
        self.assertFalse(np.array_equal(frames["general"], frames["clock"]))

    def test_clock_icon_hands_render_white(self) -> None:
        # Section3 shows the clock icon on general/theme: its hands are white ink.
        x, y = ps._svg_to_px(1635.8, 1128.0)
        region = self._frame("general")[int(y) - 10 : int(y) + 100, int(x) - 60 : int(x) + 10, :3]
        self.assertGreater(int(np.count_nonzero(np.all(region > 240, axis=2))), 150)

    def test_section3_general_art_is_shifted_onto_section3(self) -> None:
        frame = self._frame("clock")
        x, y = ps._svg_to_px(1636.0, 1128.0)
        # The "general" disc is the UI color (blue) there, not the dark container.
        self.assertGreater(int(frame[int(y) + 70, int(x), 0]), 0xC0)

    def test_timezone_dropdown_overlays_section2(self) -> None:
        st = MainSettingsState()
        st.pigeon_view = "clock"
        st.tz_dropdown_open = True
        with_list = ps.render_pigeon_settings_bgra(st)
        st.tz_dropdown_open = False
        without = ps.render_pigeon_settings_bgra(st)
        self.assertFalse(np.array_equal(with_list, without))

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
