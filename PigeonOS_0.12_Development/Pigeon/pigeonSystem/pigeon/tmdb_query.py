"""
TMDb search-query and title normalization.

Pure text rules that turn a raw now-playing title into the string(s) sent to TMDb:
query normalization (``_norm_query``), year / parenthetical splitting, degenerate-query
detection, Unicode dash / interpunct handling, ``Show: Episode`` splitting, canonical
short-show names (SNL, late-night shows, ...), and query variants. No network, cache,
or filesystem access.

``pigeon.tmdb_poster`` re-exports every name here for existing importers
(``raw_title``, ``apple_tv_now_playing``, ``pigeon_0_12`` and the tests).
"""

from __future__ import annotations

import re
import unicodedata

from pigeon.tmdb_match_mode import tmdb_match_forgiving


# Trailing ``(YYYY)`` / ``[YYYY]`` years attached to titles by Apple TV / some TMDb clients.
# We accept 1900–2099 so bare numeric titles (``1984``, ``2012``, ``2046``) aren't year-stripped.
# Matches only at end-of-string so mid-title years (``Blade Runner 2049`` — not parenthesized) stay
# intact. Also catches a comma/space-separated year suffix (``Title, 2025``) because Apple TV
# occasionally emits that variant for theatrical titles imported into the TV app.
_TMDB_TRAILING_YEAR_RE = re.compile(
    r"\s*(?:[\(\[]\s*((?:19|20)\d{2})\s*[\)\]]|,\s*((?:19|20)\d{2}))\s*$"
)


def split_query_and_year(raw: str | None) -> tuple[str, int | None]:
    """Peel a trailing ``(YYYY)`` / ``[YYYY]`` / ``, YYYY`` off ``raw``.

    Returns ``(query_without_year, year)``. TMDb's ``/search/movie`` and ``/search/tv`` endpoints
    return zero hits when the query contains a parenthetical year (TMDb titles are stored without
    the year — the year belongs in the ``primary_release_year`` / ``first_air_date_year`` filter).
    This splitter lets the four ``search_*_best*`` helpers forward a clean title to TMDb while
    still pinning the year for disambiguation + filtering.

    Only the trailing token is peeled, and only when the remaining title is non-empty, so bare
    numeric titles (``1984``) and mid-title years (``Blade Runner 2049``) are left intact.
    """
    s = (raw or "").strip()
    if not s:
        return s, None
    m = _TMDB_TRAILING_YEAR_RE.search(s)
    if not m:
        return s, None
    grp = m.group(1) or m.group(2)
    try:
        y = int(grp)
    except (TypeError, ValueError):
        return s, None
    cleaned = s[: m.start()].rstrip(" ,;:-\u2013\u2014")
    cleaned = cleaned.strip()
    if not cleaned:
        # Year-only input (``(2025)``) — don't strip, leave TMDb to decide.
        return s, None
    return cleaned, y


_TRAILING_PAREN_RE = re.compile(r"\s*[\(\[][^()\[\]]*[\)\]]\s*$")


def strip_trailing_parenthetical(raw: str | None) -> str:
    """``Title (Taylor's Version)`` → ``Title``. Unchanged when nothing would be left."""
    text = str(raw or "").strip()
    stripped = _TRAILING_PAREN_RE.sub("", text).strip()
    return stripped or text


def _norm_query(s: str) -> str:
    """Normalize a query/title for substring + token matching (ASCII-ish, punctuation-insensitive)."""
    s = (s or "").strip().lower()
    if not s:
        return ""
    # Fold accents so "Café" and "Cafe" are the same title.
    s = "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )
    out: list[str] = []
    prev_space = False
    for ch in s:
        # Keep letters/digits; treat everything else as a space.
        if ch.isalnum():
            out.append(ch)
            prev_space = False
        else:
            if not prev_space:
                out.append(" ")
                prev_space = True
    return " ".join("".join(out).split())


# App / channel branding — not a movie or episode title (TMDb search yields wrong hits).
_DEGENERATE_TMDB_QUERIES = frozenset(
    {
        "disney",
        "disney+",
        "disney plus",
        "disney+ 365",
        "netflix",
        "hulu",
        "max",
        "peacock",
        "apple tv",
        "youtube",
        "paramount+",
        "paramount plus",
        "prime video",
        "amazon video",
        "amazon prime video",
        "amazon prime",
        "roku",
        "home",
        "settings",
        "hbo max",
        "hbomax",
        "nbc",
        "pbs",
        "pbs kids",
        "pbskids",
        "nick jr",
        "nickjr",
        "noggin",
    }
)


