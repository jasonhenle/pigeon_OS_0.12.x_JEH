"""
Now-playing widget colours and theme.

Base colour constants for the circle / bar widgets, hue helpers (``_look_*``,
``_darken_hex``, ``_visible_on_dark_hex``), the ``_NpTheme`` value type loaded from the
settings colour page by ``np_theme_from_settings``, and the zone-centre lookups.

The ``_NP_UI_FROM_TT`` / ``_NP_NO_POSTER_UI_WASH`` switches stay in ``view_circles``
(the widget reads them at draw time and tests patch them there).

``pigeon.widgets.view_circles`` re-exports every name here for existing importers.
"""

from __future__ import annotations

from dataclasses import dataclass

from pigeon.np_layout import CLOCK_LOCAL_CX, CLOCK_LOCAL_CY, NOW_PLAYING_ZONES, design_xy_from_local


_COLOR_BG_HEX = "#000000"


_COLOR_ACCENT_BGR = (0, 0, 255)  # #FF0000 — legacy default (mapped to theme.ui)


_COLOR_UNPLAYED_BGR = (147, 147, 147)  # #939393


_COLOR_BUTTON_BGR = (35, 35, 35)  # #232323 — legacy; inner discs use pure black


# ``volume_container`` fill in widget_np_01-02-03_volume.svg; the zone-4 EQ box.
_VOLUME_CONTAINER_BGR = (35, 35, 35)


_COLOR_CENTER_BLACK_HEX = "#000000"


_COLOR_CENTER_BLACK_BGR = (0, 0, 0)


_COLOR_CHROME_BGR = (147, 147, 147)  # #939393


_COLOR_CHROME_RGB = (147, 147, 147)


# Empty volume ring + status-bar track: 30% white / 70% black.
_COLOR_UNFILLED_HEX = "#4d4d4d"


_COLOR_UNFILLED_BGR = (77, 77, 77)


_COLOR_UNFILLED_RGB = (77, 77, 77)


def _look_chrome_rgb() -> tuple[int, int, int]:
    try:
        from pigeon.widgets.options_settings import ui_chrome_rgb

        return ui_chrome_rgb()
    except Exception:
        return _COLOR_CHROME_RGB


def _look_chrome_bgr() -> tuple[int, int, int]:
    return _look_chrome_rgb()


def _look_chrome_hex() -> str:
    try:
        from pigeon.widgets.options_settings import ui_chrome_hex

        return ui_chrome_hex()
    except Exception:
        return "#939393"


def _look_ink_rgb() -> tuple[int, int, int]:
    try:
        from pigeon.widgets.options_settings import ui_ink_rgb

        return ui_ink_rgb()
    except Exception:
        return (255, 255, 255)


def _look_is_bright() -> bool:
    try:
        from pigeon.widgets.options_settings import ui_is_bright

        return bool(ui_is_bright())
    except Exception:
        return False


def _hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    h = (hex_color or "").strip().lstrip("#")
    if len(h) == 3:
        h = f"{h[0]}{h[0]}{h[1]}{h[1]}{h[2]}{h[2]}"
    if len(h) != 6:
        return _COLOR_ACCENT_BGR
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except ValueError:
        return _COLOR_ACCENT_BGR
    return (b, g, r)


def _visible_on_dark_hex(hex_color: str) -> str:
    """Keep analog ticks off page-white so decanvas / punch cannot eat them."""
    b, g, r = _hex_to_bgr(hex_color)
    if r >= 240 and g >= 240 and b >= 240:
        return _CLOCK_TICK_OFF_HEX
    return hex_color


def _darken_hex(hex_color: str, *, factor: float = 0.5) -> str:
    h = (hex_color or "").strip().lstrip("#")
    if len(h) == 3:
        h = f"{h[0]}{h[0]}{h[1]}{h[1]}{h[2]}{h[2]}"
    if len(h) != 6:
        return "#800000"
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except ValueError:
        return "#800000"
    f = max(0.0, min(1.0, float(factor)))
    return f"#{int(r * f):02x}{int(g * f):02x}{int(b * f):02x}"


@dataclass(frozen=True)
class _NpTheme:
    """Settings color page → now-playing paint roles."""

    ui_hex: str = "#4EA6F7"
    accent_hex: str = "#FFFFFF"
    button_hex: str = "#202020"

    @property
    def ui_bgr(self) -> tuple[int, int, int]:
        return _hex_to_bgr(self.ui_hex)

    @property
    def accent_bgr(self) -> tuple[int, int, int]:
        return _hex_to_bgr(self.accent_hex)

    @property
    def button_bgr(self) -> tuple[int, int, int]:
        return _hex_to_bgr(self.button_hex)

    @property
    def tick_active(self) -> str:
        return self.ui_hex

    @property
    def tick_dim(self) -> str:
        return _darken_hex(self.ui_hex, factor=0.5)

    @property
    def cache_key(self) -> tuple[str, str, str, str]:
        look = "bright" if _look_is_bright() else "std"
        return (self.ui_hex.lower(), self.accent_hex.lower(), self.button_hex.lower(), look)


def np_theme_from_settings() -> _NpTheme:
    """Load accent / ui / button colors from the settings color page."""
    try:
        from pigeon.widgets.ui_color_settings import (
            hex_for_color_key,
            read_ui_color_keys,
        )

        keys = read_ui_color_keys()
        return _NpTheme(
            ui_hex=hex_for_color_key("ui", keys.get("ui", "blue")),
            accent_hex=hex_for_color_key("accent", keys.get("accent", "white")),
            button_hex=hex_for_color_key("button", keys.get("button", "black")),
        )
    except Exception:
        return _NpTheme()


def _zone_spec(zone: int):
    z = int(zone)
    return NOW_PLAYING_ZONES.get(z, NOW_PLAYING_ZONES[1])


def _zone_clock_center_const(zone: int) -> tuple[float, float]:
    return design_xy_from_local(_zone_spec(zone), CLOCK_LOCAL_CX, CLOCK_LOCAL_CY)


# Analog "off" seconds ticks: dark gray (the volume ring track), not white (page-white punch uses 252;
# this must stay below that).
_CLOCK_TICK_OFF_HEX = "#4D4D4D"
