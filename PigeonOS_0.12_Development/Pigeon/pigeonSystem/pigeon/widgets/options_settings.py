"""System-wide options — the five toggles on settings_pigeon (0.11).

``option1`` 12 / 24 hour, ``option2`` °F / °C, ``option3`` theme / dark
(dark = red-tinted monochrome UI), ``option4`` info / visualizer (what the
now-playing zone 4 shows), ``option5`` now playing / visualizer (which mode
Pigeon starts in; a long encoder press flips between them, see
:mod:`pigeon.visualizer_mode`). Values persist under ``settings_options``.

The 0.8–0.11.38 options bar also had clock face, idle delay and clocksaver
on/off switches. Those have no control any more, so they always read as
their defaults (digital, 60 s, on) even if an older install saved otherwise.
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
    "idle_standby": 60,
    "clock_saver": "on",
    "zone4_mode": "info",
    "zone6_mode": "now_playing",
}

# (option number on settings_pigeon, persist key, option A value, option B value)
_SWITCHES: tuple[tuple[int, str, Any, Any], ...] = (
    (1, "time_format", "12", "24"),
    (2, "temp_format", "f", "c"),
    (3, "color_format", "color", "dark"),
    (4, "zone4_mode", "info", "visualizer"),
    (5, "zone6_mode", "now_playing", "visualizer"),
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
    z4 = str(raw.get("zone4_mode") or out["zone4_mode"]).strip().lower()
    out["zone4_mode"] = "visualizer" if z4 in ("visualizer", "viz", "eq") else "info"
    z6 = str(raw.get("zone6_mode") or out["zone6_mode"]).strip().lower()
    out["zone6_mode"] = "visualizer" if z6 in ("visualizer", "viz") else "now_playing"
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
    out = write_options(vals, persist=persist)
    if int(index) == 5:
        # The new default takes effect now, not only at the next boot.
        from pigeon import visualizer_mode

        visualizer_mode.set_active(out["zone6_mode"] == "visualizer")
    return out


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
    """Analog clock faces are no longer selectable (always digital)."""
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


def ui_is_monochrome(state: MainSettingsState | None = None) -> bool:
    """option3 = dark: red-tinted monochrome UI."""
    return _vals(state)["color_format"] == "dark"


def zone4_visualizer_on(state: MainSettingsState | None = None) -> bool:
    """option4 = visualizer: the EQ replaces the zone-4 cast / track info."""
    return _vals(state)["zone4_mode"] == "visualizer"


def zone6_visualizer_default(state: MainSettingsState | None = None) -> bool:
    """option5 = visualizer: Pigeon starts in visualizer mode (zone 6 visualizer)."""
    return _vals(state)["zone6_mode"] == "visualizer"


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
    """Apply the picker look: red-mono dark. Light mode is assigned at paint time."""
    return apply_ui_mono_bgr(frame_bgr)


__all__ = [
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
    "ui_is_monochrome",
    "ui_paper_bgr",
    "write_options",
    "zone4_visualizer_on",
    "zone6_visualizer_default",
]
