"""
settings_pigeon update screen — ``settings/pigeon/settings_pigeon_update.svg``.

Opened from settings_pigeon when **update** is activated. The card is authored
1:1 in design pixels (843×671) and centered on the 1280×800 canvas.

Focus ring (left → right): the page's EXIT pill relabeled **BACK**, then
``version_current`` (only once an update exists), then ``version_update``.

* ``version_update`` — shows the new build number when one is known (activate
  to download + install), otherwise **CHECK** (activate to query GitHub again).
* ``version_current`` — the installed build. Activating it means "stay on this
  version": same as BACK / cancel.
* ``status_placeholder`` — 60 tick cells (clocksaver seconds style) drawn as a
  live overlay so checking / download progress animate without SVG rebuilds.
"""

from __future__ import annotations

import copy
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pigeon.design import DESIGN_H, DESIGN_W
from pigeon.widgets.main_settings import (
    COLOR_UI_DEFAULT,
    MainSettingsState,
    _composite_bgra_over_bgra,
    _find_by_logical_id,
    _prune_display_none,
    _set_paint,
    _set_visible,
)
from pigeon.widgets.settings_svg_text import rasterize_settings_svg_bgra, remove_svg_text

SVG_NS = "http://www.w3.org/2000/svg"

ID_POPUP_WINDOW = "popup_window"
ID_STATUS = "status_placeholder"
ID_UPDATE_GROUP = "version_update_group"
ID_UPDATE_CONTAINER = "version_update_container"
ID_UPDATE_CONTAINER_TYPO = "version_update_containter"  # Illustrator export typo
ID_UPDATE_TEXT = "version_update_text"
ID_UPDATE_MESSAGE = "version_update_message_text"
ID_ARROW = "version_update_arrow_icon"
ID_CURRENT_GROUP = "version_current_group"
ID_CURRENT_CONTAINER = "version_current_container"
ID_CURRENT_TEXT = "version_current_text"
ID_PIGEONOS_TEXT = "pigeonOS_text"

FOCUS_BACK = "back"
FOCUS_CURRENT = "current"
FOCUS_UPDATE = "update"

CHECK_LABEL = "CHECK"
UPDATE_MESSAGE = "update"
LATEST_MESSAGE = "latest version"
PIGEONOS_LABEL = "pigeonOS"

# Kept for callers that still set a status line (no text layer on this screen).
DEFAULT_CHANGELOG = "bug fixes and optimizations."
UP_TO_DATE_CHANGELOG = "You're on the current version of PigeonOS"

# Card size in SVG units; drawn at POPUP_SCALE and centered on the canvas.
POPUP_W = 843.44
POPUP_H = 670.65
# Version digits (100 SVG units) land at the settings_pigeon BACK pill's
# Digital-7 size (exit_text font-size 46.4 design px).
_BACK_TEXT_PX = 46.4
_VERSION_FONT_PX = 100
POPUP_SCALE = _BACK_TEXT_PX / _VERSION_FONT_PX
POPUP_DRAW_W = int(round(POPUP_W * POPUP_SCALE))
POPUP_DRAW_H = int(round(POPUP_H * POPUP_SCALE))

# The blue window is sized in design px to cover settings_pigeon's two tile
# rows (x 66–1216, y 271–592, RESET / UPDATE labels to ~640) with margin.
WINDOW_RECT = (46, 248, 1188, 416)
_WINDOW_RADIUS = 40
# Scaled card content (title / versions / message), centered in the window
# with its title cap height 60 px below the window top.
_CONTENT_TOP_UNITS = 77.0
_CONTENT_TOP_PAD = 60
POPUP_X = int(round(WINDOW_RECT[0] + (WINDOW_RECT[2] - POPUP_DRAW_W) / 2.0))
POPUP_Y = int(round(WINDOW_RECT[1] + _CONTENT_TOP_PAD - _CONTENT_TOP_UNITS * POPUP_SCALE))
# Black status well spanning the window, 40 px side / 60 px bottom margins.
STATUS_WELL_RECT = (
    WINDOW_RECT[0] + 40,
    WINDOW_RECT[1] + WINDOW_RECT[3] - 60 - 56,
    WINDOW_RECT[2] - 80,
    56,
)

