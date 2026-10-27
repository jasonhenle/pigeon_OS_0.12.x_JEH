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
            ("exit", *(f"league:{lg.league_id}" for lg in teams.FOLLOW_LEAGUES), "sports_auto", "sports_games"),
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

    def test_auto_tile_toggles(self) -> None:
        w = self._widget()
        self._focus(w, "sports_auto")
        self.assertEqual(w.activate(), "sports_auto:off")
        self.assertFalse(sf.auto_enabled())
        self.assertEqual(w.activate(), "sports_auto:on")

    def test_page_and_list_render(self) -> None:
        st = MainSettingsState()
        st.pigeon_view = sps.SPORTS_VIEW
        page = ps.render_pigeon_settings_bgra(st)
        self.assertEqual(page.shape[:2], (800, 1280))
        sf.toggle_follow(NFL, teams.teams(NFL)[0].team_id)
        badged = ps.render_pigeon_settings_bgra(st)
        self.assertFalse(np.array_equal(page, badged))
        st.sports_team_league = NFL
        self.assertFalse(np.array_equal(badged, ps.render_pigeon_settings_bgra(st)))


if __name__ == "__main__":
    unittest.main()
