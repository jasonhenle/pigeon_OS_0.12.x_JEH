"""Live scoreboard: full-display takeover while a sports event is picked.

Drawn on the 1280×800 design canvas, home on the left (TheSportsDB lists
events "home vs away")::

            [league badge]  LEAGUE NAME

     [home badge]    21  –  17    [away badge]
                     (● Q3 8:12)
      HOME NAME                    AWAY NAME

Badges that have not downloaded yet are UI-colored discs with the team's
initials. Frames are cached on :func:`pigeon.sports_scores.board_token`.
"""

from __future__ import annotations

import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

from pigeon.compositing import cv_resize_interp
from pigeon.design import DESIGN_H, DESIGN_W

_LEAGUE_Y = 92
_LEAGUE_BADGE_H = 76
_LEAGUE_FONT_PX = 40
_BADGE_BOX = 290
_BADGE_CX = (230, DESIGN_W - 230)
_BADGE_CY = 360
_NAME_Y = 560
_NAME_FONT_PX = 38
_NAME_MAX_W = 420
_SCORE_CX = (500, DESIGN_W - 500)
_SCORE_FONT_PX = 170
_DASH_FONT_PX = 110
_PILL_Y = 520
_PILL_FONT_PX = 34
_PILL_H = 62
_PILL_PAD_X = 30
_LIVE_DOT_BGR = (0, 0, 255)
_INK = (255, 255, 255)
_DIM_INK = (150, 150, 150)

_cache: tuple[tuple, np.ndarray] | None = None
_ui_hex_cache: tuple[float, str] = (0.0, "")


def _ui_rgb() -> tuple[int, int, int]:
    global _ui_hex_cache
    now = time.monotonic()
    if now - _ui_hex_cache[0] > 5.0 or not _ui_hex_cache[1]:
        try:
            from pigeon.widgets.ui_color_settings import current_ui_picker_key, hex_for_color_key

            hx = hex_for_color_key("ui", current_ui_picker_key())
        except Exception:
            hx = "#2A7FFF"
        _ui_hex_cache = (now, hx or "#2A7FFF")
    h = _ui_hex_cache[1].lstrip("#")
    try:
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (42, 127, 255)


def _font(role: str, px: int):
    from pigeon.font_cache import load_font
    from pigeon.font_paths import resolve_ui_font_bold, resolve_ui_font_extrabold, resolve_ui_font_semibold

    path = {
        "extrabold": resolve_ui_font_extrabold() or resolve_ui_font_bold(),
        "bold": resolve_ui_font_bold(),
        "semibold": resolve_ui_font_semibold() or resolve_ui_font_bold(),
    }.get(role)
    return load_font(path, px)


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while len(text) > 1 and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1].rstrip()
    return text + "…"


def _initials(name: str) -> str:
    words = [w for w in name.replace("-", " ").split() if w[:1].isalnum()]
    return "".join(w[0] for w in words[:3]).upper() or "?"


