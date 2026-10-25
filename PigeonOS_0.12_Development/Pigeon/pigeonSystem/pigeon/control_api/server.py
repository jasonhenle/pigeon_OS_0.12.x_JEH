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
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlparse

from pigeon import manual_search as ms
from pigeon.control_api import profile, tls as tls_mod
from pigeon.control_api.auth import DISPLAY_TTL_S, AuthStore
from pigeon.control_api.events import EventHub, format_event

PREFIX = "/api/v1"
MAX_BODY = 64 * 1024
KEEPALIVE_S = 15.0
POLL_S = 2.0
SUGGEST_MAX = 12
# Connection hygiene (Zero 2 W budget). Every connection costs a thread, so cap them, and make slow or silent
# peers pay: ``REQUEST_TIMEOUT_S`` bounds each socket read/write (TLS handshake, headers, body, idle keep-alive,
# a stalled SSE reader) and ``REQUEST_DEADLINE_S`` bounds the whole request-reading phase against slow-drip senders.
MAX_CONNECTIONS = 24
MAX_CONNECTIONS_PER_IP = 8
REQUEST_TIMEOUT_S = 10.0
REQUEST_DEADLINE_S = 15.0
DEFAULT_TLS_PORT = 8781
# The only routes served on the unencrypted listener once TLS is on: none carries a token, claim code or setting.
_PLAIN_OK = frozenset({("GET", "/hello"), ("POST", "/pair/start"), ("POST", "/pair/cancel")})

Response = tuple[int, "dict[str, Any] | None"]


def _err(status: int, code: str, message: str, **details: Any) -> Response:
    return status, {"error": {"code": code, "message": message, "details": details}}



def _suggestion_json(row: dict, logos: dict[int, str]) -> dict[str, Any]:
    """One search hit: ids, title, year, plus artwork URLs when known."""
    tmdb_id = row.get("tmdb_id") or None
    out: dict[str, Any] = {
        "tmdb_id": tmdb_id,
        "kind": row.get("kind"),
        "title": row.get("title"),
        "year": int(row["year"]) if str(row.get("year") or "").isdigit() else None,
    }
    poster = ms.poster_url(row)
    if poster:
        out["poster_url"] = poster
    if tmdb_id and tmdb_id in logos:
        out["logo_url"] = logos[tmdb_id]
    return out


