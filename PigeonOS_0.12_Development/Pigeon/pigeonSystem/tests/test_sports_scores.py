"""Live sports scores: TheSportsDB parsing, the SPORTS list, and the board."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import sports_follow as sf  # noqa: E402
from pigeon import sports_scores as ss  # noqa: E402
from pigeon.widgets import pigeon_settings as ps  # noqa: E402
from pigeon.widgets import sports_scoreboard as board  # noqa: E402
from pigeon.widgets.main_settings import MainSettingsState, MainSettingsWidget  # noqa: E402

NOW = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)


def _row(eid: str, *, status: str = "", start: datetime = NOW, home: str = "4", away: str = "1", **kw) -> dict:
    row = {
        "idEvent": eid,
        "strSport": "Ice Hockey",
        "strLeague": "Russian KHL",
        "idLeague": "4920",
        "strHomeTeam": f"Home {eid}",
        "strAwayTeam": f"Away {eid}",
        "intHomeScore": home,
        "intAwayScore": away,
        "strStatus": status,
        "strTimestamp": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "strHomeTeamBadge": f"https://example.invalid/{eid}/home.png",
        "strAwayTeamBadge": f"https://example.invalid/{eid}/away.png",
    }
    row.update(kw)
    return row


def _ev(eid: str, **kw) -> ss.SportsEvent:
    ev = ss.parse_event(_row(eid, **kw))
    assert ev is not None
    return ev


class _Reset(unittest.TestCase):
    def setUp(self) -> None:
        ss._reset_for_tests()
        self.addCleanup(ss._reset_for_tests)
        # Never start the network poller from a test.
        p = mock.patch.object(ss, "_start_poller")
        p.start()
        self.addCleanup(p.stop)
        sf._reset_for_tests()
        self.addCleanup(sf._reset_for_tests)
        w = mock.patch("pigeon.app_state.write_app_state")
        w.start()
        self.addCleanup(w.stop)


class ParseTests(unittest.TestCase):
    def test_v1_row(self) -> None:
        ev = _ev("1", status="FT")
        self.assertEqual(ev.home, "Home 1")
        self.assertEqual((ev.home_score, ev.away_score), ("4", "1"))
        self.assertEqual(ev.league, "Russian KHL")
        self.assertEqual(ev.start_utc, NOW)
        self.assertEqual(ev.phase, ss.FINAL)

    def test_v2_livescore_row_carries_progress(self) -> None:
        ev = _ev("2", status="2H", strProgress="63", idLiveScore="99")
        self.assertEqual(ev.phase, ss.LIVE)
        self.assertEqual(ss.status_label(ev), "2H 63")

    def test_missing_id_is_dropped(self) -> None:
        self.assertIsNone(ss.parse_event({"strHomeTeam": "x"}))
        self.assertIsNone(ss.parse_event(None))

    def test_phases(self) -> None:
        self.assertEqual(ss.event_phase(_ev("a", status="NS", home="", away=""), now=NOW), ss.UPCOMING)
        self.assertEqual(ss.event_phase(_ev("b", status="Q3"), now=NOW), ss.LIVE)
        self.assertEqual(ss.event_phase(_ev("c", status="AET"), now=NOW), ss.FINAL)
        # Unlabeled but scored and under way: live.
        started = _ev("d", status="", start=NOW - timedelta(hours=1))
        self.assertEqual(ss.event_phase(started, now=NOW), ss.LIVE)
        # Unlabeled, not started: upcoming even with a stale 0-0.
        self.assertEqual(ss.event_phase(_ev("e", start=NOW + timedelta(hours=1)), now=NOW), ss.UPCOMING)

    def test_status_labels(self) -> None:
        self.assertEqual(ss.status_label(_ev("1", status="FT")), "FINAL")
        self.assertEqual(ss.status_label(_ev("1", status="PST")), "POSTPONED")
        up = _ev("1", status="NS", start=datetime(2026, 10, 26, 23, 30, tzinfo=timezone.utc))
        self.assertEqual(ss.status_label(up, tz=timezone.utc), "11:30 PM")


class RankTests(unittest.TestCase):
    def test_live_then_upcoming_then_recent_finals(self) -> None:
        events = [
            _ev("final_old", status="FT", start=NOW - timedelta(hours=9)),
            _ev("final", status="FT", start=NOW - timedelta(hours=3)),
            _ev("later", status="NS", start=NOW + timedelta(hours=3)),
            _ev("soon", status="NS", start=NOW + timedelta(hours=1)),
            _ev("tomorrow", status="NS", start=NOW + timedelta(hours=30)),
            _ev("live", status="Q2"),
        ]
        ids = [e.event_id for e in ss.rank_events(events, now=NOW)]
        self.assertEqual(ids, ["live", "soon", "later", "final"])

    def test_first_row_wins_on_duplicates(self) -> None:
        live = _ev("x", status="Q4", home="21")
        stale = _ev("x", status="Q1", home="3", strLeagueBadge="https://example.invalid/l.png")
        (merged,) = ss.rank_events([live, stale], now=NOW)
        self.assertEqual((merged.status, merged.home_score), ("Q4", "21"))
        # ...but the later row still fills fields the first lacked.
        self.assertEqual(merged.league_badge, "https://example.invalid/l.png")


class FetchTests(_Reset):
    def test_asks_each_in_season_us_league_by_id(self) -> None:
        urls: list[str] = []

        def fake(url, headers=None):
            urls.append(url)
            return {"events": [_row("1", status="Q1")]} if "l=4387" in url else {"events": None}

        with mock.patch.object(ss, "_get_json", side_effect=fake):
            events, failed = ss.fetch_available_events(key=ss.FREE_API_KEY, now=NOW)
        self.assertFalse(failed)
        self.assertEqual([e.event_id for e in events], ["1"])
        self.assertTrue(all("/123/eventsday.php" in u and "&l=" in u for u in urls))
        self.assertFalse(any("s=" in u for u in urls))
        # Late October: all six leagues are in season (WNBA runs through October).
        self.assertEqual(len(urls), len(ss.list_queries(NOW)))

    def test_queries_cover_tonight_in_utc_today_first(self) -> None:
        # 20:00 UTC: tonight's US games are already on the next UTC date.
        q = ss.list_queries(NOW)
        days = list(dict.fromkeys(d for _l, d in q))
        self.assertEqual(days, ["2026-10-26", "2026-10-27"])
        leagues = [lid for lid, d in q if d == "2026-10-26"]
        self.assertEqual(leagues, [lid for lid, _l, _a, _b in ss.LIST_LEAGUES])

    def test_out_of_season_leagues_are_skipped(self) -> None:
        july = ss.list_queries(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
        names = {n for lid, n, _a, _b in ss.LIST_LEAGUES if lid in {q[0] for q in july}}
        self.assertEqual(names, {"MLB", "MLS", "WNBA"})
        self.assertTrue(ss.league_in_season(9, 2, 1))  # NFL in January
        self.assertFalse(ss.league_in_season(9, 2, 5))

    def test_league_days_are_cached(self) -> None:
        calls = []

        def fake(url, headers=None):
            calls.append(url)
            return {"events": None}

        with mock.patch.object(ss, "_get_json", side_effect=fake):
            ss.fetch_available_events(key=ss.FREE_API_KEY, now=NOW)
            n = len(calls)
            ss.fetch_available_events(key=ss.FREE_API_KEY, now=NOW)
        self.assertEqual(len(calls), n)

    def test_429_stops_the_list_and_keeps_what_arrived(self) -> None:
        calls = []

        def fake(url, headers=None):
            calls.append(url)
            if len(calls) == 2:
                raise ss.RateLimited
            return {"events": [_row("1", status="Q1")]}

        with mock.patch.object(ss, "_get_json", side_effect=fake):
            events, failed = ss.fetch_available_events(key=ss.FREE_API_KEY, now=NOW)
        self.assertEqual(len(calls), 2)
        self.assertEqual([e.event_id for e in events], ["1"])
        self.assertFalse(failed)

    def test_get_backs_off_for_retry_after(self) -> None:
        import urllib.error

        err = urllib.error.HTTPError("u", 429, "Too Many", {"Retry-After": "90"}, None)
        with mock.patch.object(ss.urllib.request, "urlopen", side_effect=err) as op:
            with self.assertRaises(ss.RateLimited):
                ss._get("https://example.invalid/a")
            self.assertGreater(ss.backoff_remaining_s(), 80)
            # During the backoff nothing goes out.
            with self.assertRaises(ss.RateLimited):
                ss._get("https://example.invalid/b")
            self.assertEqual(op.call_count, 1)

    def test_requests_are_spaced_out(self) -> None:
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b"{}"
        with mock.patch.object(ss.urllib.request, "urlopen", return_value=resp), mock.patch.object(
            ss.time, "sleep"
        ) as sleep:
            ss._get("https://example.invalid/a")
            ss._get("https://example.invalid/b")
        self.assertEqual(sleep.call_count, 1)
        self.assertGreater(sleep.call_args[0][0], ss._MIN_GAP_FREE_S - 0.5)

    def test_premium_key_reads_the_livescore_feed_first(self) -> None:
        seen: list[tuple[str, dict | None]] = []

        def fake(url, headers=None):
            seen.append((url, headers))
            if "livescore" in url:
                return {"livescore": [_row("9", status="2H", home="2")]}
            return {"events": [_row("9", status="NS", home="", away="")]}

        with mock.patch.object(ss, "_get_json", side_effect=fake):
            (ev,), _failed = ss.fetch_available_events(key="premium-key", now=NOW)
        self.assertEqual((ev.status, ev.home_score), ("2H", "2"))
        self.assertIn("/v2/json/livescore/all", seen[0][0])
        self.assertEqual(seen[0][1], {"X-API-KEY": "premium-key"})

    def test_key_from_env(self) -> None:
        with mock.patch.dict(os.environ, {"PIGEON_SPORTSDB_KEY": " abc "}):
            self.assertEqual(ss.load_api_key(), "abc")
            self.assertTrue(ss.is_premium())


class SelectionTests(_Reset):
    def test_poll_cadence(self) -> None:
        self.assertEqual(ss.poll_interval_s(_ev("1", status="Q2"), premium=True), ss.POLL_LIVE_PREMIUM_S)
        self.assertEqual(ss.poll_interval_s(_ev("1", status="Q2"), premium=False), ss.POLL_LIVE_FREE_S)
        self.assertEqual(
            ss.poll_interval_s(_ev("1", status="NS", start=NOW + timedelta(days=1)), premium=True),
            ss.POLL_IDLE_S,
        )
        self.assertIsNone(ss.poll_interval_s(_ev("1", status="FT"), premium=True))
        self.assertIsNone(ss.poll_interval_s(None, premium=True))

    def test_update_changes_token_and_keeps_known_fields(self) -> None:
        ss.select_event(_ev("1", status="Q1", home="0", away="0"))
        t0 = ss.board_token()
        self.assertTrue(ss.apply_update(_ev("1", status="Q2", home="7", away="0", strHomeTeamBadge="")))
        cur = ss.selected_event()
        self.assertEqual((cur.status, cur.home_score), ("Q2", "7"))
        self.assertTrue(cur.home_badge)  # blank in the update, kept from before
        self.assertGreater(ss.board_token(), t0)
        self.assertFalse(ss.apply_update(_ev("other", status="Q4")))

    def test_board_clears_after_final_hold(self) -> None:
        ss.select_event(_ev("1", status="Q4"))
        ss.apply_update(_ev("1", status="FT"))
        self.assertTrue(ss.scoreboard_active())
        ss._expire_final(now=ss._final_since + ss.FINAL_HOLD_S + 1)
        self.assertFalse(ss.scoreboard_active())


class BoardRenderTests(_Reset):
    def test_inactive_is_none(self) -> None:
        self.assertIsNone(board.scoreboard_frame_bgr(1280, 800))

    def test_live_board_draws_and_caches(self) -> None:
        ss.select_event(_ev("1", status="Q3", home="21", away="17"))
        tick = datetime(2026, 10, 27, 20, 15, 30)
        clock = mock.patch.object(board, "_clock_now", return_value=tick)
        clock.start()
        self.addCleanup(clock.stop)
        a = board.scoreboard_frame_bgr(1280, 800)
        self.assertEqual(a.shape, (800, 1280, 3))
        self.assertGreater(int(np.count_nonzero(a)), 1000)
        self.assertIs(board.scoreboard_frame_bgr(1280, 800), a)
        self.assertEqual(board.scoreboard_frame_bgr(640, 400).shape, (400, 640, 3))
        ss.apply_update(_ev("1", status="Q3", home="28", away="17"))
        self.assertIsNot(board.scoreboard_frame_bgr(1280, 800), a)

    def test_bottom_clock_ticks_each_second(self) -> None:
        ss.select_event(_ev("1", status="Q3"))
        t0 = datetime(2026, 10, 27, 20, 15, 0)
        with mock.patch.object(board, "_clock_now", return_value=t0):
            a = board.scoreboard_frame_bgr(1280, 800).copy()
        with mock.patch.object(board, "_clock_now", return_value=t0.replace(second=59)):
            b = board.scoreboard_frame_bgr(1280, 800)
        self.assertNotEqual(board.clock_key(t0), board.clock_key(t0.replace(second=59)))
        bar = slice(board._CLOCK_BAR_Y, board._CLOCK_BAR_Y + board._CLOCK_BAR_H)
        lit = lambda f: int(np.count_nonzero(f[bar].max(axis=2)))  # noqa: E731
        # :00 lights one of the 60 cells; :59 lights all of them.
        self.assertGreater(lit(b), 30 * lit(a))
        self.assertGreater(lit(a), 0)

    def test_badge_is_pasted_when_loaded(self) -> None:
        ev = _ev("1", status="Q1")
        red = np.zeros((100, 100, 4), dtype=np.uint8)
        red[:, :, 2] = 255
        red[:, :, 3] = 255
        img = np.asarray(board.render_scoreboard_rgba(ev, badges={ev.home_badge: red}))
        cx, cy = board._BADGE_CX[0], board._BADGE_CY
        self.assertEqual(tuple(img[cy, cx, :3]), (255, 0, 0))


class SettingsListTests(_Reset):
    def _widget(self) -> MainSettingsWidget:
        w = MainSettingsWidget()
        with mock.patch.object(MainSettingsState, "refresh_network_ssid"):
            w.state.enter_pigeon_settings()
        ring = ps.pigeon_focus_ring(w.state.pigeon_view)
        w.state.pigeon_focus_index = ring.index("sports")
        self.assertEqual(w.activate(), "sports_page_open")
        ring = ps.pigeon_focus_ring(w.state.pigeon_view)
        w.state.pigeon_focus_index = ring.index("sports_games")
        return w

    def _with_events(self, *events: ss.SportsEvent) -> None:
        ss._events = tuple(events)
        ss._events_mono = 1e18  # fresh: no fetch on open

    def test_sports_is_the_last_general_tile(self) -> None:
        self.assertEqual(ps.view_slots("general")[-1].focus_id, "sports")

    def test_pick_a_game_leaves_settings_for_the_board(self) -> None:
        self._with_events(_ev("1", status="Q2"), _ev("2", status="NS", start=NOW + timedelta(hours=2)))
        w = self._widget()
        self.assertEqual(w.activate(), "sports_dropdown_open")
        self.assertTrue(w.state.sports_dropdown_open)
        w.navigate(forward=True)
        self.assertEqual(w.activate(), "exit")
        self.assertFalse(w.state.show_pigeon_settings)
        self.assertEqual(ss.selected_event().event_id, "2")

    def test_scores_off_row_while_a_game_is_up(self) -> None:
        self._with_events(_ev("1", status="Q2"))
        ss.select_event(_ev("1", status="Q2"))
        w = self._widget()
        w.activate()
        self.assertEqual(ps.sports_dropdown_entries()[0][2], ps.SPORTS_OFF)
        self.assertEqual(w.activate(), "sports_off")
        self.assertFalse(ss.scoreboard_active())
        self.assertTrue(w.state.show_pigeon_settings)

    def test_empty_list_shows_a_message_row(self) -> None:
        with mock.patch.object(ss, "refresh_events"):
            w = self._widget()
            w.activate()
        ((label, _status, payload),) = ps.sports_dropdown_entries()
        self.assertEqual((label, payload), ("NO GAMES TODAY", None))
        self.assertEqual(w.activate(), "sports_dropdown_close")
        self.assertTrue(w.state.show_pigeon_settings)

    def test_backoff_shows_a_busy_row(self) -> None:
        ss._blocked_until_mono = ss.time.monotonic() + 60
        ((label, _status, payload),) = ps.sports_dropdown_entries()
        self.assertEqual((label, payload), ("BUSY · TRY AGAIN SOON", None))

    def test_list_draws_over_the_page(self) -> None:
        self._with_events(_ev("1", status="Q2"))
        st = MainSettingsState()
        st.sports_dropdown_open = True
        with_list = ps.render_pigeon_settings_bgra(st)
        st.sports_dropdown_open = False
        self.assertFalse(np.array_equal(with_list, ps.render_pigeon_settings_bgra(st)))


if __name__ == "__main__":
    unittest.main()
