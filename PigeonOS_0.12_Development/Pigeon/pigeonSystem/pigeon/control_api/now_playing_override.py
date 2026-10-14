"""User corrections for what Pigeon searches TMDb for (companion app).

A correction is **remembered**: it is stored on disk against the title keys the
content was detected under, so the same wrongly-detected title is fixed every
time it plays (and after a restart). It applies whenever the detected metadata
shares a title key with a stored correction, and never to different content.
``DELETE`` (Reset) forgets it.

Two kinds of correction:

* **edited fields** — the metadata that feeds the query (title, series, episode,
  Apple TV search text, year, movie/tv) is replaced, then the normal query
  resolution runs on the edited copy;
* **pick** — a specific TMDb movie/TV id chosen from candidates, forced through
  :func:`pigeon.tmdb_poster.set_forced_pick`.

``apply_override`` is called from ``spawn_tmdb_poster_fetch`` and is the only
place the pipeline sees an override.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

# (key, label, editable)
INPUT_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("title", "Title", True),
    ("series_name", "Series", True),
    ("episode_title", "Episode title", True),
    ("query", "Apple TV search text", True),
    ("season_number", "Season", False),
    ("episode_number", "Episode", False),
    ("media_type", "Media type", False),
    ("app_name", "App", False),
    ("artist", "Artist", False),
    ("album", "Album", False),
)
EDITABLE = frozenset(k for k, _l, ed in INPUT_FIELDS if ed)
_YEAR_RE = re.compile(r"\((19|20)\d{2}\)\s*$")
_KINDS = ("auto", "movie", "tv")


@dataclass
class Override:
    keys: list[str]
    query: str
    prefer: str = "auto"
    fields: dict[str, str] = field(default_factory=dict)
    year: str = ""
    pick: dict[str, Any] | None = None
    created: float = field(default_factory=time.time)

    def summary(self) -> dict[str, Any]:
        return {
            "active": True,
            "query": self.query,
            "prefer": self.prefer,
            "fields": dict(self.fields),
            "year": self.year or None,
            "pick": dict(self.pick) if self.pick else None,
        }


_LOCK = threading.RLock()
_CURRENT: Override | None = None


_FILE = "now_playing_corrections.json"
_MAX_STORED = 200


def _norm(s: Any) -> str:
    try:
        from pigeon.tmdb_poster import _norm_query

        return _norm_query(str(s or ""))
    except Exception:
        return " ".join(str(s or "").casefold().split())


def content_keys(md: Mapping[str, Any] | None) -> list[str]:
    """Normalized title strings this content is known by (any shared key = same content).

    Mirrors how the pipeline decides two polls are the same title: Apple TV may
    alternate the show name and the episode title, so every candidate counts.
    """
    md = md or {}
    raw: list[str] = [str(md.get(k) or "") for k in ("title", "series_name", "episode_title", "query")]
    try:
        from pigeon.raw_title import tmdb_query_candidates_from_metadata

        raw += list(tmdb_query_candidates_from_metadata(md))
    except Exception:
        pass
    out: list[str] = []
    for r in raw:
        n = _norm(r)
        if len(n) >= 3 and n not in out:
            out.append(n)
    return out


def _same_content(a: list[str], b: list[str]) -> bool:
    return bool(set(a) & set(b))


def _store_path():
    from pigeon.runtime_paths import pigeon_state_dir

    return pigeon_state_dir() / _FILE


def _load_store() -> list[dict[str, Any]]:
    try:
        raw = json.loads(_store_path().read_text(encoding="utf-8"))
        rows = raw.get("corrections") if isinstance(raw, dict) else None
        return [r for r in rows if isinstance(r, dict) and r.get("keys")] if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def _save_store(rows: list[dict[str, Any]]) -> None:
    try:
        p = _store_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"corrections": rows[-_MAX_STORED:]}), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def _log(msg: str) -> None:
    try:
        from pigeon.pi_diagnostics import append_pigeon_log

        append_pigeon_log(f"correction: {msg}")
    except Exception:
        pass


def input_rows(md: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The metadata that contributed to the query, in display order."""
    md = md or {}
    rows = []
    for key, label, editable in INPUT_FIELDS:
        val = md.get(key)
        if val in (None, ""):
            if not editable:
                continue
            val = ""
        rows.append({"key": key, "label": label, "value": str(val), "editable": editable})
    return rows


def derive_query(
    md: Mapping[str, Any] | None,
    fields: Mapping[str, Any] | None = None,
    year: str | int | None = None,
) -> str:
    """The search string the pipeline would use for ``md`` with ``fields`` replaced."""
    from pigeon.raw_title import resolve_metadata_tmdb_query

    fields = {k: str(v).strip() for k, v in (fields or {}).items() if k in EDITABLE}
    md2 = dict(md or {})
    md2.update(fields)
    # ``query`` wins inside resolve_metadata_tmdb_query, so an edit to the title
    # fields must also retire the stale Apple TV search text.
    if "query" not in fields and any(k in fields for k in ("title", "series_name", "episode_title")):
        md2["query"] = ""
    q = fields.get("query") or resolve_metadata_tmdb_query(md2)
    q = " ".join(str(q or "").split())
    y = str(year or "").strip()
    if q and y.isdigit() and len(y) == 4 and not _YEAR_RE.search(q):
        q = f"{q} ({y})"
    return q


