"""The sports page over the Control API (``/sports``)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import app_state, runtime_paths  # noqa: E402
from pigeon import sports_follow as sf  # noqa: E402
from pigeon import sports_scores as ss  # noqa: E402
from pigeon.control_api.server import ControlService  # noqa: E402
from pigeon.sports_teams import teams  # noqa: E402

NFL = "4391"


def _ev(eid: str, *, status: str = "Q2", start_h: float = -1.0) -> ss.SportsEvent:
    start = datetime.now(timezone.utc) + timedelta(hours=start_h)
    ev = ss.parse_event(
        {
            "idEvent": eid,
            "strLeague": "NFL",
            "idLeague": NFL,
            "strHomeTeam": "Philadelphia Eagles",
            "strAwayTeam": "Dallas Cowboys",
            "intHomeScore": "21",
            "intAwayScore": "17",
            "strStatus": status,
            "strTimestamp": start.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )
    assert ev is not None
    return ev


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = runtime_paths._CACHED
        runtime_paths._CACHED = Path(self._tmp.name)
        app_state._STATE_TEXT_CACHE = None
        app_state._STATE_PARSED_CACHE = None
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: setattr(runtime_paths, "_CACHED", self._prev))
        ss._reset_for_tests()
        sf._cache = None  # load from the temp state dir
        self.addCleanup(ss._reset_for_tests)
        self.addCleanup(sf._reset_for_tests)
        for target, kw in (
            ("_start_poller", {}),
            ("fetch_available_events", {"return_value": ([], False)}),
        ):
            p = mock.patch.object(ss, target, **kw)
            p.start()
            self.addCleanup(p.stop)
        self.svc = ControlService(run_on_ui=lambda fn: fn())
        self.token = self.svc.auth.claim(self.svc.auth.pairing_code, "t", "c1")

    def call(self, method, path, body=None):
        return self.svc.handle(method, "/api/v1" + path, {}, self.token, body)


class SportsSettingsTests(_Base):
    def test_capability_and_defaults(self) -> None:
        self.assertIn("sports", self.call("GET", "/capabilities")[1]["capabilities"])
        st, d = self.call("GET", "/sports")
        self.assertEqual(st, 200)
        self.assertEqual((d["scores_shown"], d["followed_auto"], d["followed_active"]), (True, True, True))
        self.assertEqual([lg["name"] for lg in d["leagues"]][:3], ["NFL", "MLB", "NBA"])
        ncaab = next(lg for lg in d["leagues"] if lg["id"] == "4607")
        self.assertTrue(ncaab["by_letter"])
        self.assertIsNone(d["board"])

    def test_hiding_scores_turns_followed_teams_off(self) -> None:
        st, d = self.call("PATCH", "/sports", {"scores_shown": False})
        self.assertEqual(st, 200)
        self.assertEqual((d["scores_shown"], d["followed_auto"], d["followed_active"]), (False, True, False))
        st, d = self.call("PATCH", "/sports", {"followed_auto": False, "scores_shown": True})
        self.assertEqual((d["scores_shown"], d["followed_auto"]), (True, False))
        # Saved to state.json.
        app_state._STATE_TEXT_CACHE = None
        self.assertFalse(app_state.read_app_state()["sports_follow"]["auto"])

    def test_patch_validation(self) -> None:
        self.assertEqual(self.call("PATCH", "/sports", {"scores_shown": "no"})[1]["error"]["details"]["fields"], ["scores_shown"])
        self.assertEqual(self.call("PATCH", "/sports", {"nope": True})[0], 400)
        self.assertEqual(self.call("PATCH", "/sports", {})[0], 400)


class FollowTests(_Base):
    def test_teams_and_follow(self) -> None:
        st, d = self.call("GET", f"/sports/leagues/{NFL}/teams")
        self.assertEqual(st, 200)
        self.assertEqual(len(d["teams"]), 32)
        team = d["teams"][0]
        self.assertFalse(team["followed"])
        self.assertEqual(self.call("PUT", f"/sports/leagues/{NFL}/teams/{team['id']}/follow")[0], 204)
        self.assertEqual(self.call("PUT", f"/sports/leagues/{NFL}/teams/{team['id']}/follow")[0], 204)  # idempotent
        self.assertEqual(sf.followed(NFL), frozenset({team["id"]}))
        nfl = next(lg for lg in self.call("GET", "/sports")[1]["leagues"] if lg["id"] == NFL)
        self.assertEqual(nfl["followed"], [team["id"]])
        self.assertEqual(self.call("DELETE", f"/sports/leagues/{NFL}/teams/{team['id']}/follow")[0], 204)
        self.assertEqual(sf.followed(NFL), frozenset())

    def test_unknown_league_or_team(self) -> None:
        self.assertEqual(self.call("GET", "/sports/leagues/nope/teams")[0], 404)
        self.assertEqual(self.call("PUT", f"/sports/leagues/{NFL}/teams/999/follow")[0], 404)
        other = teams("4424")[0].team_id  # an MLB team is not an NFL team
        self.assertEqual(self.call("PUT", f"/sports/leagues/{NFL}/teams/{other}/follow")[0], 404)

    def test_ncaa_teams_carry_letters(self) -> None:
        d = self.call("GET", "/sports/leagues/4607/teams")[1]
        self.assertTrue(d["league"]["by_letter"])
        self.assertEqual(next(t for t in d["teams"] if t["name"] == "Michigan")["letter"], "M")


class GamesTests(_Base):
    def test_games_and_board(self) -> None:
        ss._events = (_ev("1"), _ev("2", status="NS", start_h=2))
        ss._events_mono = 1e18
        st, d = self.call("GET", "/sports/games")
        self.assertEqual(st, 200)
        live = d["games"][0]
        self.assertEqual((live["id"], live["home_score"], live["phase"]), ("1", "21", "live"))
        self.assertIsNone(d["games"][1]["home_score"])  # not started
        st, d = self.call("PUT", "/sports/board", {"event_id": "1"})
        self.assertEqual((st, d["board"]["id"]), (200, "1"))
        self.assertEqual(ss.selected_event().event_id, "1")
        self.assertEqual(self.call("PUT", "/sports/board", {"event_id": "9"})[0], 404)
        self.assertEqual(self.call("PUT", "/sports/board", {})[0], 400)
        self.assertEqual(self.call("DELETE", "/sports/board")[0], 204)
        self.assertIsNone(ss.selected_event())

    def test_games_say_when_the_list_is_stale(self) -> None:
        ss._events = (_ev("1"),)
        ss._events_mono = 1e18
        self.assertFalse(self.call("GET", "/sports/games")[1]["stale"])
        ss._events_stale = True
        ss._events_error = True
        d = self.call("GET", "/sports/games")[1]
        self.assertTrue(d["stale"])
        self.assertFalse(d["failed"])  # rows are still there to show
        self.assertEqual(len(d["games"]), 1)

    def test_hidden_scores_are_not_sent(self) -> None:
        ss._events = (_ev("1"),)
        ss._events_mono = 1e18
        self.call("PATCH", "/sports", {"scores_shown": False})
        game = self.call("GET", "/sports/games")[1]["games"][0]
        self.assertIsNone(game["home_score"])
        self.assertEqual(game["status"], "Q2")


if __name__ == "__main__":
    unittest.main()
