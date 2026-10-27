"""Followed teams and AUTO SCORES.

The sports page (settings_pigeon → SPORTS) lets the user follow teams in the
leagues of :mod:`pigeon.sports_teams`. With AUTO SCORES on, a background
watcher asks TheSportsDB for each followed team's next game and puts that game
on the scoreboard from its start time until the final hold runs out.

Saved in ``state.json`` as ``sports_follow``::

    {"auto": true, "teams": {"4391": ["134936", ...], ...}}

Request budget: one ``eventsnext`` per followed team every few hours, every
10 minutes once its game is near. A manual pick from the LIVE GAMES list always
wins; the watcher only fills an empty board, and only once per game (so
turning a game off sticks).
"""

from __future__ import annotations

import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from pigeon.sports_scores import (
    FINAL,
    RateLimited,
    SportsEvent,
    _V1,
    _get_json,
    _rows,
    backoff_remaining_s,
    load_api_key,
    parse_event,
    select_event,
    selected_event,
)

_STATE_KEY = "sports_follow"

# Watch window around a game: show it from kickoff until the final hold ends.
_SHOW_BEFORE = timedelta(minutes=0)
_SHOW_AFTER = timedelta(hours=5)
# How often to re-ask for a team's next game.
_NEXT_TTL_FAR_S = 3 * 3600.0
_NEXT_TTL_NEAR_S = 10 * 60.0
_NEAR = timedelta(hours=2)
_TICK_S = 60.0

_lock = threading.Lock()
_wake = threading.Event()
_version = 0
_cache: dict | None = None
# team id -> (events, monotonic time fetched)
_next: dict[str, tuple[tuple[SportsEvent, ...], float]] = {}
# Games the watcher already put on the board (never again, even if turned off).
_auto_shown: set[str] = set()
_watcher: threading.Thread | None = None


# --- store --------------------------------------------------------------------


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            from pigeon.app_state import read_app_state

            raw = read_app_state().get(_STATE_KEY)
        except Exception:
            raw = None
        raw = raw if isinstance(raw, dict) else {}
        teams = raw.get("teams") if isinstance(raw.get("teams"), dict) else {}
        _cache = {
            "auto": bool(raw.get("auto", True)),
            "teams": {str(k): [str(t) for t in v] for k, v in teams.items() if isinstance(v, list)},
        }
    return _cache


def _save() -> None:
    global _version
    data = _load()
    try:
        from pigeon.app_state import write_app_state

        write_app_state(**{_STATE_KEY: data})
    except Exception:
        pass
    _version += 1
    _wake.set()


def settings_version() -> int:
    """Bumps on every follow / auto change (settings repaint key)."""
    return _version


def auto_enabled() -> bool:
    with _lock:
        return bool(_load()["auto"])


def set_auto(on: bool) -> None:
    with _lock:
        _load()["auto"] = bool(on)
        _save()


def toggle_auto() -> bool:
    with _lock:
        data = _load()
        data["auto"] = not data["auto"]
        _save()
        return data["auto"]


def followed(league_id: str) -> frozenset[str]:
    with _lock:
        return frozenset(_load()["teams"].get(str(league_id), ()))


def followed_count(league_id: str) -> int:
    return len(followed(league_id))


def all_followed() -> list[tuple[str, str]]:
    """(league id, team id) for every followed team."""
    with _lock:
        return [(lid, tid) for lid, ids in _load()["teams"].items() for tid in ids]


def toggle_follow(league_id: str, team_id: str) -> bool:
    """Follow / unfollow; returns True when now followed."""
    lid, tid = str(league_id), str(team_id)
    with _lock:
        teams = _load()["teams"]
        ids = teams.setdefault(lid, [])
        if tid in ids:
            ids.remove(tid)
            now_on = False
        else:
            ids.append(tid)
            now_on = True
        if not ids:
            teams.pop(lid, None)
        _save()
    return now_on


# --- watcher ------------------------------------------------------------------


def _fetch_next(key: str, team_id: str) -> tuple[SportsEvent, ...] | None:
    q = urllib.parse.urlencode({"id": team_id})
    data = _get_json(f"{_V1}/{key}/eventsnext.php?{q}")
    if data is None:
        return None
    return tuple(ev for ev in (parse_event(r) for r in _rows(data, "events")) if ev is not None)


def _next_ttl(events: tuple[SportsEvent, ...], now: datetime) -> float:
    for ev in events:
        if ev.start_utc is not None and ev.start_utc - _NEAR <= now <= ev.start_utc + _SHOW_AFTER:
            return _NEXT_TTL_NEAR_S
    return _NEXT_TTL_FAR_S


def in_show_window(ev: SportsEvent, now: datetime) -> bool:
    if ev.start_utc is None or ev.phase == FINAL:
        return False
    return ev.start_utc - _SHOW_BEFORE <= now <= ev.start_utc + _SHOW_AFTER


def pick_game(events: list[SportsEvent], *, now: datetime, shown: set[str]) -> SportsEvent | None:
    """First followed game in its show window that the watcher has not shown."""
    live = [ev for ev in events if ev.event_id not in shown and in_show_window(ev, now)]
    live.sort(key=lambda ev: ev.start_utc or now)
    return live[0] if live else None


def check_once(*, now: datetime | None = None, mono: float | None = None) -> SportsEvent | None:
    """Refresh stale teams, then put a due game on an empty board."""
    now = now or datetime.now(timezone.utc)
    mono = time.monotonic() if mono is None else mono
    if not auto_enabled():
        return None
    teams = all_followed()
    if not teams:
        return None
    key = load_api_key()
    for _lid, tid in teams:
        hit = _next.get(tid)
        if hit is not None and mono - hit[1] < _next_ttl(hit[0], now):
            continue
        try:
            got = _fetch_next(key, tid)
        except RateLimited:
            break
        if got is not None:
            _next[tid] = (got, mono)
    if selected_event() is not None:
        return None
    wanted = {tid for _lid, tid in teams}
    events: dict[str, SportsEvent] = {}
    for tid in wanted:
        for ev in _next.get(tid, ((), 0.0))[0]:
            events.setdefault(ev.event_id, ev)
    game = pick_game(list(events.values()), now=now, shown=_auto_shown)
    if game is not None:
        _auto_shown.add(game.event_id)
        select_event(game)
    return game


def _watch_loop() -> None:
    # Warm the LIVE GAMES list once after boot (it is also saved to disk).
    try:
        from pigeon.sports_scores import refresh_events

        refresh_events()
    except Exception:
        pass
    while True:
        try:
            check_once()
        except Exception:
            pass
        _wake.wait(timeout=max(_TICK_S, backoff_remaining_s()))
        _wake.clear()


def start_auto_watch() -> None:
    global _watcher
    with _lock:
        if _watcher is not None and _watcher.is_alive():
            return
        _watcher = threading.Thread(target=_watch_loop, name="pigeon-sports-auto", daemon=True)
        _watcher.start()


def _reset_for_tests() -> None:
    global _cache, _version
    _cache = {"auto": True, "teams": {}}
    _version = 0
    _next.clear()
    _auto_shown.clear()


__all__ = [
    "all_followed",
    "auto_enabled",
    "check_once",
    "followed",
    "followed_count",
    "in_show_window",
    "pick_game",
    "set_auto",
    "settings_version",
    "start_auto_watch",
    "toggle_auto",
    "toggle_follow",
]
