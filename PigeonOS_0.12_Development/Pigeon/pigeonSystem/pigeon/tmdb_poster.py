"""
TMDb: search movie and/or TV by title, download poster into pigeonPulledMedia, then poster pipeline.

Credentials (never commit real keys):
  - PIGEON_TMDB_READ_TOKEN  — JWT read access token (Bearer), preferred
  - PIGEON_TMDB_API_KEY     — v3 API key (query param)
  Or files in ~/.pigeon_0_6/: tmdb_read_token, tmdb_api_key (single line each)

Query hints (optional):
  - Prefix ``tv `` to search TV only (e.g. ``tv Breaking Bad``).
  - Prefix ``movie `` to search movies only.
  - Pass pyatv ``app_name`` / ``app_id`` into :func:`apply_tmdb_movie_query` /
    :func:`search_best_media` so the foreground streaming service is part of
    identification for **every** app (not only PBS Kids): try ``Title Service``
    before the bare title, and prefer TMDb rows available on that service.
    Kids-primary apps still prefer TV and demote adult substring matches.
    Episode-only lines fall back to a cached episode-title → series index
    system-wide whenever normal TMDb title search is missing or weakly aligned.

Title matching (env):
  - ``PIGEON_TMDB_MATCH_MODE=literal`` (default) — use now-playing strings as-is where possible; only
    accept TMDb hits with strong title alignment (exact norm for single-word queries, consecutive
    tokens for multi-word). Skips query variants, forced movie/TV shortcuts, and fuzzy tiers.
  - ``PIGEON_TMDB_MATCH_MODE=forgiving`` — previous heuristic behavior (variants, substring tiers, etc.).

Runtime: in the app, **+** (Shift+= on US keyboards; numpad +) toggles literal ↔ forgiving until quit;
that overrides the env default for the current session.

This product uses the TMDb API but is not endorsed or certified by TMDb.

Language:
  - Requests use ``language=en-US``. Search ranking prefers ``original_language=en`` on
    title-tier ties (non-English is never excluded). Poster art prefers English, then
    language-neutral, then any other language only when English is unavailable. Logos
    remain English-only (no non-English fallback).
"""

from __future__ import annotations

import json
import os
import random
import re
import unicodedata
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal

import numpy as np

from pigeon.app_state import auto_delete_pulled_media
from pigeon.image_ui_protocol import backdrop_master_bgr_from_file, pulled_path_is_under_pulled_dir
from pigeon.media_cache import (
    ASSET_BACKDROP,
    ASSET_LOGO,
    ASSET_LOGO_EN,
    ASSET_POSTER_ART,
    copy_pulled_to_reformatted,
    find_cached_reformatted_asset,
    forget_recent_asset_lookups,
    title_key,
)
from pigeon.media_folders import (
    ensure_tmdb_media_dirs,
    pigeon_pulled_media_dir,
    purge_directory_contents,
    trim_pulled_media_dir,
)
from pigeon.tmdb_query import (  # noqa: F401  (re-exported for existing importers)
    _ACRONYM_HYPHEN_SUFFIX_RE,
    _DEGENERATE_TMDB_QUERIES,
    _GUEST_ON_SHOW_RE,
    _INTERPUNCT_CHAR,
    _INTERPUNCT_LIKE_CHARS,
    _LOOSE_SHOW_EPISODE_SEP_RE,
    _NBC_LATE_NIGHT_SUBSTRING_TO_SERIES,
    _OFFICIAL_SUBTITLE_TITLE_NORMS,
    _SHORT_SHOW_CANONICAL_QUERIES,
    _SHORT_SHOW_TMDB_TV_ID_BY_NORM,
    _SHOW_EPISODE_SEP_RE,
    _SPACE_LIKE_RE,
    _TMDB_TRAILING_YEAR_RE,
    _TRAILING_PAREN_RE,
    _UNICODE_DASH_CHARS,
    _canonical_series_from_dash_pair,
    _canonical_series_from_nbc_late_night_blob,
    _colon_prefix_show_query_normalized,
    _colon_show_episode_pair,
    _compact_interpunct_acronym,
    _compact_norm_for_acronym,
    _exact_tv_title_norm_for_known_series_query,
    _guest_on_show_canonical_query,
    _hyphen_acronym_movie_alias,
    _interpunct_from_hyphen_acronym,
    _norm_blob_suggests_snl,
    _norm_query,
    _normalize_interpunct_for_tmdb,
    _normalize_title_for_show_split,
    _normalize_unicode_dashes_for_episode_titles,
    _pair_is_official_subtitle_title,
    _sketch_show_dash_pair,
    _tmdb_query_variants,
    canonical_tv_display_name_for_search_query,
    canonical_tv_title_if_sketch_show_compound,
    colon_prefix_show_query,
    compound_title_streaming_series_fix,
    equivalent_tmdb_search_queries,
    is_degenerate_tmdb_query,
    refine_tmdb_search_query,
    resolve_tmdb_query_from_now_playing_fields,
    split_query_and_year,
    strip_trailing_parenthetical,
)
from pigeon.tmdb_match_mode import (  # noqa: F401  (re-exported for existing importers)
    _FORGIVING_ENV_TOKENS,
    _env_wants_forgiving,
    tmdb_match_forgiving,
    toggle_tmdb_match_mode,
)
from pigeon.runtime_paths import pigeon_state_dir as _pigeon_state_dir
from pigeon.tmdb_match_rank import (  # noqa: F401  (re-exported for existing importers)
    _CREATOR_POSSESSIVE_RE,
    _creator_possessive_title,
    _match_rank,
    _match_rank_literal,
    _result_titles,
    _short_acronym_compact_norm,
    _tokens_subsequence,
    _weak_short_acronym_match,
)
from pigeon.tmdb_http import (  # noqa: F401  (re-exported for existing importers)
    _UA,
    _download_binary,
    _http_get_bytes,
    _minimal_subprocess_env,
    _sanitize_api_secret,
)
from pigeon.tmdb_cast_cache import (  # noqa: F401  (re-exported for existing importers)
    _CAST_CACHE,
    _CAST_DISK_NAME,
    _cast_disk_path,
    _load_cast_from_disk,
    _save_cast_to_disk,
    cache_tmdb_cast_for_title,
    clear_cached_tmdb_cast,
    get_cached_tmdb_cast,
)
from pigeon.tmdb_streaming import (  # noqa: F401  (re-exported for existing importers)
    Prefer,
    _KIDS_GENRE_IDS,
    _KIDS_STREAMING_APP_NEEDLES,
    _KIDS_STREAMING_BUNDLE_NEEDLES,
    _WATCH_PROVIDER_IDS_BY_NORM,
    _apply_kids_service_result_bias,
    _item_has_kids_genre,
    _service_first_enabled,
    is_kids_streaming_service,
    prefer_media_for_streaming_service,
    streaming_service_display_name,
    watch_provider_ids_for_streaming_service,
)

TMDB_API_BASE = "https://api.themoviedb.org/3"
# Primary product language: request English metadata/artwork when TMDb has it.
# Non-English originals and assets remain available as fallbacks (never hard-excluded).
TMDB_UI_LANGUAGE = "en-US"
TMDB_PRIMARY_ISO_639 = "en"
POSTER_SIZE = "w780"  # good balance before local 1800-wide pipeline
IMG_BASE = f"https://image.tmdb.org/t/p/{POSTER_SIZE}"
# English logos: pull at w1280 for sharp logo-only / downscaled title art (see ``LogoEn`` cache).
LOGO_SIZE = "w1280"
BACKDROP_SIZE = "w1280"
IMG_LOGO_BASE = f"https://image.tmdb.org/t/p/{LOGO_SIZE}"
IMG_BACKDROP_BASE = f"https://image.tmdb.org/t/p/{BACKDROP_SIZE}"

MediaKind = Literal["movie", "tv"]

_PLAYER_DURATION_S: float | None = None
_LAST_TRT: dict[str, float | None] = {
    "player_s": None,
    "tmdb_s": None,
    "similarity": None,
}
_TMDB_DETAIL_CACHE: dict[tuple[str, int], dict] = {}
_TMDB_DETAIL_CACHE_MAX = 64
_TRT_ENRICH_CAP = 6


def _literal_min_acceptable_tier(query: str) -> int:
    """Single-token query → require exact normalized title (tier 5). Multi-word → consecutive tokens (tier 4)."""
    q_tokens = [t for t in _norm_query(query).split() if t]
    if not q_tokens:
        return 5
    return 5 if len(q_tokens) <= 1 else 4


def _title_norm_matches_exact_tv_series_filter(must_norm: str, title_norm: str) -> bool:
    """
    For short-show canonical queries: keep TMDb rows whose name equals the series **or** adds only
    numeric tokens after the series (e.g. ``Saturday Night Live (1975)`` → ``saturday night live 1975``).

    Rejects spin-offs with word suffixes (``Saturday Night Live: Christmas`` → ``… christmas``).
    """
    if not must_norm or not title_norm:
        return False
    if title_norm == must_norm:
        return True
    prefix = must_norm + " "
    if not title_norm.startswith(prefix):
        return False
    rest = title_norm[len(prefix) :].strip()
    if not rest:
        return False
    for tok in rest.split():
        if not tok.isdigit():
            return False
    return True


_WATCH_REGION = "US"
_WATCH_PROVIDER_BUCKETS: tuple[str, ...] = ("flatrate", "ads", "free")
_WATCH_PROVIDER_LOOKUP_CAP = 8
# (kind, tmdb_id) → provider ids in US, or None when the lookup failed.
_WATCH_PROVIDERS_CACHE: dict[tuple[str, int], frozenset[int] | None] = {}


