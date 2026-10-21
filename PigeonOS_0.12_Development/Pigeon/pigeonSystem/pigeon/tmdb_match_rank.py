"""
TMDb result title matching and ranking.

Pure comparisons between a search query and TMDb result titles: title extraction,
token-subsequence and short-acronym checks, creator-possessive titles, and the tiered
``_match_rank`` / ``_match_rank_literal`` scores. No network or cache access.

``pigeon.tmdb_poster`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import re

from pigeon.tmdb_query import (
    _INTERPUNCT_LIKE_CHARS,
    _compact_interpunct_acronym,
    _compact_norm_for_acronym,
    _norm_query,
)


def _result_titles(item: dict) -> list[str]:
    """Candidate title strings for movie/tv result dicts."""
    vals = [
        item.get("title"),
        item.get("original_title"),
        item.get("name"),
        item.get("original_name"),
    ]
    out: list[str] = []
    for v in vals:
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    # de-dupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _tokens_subsequence(needle: list[str], haystack: list[str]) -> bool:
    """True if ``needle`` appears as consecutive tokens in ``haystack``."""
    if not needle:
        return True
    nlen = len(needle)
    for i in range(len(haystack) - nlen + 1):
        if haystack[i : i + nlen] == needle:
            return True
    return False


def _short_acronym_compact_norm(query: str) -> str | None:
    """Compact form for Pixar-style titles (``WALL·E``, ``WALL-E``, ``WALL E`` → ``walle``)."""
    compact = _compact_interpunct_acronym(query)
    if not compact or len(compact) > 8:
        return None
    nq = _norm_query(query)
    tokens = [t for t in nq.split() if t]
    if len(tokens) == 2 and len(tokens[1]) <= 2:
        return _compact_norm_for_acronym(compact)
    if re.fullmatch(r"^[A-Za-z0-9]{2,}-[A-Za-z0-9]{1,2}$", (query or "").strip()):
        return _compact_norm_for_acronym(compact)
    if any(ch in _INTERPUNCT_LIKE_CHARS for ch in (query or "")):
        return _compact_norm_for_acronym(compact)
    return None


def _weak_short_acronym_match(query: str, item: dict, rank: tuple[int, int]) -> bool:
    """Reject fuzzy ``wall*`` hits when the query is a short acronym like ``WALL-E``."""
    if rank[0] >= 4:
        return False
    must = _short_acronym_compact_norm(query)
    if not must:
        return False
    for title in _result_titles(item):
        if _compact_norm_for_acronym(title) == must:
            return False
    return True


# "Stephen King's It", "Tyler Perry's Madea's Big Happy Family": a 2+ word
# creator name, possessive, then the title TMDb lists. One-word possessives
# ("Grey's Anatomy", "Schitt's Creek") are real titles and are left alone.
_CREATOR_POSSESSIVE_RE = re.compile(
    r"^\s*(?:[A-Z][\w.\-]*\s+){1,2}[A-Z][\w.\-]*['\u2019]s\s+(.+)$"
)


def _creator_possessive_title(query: str) -> str | None:
    m = _CREATOR_POSSESSIVE_RE.match(str(query or ""))
    if not m:
        return None
    rest = m.group(1).strip()
    return rest or None


def _match_rank(query: str, item: dict) -> tuple[int, int]:
    """Tier for ``query`` vs ``item``; see :func:`_match_rank_literal`.

    A creator-possessive query also ranks its bare title, capped at tier 4 so
    an exact full-title hit still wins.
    """
    best = _match_rank_literal(query, item)
    bare = _creator_possessive_title(query)
    if bare:
        tier, neg_len = _match_rank_literal(bare, item)
        cand = (min(tier, 4), neg_len)
        if cand > best:
            best = cand
    return best


def _match_rank_literal(query: str, item: dict) -> tuple[int, int]:
    """
    Sort key (tier, tie_break) for picking the best TMDb search hit — lexicographic **max** wins.
    ``tie_break`` is ``-len(normalized_title)`` so **shorter** titles win when tier ties
    (e.g. "Luck" over "Good Luck, Have Fun, Don't Die" for query ``luck``).

    TV queries that map to ``_SHORT_SHOW_CANONICAL_QUERIES`` are pre-filtered so every candidate’s
    title **equals** the canonical series name (normalized), or that name plus **numeric-only** suffix
    tokens (TMDb’s ``(1975)`` style); those hits are not chosen on loose substring strength alone.

    Tiers (highest first):
      5 — normalized title **equals** query (exact)
      4 — multi-word query appears as **consecutive** whole tokens in the title
      3 — every query token appears as a **whole word** in the title
      2 — normalized query substring of normalized title (fuzzy)
      1 — every query token appears as substring in some title token
      0 — no match
    """
    nq = _norm_query(query)
    if not nq:
        return (0, 0)
    if not [t for t in nq.split() if t]:
        return (0, 0)
    nq_folded = _fold_sequel_numeral(nq)

    best: tuple[int, int] = (0, -(10**9))
    for title in _result_titles(item):
        nt = _norm_query(title)
        if not nt:
            continue
        neg_len = -len(nt)
        tier = _norm_tier(nq, nt)
        # ``Frozen 2`` vs TMDb's ``Frozen II``: compare with the trailing numeral folded too.
        if nq_folded != nq or _fold_sequel_numeral(nt) != nt:
            tier = max(tier, _norm_tier(nq_folded, _fold_sequel_numeral(nt)))

        cand = (tier, neg_len)
        if cand > best:
            best = cand
    return best


_ROMAN_SEQUEL = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9"}


def _fold_sequel_numeral(norm: str) -> str:
    """``frozen ii`` -> ``frozen 2``: a trailing roman numeral after at least one other word."""
    tokens = norm.split()
    if len(tokens) >= 2 and tokens[-1] in _ROMAN_SEQUEL:
        tokens[-1] = _ROMAN_SEQUEL[tokens[-1]]
        return " ".join(tokens)
    return norm


def _norm_tier(nq: str, nt: str) -> int:
    """Match tier (see :func:`_match_rank_literal`) for already-normalized query and title."""
    q_tokens = nq.split()
    t_tokens = nt.split()
    t_set = set(t_tokens)
    if nt == nq:
        return 5
    if len(q_tokens) >= 2 and _tokens_subsequence(q_tokens, t_tokens):
        return 4
    if all(qt in t_set for qt in q_tokens):
        return 3
    if nq in nt:
        return 2
    if all(any(qt in tw for tw in t_tokens) for qt in q_tokens):
        return 1
    return 0
