"""
Sports page — ``settings/pigeon/settings_pigeon_sports.svg``.

Opened from settings_pigeon → **SPORTS** (shown as ``pigeon_view == "sports"``).
Seven league logos, left → right in the art: NFL, MLB, NBA, WNBA,
NCAA football, NCAA basketball, NHL. Under them:

* **AUTO SCORES** — on / off for :mod:`pigeon.sports_follow`'s watcher.
* **LIVE GAMES** — the manual list of today's games (pick one to watch now).

Focus ring::

    BACK → 7 leagues → AUTO SCORES → LIVE GAMES

Activating a league opens its team list over the page: **BACK** first, then
every team; activating a team follows / unfollows it. The NCAA leagues list
hundreds of teams, so they open on an A–Z grid first and a letter lists only
its teams (BACK returns to the grid). Each logo carries a badge with how many
of its teams are followed; a letter tile gets a dot when it holds one.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from pigeon.design import DESIGN_H, DESIGN_W
from pigeon.settings_layout import SETTINGS_CANVAS_ORIGIN

SPORTS_VIEW = "sports"
FOCUS_AUTO = "sports_auto"
FOCUS_GAMES = "sports_games"
LEAGUE_PREFIX = "league:"
TEAM_BACK = "back"
LETTER_PREFIX = "letter:"
# NCAA football, NCAA basketball.
LETTER_LEAGUES = frozenset({"4479", "4607"})

_COLOR_WHITE = "#FFFFFF"
_COLOR_BLACK = "#000000"
_COLOR_BUTTON = "#231F20"

# Team list: rows centered on the page under a title line (design px).
_TEAMS_ROW_W = 760
_TEAMS_ROW_H = 54
_TEAMS_ROW_GAP = 7
_TEAMS_MAX_ROWS = 8
_TEAMS_FONT_PX = 30
_TEAMS_TITLE_PX = 34
_TEAMS_PANEL_PAD = 22
_TEAMS_RADIUS = 18
_TEAMS_SCROLL_GUTTER = 22
_SCROLL_W = 8
# NCAA letter grid.
_LETTER_COLS = 7
_LETTER_H = 66
_LETTER_FONT_PX = 40
# Top of the panel: just under the header clock.
_TEAMS_TOP = 160
_CHECK_R = 15

# Follow-count badge on a logo tile's top-right corner (SVG units).
_BADGE_R = 20.0
_BADGE_INSET = 4.0
_BADGE_FONT_PX = 24
_HINT_PX = 32


def default_sports_settings_svg_path(assets_dir: Path | str | None = None) -> Path:
    env = os.environ.get("PIGEON_SPORTS_SETTINGS_SVG", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    from pigeon.settings_layout import settings_widget_path

    return settings_widget_path("sports_page", assets_dir=assets_dir)


def league_focus_id(league_id: str) -> str:
    return f"{LEAGUE_PREFIX}{league_id}"


def league_for_focus(focus_id: str) -> str | None:
    fid = str(focus_id or "")
    return fid[len(LEAGUE_PREFIX) :] if fid.startswith(LEAGUE_PREFIX) else None


def sports_focus_ring() -> tuple[str, ...]:
    from pigeon.sports_teams import FOLLOW_LEAGUES

    return ("exit", *(league_focus_id(lg.league_id) for lg in FOLLOW_LEAGUES), FOCUS_AUTO, FOCUS_GAMES)


# --- team list ------------------------------------------------------------------


def uses_letters(league_id: str) -> bool:
    """NCAA lists run to hundreds of teams: pick a letter first."""
    return str(league_id) in LETTER_LEAGUES


def team_letter(name: str) -> str:
    """Index letter for a team name; digits and symbols file under ``#``."""
    ch = next((c for c in str(name).upper() if c.isalnum()), "#")
    return ch if "A" <= ch <= "Z" else "#"


def letter_entries(league_id: str) -> list[tuple[str, str]]:
    """(payload, label): BACK, then each letter that has teams."""
    from pigeon.sports_teams import teams

    letters = sorted({team_letter(t.name) for t in teams(league_id)}, key=lambda c: (c == "#", c))
    return [(TEAM_BACK, "BACK")] + [(f"{LETTER_PREFIX}{c}", c) for c in letters]


