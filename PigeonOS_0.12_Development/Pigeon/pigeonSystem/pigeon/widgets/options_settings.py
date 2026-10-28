"""System-wide options — the toggles behind settings_pigeon (0.12).

``option1`` 12 / 24 hour, ``option2`` °F / °C, ``option3`` theme / dark
(dark = red-tinted monochrome UI; the "dark" tile in the theme menu), ``option4``
info / visualizer (what the now-playing zone 4 shows; no tile any more),
``option6`` digital / analog clock, ``option7`` standard / simple
(simple = settings drawn in just the UI color and black, no background layer). Updates are always automatic (the OS
installs the latest release only while nothing is playing; the old
auto / manual update switch is gone and any saved "manual" reads as auto).
``option5`` picks the now-playing layout: zone 11 (TT across zones 1–3,
input / volume / TRT strip in zone 4, the default) or the zone 6 + 3 look (wide
TT in zone 6, volume in zone 3). ``option8`` picks zone 11's look: standard or
alt (no input id, clock or volume; the TT grows into the freed header). It only
applies while option5 is zone 11. A long
encoder press still flips into the visualizer, see :mod:`pigeon.visualizer_mode`.
Values persist under ``settings_options``.

The 0.8–0.11.38 options bar also had idle delay and clocksaver on/off
switches. Those have no control any more, so they always read as their
defaults (60 s, on) even if an older install saved otherwise. The clock face
switch came back in 0.12 as ``option6``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from pigeon.widgets.main_settings import MainSettingsState

# option A is the default.
_DEFAULTS: dict[str, Any] = {
    "time_format": "12",
    "clock_format": "digital",
    "temp_format": "f",
    "color_format": "color",
    "ui_style": "standard",
    "idle_standby": 60,
    "clock_saver": "on",
    "zone4_mode": "info",
    "np_layout": "zone11",
    "zone11_style": "standard",
    "auto_update": "auto",
}

# (option number on settings_pigeon, persist key, option A value, option B value)
_SWITCHES: tuple[tuple[int, str, Any, Any], ...] = (
    (1, "time_format", "12", "24"),
    (2, "temp_format", "f", "c"),
    (3, "color_format", "color", "dark"),
    (4, "zone4_mode", "info", "visualizer"),
    (5, "np_layout", "zone11", "zone63"),
    (6, "clock_format", "digital", "analog"),
    (7, "ui_style", "standard", "simple"),
    (8, "zone11_style", "standard", "alt"),
)

_STATE_KEY = "settings_options"


def option_numbers() -> tuple[int, ...]:
    return tuple(n for n, _k, _a, _b in _SWITCHES)


def _normalize(raw: object) -> dict[str, Any]:
    out = dict(_DEFAULTS)
    if not isinstance(raw, dict):
        return out
    tf = str(raw.get("time_format") or out["time_format"]).strip().lower()
    out["time_format"] = "24" if tf in ("24", "24h", "24-hour") else "12"
    tmp = str(raw.get("temp_format") or out["temp_format"]).strip().lower()
    out["temp_format"] = "c" if tmp in ("c", "celsius", "celcius") else "f"
    col = str(raw.get("color_format") or out["color_format"]).strip().lower()
    out["color_format"] = (
        "dark"
        if col in ("dark", "bw", "b/w", "mono", "gray", "grey", "redmono", "red-mono")
        else "color"
    )
    us = str(raw.get("ui_style") or out["ui_style"]).strip().lower()
    out["ui_style"] = "simple" if us == "simple" else "standard"
    z4 = str(raw.get("zone4_mode") or out["zone4_mode"]).strip().lower()
    out["zone4_mode"] = "visualizer" if z4 in ("visualizer", "viz", "eq") else "info"
    nl = str(raw.get("np_layout") or out["np_layout"]).strip().lower()
    out["np_layout"] = "zone63" if nl in ("zone63", "zone6", "zone 6,3", "6,3") else "zone11"
    z11 = str(raw.get("zone11_style") or out["zone11_style"]).strip().lower()
    out["zone11_style"] = "alt" if z11 == "alt" else "standard"
    cf = str(raw.get("clock_format") or out["clock_format"]).strip().lower()
    out["clock_format"] = "analog" if cf in ("analog", "analogue") else "digital"
    return out


def read_options() -> dict[str, Any]:
    try:
        from pigeon.app_state import read_app_state_shared

        # Hot path (per-frame UI look); _normalize builds a fresh dict, so the
        # shared cached view is never mutated.
        return _normalize(read_app_state_shared().get(_STATE_KEY))
    except Exception:
        return dict(_DEFAULTS)


def write_options(values: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
    out = _normalize(values)
    if persist:
        try:
            from pigeon.app_state import write_app_state

            write_app_state(**{_STATE_KEY: out})
        except Exception:
            pass
    return out


def option_is_b(n: int, values: dict[str, Any] | None = None) -> bool:
    vals = _normalize(values if values is not None else read_options())
    for num, key, _a_val, b_val in _SWITCHES:
        if num == int(n):
            return vals.get(key) == b_val
    return False


def toggle_option(
    index: int, values: dict[str, Any] | None = None, *, persist: bool = True
) -> dict[str, Any]:
    vals = _normalize(values if values is not None else read_options())
    for n, key, a_val, b_val in _SWITCHES:
        if n == int(index):
            vals[key] = a_val if vals.get(key) == b_val else b_val
            break
    return write_options(vals, persist=persist)


def set_option_value(
    key: str,
    value: Any,
    values: dict[str, Any] | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Write one option by persist key (``"color_format"`` …) and return all of them."""
    vals = _normalize(values if values is not None else read_options())
    vals[key] = value
    return write_options(vals, persist=persist)


