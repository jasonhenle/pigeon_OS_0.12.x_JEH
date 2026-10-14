"""Manual title search (settings_main SEARCH button).

The user can pin a title by hand when Pigeon cannot detect content. The title
persists until cleared and feeds two places:

* now playing — shown only while nothing is auto-detected;
* the clocksaver — clock shrinks left, TMDb poster sits right, except while
  auto detection is reporting a *different* title (metadata wins; the poster
  returns the moment detection ends — no timed hold).

This module owns persistence, TMDb title suggestions (debounced, off-thread),
the poster raster, and the conflict clock. It has no UI imports.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
from typing import Callable

import numpy as np

SUGGEST_ROWS = 3
_SUGGEST_FETCH = 6
_DEBOUNCE_S = 0.28
_POSTER_SIZE = "w500"
_FILE = "manual_search.json"

_LOCK = threading.RLock()
_entry: dict | None = None
_loaded = False

_suggest_query = ""
_suggest_results: tuple[dict, ...] = ()
_suggest_version = 0
_suggest_pending: str | None = None
_suggest_thread_live = False

_poster_bgr: np.ndarray | None = None
_poster_key = ""
_poster_inflight = False

_conflict_active = False
_auto_active = False
# True while the manual title is what now playing shows (nothing auto-detected
# since it was spawned). ``_manual_query`` is the exact string we fed the
# pipeline so its own spawn is not mistaken for a detection.
_shown = False
_manual_query = ""

# Hooks installed by boot (spawn_tmdb_poster_fetch / redraw / landing reset).
_spawn_hook: Callable[..., object] | None = None
_refresh_hook: Callable[[], object] | None = None
_clear_display_hook: Callable[[], object] | None = None


# --------------------------------------------------------------------------- state

def _path():
    from pigeon.runtime_paths import pigeon_state_dir

    return pigeon_state_dir() / _FILE


def _clean(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    title = " ".join(str(raw.get("title") or "").split())
    if not title:
        return None
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in ("movie", "tv"):
        kind = ""
    try:
        tmdb_id = int(raw.get("tmdb_id") or 0)
    except (TypeError, ValueError):
        tmdb_id = 0
    return {
        "title": title,
        "year": str(raw.get("year") or "").strip()[:4],
        "kind": kind,
        "tmdb_id": tmdb_id,
        "poster_path": str(raw.get("poster_path") or "").strip(),
    }


def _ensure_loaded() -> None:
    global _entry, _loaded
    if _loaded:
        return
    with _LOCK:
        if _loaded:
            return
        try:
            _entry = _clean(json.loads(_path().read_text(encoding="utf-8")))
        except Exception:
            _entry = None
        _loaded = True


def _save() -> None:
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        if _entry is None:
            p.unlink(missing_ok=True)
            return
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(_entry), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        pass


def current() -> dict | None:
    """The persisted manual title entry, or ``None``."""
    _ensure_loaded()
    with _LOCK:
        return dict(_entry) if _entry else None


def current_title() -> str:
    e = current()
    return str(e["title"]) if e else ""


def set_entry(raw: dict) -> dict | None:
    """Persist a manual title (suggestion pick or free text)."""
    global _entry, _poster_bgr, _poster_key, _conflict_active
    cleaned = _clean(raw)
    if cleaned is None:
        return None
    _ensure_loaded()
    with _LOCK:
        _entry = cleaned
        _poster_bgr = None
        _poster_key = ""
        _conflict_active = False
        _save()
    return dict(cleaned)


def clear() -> None:
    """Forget the manual title and drop it from now playing if it is showing."""
    global _entry, _poster_bgr, _poster_key, _shown, _manual_query, _conflict_active
    _ensure_loaded()
    with _LOCK:
        was_shown = _shown
        _entry = None
        _poster_bgr = None
        _poster_key = ""
        _shown = False
        _manual_query = ""
        _conflict_active = False
        _save()
    cb = _clear_display_hook
    if was_shown and cb is not None:
        try:
            cb()
        except Exception:
            pass


# --------------------------------------------------------------------- title match

def _norm(s: str) -> str:
    try:
        from pigeon.tmdb_poster import _norm_query

        return _norm_query(s)
    except Exception:
        return " ".join("".join(c if c.isalnum() else " " for c in (s or "").lower()).split())


def titles_match(detected: str, manual: str) -> bool:
    a, b = _norm(detected), _norm(manual)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    # "The Office" vs "The Office (US)" / "The Office S02E03 ..." style containment.
    return len(short) >= 4 and f" {short} " in f" {long_} "


# ----------------------------------------------------------------- conflict clock

def note_detected_query(query: str, *, now: float | None = None) -> None:
    """Auto-detection reported ``query``; it wins while it differs from the manual title."""
    global _conflict_active, _auto_active, _shown
    del now  # kept for call-site compat
    q = str(query or "").strip()
    if not q or (_manual_query and q == _manual_query):
        return
    _auto_active = True
    _shown = False
    manual = current_title()
    _conflict_active = bool(manual) and not titles_match(q, manual)


def poster_allowed(now: float | None = None) -> bool:
    """False only while a mismatching auto-detected title is being reported."""
    del now
    return not _conflict_active


def auto_detected_active() -> bool:
    return bool(_auto_active)


# ---------------------------------------------------------------- hooks / display

def install_hooks(
    *,
    spawn: Callable[..., object] | None = None,
    refresh: Callable[[], object] | None = None,
    clear_display: Callable[[], object] | None = None,
) -> None:
    global _spawn_hook, _refresh_hook, _clear_display_hook
    if spawn is not None:
        _spawn_hook = spawn
    if refresh is not None:
        _refresh_hook = refresh
    if clear_display is not None:
        _clear_display_hook = clear_display


def is_displaying() -> bool:
    """True while now playing is showing the manual title (idle polls must not wipe it)."""
    return bool(_shown)


def show_in_now_playing() -> bool:
    """Feed the manual title through the normal TMDb now-playing pipeline."""
    global _shown, _manual_query
    entry = current()
    if not entry or _spawn_hook is None or _auto_active:
        return False
    query = entry["title"]
    if entry.get("year"):
        query = f"{query} ({entry['year']})"
    _manual_query = query
    _shown = True
    try:
        _spawn_hook(query, prefer=entry.get("kind") or "auto", force=True)
    except Exception:
        _shown = False
        return False
    return True


def on_content_idle() -> None:
    """Auto-detected content ended — fall back to the manual title."""
    global _auto_active, _conflict_active
    _auto_active = False
    _conflict_active = False
    if not _shown:
        show_in_now_playing()


# ------------------------------------------------------------------ suggestions

def _search_multi(query: str) -> list[dict]:
    from pigeon.tmdb_poster import (
        TMDB_API_BASE,
        TMDB_UI_LANGUAGE,
        _request_json,
        tmdb_is_configured,
    )

    if not tmdb_is_configured():
        return []
    params = {
        "query": query,
        "language": TMDB_UI_LANGUAGE,
        "include_adult": "false",
    }
    data = _request_json(f"{TMDB_API_BASE}/search/multi?{urllib.parse.urlencode(params)}")
    rows = data.get("results") if isinstance(data, dict) else None
    out: list[dict] = []
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("media_type") or "")
        if kind not in ("movie", "tv"):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        if not title:
            continue
        date = str(item.get("release_date") or item.get("first_air_date") or "")
        try:
            tmdb_id = int(item.get("id") or 0)
        except (TypeError, ValueError):
            tmdb_id = 0
        out.append(
            {
                "title": title,
                "year": date[:4],
                "kind": kind,
                "tmdb_id": tmdb_id,
                "poster_path": str(item.get("poster_path") or ""),
                "_pop": float(item.get("popularity") or 0.0),
            }
        )
        if len(out) >= _SUGGEST_FETCH:
            break
    return out


def suggest_now(query: str, limit: int = SUGGEST_ROWS) -> tuple[dict, ...]:
    """Blocking search (worker threads / tests). Title-prefix matches first."""
    q = " ".join(str(query or "").split())
    if len(q) < 2:
        return ()
    try:
        rows = _search_multi(q)
    except Exception:
        return ()
    nq = _norm(q)
    rows.sort(
        key=lambda r: (
            0 if _norm(r["title"]).startswith(nq) else 1,
            -float(r.get("_pop") or 0.0),
        )
    )
    return tuple({k: v for k, v in r.items() if k != "_pop"} for r in rows[:max(1, int(limit))])


def request_suggestions(query: str) -> None:
    """Debounced async lookup; read ``suggestions()`` / ``suggestion_version()``."""
    global _suggest_pending, _suggest_thread_live, _suggest_results, _suggest_query
    global _suggest_version
    q = " ".join(str(query or "").split())
    with _LOCK:
        if q == _suggest_query and not _suggest_pending:
            return
        if len(q) < 2:
            _suggest_query = q
            _suggest_pending = None
            if _suggest_results:
                _suggest_results = ()
                _suggest_version += 1
            return
        _suggest_pending = q
        if _suggest_thread_live:
            return
        _suggest_thread_live = True
    threading.Thread(target=_suggest_worker, daemon=True).start()


def _suggest_worker() -> None:
    global _suggest_pending, _suggest_thread_live, _suggest_results, _suggest_query
    global _suggest_version
    while True:
        time.sleep(_DEBOUNCE_S)
        with _LOCK:
            q = _suggest_pending
            _suggest_pending = None
            if q is None:
                _suggest_thread_live = False
                return
        results = suggest_now(q)
        with _LOCK:
            if _suggest_pending is not None:
                continue  # superseded while fetching
            _suggest_query = q
            _suggest_results = results
            _suggest_version += 1
        _poke()


def suggestions() -> tuple[dict, ...]:
    with _LOCK:
        return _suggest_results


def suggestion_version() -> int:
    return _suggest_version


def reset_suggestions() -> None:
    global _suggest_query, _suggest_results, _suggest_pending, _suggest_version
    with _LOCK:
        _suggest_query = ""
        _suggest_pending = None
        if _suggest_results:
            _suggest_results = ()
            _suggest_version += 1


def _poke() -> None:
    cb = _refresh_hook
    if cb is not None:
        try:
            cb()
        except Exception:
            pass


# ----------------------------------------------------------------------- poster

def _poster_cache_dir():
    from pigeon.runtime_paths import pigeon_state_dir

    return pigeon_state_dir() / "manual_search_posters"


def _fetch_poster(entry: dict) -> np.ndarray | None:
    import cv2

    from pigeon.tmdb_poster import _http_get_bytes, _UA

    path = str(entry.get("poster_path") or "")
    if not path:
        rows = _search_multi(str(entry.get("title") or ""))
        want = str(entry.get("year") or "")
        pick = next(
            (r for r in rows if r["poster_path"] and (not want or r["year"] == want)),
            next((r for r in rows if r["poster_path"]), None),
        )
        if pick is None:
            return None
        path = str(pick["poster_path"])
        with _LOCK:
            if _entry is not None and _entry.get("title") == entry.get("title"):
                _entry["poster_path"] = path
                _save()
    name = path.lstrip("/")
    cache = _poster_cache_dir() / name
    raw: bytes | None = None
    try:
        raw = cache.read_bytes()
    except Exception:
        raw = None
    if not raw:
        raw = _http_get_bytes(
            f"https://image.tmdb.org/t/p/{_POSTER_SIZE}/{name}",
            timeout_s=30.0,
            headers={"User-Agent": _UA},
        )
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(raw)
        except Exception:
            pass
    img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    return img if img is not None and img.size else None


def poster_bgr() -> np.ndarray | None:
    """Poster for the manual title if already loaded; otherwise start the fetch."""
    global _poster_inflight
    entry = current()
    if not entry:
        return None
    key = f"{entry['title']}|{entry['year']}|{entry['tmdb_id']}"
    with _LOCK:
        if _poster_bgr is not None and _poster_key == key:
            return _poster_bgr
        if _poster_inflight:
            return None
        _poster_inflight = True

    def work() -> None:
        global _poster_bgr, _poster_key, _poster_inflight
        img = None
        try:
            img = _fetch_poster(entry)
        except Exception:
            img = None
        with _LOCK:
            _poster_inflight = False
            if img is not None:
                _poster_bgr = img
                _poster_key = key
        if img is not None:
            _poke()

    threading.Thread(target=work, daemon=True).start()
    return None


__all__ = [
    "SUGGEST_ROWS",
    "auto_detected_active",
    "clear",
    "current",
    "current_title",
    "install_hooks",
    "is_displaying",
    "note_detected_query",
    "on_content_idle",
    "poster_allowed",
    "poster_bgr",
    "request_suggestions",
    "reset_suggestions",
    "set_entry",
    "show_in_now_playing",
    "suggest_now",
    "suggestion_version",
    "suggestions",
    "titles_match",
]
