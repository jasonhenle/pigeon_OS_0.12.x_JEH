"""Control API v1 (Phase 1): claim/auth, device, capabilities, search, SSE."""

from __future__ import annotations

import http.client
import json
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
from pigeon.control_api import profile  # noqa: E402
from pigeon.control_api.auth import AuthStore, MAX_FAILS  # noqa: E402
from pigeon.control_api.server import ControlServer, ControlService  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = runtime_paths._CACHED
        runtime_paths._CACHED = Path(self._tmp.name)
        ms._entry = None
        ms._loaded = False
        ms._shown = False
        ms._spawn_hook = None
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: setattr(runtime_paths, "_CACHED", self._prev))


class AuthTests(_Base):
    def test_claim_issues_token_and_rotates_code(self) -> None:
        a = AuthStore()
        self.assertFalse(a.claimed())
        old = a.pairing_code
        tok = a.claim(old, "iPhone", "c1")
        self.assertTrue(tok and tok.startswith("pgt_"))
        self.assertTrue(a.claimed())
        self.assertEqual(a.verify(tok)["id"], "c1")
        self.assertNotEqual(a.pairing_code, old)
        # only a hash is stored
        self.assertNotIn(tok, (Path(self._tmp.name) / "control_api_auth.json").read_text())

    def test_lockout_after_failures(self) -> None:
        a = AuthStore()
        wrong = "000000" if a.pairing_code != "000000" else "111111"
        for _ in range(MAX_FAILS):
            self.assertIsNone(a.claim(wrong, "x", "x"))
        with self.assertRaises(PermissionError):
            a.claim(a.pairing_code, "x", "x")

    def test_revoke(self) -> None:
        a = AuthStore()
        tok = a.claim(a.pairing_code, "p", "c1")
        self.assertTrue(a.revoke("c1"))
        self.assertIsNone(a.verify(tok))


class RouteTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.svc = ControlService(run_on_ui=lambda fn: fn(), on_manual_set=lambda: None)
        self.token = self.svc.auth.claim(self.svc.auth.pairing_code, "t", "c1")

    def call(self, method, path, body=None, query=None, token="__t__"):
        tok = self.token if token == "__t__" else token
        return self.svc.handle(method, "/api/v1" + path, query or {}, tok, body)

    def test_hello_is_open(self) -> None:
        st, body = self.call("GET", "/hello", token="")
        self.assertEqual(st, 200)
        self.assertTrue(body["claimed"])
        self.assertEqual(body["api"], 1)

    def test_auth_required(self) -> None:
        self.assertEqual(self.call("GET", "/status", token="")[0], 401)
        self.assertEqual(self.call("GET", "/status", token="bad")[0], 401)

    def test_claim_refused_when_claimed(self) -> None:
        st, body = self.call("POST", "/claim", {"code": self.svc.auth.pairing_code}, token="")
        self.assertEqual(st, 403)
        self.assertEqual(body["error"]["code"], "already_claimed")

    def test_invite_allows_second_controller(self) -> None:
        code = self.call("POST", "/controllers/invite")[1]["code"]
        st, body = self.call("POST", "/claim",
                             {"code": code, "controller": {"id": "c2", "name": "iPad"}}, token="")
        self.assertEqual(st, 200)
        self.assertEqual(len(self.call("GET", "/controllers")[1]["controllers"]), 2)

    def test_device_rename(self) -> None:
        st, body = self.call("PATCH", "/device", {"name": "Theater"})
        self.assertEqual((st, body["name"]), (200, "Theater"))
        self.assertEqual(self.call("PATCH", "/device", {"name": ""})[0], 400)

    def test_capabilities_by_product(self) -> None:
        with mock.patch.dict(os.environ, {"PIGEON_PRODUCT": "marquee"}):
            caps = self.call("GET", "/capabilities")[1]
        self.assertEqual(caps["product"], "marquee")
        self.assertNotIn("viz", caps["capabilities"])
        self.assertIn("manual_search", caps["capabilities"])

    def test_search_current_roundtrip(self) -> None:
        self.assertEqual(self.call("GET", "/search/current")[1], {"active": False})
        st, body = self.call("PUT", "/search/current",
                             {"title": "Blade Runner 2049", "kind": "movie", "tmdb_id": 335984})
        self.assertEqual(st, 200)
        self.assertEqual(body["entry"]["title"], "Blade Runner 2049")
        status = self.call("GET", "/status")[1]
        self.assertEqual(status["state"], "manual")
        self.assertEqual(status["now_playing"]["source"], "manual")
        self.assertEqual(self.call("DELETE", "/search/current")[0], 204)
        self.assertEqual(self.call("GET", "/search/current")[1], {"active": False})

    def test_search_put_requires_title(self) -> None:
        self.assertEqual(self.call("PUT", "/search/current", {"title": " "})[0], 400)

    def test_suggest_validation_and_shape(self) -> None:
        self.assertEqual(self.call("GET", "/search/suggest", query={"q": ["a"]})[0], 400)
        rows = ({"title": "Blade Runner", "year": "1982", "kind": "movie", "tmdb_id": 78},)
        with mock.patch.object(ms, "suggest_now", return_value=rows) as sn:
            st, body = self.call("GET", "/search/suggest", query={"q": ["blade run"], "limit": ["99"]})
        self.assertEqual(st, 200)
        self.assertEqual(sn.call_args.kwargs["limit"], 6)  # clamped
        self.assertEqual(body["results"][0], {"tmdb_id": 78, "kind": "movie", "title": "Blade Runner", "year": 1982})

    def test_status_provider_wins_over_manual_idle(self) -> None:
        svc = ControlService(status_provider=lambda: {"state": "playing", "now_playing": {"title": "X", "source": "detected"}})
        self.assertEqual(svc.status()["now_playing"]["title"], "X")


