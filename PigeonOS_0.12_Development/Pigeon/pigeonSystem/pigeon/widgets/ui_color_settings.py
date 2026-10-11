"""
System UI color keys — the color row on ``settings_pigeon`` (0.11).

Seven UI themes, left → right as drawn on the page. Each theme hex is the
fill of its ``ui_color_[color]_icon`` layer, so the UI matches the swatch the
user is looking at. Accent / button classes keep their saved keys (no longer
user-editable) so older installs render the same.

Dark mode is ``option3`` on settings_pigeon (``color_format``), not a swatch.
"""

from __future__ import annotations

from dataclasses import dataclass

from pigeon.widgets.main_settings import (
    COLOR_ACCENT_DEFAULT,
    COLOR_DESELECTED,
    COLOR_SELECTED,
    COLOR_UI_DEFAULT,
    MainSettingsState,
    SettingsTheme,
)


@dataclass(frozen=True)
class _Swatch:
    key: str
    hex: str


# settings_pigeon color row, left → right (``ui_color_[key]_icon`` fills).
_UI_SWATCHES: tuple[_Swatch, ...] = (
    _Swatch("blue", "#4B9EEC"),
    _Swatch("green", "#00A22D"),
    _Swatch("yellow", "#E5FF0C"),
    _Swatch("orange", "#E39F00"),
    _Swatch("red", "#FB0000"),
    _Swatch("grey", "#777777"),
    _Swatch("white", "#FFFFFF"),
)

_ACCENT_SWATCHES: tuple[_Swatch, ...] = (
    _Swatch("lightred", "#FF8383"),
    _Swatch("lightorange", "#FFD985"),
    _Swatch("lightyellow", "#FFF87D"),
    _Swatch("lightgreen", "#ACFF7B"),
    _Swatch("lightblue", "#7196FF"),
    _Swatch("lightpurple", "#C27EFC"),
    _Swatch("white", "#FFFFFF"),
)

_BUTTON_SWATCHES: tuple[_Swatch, ...] = (
    _Swatch("darkred", "#7F0000"),
    _Swatch("darkorange", "#825A00"),
    _Swatch("darkyellow", "#878000"),
    _Swatch("darkgreen", "#2F7F00"),
    _Swatch("darkblue", "#03237F"),
    _Swatch("darkpurple", "#490089"),
    _Swatch("black", "#202020"),
)

_CLASS_SWATCHES: dict[str, tuple[_Swatch, ...]] = {
    "accent": _ACCENT_SWATCHES,
    "ui": _UI_SWATCHES,
    "button": _BUTTON_SWATCHES,
}

_DEFAULT_KEYS: dict[str, str] = {
    "accent": "white",
    "ui": "blue",
    "button": "black",
}

# UI keys saved by 0.8–0.11.38 pickers.
_LEGACY_UI_KEYS: dict[str, str] = {
    "gray": "grey",
    "bright": "white",
    "dark": "blue",
    "purple": "blue",
    "lightblue": "blue",
    "light_blue": "blue",
}

# Hexes older art / themes used for the UI color; still recolored on icons.
_LEGACY_UI_HEXES: frozenset[str] = frozenset(
    {"#ffb600", "#fff800", "#58ff00", "#111111"}
)

# All swatch hexes — used by main_settings paint swaps so theme changes stick.
THEME_SWATCH_HEXES: frozenset[str] = frozenset(
    s.hex.lower()
    for row in (_ACCENT_SWATCHES, _UI_SWATCHES, _BUTTON_SWATCHES)
    for s in row
) | _LEGACY_UI_HEXES | frozenset(
    {
        COLOR_ACCENT_DEFAULT.lower(),
        COLOR_UI_DEFAULT.lower(),
        COLOR_DESELECTED.lower(),
        COLOR_SELECTED.lower(),
        "#ffffff",
        "#fff",
        "#000013",
        "#000000",
        "#202020",
        "white",
        "black",
        "red",
    }
)

UI_SWATCH_HEXES: frozenset[str] = frozenset(
    s.hex.lower() for s in _UI_SWATCHES
) | _LEGACY_UI_HEXES | frozenset(
    {
        COLOR_UI_DEFAULT.lower(),
        "#4ea6f7",
        "#ff0013",
        "#ffffff",
        "blue",
    }
)