def is_degenerate_tmdb_query(q: str) -> bool:
    """
    True if ``q`` should not be sent to TMDb alone (streaming app name, splash branding, etc.).

    Short real titles (``It``, ``Up``, ``Us``) are valid — player metadata must
    still trigger a search.
    """
    raw = (q or "").strip()
    if not raw or len(raw) < 2:
        return True
    n = _norm_query(raw)
    if not n:
        return True
    if n in _DEGENERATE_TMDB_QUERIES:
        return True
    # "disney+ originals", "disney+ 365", etc.
    if "disney" in n and ("365" in n or n.endswith(" original") or n.endswith(" originals")):
        return True
    if n.replace(" ", "").isdigit():
        return True
    return False


# Keys match ``_norm_query()`` form (e.g. ``snl`` for ``SNL``, full title for specials).
_SHORT_SHOW_CANONICAL_QUERIES: dict[str, str] = {
    "snl": "Saturday Night Live",
    "saturday night live": "Saturday Night Live",
}


# When TMDb lists compilation specials as **movies** (e.g. ``Saturday Night Live: Christmas``), inferred
# ``prefer=movie`` from pyatv ``Video`` must still resolve the **series** for artwork. Keys = ``_norm_query``
# form of the canonical display title (same namespace as ``_exact_tv_title_norm_for_known_series_query``).
_SHORT_SHOW_TMDB_TV_ID_BY_NORM: dict[str, int] = {
    "saturday night live": 1667,
}


# Peacock often sends guest/segment lines with no ``series_name``. Longer needles first.
_NBC_LATE_NIGHT_SUBSTRING_TO_SERIES: tuple[tuple[str, str], ...] = (
    ("the tonight show starring jimmy fallon", "The Tonight Show Starring Jimmy Fallon"),
    ("last week tonight with john oliver", "Last Week Tonight with John Oliver"),
    ("the late show with stephen colbert", "The Late Show with Stephen Colbert"),
    ("late night with seth meyers", "Late Night with Seth Meyers"),
    ("jimmy fallon", "The Tonight Show Starring Jimmy Fallon"),
    ("seth meyers", "Late Night with Seth Meyers"),
    ("john oliver", "Last Week Tonight with John Oliver"),
    ("stephen colbert", "The Late Show with Stephen Colbert"),
)


def _compact_norm_for_acronym(s: str) -> str:
    return "".join(ch for ch in _norm_query(s) if ch.isalnum())


def _canonical_series_from_dash_pair(left: str, right: str) -> str | None:
    """
    Peacock / tvOS sometimes send ``SNL - Sketch`` or ``Sketch - SNL``.
    If either side is a known acronym, return the canonical series search string.
    """
    le, ri = left.strip(), right.strip()
    if not le or not ri:
        return None
    lk = _compact_norm_for_acronym(le)
    rk = _compact_norm_for_acronym(ri)
    if rk in _SHORT_SHOW_CANONICAL_QUERIES:
        return _SHORT_SHOW_CANONICAL_QUERIES[rk]
    if lk in _SHORT_SHOW_CANONICAL_QUERIES:
        return _SHORT_SHOW_CANONICAL_QUERIES[lk]
    return None


def _norm_blob_suggests_snl(norm_blob: str) -> bool:
    """True when combined metadata is clearly Saturday Night Live (not The Tonight Show)."""
    if not norm_blob:
        return False
    if "saturday night live" in norm_blob:
        return True
    return "snl" in frozenset(norm_blob.split())


def _canonical_series_from_nbc_late_night_blob(norm_blob: str) -> str | None:
    """
    Peacock / NBCUniversal apps often expose a guest or segment line without ``series_name``.
    Map obvious substrings to the TMDb series title. ``jimmy fallon`` is ignored when the blob looks
    like SNL (Fallon as host/guest).
    """
    if not norm_blob:
        return None
    for needle, canon in _NBC_LATE_NIGHT_SUBSTRING_TO_SERIES:
        if needle not in norm_blob:
            continue
        if needle == "jimmy fallon" and _norm_blob_suggests_snl(norm_blob):
            continue
        return canon
    return None