def team_list_entries(league_id: str, letter: str = "") -> list[tuple[str, str]]:
    """(payload, label): BACK, then the league's teams A→Z (one letter's, if given)."""
    from pigeon.sports_teams import teams

    rows = [(t.team_id, t.name) for t in teams(league_id) if not letter or team_letter(t.name) == letter]
    return [(TEAM_BACK, "BACK")] + rows


def letter_mode(state) -> bool:
    league_id = str(getattr(state, "sports_team_league", "") or "")
    return uses_letters(league_id) and not getattr(state, "sports_team_letter", "")


def current_entries(state) -> list[tuple[str, str]]:
    """What the open team overlay lists: letters, or (one letter's) teams."""
    league_id = str(getattr(state, "sports_team_league", "") or "")
    if letter_mode(state):
        return letter_entries(league_id)
    return team_list_entries(league_id, str(getattr(state, "sports_team_letter", "") or ""))


def list_window(focus: int, total: int, visible: int) -> int:
    """First visible row that keeps ``focus`` near the middle."""
    return max(0, min(focus - visible // 2, total - visible))


def team_list_rows(state) -> tuple[list[tuple[str, bool, bool]], int, int, int]:
    """(rows on screen as (label, is_team, followed), first visible, focused, total)."""
    from pigeon.sports_follow import followed

    league_id = str(getattr(state, "sports_team_league", "") or "")
    entries = current_entries(state)
    following = followed(league_id)
    focus = int(getattr(state, "sports_team_index", 0)) % len(entries)
    visible = min(_TEAMS_MAX_ROWS, len(entries))
    first = list_window(focus, len(entries), visible)
    rows = [
        (label, payload != TEAM_BACK, payload in following)
        for payload, label in entries[first : first + visible]
    ]
    return rows, first, focus, len(entries)


def letters_with_follows(league_id: str) -> frozenset[str]:
    from pigeon.sports_follow import followed
    from pigeon.sports_teams import teams

    ids = followed(league_id)
    return frozenset(team_letter(t.name) for t in teams(league_id) if t.team_id in ids)


def _ui_rgb(state) -> tuple[int, int, int]:
    h = str(getattr(getattr(state, "theme", None), "ui", "") or "#4B9EEC").lstrip("#")
    if h.upper() in ("FFF", "FFFFFF"):
        h = "777777"
    try:
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (75, 158, 236)


def _row_box(draw, box, *, selected: bool) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """Draw one white-outlined row; returns its (fill, ink)."""
    fill = (255, 255, 255, 255) if selected else (0, 0, 0, 255)
    ink = (0, 0, 0, 255) if selected else (255, 255, 255, 255)
    draw.rounded_rectangle(box, radius=_TEAMS_RADIUS, fill=fill, outline=(255, 255, 255, 255), width=2)
    return fill, ink


def _draw_check(draw, cx: int, cy: int, *, on: bool, ink, ui) -> None:
    r = _CHECK_R
    if on:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ui)
        draw.line(
            [(cx - 7, cy + 1), (cx - 2, cy + 6), (cx + 8, cy - 6)],
            fill=(0, 0, 0, 255),
            width=4,
            joint="curve",
        )
    else:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ink, width=3)


