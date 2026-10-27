"""City abbreviations for team names that do not fit."""

from __future__ import annotations

import os
import sys
import unittest

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import sports_names as names  # noqa: E402


def _width_under(n: int):
    return lambda t: len(t) <= n


class ShortNameTests(unittest.TestCase):
    def test_city_codes(self) -> None:
        cases = {
            "Philadelphia Eagles": "PHI Eagles",
            "Los Angeles Rams": "LA Rams",
            "New York Rangers": "NY Rangers",
            "St. Louis Cardinals": "STL Cardinals",
            "Boston Red Sox": "BOS Red Sox",
            "Toronto Maple Leafs": "TOR Maple Leafs",
            "Vegas Golden Knights": "VEG Golden Knights",
            "Oklahoma City Thunder": "OKC Thunder",
            "Golden State Valkyries": "GS Valkyries",
            "Jacksonville Jaguars": "JAX Jaguars",
        }
        for full, short in cases.items():
            self.assertEqual(names.short_team_name(full), short, full)

    def test_unknown_and_ncaa_names_are_left_alone(self) -> None:
        for name in ("Athletics", "Maryland-Eastern Shore", "Michigan State", "Home 1"):
            self.assertEqual(names.short_team_name(name), name)

    def test_fit_prefers_full_then_short_then_cut(self) -> None:
        self.assertEqual(names.fit_name("Dallas Cowboys", _width_under(20)), "DALLAS COWBOYS")
        self.assertEqual(names.fit_name("Philadelphia Eagles", _width_under(12)), "PHI EAGLES")
        self.assertEqual(names.fit_name("Philadelphia Eagles", _width_under(8)), "EAGLES")
        self.assertEqual(names.fit_name("Philadelphia Eagles", _width_under(4)), "EAG…")
        self.assertEqual(names.fit_name("Maryland-Eastern Shore", _width_under(10)), "MARYLAND-…")

    def test_matchup(self) -> None:
        fits = _width_under(30)
        self.assertEqual(
            names.fit_matchup("Philadelphia Eagles", "Dallas Cowboys", fits),
            "PHI EAGLES VS DAL COWBOYS",
        )
        self.assertEqual(names.fit_matchup("Detroit Lions", "Chicago Bears", fits), "DETROIT LIONS VS CHICAGO BEARS")
        self.assertEqual(
            names.fit_matchup("Columbus Blue Jackets", "Vegas Golden Knights", fits),
            "BLUE JACKETS VS GOLDEN KNIGHTS",
        )


if __name__ == "__main__":
    unittest.main()