def canonical_tv_title_if_sketch_show_compound(display_title: str) -> str | None:
    """
    TMDb sometimes returns a TV row whose ``name`` is ``Sketch - SNL``, ``SNL - Sketch``,
    or ``Saturday Night Live: Christmas``-style episode/special labels.
    Replace with the canonical series title when a known show appears on the left (dash or colon).
    """
    q0 = _normalize_title_for_show_split(display_title or "")
    if not q0:
        return None
    pair = _sketch_show_dash_pair(q0)
    if pair is not None:
        c = _canonical_series_from_dash_pair(pair[0], pair[1])
        if c:
            return c
    for sep in (":", "\uff1a"):
        if sep in q0:
            a, b = q0.split(sep, 1)
            a_s, b_s = a.strip(), b.strip()
            if not a_s or not b_s:
                continue
            c = _canonical_series_from_dash_pair(a_s, b_s)
            if c:
                return c
            full = _SHORT_SHOW_CANONICAL_QUERIES.get(_norm_query(a_s))
            if full:
                return full
    return None


_UNICODE_DASH_CHARS = frozenset(
    "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uff0d"  # hyphen, dashes, minus (not ASCII -)
)


# NBSP and other spaces that break naive ``" - "`` substring checks (Peacock / tvOS metadata).
_SPACE_LIKE_RE = re.compile(r"[\u00a0\u2000-\u200a\u202f\u205f\u3000]+")


# Middle dot / bullet separators (Apple TV ``WALL·E``) — TMDb indexes ``WALL·E`` with the dot;
# hyphen queries (``WALL-E``) return unrelated ``wall*`` titles.
_INTERPUNCT_CHAR = "\u00b7"


_INTERPUNCT_LIKE_CHARS = frozenset("\u00b7\u2022\u2024\u2219\u22c5\u30fb\uff65")


# ``WALL E`` / ``WALL·E`` → ``WALL-E`` (short suffix token only, e.g. not ``STAR WARS``).
_ACRONYM_HYPHEN_SUFFIX_RE = re.compile(r"^([\w]{2,})\s+([\w]{1,2})$")


# ``Show - sketch`` with flexible space and any common dash (ASCII or unicode).
_SHOW_EPISODE_SEP_RE = re.compile(
    r"\s+[-\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uff0d]\s+"
)


# Metadata sometimes omits spaces around the hyphen (``Papryus-SNL``, ``Papryus -SNL``).
_LOOSE_SHOW_EPISODE_SEP_RE = re.compile(
    r"\s*[-\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uff0d]\s*"
)


def _sketch_show_dash_pair(q0: str) -> tuple[str, str] | None:
    """Return ``(left, right)`` for ``Sketch - Show`` / tight-hyphen variants, or None."""
    m = _SHOW_EPISODE_SEP_RE.split(q0, maxsplit=1)
    if len(m) == 2:
        a, b = m[0].strip(), m[1].strip()
        if a and b:
            return a, b
    parts = _LOOSE_SHOW_EPISODE_SEP_RE.split(q0, maxsplit=1)
    if len(parts) == 2:
        a, b = parts[0].strip(), parts[1].strip()
        if a and b:
            return a, b
    return None


def _normalize_unicode_dashes_for_episode_titles(s: str) -> str:
    """Map unicode dashes to `` - `` so ``SNL–Sketch`` (en dash) splits like ``SNL - Sketch``."""
    if not s:
        return s
    parts: list[str] = []
    for ch in s:
        if ch in _UNICODE_DASH_CHARS:
            parts.append(" - ")
        else:
            parts.append(ch)
    t = "".join(parts)
    while "   " in t:
        t = t.replace("   ", " ")
    while "  " in t:
        t = t.replace("  ", " ")
    return t.strip()


def _normalize_interpunct_for_tmdb(s: str) -> str:
    """Preserve middle-dot titles for TMDb search (API indexes ``WALL·E`` with the dot).

    Hyphen/compact variants are attempted separately in :func:`_tmdb_query_variants`; mapping
    ``·`` → ``-`` breaks the movie search (``WALL-E`` returns unrelated ``wall`` titles).
    """
    return s


def _compact_interpunct_acronym(s: str) -> str | None:
    """``WALL·E`` / ``WALL-E`` / ``WALL E`` → ``WALLE`` for TMDb variant search."""
    if not s:
        return None
    chars = list(s.strip())
    out: list[str] = []
    for ch in chars:
        if ch in _INTERPUNCT_LIKE_CHARS or ch in _UNICODE_DASH_CHARS or ch == "-":
            continue
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
        else:
            out.append(ch)
    t = "".join(out)
    t = re.sub(r"\s+", "", t).strip()
    if len(t) < 3:
        return None
    return t


