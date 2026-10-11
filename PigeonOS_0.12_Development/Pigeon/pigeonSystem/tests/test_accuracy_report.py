"""Accuracy report: client payloads (pigeon/accuracy_report.py) and the Mac store."""

from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import accuracy_report as ar  # noqa: E402
import pigeon_report_server as srv  # noqa: E402

_MATCH_TRACE = {
    "query": "Severance",
    "outcome": "match",
    "display_title": "Severance",
    "title_key": "Severance",
    "kind": "tv",
    "tmdb_id": 95396,
    "logo_ok": True,
    "logo_source": "cache",
    "logo_path": "/logo.png",
    "backdrop_ok": True,
    "backdrop_path": "/bd.jpg",
    "poster_ok": False,
    "poster_path": "/p.jpg",
}


def _capture_event(**overrides):
    kwargs = dict(
        metadata={"title": "Severance", "app_name": "TV"},
        streaming_service="Apple TV+",
        query_in="Severance",
        refined_query="Severance",
        used_query="Severance",
        prefer="auto",
        trigger="auto",
        ok=True,
        message="Severance::Severance::summary",
        match_tier=5,
        tier_ok=True,
        attempts=[{"query": "Sev", "outcome": "no_match"}, _MATCH_TRACE],
        tt_source="tmdb_logo",
        backdrop_source="tmdb",
    )
    kwargs.update(overrides)
    sent = []
    with mock.patch.object(ar, "_enqueue", lambda kind, p: sent.append((kind, p))):
        ar.report_fetch_event(**kwargs)
    return sent[0]


class ClientTests(unittest.TestCase):
    def test_server_url_resolution(self) -> None:
        with mock.patch.dict(os.environ, {"PIGEON_REPORT_URL": "off"}):
            self.assertIsNone(ar.server_url())
        with mock.patch.dict(os.environ, {"PIGEON_REPORT_URL": "mac.local:9000/"}):
            self.assertEqual(ar.server_url(), "http://mac.local:9000")

    def test_pigeon_id_env_override(self) -> None:
        ar.pigeon_id.cache_clear()
        try:
            with mock.patch.dict(os.environ, {"PIGEON_ID": "pi5"}):
                self.assertEqual(ar.pigeon_id(), "pi5")
        finally:
            ar.pigeon_id.cache_clear()

    def test_match_event_uses_winning_attempt(self) -> None:
        kind, p = _capture_event()
        self.assertEqual(kind, "event")
        self.assertEqual(p["assumed_title"], "Severance")
        self.assertEqual(p["queries_tried"], ["Sev", "Severance"])
        self.assertEqual(p["tt_source"], "tmdb_logo_cached")
        self.assertTrue(p["tt"])
        self.assertTrue(p["backdrop"])
        self.assertFalse(p["poster"])
        self.assertEqual(p["failure"], "TMDb has no poster")

    def test_low_tier_is_a_failure(self) -> None:
        _, p = _capture_event(tier_ok=False, tt_source="text_fallback")
        self.assertFalse(p["tt"])
        self.assertIn("below threshold", p["failure"])

    def test_no_match_explains_failure(self) -> None:
        _, p = _capture_event(
            ok=False,
            message="No movie or TV show found for that search.\n\nSearched…",
            attempts=[{"query": "Severance", "outcome": "no_match", "failure": "No movie or TV show found"}],
            tt_source="app_logo",
            backdrop_source="none",
        )
        self.assertEqual(p["failure"], "No movie or TV show found")
        self.assertEqual(p["assumed_title"], "")
        self.assertIsNone(p["tt_path"])


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = srv.Store(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _event(self, eid: str, dev: str = "pi4", t: float = 100.0) -> dict:
        return {"id": eid, "pigeon_id": dev, "t": t, "ok": True, "tt": True,
                "assumed_title": f"Title {eid}", "queries_tried": ["a", "b"]}

    def test_push_dedupes_and_persists(self) -> None:
        self.store.push("event", self._event("e1"))
        self.store.push("event", self._event("e1"))
        self.assertEqual(len(self.store.rows()), 1)
        again = srv.Store(self.root)
        self.assertEqual([r["id"] for r in again.rows()], ["e1"])

    def test_flag_marks_device_latest_event(self) -> None:
        self.store.push("event", self._event("e1", t=100))
        self.store.push("event", self._event("e2", t=200))
        self.store.push("flag", {"pigeon_id": "pi4", "event_id": None})
        flagged = {r["id"]: bool(r.get("flagged_wrong")) for r in self.store.rows()}
        self.assertEqual(flagged, {"e1": False, "e2": True})

    def test_notes_land_in_csv(self) -> None:
        self.store.push("event", self._event("e1"))
        self.assertTrue(self.store.annotate("e1", notes="wrong season"))
        rows = list(csv.reader(io.StringIO(self.store.csv_text())))
        hdr = rows[0]
        self.assertEqual(hdr[-1], "Notes")
        self.assertEqual(rows[1][-1], "wrong season")
        self.assertEqual(rows[1][hdr.index("Query terms")], "a → b")
        self.assertEqual(rows[1][hdr.index("tmdb_tt")], "TRUE")

    def test_pigeon_version_column_follows_pigeon_id(self) -> None:
        ev = self._event("e1")
        ev["pigeon_version"] = "0.11.39"
        self.store.push("event", ev)
        rows = list(csv.reader(io.StringIO(self.store.csv_text())))
        hdr = rows[0]
        self.assertEqual(hdr.index("Pigeon version"), hdr.index("Pigeon ID") + 1)
        self.assertEqual(rows[1][hdr.index("Pigeon version")], "0.11.39")


class LogoOwnerTests(unittest.TestCase):
    """Same-title TMDb items (It 1990 vs It 2017) must not share a cached TT."""

    def test_drop_and_owner_roundtrip(self) -> None:
        from pigeon import tmdb_poster as tp
        import pigeon.media_folders as mf

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with mock.patch.object(mf, "pigeon_tmdb_root_dir", lambda: root / "tmdb"), \
                 mock.patch.object(tp, "_pigeon_state_dir", lambda: root / "state"):
                tt_dir = mf.pigeon_tmdb_tt_dir()
                tt_dir.mkdir(parents=True)
                (tt_dir / "It_LogoEn.png").write_bytes(b"2017")
                tp._save_logo_owners({"It": "movie:346364:/a.png"})
                self.assertEqual(tp._load_logo_owners()["It"], "movie:346364:/a.png")
                self.assertTrue(tp._drop_cached_logos("It"))
                self.assertFalse((tt_dir / "It_LogoEn.png").exists())
                self.assertFalse(tp._drop_cached_logos("It"))


if __name__ == "__main__":
    unittest.main()