def _tmdb_watch_provider_ids(kind: MediaKind, tmdb_id: int) -> frozenset[int] | None:
    """US subscription/free provider ids for one title, or None when the lookup fails."""
    try:
        mid = int(tmdb_id)
    except (TypeError, ValueError):
        return None
    key = (str(kind), mid)
    if key in _WATCH_PROVIDERS_CACHE:
        return _WATCH_PROVIDERS_CACHE[key]
    path = "tv" if kind == "tv" else "movie"
    try:
        data = _request_json(f"{TMDB_API_BASE}/{path}/{mid}/watch/providers")
    except (
        RuntimeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ):
        _WATCH_PROVIDERS_CACHE[key] = None
        return None
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, dict):
        _WATCH_PROVIDERS_CACHE[key] = None
        return None
    region = results.get(_WATCH_REGION)
    if not isinstance(region, dict):
        _WATCH_PROVIDERS_CACHE[key] = None
        return None
    ids: set[int] = set()
    for bucket in _WATCH_PROVIDER_BUCKETS:
        rows = region.get(bucket)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                ids.add(int(row.get("provider_id")))
            except (TypeError, ValueError):
                continue
    out = frozenset(ids)
    _WATCH_PROVIDERS_CACHE[key] = out
    return out


def _service_availability_score(
    item: dict,
    media_kind: MediaKind | None,
    watch_provider_ids: frozenset[int] | None,
) -> int:
    """1 when the title is listed on the foreground service, else 0 (unknown does not penalize)."""
    if not watch_provider_ids or not media_kind:
        return 0
    mid = item.get("id") if isinstance(item, dict) else None
    if mid is None:
        return 0
    have = _tmdb_watch_provider_ids(media_kind, int(mid))
    if not have:
        return 0
    return 1 if have & watch_provider_ids else 0


def _result_pick_key(
    item: dict,
    media_kind: MediaKind | None,
    watch_provider_ids: frozenset[int] | None,
) -> tuple[int, int, float]:
    svc = _service_availability_score(item, media_kind, watch_provider_ids)
    en, pop = _english_prefer_popularity_key(item)
    return (svc, en, pop)


def _pick_best_from_pool(
    pool: list[dict],
    *,
    media_kind: MediaKind | None = None,
    watch_provider_ids: frozenset[int] | None = None,
) -> dict:
    if not watch_provider_ids or not media_kind or len(pool) == 1:
        return max(pool, key=_english_prefer_popularity_key)
    ranked = sorted(pool, key=_english_prefer_popularity_key, reverse=True)
    probe_ids: set[int] = set()
    for row in ranked[:_WATCH_PROVIDER_LOOKUP_CAP]:
        mid = row.get("id") if isinstance(row, dict) else None
        if mid is None:
            continue
        try:
            probe_ids.add(int(mid))
        except (TypeError, ValueError):
            continue

    def key(it: dict) -> tuple[int, int, float]:
        mid = it.get("id") if isinstance(it, dict) else None
        try:
            iid = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            iid = None
        if iid is None or iid not in probe_ids:
            en, pop = _english_prefer_popularity_key(it)
            return (0, en, pop)
        return _result_pick_key(it, media_kind, watch_provider_ids)

    return max(pool, key=key)


def set_player_duration_hint(seconds: float | None) -> float | None:
    """Remember Apple TV TRT (seconds) for the current TMDb search."""
    global _PLAYER_DURATION_S
    prev = _PLAYER_DURATION_S
    try:
        value = float(seconds) if seconds is not None else None
    except (TypeError, ValueError):
        value = None
    _PLAYER_DURATION_S = value if value is not None and value > 0.0 else None
    return prev


@contextmanager
def player_duration_hint(seconds: float | None) -> Iterator[None]:
    prev = set_player_duration_hint(seconds)
    try:
        yield
    finally:
        set_player_duration_hint(prev)


def last_trt_comparison() -> dict[str, float | None]:
    return dict(_LAST_TRT)


# What the most recent :func:`apply_tmdb_movie_query` call searched and pulled
# (TMDb ids + image ``file_path``s) for the accuracy report. One worker runs at
# a time, so a module global is enough.
_LAST_FETCH_TRACE: dict[str, object] = {}


def last_fetch_trace() -> dict[str, object]:
    return dict(_LAST_FETCH_TRACE)


def _trace_fetch(**fields: object) -> None:
    _LAST_FETCH_TRACE.update(fields)


def remember_trt_comparison(
    *,
    player_s: float | None,
    tmdb_s: float | None,
    similarity: float | None,
) -> None:
    _LAST_TRT["player_s"] = player_s
    _LAST_TRT["tmdb_s"] = tmdb_s
    _LAST_TRT["similarity"] = similarity


def tmdb_runtime_seconds_options(item: dict | None) -> list[float]:
    """Possible TMDb lengths in seconds (film runtime, episode, whole series)."""
    if not isinstance(item, dict):
        return []
    out: list[float] = []

    def _add_minutes(raw: object) -> None:
        try:
            minutes = float(raw)
        except (TypeError, ValueError):
            return
        if minutes > 0.0:
            out.append(minutes * 60.0)

    _add_minutes(item.get("runtime"))
    ert = item.get("episode_run_time")
    ep_minutes: list[float] = []
    if isinstance(ert, list):
        for raw in ert:
            try:
                minutes = float(raw)
            except (TypeError, ValueError):
                continue
            if minutes > 0.0:
                ep_minutes.append(minutes)
                _add_minutes(minutes)
    else:
        try:
            minutes = float(ert) if ert not in (None, "") else 0.0
        except (TypeError, ValueError):
            minutes = 0.0
        if minutes > 0.0:
            ep_minutes.append(minutes)
            _add_minutes(minutes)
    episodes = 0
    try:
        episodes = int(item.get("number_of_episodes") or 0)
    except (TypeError, ValueError):
        episodes = 0
    seasons = item.get("seasons")
    if isinstance(seasons, list):
        season_eps = 0
        for season in seasons:
            if not isinstance(season, dict):
                continue
            try:
                if int(season.get("season_number") or 0) == 0:
                    continue
                season_eps += int(season.get("episode_count") or 0)
            except (TypeError, ValueError):
                continue
        if season_eps > episodes:
            episodes = season_eps
    if episodes > 1 and ep_minutes:
        _add_minutes(ep_minutes[0] * episodes)
    unique = sorted({round(sec, 3) for sec in out if sec > 0.0})
    return unique


def _item_has_runtime_fields(item: dict) -> bool:
    if item.get("runtime"):
        return True
    ert = item.get("episode_run_time")
    if isinstance(ert, list):
        return bool(ert)
    return bool(ert)


def _cache_tmdb_detail(kind: MediaKind, media_id: int, detail: dict) -> None:
    if len(_TMDB_DETAIL_CACHE) >= _TMDB_DETAIL_CACHE_MAX:
        _TMDB_DETAIL_CACHE.pop(next(iter(_TMDB_DETAIL_CACHE)))
    slim = {
        "runtime": detail.get("runtime"),
        "episode_run_time": detail.get("episode_run_time"),
        "number_of_episodes": detail.get("number_of_episodes"),
        "seasons": detail.get("seasons"),
    }
    _TMDB_DETAIL_CACHE[(kind, int(media_id))] = slim


def enrich_item_runtime(item: dict, kind: MediaKind) -> dict:
    """Attach TMDb detail runtimes when search rows omit them."""
    if not isinstance(item, dict):
        return item
    if _item_has_runtime_fields(item):
        return item
    try:
        mid = int(item.get("id"))
    except (TypeError, ValueError):
        return item
    cached = _TMDB_DETAIL_CACHE.get((kind, mid))
    if cached is None:
        detail = _tmdb_movie_detail(mid) if kind == "movie" else _tmdb_tv_detail(mid)
        if not isinstance(detail, dict):
            return item
        _cache_tmdb_detail(kind, mid, detail)
        cached = _TMDB_DETAIL_CACHE.get((kind, mid))
    if not cached:
        return item
    merged = dict(item)
    for key, value in cached.items():
        if value not in (None, "", []):
            merged[key] = value
    if kind == "tv" and not tmdb_runtime_seconds_options(merged):
        episode = _tmdb_tv_episode(mid, 1, 1)
        runtime = episode.get("runtime") if isinstance(episode, dict) else None
        if runtime:
            merged = dict(merged)
            merged["episode_run_time"] = [runtime]
            cached_ep = dict(cached)
            cached_ep["episode_run_time"] = [runtime]
            _TMDB_DETAIL_CACHE[(kind, mid)] = cached_ep
    return merged


def _best_runtime_seconds(item: dict | None) -> float | None:
    opts = tmdb_runtime_seconds_options(item)
    player = _PLAYER_DURATION_S
    if not opts:
        return None
    if player is None:
        return opts[0]
    from pigeon.display_confidence import trt_similarity

    return max(opts, key=lambda sec: trt_similarity(player, sec))


def _trt_score_for_item(item: dict | None) -> float | None:
    from pigeon.display_confidence import trt_confidence

    return trt_confidence(_PLAYER_DURATION_S, tmdb_runtime_seconds_options(item))


def _trt_rejects(player_s: float | None, item: dict | None, kind: MediaKind | None) -> bool:
    """Hard TRT reject — movies only.

    TMDb TV runtimes are a typical episode length; premieres / finales often run
    20–30 min longer (IT: Welcome to Derry: 54 min listed, 1:17 episode). For TV
    a mismatch only lowers the rank, so a long episode cannot knock out the right
    show in favor of an unrelated title with a closer runtime.
    """
    if item is None or kind == "tv":
        return False
    from pigeon.display_confidence import trt_is_reject

    return trt_is_reject(player_s, tmdb_runtime_seconds_options(item))


def _forced_movie_survives_trt(item: dict | None) -> dict | None:
    """Drop a forced movie shortcut when Apple TV TRT clearly disagrees."""
    if item is None:
        return None
    if _PLAYER_DURATION_S is None:
        return item
    from pigeon.display_confidence import trt_is_reject

    enriched = enrich_item_runtime(item, "movie")
    if trt_is_reject(_PLAYER_DURATION_S, tmdb_runtime_seconds_options(enriched)):
        return None
    return enriched


