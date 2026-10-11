"""Accuracy report client — every Pigeon (pi4, pi5, Mac) pushes TMDb events to the Mac.

Two kinds of payload go to the report server (``pigeon_report_server.py`` on the Mac):

- **live** — what this Pigeon is looking at right now (metadata + the TMDb search in
  flight). Fire-and-forget; dropped when the server is unreachable.
- **event** — one row per finished TMDb fetch (query terms, assumed title, TT / backdrop /
  poster outcome, failure reason). Queued to ``accuracy_outbox.jsonl`` in the state dir
  when the server is unreachable and re-sent on the next successful post.
- **flag** — ⌘⇧X "this match is wrong"; the server marks this device's latest row.

Server URL, first match wins:

1. env ``PIGEON_REPORT_URL`` (``off`` disables reporting)
2. ``~/.pigeon_0_6/report_url`` (one line)
3. ``http://127.0.0.1:8765`` on macOS, else ``http://Jasons-MacBook-Air.local:8765``

Device name: env ``PIGEON_ID``, else ``pi5`` / ``pi4`` from the device-tree model, else
``Mac``.

Nothing here blocks the UI thread: payloads go on a queue drained by one daemon thread.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import urllib.request
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from pigeon.runtime_paths import pigeon_state_dir

DEFAULT_PORT = 8765
_DEFAULT_MAC_HOST = "Jasons-MacBook-Air.local"
_POST_TIMEOUT_S = 2.5
_OUTBOX_NAME = "accuracy_outbox.jsonl"
_OUTBOX_MAX_LINES = 2000
# After a failed post, skip the network for this long (outbox keeps events).
_BACKOFF_S = 20.0

# Metadata keys that feed the TMDb query (shown in the live view and logged raw).
_METADATA_KEYS = (
    "title",
    "series_name",
    "episode_title",
    "season_number",
    "episode_number",
    "media_type",
    "device_state",
    "prefer_pyatv_media",
    "app_name",
    "app_id",
    "total_time",
    "position",
    "artist",
    "album",
    "genre",
    "query",
    "prefer",
    "content_key",
    "content_identifier",
    "itunes_store_identifier",
    "hash",
)

_QUEUE: "queue.Queue[tuple[str, dict[str, Any]]]" = queue.Queue(maxsize=200)
_WORKER: threading.Thread | None = None
_WORKER_LOCK = threading.Lock()
_BACKOFF_UNTIL = [0.0]
_LAST_EVENT_ID: list[str | None] = [None]


def reporting_enabled() -> bool:
    return server_url() is not None


def server_url() -> str | None:
    raw = (os.environ.get("PIGEON_REPORT_URL") or "").strip()
    if not raw:
        try:
            raw = (pigeon_state_dir() / "report_url").read_text(encoding="utf-8").strip()
        except OSError:
            raw = ""
    if not raw:
        host = "127.0.0.1" if sys.platform == "darwin" else _DEFAULT_MAC_HOST
        raw = f"http://{host}:{DEFAULT_PORT}"
    if raw.casefold() in ("off", "0", "false", "no", "none"):
        return None
    if "://" not in raw:
        raw = "http://" + raw
    return raw.rstrip("/")


@lru_cache(maxsize=1)
def pigeon_id() -> str:
    env = (os.environ.get("PIGEON_ID") or "").strip()
    if env:
        return env
    try:
        model = Path("/proc/device-tree/model").read_bytes().decode("utf-8", "ignore")
    except OSError:
        model = ""
    if "Raspberry Pi 5" in model:
        return "pi5"
    if "Raspberry Pi 4" in model:
        return "pi4"
    if "Raspberry Pi" in model:
        return "pi"
    if sys.platform == "darwin":
        return "Mac"
    return (os.uname().nodename or "pigeon").split(".")[0]


def _version() -> str:
    try:
        from pigeon.version import version_string

        return version_string()
    except Exception:
        return ""


def _clean(v: Any) -> Any:
    """JSON-safe copy (numpy scalars, Paths, tuples → plain values)."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Mapping):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_clean(x) for x in v]
    item = getattr(v, "item", None)
    if callable(item):
        try:
            return _clean(item())
        except Exception:
            pass
    return str(v)