# Geometry from the 2026-10 Illustrator export (SVG units).
_UPDATE_BOX = (494.43, 266.26, 291.23, 126.14)
_BOX_RX = 40.2
# No current container in the export: mirror the update box's side margin.
_CURRENT_BOX = (POPUP_W - (_UPDATE_BOX[0] + _UPDATE_BOX[2]), 266.26, 291.23, 126.14)
_UPDATE_TEXT_BASELINE = 361.36
_CURRENT_TEXT_BASELINE = 363.9
_MESSAGE_BASELINE = 450.12
_PIGEONOS_XY = (79.94, 187.04)
_MESSAGE_FONT_PX = 60
_PIGEONOS_FONT_PX = 146
_VERSION_TEXT_INSET = 22.0

# Red "update found" badge on the update container's top-right corner.
_BADGE_R = 24.0
_BADGE_INSET = 14.0
_BADGE_FILL = "#FF0000"

_TEXT_SELECTED = "#000000"
# Spec asks for the UI color here, but the card itself is UI-colored, so the
# label would vanish; white matches the export.
_TEXT_UNSELECTED = "#FFFFFF"
_CONTAINER_FILL = "#FFFFFF"

# Status bar cells.
_STATUS_COUNT = 60
# Status well padding / cell gap (design px). 60 cells across the full-width
# well come out ~14 px wide, close to the clocksaver seconds cells.
_STATUS_PAD_X = 12
_STATUS_PAD_Y = 12
_STATUS_GAP = 4.0
_STATUS_DIM_OPACITY = 0.18
_STATUS_ERROR_BGR = (0, 0, 255)
_CHECK_CELLS_PER_S = 6

_SVG_TREE_TEMPLATES: dict[tuple[str, int, int], ET.Element] = {}
_SVG_TREE_TEMPLATE_MAX = 4
_STATIC_CACHE: dict[tuple[object, ...], np.ndarray] = {}
_STATIC_CACHE_MAX = 8


