"""User corrections for what Pigeon searches TMDb for (companion app).

Two kinds of correction, both tied to the content that is playing *now* (they
drop themselves when the content changes, so a fix never leaks onto the next
show):

* **edited fields** — the metadata that feeds the query (title, series, episode,
  Apple TV search text, year, movie/tv) is replaced, then the normal query
  resolution runs on the edited copy;
* **pick** — a specific TMDb movie/TV id chosen from candidates, forced through
  :func:`pigeon.tmdb_poster.set_forced_pick`.

``apply_override`` is called from ``spawn_tmdb_poster_fetch`` and is the only
place the pipeline sees an override.
"""

from __future__ import annotations

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
_SIG_KEYS = ("app_id", "app_name", "title", "series_name", "episode_title", "query")
_YEAR_RE = re.compile(r"\((19|20)\d{2}\)\s*$")
_KINDS = ("auto", "movie", "tv")


@dataclass
class Override:
    sig: str
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


def signature(md: Mapping[str, Any] | None) -> str:
    md = md or {}
    return "\x1f".join(str(md.get(k) or "").strip().casefold() for k in _SIG_KEYS)


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


def clear() -> None:
    global _CURRENT
    with _LOCK:
        _CURRENT = None
    try:
        from pigeon.tmdb_poster import clear_forced_picks

        clear_forced_picks()
    except Exception:
        pass


def set_fields(
    md: Mapping[str, Any] | None,
    fields: Mapping[str, Any] | None,
    *,
    year: str | int | None = None,
    kind: Any = "auto",
) -> Override:
    """Replace metadata fields and search with the result."""
    global _CURRENT
    changed = any(k in EDITABLE and str(v).strip() for k, v in (fields or {}).items())
    if not changed and not str(year or "").strip() and _prefer(kind) == "auto":
        raise ValueError("no changes to apply")
    q = derive_query(md, fields, year)
    if not q:
        raise ValueError("nothing to search for")
    clean = {k: str(v).strip() for k, v in (fields or {}).items() if k in EDITABLE}
    ov = Override(sig=signature(md), query=q, prefer=_prefer(kind), fields=clean,
                  year=str(year or "").strip())
    clear()
    with _LOCK:
        _CURRENT = ov
    return ov


def set_pick(
    md: Mapping[str, Any] | None,
    *,
    title: str,
    kind: str,
    tmdb_id: int,
    year: str | int | None = None,
) -> Override:
    """Force one specific TMDb title for the current content."""
    global _CURRENT
    from pigeon.tmdb_poster import set_forced_pick

    title = " ".join(str(title or "").split())
    if not title:
        raise ValueError("title is required")
    if kind not in ("movie", "tv"):
        raise ValueError("kind must be movie or tv")
    y = str(year or "").strip()
    q = f"{title} ({y})" if y.isdigit() and len(y) == 4 else title
    clear()
    set_forced_pick(kind, int(tmdb_id), q, title)
    ov = Override(sig=signature(md), query=q, prefer=kind, year=y,
                  pick={"title": title, "kind": kind, "tmdb_id": int(tmdb_id), "year": y or None})
    with _LOCK:
        _CURRENT = ov
    return ov


def apply_override(query: str, prefer: str, md: Mapping[str, Any] | None) -> tuple[str, str]:
    """Hook for ``spawn_tmdb_poster_fetch``: swap in the user's correction if it still applies."""
    ov = get()
    if ov is None:
        return query, prefer
    try:
        from pigeon import manual_search

        if manual_search.is_displaying():
            return query, prefer  # manual SEARCH spawns are not detected content
    except Exception:
        pass
    if signature(md) != ov.sig:
        clear()  # different content now: the fix was for the previous one
        return query, prefer
    return ov.query, ov.prefer