def _interpunct_from_hyphen_acronym(q: str) -> str | None:
    """``WALL-E`` → ``WALL·E`` — TMDb movie search uses the middle-dot title, not the hyphen."""
    s = (q or "").strip()
    m = re.match(r"^([A-Za-z0-9]{2,})-([A-Za-z0-9]{1,2})$", s)
    if not m:
        return None
    return f"{m.group(1)}{_INTERPUNCT_CHAR}{m.group(2)}"


def _hyphen_acronym_movie_alias(q: str) -> str | None:
    """``WALL E`` → ``WALL-E`` when the suffix is a short token (Pixar-style acronym titles)."""
    m = _ACRONYM_HYPHEN_SUFFIX_RE.match((q or "").strip())
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}"


def _normalize_title_for_show_split(s: str) -> str:
    """Unicode dashes → spaced hyphen; preserve interpunct; NBSP-like → space; collapse runs."""
    if not s:
        return s
    t = _normalize_unicode_dashes_for_episode_titles(s.strip())
    t = _normalize_interpunct_for_tmdb(t)
    t = _SPACE_LIKE_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# Official works whose names look like ``Show: Episode`` (Max/Netflix colon style).
# Keys are :func:`_norm_query` form so punctuation/case do not matter.
_OFFICIAL_SUBTITLE_TITLE_NORMS = frozenset({
    "it welcome to derry",
})


def _pair_is_official_subtitle_title(left: str, right: str) -> bool:
    """
    True when ``Left: Right`` (or dash) is the work's real name, not Show + episode.

    ``IT: Welcome to Derry`` must not collapse to ``IT`` — that matches the older
    series/film *It*. Known sketch acronyms (``SNL``) still want the left side.
    """
    le, ri = (left or "").strip(), (right or "").strip()
    if not le or not ri:
        return False
    if _norm_query(f"{le} {ri}") in _OFFICIAL_SUBTITLE_TITLE_NORMS:
        return True
    if _norm_query(le) in _SHORT_SHOW_CANONICAL_QUERIES:
        return False
    if _compact_norm_for_acronym(le) in _SHORT_SHOW_CANONICAL_QUERIES:
        return False
    left_tokens = le.split()
    right_tokens = [t for t in ri.split() if t]
    # Short standalone titles (*It*, *Us*, *Up*) plus a multi-word subtitle are
    # franchises/spinoffs, not episode labels.
    return bool(
        len(left_tokens) == 1
        and len(left_tokens[0]) <= 4
        and len(right_tokens) >= 2
    )


def _colon_prefix_show_query_normalized(q0: str) -> str | None:
    """Core split for :func:`colon_prefix_show_query`; ``q0`` must already be :func:`_normalize_title_for_show_split`."""
    if not q0:
        return None

    def _split_show(sep: str) -> str | None:
        if sep not in q0:
            return None
        left, right = q0.split(sep, 1)
        left, right = left.strip(), right.strip()
        if not left or not right:
            return None
        if len(left) < 2:
            return None
        if is_degenerate_tmdb_query(left):
            return None
        if left.lower() == q0.lower():
            return None
        if _pair_is_official_subtitle_title(left, right):
            return None
        return left

    parts = _SHOW_EPISODE_SEP_RE.split(q0, maxsplit=1)
    if len(parts) == 2:
        left, right = parts[0].strip(), parts[1].strip()
        if left and right:
            if _pair_is_official_subtitle_title(left, right):
                return None
            canon = _canonical_series_from_dash_pair(left, right)
            if canon:
                return canon
            if (
                len(left) >= 2
                and not is_degenerate_tmdb_query(left)
                and left.lower() != q0.lower()
            ):
                return left

    for sep in (" - ", " – "):
        got = _split_show(sep)
        if got:
            return got
    for sep in ("\u2014", "\u2013"):
        got = _split_show(sep)
        if got:
            return got
    for sep in (":", "\uff1a"):
        got = _split_show(sep)
        if got:
            return got
    return None