def _prefer_duration_match(
    movie: dict | None,
    tv: dict | None,
) -> tuple[dict | None, MediaKind | None]:
    """When Apple TV TRT is known, pick the catalogue whose runtime is closer."""
    player = _PLAYER_DURATION_S
    movie_e = enrich_item_runtime(movie, "movie") if movie is not None else None
    tv_e = enrich_item_runtime(tv, "tv") if tv is not None else None
    movie_s = _trt_score_for_item(movie_e)
    tv_s = _trt_score_for_item(tv_e)
    if _trt_rejects(player, movie_e, "movie"):
        movie_e, movie_s = None, None
    if _trt_rejects(player, tv_e, "tv"):
        tv_e, tv_s = None, None
    if movie_e is not None and tv_e is not None:
        if movie_s is not None and tv_s is not None:
            if tv_s > movie_s + 0.08:
                return tv_e, "tv"
            if movie_s > tv_s + 0.08:
                return movie_e, "movie"
            return (tv_e, "tv") if tv_s > movie_s else (movie_e, "movie")
        if tv_s is not None and movie_s is None:
            return tv_e, "tv"
        if movie_s is not None and tv_s is None:
            return movie_e, "movie"
        return movie_e, "movie"
    if movie_e is not None:
        return movie_e, "movie"
    if tv_e is not None:
        return tv_e, "tv"
    if player is None:
        if movie is not None:
            return movie, "movie"
        if tv is not None:
            return tv, "tv"
    return None, None


def _rerank_scored_by_trt(
    scored: list[tuple[dict, tuple[int, int]]],
    *,
    media_kind: MediaKind | None,
    title_pick: dict | None,
) -> dict | None:
    """Prefer title hits whose TMDb runtime matches Apple TV TRT."""
    from pigeon.display_confidence import TRT_AGREE

    if _PLAYER_DURATION_S is None or not scored:
        return title_pick
    best_tier = max(rk[0] for _, rk in scored)
    floor = max(3, best_tier - 1) if best_tier > 0 else 0
    eligible = [(r, rk) for r, rk in scored if rk[0] >= floor]
    eligible.sort(key=lambda pair: (pair[1], _english_prefer_popularity_key(pair[0])), reverse=True)
    ranked: list[tuple[dict, tuple[int, int], float | None]] = []
    for raw, rk in eligible[:_TRT_ENRICH_CAP]:
        item = enrich_item_runtime(raw, media_kind) if media_kind is not None else raw
        ranked.append((item, rk, _trt_score_for_item(item)))
    agree = [row for row in ranked if row[2] is not None and row[2] >= TRT_AGREE]
    if agree:
        return max(agree, key=lambda row: (row[2], row[1]))[0]
    weak = [
        row
        for row in ranked
        if row[2] is not None
        and not _trt_rejects(_PLAYER_DURATION_S, row[0], media_kind)
    ]
    if weak:
        return max(weak, key=lambda row: (row[2], row[1]))[0]
    if any(row[2] is None for row in ranked):
        return title_pick
    return None


def load_tmdb_api_key() -> str | None:
    k = _sanitize_api_secret(os.environ.get("PIGEON_TMDB_API_KEY", ""))
    if k:
        return k
    p = _pigeon_state_dir() / "tmdb_api_key"
    if p.is_file():
        try:
            return _sanitize_api_secret(p.read_bytes()) or None
        except OSError:
            return None
    return None


def load_tmdb_read_token() -> str | None:
    t = _sanitize_api_secret(os.environ.get("PIGEON_TMDB_READ_TOKEN", ""))
    if t:
        return t
    p = _pigeon_state_dir() / "tmdb_read_token"
    if p.is_file():
        try:
            return _sanitize_api_secret(p.read_bytes()) or None
        except OSError:
            return None
    return None


def tmdb_is_configured() -> bool:
    """True when a TMDb API key or read token is available."""
    return bool(load_tmdb_read_token() or load_tmdb_api_key())


def _request_json(url: str) -> dict:
    headers = {"User-Agent": _UA}
    token = load_tmdb_read_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        api_key = load_tmdb_api_key()
        if not api_key:
            raise RuntimeError(
                "TMDb not configured. Set PIGEON_TMDB_READ_TOKEN or PIGEON_TMDB_API_KEY, "
                "or create ~/.pigeon_0_6/tmdb_read_token or tmdb_api_key (single line)."
            )
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode({'api_key': api_key})}"

    body = _http_get_bytes(url, timeout_s=45.0, headers=headers)
    return json.loads(body.decode("utf-8"))


def _pick_scored_best(
    scored: list[tuple[dict, tuple[int, int]]],
    *,
    query: str,
    forgiving: bool,
    media_kind: MediaKind | None = None,
    watch_provider_ids: frozenset[int] | None = None,
) -> dict | None:
    if not scored:
        return None
    if forgiving:
        best_key = max(rank for _, rank in scored)
        pool = [r for r, rank in scored if rank == best_key] if best_key[0] > 0 else [r for r, _ in scored]
        ranked = scored
    else:
        min_tier = _literal_min_acceptable_tier(query)
        strict = [(r, rk) for r, rk in scored if rk[0] >= min_tier]
        if not strict:
            return None
        best_key = max(rk for _, rk in strict)
        pool = [r for r, rk in strict if rk == best_key]
        ranked = strict
    title_pick = _pick_best_from_pool(
        pool, media_kind=media_kind, watch_provider_ids=watch_provider_ids
    )
    if _PLAYER_DURATION_S is None:
        return title_pick
    return _rerank_scored_by_trt(ranked, media_kind=media_kind, title_pick=title_pick)


def _best_with_poster_from_results(
    query: str,
    results: list,
    *,
    tv_title_must_equal_norm: str | None = None,
    forgiving: bool = True,
    kids_bias: bool = False,
    media_kind: MediaKind | None = None,
    watch_provider_ids: frozenset[int] | None = None,
) -> dict | None:
    if not isinstance(results, list) or not results:
        return None
    with_poster = [r for r in results if isinstance(r, dict) and r.get("poster_path")]
    if not with_poster:
        return None
    if tv_title_must_equal_norm:
        with_poster = [
            r
            for r in with_poster
            if any(
                _title_norm_matches_exact_tv_series_filter(tv_title_must_equal_norm, _norm_query(t))
                for t in _result_titles(r)
            )
        ]
        if not with_poster:
            return None
    # Prefer exact / whole-word title matches from the real search query; tie-break by
    # streaming-service availability, then English original_language, then TMDb popularity.
    scored = [(r, _match_rank(query, r)) for r in with_poster]
    scored = [(r, rk) for r, rk in scored if not _weak_short_acronym_match(query, r, rk)]
    scored = _apply_kids_service_result_bias(scored, kids_bias=kids_bias)
    return _pick_scored_best(
        scored,
        query=query,
        forgiving=forgiving,
        media_kind=media_kind,
        watch_provider_ids=watch_provider_ids,
    )


def _best_from_results(
    query: str,
    results: list,
    *,
    tv_title_must_equal_norm: str | None = None,
    forgiving: bool = True,
    kids_bias: bool = False,
    media_kind: MediaKind | None = None,
    watch_provider_ids: frozenset[int] | None = None,
) -> dict | None:
    """Best title match among dict results (no poster requirement); English originals preferred."""
    if not isinstance(results, list) or not results:
        return None
    items = [r for r in results if isinstance(r, dict)]
    if not items:
        return None
    if tv_title_must_equal_norm:
        items = [
            r
            for r in items
            if any(
                _title_norm_matches_exact_tv_series_filter(tv_title_must_equal_norm, _norm_query(t))
                for t in _result_titles(r)
            )
        ]
        if not items:
            return None
    scored = [(r, _match_rank(query, r)) for r in items]
    scored = [(r, rk) for r, rk in scored if not _weak_short_acronym_match(query, r, rk)]
    scored = _apply_kids_service_result_bias(scored, kids_bias=kids_bias)
    return _pick_scored_best(
        scored,
        query=query,
        forgiving=forgiving,
        media_kind=media_kind,
        watch_provider_ids=watch_provider_ids,
    )


def _tmdb_search_get(endpoint: str, query: str, *, year_param: str | None, year: int | None) -> list:
    """GET ``{endpoint}?query=…&{year_param}=…`` and return ``results`` (empty list on any failure).

    Centralizes the "request + pull out results" dance used by the four public search helpers so
    the two-pass "with year filter, then retry without" logic doesn't repeat the HTTP boilerplate.

    Always requests ``language=en-US`` so titles / default ``poster_path`` prefer English when
    TMDb has a translation — this does not filter out non-English originals.
    """
    params: dict[str, str] = {"query": query, "language": TMDB_UI_LANGUAGE}
    if year is not None and year_param:
        params[year_param] = str(int(year))
    url = f"{TMDB_API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    data = _request_json(url)
    results = data.get("results") if isinstance(data, dict) else None
    return results if isinstance(results, list) else []


def _is_english_original(item: dict) -> bool:
    return str((item or {}).get("original_language") or "").strip().lower() == TMDB_PRIMARY_ISO_639


def _english_prefer_popularity_key(item: dict) -> tuple[int, float]:
    """Tie-break: English originals first, then TMDb popularity. Never excludes non-English."""
    return (1 if _is_english_original(item) else 0, float((item or {}).get("popularity") or 0.0))


def _image_iso_639(item: dict) -> str:
    """Normalized ``iso_639_1`` (``""`` = language-neutral / missing)."""
    iso = (item or {}).get("iso_639_1")
    if iso is None:
        return ""
    return str(iso).strip().lower()


def _prefer_english_image_rows(rows: list[dict]) -> list[dict]:
    """English → language-neutral → any other language (last resort)."""
    if not rows:
        return rows
    en = [r for r in rows if _image_iso_639(r) == TMDB_PRIMARY_ISO_639]
    if en:
        return en
    neutral = [r for r in rows if _image_iso_639(r) == ""]
    if neutral:
        return neutral
    return rows