def load_options_into_state(state: MainSettingsState) -> None:
    state.options_values = read_options()


def _vals(state: MainSettingsState | None = None) -> dict[str, Any]:
    if state is not None:
        raw = getattr(state, "options_values", None)
        if isinstance(raw, dict) and raw:
            return _normalize(raw)
    return read_options()


def clock_uses_24h(state: MainSettingsState | None = None) -> bool:
    return _vals(state)["time_format"] == "24"


def clock_widget_analog(state: MainSettingsState | None = None) -> bool:
    """option6 = analog: the analog face replaces the digital clock widgets."""
    return _vals(state)["clock_format"] == "analog"


def clock_saver_analog(state: MainSettingsState | None = None) -> bool:
    """True when idle zone-9 saver should show the centered analog clock widget."""
    try:
        from pigeon.auto_widgets import auto_clocksaver_wants_digital

        if auto_clocksaver_wants_digital():
            return False
    except Exception:
        pass
    return clock_widget_analog(state)


def temp_uses_celsius(state: MainSettingsState | None = None) -> bool:
    return _vals(state)["temp_format"] == "c"


# While the theme menu previews a color tile, the dark filter steps aside so the
# color shows as itself; committing a color also leaves dark mode.
_MONO_PREVIEW_OFF = False


def set_mono_preview_off(off: bool) -> None:
    global _MONO_PREVIEW_OFF
    _MONO_PREVIEW_OFF = bool(off)


def ui_is_monochrome(state: MainSettingsState | None = None) -> bool:
    """option3 = dark: red-on-black monochrome UI."""
    if _MONO_PREVIEW_OFF:
        return False
    return _vals(state)["color_format"] == "dark"


def ui_is_simple(state: MainSettingsState | None = None) -> bool:
    """option7 = simple: no background layer, only the UI color and black."""
    return _vals(state)["ui_style"] == "simple"


def zone4_visualizer_on(state: MainSettingsState | None = None) -> bool:
    """option4 = visualizer: the EQ replaces the zone-4 cast / track info."""
    return _vals(state)["zone4_mode"] == "visualizer"


def zone6_visualizer_default(state: MainSettingsState | None = None) -> bool:
    """Pigeon always starts in now-playing; option5 no longer selects the visualizer."""
    return False


