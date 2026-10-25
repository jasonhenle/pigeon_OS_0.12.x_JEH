"""
Streaming-service rules for TMDb matching.

Display-name cleanup for streaming apps, kids-service detection and the movie/TV
preference it implies, kids-genre result bias, and the static watch-provider id table
with its lookup. Pure rules over strings and result dicts; the network call that fetches
a title's providers stays in ``tmdb_poster``.

``pigeon.tmdb_poster`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import re
from typing import Literal

from pigeon.tmdb_query import _norm_query, is_degenerate_tmdb_query


Prefer = Literal["auto", "movie", "tv"]


# TMDb genre ids used to keep kids-app matches on age-appropriate rows.
# 16=Animation, 10751=Family, 10762=Kids (TV).
_KIDS_GENRE_IDS = frozenset({16, 10751, 10762})


# Normalized app / bundle needles for kids-only (or kids-primary) streaming apps.
# When these match, TMDb search prefers TV and demotes adult substring hits
# (e.g. PBS Kids title "Secret Tunnels" must not become "Hitler's Secret Tunnels").
_KIDS_STREAMING_APP_NEEDLES: tuple[str, ...] = (
    "pbs kids",
    "pbskids",
    "nick jr",
    "nickjr",
    "noggin",
    "disney junior",
    "disneyjunior",
)


_KIDS_STREAMING_BUNDLE_NEEDLES: tuple[str, ...] = (
    "pbskids",
    "pbs.kids",
    "nickjr",
    "noggin",
    "disneyjunior",
)


def streaming_service_display_name(
    app_name: str | None = None, app_id: str | None = None
) -> str | None:
    """
    Human streaming-app label from pyatv ``app_name`` / bundle ``app_id`` (e.g. ``PBS Kids``).

    Uses :func:`pigeon.streaming_service_badges.resolve_streaming_badge_media` so badge rules
    and TMDb bias share one mapping. Returns ``None`` when nothing useful is known.
    """
    an = str(app_name or "").strip()
    aid = str(app_id or "").strip()
    if not an and not aid:
        return None
    try:
        from pigeon.streaming_service_badges import resolve_streaming_badge_media

        _rel, display = resolve_streaming_badge_media(
            ".", app_name=an, app_id=aid
        )
    except Exception:
        display = an or ""
    d = str(display or "").strip()
    if not d or d.casefold() == "playing":
        d = an
    d = d.strip()
    if not d or is_degenerate_tmdb_query(d):
        # Degenerate alone is fine as a *hint* appended to a real title (PBS Kids, Netflix…).
        # Only reject empty / trivial.
        if not d or len(d) < 2:
            return None
    return d


def is_kids_streaming_service(
    app_name: str | None = None, app_id: str | None = None
) -> bool:
    """True when the foreground app is a kids-primary service (PBS Kids, Nick Jr, …)."""
    an = _norm_query(str(app_name or ""))
    bid = str(app_id or "").strip().lower()
    for needle in _KIDS_STREAMING_APP_NEEDLES:
        if needle in an:
            return True
    # Bare "pbs" app name / bundle (badge maps PBS → PBS Kids).
    if an == "pbs" or an.endswith(" pbs") or an.startswith("pbs "):
        return True
    for needle in _KIDS_STREAMING_BUNDLE_NEEDLES:
        if needle in bid:
            return True
    if "pbs" in bid and "kids" in bid:
        return True
    # Bundle fragment used by streaming_service_badges for PBS Kids.
    if bid and "pbs" in bid and "disney" not in bid and "passport" not in bid:
        # ``("pbs", None, …)`` badge rule — treat generic PBS apps as kids-leaning on tvOS.
        if re.search(r"(^|[._-])pbs([._-]|$)", bid):
            return True
    return False


def prefer_media_for_streaming_service(
    prefer: Prefer | str,
    *,
    app_name: str | None = None,
    app_id: str | None = None,
) -> Prefer:
    """
    When ``prefer`` is ``auto``, bump kids-primary apps to ``tv``.

    Prevents movie-first ``auto`` from winning adult documentaries that merely contain
    the same short title tokens (PBS Kids ``Secret Tunnels`` → movie *Hitler's Secret Tunnels*).
    """
    p = str(prefer or "auto").strip().lower()
    if p not in ("auto", "movie", "tv"):
        p = "auto"
    if p == "auto" and is_kids_streaming_service(app_name, app_id):
        return "tv"
    return p  # type: ignore[return-value]


# TMDb / JustWatch watch-provider ids (US catalog). Keys are ``_norm_query`` form
# (``Disney+`` → ``disney``, ``Paramount+`` → ``paramount``).
_WATCH_PROVIDER_IDS_BY_NORM: dict[str, tuple[int, ...]] = {
    "netflix": (8,),
    "disney": (337,),
    "disney plus": (337,),
    "hulu": (15,),
    "prime video": (9, 119),
    "amazon prime video": (9, 119),
    "amazon video": (9, 10, 119),
    "amazon prime": (9, 119),
    "max": (1899, 384),
    "hbo max": (384, 1899),
    "hbomax": (384, 1899),
    "peacock": (386, 387),
    "peacock premium": (387, 386),
    "paramount": (531,),
    "paramount plus": (531,),
    "apple tv": (350, 2),
    "apple tv plus": (350,),
    "youtube": (192,),
    "discovery": (524,),
    "discovery plus": (524,),
    "pbs": (209,),
    "pbs kids": (209, 293),
    "pbskids": (209, 293),
    "shudder": (99,),
}


def _service_first_enabled(service_hint: str | None) -> bool:
    """True when a known streaming app should lead TMDb queries (PBS Kids protocol, all services)."""
    sh = (service_hint or "").strip()
    return bool(sh) and bool(_norm_query(sh))


def watch_provider_ids_for_streaming_service(
    app_name: str | None = None,
    app_id: str | None = None,
    service_hint: str | None = None,
) -> frozenset[int]:
    """TMDb watch-provider ids for the foreground app, or empty when unknown."""
    labels: list[str] = []
    seen: set[str] = set()

    def add_label(raw: str | None) -> None:
        n = _norm_query(str(raw or ""))
        if not n or n in seen:
            return
        seen.add(n)
        labels.append(n)

    add_label(service_hint)
    add_label(app_name)
    add_label(streaming_service_display_name(app_name, app_id))
    ids: set[int] = set()
    for n in labels:
        hit = _WATCH_PROVIDER_IDS_BY_NORM.get(n)
        if hit:
            ids.update(hit)
    return frozenset(ids)


def _item_has_kids_genre(item: dict) -> bool:
    ids = item.get("genre_ids")
    if not isinstance(ids, list):
        return False
    for g in ids:
        try:
            if int(g) in _KIDS_GENRE_IDS:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _apply_kids_service_result_bias(
    scored: list[tuple[dict, tuple[int, int]]],
    *,
    kids_bias: bool,
) -> list[tuple[dict, tuple[int, int]]]:
    """
    For kids streaming apps: keep exact title hits and kids/family/animation genres;
    drop loose adult substring matches (tier &lt; 5 without kids genres).

    An empty result means “no acceptable kids match for this query” — callers try the
    service-augmented variant or report no match rather than falling back to adult hits.
    """
    if not kids_bias or not scored:
        return scored
    return [
        (r, rk)
        for r, rk in scored
        if rk[0] >= 5 or _item_has_kids_genre(r)
    ]
