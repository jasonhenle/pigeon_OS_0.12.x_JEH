"""Companion-app corrections to the TMDb query: field edits and hand-picked titles."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import manual_search as ms  # noqa: E402
from pigeon import runtime_paths  # noqa: E402
from pigeon import tmdb_poster as tp  # noqa: E402
from pigeon.control_api import now_playing_override as npo  # noqa: E402
from pigeon.control_api import profile  # noqa: E402
from pigeon.control_api.server import ControlService  # noqa: E402

MD = {
    "title": "The Final Show",
    "series_name": "",
    "query": "The Final Show",
    "app_name": "Disney+",
    "media_type": "video",
}


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = runtime_paths._CACHED
        runtime_paths._CACHED = Path(self._tmp.name)
        ms._entry = None
        ms._loaded = False
        ms._shown = False
        npo.clear()
        tp._LAST_FETCH_TRACE.clear()
        self.addCleanup(npo.clear)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: setattr(runtime_paths, "_CACHED", self._prev))


class DeriveTests(_Base):
    def test_edit_title_retires_stale_apple_tv_query(self) -> None:
        q = npo.derive_query(MD, {"title": "Taylor Swift The Eras Tour"})
        self.assertIn("Eras Tour", q)
        self.assertNotEqual(q, "The Final Show")

    def test_query_field_wins_and_year_is_appended_once(self) -> None:
        self.assertEqual(npo.derive_query(MD, {"query": "Heat"}, 1995), "Heat (1995)")
        self.assertEqual(npo.derive_query(MD, {"query": "Heat (1995)"}, 1995), "Heat (1995)")

    def test_uneditable_fields_ignored(self) -> None:
        self.assertEqual(npo.derive_query(MD, {"app_name": "Hulu"}), npo.derive_query(MD, {}))

    def test_input_rows_flag_editable(self) -> None:
        rows = {r["key"]: r for r in npo.input_rows(MD)}
        self.assertTrue(rows["title"]["editable"])
        self.assertFalse(rows["app_name"]["editable"])
        self.assertIn("series_name", rows)  # editable fields always listed, even when empty


class OverrideLifecycleTests(_Base):
    def test_applies_to_same_content_not_to_different_content(self) -> None:
        npo.set_fields(MD, {"query": "Heat"}, year=1995, kind="movie")
        self.assertEqual(npo.apply_override("The Final Show", "auto", MD), ("Heat (1995)", "movie"))
        other = {**MD, "title": "Something Else", "query": "Something Else"}
        self.assertEqual(npo.apply_override("Something Else", "auto", other), ("Something Else", "auto"))
        self.assertIsNone(npo.get())  # stopped applying, but still remembered

    def test_correction_is_remembered_across_content_and_restart(self) -> None:
        npo.set_pick(MD, title="Heat", kind="movie", tmdb_id=949, year=1995)
        other = {**MD, "title": "Something Else", "query": "Something Else"}
        npo.apply_override("Something Else", "auto", other)
        self.assertIsNone(npo.get())
        # the original content comes back: re-applied from disk, forced id restored
        self.assertEqual(npo.apply_override("The Final Show", "auto", MD), ("Heat (1995)", "movie"))
        self.assertEqual(npo.get().pick["tmdb_id"], 949)
        # process restart: nothing in memory, the store still has it
        npo._CURRENT = None
        tp.clear_forced_picks()
        self.assertEqual(npo.apply_override("The Final Show", "auto", MD), ("Heat (1995)", "movie"))
        detail = {"id": 949, "title": "Heat", "poster_path": "/h.jpg"}
        with mock.patch.object(tp, "_tmdb_movie_detail", return_value=detail):
            item, kind = tp._forced_pick_item("Heat (1995)")
        self.assertEqual((item["id"], kind), (949, "movie"))

    def test_survives_apple_tv_alternating_show_and_episode_titles(self) -> None:
        npo.set_pick(MD, title="Heat", kind="movie", tmdb_id=949, year=1995)
        # poll N+1: Apple TV reports the episode line as the title, same query
        alt = {**MD, "title": "A Totally Different Episode Line"}
        self.assertEqual(npo.apply_override("The Final Show", "auto", alt), ("Heat (1995)", "movie"))
        # idle poll with no metadata does not drop it either
        self.assertEqual(npo.apply_override("", "auto", None), ("Heat (1995)", "movie"))
        self.assertIsNotNone(npo.get())

    def test_reset_forgets_for_good(self) -> None:
        npo.set_fields(MD, {"query": "Heat"})
        npo.clear(MD, forget=True)
        self.assertEqual(npo.apply_override("The Final Show", "auto", MD), ("The Final Show", "auto"))
        self.assertEqual(npo._load_store(), [])

    def test_new_correction_replaces_old_for_same_content(self) -> None:
        npo.set_fields(MD, {"query": "Heat"})
        npo.set_pick(MD, title="Taylor Swift: The Eras Tour", kind="movie", tmdb_id=1114513, year=2023)
        self.assertEqual(len(npo._load_store()), 1)
        self.assertEqual(npo.apply_override("The Final Show", "auto", MD)[0], "Taylor Swift: The Eras Tour (2023)")

    def test_needs_something_playing(self) -> None:
        with self.assertRaises(ValueError):
            npo.set_pick({}, title="Heat", kind="movie", tmdb_id=949)

    def test_not_applied_to_manual_search_spawns(self) -> None:
        npo.set_fields(MD, {"query": "Heat"})
        with mock.patch.object(ms, "is_displaying", return_value=True):
            self.assertEqual(npo.apply_override("My Pin", "auto", MD), ("My Pin", "auto"))
        self.assertIsNotNone(npo.get())

    def test_pick_registers_forced_id(self) -> None:
        ov = npo.set_pick(MD, title="Taylor Swift: The Eras Tour", kind="movie", tmdb_id=1114513, year=2023)
        self.assertEqual(ov.prefer, "movie")
        self.assertEqual(ov.pick["tmdb_id"], 1114513)
        detail = {"id": 1114513, "title": "Taylor Swift: The Eras Tour", "poster_path": "/p.jpg"}
        with mock.patch.object(tp, "_tmdb_movie_detail", return_value=detail) as md:
            item, kind = tp._forced_pick_item(ov.query)
        md.assert_called_once_with(1114513)
        self.assertEqual((item["id"], kind), (1114513, "movie"))
        npo.clear()
        self.assertEqual(tp._forced_pick_item(ov.query), (None, None))

    def test_pick_validation(self) -> None:
        with self.assertRaises(ValueError):
            npo.set_pick(MD, title="", kind="movie", tmdb_id=1)
        with self.assertRaises(ValueError):
            npo.set_pick(MD, title="X", kind="album", tmdb_id=1)

    def test_forced_pick_wins_inside_apply_tmdb_movie_query(self) -> None:
        npo.set_pick(MD, title="Heat", kind="movie", tmdb_id=949, year=1995)
        item = {"id": 949, "title": "Heat", "release_date": "1995-12-15", "poster_path": "/h.jpg"}
        with mock.patch.object(tp, "_tmdb_movie_detail", return_value=item), \
             mock.patch.object(tp, "search_best_media", side_effect=AssertionError("search ran")), \
             mock.patch.object(tp, "enrich_item_runtime", side_effect=lambda i, k: i), \
             mock.patch.object(tp, "ensure_tmdb_media_dirs"), \
             mock.patch.object(tp, "purge_directory_contents"), \
             mock.patch.object(tp, "_trt_rejects", return_value=True):
            # _trt_rejects=True ends the call right after the id is chosen, which is all we check.
            tp.apply_tmdb_movie_query("Heat (1995)", prefer="auto")
        trace = tp.last_fetch_trace()
        self.assertEqual(trace.get("tmdb_id"), 949)
        self.assertTrue(trace.get("forced_pick"))


class RouteTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.spawned: list[tuple[str, str]] = []
        self.md = dict(MD)
        self.svc = ControlService(
            run_on_ui=lambda fn: fn(),
            metadata_provider=lambda: self.md,
            fetch_provider=lambda: {"refined": "The Final Show", "prefer": "auto", "in_flight": False,
                                    "display_title": "Taylor Swift | The Eras Tour"},
            respawn=lambda q, p: self.spawned.append((q, p)),
        )
        self.token = self.svc.auth.claim(self.svc.auth.pairing_code, "t", "c1")

    def call(self, method, path, body=None):
        return self.svc.handle(method, "/api/v1" + path, {}, self.token, body)

    def test_detail_shape(self) -> None:
        st, d = self.call("GET", "/now-playing/detail")
        self.assertEqual(st, 200)
        self.assertTrue(d["content_active"])
        self.assertEqual(d["app"], "Disney+")
        self.assertEqual({r["key"] for r in d["inputs"] if r["editable"]},
                         {"title", "series_name", "episode_title", "query"})
        self.assertEqual(d["query"]["apple_tv"], "The Final Show")
        self.assertEqual(d["query"]["searched"], "The Final Show")
        self.assertEqual(d["match"]["title"], "Taylor Swift | The Eras Tour")
        self.assertEqual(d["override"], {"active": False})

    def test_put_fields_respawns_with_edited_query(self) -> None:
        st, d = self.call("PUT", "/now-playing/override",
                          {"fields": {"query": "Taylor Swift The Eras Tour"}, "year": 2023, "kind": "movie"})
        self.assertEqual(st, 200)
        self.assertEqual(self.spawned, [("Taylor Swift The Eras Tour (2023)", "movie")])
        self.assertTrue(d["override"]["active"])
        self.assertEqual(d["override"]["fields"], {"query": "Taylor Swift The Eras Tour"})

    def test_put_pick_and_delete(self) -> None:
        st, d = self.call("PUT", "/now-playing/override",
                          {"pick": {"title": "Heat", "kind": "movie", "tmdb_id": 949, "year": 1995}})
        self.assertEqual(st, 200)
        self.assertEqual(d["override"]["pick"]["tmdb_id"], 949)
        self.assertEqual(self.spawned[-1], ("Heat (1995)", "movie"))
        st, d = self.call("DELETE", "/now-playing/override")
        self.assertEqual((st, d["override"]), (200, {"active": False}))
        self.assertEqual(self.spawned[-1][0], "The Final Show")  # back to what was detected

    def test_bad_requests(self) -> None:
        self.assertEqual(self.call("PUT", "/now-playing/override", {"fields": {}})[0], 400)
        self.assertEqual(self.call("PUT", "/now-playing/override",
                                   {"pick": {"title": "X", "kind": "movie", "tmdb_id": 0}})[0], 400)
        self.assertEqual(self.call("POST", "/now-playing/preview", [])[0], 400)

    def test_preview_returns_candidates_without_applying(self) -> None:
        rows = ({"title": "Heat", "year": "1995", "kind": "movie", "tmdb_id": 949},)
        with mock.patch.object(ms, "suggest_now", return_value=rows):
            st, d = self.call("POST", "/now-playing/preview", {"fields": {"query": "Heat"}})
        self.assertEqual(st, 200)
        self.assertEqual(d["query"], "Heat")
        self.assertEqual(d["candidates"][0], {"tmdb_id": 949, "kind": "movie", "title": "Heat", "year": 1995})
        self.assertEqual(self.spawned, [])
        self.assertIsNone(npo.get())

    def test_requires_auth_and_capability(self) -> None:
        self.assertEqual(self.svc.handle("GET", "/api/v1/now-playing/detail", {}, "", None)[0], 401)
        self.assertIn("now_playing_override", profile.capabilities())


if __name__ == "__main__":
    unittest.main()