def colon_prefix_show_query(raw: str) -> str | None:
    """
    If metadata looks like ``Show: segment`` or ``Show - sketch`` (guest, sketch, episode label),
    return the show side for TMDb when the full string would match the wrong thing or miss the series.

    **Prime / Hulu / Peacock:** titles like ``Series S01 E01 - Episode`` are split on the wrong dash if
    S/E is not removed first; we strip embedded season/episode clauses (see
    :func:`pigeon.raw_title._strip_season_episode_from_text`) and try that string before the original.
    """
    q0 = _normalize_title_for_show_split(raw or "")
    if not q0:
        return None
    candidates: list[str] = []
    try:
        from pigeon.raw_title import _strip_season_episode_from_text

        c_raw, _, _ = _strip_season_episode_from_text(q0)
        c_n = _normalize_title_for_show_split((c_raw or "").strip())
        if c_n:
            candidates.append(c_n)
    except ImportError:
        pass
    if not any(c.lower() == q0.lower() for c in candidates):
        candidates.append(q0)
    seen: set[str] = set()
    for cand in candidates:
        ck = cand.lower()
        if ck in seen:
            continue
        seen.add(ck)
        got = _colon_prefix_show_query_normalized(cand)
        if got:
            return got
    return None


def _colon_show_episode_pair(q: str) -> tuple[str, str] | None:
    """First ``Show: Episode`` split (ASCII or full-width colon); ``None`` if not a usable pair."""
    for sep in (":", "\uff1a"):
        if sep not in q:
            continue
        left, right = q.split(sep, 1)
        left, right = left.strip(), right.strip()
        if len(left) < 2 or len(right) < 2:
            continue
        if is_degenerate_tmdb_query(left):
            continue
        if left.lower() == q.lower():
            continue
        if _pair_is_official_subtitle_title(left, right):
            continue
        return left, right
    return None


def compound_title_streaming_series_fix(
    title: str | None, series_name: str | None
) -> str | None:
    """
    Streaming apps (Disney+, Peacock, Netflix, …) sometimes send a misleading ``series_name``:
    the full compound line duplicated in both fields, or the **episode** segment while ``title`` is
    still ``Show - Episode`` or ``Show: Episode``.
    """
    if not title or not series_name:
        return None
    t = title.strip()
    sn = series_name.strip()
    if not t or not sn:
        return None
    tl, snl = t.lower(), sn.lower()
    if tl == snl:
        cp = colon_prefix_show_query(t)
        if cp:
            return cp.strip()
        q0 = _normalize_title_for_show_split(t)
        if " - " in q0:
            left, _ = q0.split(" - ", 1)
            left = left.strip()
            if len(left) >= 2 and not is_degenerate_tmdb_query(left):
                return left
        pair_c = _colon_show_episode_pair(q0)
        if pair_c:
            le, _ri = pair_c
            return le
        return None
    q0 = _normalize_title_for_show_split(t)

    if " - " in q0:
        left, right = q0.split(" - ", 1)
        left, right = left.strip(), right.strip()
        if len(left) >= 2 and len(right) >= 2 and snl == right.lower():
            return left

    pair = _colon_show_episode_pair(q0)
    if pair:
        left, right = pair
        if snl == right.lower():
            return left

    return None


_GUEST_ON_SHOW_RE = re.compile(
    r"^(.+?)\s+on\s+(snl|saturday\s+night\s+live)\s*$",
    re.IGNORECASE,
)


def _guest_on_show_canonical_query(s: str) -> str | None:
    """``Will Ferrell on SNL`` → ``Saturday Night Live`` for TMDb TV search."""
    m = _GUEST_ON_SHOW_RE.match((s or "").strip())
    if not m:
        return None
    return _SHORT_SHOW_CANONICAL_QUERIES.get("snl") or "Saturday Night Live"


def refine_tmdb_search_query(raw: str | None) -> str | None:
    """
    Last-mile cleanup for any metadata source: unicode dashes, then ``Show - segment`` / colon stripping.
    Safe to call on strings that already went through pyatv heuristics (idempotent for plain titles).
    Official colon titles (``IT: Welcome to Derry``) are left intact so they are not
    reduced to a different work (``It``).
    """
    if raw is None:
        return None
    s = _normalize_title_for_show_split(str(raw).strip())
    if not s:
        return None
    if _norm_query(s) in _OFFICIAL_SUBTITLE_TITLE_NORMS:
        return s
    guest_show = _guest_on_show_canonical_query(s)
    if guest_show:
        return guest_show
    pick = colon_prefix_show_query(s)
    out = (pick or s).strip()
    return out or None


