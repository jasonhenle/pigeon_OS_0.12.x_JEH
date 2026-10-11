# Pigeon Settings (settings_main)

## Tab cycle

| Press | Result |
|-------|--------|
| Tab / Shift+Tab / F9 / right-click | Toggle **settings_main** ↔ OFF |

Never enters the design grid via Tab (grid remains key 5).

While in **settings_main**: Left/Right move focus; Spacebar activates the focused control (`exit` returns to OFF). Activating **location** or **network** opens the text keyboard overlay (same Left/Right/Space controls). Deeper pages (pigeon settings, preferences, update popup) stay on the same `DevPhase.MAIN_SETTINGS` composite.

Preferences zone nav: zone1 → zone5 → **color** → BACK. The color control uses `settings_pigeon_preferences_color_*` layers (graphic selected/deselected + text pill).

## Surfaces

| Name | Module / surface | Asset |
|------|------------------|-------|
| **settings_main** | `pigeon/widgets/main_settings.py` + OpenCV composite | `pigeonAssets/settings_0.8/settings_main.svg` |
| **pigeon settings** | `pigeon/widgets/pigeon_settings.py` (0.11 flat page, see below) | `pigeonAssets/settings/pigeon/settings_pigeon.svg` |
| **preferences** | `pigeon/widgets/preferences_settings.py` | `pigeon_settings_preferences.svg` |
| **update popup** | `pigeon/widgets/update_popup.py` | update SVG layers |
| **keyboards** | `pigeon/widgets/settings_keyboard.py` | `keyboard_*.svg` |

`DevPhase.MAIN_SETTINGS = 2` (SVG stack only). The legacy Tk settings form is no longer reachable.

## settings_pigeon (0.11)

One flat page, opened from settings_main box1. Nothing opens a sub-page except
the zip keypad, the timezone dropdown and the update popup.

Focus order: **EXIT → ZIP → TIMEZONE → blue, green, yellow, orange, red, grey,
white → 12/24 hr → °F/°C → theme/dark → RESET → UPDATE**. The clock, version
and the wifi / metadata / audio lights are not selectable.

- **EXIT** returns to now playing (settings_main while WiFi setup still locks settings open).
- **ZIP** opens the numeric keypad. The zip is guessed once from the public IP
  when settings opens (`pigeon/pigeon_locale.py`); a typed zip wins, sets the
  timezone for that zip, and drives the weather widget. Shows `ENTER` when unknown.
- **TIMEZONE** opens a dropdown (`CST -1:00` = offset from the current zone).
  It applies to Pigeon's clocks only (`pigeon_now()`); the OS clock is untouched.
- **Colors** preview live while focused; activating commits. Leaving the row
  falls back to the committed color. Theme hexes are the `ui_color_*_icon` fills.
- **Options** toggle `time_format`, `temp_format`, `color_format` (dark = red
  monochrome). The knob shown is the circle nearest the active label (the export's
  `toggle_a` / `toggle_b` names are swapped relative to their labels).
- **Lights**: wifi green while associated; metadata / audio green when seen in
  the last 60 s (`pigeon/source_status.py`).

The now-play widget picker and the old options / color bars are retired: now
playing always uses the default zone layout, and the old clock-face, idle-delay
and clocksaver-off switches read as their defaults.

## Assets

## Keyboards

Runtime SVGs under `settings_0.8/`:

- `keyboard_bottom_row.svg` — shared ABC / abc / sym / space / delete / cancel / go
- `keyboard_qwerty_lower.svg` / `keyboard_qwerty_upper.svg`
- `keyboard_numeric_all.svg` (layer ids use `keyboard_numeric_full_*`)
- `keyboard_numeric_pin.svg` — Apple TV pairing PIN
- `keyboard_symbolic.svg`

Module: `pigeon/widgets/settings_keyboard.py`.

**Open:** Space on location or network in main_settings opens the qwerty keyboard overlay.
**Nav:** Left/Right move key focus; Space activates (type / mode switch / delete / cancel / go).
**Close:** cancel discards; go commits text back into location/network.

`keyboard_numeric_ip` is specified in instructions but not yet in the GFX export set.

Override main SVG path with env `PIGEON_MAIN_SETTINGS_SVG`.

## Layer classes

- `_text` — dynamic content; fill/stroke follow selection
- `_icon` — fixed form; fill/stroke follow selection
- `_button` — fixed form; fill/stroke follow selection; default fill ~`#202020`; bottommost vs paired layers
- `_accent` — theme accent (default white); **not** changed by selection
- `_group` — parent grouping / position
- `_container` — static chrome; bottommost in a group when present

Illustrator ids encode `_` as `_x5F_` and leading `0` as `_x30_`. Use `decode_svg_id` / `encode_svg_id` in `main_settings.py`.

## Colors

| Role | Default |
|------|---------|
| UI | `#ff0013` (user configurable later) |
| Selected | `#02e900` |
| Deselected | `#202020` |
| Accent | `#FFFFFF` (selection does not change accent) |
| Inactive | dark gray (not user configurable) |

Selected button → green fill, black contrasting text/icons.  
Deselected button → black fill, green contrasting text/icons.  
`text_pigeonVersion` stays black when present.

**Fonts:** layers under `main_instructions` and all keyboard text use **Sharp Sans Semibold**; other UI text (device names, IPs, EXIT, location/network labels, etc.) use **Digital-7 Regular**.

Design source of truth: `settingInstructions_0.8.0.numbers` (under `pigeonAssets/settings_0.8/` and optionally `docs/`).
