"""Process-wide cache for PIL fonts.

``ImageFont.truetype`` opens and parses the font file every time it is called.
Several widgets fit text by binary-searching font sizes on every redraw, so the
same (path, size) pairs were being re-opened many times per second. These
helpers return a shared font object per (path, size) instead.

Font objects are shared, so callers must not mutate them (e.g. ``set_variation``).
"""

from __future__ import annotations

from functools import lru_cache
from os import PathLike

from PIL import ImageFont

FontLike = ImageFont.FreeTypeFont | ImageFont.ImageFont


@lru_cache(maxsize=512)
def _truetype_or_error(path: str, size: int) -> FontLike | OSError:
    try:
        return ImageFont.truetype(path, size)
    except OSError as exc:  # cache misses too, so a missing font is not retried every frame
        return exc


@lru_cache(maxsize=1)
def default_font() -> FontLike:
    return ImageFont.load_default()


def truetype(path: str | PathLike[str], size: int) -> FontLike:
    """Cached drop-in for ``ImageFont.truetype(path, size)``; raises ``OSError`` the same way."""
    got = _truetype_or_error(str(path), int(size))
    if isinstance(got, OSError):
        raise got
    return got


def load_font(path: str | PathLike[str] | None, size: int) -> FontLike:
    """Cached ``truetype`` that falls back to Pillow's default font when ``path`` is empty or unreadable."""
    if not path:
        return default_font()
    got = _truetype_or_error(str(path), int(size))
    return default_font() if isinstance(got, OSError) else got


__all__ = ["default_font", "load_font", "truetype"]