def search_movie_best_with_poster(
    query: str,
    *,
    forgiving: bool | None = None,
    rank_query: str | None = None,
    kids_bias: bool = False,
    watch_provider_ids: frozenset[int] | None = None,
) -> dict | None:
    """Return one TMDb movie dict (has poster_path) or None.

    Trailing ``(YYYY)`` on the query is peeled off and sent as ``primary_release_year`` because
    TMDb's ``query`` param does not recognize parenthetical years — leaving them in returns zero
    hits. Falls back to an unfiltered search if the year-filtered pass comes up empty, so
    slightly-off reported years (imports, re-releases) still resolve to the real title.

    ``rank_query`` (optional) scores hits against a shorter title when ``query`` was augmented
    with a streaming-service hint (e.g. search ``Secret Tunnels PBS Kids``, rank ``Secret Tunnels``).
    """
    q = query.strip()
    if not q:
        return None
    fg = tmdb_match_forgiving(override=forgiving)
    q_clean, year = split_query_and_year(q)
    rq = (rank_query or q_clean).strip() or q_clean
    rq_clean, _ = split_query_and_year(rq)
    rq_clean = rq_clean or rq
    kw = dict(
        forgiving=fg,
        kids_bias=kids_bias,
        media_kind="movie",
        watch_provider_ids=watch_provider_ids,
    )
    results = _tmdb_search_get("search/movie", q_clean, year_param="primary_release_year", year=year)
    hit = _best_with_poster_from_results(rq_clean, results, **kw)
    if hit is None and year is not None:
        results = _tmdb_search_get("search/movie", q_clean, year_param=None, year=None)
        hit = _best_with_poster_from_results(rq_clean, results, **kw)
    return hit


def search_movie_best(
    query: str,
    *,
    forgiving: bool | None = None,
    rank_query: str | None = None,
    kids_bias: bool = False,
    watch_provider_ids: frozenset[int] | None = None,
) -> dict | None:
    q = query.strip()
    if not q:
        return None
    fg = tmdb_match_forgiving(override=forgiving)
    q_clean, year = split_query_and_year(q)
    rq = (rank_query or q_clean).strip() or q_clean
    rq_clean, _ = split_query_and_year(rq)
    rq_clean = rq_clean or rq
    kw = dict(
        forgiving=fg,
        kids_bias=kids_bias,
        media_kind="movie",
        watch_provider_ids=watch_provider_ids,
    )
    results = _tmdb_search_get("search/movie", q_clean, year_param="primary_release_year", year=year)
    hit = _best_from_results(rq_clean, results, **kw)
    if hit is None and year is not None:
        results = _tmdb_search_get("search/movie", q_clean, year_param=None, year=None)
        hit = _best_from_results(rq_clean, results, **kw)
    return hit


def search_tv_best(
    query: str,
    *,
    forgiving: bool | None = None,
    rank_query: str | None = None,
    kids_bias: bool = False,
    watch_provider_ids: frozenset[int] | None = None,
) -> dict | None:
    q = query.strip()
    if not q:
        return None
    fg = tmdb_match_forgiving(override=forgiving)
    q_clean, year = split_query_and_year(q)
    rq = (rank_query or q_clean).strip() or q_clean
    rq_clean, _ = split_query_and_year(rq)
    rq_clean = rq_clean or rq
    en = _exact_tv_title_norm_for_known_series_query(rq_clean) if fg else None
    kw = dict(
        tv_title_must_equal_norm=en,
        forgiving=fg,
        kids_bias=kids_bias,
        media_kind="tv",
        watch_provider_ids=watch_provider_ids,
    )
    results = _tmdb_search_get("search/tv", q_clean, year_param="first_air_date_year", year=year)
    hit = _best_from_results(rq_clean, results, **kw)
    if hit is None and year is not None:
        results = _tmdb_search_get("search/tv", q_clean, year_param=None, year=None)
        hit = _best_from_results(rq_clean, results, **kw)
    return hit


def search_tv_best_with_poster(
    query: str,
    *,
    forgiving: bool | None = None,
    rank_query: str | None = None,
    kids_bias: bool = False,
    watch_provider_ids: frozenset[int] | None = None,
) -> dict | None:
    """Return one TMDb TV result (has poster_path) or None.

    See :func:`search_movie_best_with_poster` for the year-peel rationale; TV uses
    ``first_air_date_year`` as the filter param.
    """
    q = query.strip()
    if not q:
        return None
    fg = tmdb_match_forgiving(override=forgiving)
    q_clean, year = split_query_and_year(q)
    rq = (rank_query or q_clean).strip() or q_clean
    rq_clean, _ = split_query_and_year(rq)
    rq_clean = rq_clean or rq
    en = _exact_tv_title_norm_for_known_series_query(rq_clean) if fg else None
    kw = dict(
        tv_title_must_equal_norm=en,
        forgiving=fg,
        kids_bias=kids_bias,
        media_kind="tv",
        watch_provider_ids=watch_provider_ids,
    )
    results = _tmdb_search_get("search/tv", q_clean, year_param="first_air_date_year", year=year)
    hit = _best_with_poster_from_results(rq_clean, results, **kw)
    if hit is None and year is not None:
        results = _tmdb_search_get("search/tv", q_clean, year_param=None, year=None)
        hit = _best_with_poster_from_results(rq_clean, results, **kw)
    return hit


def _tmdb_tv_detail(tv_id: int) -> dict | None:
    try:
        data = _request_json(
            f"{TMDB_API_BASE}/tv/{int(tv_id)}?{urllib.parse.urlencode({'language': TMDB_UI_LANGUAGE})}"
        )
    except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("id") is None:
        return None
    return data


def _tmdb_tv_episode(tv_id: int, season: int, episode: int) -> dict | None:
    try:
        data = _request_json(
            f"{TMDB_API_BASE}/tv/{int(tv_id)}/season/{int(season)}/episode/{int(episode)}"
            f"?{urllib.parse.urlencode({'language': TMDB_UI_LANGUAGE})}"
        )
    except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _tmdb_movie_detail(movie_id: int) -> dict | None:
    try:
        data = _request_json(
            f"{TMDB_API_BASE}/movie/{int(movie_id)}?{urllib.parse.urlencode({'language': TMDB_UI_LANGUAGE})}"
        )
    except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("id") is None:
        return None
    return data


_KNOWN_TMDB_MOVIE_ID_BY_COMPACT_NORM: dict[str, int] = {
    "walle": 10681,
}


def _forced_tmdb_movie_id_for_disambiguated_query(q: str) -> int | None:
    """
    TMDb search often picks the wrong row when many titles share ``Taylor Swift`` tokens
    (e.g. *Journey to Fearless* over *The Eras Tour*). Map full queries to the known movie ids.
    """
    must = _short_acronym_compact_norm(q)
    if must:
        known = _KNOWN_TMDB_MOVIE_ID_BY_COMPACT_NORM.get(must)
        if known is not None:
            return known
    cn = _compact_norm_for_acronym(q)
    if cn:
        known = _KNOWN_TMDB_MOVIE_ID_BY_COMPACT_NORM.get(cn)
        if known is not None:
            return known
    n = _norm_query(q)
    if not n:
        return None
    if "taylor" not in n or "swift" not in n:
        return None
    if "eras" not in n or "tour" not in n:
        return None
    # The Final Show (2025, Vancouver) vs theatrical Eras Tour (2023)
    if "final" in n:
        return 1562010
    return 1160164


def _forced_tmdb_movie_item_for_disambiguated_query(q: str, *, require_poster: bool) -> dict | None:
    mid = _forced_tmdb_movie_id_for_disambiguated_query(q)
    if mid is None:
        return None
    detail = _tmdb_movie_detail(mid)
    if detail is None:
        return None
    if require_poster and not detail.get("poster_path"):
        return None
    return detail


def _forced_tmdb_tv_item_for_canonical_query(q: str, *, require_poster: bool) -> dict | None:
    """
    For queries that map to :data:`_SHORT_SHOW_CANONICAL_QUERIES`, return the fixed TMDb TV row from
    ``/tv/{id}`` when listed in :data:`_SHORT_SHOW_TMDB_TV_ID_BY_NORM`.

    Holiday / clip compilations for the same franchise are often **movies** on TMDb; Apple TV often
    reports them as ``Video`` so ``prefer`` becomes ``movie`` and would otherwise beat the series.
    """
    en = _exact_tv_title_norm_for_known_series_query(q)
    if en is None:
        return None
    tv_id = _SHORT_SHOW_TMDB_TV_ID_BY_NORM.get(en)
    if tv_id is None:
        return None
    detail = _tmdb_tv_detail(tv_id)
    if detail is None:
        return None
    if require_poster and not detail.get("poster_path"):
        return None
    return detail


