"""
TMDb cast name cache.

In-memory cache (``_CAST_CACHE``) of ``(actor, character)`` pairs per title key, backed
by ``tmdb_cast.json`` in the Pigeon state directory. Reads / writes / clears only;
fetching cast from the API stays in ``tmdb_poster.fetch_top_cast``.

``pigeon.tmdb_poster`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import json
from pathlib import Path

from pigeon.tmdb_query import split_query_and_year


# title_key → [(actor, character), ...] for view_circles cast row.
_CAST_CACHE: dict[str, list[tuple[str, str]]] = {}


_CAST_DISK_NAME = "tmdb_cast.json"


def _cast_disk_path() -> Path:
    try:
        from pigeon.runtime_paths import pigeon_state_dir

        return pigeon_state_dir() / _CAST_DISK_NAME
    except Exception:
        return Path.home() / ".pigeon_0_6" / _CAST_DISK_NAME


def _load_cast_from_disk(title_key_s: str) -> list[tuple[str, str]]:
    tk = str(title_key_s or "").strip()
    if not tk:
        return []
    path = _cast_disk_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    rows = raw.get(tk)
    if not isinstance(rows, list):
        cleaned, _year = split_query_and_year(tk)
        cleaned = (cleaned or "").strip()
        rows = raw.get(cleaned) if cleaned else None
    if not isinstance(rows, list):
        return []
    out: list[tuple[str, str]] = []
    for row in rows:
        if isinstance(row, (list, tuple)) and row:
            actor = str(row[0] or "").strip()
            character = str(row[1] or "").strip() if len(row) > 1 else ""
            if actor:
                out.append((actor, character))
        if len(out) >= 9:
            break
    return out


def _save_cast_to_disk(title_key_s: str, rows: list[tuple[str, str]]) -> None:
    tk = str(title_key_s or "").strip()
    if not tk:
        return
    path = _cast_disk_path()
    data: dict[str, object] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data = raw
    except Exception:
        data = {}
    data[tk] = [[str(a or ""), str(c or "")] for a, c in rows[:9]]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get_cached_tmdb_cast(title_key_s: str) -> list[tuple[str, str]]:
    """Return top cast cached for a reformatted-media title key (may be empty).

    Also tries a year-stripped alias so Apple TV ``Title (YYYY)`` keys still hit
    cast cached under the clean TMDb display name. Memory first, then disk so
    a restart still has actor / character names.
    """
    tk = str(title_key_s or "").strip()
    if not tk:
        return []
    hit = _CAST_CACHE.get(tk)
    if hit:
        return list(hit)
    cleaned, _year = split_query_and_year(tk)
    cleaned = (cleaned or "").strip()
    if cleaned and cleaned != tk:
        hit = _CAST_CACHE.get(cleaned)
        if hit:
            return list(hit)
    disk = _load_cast_from_disk(tk)
    if disk:
        _CAST_CACHE[tk] = list(disk)
        if cleaned and cleaned != tk:
            _CAST_CACHE[cleaned] = list(disk)
        return list(disk)
    return []


def clear_cached_tmdb_cast(title_key_s: str | None = None) -> None:
    if title_key_s is None:
        _CAST_CACHE.clear()
        return
    _CAST_CACHE.pop(str(title_key_s).strip(), None)


def cache_tmdb_cast_for_title(title_key_s: str, cast: list[tuple[str, str]]) -> None:
    tk = str(title_key_s or "").strip()
    if not tk:
        return
    rows = [(str(a or ""), str(c or "")) for a, c in cast[:9]]
    # Bound the cache: long sessions cycle through many titles; evict oldest.
    while len(_CAST_CACHE) >= 64:
        _CAST_CACHE.pop(next(iter(_CAST_CACHE)))
    _CAST_CACHE[tk] = rows
    cleaned, _year = split_query_and_year(tk)
    cleaned = (cleaned or "").strip()
    if cleaned and cleaned != tk:
        _CAST_CACHE[cleaned] = list(rows)
    _save_cast_to_disk(tk, rows)