_LIVE_UI_KEY: str | None = None


def ui_color_swatch_focus_ring(color_class: str = "ui") -> tuple[str, ...]:
    return tuple(s.key for s in _CLASS_SWATCHES.get(color_class, ()))


def _swatch_by_key(color_class: str, key: str) -> _Swatch | None:
    for s in _CLASS_SWATCHES.get(color_class, ()):
        if s.key == key:
            return s
    return None


def _normalize_key(color_class: str, key: object) -> str:
    default = _DEFAULT_KEYS.get(color_class, "")
    k = str(key or default).strip().lower()
    if color_class == "ui":
        k = _LEGACY_UI_KEYS.get(k, k)
    return k if _swatch_by_key(color_class, k) is not None else default


def hex_for_color_key(color_class: str, key: str) -> str:
    sw = _swatch_by_key(color_class, _normalize_key(color_class, key))
    if sw is not None:
        return sw.hex
    return {
        "accent": COLOR_ACCENT_DEFAULT,
        "ui": COLOR_UI_DEFAULT,
        "button": "#202020",
    }.get(color_class, COLOR_SELECTED)


def read_ui_color_keys() -> dict[str, str]:
    try:
        from pigeon.app_state import read_app_state

        raw = read_app_state().get("settings_ui_colors")
    except Exception:
        raw = None
    if not isinstance(raw, dict):
        return dict(_DEFAULT_KEYS)
    return {cls: _normalize_key(cls, raw.get(cls)) for cls in _DEFAULT_KEYS}


def write_ui_color_keys(
    keys: dict[str, str],
    *,
    persist: bool = True,
) -> dict[str, str]:
    """Normalize keys and make them live; ``persist`` also saves them."""
    out = {cls: _normalize_key(cls, keys.get(cls)) for cls in _DEFAULT_KEYS}
    global _LIVE_UI_KEY
    _LIVE_UI_KEY = out["ui"]
    if persist:
        try:
            from pigeon.app_state import write_app_state

            write_app_state(settings_ui_colors=out)
        except Exception:
            pass
    return out


def current_ui_picker_key() -> str:
    """Live UI key, including an in-progress (unsaved) color preview."""
    global _LIVE_UI_KEY
    if _LIVE_UI_KEY is None:
        _LIVE_UI_KEY = read_ui_color_keys()["ui"]
    return _normalize_key("ui", _LIVE_UI_KEY)


def theme_from_color_keys(keys: dict[str, str], *, base: SettingsTheme | None = None) -> SettingsTheme:
    b = base or SettingsTheme()
    return SettingsTheme(
        ui=hex_for_color_key("ui", keys.get("ui", "blue")),
        selected=b.selected or COLOR_SELECTED,
        deselected=hex_for_color_key("button", keys.get("button", "black")),
        inactive=b.inactive,
        accent=hex_for_color_key("accent", keys.get("accent", "white")),
    )


def apply_color_keys_to_state(
    state: MainSettingsState,
    keys: dict[str, str],
    *,
    persist: bool = False,
) -> None:
    norm = write_ui_color_keys(keys, persist=persist)
    state.ui_color_accent_key = norm["accent"]
    state.ui_color_ui_key = norm["ui"]
    state.ui_color_button_key = norm["button"]
    state.theme = theme_from_color_keys(norm, base=state.theme)


def load_persisted_theme_into_state(state: MainSettingsState) -> None:
    """Apply saved accent/ui/button keys onto ``state.theme`` (startup / open)."""
    apply_color_keys_to_state(state, read_ui_color_keys(), persist=False)


__all__ = [
    "THEME_SWATCH_HEXES",
    "UI_SWATCH_HEXES",
    "apply_color_keys_to_state",
    "current_ui_picker_key",
    "hex_for_color_key",
    "load_persisted_theme_into_state",
    "read_ui_color_keys",
    "theme_from_color_keys",
    "ui_color_swatch_focus_ring",
    "write_ui_color_keys",
]
