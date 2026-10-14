"""Control API v1 service and HTTP front end (see docs/control_api_v1.md).

``ControlService.handle`` is a pure request -> (status, body) function so routes
are testable without sockets; ``ControlServer`` wraps it in a stdlib
``ThreadingHTTPServer``. Nothing here imports Tk: anything that must run on the
UI thread goes through the injected ``run_on_ui``.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from pigeon import manual_search as ms
from pigeon.control_api import profile
from pigeon.control_api.auth import AuthStore
from pigeon.control_api.events import EventHub, format_event

PREFIX = "/api/v1"
MAX_BODY = 64 * 1024
KEEPALIVE_S = 15.0
POLL_S = 2.0
SUGGEST_MAX = 6

Response = tuple[int, "dict[str, Any] | None"]


def _err(status: int, code: str, message: str, **details: Any) -> Response:
    return status, {"error": {"code": code, "message": message, "details": details}}


class ControlService:
    def __init__(
        self,
        *,
        auth: AuthStore | None = None,
        hub: EventHub | None = None,
        status_provider: Callable[[], dict[str, Any]] | None = None,
        run_on_ui: Callable[[Callable[[], object]], object] | None = None,
        on_manual_set: Callable[[], object] | None = None,
    ) -> None:
        self.auth = auth or AuthStore()
        self.hub = hub or EventHub()
        self._status_provider = status_provider
        self._run_on_ui = run_on_ui or (lambda fn: fn())
        self._on_manual_set = on_manual_set or ms.show_in_now_playing

    # ------------------------------------------------------------------ status
    def _hello_body(self) -> dict[str, Any]:
        return {
            "id": profile.device_id(),
            "name": profile.device_name(),
            "product": profile.product(),
            "api": profile.API_VERSION,
            "version": profile.version(),
            "claimed": self.auth.claimed(),
            "setup_mode": False,
        }

    def _manual_body(self) -> dict[str, Any]:
        entry = ms.current()
        return {"active": True, "entry": entry} if entry else {"active": False}

    def status(self) -> dict[str, Any]:
        provided: dict[str, Any] = {}
        if self._status_provider is not None:
            try:
                provided = dict(self._status_provider() or {})
            except Exception:
                provided = {}
        manual = self._manual_body()
        now = provided.get("now_playing")
        if now is None and manual["active"]:
            e = manual["entry"]
            now = {"title": e.get("title"), "kind": e.get("kind") or None,
                   "tmdb_id": e.get("tmdb_id") or None, "source": "manual"}
        state = provided.get("state") or ("manual" if manual["active"] else "idle")
        return {"state": state, "now_playing": now, "manual_search": manual}

    def device_body(self) -> dict[str, Any]:
        h = self._hello_body()
        return {
            "id": h["id"], "name": h["name"], "product": h["product"],
            "version": h["version"], "api": h["api"], "claimed": h["claimed"],
        }

    def txt_record(self) -> dict[str, str]:
        h = self._hello_body()
        return {
            "id": h["id"], "name": h["name"], "product": h["product"],
            "api": str(h["api"]), "ver": h["version"], "claimed": "1" if h["claimed"] else "0",
        }

    # ---------------------------------------------------------------- dispatch
    def handle(self, method: str, path: str, query: dict[str, list[str]],
               token: str, body: Any) -> Response:
        if not path.startswith(PREFIX + "/"):
            return _err(404, "not_found", "Unknown path.")
        route = path[len(PREFIX):].rstrip("/") or "/"

        # open endpoints
        if route == "/hello" and method == "GET":
            return 200, self._hello_body()
        if route == "/claim" and method == "POST":
            return self._claim(body)

        if self.auth.verify(token) is None:
            return _err(401, "unauthorized", "Missing or invalid token.")

        if route == "/device":
            if method == "GET":
                return 200, self.device_body()
            if method == "PATCH":
                return self._patch_device(body)
        elif route == "/capabilities" and method == "GET":
            return 200, {
                "product": profile.product(),
                "has_local_ui": profile.product() == "clock",
                "capabilities": profile.capabilities(),
                "limits": {},
            }
        elif route == "/status" and method == "GET":
            return 200, self.status()
        elif route.startswith("/search"):
            return self._search(method, route, query, body)
        elif route == "/controllers":
            if method == "GET":
                return 200, {"controllers": self.auth.controllers()}
        elif route == "/controllers/invite" and method == "POST":
            return 200, {"code": self.auth.invite(), "expires_in_s": 300}
        else:
            m = re.fullmatch(r"/controllers/([^/]+)", route)
            if m and method == "DELETE":
                if self.auth.revoke(m.group(1)):
                    return 204, None
                return _err(404, "not_found", "Unknown controller.")
        return _err(404, "not_found", "Unknown endpoint or method.")

    # ------------------------------------------------------------------ routes
    def _claim(self, body: Any) -> Response:
        if not isinstance(body, dict):
            return _err(400, "bad_request", "JSON object required.")
        if not self.auth.claim_open():
            return _err(403, "already_claimed", "Device already has a controller.")
        ctl = body.get("controller") if isinstance(body.get("controller"), dict) else {}
        try:
            token = self.auth.claim(
                str(body.get("code") or ""), str(ctl.get("name") or ""), str(ctl.get("id") or "")
            )
        except PermissionError:
            return _err(429, "rate_limited", "Too many attempts.",
                        retry_after_s=int(self.auth.retry_after()) + 1)
        if token is None:
            return _err(403, "not_claimed", "Pairing code rejected.")
        self.hub.publish("device", {"claimed": True})
        return 200, {"token": token, "device": {"id": profile.device_id(), "name": profile.device_name()}}

    def _patch_device(self, body: Any) -> Response:
        if not isinstance(body, dict) or "name" not in body:
            return _err(400, "bad_request", "Expected {\"name\": ...}.", fields=["name"])
        try:
            name = profile.set_device_name(body["name"])
        except ValueError as exc:
            return _err(400, "bad_request", str(exc), fields=["name"])
        self.hub.publish("device", {"name": name})
        return 200, self.device_body()

    def _search(self, method: str, route: str, query: dict[str, list[str]], body: Any) -> Response:
        if not profile.has_capability("manual_search"):
            return _err(422, "unsupported", "manual_search not supported on this device.")
        if route == "/search/suggest" and method == "GET":
            q = " ".join((query.get("q") or [""])[0].split())
            if len(q) < 2:
                return _err(400, "bad_request", "q must be at least 2 characters.", fields=["q"])
            try:
                limit = int((query.get("limit") or ["3"])[0])
            except ValueError:
                return _err(400, "bad_request", "limit must be an integer.", fields=["limit"])
            limit = max(1, min(SUGGEST_MAX, limit))
            rows = ms.suggest_now(q, limit=limit)
            return 200, {"query": q, "results": [
                {"tmdb_id": r.get("tmdb_id") or None, "kind": r.get("kind"),
                 "title": r.get("title"), "year": int(r["year"]) if str(r.get("year") or "").isdigit() else None}
                for r in rows
            ]}
        if route == "/search/current":
            if method == "GET":
                return 200, self._manual_body()
            if method == "PUT":
                if not isinstance(body, dict):
                    return _err(400, "bad_request", "JSON object required.")
                entry = ms.set_entry(body)
                if entry is None:
                    return _err(400, "bad_request", "title is required.", fields=["title"])
                self._run_on_ui(self._on_manual_set)
                self.hub.publish("manual_search", self._manual_body())
                return 200, self._manual_body()
            if method == "DELETE":
                self._run_on_ui(ms.clear)
                self.hub.publish("manual_search", self._manual_body())
                return 204, None
        return _err(404, "not_found", "Unknown endpoint or method.")


class _Handler(BaseHTTPRequestHandler):
    service: ControlService  # set on the subclass by ControlServer
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # quiet
        pass

    def _token(self) -> str:
        h = self.headers.get("Authorization", "")
        return h[7:].strip() if h.lower().startswith("bearer ") else ""

    def _send(self, status: int, body: dict | None) -> None:
        raw = b"" if body is None else json.dumps(body).encode("utf-8")
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        if status == 429 and body:
            ra = body["error"]["details"].get("retry_after_s")
            if ra:
                self.send_header("Retry-After", str(ra))
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def _dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        body: Any = None
        if method in ("POST", "PUT", "PATCH"):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n > MAX_BODY:
                self._send(*_err(400, "bad_request", "Body too large."))
                return
            if n:
                try:
                    body = json.loads(self.rfile.read(n).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    self._send(*_err(400, "bad_request", "Malformed JSON."))
                    return
        if method == "GET" and url.path.rstrip("/") == PREFIX + "/events":
            self._events()
            return
        status, resp = self.service.handle(
            method, url.path, parse_qs(url.query), self._token(), body
        )
        self._send(status, resp)

    def _events(self) -> None:
        svc = self.service
        if svc.auth.verify(self._token()) is None:
            self._send(*_err(401, "unauthorized", "Missing or invalid token."))
            return
        q = svc.hub.subscribe()
        if q is None:
            self._send(*_err(503, "busy", "Too many event streams."))
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(format_event("snapshot", svc.status()))
            self.wfile.flush()
            while True:
                try:
                    chunk = q.get(timeout=KEEPALIVE_S)
                except queue.Empty:
                    chunk = b": keepalive\n\n"
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            svc.hub.unsubscribe(q)

    def do_GET(self) -> None: self._dispatch("GET")
    def do_POST(self) -> None: self._dispatch("POST")
    def do_PUT(self) -> None: self._dispatch("PUT")
    def do_PATCH(self) -> None: self._dispatch("PATCH")
    def do_DELETE(self) -> None: self._dispatch("DELETE")


class ControlServer:
    def __init__(self, service: ControlService, *, host: str = "0.0.0.0",
                 port: int = profile.DEFAULT_PORT) -> None:
        handler = type("BoundHandler", (_Handler,), {"service": service})
        self.service = service
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._httpd.daemon_threads = True
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    def start(self) -> None:
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True,
                                        name="pigeon-control-api")
        self._thread.start()
        threading.Thread(target=self._poll_loop, daemon=True, name="pigeon-control-poll").start()

    def _poll_loop(self) -> None:
        last: str | None = None
        while not self._stop.wait(POLL_S):
            try:
                st = self.service.status()
                key = json.dumps(st, sort_keys=True)
                if last is not None and key != last:
                    self.service.hub.publish("now_playing", st["now_playing"])
                last = key
            except Exception:
                pass

    def stop(self) -> None:
        self._stop.set()
        self._httpd.shutdown()
        self._httpd.server_close()