def canonical_tv_display_name_for_search_query(search_query: str) -> str | None:
    """
    When the user/device search resolves to a known acronym (e.g. ``SNL``), use TMDb’s full series
    name for on-screen title/logo cache even if TMDb matched a sketch row.
    """
    p = (search_query or "").strip()
    m = re.match(r"(?is)^tv\s+(.+)$", p)
    if m:
        p = m.group(1).strip()
    key = _norm_query(p)
    return _SHORT_SHOW_CANONICAL_QUERIES.get(key)


def _exact_tv_title_norm_for_known_series_query(q: str) -> str | None:
    """
    If ``q`` maps to a canonical series in ``_SHORT_SHOW_CANONICAL_QUERIES`` (via
    :func:`canonical_tv_display_name_for_search_query`, including after
    :func:`refine_tmdb_search_query`), return that series’ normalized title.

    TV search keeps only rows whose title matches the canonical series (normalized), optionally with
    **numeric-only** trailing tokens (e.g. TMDb’s ``(1975)`` in the title). When this returns
    non-``None``, media pick uses **TV** for that query (and a fixed TMDb id when configured) even if
    ``prefer`` is ``movie``, so compilation **movies** with the same words cannot beat the series.
    """
    p = (q or "").strip()
    m = re.match(r"(?is)^tv\s+(.+)$", p)
    if m:
        p = m.group(1).strip()
    canon = canonical_tv_display_name_for_search_query(p)
    if canon:
        return _norm_query(canon)
    r = refine_tmdb_search_query(p) or p
    if r.strip() != p.strip():
        canon = canonical_tv_display_name_for_search_query(r)
        if canon:
            return _norm_query(canon)
    return None