class ControlService:
    def __init__(
        self,
        *,
        auth: AuthStore | None = None,
        hub: EventHub | None = None,
        status_provider: Callable[[], dict[str, Any]] | None = None,
        run_on_ui: Callable[[Callable[[], object]], object] | None = None,
        on_manual_set: Callable[[], object] | None = None,
        metadata_provider: Callable[[], Mapping[str, Any] | None] | None = None,
        fetch_provider: Callable[[], dict[str, Any]] | None = None,
        respawn: Callable[[str, str], object] | None = None,
        apply_location: Callable[[], object] | None = None,
        apply_settings: Callable[[], object] | None = None,
        restart: Callable[[], object] | None = None,
        apply_update: Callable[[], object] | None = None,
        update_state: Callable[[], Mapping[str, Any]] | None = None,
        pair_scan: Callable[[str], object] | None = None,
    ) -> None:
        self.auth = auth or AuthStore()
        self.hub = hub or EventHub()
        self._status_provider = status_provider
        self._run_on_ui = run_on_ui or (lambda fn: fn())
        self._on_manual_set = on_manual_set or ms.show_in_now_playing
        self._metadata = metadata_provider or (lambda: None)
        self._fetch = fetch_provider or (lambda: {})
        self._respawn = respawn
        self._apply_location = apply_location
        self._apply_settings = apply_settings
        self._restart = restart
        self._apply_update = apply_update
        self._update_state = update_state or (lambda: {})
        self._pair_scan = pair_scan
        # Called with the new TXT record whenever it changes (claimed, renamed).
        self.txt_listeners: list[Callable[[dict[str, str]], object]] = []
        # ``{"port": int, "fingerprint_sha256": str}`` once a TLS listener is up (set by ControlServer).
        self.tls_info: dict[str, Any] | None = None

    # ------------------------------------------------------------------ status
    def _hello_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "id": profile.device_id(),
            "name": profile.device_name(),
            "product": profile.product(),
            "api": profile.API_VERSION,
            "version": profile.version(),
            "claimed": self.auth.claimed(),
            "setup_mode": False,
        }
        if self.tls_info:
            body["tls"] = dict(self.tls_info)
        return body

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
        txt = {
            "id": h["id"], "name": h["name"], "product": h["product"],
            "api": str(h["api"]), "ver": h["version"], "claimed": "1" if h["claimed"] else "0",
        }
        if self.tls_info:
            txt["tlsport"] = str(self.tls_info["port"])
            txt["fp"] = str(self.tls_info["fingerprint_sha256"])
        return txt

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
        if route == "/pair/start" and method == "POST":
            if not self.auth.request_display():
                return _err(403, "already_claimed", "Device already has a controller.")
            return 200, {"expires_in_s": int(DISPLAY_TTL_S)}
        if route == "/pair/cancel" and method == "POST":
            self.auth.cancel_display()
            return 204, None

        if self.auth.verify(token) is None:
            return _err(401, "unauthorized", "Missing or invalid token.")

        if route == "/device":
            if method == "GET":
                return 200, self.device_body()
            if method == "PATCH":
                return self._patch_device(body)
        elif route == "/device/restart" and method == "POST":
            return self._restart_device()
        elif route == "/update":
            return self._update(method)
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
        elif route.startswith("/now-playing"):
            return self._now_playing(method, route, body)
        elif route.startswith("/rooms"):
            return self._rooms(method, route, body)
        elif route == "/pigeon-settings":
            return self._pigeon_settings(method, body)
        elif route == "/display":
            return self._display(method, body)
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

    def _restart_device(self) -> Response:
        if not profile.has_capability("restart"):
            return _err(422, "unsupported", "restart not supported on this device.")
        if self._restart is None:
            return _err(503, "busy", "Restart is not available right now.")
        if self._update_state().get("applying"):
            return _err(503, "busy", "The device is installing an update.")
        self.hub.publish("device", {"restarting": True})
        self._on_ui(self._restart)
        return 202, {"state": "restarting"}

    def _update(self, method: str) -> Response:
        """GET checks GitHub for a newer version; POST installs it and restarts."""
        if not profile.has_capability("update"):
            return _err(422, "unsupported", "update not supported on this device.")
        state = dict(self._update_state() or {})
        if method == "GET":
            if state.get("applying"):
                return 200, {"local_version": profile.version(), "remote_version": None,
                             "update_available": False, "error": None, "applying": True}
            from pigeon.update_check import check_for_update

            try:
                res = check_for_update(force=True)
            except Exception as exc:  # network trouble must not 500 the app
                return 200, {"local_version": profile.version(), "remote_version": None,
                             "update_available": False, "error": str(exc), "applying": False}
            return 200, {
                "local_version": res.local_version,
                "remote_version": res.remote_version,
                "update_available": bool(res.update_available),
                "error": res.error or None,
                "applying": False,
            }
        if method == "POST":
            if self._apply_update is None:
                return _err(503, "busy", "Updating is not available right now.")
            if state.get("applying"):
                return _err(409, "conflict", "An update is already installing.")
            self.hub.publish("device", {"updating": True})
            self._on_ui(self._apply_update)
            return 202, {"state": "updating"}
        return _err(404, "not_found", "Unknown endpoint or method.")

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
            kind = (query.get("kind") or [""])[0]
            if kind not in ("", "movie", "tv"):
                return _err(400, "bad_request", "kind must be movie or tv.", fields=["kind"])
            year = (query.get("year") or [""])[0]
            if year and not re.fullmatch(r"\d{4}", year):
                return _err(400, "bad_request", "year must be four digits.", fields=["year"])
            try:
                rows = ms.suggest_now(q, limit=limit, strict=True, kind=kind or None, year=year or None)
            except ms.SuggestionSearchError as exc:
                return _err(503, exc.code, str(exc))
            logos = ms.logo_urls(rows) if (query.get("logos") or [""])[0] == "1" else {}
            return 200, {"query": q, "results": [_suggestion_json(r, logos) for r in rows]}
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


    # ------------------------------------------------- now playing correction
    def _override_detail(self) -> dict[str, Any]:
        from pigeon.control_api import now_playing_override as npo

        md = self._metadata() or {}
        try:
            from pigeon.raw_title import (
                resolve_metadata_tmdb_query,
                tmdb_query_candidates_from_metadata,
            )

            resolved = resolve_metadata_tmdb_query(md)
            candidates = tmdb_query_candidates_from_metadata(md)
        except Exception:
            resolved, candidates = "", []
        fetch = {}
        try:
            fetch = dict(self._fetch() or {})
        except Exception:
            pass
        trace: dict[str, Any] = {}
        try:
            from pigeon.tmdb_poster import last_fetch_trace

            trace = last_fetch_trace()
        except Exception:
            pass
        tmdb_id = trace.get("tmdb_id")
        match = None
        if trace.get("tmdb_title") or fetch.get("display_title"):
            match = {
                "title": fetch.get("display_title") or trace.get("tmdb_title"),
                "kind": trace.get("kind"),
                "tmdb_id": int(tmdb_id) if isinstance(tmdb_id, int) else None,
                "year": trace.get("tmdb_year") or None,
                "outcome": trace.get("outcome") or ("matched" if tmdb_id else None),
                "forced": bool(trace.get("forced_pick")),
            }
        ov = npo.get()
        title = str(md.get("series_name") or md.get("title") or "").strip()
        return {
            "content_active": bool(title or md.get("query")),
            "app": str(md.get("app_name") or "") or None,
            "inputs": npo.input_rows(md),
            "query": {
                "apple_tv": str(md.get("query") or "") or None,
                "resolved": resolved or None,
                "candidates": candidates,
                "searched": fetch.get("refined") or None,
                "prefer": fetch.get("prefer") or None,
                "in_flight": bool(fetch.get("in_flight")),
            },
            "match": match,
            "override": ov.summary() if ov else {"active": False},
        }

    def _now_playing(self, method: str, route: str, body: Any) -> Response:
        from pigeon.control_api import now_playing_override as npo

        if not profile.has_capability("now_playing_override"):
            return _err(422, "unsupported", "now_playing_override not supported on this device.")
        if route == "/now-playing/detail" and method == "GET":
            return 200, self._override_detail()
        if route == "/now-playing/refresh" and method == "POST":
            return self._refresh_tmdb()
        if route == "/now-playing/preview" and method == "POST":
            if not isinstance(body, dict):
                return _err(400, "bad_request", "JSON object required.")
            fields = body.get("fields") if isinstance(body.get("fields"), dict) else {}
            q = npo.derive_query(self._metadata(), fields, body.get("year"))
            if not q:
                return _err(400, "bad_request", "Nothing to search for.", fields=["fields"])
            rows = ms.suggest_now(q, limit=SUGGEST_MAX)
            return 200, {"query": q, "candidates": [_suggestion_json(r, {}) for r in rows]}
        if route == "/now-playing/override" and method == "PUT":
            if not isinstance(body, dict):
                return _err(400, "bad_request", "JSON object required.")
            md = self._metadata()
            try:
                pick = body.get("pick")
                if isinstance(pick, dict):
                    ov = npo.set_pick(md, title=pick.get("title"), kind=str(pick.get("kind") or ""),
                                      tmdb_id=int(pick.get("tmdb_id") or 0), year=pick.get("year"))
                else:
                    fields = body.get("fields") if isinstance(body.get("fields"), dict) else {}
                    ov = npo.set_fields(md, fields, year=body.get("year"), kind=body.get("kind"))
            except (ValueError, TypeError) as exc:
                return _err(400, "bad_request", str(exc))
            self._do_respawn(ov.query, ov.prefer)
            self.hub.publish("override", ov.summary())
            return 200, self._override_detail()
        if route == "/now-playing/override" and method == "DELETE":
            md = self._metadata() or {}
            npo.clear(md, forget=True)
            try:
                from pigeon.raw_title import resolve_metadata_tmdb_query

                detected = resolve_metadata_tmdb_query(md)
            except Exception:
                detected = ""
            if detected:
                self._do_respawn(detected, str(md.get("prefer") or "auto"))
            self.hub.publish("override", {"active": False})
            return 200, self._override_detail()
        return _err(404, "not_found", "Unknown endpoint or method.")

    # ------------------------------------------------------- rooms / settings
    def _refresh_tmdb(self) -> Response:
        """Force Pigeon to run its TMDb lookup again for what is playing."""
        if not profile.has_capability("tmdb_refresh"):
            return _err(422, "unsupported", "tmdb_refresh not supported on this device.")
        md = self._metadata() or {}
        query, prefer = "", str(md.get("prefer") or "auto")
        try:
            from pigeon.raw_title import resolve_metadata_tmdb_query

            query = resolve_metadata_tmdb_query(md) or ""
        except Exception:
            pass
        fetch: dict[str, Any] = {}
        try:
            fetch = dict(self._fetch() or {})
        except Exception:
            pass
        query = query or str(fetch.get("input") or "")
        prefer = str(fetch.get("prefer") or prefer or "auto")
        if not query.strip():
            return _err(409, "conflict", "Nothing is playing to look up.")
        self._do_respawn(query, prefer)
        self.hub.publish("override", {"active": False, "refreshed": True})
        return 200, self._override_detail()

    def _rooms_pairing(self, room_id: str, body: Any) -> Response:
        """Start the on-screen player / audio pairing flow for a room."""
        kind = body.get("kind") if isinstance(body, dict) else None
        cap = {"player": "pairing_player", "audio": "pairing_receiver"}.get(str(kind))
        if cap is None:
            return _err(400, "bad_request", "kind must be player or audio.", fields=["kind"])
        if not profile.has_capability(cap):
            return _err(422, "unsupported", f"{cap} not supported on this device.")
        if self._pair_scan is None:
            return _err(503, "busy", "Pairing is not available right now.")
        from pigeon.control_api import device_settings as ds

        if not any(r["id"] == room_id for r in ds.read_rooms()["rooms"]):
            return _err(404, "not_found", "Unknown room.")
        try:
            ds.switch_room(room_id)
        except KeyError:
            return _err(404, "not_found", "Unknown room.")
        self._on_ui(self._apply_location)
        scan = self._pair_scan
        self._on_ui(lambda: scan(str(kind)))
        self.hub.publish("settings", {"changed": ["rooms"]})
        return 202, {"state": "scanning", "kind": kind}

    def _on_ui(self, fn: Callable[[], object] | None) -> None:
        if fn is not None:
            self._run_on_ui(fn)

    def _rooms(self, method: str, route: str, body: Any) -> Response:
        from pigeon.control_api import device_settings as ds

        if not profile.has_capability("rooms"):
            return _err(422, "unsupported", "rooms not supported on this device.")
        if route == "/rooms" and method == "GET":
            return 200, ds.read_rooms()
        if route == "/rooms/current" and method == "PUT":
            rid = body.get("id") if isinstance(body, dict) else None
            if not rid:
                return _err(400, "bad_request", "id is required.", fields=["id"])
            try:
                ds.switch_room(str(rid))
            except KeyError:
                return _err(404, "not_found", "Unknown room.")
            self._on_ui(self._apply_location)
            self.hub.publish("settings", {"changed": ["rooms"]})
            return 200, ds.read_rooms()
        mp = re.fullmatch(r"/rooms/([^/]+)/pairing", route)
        if mp and method == "POST":
            return self._rooms_pairing(mp.group(1), body)
        m = re.fullmatch(r"/rooms/([^/]+)", route)
        if m and method == "PATCH":
            if not isinstance(body, dict) or "name" not in body:
                return _err(400, "bad_request", "Expected {\"name\": ...}.", fields=["name"])
            try:
                ds.rename_room(m.group(1), body["name"])
            except ValueError as exc:
                return _err(400, "bad_request", str(exc), fields=["name"])
            except KeyError:
                return _err(404, "not_found", "Unknown room.")
            self._on_ui(self._apply_location)
            self.hub.publish("settings", {"changed": ["rooms"]})
            return 200, ds.read_rooms()
        return _err(404, "not_found", "Unknown endpoint or method.")

    def _display(self, method: str, body: Any) -> Response:
        from pigeon.control_api import device_settings as ds

        if not profile.has_capability("display_brightness"):
            return _err(422, "unsupported", "display_brightness not supported on this device.")
        if method == "GET":
            return 200, ds.read_display()
        if method == "PATCH":
            if not isinstance(body, dict):
                return _err(400, "bad_request", "JSON object required.")
            try:
                ds.patch_display(body)
            except ValueError as exc:
                return _err(400, "bad_request", "Invalid value.", fields=str(exc).split(","))
            self._on_ui(self._apply_settings)
            self.hub.publish("settings", {"changed": ["display"]})
            return 200, ds.read_display()
        return _err(404, "not_found", "Unknown endpoint or method.")

    def _pigeon_settings(self, method: str, body: Any) -> Response:
        from pigeon.control_api import device_settings as ds

        if not profile.has_capability("pigeon_settings"):
            return _err(422, "unsupported", "pigeon_settings not supported on this device.")
        if method == "GET":
            return 200, ds.read_pigeon_settings()
        if method == "PATCH":
            if not isinstance(body, dict) or not body:
                return _err(400, "bad_request", "JSON object required.")
            try:
                ds.patch_pigeon_settings(body)
            except ValueError as exc:
                return _err(400, "bad_request", "Invalid value.", fields=str(exc).split(","))
            self._on_ui(self._apply_settings)
            self.hub.publish("settings", {"changed": sorted(body)})
            return 200, ds.read_pigeon_settings()
        return _err(404, "not_found", "Unknown endpoint or method.")

    def _do_respawn(self, query: str, prefer: str) -> None:
        if self._respawn is None:
            return
        fn = self._respawn
        self._run_on_ui(lambda: fn(query, prefer))


