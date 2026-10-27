"""Followed teams, AUTO SCORES, and the settings_pigeon sports page."""

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
from pigeon import sports_teams as teams  # noqa: E402
from pigeon.widgets import pigeon_settings as ps  # noqa: E402
from pigeon.widgets import sports_settings as sps  # noqa: E402
from pigeon.widgets.main_settings import MainSettingsState, MainSettingsWidget  # noqa: E402

NOW = datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc)
NFL = "4391"


def _ev(eid: str, *, start: datetime, status: str = "NS", home: str = "Dallas Cowboys") -> ss.SportsEvent:
    ev = ss.parse_event(
        {
            "idEvent": eid,
            "strSport": "American Football",
            "strLeague": "NFL",
            "idLeague": NFL,
            "strHomeTeam": home,
            "strAwayTeam": "Philadelphia Eagles",
            "strStatus": status,
            "strTimestamp": start.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )
    assert ev is not None
    return ev


class _Reset(unittest.TestCase):
    def setUp(self) -> None:
        ss._reset_for_tests()
        sf._reset_for_tests()
        self.addCleanup(ss._reset_for_tests)
        self.addCleanup(sf._reset_for_tests)
        for target in ("pigeon.app_state.write_app_state",):
            p = mock.patch(target)
            self.saved = p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(ss, "_start_poller")
        p.start()
        self.addCleanup(p.stop)
        # Opening the page warms LIVE GAMES: keep that off the network.
        p = mock.patch.object(ss, "fetch_available_events", return_value=([], False))
        p.start()
        self.addCleanup(p.stop)


class CatalogTests(unittest.TestCase):
    def test_leagues_match_the_logo_order(self) -> None:
        self.assertEqual(
            [lg.name for lg in teams.FOLLOW_LEAGUES],
            ["NFL", "MLB", "NBA", "WNBA", "NCAA FOOTBALL", "NCAA BASKETBALL", "NHL"],
        )

    def test_teams_are_sorted_and_unique(self) -> None:
        for lg in teams.FOLLOW_LEAGUES:
            rows = teams.teams(lg.league_id)
            names = [t.name.lower() for t in rows]
            self.assertEqual(names, sorted(names), lg.name)
            self.assertEqual(len({t.team_id for t in rows}), len(rows), lg.name)


class FollowStoreTests(_Reset):
    def test_toggle_follow_saves(self) -> None:
        self.assertTrue(sf.toggle_follow(NFL, "134934"))
        self.assertEqual(sf.followed(NFL), frozenset({"134934"}))
        self.saved.assert_called()
        self.assertEqual(self.saved.call_args.kwargs["sports_follow"]["teams"], {NFL: ["134934"]})
        self.assertFalse(sf.toggle_follow(NFL, "134934"))
        self.assertEqual(sf.all_followed(), [])

    def test_auto_toggles_and_bumps_version(self) -> None:
        v0 = sf.settings_version()
        self.assertTrue(sf.auto_enabled())
        self.assertFalse(sf.toggle_auto())
        self.assertGreater(sf.settings_version(), v0)


class AutoTests(_Reset):
    def _follow(self, *events: ss.SportsEvent) -> mock.MagicMock:
        sf.toggle_follow(NFL, "134934")
        p = mock.patch.object(sf, "_fetch_next", return_value=tuple(events))
        fetch = p.start()
        self.addCleanup(p.stop)
        return fetch

    def test_game_goes_up_at_kickoff_once(self) -> None:
        game = _ev("1", start=NOW + timedelta(hours=1))
        fetch = self._follow(game)
        self.assertIsNone(sf.check_once(now=NOW, mono=0.0))
        self.assertIsNone(ss.selected_event())
        self.assertEqual(sf.check_once(now=NOW + timedelta(hours=1, minutes=1), mono=1.0).event_id, "1")
        self.assertEqual(ss.selected_event().event_id, "1")
        # Turned off by hand: the watcher does not bring it back.
        ss.clear_selection()
        self.assertIsNone(sf.check_once(now=NOW + timedelta(hours=1, minutes=5), mono=2.0))
        # Cached between checks, re-asked once the game is near.
        self.assertEqual(fetch.call_count, 1)
        sf.check_once(now=NOW + timedelta(hours=1), mono=11 * 60.0)
        self.assertEqual(fetch.call_count, 2)

    def test_manual_pick_wins(self) -> None:
        self._follow(_ev("1", start=NOW - timedelta(minutes=5)))
        ss.select_event(_ev("9", start=NOW, status="Q1"))
        self.assertIsNone(sf.check_once(now=NOW, mono=0.0))
        self.assertEqual(ss.selected_event().event_id, "9")

    def test_auto_off_or_nothing_followed_does_nothing(self) -> None:
        with mock.patch.object(sf, "_fetch_next") as fetch:
            self.assertIsNone(sf.check_once(now=NOW, mono=0.0))
            sf.toggle_follow(NFL, "134934")
            sf.set_auto(False)
            self.assertIsNone(sf.check_once(now=NOW, mono=0.0))
        fetch.assert_not_called()

    def test_hidden_scores_stop_auto_games(self) -> None:
        self._follow(_ev("1", start=NOW - timedelta(minutes=5)))
        sf.toggle_scores()
        self.assertIsNone(sf.check_once(now=NOW, mono=0.0))
        self.assertIsNone(ss.selected_event())

    def test_finished_and_far_games_are_skipped(self) -> None:
        shown: set[str] = set()
        done = _ev("1", start=NOW - timedelta(hours=3), status="FT")
        late = _ev("2", start=NOW - timedelta(hours=6), status="Q4")
        soon = _ev("3", start=NOW + timedelta(minutes=10))
        self.assertIsNone(sf.pick_game([done, late, soon], now=NOW, shown=shown))
        on = _ev("4", start=NOW - timedelta(hours=1), status="Q2")
        self.assertEqual(sf.pick_game([done, on, soon], now=NOW, shown=shown).event_id, "4")
        self.assertIsNone(sf.pick_game([on], now=NOW, shown={"4"}))

    def test_rate_limit_stops_the_round(self) -> None:
        sf.toggle_follow(NFL, "a")
        sf.toggle_follow(NFL, "b")
        with mock.patch.object(sf, "_fetch_next", side_effect=ss.RateLimited()) as fetch:
            self.assertIsNone(sf.check_once(now=NOW, mono=0.0))
        self.assertEqual(fetch.call_count, 1)


class SportsPageTests(_Reset):
    def _widget(self) -> MainSettingsWidget:
        w = MainSettingsWidget()
        with mock.patch.object(MainSettingsState, "refresh_network_ssid"):
            w.state.enter_pigeon_settings()
        ring = ps.pigeon_focus_ring(w.state.pigeon_view)
        w.state.pigeon_focus_index = ring.index("sports")
        self.assertEqual(w.activate(), "sports_page_open")
        return w

    def _focus(self, w: MainSettingsWidget, focus_id: str) -> None:
        w.state.pigeon_focus_index = ps.pigeon_focus_ring(w.state.pigeon_view).index(focus_id)

    def test_ring_and_landing(self) -> None:
        w = self._widget()
        self.assertEqual(w.state.pigeon_view, sps.SPORTS_VIEW)
        self.assertEqual(w.state.pigeon_focused_id, "league:4391")
        self.assertEqual(
            sps.sports_focus_ring(),
            (
                "exit",
                *(f"league:{lg.league_id}" for lg in teams.FOLLOW_LEAGUES),
                "sports_scores",
                "sports_followed",
                "sports_today",
            ),
        )

    def test_back_returns_to_general_on_sports(self) -> None:
        w = self._widget()
        self._focus(w, "exit")
        self.assertEqual(w.activate(), "sports_page_back")
        self.assertEqual(w.state.pigeon_view, "general")
        self.assertEqual(w.state.pigeon_focused_id, "sports")
        self.assertTrue(w.state.show_pigeon_settings)

    def test_follow_teams_from_the_list(self) -> None:
        w = self._widget()
        self.assertEqual(w.activate(), "sports_teams_open:4391")
        first = teams.teams(NFL)[0]
        w.navigate(forward=True)
        self.assertEqual(w.activate(), f"sports_follow:{NFL}:{first.team_id}:on")
        self.assertIn(first.team_id, sf.followed(NFL))
        # Stays open to pick more; BACK (row 0) closes it.
        self.assertEqual(w.state.sports_team_league, NFL)
        w.navigate(forward=False)
        self.assertEqual(w.activate(), "sports_teams_back")
        self.assertEqual(w.state.sports_team_league, "")
        self.assertEqual(w.state.pigeon_view, sps.SPORTS_VIEW)

    def test_ncaa_opens_on_letters(self) -> None:
        ncaab = "4607"
        w = self._widget()
        self._focus(w, f"league:{ncaab}")
        self.assertEqual(w.activate(), f"sports_teams_open:{ncaab}")
        self.assertTrue(sps.letter_mode(w.state))
        letters = sps.letter_entries(ncaab)
        self.assertEqual(letters[0][0], sps.TEAM_BACK)
        m = [p for p, label in letters].index("letter:M")
        w.state.sports_team_index = m
        self.assertEqual(w.activate(), "sports_letter:M")
        names = [label for _p, label in sps.current_entries(w.state)[1:]]
        self.assertIn("Michigan", names)
        self.assertTrue(all(n.upper().startswith("M") for n in names))
        w.navigate(forward=True)
        team = sps.current_entries(w.state)[1][0]
        self.assertTrue(w.activate().endswith(f":{team}:on"))
        # BACK → the grid, on M; BACK again → the page.
        w.navigate(forward=False)
        self.assertEqual(w.activate(), "sports_letters_back")
        self.assertEqual(w.state.sports_team_index, m)
        self.assertEqual(sps.letters_with_follows(ncaab), frozenset({"M"}))
        w.state.sports_team_index = 0
        self.assertEqual(w.activate(), "sports_teams_back")
        self.assertEqual(w.state.sports_team_league, "")

    def test_pro_leagues_skip_letters(self) -> None:
        w = self._widget()
        w.activate()
        self.assertFalse(sps.letter_mode(w.state))
        self.assertEqual(len(sps.current_entries(w.state)), 33)

    def test_team_letter(self) -> None:
        self.assertEqual(sps.team_letter("Ole Miss"), "O")
        self.assertEqual(sps.team_letter("49ers"), "#")

    def test_followed_teams_tile_toggles(self) -> None:
        w = self._widget()
        self._focus(w, "sports_followed")
        self.assertEqual(w.activate(), "sports_followed:off")
        self.assertFalse(sf.auto_enabled())
        self.assertEqual(w.activate(), "sports_followed:auto")

    def test_hiding_scores_greys_out_followed_teams(self) -> None:
        w = self._widget()
        self._focus(w, "sports_scores")
        self.assertEqual(w.activate(), "sports_scores:hide")
        self.assertFalse(sf.scores_shown())
        self.assertNotIn("sports_followed", ps.pigeon_focus_ring(w.state.pigeon_view))
        # Still on SCORES; the next stop skips FOLLOWED TEAMS.
        self.assertEqual(w.state.pigeon_focused_id, "sports_scores")
        w.navigate(forward=True)
        self.assertEqual(w.state.pigeon_focused_id, "sports_today")
        # The AUTO choice is kept, but nothing comes up on its own.
        self.assertTrue(sf.auto_enabled())
        self.assertFalse(sf.auto_active())
        w.navigate(forward=False)
        self.assertEqual(w.activate(), "sports_scores:show")
        self.assertTrue(sf.auto_active())

    def test_today_opens_the_game_list(self) -> None:
        w = self._widget()
        self._focus(w, "sports_today")
        self.assertEqual(w.activate(), "sports_dropdown_open")
        self.assertTrue(w.state.sports_dropdown_open)

    def test_page_and_list_render(self) -> None:
        st = MainSettingsState()
        st.pigeon_view = sps.SPORTS_VIEW
        page = ps.render_pigeon_settings_bgra(st)
        self.assertEqual(page.shape[:2], (800, 1280))
        sf.toggle_follow(NFL, teams.teams(NFL)[0].team_id)
        badged = ps.render_pigeon_settings_bgra(st)
        self.assertFalse(np.array_equal(page, badged))
        st.sports_team_league = NFL
        listed = ps.render_pigeon_settings_bgra(st)
        self.assertFalse(np.array_equal(badged, listed))
        st.sports_team_league = "4479"
        self.assertFalse(np.array_equal(listed, ps.render_pigeon_settings_bgra(st)))


class ScrollTests(unittest.TestCase):
    def test_thumb_tracks_the_window(self) -> None:
        self.assertIsNone(ps.scroll_thumb(first=0, visible=8, total=8, height=400))
        top, length = ps.scroll_thumb(first=0, visible=8, total=32, height=400)
        self.assertEqual((top, length), (0, 100))
        top, length = ps.scroll_thumb(first=24, visible=8, total=32, height=400)
        self.assertEqual(top + length, 400)
        mid, _ = ps.scroll_thumb(first=12, visible=8, total=32, height=400)
        self.assertEqual(mid, 150)
        # Long lists keep a grabbable thumb.
        self.assertEqual(ps.scroll_thumb(first=0, visible=8, total=1000, height=400)[1], 28)


class ListCacheTests(_Reset):
    def setUp(self) -> None:
        super().setUp()
        import tempfile
        from pathlib import Path

        self.dir = Path(tempfile.mkdtemp())
        p = mock.patch.object(ss, "_events_path", return_value=self.dir / "sports_events.json")
        p.start()
        self.addCleanup(p.stop)
        ss._disk_enabled = True
        ss._disk_loaded = False

    def test_saved_list_shows_before_the_fetch(self) -> None:
        now = datetime.now(timezone.utc)
        game = _ev("1", start=now + timedelta(hours=1))
        ss._save_disk_events((game,))
        events, loading, _failed = ss.events_snapshot()
        self.assertEqual([e.event_id for e in events], ["1"])
        self.assertEqual(events[0].start_utc, game.start_utc)
        self.assertFalse(loading)

    def test_cut_short_refresh_keeps_old_rows(self) -> None:
        now = datetime.now(timezone.utc)
        ss._events = (_ev("old", start=now + timedelta(hours=2)),)
        fresh = _ev("new", start=now + timedelta(hours=1))

        def fetch(**_kw):
            ss._blocked_until_mono = ss.time.monotonic() + 60
            return [fresh], False

        threads = []
        with mock.patch.object(ss, "fetch_available_events", side_effect=fetch), mock.patch.object(
            ss.threading, "Thread", side_effect=lambda **kw: threads.append(kw) or mock.Mock()
        ):
            self.assertTrue(ss.refresh_events(force=True))
            threads[0]["target"]()
        self.assertEqual(sorted(e.event_id for e in ss.events_snapshot()[0]), ["new", "old"])


if __name__ == "__main__":
    unittest.main()
