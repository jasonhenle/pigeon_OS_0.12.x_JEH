#!/usr/bin/env python3
"""Pigeon accuracy report server — runs on the Mac, collects events from every Pigeon.

    .venv/bin/python pigeon_report_server.py            # http://localhost:8765
    .venv/bin/python pigeon_report_server.py --port 9000 --no-browser

Pigeons (pi4, pi5, this Mac) POST to ``/api/push`` via ``pigeon/accuracy_report.py``.
The browser UI has three tabs:

- **Live** — per-device now-playing metadata, the TMDb query, and TT / backdrop / poster
  thumbnails for the current title.
- **Gallery** — every title pulled, with its three TMDb thumbnails side by side.
- **Log** — the spreadsheet; the Notes column and "wrong match" checkbox are editable.

Files (``PIGEON_REPORT_ROOT``, default ``~/Pigeon/pigeonReport``):

- ``accuracy/events.jsonl`` — raw events, including every TMDb attempt (append-only)
- ``accuracy/annotations.json`` — your notes / wrong-match flags, keyed by event id
- ``pigeon_accuracy.csv`` — the spreadsheet, rewritten on every change
- ``pigeon_accuracy.numbers`` — written by the Export .numbers button
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
UI_HTML = HERE / "pigeon" / "accuracy_report_ui.html"
DEFAULT_PORT = 8765
_MAX_BODY = 2_000_000


def report_root() -> Path:
    raw = (os.environ.get("PIGEON_REPORT_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / "Pigeon" / "pigeonReport"


def _fmt_s(v: Any) -> str:
    try:
        s = int(round(float(v)))
    except (TypeError, ValueError):
        return ""
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _md(r: dict[str, Any], *keys: str) -> Any:
    md = r.get("metadata") or {}
    for k in keys:
        if md.get(k) not in (None, ""):
            return md[k]
    return ""


def _yn(v: Any) -> Any:
    return "" if v is None else bool(v)


# (header, row → value). Booleans stay bool so Numbers renders checkboxes.
COLUMNS: tuple[tuple[str, Any], ...] = (
    ("Pigeon ID", lambda r: r.get("pigeon_id", "")),
    ("Pigeon version", lambda r: r.get("pigeon_version", "")),
    ("Date", lambda r: time.strftime("%Y-%m-%d", time.localtime(r.get("t") or 0))),
    ("Time", lambda r: time.strftime("%H:%M:%S", time.localtime(r.get("t") or 0))),
    ("Streaming service", lambda r: r.get("streaming_service", "")),
    ("Query terms", lambda r: " → ".join(q for q in r.get("queries_tried") or [] if q)
        or r.get("refined_query", "")),
    ("Apple TV query", lambda r: r.get("query_in", "")),
    ("Assumed title", lambda r: r.get("assumed_title", "")),
    ("tmdb_tt", lambda r: bool(r.get("tt"))),
    ("TT converted to white", lambda r: _yn(r.get("tt_whitened"))),
    ("tmdb_backdrop", lambda r: bool(r.get("backdrop"))),
    ("tmdb_poster", lambda r: bool(r.get("poster"))),
    ("Failures", lambda r: r.get("failure", "")),
    ("Wrong match (flagged)", lambda r: bool(r.get("flagged_wrong"))),
    ("Outcome", lambda r: r.get("outcome", "")),
    ("TT shown as", lambda r: r.get("tt_source", "")),
    ("Backdrop shown as", lambda r: r.get("backdrop_source", "")),
    ("TMDb type", lambda r: r.get("tmdb_kind", "")),
    ("TMDb ID", lambda r: r.get("tmdb_id") or ""),
    ("TMDb year", lambda r: r.get("tmdb_year", "")),
    ("Match tier", lambda r: r.get("match_tier", "")),
    ("Tier OK", lambda r: _yn(r.get("tier_ok"))),
    ("Player TRT", lambda r: _fmt_s(r.get("trt_player_s"))),
    ("TMDb TRT", lambda r: _fmt_s(r.get("trt_tmdb_s"))),
    ("TRT similarity", lambda r: "" if r.get("trt_similarity") is None
        else round(float(r["trt_similarity"]), 3)),
    ("Prefer", lambda r: r.get("prefer", "")),
    ("Trigger", lambda r: r.get("trigger", "")),
    ("Fetch ms", lambda r: r.get("fetch_ms") or ""),
    ("raw_title", lambda r: (r.get("metadata") or {}).get("raw_title", "")),
    ("raw_series_name", lambda r: (r.get("metadata") or {}).get("raw_series_name", "")),
    ("raw_episode_title", lambda r: (r.get("metadata") or {}).get("raw_episode_title", "")),
    ("Season", lambda r: _md(r, "season_index", "season_number")),
    ("Episode", lambda r: _md(r, "episode_index", "episode_number")),
    ("Media type", lambda r: (r.get("metadata") or {}).get("media_type", "")),
    ("App ID", lambda r: (r.get("metadata") or {}).get("app_id", "")),
    ("Title decision", lambda r: (r.get("metadata") or {}).get("title_decision", "")),
    ("Event ID", lambda r: r.get("id", "")),
    ("Notes", lambda r: r.get("notes", "")),
)


class Store:
    """Events + annotations on disk, live snapshots in memory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.dir = root / "accuracy"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "events.jsonl"
        self.ann_path = self.dir / "annotations.json"
        self.csv_path = root / "pigeon_accuracy.csv"
        self.numbers_path = root / "pigeon_accuracy.numbers"
        self.lock = threading.RLock()
        self.events: list[dict[str, Any]] = []
        self.ids: set[str] = set()
        self.ann: dict[str, dict[str, Any]] = {}
        self.live: dict[str, dict[str, Any]] = {}
        self.seq = 0  # bumps on any change; the UI polls with ?since=
        self._csv_timer: threading.Timer | None = None
        self._load()

    def _load(self) -> None:
        if self.ann_path.is_file():
            try:
                self.ann = json.loads(self.ann_path.read_text(encoding="utf-8"))
            except ValueError:
                self.ann = {}
        if self.events_path.is_file():
            for line in self.events_path.read_text(encoding="utf-8").splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("id") and ev["id"] not in self.ids:
                    self.ids.add(ev["id"])
                    self.events.append(ev)
        self.events.sort(key=lambda e: e.get("t") or 0)
        for ev in self.events:
            dev = str(ev.get("pigeon_id") or "?")
            self.live.setdefault(dev, {"pigeon_id": dev, "last_seen": ev.get("t")})
            self.live[dev]["last_event_id"] = ev["id"]
        self.seq = 1
        self.write_csv()

    # --- mutation ---------------------------------------------------------

    def push(self, kind: str, p: dict[str, Any]) -> None:
        dev = str(p.get("pigeon_id") or "?")
        with self.lock:
            dev_state = self.live.setdefault(dev, {"pigeon_id": dev})
            dev_state["last_seen"] = time.time()
            dev_state["pigeon_version"] = p.get("pigeon_version", "")
            if kind == "live":
                dev_state["live"] = p
            elif kind == "event":
                eid = str(p.get("id") or "")
                if not eid or eid in self.ids:
                    return
                self.ids.add(eid)
                self.events.append(p)
                self.events.sort(key=lambda e: e.get("t") or 0)
                with self.events_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(p, ensure_ascii=False) + "\n")
                if (p.get("t") or 0) >= (self._event(dev_state.get("last_event_id")) or {}).get("t", 0):
                    dev_state["last_event_id"] = eid
                    live = dev_state.get("live")
                    if isinstance(live, dict) and live.get("state") == "searching":
                        live["state"] = "done"
            elif kind == "flag":
                eid = str(p.get("event_id") or "") or dev_state.get("last_event_id")
                if eid:
                    self.annotate(eid, flagged_wrong=True, flag_source="pigeon ⌘⇧X")
                    return
            self.seq += 1
        if kind == "event":
            self.schedule_csv()

    def annotate(self, eid: str, **fields: Any) -> bool:
        with self.lock:
            if eid not in self.ids:
                return False
            a = self.ann.setdefault(eid, {})
            a.update(fields)
            tmp = self.ann_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.ann, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.ann_path)
            self.seq += 1
        self.schedule_csv()
        return True

    # --- views ------------------------------------------------------------

    def _event(self, eid: Any) -> dict[str, Any] | None:
        if not eid:
            return None
        for ev in reversed(self.events):
            if ev.get("id") == eid:
                return ev
        return None

    def rows(self) -> list[dict[str, Any]]:
        with self.lock:
            return [{**ev, **self.ann.get(ev["id"], {})} for ev in self.events]

    def state(self) -> dict[str, Any]:
        with self.lock:
            devices = []
            for dev, st in sorted(self.live.items()):
                ev = self._event(st.get("last_event_id"))
                devices.append(
                    {
                        **{k: v for k, v in st.items() if k != "last_event_id"},
                        "last_event": {**ev, **self.ann.get(ev["id"], {})} if ev else None,
                    }
                )
            return {
                "seq": self.seq,
                "now": time.time(),
                "devices": devices,
                "rows": self.rows(),
                "csv_path": str(self.csv_path),
                "numbers_path": str(self.numbers_path),
            }

    # --- files ------------------------------------------------------------

    def table(self) -> list[list[Any]]:
        out: list[list[Any]] = [[h for h, _ in COLUMNS]]
        for r in self.rows():
            out.append([fn(r) for _, fn in COLUMNS])
        return out

    def csv_text(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        for row in self.table():
            w.writerow(["TRUE" if v is True else "FALSE" if v is False else v for v in row])
        return buf.getvalue()

    def schedule_csv(self) -> None:
        with self.lock:
            if self._csv_timer is not None:
                self._csv_timer.cancel()
            self._csv_timer = threading.Timer(1.0, self.write_csv)
            self._csv_timer.daemon = True
            self._csv_timer.start()

    def write_csv(self) -> None:
        try:
            tmp = self.csv_path.with_suffix(".csv.tmp")
            tmp.write_text(self.csv_text(), encoding="utf-8")
            tmp.replace(self.csv_path)
        except OSError as e:
            sys.stderr.write(f"report: csv write failed: {e}\n")

    def write_numbers(self) -> str:
        from numbers_parser import Document

        table = self.table()
        doc = Document(num_rows=len(table), num_cols=len(COLUMNS))
        sheet = doc.sheets[0]
        sheet.name = "Pigeon accuracy"
        t = sheet.tables[0]
        t.name = "Events"
        for r, row in enumerate(table):
            for c, v in enumerate(row):
                if v == "" or v is None:
                    continue
                t.write(r, c, v)
        doc.save(str(self.numbers_path))
        return str(self.numbers_path)


def make_handler(store: Store) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "PigeonReport/1"

        def log_message(self, fmt: str, *args: Any) -> None:
            if "/api/state" not in (args[0] if args else ""):
                sys.stderr.write("report: " + fmt % args + "\n")

        def _send(self, code: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

        def _body(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > _MAX_BODY:
                return {}
            try:
                obj = json.loads(self.rfile.read(n))
            except ValueError:
                return {}
            return obj if isinstance(obj, dict) else {}

        def do_GET(self) -> None:
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                self._send(200, UI_HTML.read_bytes(), "text/html; charset=utf-8")
            elif u.path == "/api/state":
                since = parse_qs(u.query).get("since", ["0"])[0]
                if since.isdigit() and int(since) == store.seq:
                    self._json({"seq": store.seq, "unchanged": True, "now": time.time()})
                else:
                    self._json(store.state())
            elif u.path == "/pigeon_accuracy.csv":
                self._send(
                    200,
                    store.csv_text().encode("utf-8"),
                    "text/csv; charset=utf-8",
                    {"Content-Disposition": 'attachment; filename="pigeon_accuracy.csv"'},
                )
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            u = urlparse(self.path)
            body = self._body()
            if u.path == "/api/push":
                kind = str(body.get("kind") or "")
                payload = body.get("payload")
                if kind not in ("live", "event", "flag") or not isinstance(payload, dict):
                    self._json({"ok": False}, HTTPStatus.BAD_REQUEST)
                    return
                store.push(kind, payload)
                self._json({"ok": True})
            elif u.path == "/api/annotate":
                eid = str(body.get("id") or "")
                fields = {
                    k: body[k] for k in ("notes", "flagged_wrong") if k in body
                }
                if "flagged_wrong" in fields:
                    fields["flagged_wrong"] = bool(fields["flagged_wrong"])
                    fields["flag_source"] = "report" if fields["flagged_wrong"] else ""
                if "notes" in fields:
                    fields["notes"] = str(fields["notes"])[:4000]
                self._json({"ok": store.annotate(eid, **fields)})
            elif u.path == "/api/export_numbers":
                try:
                    self._json({"ok": True, "path": store.write_numbers()})
                except Exception as e:
                    self._json({"ok": False, "error": str(e)}, 500)
            else:
                self._send(404, b"not found", "text/plain")

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 so the Pis can reach it")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    store = Store(report_root())
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    url = f"http://localhost:{args.port}/"
    print(f"Pigeon report: {url}  (data in {store.root})", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        store.write_csv()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
