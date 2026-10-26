"""Live sports scores from TheSportsDB (settings_pigeon SPORTS tile).

The SPORTS tile opens a list of today's events; picking one makes Pigeon
show a scoreboard (both team badges, the league, the score) instead of now
playing. The pick is not persisted: a game is over long before a reboot
matters. The board clears itself a while after the final whistle.

API key: ``PIGEON_SPORTSDB_KEY`` or ``~/.pigeon_0_6/sportsdb_api_key`` (one
line). Without one Pigeon uses TheSportsDB's free key, which has no live feed
and caps ``eventsday`` at a few events per sport, so scores update only as
fast as TheSportsDB refreshes its event records. A Premium key adds the v2
livescore feed (every live game, scores within a couple of minutes).

Network work runs on daemon threads; the UI only reads snapshots.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

FREE_API_KEY = "123"
_V1 = "https://www.thesportsdb.com/api/v1/json"
_V2 = "https://www.thesportsdb.com/api/v2/json"
_KEY_FILE = "sportsdb_api_key"
_FETCH_TIMEOUT_S = 8.0

# Sports listed on the free key (one eventsday call each, per date).
LIST_SPORTS: tuple[str, ...] = (
    "American Football",
    "Basketball",
    "Baseball",
    "Ice Hockey",
    "Soccer",
)
_LIST_TTL_S = 60.0
# Free key: 30 requests/min. Premium: 100/min, and the feed itself moves
# about every couple of minutes, so 30 s never misses an update.
POLL_LIVE_PREMIUM_S = 30.0
POLL_LIVE_FREE_S = 60.0
POLL_IDLE_S = 120.0  # not started yet
_POLL_RETRY_S = 20.0
# Keep the final score up this long, then return to now playing.
FINAL_HOLD_S = 15 * 60.0
# List finals that started at most this long ago (so ended within a few
# hours), and upcoming games this far ahead.
_LIST_FINAL_MAX_AGE = timedelta(hours=7)
_LIST_UPCOMING_MAX = timedelta(hours=18)
# An event with no status but a score, started this recently, is live.
_UNLABELED_LIVE_WINDOW = timedelta(hours=4)

_FINISHED = frozenset(
    {
        "FT", "AET", "PEN", "AOT", "AP", "FINAL", "FINISHED", "MATCH FINISHED",
        "AFTER OT", "AFTER PENALTIES", "AWARDED", "AWD", "WO", "ABD", "ABANDONED",
        "CANC", "CANCELLED", "CANCELED", "PST", "POSTPONED",
    }
)
_NOT_STARTED = frozenset({"", "NS", "NOT STARTED", "TBD", "SCHEDULED", "TIME TBD"})

LIVE = "live"
UPCOMING = "upcoming"
FINAL = "final"


@dataclass(frozen=True)
class SportsEvent:
    event_id: str
    sport: str = ""
    league: str = ""
    league_id: str = ""
    league_badge: str = ""
    home: str = ""
    away: str = ""
    home_badge: str = ""
    away_badge: str = ""
    home_score: str = ""
    away_score: str = ""
    status: str = ""
    progress: str = ""
    start_utc: datetime | None = None

    @property
    def phase(self) -> str:
        return event_phase(self)

    @property
    def title(self) -> str:
        if self.home and self.away:
            return f"{self.home} vs {self.away}"
        return self.home or self.away


# --- parsing ------------------------------------------------------------------


def _s(row: dict, *keys: str) -> str:
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _parse_start(row: dict) -> datetime | None:
    raw = _s(row, "strTimestamp")
    if not raw:
        day, clock = _s(row, "dateEvent"), _s(row, "strTime", "strEventTime")
        if not day:
            return None
        raw = f"{day}T{clock or '00:00:00'}"
    try:
        dt = datetime.fromisoformat(raw.replace(" ", "T").rstrip("Z"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def parse_event(row: object) -> SportsEvent | None:
    """One v1 ``events`` row or v2 ``livescore`` row; None without an id."""
    if not isinstance(row, dict):
        return None
    eid = _s(row, "idEvent")
    if not eid:
        return None
    return SportsEvent(
        event_id=eid,
        sport=_s(row, "strSport"),
        league=_s(row, "strLeague"),
        league_id=_s(row, "idLeague"),
        league_badge=_s(row, "strLeagueBadge"),
        home=_s(row, "strHomeTeam"),
        away=_s(row, "strAwayTeam"),
        home_badge=_s(row, "strHomeTeamBadge"),
        away_badge=_s(row, "strAwayTeamBadge"),
        home_score=_s(row, "intHomeScore"),
        away_score=_s(row, "intAwayScore"),
        status=_s(row, "strStatus"),
        progress=_s(row, "strProgress"),
        start_utc=_parse_start(row),
    )


def event_phase(ev: SportsEvent, *, now: datetime | None = None) -> str:
    st = ev.status.strip().upper()
    if st in _FINISHED:
        return FINAL
    if st in _NOT_STARTED:
        now = now or datetime.now(timezone.utc)
        started = ev.start_utc is not None and ev.start_utc <= now
        if (
            not st
            and started
            and (ev.home_score or ev.away_score)
            and now - ev.start_utc < _UNLABELED_LIVE_WINDOW
        ):
            return LIVE
        return UPCOMING
    return LIVE


def status_label(ev: SportsEvent, *, tz: Any = None) -> str:
    """Short status for the list and the board: ``Q3 8:12`` / ``7:30 PM`` / ``FINAL``."""
    phase = ev.phase
    if phase == FINAL:
        st = ev.status.strip().upper()
        if st in ("PST", "POSTPONED"):
            return "POSTPONED"
        if st in ("CANC", "CANCELLED", "CANCELED", "ABD", "ABANDONED"):
            return "CANCELLED"
        return "FINAL"
    if phase == LIVE:
        bits = [b for b in (ev.status.strip(), ev.progress.strip()) if b]
        if len(bits) == 2 and bits[1].upper() in bits[0].upper():
            bits = bits[:1]
        text = " ".join(bits).upper()
        return text if text and text != "LIVE" else "LIVE"
    if ev.start_utc is None:
        return "TODAY"
    local = ev.start_utc.astimezone(tz) if tz is not None else ev.start_utc.astimezone()
    return local.strftime("%I:%M %p").lstrip("0")


# --- HTTP ---------------------------------------------------------------------


def load_api_key() -> str:
    k = os.environ.get("PIGEON_SPORTSDB_KEY", "").strip()
    if k:
        return k
    try:
        from pigeon.runtime_paths import pigeon_state_dir

        p = pigeon_state_dir() / _KEY_FILE
        if p.is_file():
            k = p.read_text(encoding="utf-8", errors="ignore").strip().splitlines()[0].strip()
            if k:
                return k
    except (OSError, IndexError):
        pass
    return FREE_API_KEY


def is_premium(key: str | None = None) -> bool:
    return (key if key is not None else load_api_key()) != FREE_API_KEY


def _get(url: str, *, headers: dict[str, str] | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Pigeon/0.12 (sports)", **(headers or {})})
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:
        return resp.read()


def _get_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    try:
        return json.loads(_get(url, headers=headers).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def _rows(data: Any, *keys: str) -> list:
    if not isinstance(data, dict):
        return []
    for k in keys:
        v = data.get(k)
        if isinstance(v, list):
            return v
    return []


def _fetch_day(key: str, day: str, sport: str) -> list[SportsEvent]:
    q = urllib.parse.urlencode({"d": day, "s": sport})
    data = _get_json(f"{_V1}/{key}/eventsday.php?{q}")
    return [e for e in map(parse_event, _rows(data, "events")) if e is not None]


def _fetch_livescores(key: str, scope: str = "all") -> list[SportsEvent] | None:
    """v2 livescore feed (Premium). None when the key is refused / offline."""
    data = _get_json(f"{_V2}/livescore/{urllib.parse.quote(scope)}", headers={"X-API-KEY": key})
    if not isinstance(data, dict) or "livescore" not in data and "livescores" not in data:
        return None
    return [e for e in map(parse_event, _rows(data, "livescore", "livescores")) if e is not None]


def _fetch_event(key: str, event_id: str) -> SportsEvent | None:
    q = urllib.parse.urlencode({"id": event_id})
    rows = _rows(_get_json(f"{_V1}/{key}/lookupevent.php?{q}"), "events")
    return parse_event(rows[0]) if rows else None


def _local_tz() -> Any:
    try:
        from zoneinfo import ZoneInfo

        from pigeon.pigeon_locale import read_timezone

        name = read_timezone()
        return ZoneInfo(name) if name else None
    except Exception:
        return None


def _list_days(now: datetime) -> list[str]:
    """TheSportsDB files events by UTC date; an evening game locally is
    tomorrow in UTC, so ask for both."""
    tz = _local_tz()
    local = now.astimezone(tz) if tz is not None else now.astimezone()
    days = [local.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")]
    return list(dict.fromkeys(days))


def _merge_score(base: SportsEvent, fresh: SportsEvent) -> SportsEvent:
    """``fresh`` wins, but never blanks a field ``base`` already had."""
    kw = {
        f: getattr(fresh, f) or getattr(base, f)
        for f in SportsEvent.__dataclass_fields__
        if f != "event_id"
    }
    return replace(base, **kw)


def rank_events(events: list[SportsEvent], *, now: datetime | None = None) -> list[SportsEvent]:
    """Live first, then upcoming by start, then recent finals; stale ones dropped."""
    now = now or datetime.now(timezone.utc)
    order = {LIVE: 0, UPCOMING: 1, FINAL: 2}
    keep: dict[str, SportsEvent] = {}
    for ev in events:
        phase = event_phase(ev, now=now)
        start = ev.start_utc
        if phase == FINAL and (start is None or now - start > _LIST_FINAL_MAX_AGE):
            continue
        if phase == UPCOMING and start is not None and start - now > _LIST_UPCOMING_MAX:
            continue
        prev = keep.get(ev.event_id)
        # The first row seen wins (livescore before eventsday); later ones fill gaps.
        keep[ev.event_id] = _merge_score(ev, prev) if prev else ev

    def key(ev: SportsEvent) -> tuple:
        phase = event_phase(ev, now=now)
        t = ev.start_utc.timestamp() if ev.start_utc else 1e18
        # Finals: most recent first.
        return (order[phase], -t if phase == FINAL else t, ev.league, ev.title)

    return sorted(keep.values(), key=key)


def fetch_available_events(*, key: str | None = None, now: datetime | None = None) -> list[SportsEvent]:
    key = key or load_api_key()
    now = now or datetime.now(timezone.utc)
    found: list[SportsEvent] = []
    if is_premium(key):
        found.extend(_fetch_livescores(key) or [])
    for day in _list_days(now):
        for sport in LIST_SPORTS:
            found.extend(_fetch_day(key, day, sport))
    # Livescore rows first: they are the freshest.
    return rank_events(found, now=now)


# --- badges -------------------------------------------------------------------

_badge_lock = threading.Lock()
_badges: dict[str, np.ndarray | None] = {}


def _decode_badge(data: bytes) -> np.ndarray | None:
    import cv2

    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None or img.size == 0:
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


def _fetch_badge(url: str) -> np.ndarray | None:
    # ``/small`` is TheSportsDB's 250 px variant; plenty for the board.
    for u in (f"{url.rstrip('/')}/small", url):
        try:
            img = _decode_badge(_get(u))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            img = None
        if img is not None:
            return img
    return None


def badge_bgra(url: str) -> np.ndarray | None:
    """Cached badge, or None (not fetched yet / failed)."""
    if not url:
        return None
    with _badge_lock:
        return _badges.get(url)


def _ensure_badges(*urls: str) -> None:
    for url in urls:
        if not url:
            continue
        with _badge_lock:
            if url in _badges:
                continue
        img = _fetch_badge(url)
        with _badge_lock:
            _badges[url] = img
            if len(_badges) > 32:
                _badges.pop(next(iter(_badges)))
        _bump()


# --- state --------------------------------------------------------------------

_lock = threading.RLock()
_version = 0
_events: tuple[SportsEvent, ...] = ()
_events_mono = 0.0
_events_loading = False
_events_error = False
_selected: SportsEvent | None = None
_final_since: float | None = None
_wake = threading.Event()
_poller: threading.Thread | None = None


def _bump() -> None:
    global _version
    with _lock:
        _version += 1


def board_token() -> int:
    """Changes whenever the scoreboard or the event list would draw differently."""
    with _lock:
        return _version


def events_snapshot() -> tuple[tuple[SportsEvent, ...], bool, bool]:
    """(events, loading, failed)."""
    with _lock:
        return _events, _events_loading, _events_error


def refresh_events(*, force: bool = False) -> bool:
    """Fetch the event list off-thread; False if a fresh list or a fetch is already there."""
    global _events_loading
    with _lock:
        if _events_loading:
            return False
        if not force and _events and time.monotonic() - _events_mono < _LIST_TTL_S:
            return False
        _events_loading = True
    _bump()

    def worker() -> None:
        global _events, _events_mono, _events_loading, _events_error
        try:
            found = fetch_available_events()
            err = False
        except Exception:
            found, err = [], True
        with _lock:
            if found or err or not _events:
                _events = tuple(found)
            _events_error = err
            _events_mono = time.monotonic()
            _events_loading = False
        _bump()

    threading.Thread(target=worker, name="pigeon-sports-list", daemon=True).start()
    return True


def selected_event() -> SportsEvent | None:
    with _lock:
        return _selected


def scoreboard_active() -> bool:
    _expire_final()
    with _lock:
        return _selected is not None


def select_event(ev: SportsEvent) -> None:
    global _selected, _final_since
    with _lock:
        _selected = ev
        _final_since = time.monotonic() if ev.phase == FINAL else None
    _bump()
    _start_poller()
    _wake.set()


def clear_selection() -> None:
    global _selected, _final_since
    with _lock:
        if _selected is None:
            return
        _selected = None
        _final_since = None
    _bump()
    _wake.set()


def _expire_final(now: float | None = None) -> None:
    with _lock:
        since = _final_since
    if since is not None and (now if now is not None else time.monotonic()) - since >= FINAL_HOLD_S:
        clear_selection()


def poll_interval_s(ev: SportsEvent | None, *, premium: bool) -> float | None:
    """Seconds until the next poll; None = stop (no event, or it is over)."""
    if ev is None or ev.phase == FINAL:
        return None
    if ev.phase == UPCOMING:
        return POLL_IDLE_S
    return POLL_LIVE_PREMIUM_S if premium else POLL_LIVE_FREE_S


def _fetch_update(ev: SportsEvent, key: str) -> SportsEvent | None:
    if is_premium(key):
        live = _fetch_livescores(key, ev.league_id) if ev.league_id else None
        for row in live or []:
            if row.event_id == ev.event_id:
                return row
    return _fetch_event(key, ev.event_id)


def apply_update(fresh: SportsEvent) -> bool:
    """Fold a polled row into the selection; True when the board changed."""
    global _selected, _final_since
    with _lock:
        cur = _selected
        if cur is None or cur.event_id != fresh.event_id:
            return False
        merged = _merge_score(cur, fresh)
        if merged == cur:
            return False
        _selected = merged
        if merged.phase == FINAL and _final_since is None:
            _final_since = time.monotonic()
    _bump()
    return True


def _poll_loop() -> None:
    while True:
        ev = selected_event()
        if ev is None:
            _wake.wait()
            _wake.clear()
            continue
        _ensure_badges(ev.home_badge, ev.away_badge, ev.league_badge)
        key = load_api_key()
        delay: float | None
        try:
            fresh = _fetch_update(ev, key)
        except Exception:
            fresh = None
        if fresh is not None:
            apply_update(fresh)
            delay = poll_interval_s(selected_event(), premium=is_premium(key))
        else:
            delay = _POLL_RETRY_S
        if delay is None:
            # Over: sleep until the hold runs out (or a new pick wakes us).
            _wake.wait(timeout=30.0)
            _wake.clear()
            _expire_final()
            continue
        if _wake.wait(timeout=delay):
            _wake.clear()


def _start_poller() -> None:
    global _poller
    with _lock:
        if _poller is not None and _poller.is_alive():
            return
        _poller = threading.Thread(target=_poll_loop, name="pigeon-sports-poll", daemon=True)
        _poller.start()


def _reset_for_tests() -> None:
    global _events, _events_mono, _events_loading, _events_error, _selected, _final_since
    with _lock:
        _events = ()
        _events_mono = 0.0
        _events_loading = False
        _events_error = False
        _selected = None
        _final_since = None
    with _badge_lock:
        _badges.clear()
    _bump()


__all__ = [
    "FINAL",
    "LIVE",
    "UPCOMING",
    "SportsEvent",
    "apply_update",
    "badge_bgra",
    "board_token",
    "clear_selection",
    "event_phase",
    "events_snapshot",
    "fetch_available_events",
    "is_premium",
    "load_api_key",
    "parse_event",
    "poll_interval_s",
    "rank_events",
    "refresh_events",
    "scoreboard_active",
    "select_event",
    "selected_event",
    "status_label",
]
