"""First-run setup: state machine, Control API routes, QR payload and Welcome screen."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from pigeon import control_api, runtime_paths, setup_state  # noqa: E402
from pigeon.control_api.auth import AuthStore  # noqa: E402
from pigeon.control_api.server import ControlService  # noqa: E402
from pigeon.widgets import welcome_setup  # noqa: E402

API = "/api/v1"


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        prev = runtime_paths._CACHED
        runtime_paths._CACHED = self.dir
        setup_state._reset_for_tests()
        env = mock.patch.dict(os.environ, {"PIGEON_SETUP": ""})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: setattr(runtime_paths, "_CACHED", prev))
        self.addCleanup(setup_state._reset_for_tests)


class StateTests(_Base):
    def test_fresh_install_shows_welcome(self) -> None:
        self.assertEqual(setup_state.resolve_at_boot(), "welcome")
        self.assertTrue(setup_state.needs_setup())
        self.assertTrue((self.dir / "setup_state.json").is_file())

    def test_existing_install_is_done(self) -> None:
        (self.dir / "state.json").write_text(json.dumps({"locations": {"v": 2}}))
        self.assertEqual(setup_state.resolve_at_boot(), "done")
        self.assertEqual(setup_state.current()["via"], "existing")
        # and stays done on later boots
        setup_state._reset_for_tests()
        self.assertEqual(setup_state.resolve_at_boot(), "done")

    def test_unresolved_reads_as_done(self) -> None:
        self.assertEqual(setup_state.state(), "done")
        self.assertFalse(setup_state.welcome_showing())

    def test_env_forces(self) -> None:
        (self.dir / "state.json").write_text(json.dumps({"x": 1}))
        with mock.patch.dict(os.environ, {"PIGEON_SETUP": "welcome"}):
            self.assertEqual(setup_state.resolve_at_boot(), "welcome")
        setup_state._reset_for_tests()
        with mock.patch.dict(os.environ, {"PIGEON_SETUP": "done"}):
            self.assertEqual(setup_state.resolve_at_boot(), "done")

    def test_flow(self) -> None:
        seen = []
        setup_state.resolve_at_boot()
        setup_state.add_listener(lambda d: seen.append(d["state"]))
        self.assertTrue(setup_state.note_claimed())
        self.assertFalse(setup_state.note_claimed())
        self.assertEqual(setup_state.state(), "app")
        out = setup_state.set_progress("player", ["location"])
        self.assertEqual(out, {"state": "app", "step": "player", "skipped": ["location"]})
        with self.assertRaises(ValueError):
            setup_state.set_progress("bogus")
        with self.assertRaises(ValueError):
            setup_state.set_progress(skipped=["nope"])
        setup_state.complete("app")
        self.assertEqual(setup_state.current()["skipped"], ["location"])
        self.assertFalse(setup_state.needs_setup())
        with self.assertRaises(ValueError):
            setup_state.set_progress("audio")
        setup_state.reset_to_welcome()
        self.assertEqual(setup_state.public(), {"state": "welcome", "step": None, "skipped": []})
        self.assertEqual(seen, ["app", "app", "done", "welcome"])

    def test_screen_steps_aside_for_on_device_pairing(self) -> None:
        setup_state.reset_to_welcome()
        self.assertTrue(setup_state.screen_wanted())
        setup_state.note_claimed()
        self.assertTrue(setup_state.screen_wanted())
        setup_state.set_progress("player")
        self.assertFalse(setup_state.screen_wanted())
        setup_state.set_progress("audio")
        self.assertFalse(setup_state.screen_wanted())
        setup_state.set_progress("finish")
        self.assertTrue(setup_state.screen_wanted())
        setup_state.complete("app")
        self.assertFalse(setup_state.screen_wanted())

    def test_corrupt_file_reads_as_done(self) -> None:
        (self.dir / "setup_state.json").write_text("{nope")
        self.assertEqual(setup_state.state(), "done")


class ApiTests(_Base):
    def _svc(self) -> ControlService:
        return ControlService(auth=AuthStore())

    def test_hello_and_txt_report_setup(self) -> None:
        setup_state.resolve_at_boot()
        svc = self._svc()
        st, body = svc.handle("GET", API + "/hello", {}, "", None)
        self.assertEqual(body["setup"]["state"], "welcome")
        self.assertEqual(svc.txt_record()["setup"], "1")
        setup_state.complete("manual")
        self.assertEqual(svc.txt_record()["setup"], "0")

    def test_claim_moves_welcome_to_app(self) -> None:
        setup_state.resolve_at_boot()
        svc = self._svc()
        st, body = svc.handle("POST", API + "/claim", {}, "",
                              {"code": svc.auth.pairing_code, "controller": {"name": "iPhone", "id": "c1"}})
        self.assertEqual(st, 200)
        self.assertEqual(setup_state.state(), "app")
        tok = body["token"]
        st, body = svc.handle("PUT", API + "/setup", {}, tok, {"step": "location"})
        self.assertEqual((st, body["step"]), (200, "location"))
        st, body = svc.handle("PUT", API + "/setup", {}, tok, {"step": "nope"})
        self.assertEqual(st, 400)
        st, body = svc.handle("PUT", API + "/setup", {}, tok, {"skipped": "player"})
        self.assertEqual(st, 400)
        st, body = svc.handle("POST", API + "/setup/complete", {}, tok, None)
        self.assertEqual((st, body["state"]), (200, "done"))
        st, _ = svc.handle("PUT", API + "/setup", {}, tok, {"step": "audio"})
        self.assertEqual(st, 409)
        st, body = svc.handle("GET", API + "/setup", {}, tok, None)
        self.assertEqual(body["state"], "done")

    def test_setup_routes_need_token(self) -> None:
        st, _ = self._svc().handle("GET", API + "/setup", {}, "", None)
        self.assertEqual(st, 401)

    def test_welcome_keeps_claims_open_for_a_new_phone(self) -> None:
        a = AuthStore()
        self.assertTrue(a.claim(a.pairing_code, "Old phone", "old"))
        self.assertFalse(a.claim_open())  # claimed, set up
        setup_state.reset_to_welcome()  # factory reset keeps the old phone paired
        self.assertTrue(a.claim_open())
        self.assertTrue(a.claim(a.pairing_code, "New phone", "new"))
        setup_state.note_claimed()
        self.assertFalse(a.claim_open())

    def test_enabled_while_setup_pending(self) -> None:
        with mock.patch.dict(os.environ, {"PIGEON_CONTROL_API": ""}):
            self.assertFalse(control_api.enabled())
            setup_state.reset_to_welcome()
            self.assertTrue(control_api.enabled())
            (self.dir / "state.json").write_text(json.dumps({"control_api": False}))
            self.assertFalse(control_api.enabled())  # an explicit off still wins
        with mock.patch.dict(os.environ, {"PIGEON_CONTROL_API": "0"}):
            self.assertFalse(control_api.enabled())

    def test_setup_url(self) -> None:
        svc = self._svc()
        svc.tls_info = {"port": 8781, "fingerprint_sha256": "ab" * 32}
        setup_state.reset_to_welcome()
        srv = mock.Mock(port=8780)
        with mock.patch.object(control_api, "_service", svc), mock.patch.object(control_api, "_server", srv), \
                mock.patch("pigeon.local_ip.local_ipv4_address", return_value="10.0.0.9"):
            url = control_api.setup_url()
            self.assertEqual(parse_qs(urlparse(url).fragment)["host"], ["10.0.0.9"])
            self.assertEqual(parse_qs(urlparse(url).fragment)["port"], ["8780"])
            self.assertTrue(url.startswith("pigeon://setup#"))
            q = parse_qs(urlparse(url).fragment)
            self.assertEqual(q["code"], [svc.auth.pairing_code])
            self.assertEqual(q["fp"], ["ab" * 32])
            self.assertEqual(q["v"], ["1"])
            svc.auth.claim(svc.auth.pairing_code, "iPhone", "c1")
            setup_state.note_claimed()
            self.assertNotIn("code", parse_qs(urlparse(control_api.setup_url()).fragment))
            self.assertEqual(control_api.setup_controller_name(), "iPhone")
        self.assertEqual(control_api.setup_url(), "")


class ScreenTests(_Base):
    def test_qr_decodes(self) -> None:
        url = "pigeon://setup#v=1&id=pgn-7f3a91&name=Pigeon+Clock&code=482913&fp=" + "ab" * 32
        img = welcome_setup.render_welcome_image(welcome_setup.WelcomeView("welcome", url, "482913"), 1280, 800)
        bgr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
        self.assertEqual(cv2.QRCodeDetector().detectAndDecode(bgr)[0], url)

    def test_other_views_render(self) -> None:
        for view in (welcome_setup.WelcomeView("welcome"), welcome_setup.WelcomeView("app", controller="iPhone")):
            img = welcome_setup.render_welcome_image(view, 1280, 800)
            self.assertEqual(img.size, (1280, 800))
            self.assertGreater(max(np.asarray(img.convert("L")).ravel()), 200)

    def test_knob_routing(self) -> None:
        self.assertFalse(welcome_setup.handle_rotary_action("activate"))  # no overlay
        chosen = []

        class Fake:
            visible = True

            def choose_manual(self) -> None:
                chosen.append(1)

        with mock.patch.object(welcome_setup, "_active", Fake()):
            self.assertTrue(welcome_setup.handle_rotary_action("forward"))
            self.assertTrue(welcome_setup.handle_rotary_action("hold"))
            self.assertEqual(chosen, [])
            self.assertTrue(welcome_setup.handle_rotary_action("activate"))
            self.assertEqual(chosen, [1])


if __name__ == "__main__":
    unittest.main()