def resolve_tmdb_query_from_now_playing_fields(
    *,
    base_query: str | None,
    title: object | None = None,
    series_name: object | None = None,
    artist: object | None = None,
    album: object | None = None,
    episode_title: object | None = None,
    forgiving: bool | None = None,
) -> str | None:
    """
    Build the TMDb search string from pyatv-style fields plus the heuristic ``base_query``.

    **Literal mode** (default, ``PIGEON_TMDB_MATCH_MODE=literal``): first substantive non-degenerate
    field. Normally ``base_query`` (Apple TV heuristics) wins first so Disney+/etc. fixes beat a stale
    ``series_name``. When ``series_name`` and ``title`` disagree but ``base_query`` is just the episode
    ``title``, ``series_name`` is tried first so TV rows are not reduced to movie-style title-only
    metadata. If the chosen string is still just the episode line but combined metadata matches a
    Peacock/NBC late-night franchise (same substring map as forgiving mode), the canonical series
    title is used instead.

    **Forgiving mode** (``forgiving=True`` or env ``forgiving``): prefer canonical series titles,
    sketch–show compounds, Peacock NBC blob rules, episode hints, etc.
    """

    def _field(x: object | None) -> str | None:
        if x is None:
            return None
        t = str(x).strip()
        return t or None

    def _prefer_full_title_when_base_is_stub(
        base_q: str | None, title_q: str | None
    ) -> str | None:
        """If ``base_q`` is a short prefix of a fuller ``title_q``, return ``title_q``."""
        if not base_q or not title_q:
            return base_q
        nbq = _norm_query(base_q)
        nti = _norm_query(title_q)
        if (
            nbq
            and nti
            and len(nbq.split()) <= 2
            and len(nti.split()) >= 3
            and nti.startswith(nbq + " ")
        ):
            return title_q
        return base_q

    fg = tmdb_match_forgiving(override=forgiving)
    bq = _field(base_query)
    sn = _field(series_name)
    ti = _field(title)
    et = _field(episode_title)
    bq = _prefer_full_title_when_base_is_stub(bq, ti)
    if not fg:
        # Episode/film title in base_query while series_name names the show → search the show, not the episode string.
        bq_is_episode_like = bool(
            bq
            and (
                (ti and bq.lower() == ti.lower())
                or (et and bq.lower() == et.lower())
            )
        )
        compound_disagrees_with_sn = False
        if sn and ti:
            cp_ti = colon_prefix_show_query(ti)
            if cp_ti:
                snl = sn.lower()
                cpl = cp_ti.strip().lower()
                til = ti.lower()
                # Stale series_name (e.g. Disney+) while title is already ``NewShow - Episode``: trust base_query order.
                if cpl != snl and snl not in til:
                    compound_disagrees_with_sn = True
        prefer_series_first = bool(
            sn
            and not is_degenerate_tmdb_query(sn)
            and bq_is_episode_like
            and not compound_disagrees_with_sn
            and (
                (ti and sn.lower() != ti.lower())
                or (et and sn.lower() != et.lower())
            )
        )
        if prefer_series_first:
            ordered = (series_name, base_query, album, artist, title, episode_title)
        else:
            ordered = (base_query, series_name, album, artist, title, episode_title)
        first_pick: str | None = None
        for x in ordered:
            s = _field(x)
            if s and not is_degenerate_tmdb_query(s):
                first_pick = s
                break
        if first_pick is None:
            return None
        # Literal mode used to return before forgiving Peacock/NBC blob rules; guest-only titles still need it.
        blob_parts_lit: list[str] = []
        for x in (base_query, series_name, title, episode_title, artist, album):
            s = _field(x)
            if s and not is_degenerate_tmdb_query(s):
                blob_parts_lit.append(s)
        norm_lit = _norm_query(" ".join(blob_parts_lit)) if blob_parts_lit else ""
        nbc_lit = _canonical_series_from_nbc_late_night_blob(norm_lit)
        if nbc_lit:
            fp = first_pick.lower()
            episode_like_pick = bool(
                (ti and fp == ti.lower()) or (et and fp == et.lower())
            )
            if episode_like_pick and _norm_query(first_pick) != _norm_query(nbc_lit):
                return nbc_lit
        return first_pick

    ordered: list[str] = []
    for x in (base_query, series_name, title, episode_title, artist, album):
        s = _field(x)
        if s and s not in ordered:
            ordered.append(s)

    for s in ordered:
        compound = canonical_tv_title_if_sketch_show_compound(s)
        if compound:
            return compound
    for s in ordered:
        r = refine_tmdb_search_query(s) or s
        canon = canonical_tv_display_name_for_search_query(r)
        if canon:
            return canon

    # Peacock: guest/segment-only strings (no series_name) — e.g. Tonight Show, Late Night, LWT, Colbert.
    blob_parts: list[str] = []
    for x in (base_query, series_name, title, episode_title, artist, album):
        s = _field(x)
        if s and not is_degenerate_tmdb_query(s):
            blob_parts.append(s)
    norm_blob = _norm_query(" ".join(blob_parts)) if blob_parts else ""
    nbc_series = _canonical_series_from_nbc_late_night_blob(norm_blob)
    if nbc_series:
        return refine_tmdb_search_query(nbc_series) or nbc_series

    # Apple TV+ / streamers often put a sketch or episode label in ``title`` and the real series in
    # ``series_name``. Disney+ can send a **stale** ``series_name`` (previous show) while ``title``
    # is still ``Show - Episode`` — prefer the show parsed from ``title`` when it disagrees and the
    # reported series string does not appear inside ``title``.
        # bq/sn/ti/et were normalized above.
    if (
        sn
        and ti
        and sn.lower() != ti.lower()
        and not is_degenerate_tmdb_query(sn)
    ):
        cp = colon_prefix_show_query(ti)
        if cp:
            cpl = cp.strip().lower()
            snl = sn.lower()
            til = ti.lower()
            if cpl != snl and snl not in til:
                return refine_tmdb_search_query(cp) or cp.strip()
        return refine_tmdb_search_query(sn) or sn

    # Episode-only metadata (common on iOS Now Playing): optional ~/.pigeon_0_6/episode_series_hints.json
    if not sn:
        from pigeon.episode_series_hints import series_name_for_episode_title_hint

        for cand in (_field(episode_title), _field(title)):
            if not cand:
                continue
            g = series_name_for_episode_title_hint(cand)
            if g and not is_degenerate_tmdb_query(g):
                return refine_tmdb_search_query(g) or g

    if base_query is None:
        return None
    out = refine_tmdb_search_query(str(base_query).strip()) or str(base_query).strip()
    if not out:
        return None
    compound = canonical_tv_title_if_sketch_show_compound(out)
    if compound:
        return compound
    canon = canonical_tv_display_name_for_search_query(out)
    return canon or out


def equivalent_tmdb_search_queries(a: str, b: str) -> bool:
    """
    True when two query strings mean the same show for alternation / dedupe
    (e.g. primary ``SNL`` vs metadata title ``Papyrus - SNL``).
    """
    ra = refine_tmdb_search_query((a or "").strip()) or (a or "").strip()
    rb = refine_tmdb_search_query((b or "").strip()) or (b or "").strip()
    if ra.lower() == rb.lower():
        return True
    ca = canonical_tv_display_name_for_search_query(ra)
    cb = canonical_tv_display_name_for_search_query(rb)
    if ca and cb and ca.lower() == cb.lower():
        return True
    if ca and rb.lower() == ca.lower():
        return True
    if cb and ra.lower() == cb.lower():
        return True
    return False