class HttpTests(_Base):
    def test_end_to_end_and_sse(self) -> None:
        svc = ControlService(run_on_ui=lambda fn: fn(), on_manual_set=lambda: None)
        srv = ControlServer(svc, host="127.0.0.1", port=0)
        srv.start()
        self.addCleanup(srv.stop)

        def req(method, path, body=None, token=None):
            c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
            h = {"Content-Type": "application/json"}
            if token:
                h["Authorization"] = "Bearer " + token
            c.request(method, "/api/v1" + path, json.dumps(body) if body is not None else None, h)
            r = c.getresponse()
            raw = r.read()
            c.close()
            return r.status, (json.loads(raw) if raw else None)

        st, hello = req("GET", "/hello")
        self.assertEqual((st, hello["claimed"]), (200, False))
        st, claim = req("POST", "/claim", {"code": svc.auth.pairing_code, "controller": {"id": "c1", "name": "me"}})
        self.assertEqual(st, 200)
        tok = claim["token"]
        self.assertEqual(req("GET", "/device", token=tok)[0], 200)

        c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        c.request("GET", "/api/v1/events", headers={"Authorization": "Bearer " + tok})
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        first = ""
        while True:
            line = r.fp.readline().decode()
            if line in ("\n", ""):
                break
            first += line
        self.assertIn("event: snapshot", first)
        req("PUT", "/search/current", {"title": "Heat", "kind": "movie"}, token=tok)
        seen = ""
        for _ in range(6):
            seen += r.fp.readline().decode()
            if "manual_search" in seen:
                break
        self.assertIn("event: manual_search", seen)
        c.close()


if __name__ == "__main__":
    unittest.main()


class ClaimCodeDrawTests(_Base):
    def test_draw_companion_code(self) -> None:
        import numpy as np
        from pigeon.widgets.pigeon_settings import draw_companion_code

        frame = np.zeros((800, 1280, 4), np.uint8)
        self.assertIs(draw_companion_code(frame, ""), frame)  # nothing to show
        out = draw_companion_code(frame, "482913")
        self.assertIsNot(out, frame)
        self.assertGreater(int(out[600:660, 60:500, 3].max()), 0)
        self.assertEqual(int(frame.max()), 0)  # input untouched

    def test_code_hidden_when_api_not_running(self) -> None:
        from pigeon import control_api

        self.assertEqual(control_api.claim_code_to_show(), "")
