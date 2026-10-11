"""
Resolve an episode-only title to its parent TV series via Wikidata.

Used when Apple TV / streamers (Peacock, etc.) report an episode line with no
series name, and the local kids episode index / hints do not cover it.

Requires an unambiguous Wikidata hit: exact episode label match and exactly one
parent series (so generic titles like ``Pilot`` stay unresolved). The series comes
from structured claims, including its TMDb id when Wikidata has one.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_UA = "Pigeon/0.9 (episode-series; local media display)"
_API = "https://www.wikidata.org/w/api.php"
_EPISODE_DESC_RE = re.compile(
    r"(?i)^(?:(?:two|multi)-part )?(?:tv |television )?episode of\b"
)
_SERIES_FROM_DESC_RE = re.compile(
    r"(?i)^(?:(?:two|multi)-part )?(?:tv |television )?episode of (.+?)(?:\s*\(|$)"
)
# Trailing multi-part marker: ``Part 2``, ``(part 2)``, ``Pt. II``, ``- Part Two``.
_PART_SUFFIX_RE = re.compile(
    r"[\s,:\-–—]*[\(\[]?\s*\b(?:part|pt\.?)\s*(\d+|one|two|three|four|five|i{1,3}|iv|v)\s*[\)\]]?\s*$",
    re.IGNORECASE,
)
_PART_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
}

# ``instance of`` classes that mark an item as an episode (TV, two-part, generic, podcast).
_EPISODE_CLASSES = frozenset({"Q21191270", "Q21664088", "Q1983062", "Q61855877"})

# In-process cache: normalized episode title → candidate series list (empty = miss).
_cache: dict[str, list[dict[str, Any]]] = {}


def _norm(s: str) -> str:
    try:
        from pigeon.tmdb_poster import _norm_query

        return _norm_query(s)
    except Exception:
        t = re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
        return re.sub(r"\s+", " ", t)


def _http_json(params: dict[str, str], *, timeout_s: float = 12.0) -> dict[str, Any]:
    url = _API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _series_from_episode_description(desc: str) -> str | None:
    m = _SERIES_FROM_DESC_RE.match((desc or "").strip())
    if not m:
        return None
    name = m.group(1).strip().rstrip(".")
    # Reject descriptions that glued extra prose onto the series name.
    if not name or re.search(r"(?i)\bpublished on\b", name) or len(name) > 80:
        return None
    return name


def _split_part_suffix(title: str) -> tuple[str, str] | None:
    """``Weight Loss Part 2`` / ``Weight Loss (Pt. Two)`` → ``("Weight Loss", "2")``."""
    m = _PART_SUFFIX_RE.search(title or "")
    if not m:
        return None
    base = title[: m.start()].strip(" ,:-–—")
    if not base:
        return None
    num = m.group(1).lower()
    return base, _PART_WORDS.get(num, num)


def _episode_label_key(label: str) -> str:
    """Normalized label with any multi-part suffix canonicalized to ``part N``."""
    split = _split_part_suffix(label)
    if split is None:
        return _norm(label)
    base, num = split
    return f"{_norm(base)} part {num}"


def _claim_values(entity: dict, prop: str) -> list[Any]:
    out: list[Any] = []
    for st in (entity.get("claims") or {}).get(prop) or []:
        try:
            v = st["mainsnak"]["datavalue"]["value"]
        except (KeyError, TypeError):
            continue
        out.append(v.get("id") if isinstance(v, dict) else v)
    return out


def _get_entities(ids: list[str], props: str) -> dict[str, Any]:
    if not ids:
        return {}
    data = _http_json(
        {
            "action": "wbgetentities",
            "ids": "|".join(ids[:50]),
            "props": props,
            "languages": "en",
            "format": "json",
        }
    )
    ents = data.get("entities")
    return ents if isinstance(ents, dict) else {}


def _search_exact_episode_series(episode_title: str) -> list[dict[str, Any]]:
    """
    Candidate parent series (``{"name", "tmdb_tv_id"}``) for exact-label episode hits.

    Reads the episode's ``part of the series`` (P179) claim and the series' TMDb TV id
    (P4983); descriptions are free text (``third episode of the fifth season of the US
    television series The Office``), so they are only a fallback. An episode whose
    series cannot be named still counts, keeping the title ambiguous.
    """
    # Wikidata labels multi-part episodes ``Weight Loss (part 2)``; its prefix search finds
    # nothing for ``Weight Loss Part 2``, so also search the base title.
    searches = [(episode_title, "10")]
    split = _split_part_suffix(episode_title)
    if split is not None:
        searches.append((split[0], "20"))
    want = _episode_label_key(episode_title)
    ids: list[str] = []
    descs: dict[str, str] = {}
    for text, limit in searches:
        data = _http_json(
            {
                "action": "wbsearchentities",
                "search": text,
                "language": "en",
                "format": "json",
                "limit": limit,
                "type": "item",
            }
        )
        for row in data.get("search") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            if _episode_label_key(str(row.get("label") or "")) != want:
                continue
            qid = str(row["id"])
            if qid not in descs:
                ids.append(qid)
                descs[qid] = str(row.get("description") or "").strip()
    if not ids:
        return []

    episodes = _get_entities(ids, "claims")
    series_qids: list[str] = []
    unnamed: list[dict[str, Any]] = []
    for qid in ids:
        ent = episodes.get(qid) or {}
        desc = descs.get(qid, "")
        is_episode = bool(set(_claim_values(ent, "P31")) & _EPISODE_CLASSES) or "episode" in desc.lower()
        if not is_episode:
            continue
        parents = [v for v in _claim_values(ent, "P179") if isinstance(v, str)]
        if parents:
            series_qids.extend(v for v in parents if v not in series_qids)
            continue
        unnamed.append({"name": _series_from_episode_description(desc) or "", "tmdb_tv_id": None, "_qid": qid})

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    series_ents = _get_entities(series_qids, "labels|claims")
    for sq in series_qids:
        ent = series_ents.get(sq) or {}
        name = str(((ent.get("labels") or {}).get("en") or {}).get("value") or "")
        tmdb_id: int | None = None
        for raw in _claim_values(ent, "P4983"):
            try:
                tmdb_id = int(str(raw))
                break
            except ValueError:
                continue
        key = _norm(name) or f"?{sq}"
        if key not in seen:
            seen.add(key)
            out.append({"name": name, "tmdb_tv_id": tmdb_id})
    for row in unnamed:
        key = _norm(row["name"]) or f"?{row['_qid']}"
        if key not in seen:
            seen.add(key)
            out.append({"name": row["name"], "tmdb_tv_id": None})
    return out


def series_candidates_from_wikidata_episode_title(episode_title: str | None) -> list[dict[str, Any]]:
    """
    Every parent series (``{"name", "tmdb_tv_id"}``) with an episode labeled this title.

    ``Baby Shower`` is an episode of The Office, ER, Superstore and SNL; callers that
    know more (the series that was just playing) can pick among them. Empty on a miss
    or a transient network / rate-limit failure (which is not cached).
    """
    t = (episode_title or "").strip()
    if not t or len(t) < 2:
        return []
    key = _norm(t)
    if not key:
        return []
    if key in _cache:
        return list(_cache[key])

    try:
        candidates = _search_exact_episode_series(t)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
        ValueError,
        KeyError,
    ):
        # Transient network/rate-limit failures: do not cache a negative.
        return []

    _cache[key] = candidates
    return list(candidates)


def series_from_wikidata_episode_title(episode_title: str | None) -> dict[str, Any] | None:
    """
    Return ``{"name", "tmdb_tv_id"}`` for an unambiguous episode title, or ``None``.

    Ambiguous titles (multiple Wikidata episodes with the same name, from different
    series) return ``None`` rather than guessing. ``tmdb_tv_id`` may be ``None``.
    """
    candidates = series_candidates_from_wikidata_episode_title(episode_title)
    # Exactly one distinct series → use it; 0 or 2+ → unresolved.
    if len(candidates) == 1 and candidates[0].get("name"):
        return candidates[0]
    return None


def series_name_from_wikidata_episode_title(episode_title: str | None) -> str | None:
    """Parent series name for an unambiguous episode title, or ``None``."""
    hit = series_from_wikidata_episode_title(episode_title)
    return str(hit["name"]) if hit else None


def clear_wikidata_episode_cache() -> None:
    """For tests: drop in-process Wikidata episode→series cache."""
    _cache.clear()
