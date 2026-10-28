"""
settings_pigeon FACTORY RESET warning.

Opened when RESET is activated on the Pigeon page. The page dims behind a card
that says what a factory reset erases; the knob moves between CANCEL and RESET
(CANCEL first, so a stray press never wipes anything) and a press picks one.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw

FOCUS_CANCEL = "cancel"
FOCUS_RESET = "reset"
FOCUS_RING: tuple[str, ...] = (FOCUS_CANCEL, FOCUS_RESET)

TITLE = "FACTORY RESET PIGEON?"
WARNING_LINES = (
    "Theme, clock, location, rooms and paired",
    "players and receivers go back to their defaults.",
    "This can't be undone.",
)

_CARD_W, _CARD_H = 760, 420
_PILL_W, _PILL_H, _PILL_GAP = 220, 64, 40
_DIM = 0.35  # page brightness left behind the card
_WARN_RGB = (255, 0, 0)


def _ink_rgb(state) -> tuple[int, int, int]:
    from pigeon.widgets.pigeon_settings import page_ink_rgb

    return page_ink_rgb(state)


def _simple(state) -> bool:
    from pigeon.widgets.options_settings import ui_is_simple

    return bool(ui_is_simple(state))


def _rounded_patch(
    w: int,
    h: int,
    *,
    radius: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    width: int = 3,
) -> np.ndarray:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        (1, 1, w - 2, h - 2), radius=radius, fill=fill, outline=outline, width=width if outline else 0
    )
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)


def composite_reset_confirm_over_bgra(frame: np.ndarray, state) -> np.ndarray:
    """Dim *frame* and draw the warning card with CANCEL / RESET on top."""
    from pigeon.widgets.settings_main_1280 import _blit, _draw_centered_text

    out = frame.copy()
    out[:, :, :3] = (out[:, :, :3].astype(np.float32) * _DIM).astype(np.uint8)
    fh, fw = int(out.shape[0]), int(out.shape[1])
    cx = (fw - _CARD_W) // 2
    cy = (fh - _CARD_H) // 2
    ink = _ink_rgb(state)
    simple = _simple(state)

    card_fill = (0, 0, 0, 255) if simple else (35, 31, 32, 255)
    card_line = (*ink, 255) if simple else (*_WARN_RGB, 255)
    _blit(out, _rounded_patch(_CARD_W, _CARD_H, radius=28, fill=card_fill, outline=card_line, width=4), cx, cy)

    title_rgb = ink if simple else _WARN_RGB
    _draw_centered_text(out, TITLE, box=(cx + 30, cy + 34, _CARD_W - 60, 70), size=60, fill=title_rgb, digital=True)
    for i, line in enumerate(WARNING_LINES):
        _draw_centered_text(
            out, line, box=(cx + 40, cy + 128 + i * 44, _CARD_W - 80, 40), size=30, fill=ink, digital=False
        )

    focus = reset_confirm_focused(state)
    px = cx + (_CARD_W - (_PILL_W * 2 + _PILL_GAP)) // 2
    py = cy + _CARD_H - _PILL_H - 34
    for label, key, x in (("CANCEL", FOCUS_CANCEL, px), ("RESET", FOCUS_RESET, px + _PILL_W + _PILL_GAP)):
        on = focus == key
        if simple:
            fill = (*ink, 255) if on else (0, 0, 0, 255)
            line = (*ink, 255)
        else:
            fill = (255, 255, 255, 255) if on else (26, 26, 26, 255)
            line = (*_WARN_RGB, 255) if key == FOCUS_RESET else (0, 0, 0, 255)
        _blit(out, _rounded_patch(_PILL_W, _PILL_H, radius=_PILL_H // 2, fill=fill, outline=line), x, py)
        text_rgb = (0, 0, 0) if on else (ink if simple else (255, 255, 255))
        _draw_centered_text(out, label, box=(x, py, _PILL_W, _PILL_H), size=40, fill=text_rgb, digital=True)
    return out


def reset_confirm_focused(state) -> str:
    return FOCUS_RING[int(getattr(state, "reset_confirm_focus_index", 0)) % len(FOCUS_RING)]
