"""The sports page (settings_pigeon → SPORTS) as plain data (Control API ``/sports``).

Same settings the device shows: SCORES show / hide, FOLLOWED TEAMS auto / off
(only while scores are shown), the followed teams per league, and TODAY'S
GAMES (put one on the scoreboard, or take it off). While scores are hidden
the game rows leave the scores out too, so the phone does not spoil them.

The device's screens read these values live, so no UI-thread reload is needed.
"""

from __future__ import annotations

from typing import Any, Mapping


def _event_body(ev, *, tz, scores: bool) -> dict[str, Any]:
    from pigeon.sports_scores import status_label

    return {
        "id": ev.event_id,
        "league": ev.league,
        "league_id": ev.league_id or None,
        "home": ev.home,
        "away": ev.away,
        "home_score": (ev.home_score or "0") if scores and ev.phase != "upcoming" else None,
        "away_score": (ev.away_score or "0") if scores and ev.phase != "upcoming" else None,
        "phase": ev.phase,
        "status": status_label(ev, tz=tz),
        "start": ev.start_utc.isoformat() if ev.start_utc else None,
        "home_badge": ev.home_badge or None,
        "away_badge": ev.away_badge or None,
        "league_badge": ev.league_badge or None,
    }


def _tz():
    try:
        from zoneinfo import ZoneInfo

        from pigeon.pigeon_locale import read_timezone

        name = read_timezone()
        return ZoneInfo(name) if name else None
    except Exception:
        return None


def read_sports() -> dict[str, Any]:
    from pigeon import sports_follow as sf
    from pigeon.sports_scores import scoreboard_active, selected_event
    from pigeon.sports_teams import FOLLOW_LEAGUES, teams
    from pigeon.widgets.sports_settings import uses_letters

    shown = sf.scores_shown()
    board = selected_event() if scoreboard_active() else None
    return {
        "scores_shown": shown,
        "followed_auto": sf.auto_enabled(),
        "followed_active": sf.auto_active(),
        "leagues": [
            {
                "id": lg.league_id,
                "name": lg.name,
                "team_count": len(teams(lg.league_id)),
                "by_letter": uses_letters(lg.league_id),
                "followed": sorted(sf.followed(lg.league_id)),
            }
            for lg in FOLLOW_LEAGUES
        ],
        "board": _event_body(board, tz=_tz(), scores=shown) if board is not None else None,
    }


def patch_sports(body: Mapping[str, Any]) -> None:
    """``scores_shown`` / ``followed_auto`` booleans. Raises ValueError with the field names."""
    from pigeon import sports_follow as sf

    errors = sorted(set(body) - {"scores_shown", "followed_auto"})
    for key in ("scores_shown", "followed_auto"):
        if key in body and not isinstance(body[key], bool):
            errors.append(key)
    if errors or not body:
        raise ValueError(",".join(errors) or "scores_shown")
    if "scores_shown" in body and body["scores_shown"] != sf.scores_shown():
        sf.toggle_scores()
    if "followed_auto" in body:
        sf.set_auto(bool(body["followed_auto"]))


def read_teams(league_id: str) -> dict[str, Any]:
    """Raises KeyError for an unknown league."""
    from pigeon.sports_follow import followed
    from pigeon.sports_teams import league, teams
    from pigeon.widgets.sports_settings import team_letter, uses_letters

    lg = league(league_id)
    if lg is None:
        raise KeyError(league_id)
    on = followed(lg.league_id)
    return {
        "league": {"id": lg.league_id, "name": lg.name, "by_letter": uses_letters(lg.league_id)},
        "teams": [
            {"id": t.team_id, "name": t.name, "letter": team_letter(t.name), "followed": t.team_id in on}
            for t in teams(lg.league_id)
        ],
    }


def set_follow(league_id: str, team_id: str, on: bool) -> None:
    """Raises KeyError for an unknown league or team."""
    from pigeon import sports_follow as sf
    from pigeon.sports_teams import league, teams

    if league(league_id) is None or all(t.team_id != team_id for t in teams(league_id)):
        raise KeyError(team_id)
    if (team_id in sf.followed(league_id)) != on:
        sf.toggle_follow(league_id, team_id)


def read_games() -> dict[str, Any]:
    """Today's games (starts a refresh when the list is stale)."""
    from pigeon import sports_follow as sf
    from pigeon.sports_scores import backoff_remaining_s, events_snapshot, refresh_events

    refresh_events()
    events, loading, failed = events_snapshot()
    tz = _tz()
    shown = sf.scores_shown()
    return {
        "games": [_event_body(ev, tz=tz, scores=shown) for ev in events],
        "loading": loading,
        "failed": failed and not events,
        "busy": backoff_remaining_s() > 0,
    }


def show_game(event_id: str) -> None:
    """Put a game from today's list on the scoreboard. Raises KeyError if it is not listed."""
    from pigeon.sports_scores import events_snapshot, select_event

    ev = next((e for e in events_snapshot()[0] if e.event_id == str(event_id)), None)
    if ev is None:
        raise KeyError(event_id)
    select_event(ev)


def clear_game() -> None:
    from pigeon.sports_scores import clear_selection

    clear_selection()


__all__ = [
    "clear_game",
    "patch_sports",
    "read_games",
    "read_sports",
    "read_teams",
    "set_follow",
    "show_game",
]
