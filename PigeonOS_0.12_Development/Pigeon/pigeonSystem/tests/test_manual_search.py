"""Manual title search: persistence, conflict window, SEARCH bar, keyboard rows."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import manual_search as ms  # noqa: E402
from pigeon import runtime_paths  # noqa: E402

ASSETS = Path(__file__).resolve().parents[2] / "pigeonAssets"


def _reset_module(state_dir: Path) -> None:
    runtime_paths._CACHED = state_dir
    ms._entry = None
    ms._loaded = False
    ms._conflict_active = False
    ms._auto_active = False
    ms._shown = False
    ms._manual_query = ""
    ms._spawn_hook = None
    ms._clear_display_hook = None
    ms.reset_suggestions()


class ManualSearchStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = runtime_paths._CACHED
        _reset_module(Path(self._tmp.name))

    def tearDown(self) -> None:
        runtime_paths._CACHED = self._prev
        self._tmp.cleanup()

    def test_title_persists_until_cleared(self) -> None:
        ms.set_entry({"title": "The Office", "year": "2005", "kind": "tv", "tmdb_id": 2316})
        ms._loaded = False
        ms._entry = None  # simulate a restart
        self.assertEqual(ms.current_title(), "The Office")
        self.assertEqual(ms.current()["year"], "2005")
        ms.clear()
        ms._loaded = False
        self.assertEqual(ms.current_title(), "")

    def test_blank_title_is_rejected(self) -> None:
        self.assertIsNone(ms.set_entry({"title": "   "}))
        self.assertEqual(ms.current_title(), "")

    def test_titles_match_is_forgiving_but_not_loose(self) -> None:
        self.assertTrue(ms.titles_match("the office", "The Office"))
        self.assertTrue(ms.titles_match("The Office (US)", "The Office"))
        self.assertFalse(ms.titles_match("Severance", "The Office"))
        self.assertFalse(ms.titles_match("", "The Office"))

    def test_mismatching_metadata_hides_poster_only_while_detected(self) -> None:
        ms.set_entry({"title": "The Office"})
        self.assertTrue(ms.poster_allowed())
        ms.note_detected_query("The Office")  # matches: no conflict
        self.assertTrue(ms.poster_allowed())
        ms.note_detected_query("Severance")  # metadata wins
        self.assertFalse(ms.poster_allowed())
        ms.note_detected_query("Ted Lasso")
        self.assertFalse(ms.poster_allowed())
        ms.on_content_idle()  # detection ended: poster is back immediately
        self.assertTrue(ms.poster_allowed())

    def test_matching_metadata_clears_an_earlier_conflict(self) -> None:
        ms.set_entry({"title": "The Office"})
        ms.note_detected_query("Severance")
        self.assertFalse(ms.poster_allowed())
        ms.note_detected_query("The Office")
        self.assertTrue(ms.poster_allowed())

    def test_no_manual_title_never_conflicts(self) -> None:
        ms.note_detected_query("Severance", now=10.0)
        self.assertTrue(ms.poster_allowed(now=11.0))

    def test_idle_falls_back_to_manual_title_once(self) -> None:
        calls: list[tuple[str, dict]] = []
        ms.install_hooks(spawn=lambda q, **kw: calls.append((q, kw)))
        ms.set_entry({"title": "The Office", "year": "2005", "kind": "tv"})
        ms.note_detected_query("Severance", now=5.0)  # auto content playing
        self.assertFalse(ms.show_in_now_playing())  # detection wins
        self.assertEqual(calls, [])
        ms.on_content_idle()  # content ended
        self.assertEqual([c[0] for c in calls], ["The Office (2005)"])
        self.assertTrue(ms.is_displaying())
        ms.on_content_idle()  # later idle polls must not respawn
        self.assertEqual(len(calls), 1)
        ms.note_detected_query("Ted Lasso", now=9.0)  # detection again
        self.assertFalse(ms.is_displaying())

    def test_own_spawn_is_not_a_detection(self) -> None:
        ms.install_hooks(spawn=lambda q, **kw: ms.note_detected_query(q, now=7.0))
        ms.set_entry({"title": "The Office", "year": "2005"})
        self.assertTrue(ms.show_in_now_playing())
        self.assertTrue(ms.is_displaying())
        self.assertFalse(ms.auto_detected_active())

    def test_clear_drops_displayed_title(self) -> None:
        dropped: list[int] = []
        ms.install_hooks(
            spawn=lambda q, **kw: None, clear_display=lambda: dropped.append(1)
        )
        ms.set_entry({"title": "The Office"})
        ms.show_in_now_playing()
        ms.clear()
        self.assertEqual(dropped, [1])
        self.assertFalse(ms.is_displaying())


class SearchBarTests(unittest.TestCase):
    def _state(self, title: str = ""):
        from pigeon.widgets.main_settings import MainSettingsState

        st = MainSettingsState()
        st.selected_wifi_ssid = "HomeNet"
        st.live_wifi_ssid = "HomeNet"
        st.manual_search_title = title
        st.ensure_focus_ring()
        return st

    def test_search_is_last_in_ring_and_clear_only_with_title(self) -> None:
        st = self._state()
        self.assertEqual(st.focus_ring[-1], "main_search_button")
        self.assertNotIn("main_search_clear_button", st.focus_ring)
        st = self._state("The Office")
        self.assertEqual(
            st.focus_ring[-2:], ("main_search_button", "main_search_clear_button")
        )

    def test_search_yields_to_lists(self) -> None:
        st = self._state()
        st.show_location_picker = True
        st.ensure_focus_ring()
        self.assertNotIn("main_search_button", st.focus_ring)

    def test_bar_changes_pixels_and_clear_label_shows_with_title(self) -> None:
        from pigeon.settings_layout import SETTINGS_MAIN_ZONES
        from pigeon.widgets.settings_main_1280 import (
            clear_settings_main_compose_cache,
            render_settings_main_1280_bgra,
        )

        zx, zy, zw, zh = SETTINGS_MAIN_ZONES[5].xywh
        clear_settings_main_compose_cache()
        idle = render_settings_main_1280_bgra(self._state(), assets_dir=ASSETS)
        clear_settings_main_compose_cache()
        titled = render_settings_main_1280_bgra(
            self._state("The Office"), assets_dir=ASSETS
        )
        a = idle[zy : zy + zh, zx : zx + zw, :3].astype(int)
        b = titled[zy : zy + zh, zx : zx + zw, :3].astype(int)
        self.assertGreater(int(np.abs(a - b).sum()), 10000)
        # Nothing above the SEARCH strip changed.
        np.testing.assert_array_equal(idle[: zy - 10], titled[: zy - 10])

    def test_column_focus_changes_do_not_erase_search_bar(self) -> None:
        from pigeon.settings_layout import SETTINGS_MAIN_ZONES
        from pigeon.widgets.settings_main_1280 import (
            clear_settings_main_compose_cache,
            render_settings_main_1280_bgra,
        )

        zx, zy, zw, zh = SETTINGS_MAIN_ZONES[5].xywh
        clear_settings_main_compose_cache()
        st = self._state()
        reference = None
        for focus in ("main_box1_button", "main_box2_button", "main_box3_button",
                      "main_box2_button", "main_box1_button"):
            st.focus_main_button(focus)
            frame = render_settings_main_1280_bgra(st, assets_dir=ASSETS)
            strip = frame[zy : zy + zh, zx : zx + zw, :3].copy()
            if reference is None:
                reference = strip
            np.testing.assert_array_equal(strip, reference, err_msg=focus)

    def test_focus_moves_between_search_and_clear(self) -> None:
        st = self._state("The Office")
        self.assertTrue(st.focus_main_button("main_search_clear_button"))
        self.assertEqual(st.focused_id, "main_search_clear_button")
        self.assertEqual(st.manual_search_title, "The Office")


class SearchKeyboardTests(unittest.TestCase):
    def _kb(self):
        from pigeon.widgets.settings_keyboard import open_keyboard

        return open_keyboard(target="search", assets_dir=ASSETS)

    def test_suggestion_keys_trail_the_ring_and_skip_when_empty(self) -> None:
        from pigeon.widgets.settings_keyboard import KeyAction, SEARCH_ROWS

        kb = self._kb()
        tail = kb.focus_ring[-SEARCH_ROWS:]
        self.assertTrue(all(k.action == KeyAction.SUGGEST for k in tail))
        # No suggestions yet: wrapping left from Q never lands on a virtual key.
        kb.focus_index = 0
        kb.navigate(forward=False)
        self.assertNotEqual(kb.focused.action, KeyAction.SUGGEST)
        kb.suggestions = ("THE OFFICE (2005)", "THE OFFICE (2001)")
        kb.focus_index = 0
        kb.navigate(forward=False)
        self.assertEqual(kb.focused.action, KeyAction.SUGGEST)
        self.assertEqual(kb.focused.char, "1")  # last available row

    def test_pick_suggestion_pins_title(self) -> None:
        from pigeon.widgets.main_settings import MainSettingsWidget

        tmp = tempfile.TemporaryDirectory()
        prev = runtime_paths._CACHED
        try:
            _reset_module(Path(tmp.name))
            w = MainSettingsWidget(assets_dir=ASSETS)
            st = w.state
            st.selected_wifi_ssid = st.live_wifi_ssid = "HomeNet"
            st.ensure_focus_ring()
            st.focus_main_button("main_search_button")
            self.assertEqual(w.activate(), "keyboard_open:search")
            self.assertEqual(st.keyboard.target, "search")
            ms._suggest_results = (
                {"title": "The Office", "year": "2005", "kind": "tv",
                 "tmdb_id": 2316, "poster_path": ""},
            )
            self.assertTrue(st.sync_search_suggestions())
            from pigeon.widgets.settings_keyboard import KeyAction

            st.keyboard.focus_index = next(
                i for i, k in enumerate(st.keyboard.focus_ring)
                if k.action == KeyAction.SUGGEST and k.char == "0"
            )
            self.assertEqual(w.activate(), "manual_search:set")
            self.assertFalse(st.keyboard_open)
            self.assertEqual(st.manual_search_title, "The Office")
            self.assertEqual(ms.current()["tmdb_id"], 2316)
            self.assertEqual(st.focused_id, "main_search_button")
            st.focus_main_button("main_search_clear_button")
            self.assertEqual(w.activate(), "manual_search:clear")
            self.assertEqual(st.manual_search_title, "")
            self.assertEqual(ms.current_title(), "")
        finally:
            runtime_paths._CACHED = prev
            tmp.cleanup()

    def test_search_overlay_is_painted_while_nav_scrubbing(self) -> None:
        from pigeon.widgets.main_settings import MainSettingsWidget

        tmp = tempfile.TemporaryDirectory()
        prev = runtime_paths._CACHED
        try:
            _reset_module(Path(tmp.name))
            w = MainSettingsWidget(assets_dir=ASSETS)
            st = w.state
            st.selected_wifi_ssid = st.live_wifi_ssid = "HomeNet"
            st.ensure_focus_ring()
            st.open_keyboard("search", assets_dir=ASSETS)
            st.keyboard.buffer = "THE OFFICE"
            w._nav_scrub = False
            a = np.zeros((800, 1280, 3), dtype=np.uint8)
            w.render(a)
            w._nav_scrub = True
            b = np.zeros((800, 1280, 3), dtype=np.uint8)
            w.render(b)
            # Field strip (dual bar rows) identical apart from the blinking caret.
            fa, fb = a[200:305, 60:1220].astype(int), b[200:305, 60:1220].astype(int)
            self.assertLess(int((np.abs(fa - fb).sum(axis=2) > 0).sum()), 400)
        finally:
            runtime_paths._CACHED = prev
            tmp.cleanup()

    def test_enter_with_typed_text_pins_free_text(self) -> None:
        from pigeon.widgets.main_settings import MainSettingsWidget
        from pigeon.widgets.settings_keyboard import KeyAction

        tmp = tempfile.TemporaryDirectory()
        prev = runtime_paths._CACHED
        try:
            _reset_module(Path(tmp.name))
            w = MainSettingsWidget(assets_dir=ASSETS)
            st = w.state
            st.selected_wifi_ssid = st.live_wifi_ssid = "HomeNet"
            st.ensure_focus_ring()
            st.open_keyboard("search", assets_dir=ASSETS)
            st.keyboard.buffer = "  my  home movie "
            st.keyboard.focus_index = next(
                i for i, k in enumerate(st.keyboard.focus_ring) if k.action == KeyAction.GO
            )
            self.assertEqual(w.activate(), "manual_search:set")
            self.assertEqual(ms.current_title(), "my home movie")
        finally:
            runtime_paths._CACHED = prev
            tmp.cleanup()


class ClockSaverSplitTests(unittest.TestCase):
    def test_boxes_leave_edge_padding_and_clock_left_of_poster(self) -> None:
        from pigeon.design import DESIGN_H, DESIGN_W
        from pigeon.widgets.clock_saver import clock_saver_poster_split_boxes

        (cx, cy, cw, ch), (px, py, pw, ph) = clock_saver_poster_split_boxes()
        self.assertGreater(cx, 0)
        self.assertGreater(py, 0)
        self.assertLessEqual(cx + cw, px)
        self.assertLess(px + pw, DESIGN_W)
        self.assertLess(py + ph, DESIGN_H)
        self.assertAlmostEqual(pw / ph, 2.0 / 3.0, places=2)

    def test_faint_backdrop_does_not_become_an_outline(self) -> None:
        from pigeon.design import DESIGN_H, DESIGN_W
        from pigeon.widgets.clock_saver import (
            clock_saver_poster_split_boxes,
            compose_clock_with_poster,
        )

        frame = np.zeros((DESIGN_H, DESIGN_W, 4), dtype=np.uint8)
        frame[:, :, :3] = 15  # faint translucent backdrop behind the digits
        frame[:, :, 3] = 80
        frame[300:500, 200:1000] = (255, 255, 0, 255)  # lit ink
        poster = np.full((600, 400, 3), 90, dtype=np.uint8)
        out = compose_clock_with_poster(frame, poster)
        (cx, cy, cw, ch), _ = clock_saver_poster_split_boxes()
        clock = out[cy : cy + ch, cx : cx + cw]
        lit = clock[:, :, 3] > 0
        ys, xs = np.where(lit)
        self.assertGreater(xs.size, 0)
        # Ink is 800x200 in the source and scales to ~680x170; the whole
        # backdrop (1280x800 -> ~680x425) must not survive as a box around it.
        self.assertLess(int(lit.sum()), int(680 * 170 * 1.1))
        self.assertLess(int(ys.max() - ys.min()), 200)

    def test_compose_places_poster_right_and_shrinks_clock(self) -> None:
        from pigeon.design import DESIGN_H, DESIGN_W
        from pigeon.widgets.clock_saver import (
            clock_saver_poster_split_boxes,
            compose_clock_with_poster,
        )

        frame = np.zeros((DESIGN_H, DESIGN_W, 4), dtype=np.uint8)
        frame[300:500, 100:1180] = (255, 255, 0, 255)  # wide "clock" ink
        poster = np.full((600, 400, 3), (10, 20, 200), dtype=np.uint8)
        out = compose_clock_with_poster(frame, poster)
        _clock, (px, py, pw, ph) = clock_saver_poster_split_boxes()
        right = out[py : py + ph, px : px + pw]
        self.assertGreater(int((right[:, :, 3] == 255).sum()), pw * ph * 0.9)
        left = out[:, : px - 10]
        ys, xs = np.where(left[:, :, 3] > 0)
        self.assertGreater(xs.size, 0)
        self.assertLess(int(xs.max()), px)
        self.assertGreater(int(xs.min()), 0)
        self.assertEqual(int(out[:, px + pw + 1 :, 3].max()), 0)


class ExitLabelCenteringTests(unittest.TestCase):
    def test_label_ink_centers_on_pill(self) -> None:
        import xml.etree.ElementTree as ET

        from pigeon.widgets.settings_svg_text import center_label_on_pill

        pill = ET.fromstring(
            '<path xmlns="http://www.w3.org/2000/svg" d="M100,100h80c8,0,10,2,10,10v40'
            'c0,8-2,10-10,10h-80c-8,0-10-2-10-10v-40c0-8,2-10,10-10z"/>'
        )
        text = ET.fromstring(
            '<text xmlns="http://www.w3.org/2000/svg" transform="translate(5 5)" '
            'font-family="Digital-7" font-size="40"><tspan x="0" y="0">EXIT</tspan></text>'
        )
        if not center_label_on_pill(text, pill):
            self.skipTest("Digital-7 font unavailable")
        tx, ty = (float(v) for v in text.get("transform")[10:-1].split())
        # Pill spans x 90..190, y 100..170 → label origin lands near the center
        # (left of cx by half the label width, below cy by half the cap height).
        self.assertTrue(100.0 < tx < 140.0, tx)
        self.assertTrue(135.0 < ty < 165.0, ty)


if __name__ == "__main__":
    unittest.main()
