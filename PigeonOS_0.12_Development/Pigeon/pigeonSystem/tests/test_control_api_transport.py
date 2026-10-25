"""Control API transport: pinned TLS, plain-listener restriction, connection limits and timeouts."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import ssl
import stat
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.control_api import server as server_mod  # noqa: E402
from pigeon.control_api import tls  # noqa: E402
from pigeon.control_api.server import ControlServer, ControlService  # noqa: E402
from tests.test_control_api import _Base  # noqa: E402


def _client_ctx(identity: tls.TlsIdentity) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False  # pinned by certificate, not by name
    ctx.load_verify_locations(identity.certfile)
    return ctx


class _Net(_Base):
    def start(self, **kw) -> tuple[ControlService, ControlServer, tls.TlsIdentity]:
        ident = tls.ensure_identity(Path(self._tmp.name), device_id="pgn-test")
        svc = ControlService(run_on_ui=lambda fn: fn(), on_manual_set=lambda: None)
        srv = ControlServer(svc, host="127.0.0.1", port=0, tls=ident, tls_port=0, **kw)
        srv.start()
        self.addCleanup(srv.stop)
        return svc, srv, ident

    @staticmethod
    def req(conn: http.client.HTTPConnection, method: str, path: str, body=None, token=None):
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = "Bearer " + token
        conn.request(method, "/api/v1" + path, json.dumps(body) if body is not None else None, h)
        r = conn.getresponse()
        raw = r.read()
        conn.close()  # auto-reopens on the next request
        return r.status, (json.loads(raw) if raw else None)

    def https(self, srv, ident) -> http.client.HTTPSConnection:
        return http.client.HTTPSConnection("127.0.0.1", srv.tls_port, timeout=5, context=_client_ctx(ident))

    def plain(self, srv) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)


class TlsIdentityTests(_Base):
    def test_created_private_stable_and_fingerprinted(self) -> None:
        d = Path(self._tmp.name)
        a = tls.ensure_identity(d, device_id="pgn-1")
        self.assertEqual(stat.S_IMODE(os.stat(a.keyfile).st_mode), 0o600)
        der = ssl.PEM_cert_to_DER_cert(Path(a.certfile).read_text())
        self.assertEqual(a.fingerprint_sha256, hashlib.sha256(der).hexdigest())
        b = tls.ensure_identity(d, device_id="pgn-1")
        self.assertEqual(a.fingerprint_sha256, b.fingerprint_sha256)  # reused, not regenerated

    def test_curve_is_named_not_explicit(self) -> None:
        # Apple's TLS stack rejects certificates that spell out the curve parameters.
        a = tls.ensure_identity(Path(self._tmp.name))
        out = subprocess.run(["openssl", "x509", "-in", a.certfile, "-noout", "-text"],
                             capture_output=True, text=True).stdout
        self.assertNotIn("Field Type", out)

    def test_corrupt_identity_is_replaced(self) -> None:
        d = Path(self._tmp.name)
        a = tls.ensure_identity(d)
        Path(a.certfile).write_text("junk")
        b = tls.ensure_identity(d)
        self.assertNotEqual(a.fingerprint_sha256, b.fingerprint_sha256)
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(b.certfile, b.keyfile)

    def test_no_generator_raises(self) -> None:
        with mock.patch.object(tls, "_generate_openssl", return_value=False), \
                mock.patch.object(tls, "_generate_cryptography", return_value=False):
            with self.assertRaises(RuntimeError):
                tls.ensure_identity(Path(self._tmp.name))


class TlsServingTests(_Net):
    def test_claim_and_api_over_pinned_tls(self) -> None:
        svc, srv, ident = self.start()
        c = self.plain(srv)
        st, hello = self.req(c, "GET", "/hello")
        self.assertEqual(st, 200)
        self.assertEqual(hello["tls"], {"port": srv.tls_port, "fingerprint_sha256": ident.fingerprint_sha256})
        self.assertEqual(svc.txt_record()["fp"], ident.fingerprint_sha256)

        s = self.https(srv, ident)
        st, claim = self.req(s, "POST", "/claim", {"code": svc.auth.pairing_code,
                                                   "controller": {"id": "c1", "name": "me"}})
        self.assertEqual(st, 200)
        tok = claim["token"]
        self.assertEqual(self.req(s, "GET", "/device", token=tok)[0], 200)
        # the pin matches what the server actually presents
        peer = ssl.get_server_certificate(("127.0.0.1", srv.tls_port))
        self.assertEqual(hashlib.sha256(ssl.PEM_cert_to_DER_cert(peer)).hexdigest(), ident.fingerprint_sha256)

    def test_untrusted_client_rejects_cert(self) -> None:
        _, srv, _ = self.start()
        c = http.client.HTTPSConnection("127.0.0.1", srv.tls_port, timeout=5,
                                        context=ssl.create_default_context())
        with self.assertRaises(ssl.SSLError):
            c.request("GET", "/api/v1/hello")

    def test_plain_listener_refuses_everything_but_hello(self) -> None:
        svc, srv, _ = self.start()
        tok = svc.auth.claim(svc.auth.pairing_code, "t", "c1")
        for method, path, body, token in [
            ("POST", "/claim", {"code": svc.auth.pairing_code, "controller": {"id": "x", "name": "x"}}, None),
            ("GET", "/status", None, tok),
            ("GET", "/events", None, tok),
            ("PATCH", "/display", {"brightness": 1}, tok),
        ]:
            st, body_ = self.req(self.plain(srv), method, path, body, token)
            self.assertEqual(st, 426, path)
            self.assertEqual(body_["error"]["code"], "tls_required")
        self.assertEqual(self.req(self.plain(srv), "GET", "/hello")[0], 200)
        # a token sent to /hello in clear is still not honoured anywhere on this listener
        self.assertEqual(self.req(self.plain(srv), "GET", "/hello", token=tok)[0], 426)
        self.assertTrue(svc.auth.verify(tok))  # (and was not consumed or revoked)

    def test_allow_plain_restores_legacy_behaviour(self) -> None:
        svc, srv, _ = self.start(allow_plain=True)
        tok = svc.auth.claim(svc.auth.pairing_code, "t", "c1")
        self.assertEqual(self.req(self.plain(srv), "GET", "/device", token=tok)[0], 200)

    def test_bad_content_length_closes(self) -> None:
        _, srv, ident = self.start()
        s = socket.create_connection(("127.0.0.1", srv.tls_port), timeout=5)
        t = _client_ctx(ident).wrap_socket(s, server_hostname="pigeon.local")
        t.sendall(b"POST /api/v1/claim HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\n")
        self.assertIn(b" 400 ", t.recv(200))
        t.close()


class LimitTests(_Net):
    def setUp(self) -> None:
        super().setUp()
        for target, val in ((server_mod._Handler, "timeout"), (server_mod, "REQUEST_DEADLINE_S")):
            p = mock.patch.object(target, val, 0.6 if val == "timeout" else 1.0)
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def _closed_within(sock: socket.socket, secs: float) -> bool:
        sock.settimeout(secs)
        try:
            return sock.recv(1) == b""
        except socket.timeout:
            return False
        except OSError:
            return True

    def test_silent_connection_is_dropped(self) -> None:
        _, srv, _ = self.start()
        s = socket.create_connection(("127.0.0.1", srv.port))
        self.addCleanup(s.close)
        self.assertTrue(self._closed_within(s, 3))

    def test_slow_drip_headers_hit_deadline(self) -> None:
        _, srv, _ = self.start()
        s = socket.create_connection(("127.0.0.1", srv.port))
        self.addCleanup(s.close)
        s.sendall(b"GET /api/v1/hello HTTP/1.1\r\n")
        t0, dropped = time.monotonic(), False
        while time.monotonic() - t0 < 4:  # a byte every 0.3s defeats the per-read timeout alone
            try:
                s.sendall(b"X-A: b\r\n"[:1])
            except OSError:
                dropped = True
                break
            time.sleep(0.3)
        self.assertTrue(dropped)
        self.assertLess(time.monotonic() - t0, 3)

    def test_stalled_tls_handshake_neither_blocks_accept_nor_lingers(self) -> None:
        _, srv, ident = self.start()
        stuck = socket.create_connection(("127.0.0.1", srv.tls_port))
        self.addCleanup(stuck.close)
        st, _ = self.req(self.https(srv, ident), "GET", "/hello")
        self.assertEqual(st, 200)
        self.assertTrue(self._closed_within(stuck, 3))

    def test_connection_cap_and_recovery(self) -> None:
        _, srv, _ = self.start(max_connections=3, max_per_ip=3)
        held = [socket.create_connection(("127.0.0.1", srv.port)) for _ in range(3)]
        time.sleep(0.2)
        over = socket.create_connection(("127.0.0.1", srv.port))
        over.settimeout(2)
        self.assertIn(b" 503 ", over.recv(200))
        over.close()
        for h in held:
            h.close()
        deadline = time.monotonic() + 3
        while True:  # slots free once the handler threads notice the closes
            try:
                st, _ = self.req(self.plain(srv), "GET", "/hello")
                if st == 200:
                    break
            except (OSError, http.client.HTTPException):
                pass
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.1)

    def test_per_ip_cap(self) -> None:
        _, srv, _ = self.start(max_connections=10, max_per_ip=2)
        held = [socket.create_connection(("127.0.0.1", srv.port)) for _ in range(2)]
        self.addCleanup(lambda: [h.close() for h in held])
        time.sleep(0.2)
        over = socket.create_connection(("127.0.0.1", srv.port))
        self.addCleanup(over.close)
        over.settimeout(2)
        self.assertIn(b" 503 ", over.recv(200))


if __name__ == "__main__":
    unittest.main()
