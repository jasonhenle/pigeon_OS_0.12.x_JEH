"""Helpers extracted from ``pigeon_0_12.bootstrap()`` into ``pigeon.core``.

Covers the ``bind_deps`` wiring contract, a structural check that every bind
site in ``pigeon_0_12.py`` matches the extracted function's signature, and
behaviour of the pure helpers.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import sys
import time
import unittest
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.core.binding import bind_deps  # noqa: E402


class BindDepsTests(unittest.TestCase):
    def test_binds_keyword_only_deps_and_passes_call_args(self):
        def helper(a, b=2, *, holder):
            holder.append((a, b))
            return a + b

        holder: list = []
        bound = bind_deps(helper, holder=holder)
        self.assertEqual(bound(1), 3)
        self.assertEqual(bound(1, b=5), 6)
        self.assertEqual(holder, [(1, 2), (1, 5)])

    def test_preserves_name_and_doc(self):
        def helper(*, dep):
            """Doc."""

        bound = bind_deps(helper, dep=1)
        self.assertEqual(bound.__name__, "helper")
        self.assertEqual(bound.__doc__, "Doc.")

    def test_sees_in_place_mutation_of_holders(self):
        def read(*, holder):
            return holder[0]

        holder = [None]
        bound = bind_deps(read, holder=holder)
        holder[0] = "later"
        self.assertEqual(bound(), "later")


class BindSitesMatchSignaturesTests(unittest.TestCase):
    """Every ``name = _bind_deps(_core_mod.name, dep=dep, ...)`` in pigeon_0_12.py
    must reference a real extracted function and bind only its keyword-only
    parameters (catches renames/typos when either side is edited)."""

    def test_bind_sites(self):
        # Bind sites live in pigeon_0_12.py and (since pass 13) the boot phases.
        import glob

        paths = [os.path.join(_SYS_ROOT, "pigeon_0_12.py")] + sorted(
            glob.glob(os.path.join(_SYS_ROOT, "pigeon", "core", "boot", "[mp][0-9]*.py")))
        nodes = [n for p in paths for n in ast.walk(ast.parse(open(p, encoding="utf-8").read()))]
        sites = 0
        for node in nodes:
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                continue
            v = node.value
            call = v if isinstance(v, ast.Call) and getattr(v.func, "id", "") == "_bind_deps" else None
            ref = call.args[0] if call else v
            if not (isinstance(ref, ast.Attribute) and isinstance(ref.value, ast.Name)
                    and ref.value.id.startswith("_core_")):
                continue
            mod = importlib.import_module("pigeon.core." + ref.value.id[len("_core_"):])
            fn = getattr(mod, ref.attr)
            kwonly = {p.name for p in inspect.signature(fn).parameters.values()
                      if p.kind is p.KEYWORD_ONLY}
            got = {k.arg for k in call.keywords} if call else set()
            self.assertLessEqual(got, kwonly, ref.attr)
            sites += 1
        self.assertGreater(sites, 100)


class TmdbFlowTests(unittest.TestCase):
    def setUp(self):
        from pigeon.core import tmdb_flow

        self.m = tmdb_flow

    def test_parse_command_phrase(self):
        p = self.m.parse_tmdb_command_phrase
        self.assertEqual(p("tv  Severance "), ("Severance", "tv"))
        self.assertEqual(p("MOVIE Dune"), ("Dune", "movie"))
        self.assertEqual(p(" Dune "), ("Dune", "auto"))

    def test_escape_log_field(self):
        self.assertEqual(self.m._escape_log_field("a\tb\nc\\"), "a b c\\\\")
        self.assertEqual(self.m._escape_log_field(None), "")

    def test_match_quality_glance(self):
        f = self.m._format_tmdb_match_quality_glance
        self.assertIn("no scored events", f(0, 0))
        self.assertIn("75% ok", f(3, 1))

    def test_overlay_trigger_writes_holders(self):
        mode, t0 = [""], [0.0]
        self.m._trigger_tmdb_quality_toggle_overlay(
            "flag", tmdb_quality_overlay_mode=mode, tmdb_quality_overlay_t0=t0
        )
        self.assertEqual(mode[0], "flag")
        self.assertGreater(t0[0], 0.0)


class SettingsUiTests(unittest.TestCase):
    def setUp(self):
        from pigeon.core import settings_ui

        self.m = settings_ui

    def test_parse_device_rows(self):
        p = self.m._settings_parse_device_rows
        good = {"identifier": "id1", "address": "10.0.0.2"}
        self.assertEqual(p([good, {"identifier": "x"}, "junk"]), [good])
        self.assertEqual(p(good), [good])
        self.assertEqual(p(None), [])

    def test_parse_receiver_rows_allows_missing_identifier(self):
        p = self.m._settings_parse_receiver_rows
        self.assertEqual(p([{"address": "10.0.0.9"}, {"address": " "}]), [{"address": "10.0.0.9"}])

    def test_device_addr_key(self):
        k = self.m._device_addr_key
        self.assertEqual(k("10.0.0.2:7000"), "10.0.0.2")
        self.assertEqual(k("FE80::1%en0"), "fe80::1")
        self.assertEqual(k("[fe80::1]:7000"), "[fe80::1]:7000")
        self.assertEqual(k(""), "")

    def test_row_matches_saved_by_identifier_or_address(self):
        match = bind_deps(self.m._device_row_matches_saved, _device_addr_key=self.m._device_addr_key)
        self.assertTrue(match({"identifier": "A"}, {"identifier": "A"}))
        self.assertTrue(match({"address": "10.0.0.2:7000"}, {"address": "10.0.0.2"}))
        self.assertFalse(match({"address": "10.0.0.3"}, {"address": "10.0.0.2"}))


class NowPlayingTests(unittest.TestCase):
    def setUp(self):
        from pigeon.core import now_playing

        self.m = now_playing

    def test_netflix_detection(self):
        f = self.m._metadata_is_netflix_app
        self.assertTrue(f({"app_name": "Netflix"}))
        self.assertTrue(f({"bundle_identifier": "com.netflix.Netflix"}))
        self.assertFalse(f({"app_name": "Disney+"}))
        self.assertFalse(f(None))

    def test_music_track_key(self):
        self.assertEqual(self.m._music_artwork_track_key({"title": "T", "artist": "A"}), "||T|A|")

    def test_progress_fraction(self):
        f = self.m._playback_progress_fraction_for_bar
        clk = {"has_sync": True, "latched_total": 100.0, "sync_position": 25.0,
               "sync_mono": time.monotonic(), "playing": False}
        self.assertEqual(f(apple_tv_playback_clock=clk), 0.25)
        self.assertIsNone(f(apple_tv_playback_clock={**clk, "live_mode": True}))
        self.assertIsNone(f(apple_tv_playback_clock={**clk, "latched_total": None}))


class SaverAndViewFourTests(unittest.TestCase):
    def test_vol_norm(self):
        from pigeon.core.saver_state import _vol_norm_for_clock_saver as f

        self.assertEqual(f(None), "")
        self.assertEqual(f(float("nan")), "")
        self.assertEqual(f("-35.5"), "-35.5")
        self.assertEqual(f("vol?"), "vol?")

    def test_view_four_placeholder(self):
        from pigeon.core.view_four import _view_four_text_is_placeholder as f

        for s in ("", "  ", "Title: NONE", "Show -", "Unknown'", '"'):
            self.assertTrue(f(s), s)
        self.assertFalse(f("Severance"))


class PassTwoHelpersTests(unittest.TestCase):
    """Pass 2 also lifts helpers that read module globals / main() locals."""

    def test_ui_scale_clamps(self):
        from pigeon.core.stage_render import _ui_scale as f

        kw = dict(WINDOW_W=1280, WINDOW_H=800)
        self.assertEqual(f(display_dims=[1280, 800], **kw), 1.0)
        self.assertEqual(f(display_dims=[100, 100], **kw), 0.45)
        self.assertEqual(f(display_dims=[99999, 99999], **kw), 5.0)

    def test_location_toast_alpha(self):
        from pigeon.core.stage_render import _location_toast_alpha as f

        st = {"active": True, "t0": 100.0}
        kw = dict(LOCATION_TOAST_FADE_S=2.0, LOCATION_TOAST_FULL_S=3.0, location_toast_state=st)
        self.assertEqual(f(101.0, **kw), 1.0)
        self.assertAlmostEqual(f(104.0, **kw), 0.5)
        self.assertEqual(f(106.0, **kw), 0.0)
        self.assertFalse(st["active"])

    def test_view_one_full_path_falls_back_without_variant(self):
        from pigeon.core.view_one import _view_one_variant_uses_full_path as f

        kw = dict(
            _current_view_one_variant=lambda: None,
            _view_one_is_pigeon_full=lambda: True,
            _view_one_is_pigeon_poster=lambda: False,
            variant_uses_full_path=None,
        )
        self.assertTrue(f(**kw))
        self.assertFalse(f(**{**kw, "_view_one_is_pigeon_poster": lambda: True}))


class HdmiFrameCheckWiringTests(unittest.TestCase):
    """OCR is retired; the poll still schedules HDMI frame checks for the clock saver."""

    def setUp(self):
        from pigeon import hdmi_capture

        self.hc = hdmi_capture
        hdmi_capture.reset_frame_schedule()

    def test_changed_frame_counts_as_activity(self):
        from pigeon.core.device_control import _apply_hdmi_frame_check

        calls = []
        state = {"hdmi_check_in_flight": True}
        kw = dict(
            _bump_clock_saver_significant_device=lambda: calls.append("bump"),
            _note_metadata_activity=lambda: calls.append("activity"),
            _sync_now_playing_screen_state=lambda: calls.append("sync"),
            apple_tv_auto_state=state,
        )
        _apply_hdmi_frame_check(True, **kw)
        self.assertEqual(calls, ["activity", "bump", "sync"])
        calls.clear()
        _apply_hdmi_frame_check(False, **kw)
        self.assertEqual(calls, ["sync"])
        self.assertFalse(state["hdmi_check_in_flight"])

    def test_schedule_respects_cadence(self):
        from pigeon.core.device_control import _schedule_hdmi_frame_check_from_poll

        started = []
        state = {}
        kw = dict(_on_hdmi_frame_checked=lambda c: None, apple_tv_auto_state=state)
        with mock.patch.object(self.hc, "request_frame_check",
                               side_effect=lambda cb: started.append(cb) or True):
            _schedule_hdmi_frame_check_from_poll(**kw)
            self.assertEqual(len(started), 1)
            self.assertTrue(state["hdmi_check_in_flight"])
            _schedule_hdmi_frame_check_from_poll(**kw)  # still in flight
            state["hdmi_check_in_flight"] = False
            _schedule_hdmi_frame_check_from_poll(**kw)  # not due yet
            self.assertEqual(len(started), 1)


class SourceTilesAreStatusOnlyTests(unittest.TestCase):
    """WIFI / METADATA / AUDIO lights report status; they are not selectable."""

    def test_source_tiles_not_in_focus_ring(self):
        from pigeon.widgets.pigeon_settings import pigeon_focus_ring

        ring = pigeon_focus_ring()
        for fid in ring:
            for source in ("wifi", "metadata", "hdmi", "audio"):
                self.assertNotIn(source, fid)
        self.assertIn("update", ring)

    def test_no_toggle_module(self):
        import importlib.util

        self.assertIsNone(importlib.util.find_spec("pigeon.source_toggles"))


if __name__ == "__main__":
    unittest.main()
