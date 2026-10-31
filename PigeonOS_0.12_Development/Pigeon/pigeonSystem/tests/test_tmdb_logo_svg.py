"""SVG TMDb logos are fetched as their PNG rendition."""

from __future__ import annotations

import os
import sys
import unittest

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import tmdb_poster as tp  # noqa: E402


def _logo(path: str, votes: float) -> dict:
    return {"iso_639_1": "en", "file_path": path, "vote_average": votes}


class LogoPathTests(unittest.TestCase):
    def test_svg_logo_uses_png_rendition(self) -> None:
        images = {
            "logos": [
                _logo("/b1rdD4sllG4olG5TTClp5Ikjdr7.svg", 3.3),
                _logo("/c4chOkNTnwNMFhxkzi6tCJ2UzsM.png", 1.7),
            ]
        }
        self.assertEqual(
            tp._logo_path_from_images(images), "/b1rdD4sllG4olG5TTClp5Ikjdr7.png"
        )

    def test_png_logo_unchanged(self) -> None:
        images = {"logos": [_logo("/abc.png", 2.0)]}
        self.assertEqual(tp._logo_path_from_images(images), "/abc.png")

    def test_no_english_logo(self) -> None:
        images = {"logos": [{"iso_639_1": "fr", "file_path": "/x.svg"}]}
        self.assertIsNone(tp._logo_path_from_images(images))


if __name__ == "__main__":
    unittest.main()