def _paste_badge(canvas: Image.Image, bgra: np.ndarray | None, cx: int, cy: int, box: int, name: str) -> None:
    if bgra is None:
        draw = ImageDraw.Draw(canvas)
        r = box // 2 - 10
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*_ui_rgb(), 255))
        draw.text((cx, cy), _initials(name), font=_font("extrabold", box // 4), fill=_INK, anchor="mm")
        return
    h, w = bgra.shape[:2]
    s = box / float(max(h, w))
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    small = cv2.resize(bgra, (nw, nh), interpolation=cv_resize_interp(w, h, nw, nh))
    img = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGRA2RGBA))
    canvas.alpha_composite(img, (cx - nw // 2, cy - nh // 2))


def render_scoreboard_rgba(ev, *, badges: dict[str, np.ndarray | None] | None = None) -> Image.Image:
    """Design-size RGBA board for ``ev`` (a :class:`pigeon.sports_scores.SportsEvent`)."""
    from pigeon.sports_scores import LIVE, UPCOMING, badge_bgra, status_label

    def badge(url: str) -> np.ndarray | None:
        if badges is not None:
            return badges.get(url)
        return badge_bgra(url)

    canvas = Image.new("RGBA", (DESIGN_W, DESIGN_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(canvas)

    # League: badge + name, centered as one row.
    lfont = _font("semibold", _LEAGUE_FONT_PX)
    league = _fit_text(draw, ev.league.upper(), lfont, DESIGN_W - 300)
    lb = badge(ev.league_badge)
    lw = int(draw.textlength(league, font=lfont))
    bw = 0
    if lb is not None:
        bh, bwi = lb.shape[:2]
        bw = int(round(bwi * _LEAGUE_BADGE_H / float(max(1, bh))))
        bw = min(bw, _LEAGUE_BADGE_H * 3)
    gap = 20 if bw and lw else 0
    x = (DESIGN_W - (bw + gap + lw)) // 2
    if lb is not None and bw:
        _paste_badge(canvas, lb, x + bw // 2, _LEAGUE_Y, max(bw, _LEAGUE_BADGE_H), ev.league)
    draw.text((x + bw + gap, _LEAGUE_Y), league, font=lfont, fill=_INK, anchor="lm")

    # Teams.
    nfont = _font("bold", _NAME_FONT_PX)
    for cx, name, url in (
        (_BADGE_CX[0], ev.home, ev.home_badge),
        (_BADGE_CX[1], ev.away, ev.away_badge),
    ):
        _paste_badge(canvas, badge(url), cx, _BADGE_CY, _BADGE_BOX, name)
        draw.text(
            (cx, _NAME_Y),
            _fit_text(draw, name.upper(), nfont, _NAME_MAX_W),
            font=nfont,
            fill=_INK,
            anchor="mt",
        )

    # Scores; "VS" until the game starts.
    phase = ev.phase
    if phase == UPCOMING:
        draw.text((DESIGN_W // 2, _BADGE_CY), "VS", font=_font("extrabold", _DASH_FONT_PX), fill=_DIM_INK, anchor="mm")
    else:
        sfont = _font("extrabold", _SCORE_FONT_PX)
        for cx, score in ((_SCORE_CX[0], ev.home_score), (_SCORE_CX[1], ev.away_score)):
            draw.text((cx, _BADGE_CY), score or "0", font=sfont, fill=_INK, anchor="mm")
        draw.text((DESIGN_W // 2, _BADGE_CY), "–", font=_font("bold", _DASH_FONT_PX), fill=_DIM_INK, anchor="mm")

    # Status pill.
    pfont = _font("bold", _PILL_FONT_PX)
    label = status_label(ev)
    dot = phase == LIVE
    tw = int(draw.textlength(label, font=pfont))
    dot_w = 34 if dot else 0
    pw = tw + dot_w + 2 * _PILL_PAD_X
    px0 = (DESIGN_W - pw) // 2
    py0 = _PILL_Y - _PILL_H // 2
    ui = _ui_rgb()
    draw.rounded_rectangle(
        (px0, py0, px0 + pw, py0 + _PILL_H),
        radius=_PILL_H // 2,
        fill=(0, 0, 0, 255),
        outline=(*ui, 255),
        width=3,
    )
    if dot:
        dcx = px0 + _PILL_PAD_X + 10
        b, g, r = _LIVE_DOT_BGR
        draw.ellipse((dcx - 10, _PILL_Y - 10, dcx + 10, _PILL_Y + 10), fill=(r, g, b, 255))
    draw.text((px0 + _PILL_PAD_X + dot_w + tw // 2, _PILL_Y), label, font=pfont, fill=_INK, anchor="mm")
    return canvas


def scoreboard_frame_bgr(width: int, height: int) -> np.ndarray | None:
    """Board at ``width``×``height`` while an event is picked; None otherwise."""
    global _cache
    from pigeon.sports_scores import board_token, scoreboard_active, selected_event

    if not scoreboard_active():
        return None
    ev = selected_event()
    if ev is None:
        return None
    w, h = max(1, int(width)), max(1, int(height))
    key = (board_token(), _ui_rgb(), w, h)
    if _cache is not None and _cache[0] == key:
        return _cache[1]
    bgr = cv2.cvtColor(np.asarray(render_scoreboard_rgba(ev)), cv2.COLOR_RGBA2BGR)
    if (w, h) != (DESIGN_W, DESIGN_H):
        bgr = cv2.resize(bgr, (w, h), interpolation=cv_resize_interp(DESIGN_W, DESIGN_H, w, h))
    _cache = (key, np.ascontiguousarray(bgr))
    return _cache[1]


__all__ = ["render_scoreboard_rgba", "scoreboard_frame_bgr"]
