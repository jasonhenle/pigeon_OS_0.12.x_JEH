"""TMDb title matching: accents and trailing parentheticals."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pigeon.tmdb_poster import _norm_query, strip_trailing_parenthetical  # noqa: E402


class TitleMatchingTests(unittest.TestCase):
    def test_accents_fold(self) -> None:
        self.assertEqual(_norm_query("Butterbean's Café"), _norm_query("Butterbean's Cafe"))

    def test_pipe_and_colon_match(self) -> None:
        self.assertEqual(
            _norm_query("Taylor Swift | The Eras Tour"), _norm_query("Taylor Swift: The Eras Tour")
        )

    def test_trailing_parenthetical_is_stripped(self) -> None:
        self.assertEqual(
            strip_trailing_parenthetical("Taylor Swift | The Eras Tour (Taylor's Version)"),
            "Taylor Swift | The Eras Tour",
        )
        self.assertEqual(strip_trailing_parenthetical("Dune (2021)"), "Dune")
        self.assertEqual(strip_trailing_parenthetical("(Untitled)"), "(Untitled)")
        self.assertEqual(strip_trailing_parenthetical("Elf"), "Elf")


if __name__ == "__main__":
    unittest.main()