def _prefer(kind: Any) -> str:
    k = str(kind or "auto").strip().lower()
    return k if k in _KINDS else "auto"


def get() -> Override | None:
    with _LOCK:
        return _CURRENT


def _deactivate() -> None:
    """Stop applying the active correction (it stays stored)."""
    global _CURRENT
    with _LOCK:
        _CURRENT = None
    try:
        from pigeon.tmdb_poster import clear_forced_picks

        clear_forced_picks()
    except Exception:
        pass


def clear(md: Mapping[str, Any] | None = None, *, forget: bool = False) -> None:
    """Stop applying the correction; with ``forget`` also delete it from disk.

    ``forget`` removes every stored correction that shares a title key with
    ``md`` (the content on screen) or with the active correction.
    """
    ov = get()
    keys = set(content_keys(md)) | set(ov.keys if ov else [])
    _deactivate()
    if forget and keys:
        rows = _load_store()
        keep = [r for r in rows if not (keys & set(r.get("keys") or []))]
        if len(keep) != len(rows):
            _save_store(keep)
            _log(f"forgot {len(rows) - len(keep)} stored correction(s)")


def _activate(ov: Override) -> None:
    global _CURRENT
    if ov.pick:
        from pigeon.tmdb_poster import set_forced_pick

        set_forced_pick(ov.pick["kind"], int(ov.pick["tmdb_id"]), ov.query, str(ov.pick.get("title") or ""))
    with _LOCK:
        _CURRENT = ov


def _remember(ov: Override) -> None:
    rows = _load_store()
    mine = set(ov.keys)
    rows = [r for r in rows if not (mine & set(r.get("keys") or []))]
    rows.append({
        "keys": list(ov.keys), "query": ov.query, "prefer": ov.prefer, "fields": ov.fields,
        "year": ov.year, "pick": ov.pick, "created": ov.created,
    })
    _save_store(rows)


def _from_row(row: Mapping[str, Any]) -> Override:
    return Override(
        keys=list(row.get("keys") or []), query=str(row.get("query") or ""),
        prefer=_prefer(row.get("prefer")),
        fields=dict(row.get("fields") or {}), year=str(row.get("year") or ""),
        pick=dict(row["pick"]) if isinstance(row.get("pick"), dict) else None,
        created=float(row.get("created") or time.time()),
    )


def set_fields(
    md: Mapping[str, Any] | None,
    fields: Mapping[str, Any] | None,
    *,
    year: str | int | None = None,
    kind: Any = "auto",
) -> Override:
    """Replace metadata fields and search with the result (remembered)."""
    changed = any(k in EDITABLE and str(v).strip() for k, v in (fields or {}).items())
    if not changed and not str(year or "").strip() and _prefer(kind) == "auto":
        raise ValueError("no changes to apply")
    q = derive_query(md, fields, year)
    if not q:
        raise ValueError("nothing to search for")
    keys = content_keys(md)
    if not keys:
        raise ValueError("nothing is playing")
    clean = {k: str(v).strip() for k, v in (fields or {}).items() if k in EDITABLE}
    ov = Override(keys=keys, query=q, prefer=_prefer(kind), fields=clean,
                  year=str(year or "").strip())
    _deactivate()
    _activate(ov)
    _remember(ov)
    _log(f"saved edit for {keys[:2]} -> {q!r} prefer={ov.prefer}")
    return ov


def set_pick(
    md: Mapping[str, Any] | None,
    *,
    title: str,
    kind: str,
    tmdb_id: int,
    year: str | int | None = None,
) -> Override:
    """Force one specific TMDb title for this content (remembered)."""
    title = " ".join(str(title or "").split())
    if not title:
        raise ValueError("title is required")
    if kind not in ("movie", "tv"):
        raise ValueError("kind must be movie or tv")
    if int(tmdb_id) <= 0:
        raise ValueError("tmdb_id must be positive")
    keys = content_keys(md)
    if not keys:
        raise ValueError("nothing is playing")
    y = str(year or "").strip()
    q = f"{title} ({y})" if y.isdigit() and len(y) == 4 else title
    ov = Override(keys=keys, query=q, prefer=kind, year=y,
                  pick={"title": title, "kind": kind, "tmdb_id": int(tmdb_id), "year": y or None})
    _deactivate()
    _activate(ov)
    _remember(ov)
    _log(f"saved pick for {keys[:2]} -> {title!r} tmdb={tmdb_id} {kind}")
    return ov


def apply_override(query: str, prefer: str, md: Mapping[str, Any] | None) -> tuple[str, str]:
    """Hook for ``spawn_tmdb_poster_fetch``: swap in a remembered correction if it applies."""
    try:
        from pigeon import manual_search

        if manual_search.is_displaying():
            return query, prefer  # manual SEARCH spawns are not detected content
    except Exception:
        pass
    keys = content_keys(md)
    ov = get()
    if ov is not None:
        if not keys or _same_content(ov.keys, keys):
            return ov.query, ov.prefer
        _log(f"content changed, stopped applying {ov.query!r}")
        _deactivate()
    if not keys:
        return query, prefer
    for row in reversed(_load_store()):
        if _same_content(list(row.get("keys") or []), keys):
            found = _from_row(row)
            _activate(found)
            _log(f"re-applied remembered correction {found.query!r} for {keys[:2]}")
            return found.query, found.prefer
    return query, prefer