_SINGALONG_RE = re.compile(
    r"[\(\[]?\s*[-:–—]?\s*\bsing[\s-]*a[\s-]*long\b(?:\s+(?:edition|version|cut))?\s*[\)\]]?",
    re.I,
)


def _strip_singalong(s: str) -> str | None:
    """``Frozen Sing-Along`` -> ``Frozen``; None when there is no sing-along marker."""
    if not _SINGALONG_RE.search(s):
        return None
    out = _SINGALONG_RE.sub(" ", s)
    out = re.sub(r"\s+", " ", out).strip(" -:–—|,")
    return out or None


def _tmdb_query_variants(raw: str) -> list[str]:
    """
    Extra query strings to try when now-playing metadata appends app names or episode titles
    (common from Apple TV), which TMDb will not match as a single search phrase.

    The full, unsimplified title is always tried first. Simplified variants
    (show-prefix, colon-left, etc.) are fallbacks only.
    """
    q0 = _normalize_title_for_show_split((raw or "").strip())
    raw0 = (raw or "").strip()
    if not q0:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        t = s.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)

    # Hyphen acronym titles (``WALL-E``): TMDb indexes ``WALL·E`` — try that before the hyphen.
    interpunct = _interpunct_from_hyphen_acronym(raw0 or q0)
    if interpunct:
        add(interpunct)
    # Always try the exact/full title next; only fall back to simplifications.
    add(q0)
    if raw0 and raw0.casefold() != q0.casefold():
        add(raw0)
    compact = _compact_interpunct_acronym(raw0 or q0)
    if compact:
        add(compact)
    alias = _hyphen_acronym_movie_alias(q0)
    if alias:
        add(alias)

    prefixes: list[str] = []

    def push_left(left: str, right: str) -> None:
        le = left.strip()
        ri = right.strip()
        if not le or not ri or len(le) < 2:
            return
        if is_degenerate_tmdb_query(le):
            return
        if le.lower() == q0.lower():
            return
        if _pair_is_official_subtitle_title(le, ri):
            return
        prefixes.append(le)

    rx_parts = _SHOW_EPISODE_SEP_RE.split(q0, maxsplit=1)
    if len(rx_parts) == 2:
        lx, rx = rx_parts[0].strip(), rx_parts[1].strip()
        cnp = _canonical_series_from_dash_pair(lx, rx)
        if cnp:
            add(cnp)
        else:
            push_left(lx, rx)

    if "|" in q0:
        a, b = q0.split("|", 1)
        push_left(a, b)
    if " - " in q0:
        a, b = q0.split(" - ", 1)
        push_left(a, b)
    for sep in (" – ", "\u2014", "\u2013"):
        if sep in q0:
            a, b = q0.split(sep, 1)
            push_left(a, b)
    for sep in (":", "\uff1a"):
        if sep in q0:
            a, b = q0.split(sep, 1)
            push_left(a, b)

    uniq_prefix: list[str] = []
    for p in prefixes:
        if p not in uniq_prefix:
            uniq_prefix.append(p)
    # Shortest first: e.g. ``SNL`` before a longer accidental prefix.
    uniq_prefix.sort(key=len)
    for p in uniq_prefix:
        add(p)
        key = _norm_query(p)
        canon = _SHORT_SHOW_CANONICAL_QUERIES.get(key)
        if canon:
            add(canon)
    if "|" in q0:
        add(q0.split("|", 1)[0])
    for sep in ("\u2014", "\u2013", " – "):
        if sep in q0:
            left, right = q0.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and not _pair_is_official_subtitle_title(left, right):
                add(left)
    for sep in (":", "\uff1a"):
        if sep in q0:
            left, right = q0.split(sep, 1)
            left, right = left.strip(), right.strip()
            if (
                left
                and not is_degenerate_tmdb_query(left)
                and not _pair_is_official_subtitle_title(left, right)
            ):
                add(left)
    # Sing-along screenings are listed on TMDb under the plain film title.
    for base in (q0, raw0):
        plain = _strip_singalong(base)
        if plain and not is_degenerate_tmdb_query(plain):
            add(plain)
    return out