def zone11_selected(state: MainSettingsState | None = None) -> bool:
    """option5 = zone11 (default): TT across zones 1–3, input / volume / TRT in zone 4."""
    return _vals(state)["np_layout"] == "zone11"


def zone11_alt_selected(state: MainSettingsState | None = None) -> bool:
    """option8 = alt while option5 = zone11: no input id / clock / volume, bigger TT."""
    vals = _vals(state)
    return vals["np_layout"] == "zone11" and vals["zone11_style"] == "alt"


def auto_update_enabled(state: MainSettingsState | None = None) -> bool:
    """Auto-update is mandatory: install the latest OS while nothing is playing."""
    _ = state
    return True


def ui_is_bright(state: MainSettingsState | None = None) -> bool:
    """The white-paper "bright" look was retired with the 0.8 picker."""
    _ = state
    return False


def ui_paper_bgr() -> tuple[int, int, int]:
    """Frame / plate paper (BGR)."""
    return (0, 0, 0)


def ui_ink_rgb() -> tuple[int, int, int]:
    """Primary text on paper."""
    return (255, 255, 255)


def ui_ink_hex() -> str:
    return "#FFFFFF"


def ui_chrome_rgb() -> tuple[int, int, int]:
    """NP labels / Digital-7 / unplayed track."""
    return (147, 147, 147)


def ui_chrome_bgr() -> tuple[int, int, int]:
    return ui_chrome_rgb()


def ui_chrome_hex() -> str:
    return "#939393"


def ui_idle_text_hex() -> str:
    """Deselected settings labels sitting on the plate."""
    return "#919190"


def clock_saver_idle_s(state: MainSettingsState | None = None) -> float:
    return float(_vals(state)["idle_standby"])


def clock_saver_enabled(state: MainSettingsState | None = None) -> bool:
    return _vals(state)["clock_saver"] == "on"


def apply_ui_mono_bgr(frame_bgr: np.ndarray) -> np.ndarray:
    """Map the frame to red-channel monochrome when the dark UI option is on."""
    if frame_bgr is None or frame_bgr.size == 0:
        return frame_bgr
    try:
        if not ui_is_monochrome():
            return frame_bgr
    except Exception:
        return frame_bgr
    from pigeon.compositing import bgr_to_red_monochrome_luma

    return bgr_to_red_monochrome_luma(frame_bgr)


def apply_ui_bright_bgr(frame_bgr: np.ndarray) -> np.ndarray:
    """Light mode is painted on the vector layers; no full-frame invert."""
    return frame_bgr


def apply_ui_look_bgr(frame_bgr: np.ndarray) -> np.ndarray:
    """Apply the picker look (red-mono dark; light mode is assigned at paint time),
    then the user's display brightness. Every displayed frame passes through here."""
    frame_bgr = apply_ui_mono_bgr(frame_bgr)
    try:
        from pigeon.display_brightness import apply as _apply_brightness

        return _apply_brightness(frame_bgr)
    except Exception:
        return frame_bgr


__all__ = [
    "auto_update_enabled",
    "apply_ui_bright_bgr",
    "apply_ui_look_bgr",
    "apply_ui_mono_bgr",
    "clock_saver_analog",
    "clock_saver_enabled",
    "clock_saver_idle_s",
    "clock_uses_24h",
    "clock_widget_analog",
    "load_options_into_state",
    "option_is_b",
    "option_numbers",
    "read_options",
    "temp_uses_celsius",
    "toggle_option",
    "ui_chrome_bgr",
    "ui_chrome_hex",
    "ui_chrome_rgb",
    "ui_idle_text_hex",
    "ui_ink_hex",
    "ui_ink_rgb",
    "ui_is_bright",
    "set_mono_preview_off",
    "ui_is_monochrome",
    "ui_is_simple",
    "ui_paper_bgr",
    "write_options",
    "zone4_visualizer_on",
    "zone6_visualizer_default",
    "zone11_alt_selected",
    "zone11_selected",
]