class _Handler(BaseHTTPRequestHandler):
    service: ControlService  # set on the subclass by ControlServer
    secure = False           # this listener speaks TLS
    plain_restricted = False  # unencrypted listener that only serves ``_PLAIN_OK`` (TLS is on elsewhere)
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT_S  # StreamRequestHandler applies this to the socket

    def log_message(self, *args: Any) -> None:  # quiet
        pass

    def setup(self) -> None:
        if self.secure:
            # Handshake here, on the connection's own thread and under the socket timeout, never in accept().
            self.request.settimeout(self.timeout)
            self.request.do_handshake()
        super().setup()

    def handle_one_request(self) -> None:
        self._deadline = threading.Timer(REQUEST_DEADLINE_S, self._abort)
        self._deadline.daemon = True
        self._deadline.start()
        try:
            super().handle_one_request()
        finally:
            self._deadline.cancel()

    def _abort(self) -> None:
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
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
        if self.plain_restricted and not self._plain_allowed(method, url.path):
            # Refuse before reading the body or looking at the token: it already crossed the wire in clear.
            self.close_connection = True
            info = self.service.tls_info or {}
            self._send(*_err(426, "tls_required", "Use HTTPS on the TLS port; pin the certificate fingerprint "
                             "from GET /hello.", tls=info))
            return
        body: Any = None
        if method in ("POST", "PUT", "PATCH"):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                self.close_connection = True  # unread body would corrupt the next request
                self._send(*_err(400, "bad_request", "Body too large." if n > 0 else "Bad Content-Length."))
                return
            if n:
                try:
                    body = json.loads(self.rfile.read(n).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    self._send(*_err(400, "bad_request", "Malformed JSON."))
                    return
        self._deadline.cancel()  # request fully read; handling (and SSE) may legitimately take longer
        if method == "GET" and url.path.rstrip("/") == PREFIX + "/events":
            self._events()
            return
        status, resp = self.service.handle(
            method, url.path, parse_qs(url.query), self._token(), body
        )
        self._send(status, resp)

    def _plain_allowed(self, method: str, path: str) -> bool:
        if self.headers.get("Authorization"):
            return False
        if not path.startswith(PREFIX + "/"):
            return False
        return (method, path[len(PREFIX):].rstrip("/") or "/") in _PLAIN_OK

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


class _Limiter:
    """Total and per-client connection budget; ``acquire`` never blocks."""

    def __init__(self, total: int, per_ip: int) -> None:
        self._total, self._per_ip = total, per_ip
        self._lock = threading.Lock()
        self._n = 0
        self._by_ip: dict[str, int] = {}

    def acquire(self, ip: str) -> bool:
        with self._lock:
            if self._n >= self._total or self._by_ip.get(ip, 0) >= self._per_ip:
                return False
            self._n += 1
            self._by_ip[ip] = self._by_ip.get(ip, 0) + 1
            return True

    def release(self, ip: str) -> None:
        with self._lock:
            self._n = max(0, self._n - 1)
            left = self._by_ip.get(ip, 0) - 1
            if left > 0:
                self._by_ip[ip] = left
            else:
                self._by_ip.pop(ip, None)


_BUSY = (b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nRetry-After: 2\r\n"
         b"Connection: close\r\n\r\n")


class _BoundedHTTPServer(ThreadingHTTPServer):
    """Thread-per-connection, but only while the shared ``_Limiter`` has room; over budget is refused up front."""

    daemon_threads = True
    request_queue_size = 32

    def __init__(self, addr: tuple[str, int], handler: type, limiter: _Limiter,
                 ssl_context: ssl.SSLContext | None = None) -> None:
        self._limiter = limiter
        self._ssl = ssl_context
        super().__init__(addr, handler)

    def get_request(self) -> tuple[Any, Any]:
        sock, addr = self.socket.accept()
        if self._ssl is not None:
            # No handshake yet: a peer that never speaks must not stall the accept loop.
            sock = self._ssl.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, addr

    def process_request(self, request: Any, client_address: Any) -> None:
        ip = client_address[0]
        if not self._limiter.acquire(ip):
            if self._ssl is None:
                try:
                    request.settimeout(1.0)
                    request.sendall(_BUSY)
                except OSError:
                    pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._limiter.release(ip)
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._limiter.release(client_address[0])

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass  # handshake failures, resets and timeouts from LAN peers are routine


class ControlServer:
    """Plain HTTP listener on ``port`` and, when ``tls`` is given, an HTTPS listener on ``tls_port``.

    With TLS on, the plain listener serves only ``_PLAIN_OK`` (``/hello`` to learn the pin) unless ``allow_plain``
    keeps the legacy full-API-over-HTTP behaviour. Without ``tls`` everything is plain, as in v1.0.
    """

    def __init__(self, service: ControlService, *, host: str = "0.0.0.0",
                 port: int = profile.DEFAULT_PORT, tls: tls_mod.TlsIdentity | None = None,
                 tls_port: int = DEFAULT_TLS_PORT, allow_plain: bool = False,
                 max_connections: int = MAX_CONNECTIONS, max_per_ip: int = MAX_CONNECTIONS_PER_IP) -> None:
        self.service = service
        limiter = _Limiter(max_connections, max_per_ip)
        restricted = tls is not None and not allow_plain
        plain_h = type("PlainHandler", (_Handler,), {"service": service, "plain_restricted": restricted})
        self._httpds: list[_BoundedHTTPServer] = [_BoundedHTTPServer((host, port), plain_h, limiter)]
        self._tls_httpd: _BoundedHTTPServer | None = None
        if tls is not None:
            tls_h = type("TlsHandler", (_Handler,), {"service": service, "secure": True})
            self._tls_httpd = _BoundedHTTPServer((host, tls_port), tls_h, limiter, tls_mod.server_context(tls))
            self._httpds.append(self._tls_httpd)
            service.tls_info = {"port": self.tls_port, "fingerprint_sha256": tls.fingerprint_sha256}
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    @property
    def tls_port(self) -> int | None:
        return int(self._tls_httpd.server_address[1]) if self._tls_httpd is not None else None

    @property
    def port(self) -> int:
        return int(self._httpds[0].server_address[1])

    def start(self) -> None:
        for httpd in self._httpds:
            t = threading.Thread(target=httpd.serve_forever, daemon=True,
                                 name="pigeon-control-api" + ("-tls" if httpd is self._tls_httpd else ""))
            t.start()
            self._threads.append(t)
        threading.Thread(target=self._poll_loop, daemon=True, name="pigeon-control-poll").start()

    def _poll_loop(self) -> None:
        last: str | None = None
        last_txt: dict[str, str] | None = None
        while not self._stop.wait(POLL_S):
            try:
                txt = self.service.txt_record()
                if last_txt is not None and txt != last_txt:
                    for fn in list(self.service.txt_listeners):
                        try:
                            fn(txt)
                        except Exception:
                            pass
                last_txt = txt
            except Exception:
                pass
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
        for httpd in self._httpds:
            httpd.shutdown()
            httpd.server_close()