def metadata_snapshot(md: Mapping[str, Any] | None) -> dict[str, Any]:
    """The metadata fields Pigeon uses to build a TMDb query, plus rawTitle layers."""
    if not isinstance(md, Mapping):
        return {}
    out: dict[str, Any] = {}
    for k in _METADATA_KEYS:
        v = md.get(k)
        if v not in (None, ""):
            out[k] = _clean(v)
    try:
        from pigeon.raw_title import raw_title_from_metadata_dict

        rt = raw_title_from_metadata_dict(md)
        for f in (
            "raw_title",
            "raw_series_name",
            "raw_episode_title",
            "raw_query",
            "season_index",
            "episode_index",
            "layer_series_title",
            "layer_series_number",
            "layer_episode_number",
            "layer_episode_title",
            "media_type_label",
        ):
            v = getattr(rt, f, None)
            if v not in (None, ""):
                out[f] = _clean(v)
    except Exception:
        pass
    try:
        from pigeon.raw_title import tmdb_query_candidates_from_metadata

        out["query_candidates"] = list(tmdb_query_candidates_from_metadata(md))
    except Exception:
        pass
    try:
        from pigeon.title_decision import decision_from_metadata

        why = decision_from_metadata(md)
        if why:
            out["title_decision"] = str(why)
    except Exception:
        pass
    return out


def tt_whitened(title_key: str | None) -> bool | None:
    """Would the on-screen TT be recolored white (``whiten_dark_tt_bgra``)? None = no logo."""
    if not title_key:
        return None
    try:
        import cv2

        from pigeon.media_cache import ASSET_LOGO_EN, find_cached_reformatted_asset
        from pigeon.tmdb_tt_contrast import whiten_dark_tt_bgra

        p = find_cached_reformatted_asset(title_key, ASSET_LOGO_EN)
        if p is None:
            return None
        arr = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if arr is None:
            return None
        if arr.ndim == 3 and arr.shape[2] == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGR2BGRA)
        return whiten_dark_tt_bgra(arr) is not arr
    except Exception:
        return None


def report_live(
    *,
    state: str,
    metadata: Mapping[str, Any] | None,
    streaming_service: str = "",
    query: str = "",
    refined_query: str = "",
    prefer: str = "",
) -> None:
    """Now-playing snapshot for the live view (``state``: searching / idle / skipped)."""
    _enqueue(
        "live",
        {
            "state": state,
            "streaming_service": streaming_service,
            "query": query,
            "refined_query": refined_query,
            "prefer": prefer,
            "metadata": metadata_snapshot(metadata),
        },
    )


def report_fetch_event(
    *,
    metadata: Mapping[str, Any] | None,
    streaming_service: str,
    query_in: str,
    refined_query: str,
    used_query: str,
    prefer: str,
    trigger: str,
    ok: bool,
    message: str,
    match_tier: int,
    tier_ok: bool,
    attempts: list[dict[str, Any]] | None,
    tt_source: str,
    backdrop_source: str,
    started_mono: float | None = None,
) -> None:
    """One finished TMDb fetch → one spreadsheet row on the Mac."""
    attempts = [dict(a) for a in (attempts or []) if isinstance(a, Mapping)]
    # The attempt that produced the result (last with that query), else the last one.
    win: dict[str, Any] = {}
    for a in attempts:
        if a.get("query") == used_query:
            win = a
    if not win and attempts:
        win = attempts[-1]
    title_key = str(win.get("title_key") or "") if ok else ""
    if tt_source == "tmdb_logo" and win.get("logo_source") == "cache":
        tt_source = "tmdb_logo_cached"
    failure = ""
    if not ok:
        failure = (
            message
            if message.startswith("Loose match rejected")
            else str(win.get("failure") or "").strip() or message.split("\n", 1)[0]
        )
    elif not tier_ok:
        failure = (
            f"match tier {match_tier} below threshold — query "
            f"{used_query!r} is a loose match for {win.get('display_title')!r}"
        )
    else:
        missing = [
            n
            for n, flag in (
                ("TT", win.get("logo_ok")),
                ("backdrop", win.get("backdrop_ok")),
                ("poster", win.get("poster_ok")),
            )
            if not flag
        ]
        if missing:
            failure = "TMDb has no " + " / ".join(missing)
    payload = {
        "id": uuid.uuid4().hex[:12],
        "streaming_service": streaming_service,
        "trigger": trigger,
        "outcome": (
            str(win.get("outcome") or "match")
            if ok
            else "loose_match_rejected"
            if message.startswith("Loose match rejected")
            else str(win.get("outcome") or "no_match")
        ),
        "ok": bool(ok),
        "query_in": query_in,
        "refined_query": refined_query,
        "used_query": used_query,
        "queries_tried": [str(a.get("query") or "") for a in attempts],
        "prefer": prefer,
        "assumed_title": str(win.get("display_title") or "") if ok else "",
        "tmdb_kind": str(win.get("kind") or "") if ok else "",
        "tmdb_id": win.get("tmdb_id") if ok else None,
        "tmdb_year": str(win.get("tmdb_year") or "") if ok else "",
        "match_tier": int(match_tier),
        "tier_ok": bool(tier_ok),
        "tt": tt_source in ("tmdb_logo", "tmdb_logo_cached"),
        "tt_source": tt_source,
        "tt_path": win.get("logo_path") if ok else None,
        "backdrop": backdrop_source == "tmdb",
        "backdrop_source": backdrop_source,
        "backdrop_path": win.get("backdrop_path") if ok else None,
        "poster": bool(ok and win.get("poster_ok")),
        "poster_path": win.get("poster_path") if ok else None,
        "trt_player_s": win.get("trt_player_s"),
        "trt_tmdb_s": win.get("trt_tmdb_s") if ok else None,
        "trt_similarity": win.get("trt_similarity") if ok else None,
        "service_hint": win.get("service_hint"),
        "failure": failure,
        "message": message,
        "fetch_ms": (
            int((time.monotonic() - started_mono) * 1000) if started_mono else None
        ),
        "metadata": metadata_snapshot(metadata),
        "attempts": attempts,
        "_title_key": title_key,
    }
    _LAST_EVENT_ID[0] = payload["id"]
    _enqueue("event", payload)