def default_update_popup_svg_path(assets_dir: Path | str | None = None) -> Path:
    env = os.environ.get("PIGEON_UPDATE_POPUP_SVG", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if assets_dir is not None:
        return Path(assets_dir) / "settings" / "pigeon" / "settings_pigeon_update.svg"
    pigeon_root = Path(__file__).resolve().parents[3]
    return pigeon_root / "pigeonAssets" / "settings" / "pigeon" / "settings_pigeon_update.svg"


def update_popup_focus_ring(
    *,
    update_available: bool,
    checking: bool = False,
    applying: bool = False,
    latest: bool = False,
) -> tuple[str, ...]:
    """Choices the encoder can land on, left to right.

    ``version_current`` is skipped until an update exists. Nothing is
    selectable while an update is installing. A check in flight keeps BACK
    reachable so the user can always leave. Once a check confirms this is the
    latest version (``latest``), ``version_update`` is pulled too until the
    screen is opened again.
    """
    del checking
    if applying:
        return ()
    if latest and not update_available:
        return (FOCUS_BACK,)
    if update_available:
        return (FOCUS_BACK, FOCUS_CURRENT, FOCUS_UPDATE)
    return (FOCUS_BACK, FOCUS_UPDATE)


def _svg_tree_from_path(path: Path) -> ET.Element:
    try:
        st = path.stat()
        key = (str(path.resolve()), int(st.st_mtime_ns), int(st.st_size))
    except OSError:
        key = (str(path), 0, 0)
    template = _SVG_TREE_TEMPLATES.get(key)
    if template is None:
        template = ET.parse(path).getroot()
        if len(_SVG_TREE_TEMPLATES) >= _SVG_TREE_TEMPLATE_MAX:
            _SVG_TREE_TEMPLATES.clear()
        _SVG_TREE_TEMPLATES[key] = template
    return copy.deepcopy(template)


def _format_version(ver: str | None) -> str:
    v = (ver or "").strip()
    if v[:1] in ("v", "V"):
        v = v[1:].lstrip()
    return v


def _focused_choice(state: MainSettingsState) -> str:
    ring = update_popup_focus_ring(
        update_available=bool(state.update_available),
        checking=bool(state.update_checking),
        applying=bool(state.update_applying),
        latest=bool(state.update_latest_confirmed),
    )
    if not ring:
        return FOCUS_UPDATE
    return ring[int(state.update_popup_focus_index) % len(ring)]


def _rect_el(x: float, y: float, w: float, h: float, *, rx: float, fill: str, el_id: str) -> ET.Element:
    el = ET.Element(f"{{{SVG_NS}}}rect")
    el.set("id", el_id)
    for k, v in (("x", x), ("y", y), ("width", w), ("height", h), ("rx", rx), ("ry", rx)):
        el.set(k, f"{v:.2f}")
    el.set("fill", fill)
    return el


def apply_update_popup_svg_state(root: ET.Element, state: MainSettingsState) -> None:
    """Shape layers only — labels are painted by :func:`_draw_labels_bgra`."""
    ui = state.theme.ui or COLOR_UI_DEFAULT
    available = bool(state.update_available)
    focused = _focused_choice(state)

    # The card sits inside the larger drawn window: square, UI-filled corners
    # so it blends in, and its status well is redrawn full width instead.
    window = _find_by_logical_id(root, ID_POPUP_WINDOW)
    for node in ([window] + list(window.iter())) if window is not None else []:
        if node.tag.endswith("rect") or node.tag.endswith("path"):
            _set_paint(node, fill=ui, stroke=ui)
            node.set("rx", "0")
            node.set("ry", "0")
    _set_visible(_find_by_logical_id(root, ID_STATUS), False)

    update_group = _find_by_logical_id(root, ID_UPDATE_GROUP)
    update_box = _find_by_logical_id(root, ID_UPDATE_CONTAINER)
    if update_box is None:
        update_box = _find_by_logical_id(root, ID_UPDATE_CONTAINER_TYPO)
    if update_box is not None:
        _set_paint(update_box, fill=_CONTAINER_FILL, stroke="none")
        _set_visible(update_box, focused == FOCUS_UPDATE)
    if available:
        bx, by, bw, _bh = _UPDATE_BOX
        badge = ET.Element(f"{{{SVG_NS}}}circle")
        badge.set("id", "version_update_badge")
        badge.set("cx", f"{bx + bw - _BADGE_INSET:.2f}")
        badge.set("cy", f"{by + _BADGE_INSET:.2f}")
        badge.set("r", f"{_BADGE_R:.2f}")
        badge.set("fill", _BADGE_FILL)
        # On top of the container: last shape in the group.
        if update_group is not None:
            update_group.append(badge)

    arrow = _find_by_logical_id(root, ID_ARROW)
    if arrow is not None:
        _set_paint(arrow, fill="#FFFFFF", stroke="none")
        _set_visible(arrow, available)

    current_group = _find_by_logical_id(root, ID_CURRENT_GROUP)
    current_box = _find_by_logical_id(root, ID_CURRENT_CONTAINER)
    if current_box is None and current_group is not None:
        cx, cy, cw, ch = _CURRENT_BOX
        current_box = _rect_el(
            cx, cy, cw, ch, rx=_BOX_RX, fill=_CONTAINER_FILL, el_id=ID_CURRENT_CONTAINER
        )
        current_group.insert(0, current_box)
    if current_box is not None:
        _set_paint(current_box, fill=_CONTAINER_FILL, stroke="none")
        _set_visible(current_box, available and focused == FOCUS_CURRENT)


def _hex_rgba(hex_color: str) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    except ValueError:
        return (255, 255, 255, 255)


def _font(role: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    from pigeon.font_paths import (
        resolve_digital7_font,
        resolve_ui_font_extrabold,
        resolve_ui_font_extrabold_italic,
        resolve_ui_font_medium_italic,
        resolve_ui_font_semibold,
    )

    if role == "digital7":
        path = resolve_digital7_font()
    elif role == "extrabold_italic":
        path = resolve_ui_font_extrabold_italic() or resolve_ui_font_extrabold()
    else:
        path = resolve_ui_font_medium_italic()
    path = path or resolve_ui_font_semibold()
    return _load_font(path or "", int(size))


_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = (path, size)
    hit = _FONT_CACHE.get(key)
    if hit is None:
        try:
            hit = ImageFont.truetype(path, max(6, size))
        except OSError:
            hit = ImageFont.load_default()
        _FONT_CACHE[key] = hit
    return hit


def _fit_font(draw: ImageDraw.ImageDraw, text: str, role: str, size: int, max_w: float):
    font = _font(role, size)
    while size > 24:
        l, _t, r, _b = draw.textbbox((0, 0), text, font=font, anchor="ls")
        if r - l <= max_w:
            break
        size -= 4
        font = _font(role, size)
    return font


def _draw_labels_bgra(bgra: np.ndarray, state: MainSettingsState) -> None:
    available = bool(state.update_available)
    focused = _focused_choice(state)
    current = _format_version(state.update_local_version or state.version_string)
    remote = _format_version(state.update_remote_version)

    img = Image.fromarray(cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA))
    draw = ImageDraw.Draw(img)
    white = _hex_rgba("#FFFFFF")

    draw.text(
        _PIGEONOS_XY,
        PIGEONOS_LABEL,
        font=_font("extrabold_italic", _PIGEONOS_FONT_PX),
        fill=white,
        anchor="ls",
    )

    ux, _uy, uw, _uh = _UPDATE_BOX
    ucx = ux + uw / 2.0
    message = (
        LATEST_MESSAGE if (state.update_latest_confirmed and not available) else UPDATE_MESSAGE
    )
    # Centered under the update box; "latest version" shrinks to stay on the card.
    message_max_w = 2.0 * (POPUP_W - ucx - _VERSION_TEXT_INSET * 2)
    draw.text(
        (ucx, _MESSAGE_BASELINE),
        message,
        font=_fit_font(draw, message, "medium_italic", _MESSAGE_FONT_PX, message_max_w),
        fill=white,
        anchor="ms",
    )

    update_label = remote if (available and remote) else CHECK_LABEL
    max_w = uw - 2 * _VERSION_TEXT_INSET
    draw.text(
        (ucx, _UPDATE_TEXT_BASELINE),
        update_label,
        font=_fit_font(draw, update_label, "digital7", _VERSION_FONT_PX, max_w),
        fill=_hex_rgba(_TEXT_SELECTED if focused == FOCUS_UPDATE else _TEXT_UNSELECTED),
        anchor="ms",
    )

    if current:
        cx, _cy, cw, _ch = _CURRENT_BOX
        selected = available and focused == FOCUS_CURRENT
        draw.text(
            (cx + cw / 2.0, _CURRENT_TEXT_BASELINE),
            current,
            font=_fit_font(draw, current, "digital7", _VERSION_FONT_PX, cw - 2 * _VERSION_TEXT_INSET),
            fill=_hex_rgba(_TEXT_SELECTED if selected else _TEXT_UNSELECTED),
            anchor="ms",
        )

    bgra[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)


def _popup_static_key(state: MainSettingsState, path: Path) -> tuple[object, ...]:
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    return (
        str(path),
        mtime,
        str(state.theme.ui or ""),
        bool(state.update_available),
        bool(state.update_applying),
        bool(state.update_latest_confirmed),
        _focused_choice(state),
        _format_version(state.update_local_version or state.version_string),
        _format_version(state.update_remote_version),
    )


def render_update_popup_card_bgra(
    state: MainSettingsState,
    *,
    path: Path,
) -> np.ndarray:
    """The card at ``POPUP_DRAW_W``×``POPUP_DRAW_H`` px.

    Rendered at the authored size, then area-downsampled so the small text
    stays crisp.
    """
    key = _popup_static_key(state, path)
    hit = _STATIC_CACHE.get(key)
    if hit is not None:
        return hit
    root = _svg_tree_from_path(path)
    apply_update_popup_svg_state(root, state)
    remove_svg_text(root)
    _prune_display_none(root)
    w = int(round(POPUP_W))
    h = int(round(POPUP_H))
    root.set("viewBox", f"0 0 {POPUP_W} {POPUP_H}")
    root.set("width", str(w))
    root.set("height", str(h))
    card = rasterize_settings_svg_bgra(root, width=w, height=h, view_box=(0.0, 0.0, POPUP_W, POPUP_H))
    _draw_labels_bgra(card, state)
    card = cv2.resize(card, (POPUP_DRAW_W, POPUP_DRAW_H), interpolation=cv2.INTER_AREA)
    # Flatten onto the window's UI fill: anti-aliased card edges would
    # otherwise leave a see-through seam inside the window. PyMuPDF edge
    # pixels are premultiplied, so only the backdrop is scaled.
    alpha = card[:, :, 3:4].astype(np.float32) / 255.0
    ui = np.array(_ui_bgr(state), dtype=np.float32)
    card[:, :, :3] = np.clip(
        card[:, :, :3].astype(np.float32) + ui * (1.0 - alpha), 0, 255
    ).astype(np.uint8)
    card[:, :, 3] = 255
    if len(_STATIC_CACHE) >= _STATIC_CACHE_MAX:
        _STATIC_CACHE.clear()
    _STATIC_CACHE[key] = card
    return card


def render_update_popup_bgra(
    state: MainSettingsState | None = None,
    *,
    svg_path: Path | str | None = None,
    assets_dir: Path | str | None = None,
) -> np.ndarray:
    """Full-canvas BGRA (transparent outside the window)."""
    from pigeon.widgets.view_circles import _draw_rounded_bar_bgra

    path = Path(svg_path) if svg_path is not None else default_update_popup_svg_path(assets_dir)
    if not path.is_file():
        raise FileNotFoundError(f"update popup SVG not found: {path}")
    st = state if state is not None else MainSettingsState()
    card = render_update_popup_card_bgra(st, path=path)
    frame = np.zeros((DESIGN_H, DESIGN_W, 4), dtype=np.uint8)
    wx, wy, ww, wh = WINDOW_RECT
    _draw_rounded_bar_bgra(
        frame, x=wx, y=wy, w=ww, h=wh, fill_bgr=_ui_bgr(st), radius=_WINDOW_RADIUS
    )
    ch, cw = card.shape[:2]
    y1 = min(DESIGN_H, POPUP_Y + ch)
    x1 = min(DESIGN_W, POPUP_X + cw)
    frame[POPUP_Y:y1, POPUP_X:x1] = card[: y1 - POPUP_Y, : x1 - POPUP_X]
    sx, sy, sw, sh = STATUS_WELL_RECT
    frame[sy : sy + sh, sx : sx + sw] = (0, 0, 0, 255)
    return frame


def composite_update_popup_over_bgra(
    base_bgra: np.ndarray,
    state: MainSettingsState,
    *,
    assets_dir: Path | str | None = None,
) -> np.ndarray:
    overlay = render_update_popup_bgra(state, assets_dir=assets_dir)
    return _composite_bgra_over_bgra(base_bgra, overlay)


def update_status_cells(
    state: MainSettingsState,
    *,
    now_mono: float | None = None,
) -> tuple[int, str]:
    """``(lit_cells, mode)`` for the 60-cell status bar.

    * applying → download / install progress
    * checking → cells sweep in from the left while GitHub is queried
    * check failed → every cell red
    * up to date → full bar
    * update waiting → empty bar, ready to show progress
    """
    if state.update_applying:
        frac = max(0.0, min(1.0, float(state.update_progress)))
        return int(round(frac * _STATUS_COUNT)), "ui"
    if state.update_checking:
        started = float(getattr(state, "update_check_started_mono", 0.0) or 0.0)
        now = time.monotonic() if now_mono is None else float(now_mono)
        elapsed = max(0, int(now - started)) if started > 0 else 0
        return min(_STATUS_COUNT - 1, (elapsed + 1) * _CHECK_CELLS_PER_S), "ui"
    if state.update_error:
        return _STATUS_COUNT, "error"
    if state.update_available:
        return 0, "ui"
    if state.update_remote_version or state.update_local_version:
        return _STATUS_COUNT, "ui"
    return 0, "ui"


def _ui_bgr(state: MainSettingsState) -> tuple[int, int, int]:
    r, g, b, _a = _hex_rgba(str(state.theme.ui or COLOR_UI_DEFAULT))
    return (b, g, r)


def draw_update_status_bar_bgra(
    frame: np.ndarray,
    state: MainSettingsState,
    *,
    now_mono: float | None = None,
) -> np.ndarray:
    """Paint the 60 status cells into the card's black status well (returns a copy)."""
    from pigeon.np_layout import clock_saver_seconds_segment_rects
    from pigeon.widgets.view_circles import _draw_rounded_bar_bgra

    out = frame.copy()
    sx, sy, sw, sh = STATUS_WELL_RECT
    track = (
        sx + _STATUS_PAD_X,
        sy + _STATUS_PAD_Y,
        sw - 2 * _STATUS_PAD_X,
        sh - 2 * _STATUS_PAD_Y,
    )
    rects = clock_saver_seconds_segment_rects(track, count=_STATUS_COUNT, gap=_STATUS_GAP)
    if not rects:
        return out
    lit, mode = update_status_cells(state, now_mono=now_mono)
    color = _STATUS_ERROR_BGR if mode == "error" else _ui_bgr(state)
    radius = max(1, min(min(r[2] for r in rects) // 2, 3))
    for i, (x, y, w, h) in enumerate(rects):
        _draw_rounded_bar_bgra(
            out,
            x=x,
            y=y,
            w=w,
            h=h,
            fill_bgr=color,
            radius=radius,
            fill_opacity=1.0 if i < lit else _STATUS_DIM_OPACITY,
        )
    return out


__all__ = [
    "CHECK_LABEL",
    "DEFAULT_CHANGELOG",
    "FOCUS_BACK",
    "FOCUS_CURRENT",
    "FOCUS_UPDATE",
    "LATEST_MESSAGE",
    "UP_TO_DATE_CHANGELOG",
    "apply_update_popup_svg_state",
    "composite_update_popup_over_bgra",
    "default_update_popup_svg_path",
    "draw_update_status_bar_bgra",
    "render_update_popup_bgra",
    "update_popup_focus_ring",
    "update_status_cells",
]
