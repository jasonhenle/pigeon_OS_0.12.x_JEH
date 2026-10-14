"""Rooms and the settings_pigeon page, as plain data (no Tk).

The on-device screens keep their own copy of these values, so every change is
followed by a UI-thread callback (supplied by boot) that reloads that copy.
"""

from __future__ import annotations

from typing import Any, Mapping

ROOM_NAME_MAX = 24
ROOM_SLOTS = 3

UI_COLORS = ("blue", "green", "yellow", "orange", "red", "grey", "white")
# option name -> allowed values (first is the default)
OPTION_VALUES: dict[str, tuple[str, ...]] = {
    "time_format": ("12", "24"),
    "temp_format": ("f", "c"),
    "color_format": ("color", "dark"),
    "zone4_mode": ("info", "visualizer"),
    "zone6_mode": ("now_playing", "zone11"),
}


# ------------------------------------------------------------------- rooms

def _room_label(raw: str, slot: int) -> str:
    try:
        from pigeon.widgets.main_settings import location_room_label

        return location_room_label(raw, slot_index=slot)
    except Exception:
        return raw or f"ROOM {slot}"


def read_rooms() -> dict[str, Any]:
    from pigeon.app_state import (
        LOCATION_PRESET_ROOM_NAMES,
        add_empty_location_v2,
        read_all_locations_v2,
        read_current_location_id,
    )

    locs = read_all_locations_v2()
    while len(locs) < ROOM_SLOTS:  # the screens always offer three rooms; match them
        add_empty_location_v2(f"ROOM {len(locs) + 1}")
        locs = read_all_locations_v2()
    current = read_current_location_id()
    rooms = []
    for i, loc in enumerate(locs[:ROOM_SLOTS], start=1):
        lid = str(loc.get("id") or "").strip()
        if not lid:
            continue
        rooms.append({
            "id": lid,
            "slot": i,
            "name": _room_label(str(loc.get("name") or "").strip(), i),
            "current": lid == current,
        })
    return {"current": current, "rooms": rooms, "presets": list(LOCATION_PRESET_ROOM_NAMES)}


def switch_room(room_id: str) -> None:
    from pigeon.app_state import set_current_location_id

    if not set_current_location_id(str(room_id or "").strip()):
        raise KeyError("unknown room")


def rename_room(room_id: str, name: Any) -> str:
    from pigeon.app_state import rename_location_v2

    nm = " ".join(str(name or "").split())
    if not 1 <= len(nm) <= ROOM_NAME_MAX:
        raise ValueError(f"name must be 1-{ROOM_NAME_MAX} characters")
    if not rename_location_v2(str(room_id or "").strip(), nm):
        raise KeyError("unknown room")
    return nm


# ---------------------------------------------------------- pigeon settings

def read_pigeon_settings() -> dict[str, Any]:
    from pigeon import pigeon_locale
    from pigeon.version import version_string
    from pigeon.widgets.options_settings import read_options
    from pigeon.widgets.ui_color_settings import read_ui_color_keys

    opts = read_options()
    return {
        "version": version_string(),
        "zip": pigeon_locale.read_zipcode() or None,
        "timezone": pigeon_locale.read_timezone(),
        "timezone_choices": list(pigeon_locale.timezone_choices()),
        "options": {k: opts.get(k) for k in OPTION_VALUES},
        "option_values": {k: list(v) for k, v in OPTION_VALUES.items()},
        "ui_color": read_ui_color_keys().get("ui"),
        "ui_color_choices": list(UI_COLORS),
    }


def patch_pigeon_settings(body: Mapping[str, Any]) -> None:
    """Validate everything first, then apply. Raises ValueError with the field name."""
    from pigeon import pigeon_locale

    errors: list[str] = []
    zip_raw = body.get("zip")
    if "zip" in body:
        if pigeon_locale.normalize_zip(str(zip_raw or "")) == "":
            errors.append("zip")
    tz = body.get("timezone")
    if "timezone" in body and str(tz or "") not in pigeon_locale.timezone_choices():
        errors.append("timezone")
    options = body.get("options")
    if "options" in body:
        if not isinstance(options, Mapping):
            errors.append("options")
        else:
            for k, v in options.items():
                if k not in OPTION_VALUES or str(v) not in OPTION_VALUES[k]:
                    errors.append(f"options.{k}")
    if "ui_color" in body and str(body.get("ui_color")) not in UI_COLORS:
        errors.append("ui_color")
    unknown = set(body) - {"zip", "timezone", "options", "ui_color"}
    errors += sorted(unknown)
    if errors:
        raise ValueError(",".join(errors))

    if isinstance(options, Mapping) and options:
        from pigeon.widgets.options_settings import read_options, write_options

        merged = dict(read_options())
        merged.update({k: str(v) for k, v in options.items()})
        write_options(merged)
    if "ui_color" in body:
        from pigeon.widgets.ui_color_settings import read_ui_color_keys, write_ui_color_keys

        keys = dict(read_ui_color_keys())
        keys["ui"] = str(body["ui_color"])
        write_ui_color_keys(keys)
    if "timezone" in body:
        pigeon_locale.set_timezone_manual(str(tz))
    if "zip" in body:
        pigeon_locale.set_zipcode_manual(str(zip_raw))