def report_flag(*, display_title: str | None) -> None:
    """⌘⇧X: the user says the current artwork is wrong."""
    _enqueue(
        "flag",
        {"event_id": _LAST_EVENT_ID[0], "display_title": display_title or ""},
    )


# --- transport --------------------------------------------------------------


def _enqueue(kind: str, payload: dict[str, Any]) -> None:
    if not reporting_enabled():
        return
    payload = dict(payload)
    payload["pigeon_id"] = pigeon_id()
    payload["pigeon_version"] = _version()
    payload["t"] = time.time()
    try:
        _QUEUE.put_nowait((kind, payload))
    except queue.Full:
        return
    _ensure_worker()


def _ensure_worker() -> None:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            return
        _WORKER = threading.Thread(
            target=_worker_loop, name="pigeon-accuracy-report", daemon=True
        )
        _WORKER.start()


def _outbox_path() -> Path:
    return pigeon_state_dir() / _OUTBOX_NAME


def _post(kind: str, payload: dict[str, Any]) -> bool:
    url = server_url()
    if url is None:
        return True
    if time.monotonic() < _BACKOFF_UNTIL[0]:
        return False
    body = json.dumps({"kind": kind, "payload": payload}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"{url}/api/push",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_POST_TIMEOUT_S) as resp:
            ok = 200 <= int(resp.status) < 300
    except Exception:
        ok = False
    if not ok:
        _BACKOFF_UNTIL[0] = time.monotonic() + _BACKOFF_S
    return ok


def _append_outbox(kind: str, payload: dict[str, Any]) -> None:
    p = _outbox_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, "payload": payload}, ensure_ascii=False) + "\n")
        lines = p.read_text(encoding="utf-8").splitlines()
        if len(lines) > _OUTBOX_MAX_LINES:
            p.write_text("\n".join(lines[-_OUTBOX_MAX_LINES:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def _flush_outbox() -> None:
    p = _outbox_path()
    if not p.is_file():
        return
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    left: list[str] = []
    for i, line in enumerate(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not _post(str(rec.get("kind") or "event"), dict(rec.get("payload") or {})):
            left = lines[i:]
            break
    try:
        if left:
            p.write_text("\n".join(left) + "\n", encoding="utf-8")
        else:
            p.unlink()
    except OSError:
        pass


def _finish_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Slow bits (disk read of the cached logo) happen here, off the UI thread."""
    tk = payload.pop("_title_key", "")
    if payload.get("tt"):
        payload["tt_whitened"] = tt_whitened(tk)
    return payload


def _worker_loop() -> None:
    _flush_outbox()
    while True:
        kind, payload = _QUEUE.get()
        if kind == "event":
            payload = _finish_event(payload)
        if _post(kind, payload):
            if kind != "live":
                _flush_outbox()
        elif kind != "live":
            _append_outbox(kind, payload)