def _service_augmented_search_queries(
    query: str,
    *,
    service_hint: str | None,
    forgiving: bool,
    service_first: bool = False,
) -> list[str]:
    """
    Ordered TMDb search strings.

    When ``service_first`` (any known streaming app), try ``Title Netflix`` / ``Title PBS Kids``
    before the bare title so the API surface leans toward that service. The suffix is also
    appended as a fallback when service-first is off.
    """
    raw = (query or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        t = s.strip()
        if not t:
            return
        key = t.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(t)

    sh = (service_hint or "").strip()
    svc_q = ""
    if sh and _norm_query(sh) and _norm_query(sh) not in _norm_query(raw):
        svc_q = f"{raw} {sh}"

    if service_first and svc_q:
        add(svc_q)
    if forgiving:
        for v in _tmdb_query_variants(raw):
            add(v)
    else:
        add(raw)
    if svc_q:
        add(svc_q)
    return out


def _search_best_media_with_poster_one(
    q: str,
    *,
    prefer: Prefer,
    forgiving: bool,
    rank_query: str | None = None,
    kids_bias: bool = False,
    watch_provider_ids: frozenset[int] | None = None,
) -> tuple[dict | None, MediaKind | None]:
    if not q:
        return None, None
    rq = (rank_query or q).strip() or q
    providers = watch_provider_ids
    if forgiving:
        en = _exact_tv_title_norm_for_known_series_query(rq)
        if en is not None:
            hit = _forced_tmdb_tv_item_for_canonical_query(rq, require_poster=True)
            if hit is None:
                hit = search_tv_best_with_poster(
                    q,
                    forgiving=True,
                    rank_query=rq,
                    kids_bias=kids_bias,
                    watch_provider_ids=providers,
                )
            if hit is not None:
                return hit, "tv"
            return None, None
    if prefer == "movie":
        m = search_movie_best_with_poster(
            q,
            forgiving=forgiving,
            rank_query=rq,
            kids_bias=kids_bias,
            watch_provider_ids=providers,
        )
        return (m, "movie") if m else (None, None)
    if prefer == "tv":
        t = search_tv_best_with_poster(
            q,
            forgiving=forgiving,
            rank_query=rq,
            kids_bias=kids_bias,
            watch_provider_ids=providers,
        )
        return (t, "tv") if t else (None, None)

    # auto: movie first. When Apple TV TRT is known, search both catalogues
    # and prefer the closer runtime (1990 It miniseries vs 2017 film vs a short parody).
    m = search_movie_best_with_poster(
        q,
        forgiving=forgiving,
        rank_query=rq,
        kids_bias=kids_bias,
        watch_provider_ids=providers,
    )
    if _PLAYER_DURATION_S is None:
        if m is not None:
            return m, "movie"
        t = search_tv_best_with_poster(
            q,
            forgiving=forgiving,
            rank_query=rq,
            kids_bias=kids_bias,
            watch_provider_ids=providers,
        )
        return (t, "tv") if t else (None, None)
    t = search_tv_best_with_poster(
        q,
        forgiving=forgiving,
        rank_query=rq,
        kids_bias=kids_bias,
        watch_provider_ids=providers,
    )
    return _prefer_duration_match(m, t)


# Series that an episode-only title last resolved to, per streaming service:
# normalized service name → (TMDb TV id, monotonic time). Lets an ambiguous episode
# title (``Baby Shower``: The Office, Superstore, SNL …) follow the show being binged.
_RECENT_EPISODE_SERIES: dict[str, tuple[int, float]] = {}
_RECENT_EPISODE_SERIES_TTL_S = 4 * 3600.0


def _recent_series_key(service: str | None) -> str:
    return _norm_query(service or "")


def _remember_episode_series(
    service: str | None, hit: tuple[dict | None, MediaKind | None]
) -> None:
    key = _recent_series_key(service)
    if not key or hit[1] != "tv" or hit[0] is None or hit[0].get("id") is None:
        return
    _RECENT_EPISODE_SERIES[key] = (int(hit[0]["id"]), time.monotonic())


def _recent_episode_series_id(service: str | None) -> int | None:
    row = _RECENT_EPISODE_SERIES.get(_recent_series_key(service))
    if row is None or time.monotonic() - row[1] > _RECENT_EPISODE_SERIES_TTL_S:
        return None
    return row[0]


def clear_recent_episode_series() -> None:
    """For tests: forget which series each service was last playing."""
    _RECENT_EPISODE_SERIES.clear()


# Set on a series hit that came from an episode title (``Employee Transfer`` → The
# Office). Its title shares no words with the query, so the literal match tier would
# be 0 and the caller would reject it as a loose match.
EPISODE_SERIES_FLAG = "_pigeon_episode_series"


def _mark_episode_series(
    hit: tuple[dict | None, MediaKind | None],
) -> tuple[dict | None, MediaKind | None]:
    if hit[0] is None:
        return hit
    return {**hit[0], EPISODE_SERIES_FLAG: True}, hit[1]


def _pick_wikidata_episode_series(
    candidates: list[dict],
    *,
    service: str | None,
    providers: frozenset[int] | None,
) -> dict | None:
    """
    One parent series for an episode title from Wikidata's candidates.

    Unambiguous → that series. Ambiguous → the series this service was just playing,
    else the only candidate listed on the service — provided every other candidate is
    known not to be (no TMDb id or a failed provider lookup could hide a second match);
    otherwise unresolved.
    """
    if len(candidates) == 1:
        return candidates[0] if candidates[0].get("name") else None
    recent = _recent_episode_series_id(service)
    if recent is not None:
        for c in candidates:
            if c.get("tmdb_tv_id") and int(c["tmdb_tv_id"]) == recent:
                return c
    if not providers:
        return None
    on_service: list[dict] = []
    for c in candidates:
        have = _tmdb_watch_provider_ids("tv", int(c["tmdb_tv_id"])) if c.get("tmdb_tv_id") else None
        if have is None:
            return None  # can't rule this one out
        if have & providers:
            on_service.append(c)
    return on_service[0] if len(on_service) == 1 else None


def _episode_title_series_fallback(
    query: str,
    *,
    require_poster: bool,
    service: str | None = None,
    providers: frozenset[int] | None = None,
) -> tuple[dict | None, MediaKind | None]:
    """
    Map an episode-only title to its parent series (system-wide, not kids-only).

    Order:
      1. Disk-cached kids/PBS episode index (same data PBS Kids uses)
      2. Local ``episode_series_hints.json`` / built-ins → TMDb TV search for that series
      3. Wikidata episode → series (Peacock / general streamers); a title shared by
         several series resolves only via the series ``service`` was just playing, or
         the only one listed on ``providers``

    Used when normal TMDb title search misses or only yields a weak title match.
    """
    q = (query or "").strip()
    if not q:
        return None, None
    try:
        from pigeon.tmdb_episode_index import resolve_kids_series_from_episode_title

        detail = resolve_kids_series_from_episode_title(q)
    except Exception:
        detail = None
    if detail is not None and detail.get("id") is not None:
        if not require_poster or detail.get("poster_path"):
            return detail, "tv"

    hinted: str | None = None
    try:
        from pigeon.episode_series_hints import series_name_for_episode_title_hint

        hinted = series_name_for_episode_title_hint(q)
    except Exception:
        hinted = None
    if not hinted:
        try:
            from pigeon.wikidata_episode import series_candidates_from_wikidata_episode_title

            wd = _pick_wikidata_episode_series(
                series_candidates_from_wikidata_episode_title(q),
                service=service,
                providers=providers,
            )
        except Exception:
            wd = None
        if wd:
            hinted = str(wd.get("name") or "") or None
            # Wikidata's TMDb id pins the exact series (The Office US vs UK).
            if wd.get("tmdb_tv_id"):
                detail = _tmdb_tv_detail(int(wd["tmdb_tv_id"]))
                if detail is not None and (not require_poster or detail.get("poster_path")):
                    return detail, "tv"
    if hinted and not is_degenerate_tmdb_query(hinted):
        if require_poster:
            hit = search_tv_best_with_poster(hinted, forgiving=True, kids_bias=False)
        else:
            hit = search_tv_best(hinted, forgiving=True, kids_bias=False)
        if hit is not None and hit.get("id") is not None:
            if not require_poster or hit.get("poster_path"):
                return hit, "tv"
    return None, None


def _episode_series_on_service_instead(
    raw: str,
    best: tuple[dict | None, MediaKind | None],
    providers: frozenset[int],
    *,
    require_poster: bool,
    service: str | None = None,
) -> tuple[dict | None, MediaKind | None] | None:
    """
    Swap a title-search hit that is **not** on the foreground service for the series an
    episode title belongs to, when that series **is** on the service.

    Peacock reports only the episode line (``Business Ethics``); TMDb title search then
    lands on an unrelated same-named film that ranks as a strong match.
    """
    if not providers or best[0] is None:
        return None
    if _service_availability_score(best[0], best[1], providers):
        return None
    ep = _episode_title_series_fallback(
        raw, require_poster=require_poster, service=service, providers=providers
    )
    if ep[0] is None or not _service_availability_score(ep[0], ep[1], providers):
        return None
    return ep


# Back-compat alias (older call sites / docs).
_kids_episode_index_series_fallback = _episode_title_series_fallback


def _tmdb_hit_is_weak_for_query(
    query: str, item: dict | None, *, require_poster: bool = False
) -> bool:
    """True when there is no hit, missing poster (if required), or match tier &lt; 4."""
    if item is None:
        return True
    if require_poster and not item.get("poster_path"):
        return True
    return _match_rank(query, item)[0] < 4


def search_best_media_with_poster(
    query: str,
    *,
    prefer: Prefer = "auto",
    forgiving: bool | None = None,
    service_hint: str | None = None,
    kids_bias: bool = False,
    app_name: str | None = None,
    app_id: str | None = None,
) -> tuple[dict | None, MediaKind | None]:
    """
    Pick one movie or TV hit with a poster.
    ``auto`` takes the best movie result first; only if none is found uses the TV catalogue.

    When ``app_name`` / ``app_id`` (or ``service_hint``) name a streaming app, search
    ``Title Service`` first and prefer rows listed on that service. Kids-primary apps
    also prefer TV and bias ranking away from adult substring matches.

    When search still fails (or only a weak hit), resolve episode-only titles via the
    episode→series index (same path PBS Kids uses) — **system-wide**, not kids-only.
    """
    fg = tmdb_match_forgiving(override=forgiving)
    raw = (query or "").strip()
    hint = (service_hint or "").strip() or None
    if hint is None and (app_name or app_id):
        hint = streaming_service_display_name(app_name, app_id)
    kids = bool(kids_bias) or is_kids_streaming_service(app_name, app_id)
    pref = prefer_media_for_streaming_service(prefer, app_name=app_name, app_id=app_id)
    providers = watch_provider_ids_for_streaming_service(
        app_name=app_name, app_id=app_id, service_hint=hint
    )
    if raw and not kids:
        mf = _forced_tmdb_movie_item_for_disambiguated_query(raw, require_poster=True)
        if _forced_movie_survives_trt(mf) is not None:
            return mf, "movie"
    variants = _service_augmented_search_queries(
        raw, service_hint=hint, forgiving=fg, service_first=_service_first_enabled(hint)
    )
    best: tuple[dict | None, MediaKind | None] = (None, None)
    for q in variants:
        hit = _search_best_media_with_poster_one(
            q,
            prefer=pref,
            forgiving=fg,
            rank_query=raw,
            kids_bias=kids,
            watch_provider_ids=providers,
        )
        if hit[0] is not None:
            best = hit
            break
    if _tmdb_hit_is_weak_for_query(raw, best[0], require_poster=True):
        ep = _episode_title_series_fallback(
            raw, require_poster=True, service=hint, providers=providers
        )
        if ep[0] is not None:
            _remember_episode_series(hint, ep)
            return _mark_episode_series(ep)
    else:
        swap = _episode_series_on_service_instead(
            raw, best, providers, require_poster=True, service=hint
        )
        if swap is not None:
            _remember_episode_series(hint, swap)
            return _mark_episode_series(swap)
    return best


def search_best_media(
    query: str,
    *,
    prefer: Prefer = "auto",
    forgiving: bool | None = None,
    service_hint: str | None = None,
    kids_bias: bool = False,
    app_name: str | None = None,
    app_id: str | None = None,
) -> tuple[dict | None, MediaKind | None]:
    """Pick one movie or TV hit; ``auto`` tries movies first, then TV if no movie match.

    The foreground streaming service leads query variants and ranks same-title hits.
    Episode-only titles fall back to the episode→series index when search misses or only
    returns a weak title alignment (system-wide; not limited to kids apps).
    """
    fg = tmdb_match_forgiving(override=forgiving)
    raw = (query or "").strip()
    hint = (service_hint or "").strip() or None
    if hint is None and (app_name or app_id):
        hint = streaming_service_display_name(app_name, app_id)
    kids = bool(kids_bias) or is_kids_streaming_service(app_name, app_id)
    pref = prefer_media_for_streaming_service(prefer, app_name=app_name, app_id=app_id)
    providers = watch_provider_ids_for_streaming_service(
        app_name=app_name, app_id=app_id, service_hint=hint
    )
    if raw and not kids:
        mf = _forced_tmdb_movie_item_for_disambiguated_query(raw, require_poster=False)
        if _forced_movie_survives_trt(mf) is not None:
            return mf, "movie"
    variants = _service_augmented_search_queries(
        raw, service_hint=hint, forgiving=fg, service_first=_service_first_enabled(hint)
    )
    best: tuple[dict | None, MediaKind | None] = (None, None)
    for q in variants:
        hit = _search_best_media_one(
            q,
            prefer=pref,
            forgiving=fg,
            rank_query=raw,
            kids_bias=kids,
            watch_provider_ids=providers,
        )
        if hit[0] is not None:
            best = hit
            break
    if _tmdb_hit_is_weak_for_query(raw, best[0]):
        ep = _episode_title_series_fallback(
            raw, require_poster=False, service=hint, providers=providers
        )
        if ep[0] is not None:
            _remember_episode_series(hint, ep)
            return _mark_episode_series(ep)
    else:
        swap = _episode_series_on_service_instead(
            raw, best, providers, require_poster=False, service=hint
        )
        if swap is not None:
            _remember_episode_series(hint, swap)
            return _mark_episode_series(swap)
    return best


def _search_best_media_one(
    q: str,
    *,
    prefer: Prefer,
    forgiving: bool,
    rank_query: str | None = None,
    kids_bias: bool = False,
    watch_provider_ids: frozenset[int] | None = None,
) -> tuple[dict | None, MediaKind | None]:
    if not q:
        return None, None
    rq = (rank_query or q).strip() or q
    providers = watch_provider_ids
    if forgiving:
        en = _exact_tv_title_norm_for_known_series_query(rq)
        if en is not None:
            hit = _forced_tmdb_tv_item_for_canonical_query(rq, require_poster=False)
            if hit is None:
                hit = search_tv_best(
                    q,
                    forgiving=True,
                    rank_query=rq,
                    kids_bias=kids_bias,
                    watch_provider_ids=providers,
                )
            if hit is not None:
                return hit, "tv"
            return None, None
    if prefer == "movie":
        m = search_movie_best(
            q,
            forgiving=forgiving,
            rank_query=rq,
            kids_bias=kids_bias,
            watch_provider_ids=providers,
        )
        return (m, "movie") if m else (None, None)
    if prefer == "tv":
        t = search_tv_best(
            q,
            forgiving=forgiving,
            rank_query=rq,
            kids_bias=kids_bias,
            watch_provider_ids=providers,
        )
        return (t, "tv") if t else (None, None)

    # auto: movie catalogue first, then TV when no film hit (same policy as with-poster path).
    # Known Apple TV TRT searches both so a long 1990 miniseries can beat a short parody.
    m = search_movie_best(
        q,
        forgiving=forgiving,
        rank_query=rq,
        kids_bias=kids_bias,
        watch_provider_ids=providers,
    )
    if _PLAYER_DURATION_S is None:
        if m is not None:
            return m, "movie"
        t = search_tv_best(
            q,
            forgiving=forgiving,
            rank_query=rq,
            kids_bias=kids_bias,
            watch_provider_ids=providers,
        )
        return (t, "tv") if t else (None, None)
    t = search_tv_best(
        q,
        forgiving=forgiving,
        rank_query=rq,
        kids_bias=kids_bias,
        watch_provider_ids=providers,
    )
    return _prefer_duration_match(m, t)


def fetch_media_images(kind: MediaKind, media_id: int) -> dict:
    """Fetch image lists in all languages; callers prefer English in code.

    Do not pass ``language=en-US`` here — TMDb then returns only English-tagged images
    and drops Spanish-only posters needed as last-resort fallbacks.
    """
    if kind == "movie":
        url = f"{TMDB_API_BASE}/movie/{int(media_id)}/images"
    else:
        url = f"{TMDB_API_BASE}/tv/{int(media_id)}/images"
    return _request_json(url)


def _character_from_cast_entry(entry: dict) -> str:
    roles = entry.get("roles")
    if isinstance(roles, list) and roles:
        chars: list[str] = []
        for role in roles:
            if not isinstance(role, dict):
                continue
            ch = str(role.get("character") or "").strip()
            if ch:
                chars.append(ch)
        if chars:
            return chars[0]
    return str(entry.get("character") or "").strip()


def fetch_top_cast(kind: MediaKind, media_id: int, *, limit: int = 9) -> list[tuple[str, str]]:
    """
    Top billed cast as ``(actor_name, character_name)``.

    Movies use ``/credits``. TV prefers ``/aggregate_credits``, then ``/credits``.
    """
    lim = max(0, int(limit))
    if lim <= 0:
        return []
    mid = int(media_id)
    cast_rows: list[dict] = []
    if kind == "tv":
        try:
            data = _request_json(f"{TMDB_API_BASE}/tv/{mid}/aggregate_credits")
            rows = data.get("cast") or []
            if isinstance(rows, list):
                cast_rows = [r for r in rows if isinstance(r, dict)]
        except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
            cast_rows = []
        if not cast_rows:
            try:
                data = _request_json(f"{TMDB_API_BASE}/tv/{mid}/credits")
                rows = data.get("cast") or []
                if isinstance(rows, list):
                    cast_rows = [r for r in rows if isinstance(r, dict)]
            except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
                cast_rows = []
    else:
        try:
            data = _request_json(f"{TMDB_API_BASE}/movie/{mid}/credits")
            rows = data.get("cast") or []
            if isinstance(rows, list):
                cast_rows = [r for r in rows if isinstance(r, dict)]
        except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
            cast_rows = []

    def _order_key(row: dict) -> tuple[int, int]:
        try:
            order = int(row.get("order") if row.get("order") is not None else 10_000)
        except (TypeError, ValueError):
            order = 10_000
        roles = row.get("roles")
        role_n = len(roles) if isinstance(roles, list) else 0
        return (order, -role_n)

    cast_rows.sort(key=_order_key)
    out: list[tuple[str, str]] = []
    for row in cast_rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        character = _character_from_cast_entry(row)
        out.append((name, character))
        if len(out) >= lim:
            break
    return out


def _logo_path_from_images(images: dict) -> str | None:
    logos = images.get("logos") or []
    if not logos:
        return None

    # Always prefer English logos. If none exist, treat as no logo (do not fall back).
    en = [l for l in logos if _image_iso_639(l) == TMDB_PRIMARY_ISO_639]
    if not en:
        return None
    best = max(en, key=lambda l: float((l or {}).get("vote_average") or 0.0))
    return (best or {}).get("file_path")  # type: ignore[return-value]


def _backdrop_is_no_language(item: dict) -> bool:
    """TMDb uses ``iso_639_1: null`` (and sometimes missing/empty) for language-neutral backdrops."""
    iso = item.get("iso_639_1")
    if iso is None:
        return True
    if isinstance(iso, str) and iso.strip() == "":
        return True
    return False


def _random_backdrop_path(images: dict) -> str | None:
    backs = images.get("backdrops") or []
    neutral = [
        b
        for b in backs
        if isinstance(b, dict) and _backdrop_is_no_language(b) and b.get("file_path")
    ]
    if not neutral:
        return None
    choice = random.choice(neutral)
    return choice.get("file_path")


def _poster_path_from_item_or_images(item: dict, images: dict) -> str | None:
    """Prefer English poster art; fall back to neutral, then any language, then ``poster_path``.

    ``item.poster_path`` is TMDb's default for the request language and can still be a
    non-English asset when that is the only upload — use the images list first so an
    English alternate wins when it exists.
    """
    posters = images.get("posters") or []
    rows: list[dict] = []
    if isinstance(posters, list):
        rows = [r for r in posters if isinstance(r, dict) and r.get("file_path")]
    if rows:
        pool = _prefer_english_image_rows(rows)
        best = max(pool, key=lambda r: float((r or {}).get("vote_average") or 0.0))
        path = str((best or {}).get("file_path") or "").strip()
        if path:
            return path
    p = str(item.get("poster_path") or "").strip()
    return p or None


_LOGO_OWNERS_NAME = "tmdb_logo_owners.json"


def _logo_owners_path() -> Path:
    # State dir, not pigeonTMDB_TT: that folder is trimmed by file count.
    return _pigeon_state_dir() / _LOGO_OWNERS_NAME


def _load_logo_owners() -> dict[str, str]:
    try:
        data = json.loads(_logo_owners_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _save_logo_owners(owners: dict[str, str]) -> None:
    try:
        p = _logo_owners_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(owners, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def _drop_cached_logos(tk: str) -> bool:
    """Delete every cached logo filed under ``tk``; True if one existed."""
    dropped = False
    for asset in (ASSET_LOGO_EN, ASSET_LOGO):
        while (old := find_cached_reformatted_asset(tk, asset)) is not None:
            try:
                old.unlink()
            except OSError:
                break
            dropped = True
    if dropped:
        forget_recent_asset_lookups()
    return dropped


def _maybe_delete_pulled(path: Path) -> None:
    if pulled_path_is_under_pulled_dir(path) and auto_delete_pulled_media():
        try:
            path.unlink()
        except OSError:
            pass


def _display_title(item: dict, kind: MediaKind) -> str:
    if kind == "movie":
        return str(item.get("title") or item.get("original_title") or "movie")
    return str(item.get("name") or item.get("original_name") or "TV")


def download_poster_to_pulled(item: dict, kind: MediaKind) -> tuple[bool, str, Path | None]:
    """
    Save poster under pigeonPulledMedia as ``tmdb_m_<id>`` or ``tmdb_tv_<id>`` (IDs differ by media type).
    """
    mid = item.get("id")
    ppath = item.get("poster_path")
    title = _display_title(item, kind)
    if mid is None or not ppath:
        return False, "TMDb result missing id or poster_path.", None
    ext = Path(str(ppath)).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    tag = "m" if kind == "movie" else "tv"
    pulled = pigeon_pulled_media_dir()
    dest = pulled / f"tmdb_{tag}_{int(mid)}{ext}"
    image_url = f"{IMG_BASE}{ppath}"
    try:
        _download_binary(image_url, dest)
    except urllib.error.HTTPError as e:
        return False, f"Poster download failed ({e.code}): {e.reason}", None
    except urllib.error.URLError as e:
        return False, f"Poster download failed: {e.reason}", None
    except OSError as e:
        return False, f"Could not save poster: {e}", None
    kind_label = "movie" if kind == "movie" else "TV"
    return True, f"{title} ({kind_label}) → {dest.name}", dest


def download_logo_to_pulled(item: dict, kind: MediaKind, file_path: str) -> tuple[bool, str, Path | None]:
    mid = item.get("id")
    if mid is None or not file_path:
        return False, "TMDb logo path missing.", None
    ext = Path(str(file_path)).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".svg"):
        ext = ".png"
    tag = "m" if kind == "movie" else "tv"
    dest = pigeon_pulled_media_dir() / f"tmdb_logo_{tag}_{int(mid)}{ext}"
    image_url = f"{IMG_LOGO_BASE}{file_path}"
    try:
        _download_binary(image_url, dest)
    except urllib.error.HTTPError as e:
        return False, f"Logo download failed ({e.code}): {e.reason}", None
    except urllib.error.URLError as e:
        return False, f"Logo download failed: {e.reason}", None
    except OSError as e:
        return False, f"Could not save logo: {e}", None
    return True, dest.name, dest


def download_backdrop_to_pulled(item: dict, kind: MediaKind, file_path: str) -> tuple[bool, str, Path | None]:
    mid = item.get("id")
    if mid is None or not file_path:
        return False, "TMDb backdrop path missing.", None
    ext = Path(str(file_path)).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    tag = "m" if kind == "movie" else "tv"
    rand = secrets.token_hex(4)
    dest = pigeon_pulled_media_dir() / f"tmdb_bd_{tag}_{int(mid)}_{rand}{ext}"
    image_url = f"{IMG_BACKDROP_BASE}{file_path}"
    try:
        _download_binary(image_url, dest)
    except urllib.error.HTTPError as e:
        return False, f"Backdrop download failed ({e.code}): {e.reason}", None
    except urllib.error.URLError as e:
        return False, f"Backdrop download failed: {e.reason}", None
    except OSError as e:
        return False, f"Could not save backdrop: {e}", None
    return True, dest.name, dest


def _resolve_preferred_poster_path(item: dict, kind: MediaKind) -> str | None:
    """English-first poster path for a search/detail hit (images when available)."""
    try:
        images = fetch_media_images(kind, int(item["id"]))
    except (
        RuntimeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
        json.JSONDecodeError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ):
        images = {}
    return _poster_path_from_item_or_images(item, images if isinstance(images, dict) else {})


def fetch_tmdb_poster_to_pulled(
    query: str,
    *,
    prefer: Prefer = "auto",
    forgiving: bool | None = None,
    app_name: str | None = None,
    app_id: str | None = None,
) -> tuple[bool, str, Path | None]:
    """Search TMDb (movie and/or TV) and download best-match poster to pigeonPulledMedia."""
    fg = tmdb_match_forgiving(override=forgiving)
    try:
        item, kind = search_best_media_with_poster(
            query,
            prefer=prefer,
            forgiving=forgiving,
            app_name=app_name,
            app_id=app_id,
        )
    except RuntimeError as e:
        return False, str(e), None
    except urllib.error.HTTPError as e:
        return False, f"TMDb API error ({e.code}): {e.reason}", None
    except urllib.error.URLError as e:
        return False, f"TMDb network error: {e.reason}", None
    except (json.JSONDecodeError, OSError, ValueError) as e:
        return False, str(e), None
    if item is None or kind is None:
        q0 = query.strip()
        variants = _tmdb_query_variants(q0) if fg else ([q0] if q0 else [])
        tried_line = (
            "Variants tried: " + ", ".join(repr(x) for x in variants) + "\n"
            if len(variants) > 1
            else ""
        )
        return (
            False,
            "No movie or TV show found with a poster for that search.\n\n"
            f"Searched: {q0!r}\n{tried_line}\n"
            "Tips: In the command bar use tv Your Show or movie Your Film; use the series or "
            "film title only. If the string included an app, episode name, or a colon "
            "(Show: guest), Pigeon already tried shortened variants.",
            None,
        )
    pp = _resolve_preferred_poster_path(item, kind)
    if pp:
        item = {**item, "poster_path": pp}
    ok_p, msg_p, path_p = download_poster_to_pulled(item, kind)
    if ok_p:
        trim_pulled_media_dir()
    return ok_p, msg_p, path_p


# Titles the user picked by hand (companion app). Keyed by normalized search
# query; consulted by :func:`apply_tmdb_movie_query` before searching, so the
# chosen TMDb id wins over whatever the text search would rank first.
_FORCED_PICKS: dict[str, tuple[str, int]] = {}


def _forced_key(query: str) -> str:
    return _norm_query(refine_tmdb_search_query(query) or query or "")


def set_forced_pick(kind: str, tmdb_id: int, *queries: str) -> None:
    """Force ``kind``/``tmdb_id`` whenever one of ``queries`` is searched."""
    if kind not in ("movie", "tv") or int(tmdb_id) <= 0:
        raise ValueError("kind must be movie|tv and tmdb_id positive")
    for q in queries:
        for key in {_norm_query(q or ""), _forced_key(q or "")}:
            if key:
                _FORCED_PICKS[key] = (kind, int(tmdb_id))


def clear_forced_picks() -> None:
    _FORCED_PICKS.clear()


def _forced_pick_item(query: str) -> tuple[dict | None, MediaKind | None]:
    hit = _FORCED_PICKS.get(_norm_query(query or "")) or _FORCED_PICKS.get(_forced_key(query))
    if hit is None:
        return None, None
    kind, tmdb_id = hit
    detail = _tmdb_movie_detail(tmdb_id) if kind == "movie" else _tmdb_tv_detail(tmdb_id)
    if not isinstance(detail, dict) or not detail.get("id"):
        return None, None
    _trace_fetch(forced_pick=True)
    return detail, kind  # type: ignore[return-value]


def apply_tmdb_movie_query(
    query: str,
    *,
    prefer: Prefer = "auto",
    forgiving: bool | None = None,
    app_name: str | None = None,
    app_id: str | None = None,
    service_hint: str | None = None,
    player_duration_s: float | None = None,
) -> tuple[bool, str, np.ndarray | None, int]:
    """
    Search TMDb, prefer cached logo when present; pull missing assets and cache as
    ``{Title}_{Logo|Backdrop}`` in pigeonReFormattedMedia.

    Always picks a **random** backdrop from TMDb image results (not served from cache).

    ``app_name`` / ``app_id`` (pyatv) are part of identification for every streaming
    app: search ``Title Service`` first, prefer titles listed on that service, and
    (for kids-primary apps) prefer TV and demote adult substring hits.

    ``player_duration_s`` is Apple TV ``total_time`` (seconds). When set, TMDb hits
    whose runtime is far from that length are rejected, and movie vs TV ties prefer
    the closer TRT.

    Returns ``(ok, message, backdrop_master_bgr_or_none, match_tier)`` where master is BGR
    scaled to uniform design canvas height for the compositor, or None if no backdrop could be
    loaded. ``match_tier`` is the :func:`_match_rank` tier (0 when no hit).
    """
    from pigeon.display_confidence import parse_duration_seconds, trt_confidence

    q = query.strip()
    _LAST_FETCH_TRACE.clear()
    _trace_fetch(query=q, prefer_in=prefer, forgiving=forgiving)
    if not q:
        _trace_fetch(outcome="empty")
        return False, "Empty search.", None, 0
    # Protocol: keep ORIGINAL as transient staging only; clear leftovers before each new TMDB pull.
    try:
        ensure_tmdb_media_dirs()
        purge_directory_contents(pigeon_pulled_media_dir())
    except Exception:
        pass
    fg = tmdb_match_forgiving(override=forgiving)
    hint = (service_hint or "").strip() or streaming_service_display_name(app_name, app_id)
    kids = is_kids_streaming_service(app_name, app_id)
    pref = prefer_media_for_streaming_service(prefer, app_name=app_name, app_id=app_id)
    service_first = _service_first_enabled(hint)
    duration = parse_duration_seconds(player_duration_s)
    remember_trt_comparison(player_s=duration, tmdb_s=None, similarity=None)
    _trace_fetch(
        service_hint=hint,
        kids_bias=kids,
        prefer=pref,
        forgiving_mode=fg,
        trt_player_s=duration,
    )

    try:
        with player_duration_hint(duration):
            item, kind = _forced_pick_item(q)
            if item is None:
                item, kind = search_best_media(
                    q,
                    prefer=pref,
                    forgiving=forgiving,
                    service_hint=hint,
                    kids_bias=kids,
                    app_name=app_name,
                    app_id=app_id,
                )
            if item is None and not fg:
                variants = _service_augmented_search_queries(
                    q, service_hint=hint, forgiving=True, service_first=service_first
                )
                for v in variants:
                    if v.strip().casefold() == q.strip().casefold():
                        continue
                    item, kind = search_best_media(
                        v,
                        prefer=pref,
                        forgiving=False,
                        service_hint=None,
                        kids_bias=kids,
                        app_name=app_name,
                        app_id=app_id,
                    )
                    if item is not None:
                        break
                if item is None:
                    for v in variants:
                        item, kind = search_best_media(
                            v,
                            prefer=pref,
                            forgiving=True,
                            service_hint=None,
                            kids_bias=kids,
                            app_name=app_name,
                            app_id=app_id,
                        )
                        if item is not None:
                            break
    except RuntimeError as e:
        _trace_fetch(outcome="error", failure=str(e))
        return False, str(e), None, 0
    except urllib.error.HTTPError as e:
        _trace_fetch(outcome="error", failure=f"TMDb API error ({e.code}): {e.reason}")
        return False, f"TMDb API error ({e.code}): {e.reason}", None, 0
    except urllib.error.URLError as e:
        _trace_fetch(outcome="error", failure=f"TMDb network error: {e.reason}")
        return False, f"TMDb network error: {e.reason}", None, 0
    except (json.JSONDecodeError, OSError, ValueError) as e:
        _trace_fetch(outcome="error", failure=str(e))
        return False, str(e), None, 0

    if item is None or kind is None:
        variants = _service_augmented_search_queries(
            q, service_hint=hint, forgiving=fg, service_first=service_first
        )
        _trace_fetch(
            outcome="no_match",
            failure="No movie or TV show found",
            variants=list(variants),
        )
        tried_line = (
            "Variants tried: " + ", ".join(repr(x) for x in variants) + "\n"
            if len(variants) > 1
            else ""
        )
        return (
            False,
            "No movie or TV show found for that search.\n\n"
            f"Searched: {q!r}\n{tried_line}\n"
            "Tips: Use tv Your Show or movie Your Film in the command bar; try the main title "
            "only. Apple TV sometimes sends a label TMDb does not recognize (episode titles, apps, "
            "Show: guest lines, or extras). Check spelling and network — API errors show a different message.",
            None,
            0,
        )

    item = enrich_item_runtime(item, kind)
    runtime_opts = tmdb_runtime_seconds_options(item)
    if runtime_opts:
        if duration is None:
            tmdb_s = runtime_opts[0]
        else:
            from pigeon.display_confidence import trt_similarity

            tmdb_s = max(runtime_opts, key=lambda sec: trt_similarity(duration, sec))
    else:
        tmdb_s = None
    similarity = trt_confidence(duration, runtime_opts)
    remember_trt_comparison(player_s=duration, tmdb_s=tmdb_s, similarity=similarity)
    _trace_fetch(
        kind=kind,
        tmdb_id=item.get("id"),
        tmdb_title=_display_title(item, kind),
        tmdb_year=str(item.get("release_date") or item.get("first_air_date") or "")[:4],
        trt_tmdb_s=tmdb_s,
        trt_similarity=similarity,
    )
    if duration is not None and _trt_rejects(duration, item, kind):
        _trace_fetch(
            outcome="runtime_reject",
            failure="TMDb runtime does not match the Apple TV duration",
        )
        return (
            False,
            "TMDb runtime does not match the Apple TV duration.\n\n"
            f"Searched: {q!r}\n"
            "The matched title is much shorter or longer than what is playing.",
            None,
            0,
        )

    match_tier = int(_match_rank(q, item)[0])
    canon_q = canonical_tv_display_name_for_search_query(q)
    if canon_q:
        # ``SNL`` shares no words with ``Saturday Night Live``; rank the known full name too.
        match_tier = max(match_tier, int(_match_rank(canon_q, item)[0]))
    if item.get(EPISODE_SERIES_FLAG):
        # The episode → series lookup vouched for this show; trust it like an exact title.
        match_tier = 5

    display_title = _display_title(item, kind)
    # TMDb may classify an SNL sketch row as a **movie**; still normalize the on-screen title.
    swap = canonical_tv_title_if_sketch_show_compound(display_title)
    if swap:
        display_title = swap
    if kind == "tv":
        canon = canonical_tv_display_name_for_search_query(q)
        if canon:
            display_title = canon
    tk = title_key(display_title)
    parts: list[str] = [display_title]
    _trace_fetch(match_tier=match_tier, display_title=display_title, title_key=tk)

    # --- Cast (enough for two 3-up strips: zone4 + zone5) ---
    try:
        cast = fetch_top_cast(kind, int(item["id"]), limit=9)
        cache_tmdb_cast_for_title(tk, cast)
        if cast:
            parts.append(f"cast: {len(cast)}")
        else:
            parts.append("cast: none")
    except Exception:
        clear_cached_tmdb_cast(tk)
        parts.append("cast: fail")

    # --- Images bundle (logo + random backdrop) ---
    backdrop_master: np.ndarray | None = None
    try:
        images = fetch_media_images(kind, int(item["id"]))
    except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
        images = {}

    # --- Poster: routinely pull/cache alongside TT + BD ---
    pp = _poster_path_from_item_or_images(item, images)
    _trace_fetch(
        poster_path=pp,
        logo_path=_logo_path_from_images(images),
        logo_count=len(images.get("logos") or []),
        backdrop_count=len(images.get("backdrops") or []),
        poster_ok=False,
        logo_ok=False,
        backdrop_ok=False,
    )
    if not pp:
        parts.append("poster: none")
    else:
        ok_p, msg_p, p_pulled = download_poster_to_pulled(
            {"id": item.get("id"), "poster_path": pp, "title": display_title, "name": display_title},
            kind,
        )
        if ok_p and p_pulled is not None:
            try:
                copy_pulled_to_reformatted(p_pulled, tk, ASSET_POSTER_ART)
            except OSError as e:
                parts.append(f"poster: cache failed ({e})")
            else:
                parts.append(f"poster: {p_pulled.name}")
                _trace_fetch(poster_ok=True)
            _maybe_delete_pulled(p_pulled)
        else:
            parts.append(f"poster: download failed ({msg_p})")

    # --- Logo (English-only; cache first) ---
    # The cache is keyed by title, so two TMDb items with the same title
    # (It 1990 miniseries vs It 2017 film) share ``It_LogoEn``. Only reuse a
    # cached logo that this TMDb item owns; otherwise drop it and re-pull.
    lp = _logo_path_from_images(images)
    owner = f"{kind}:{item.get('id')}:{lp}"
    owners = _load_logo_owners()
    logo_cached = find_cached_reformatted_asset(tk, ASSET_LOGO_EN)
    if logo_cached is not None and lp and owners.get(tk) == owner:
        parts.append("logo: en cache")
        _trace_fetch(logo_ok=True, logo_source="cache", logo_file=str(logo_cached))
    else:
        if _drop_cached_logos(tk):
            parts.append("logo: dropped stale cache")
        owners.pop(tk, None)
        if lp:
            ok_l, _msg_l, logo_path = download_logo_to_pulled(item, kind, lp)
            if ok_l and logo_path is not None:
                try:
                    copy_pulled_to_reformatted(logo_path, tk, ASSET_LOGO_EN)
                    parts.append(f"logo: {logo_path.name}")
                    owners[tk] = owner
                    _trace_fetch(logo_ok=True, logo_source="download")
                except OSError as e:
                    parts.append(f"logo: copy failed ({e})")
                _maybe_delete_pulled(logo_path)
            else:
                parts.append("logo: skip")
        else:
            parts.append("logo: none")
        _save_logo_owners(owners)

    # --- Backdrop: always random from API ---
    bp = _random_backdrop_path(images)
    _trace_fetch(backdrop_path=bp)
    if not bp:
        parts.append("backdrop: none")
    else:
        ok_b, msg_b, bd_pulled = download_backdrop_to_pulled(item, kind, bp)
        if ok_b and bd_pulled is not None:
            try:
                copy_pulled_to_reformatted(bd_pulled, tk, ASSET_BACKDROP)
            except OSError as e:
                parts.append(f"backdrop: reformatted copy failed ({e})")
            else:
                parts.append(f"backdrop: {bd_pulled.name}")
            backdrop_master = backdrop_master_bgr_from_file(bd_pulled)
            _trace_fetch(backdrop_ok=backdrop_master is not None)
            _maybe_delete_pulled(bd_pulled)
        else:
            parts.append(f"backdrop: download failed ({msg_b})")

    summary = " | ".join(parts)
    trim_pulled_media_dir()
    _trace_fetch(outcome="match", summary=summary)
    # Prefix title_key + display_title so the UI can render a text fallback when no English logo exists.
    return True, f"{tk}::{display_title}::{summary}", backdrop_master, match_tier
