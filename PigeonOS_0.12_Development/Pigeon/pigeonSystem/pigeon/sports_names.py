"""Shorter team names for tight spots: abbreviate the city, keep the nickname.

``Philadelphia Eagles`` → ``PHI Eagles``, ``Los Angeles Rams`` → ``LA Rams``,
``St. Louis Blues`` → ``STL Blues``. Only names of the pro teams Pigeon knows
(:mod:`pigeon.sports_teams`) are split this way; NCAA names are school names
with no nickname, so they are left alone.

:func:`fit_name` tries the full name, then the short-city one, then the
nickname alone, then cuts with "…".
"""

from __future__ import annotations

from functools import lru_cache
from typing import Callable

# Nicknames longer than one word (everything else is the last word).
_MULTI_WORD_NICKNAMES = (
    "Red Sox",
    "White Sox",
    "Blue Jays",
    "Trail Blazers",
    "Maple Leafs",
    "Red Wings",
    "Blue Jackets",
    "Golden Knights",
)

# Cities whose usual short form is not the first three letters / initials.
_CITY_CODES = {
    "Brooklyn": "BKN",
    "Calgary": "CGY",
    "Florida": "FLA",
    "Golden State": "GS",
    "Jacksonville": "JAX",
    "Montreal": "MTL",
    "Nashville": "NSH",
    "Oklahoma City": "OKC",
    "Phoenix": "PHX",
    "St. Louis": "STL",
    "Washington": "WSH",
    "Winnipeg": "WPG",
}

_PRO_LEAGUES = ("4391", "4424", "4387", "4516", "4380")


@lru_cache(maxsize=1)
def _pro_names() -> frozenset[str]:
    from pigeon.sports_teams import teams

    return frozenset(t.name.lower() for lid in _PRO_LEAGUES for t in teams(lid))


def split_team(name: str) -> tuple[str, str] | None:
    """(city, nickname) for a known pro team; None otherwise."""
    name = " ".join(str(name or "").split())
    if name.lower() not in _pro_names():
        return None
    for nick in _MULTI_WORD_NICKNAMES:
        if name.endswith(" " + nick):
            return name[: -len(nick) - 1], nick
    city, _, nick = name.rpartition(" ")
    return (city, nick) if city else None


def city_code(city: str) -> str:
    if city in _CITY_CODES:
        return _CITY_CODES[city]
    words = city.split()
    if len(words) > 1:
        return "".join(w[0] for w in words).upper()
    return city[:3].upper()


def short_team_name(name: str) -> str:
    """City abbreviated (``PHI Eagles``); unchanged when it is not a known pro team."""
    parts = split_team(name)
    if parts is None:
        return str(name or "")
    city, nick = parts
    return f"{city_code(city)} {nick}"


def nickname(name: str) -> str:
    """``Eagles`` for ``Philadelphia Eagles``; unchanged when not a known pro team."""
    parts = split_team(name)
    return parts[1] if parts is not None else str(name or "")


def ellipsize(text: str, fits: Callable[[str], bool]) -> str:
    if fits(text):
        return text
    while len(text) > 1 and not fits(text + "…"):
        text = text[:-1].rstrip()
    return text + "…"


def fit_name(name: str, fits: Callable[[str], bool], *, upper: bool = True) -> str:
    """Full name if it fits, else the short-city name, else the nickname, else cut with "…"."""
    for candidate in (name, short_team_name(name)):
        text = candidate.upper() if upper else candidate
        if fits(text):
            return text
    last = nickname(name)
    return ellipsize(last.upper() if upper else last, fits)


def fit_matchup(home: str, away: str, fits: Callable[[str], bool], *, sep: str = " vs ") -> str:
    """``HOME vs AWAY``: full, then both cities short, then nicknames, then cut with "…"."""
    for h, a in ((home, away), (short_team_name(home), short_team_name(away))):
        text = f"{h}{sep}{a}".upper()
        if fits(text):
            return text
    return ellipsize(f"{nickname(home)}{sep}{nickname(away)}".upper(), fits)


__all__ = ["city_code", "ellipsize", "fit_matchup", "fit_name", "nickname", "short_team_name", "split_team"]