def _draw_team_rows(draw, state, *, top: int, font, ui) -> None:
    from pigeon.widgets.pigeon_settings import draw_list_scrollbar

    rows, first, focus, total = team_list_rows(state)
    pad = 24
    x0 = _TEAMS_PANEL_PAD
    x1 = x0 + _TEAMS_ROW_W - 1
    for i, (label, is_team, on) in enumerate(rows):
        rtop = top + i * (_TEAMS_ROW_H + _TEAMS_ROW_GAP)
        mid = rtop + _TEAMS_ROW_H // 2
        _fill, ink = _row_box(draw, (x0, rtop, x1, rtop + _TEAMS_ROW_H - 1), selected=first + i == focus)
        if not is_team:
            draw.text(((x0 + x1) // 2, mid), label, font=font, fill=ink, anchor="mm")
            continue
        cx = x1 - pad - _CHECK_R
        _draw_check(draw, cx, mid, on=on, ink=ink, ui=ui)
        max_w = cx - _CHECK_R - 20 - (x0 + pad)
        text = label.upper()
        if draw.textlength(text, font=font) > max_w:
            while len(text) > 1 and draw.textlength(text + "…", font=font) > max_w:
                text = text[:-1].rstrip()
            text += "…"
        draw.text((x0 + pad, mid), text, font=font, fill=ink, anchor="lm")
    list_h = len(rows) * (_TEAMS_ROW_H + _TEAMS_ROW_GAP) - _TEAMS_ROW_GAP
    draw_list_scrollbar(
        draw,
        x=x1 + 1 + (_TEAMS_SCROLL_GUTTER - _SCROLL_W) // 2,
        top=top,
        height=list_h,
        first=first,
        visible=len(rows),
        total=total,
        thumb=ui,
    )


def _letter_grid_height(n_letters: int) -> int:
    rows = (n_letters + _LETTER_COLS - 1) // _LETTER_COLS
    return _TEAMS_ROW_H + _TEAMS_ROW_GAP + rows * (_LETTER_H + _TEAMS_ROW_GAP) - _TEAMS_ROW_GAP


def _draw_letter_grid(draw, state, *, top: int, font, lfont, ui) -> None:
    league_id = str(getattr(state, "sports_team_league", "") or "")
    entries = letter_entries(league_id)
    focus = int(getattr(state, "sports_team_index", 0)) % len(entries)
    marked = letters_with_follows(league_id)
    x0 = _TEAMS_PANEL_PAD
    x1 = x0 + _TEAMS_ROW_W - 1
    _fill, ink = _row_box(draw, (x0, top, x1, top + _TEAMS_ROW_H - 1), selected=focus == 0)
    draw.text(((x0 + x1) // 2, top + _TEAMS_ROW_H // 2), "BACK", font=font, fill=ink, anchor="mm")
    tile_w = (_TEAMS_ROW_W - (_LETTER_COLS - 1) * _TEAMS_ROW_GAP) / _LETTER_COLS
    gtop = top + _TEAMS_ROW_H + _TEAMS_ROW_GAP
    for i, (_payload, letter) in enumerate(entries[1:]):
        r, c = divmod(i, _LETTER_COLS)
        tx0 = int(round(x0 + c * (tile_w + _TEAMS_ROW_GAP)))
        tx1 = int(round(x0 + c * (tile_w + _TEAMS_ROW_GAP) + tile_w)) - 1
        ty0 = gtop + r * (_LETTER_H + _TEAMS_ROW_GAP)
        _fill, ink = _row_box(draw, (tx0, ty0, tx1, ty0 + _LETTER_H - 1), selected=focus == i + 1)
        draw.text(((tx0 + tx1) // 2, ty0 + _LETTER_H // 2), letter, font=lfont, fill=ink, anchor="mm")
        if letter in marked:
            draw.ellipse((tx1 - 22, ty0 + 8, tx1 - 8, ty0 + 22), fill=ui)


def draw_team_list(frame: np.ndarray, state) -> None:
    """Team list (or an NCAA league's letter grid) over the sports page, in place."""
    import cv2
    from PIL import Image, ImageDraw

    from pigeon.font_paths import resolve_ui_font_bold
    from pigeon.sports_follow import followed_count
    from pigeon.sports_teams import league
    from pigeon.widgets.main_settings import _composite_bgra_over_bgra
    from pigeon.widgets.settings_svg_text import _load_font

    league_id = str(getattr(state, "sports_team_league", "") or "")
    lg = league(league_id)
    if lg is None:
        return
    ui = (*_ui_rgb(state), 255)
    font_path = resolve_ui_font_bold()
    font = _load_font(font_path, _TEAMS_FONT_PX) if font_path else None
    tfont = _load_font(font_path, _TEAMS_TITLE_PX) if font_path else None
    letters = letter_mode(state)
    if letters:
        body_h = _letter_grid_height(len(letter_entries(league_id)) - 1)
    else:
        rows = team_list_rows(state)[0]
        body_h = len(rows) * (_TEAMS_ROW_H + _TEAMS_ROW_GAP) - _TEAMS_ROW_GAP
    title_h = _TEAMS_TITLE_PX + 26
    pw = _TEAMS_ROW_W + 2 * _TEAMS_PANEL_PAD + _TEAMS_SCROLL_GUTTER
    ph = title_h + body_h + 2 * _TEAMS_PANEL_PAD
    patch = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    draw = ImageDraw.Draw(patch)
    draw.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=_TEAMS_RADIUS + 8, fill=(0, 0, 0, 255), outline=ui, width=3)
    letter = str(getattr(state, "sports_team_letter", "") or "")
    title = f"{lg.name} · {letter}" if letter else lg.name
    n = followed_count(league_id)
    title_y = _TEAMS_PANEL_PAD + title_h // 2 - 6
    draw.text((_TEAMS_PANEL_PAD + 8, title_y), title, font=tfont, fill=ui, anchor="lm")
    hint = f"{n} FOLLOWING" if n else ("PICK A LETTER" if letters else "PICK TEAMS")
    draw.text((pw - _TEAMS_PANEL_PAD - 8, title_y), hint, font=font, fill=(255, 255, 255, 255), anchor="rm")
    top = _TEAMS_PANEL_PAD + title_h
    if letters:
        lfont = _load_font(font_path, _LETTER_FONT_PX) if font_path else None
        _draw_letter_grid(draw, state, top=top, font=font, lfont=lfont, ui=ui)
    else:
        _draw_team_rows(draw, state, top=top, font=font, ui=ui)
    bgra = cv2.cvtColor(np.asarray(patch), cv2.COLOR_RGBA2BGRA)
    x = (DESIGN_W - pw) // 2
    y = min(_TEAMS_TOP, max(0, DESIGN_H - ph))
    overlay = np.zeros_like(frame)
    x1 = min(DESIGN_W, x + bgra.shape[1])
    y1 = min(DESIGN_H, y + bgra.shape[0])
    overlay[y:y1, x:x1] = bgra[: y1 - y, : x1 - x]
    frame[:] = _composite_bgra_over_bgra(frame, overlay)


# --- state → SVG ------------------------------------------------------------------


def _league_tiles(root: ET.Element) -> list[ET.Element]:
    """The seven logo tiles, left → right (ids in the export are leftovers)."""
    from pigeon.widgets.pigeon_settings import _bbox, _by_id, _local

    group = _by_id(root, "settings_ui_color_group")
    if group is None:
        return []
    tiles = [el for el in group.iter() if _local(el) == "path" and (el.get("id") or "").startswith("ui_color_")]
    tiles.sort(key=lambda el: _bbox(el)[0])
    return tiles


def _style_tile(
    tile: ET.Element | None,
    texts: list[ET.Element | None],
    *,
    selected: bool,
    simple: bool,
    ui_hex: str,
) -> None:
    from pigeon.widgets.main_settings import _set_paint
    from pigeon.widgets.pigeon_settings import _paint_text, _sync_stroke_button

    if tile is None:
        return
    if simple:
        _set_paint(tile, fill=ui_hex if selected else _COLOR_BLACK, stroke=ui_hex)
        tile.set("stroke-width", "3")
        ink = _COLOR_BLACK if selected else ui_hex
    else:
        _set_paint(tile, fill=_COLOR_BUTTON)
        _sync_stroke_button(tile, selected=selected)
        ink = _COLOR_WHITE
    for t in texts:
        _paint_text(t, ink)


def _set_value(el: ET.Element | None, text: str) -> None:
    from pigeon.widgets.main_settings import _set_text_content

    if el is not None:
        _set_text_content(el, text)


def _add_badge(parent: ET.Element, tile: ET.Element, count: int, *, ui_hex: str) -> None:
    from pigeon.widgets.pigeon_settings import _bbox, _sibling_tag

    if count <= 0:
        return
    _x0, y0, x1, _y1 = _bbox(tile)
    cx, cy = x1 - _BADGE_INSET, y0 + _BADGE_INSET
    dot = ET.SubElement(parent, _sibling_tag(parent, "circle"))
    dot.set("cx", f"{cx:.2f}")
    dot.set("cy", f"{cy:.2f}")
    dot.set("r", f"{_BADGE_R:.2f}")
    dot.set("fill", ui_hex)
    dot.set("stroke", _COLOR_BLACK)
    dot.set("stroke-width", "3")
    label = ET.SubElement(parent, _sibling_tag(parent, "text"))
    label.text = str(count) if count < 100 else "99"
    label.set("transform", f"translate({cx:.2f} {cy + _BADGE_FONT_PX * 0.36:.2f})")
    label.set("font-family", "SharpSans-Bold, 'Sharp Sans'")
    label.set("font-weight", "700")
    label.set("font-size", str(_BADGE_FONT_PX))
    label.set("text-anchor", "middle")
    label.set("fill", _COLOR_BLACK)


def apply_sports_svg_state(root: ET.Element, state) -> None:
    from pigeon.sports_follow import auto_enabled, followed_count
    from pigeon.sports_scores import scoreboard_active
    from pigeon.sports_teams import FOLLOW_LEAGUES
    from pigeon.widgets.main_settings import _set_paint, _set_text_content, _set_visible
    from pigeon.widgets.options_settings import ui_is_simple
    from pigeon.widgets.pigeon_settings import (
        _by_id,
        _local,
        _paint_text,
        _set_label,
        _sync_pill,
        _sync_status_lights,
        _sync_version_text,
        _ui_hex,
        normalize_pigeon_focus_id,
    )
    from pigeon.widgets.settings_svg_text import center_label_on_pill

    overlay_open = bool(getattr(state, "sports_team_league", "")) or bool(
        getattr(state, "sports_dropdown_open", False)
    )
    focused = "" if overlay_open else normalize_pigeon_focus_id(state.pigeon_focused_id)
    ui_hex = _ui_hex(state)
    simple = ui_is_simple(state)

    _sync_pill(root, button_id="exit_button", text_id="exit_text", selected=focused == "exit")
    if simple:
        exit_button = _by_id(root, "exit_button")
        if exit_button is not None:
            _set_paint(exit_button, fill=ui_hex if focused == "exit" else _COLOR_BLACK, stroke=ui_hex)
            exit_button.set("stroke-width", "3")
        _paint_text(_by_id(root, "exit_text"), _COLOR_BLACK if focused == "exit" else ui_hex)
    _set_text_content(_by_id(root, "exit_text"), "BACK")
    center_label_on_pill(_by_id(root, "exit_text"), _by_id(root, "exit_button"))

    _sync_version_text(root, state)
    if simple:
        _paint_text(_by_id(root, "settings_pigeon_version_text"), ui_hex)
    _sync_status_lights(root, state)
    # Header as on settings_pigeon: the live clock is drawn on top; zip and
    # time zone live in the clock menu.
    for gid in ("settings_zipcode_group", "settings_timezone_group"):
        _set_visible(_by_id(root, gid), False)

    # The hint line sits in ``background``, which the renderer hides: lift it
    # out and center it on the page.
    background = _by_id(root, "background")
    if background is not None:
        for el in [c for c in background if _local(c) == "text"]:
            background.remove(el)
            _set_label(
                el,
                "".join(el.itertext()).strip(),
                cx=SETTINGS_CANVAS_ORIGIN[0] + DESIGN_W / 2,
                size=_HINT_PX,
                color=ui_hex if simple else _COLOR_WHITE,
            )
            el.set("font-family", "SharpSans-SemiboldItalic, 'Sharp Sans'")
            root.append(el)

    group = _by_id(root, "settings_ui_color_group")
    for lg, tile in zip(FOLLOW_LEAGUES, _league_tiles(root)):
        _style_tile(tile, [], selected=focused == f"{LEAGUE_PREFIX}{lg.league_id}", simple=simple, ui_hex=ui_hex)
        if group is not None:
            _add_badge(group, tile, followed_count(lg.league_id), ui_hex=ui_hex)

    _set_value(_by_id(root, "sports_auto_value"), "ON" if auto_enabled() else "OFF")
    _set_value(_by_id(root, "sports_games_value"), "LIVE" if scoreboard_active() else "OFF")
    for name, fid in (("auto", FOCUS_AUTO), ("games", FOCUS_GAMES)):
        _style_tile(
            _by_id(root, f"sports_{name}_button"),
            [_by_id(root, f"sports_{name}_caption"), _by_id(root, f"sports_{name}_value")],
            selected=focused == fid,
            simple=simple,
            ui_hex=ui_hex,
        )


def sports_page_token() -> tuple[object, ...]:
    """Content of the sports page that is not focus (settings repaint key)."""
    try:
        from pigeon.sports_follow import settings_version

        return (settings_version(),)
    except Exception:
        return (0,)


__all__ = [
    "FOCUS_AUTO",
    "FOCUS_GAMES",
    "SPORTS_VIEW",
    "TEAM_BACK",
    "apply_sports_svg_state",
    "default_sports_settings_svg_path",
    "draw_team_list",
    "league_focus_id",
    "league_for_focus",
    "sports_focus_ring",
    "sports_page_token",
    "current_entries",
    "letter_entries",
    "letter_mode",
    "team_letter",
    "team_list_entries",
    "team_list_rows",
]
