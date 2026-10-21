"""
Text-entry field drawing for the main settings menu.

Field specs (``_TEXT_ENTRY_FIELDS``), font sizing / loading, password masking, cursor
placement and the Pillow draw routines that render the active entry buffer from a
``MainSettingsState`` onto the settings BGRA frame. Reads state; never mutates it.

Also owns the artboard height and gray constants these routines share with
``main_settings``, which re-imports them (along with every other name here).
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pigeon.design import DESIGN_H, DESIGN_W
from pigeon.font_paths import resolve_digital7_font, resolve_ui_font_medium
from pigeon.widgets.settings_state import MainSettingsState


_ARTBOARD_H = 480.0


_COLOR_GRAY_RGBA = (128, 128, 128, 255)


_TEXT_ENTRY_FIELDS: dict[str, dict[str, float | str | bool]] = {
    "location": {
        "text_id": "main_dual_location_text",
        "x0_svg": 82.0,
        "x1_svg": 383.5,
        "baseline_y_svg": 184.05,
        "font_size_svg": 35.0,
        "font": "digital7",
        "uppercase_only": True,
        "password_mask": False,
    },
    "network": {
        "text_id": "main_dual_network_name_text",
        "x0_svg": 417.0,
        "x1_svg": 717.8,
        "baseline_y_svg": 184.05,
        "font_size_svg": 35.0,
        "font": "sharp_medium",
        "uppercase_only": False,
        "password_mask": True,
        "placeholder": "password",
        "placeholder_font_size_svg": 30.0,
        "placeholder_baseline_offset_px": -1,
    },
    "pin": {
        "text_id": "main_dual_network_name_text",
        "x0_svg": 417.0,
        "x1_svg": 717.8,
        "baseline_y_svg": 184.05,
        "font_size_svg": 35.0,
        "font": "digital7",
        "uppercase_only": True,
        "password_mask": False,
        "placeholder": "ENTER PIN",
    },
    "device_ip": {
        "text_id": "main_dual_network_name_text",
        "x0_svg": 417.0,
        "x1_svg": 717.8,
        "baseline_y_svg": 184.05,
        "font_size_svg": 35.0,
        "font": "digital7",
        "uppercase_only": False,
        "password_mask": False,
    },
    "device_name": {
        "text_id": "main_dual_location_text",
        "x0_svg": 82.0,
        "x1_svg": 383.5,
        "baseline_y_svg": 184.05,
        "font_size_svg": 35.0,
        "font": "digital7",
        "uppercase_only": True,
        "password_mask": False,
        "placeholder": "NEW DEVICE",
    },
}


_DUAL_NETWORK_TEXT_X0_SVG = 417.0


_DUAL_NETWORK_TEXT_X1_SVG = 717.8


def _dual_location_text_bounds_px(root: ET.Element | None = None) -> tuple[int, int]:
    from pigeon.settings_layout import DUAL_SLOT_A, dual_slot_design

    del root
    x, _y, w, _h = dual_slot_design(DUAL_SLOT_A)
    return x + 96, x + max(97, w - 16)


def _text_field_spec(target: str) -> dict[str, float | str | bool] | None:
    return _TEXT_ENTRY_FIELDS.get(target)


def _location_text_is_grayed(state: MainSettingsState) -> bool:
    """True when dual-location shows placeholder gray (replace mode, not append)."""
    if state.show_instructions:
        return True
    name = str(state.location_name or "").strip().lower()
    return name in ("", "nest 1", "nest1", "room 1", "room1")


@lru_cache(maxsize=4)
def _load_digital7(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = resolve_digital7_font()
    if not path:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, max(6, size_px))
    except OSError:
        return ImageFont.load_default()


def _field_font_size_px(font_size_svg: float) -> int:
    return max(6, int(round(font_size_svg * DESIGN_H / _ARTBOARD_H)))


def _fit_text_font_size(
    text: str,
    font_fn,
    *,
    max_width_px: int,
    start_px: int,
) -> tuple[int, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    size = max(6, int(start_px))
    font = font_fn(size)
    while size > 6 and probe.textlength(text, font=font) > max_width_px:
        size -= 1
        font = font_fn(size)
    return size, font


def _draw_centered_field_text(
    draw: ImageDraw.ImageDraw,
    *,
    x0_px: int,
    x1_px: int,
    baseline_px: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
) -> None:
    if not text:
        return
    bbox = draw.textbbox((0, 0), text, font=font, anchor="ls")
    tw = bbox[2] - bbox[0]
    cx = (x0_px + x1_px) // 2
    draw.text((cx - tw // 2, baseline_px), text, font=font, fill=fill, anchor="ls")


def _entry_content_font_size_px(
    spec: dict[str, float | str | bool],
    *,
    buffer: str,
    display: str,
    max_width_px: int | None = None,
) -> int:
    if display == "incorrect password" and max_width_px is not None:
        start = min(_field_font_size_px(float(spec["font_size_svg"])) - 10, 18)
        font_fn = lambda s: _field_font(spec, s)
        size, _font = _fit_text_font_size(
            display, font_fn, max_width_px=max_width_px, start_px=max(8, start)
        )
        return max(8, min(size, 18))
    placeholder = str(spec.get("placeholder", "") or "")
    is_placeholder = (
        not buffer
        and spec.get("password_mask")
        and display == placeholder
    )
    if is_placeholder:
        ph_size = spec.get("placeholder_font_size_svg")
        if ph_size is not None:
            return _field_font_size_px(float(ph_size))
        return max(6, _field_font_size_px(float(spec["font_size_svg"])) - 5)
    return _field_font_size_px(float(spec["font_size_svg"]))


@lru_cache(maxsize=4)
def _load_sharp_medium(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = resolve_ui_font_medium()
    if not path:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, max(6, size_px))
    except OSError:
        return ImageFont.load_default()


def _field_font(spec: dict[str, float | str | bool], size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if spec.get("font") == "sharp_medium":
        return _load_sharp_medium(size_px)
    return _load_digital7(size_px)


def _password_mask_display(buffer: str) -> str:
    """Reveal only the most recently typed character (e.g. ``**g``)."""
    if not buffer:
        return ""
    if len(buffer) == 1:
        return buffer
    return ("*" * (len(buffer) - 1)) + buffer[-1]


def _asterisk_font_for_password_mask(
    draw: ImageDraw.ImageDraw,
    spec: dict[str, float | str | bool],
    *,
    size_px: int,
    visible: str,
    base_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return a font sized so ``*`` matches the visible character height (~2× body size)."""
    vis_bbox = draw.textbbox((0, 0), visible or "0", font=base_font, anchor="ls")
    vis_h = max(1, vis_bbox[3] - vis_bbox[1])
    target = max(size_px + 4, int(round(size_px * 2.0)))
    best = _field_font(spec, target)
    best_bbox = draw.textbbox((0, 0), "*", font=best, anchor="ls")
    best_h = best_bbox[3] - best_bbox[1]
    for candidate in range(target, max(size_px, target - 8), -1):
        trial = _field_font(spec, candidate)
        trial_bbox = draw.textbbox((0, 0), "*", font=trial, anchor="ls")
        trial_h = trial_bbox[3] - trial_bbox[1]
        if trial_h <= vis_h:
            best = trial
            best_h = trial_h
            break
        best = trial
        best_h = trial_h
    if best_h > vis_h * 1.15:
        for candidate in range(target - 1, size_px, -1):
            trial = _field_font(spec, candidate)
            trial_bbox = draw.textbbox((0, 0), "*", font=trial, anchor="ls")
            trial_h = trial_bbox[3] - trial_bbox[1]
            if trial_h <= vis_h * 1.05:
                return trial
    return best


def _password_mask_layout(
    draw: ImageDraw.ImageDraw,
    *,
    cx: int,
    baseline_px: int,
    display: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    spec: dict[str, float | str | bool],
    size_px: int,
) -> tuple[int, int, int, int, int, int, int]:
    """
    Layout ``***x`` with enlarged asterisks.

    Returns ``(x0, mask_y, mask_w, vis_w, cursor_x, text_top, text_bottom)``.
    """
    if not display or "*" not in display:
        bbox = draw.textbbox((0, 0), display, font=font, anchor="ls")
        tw = bbox[2] - bbox[0]
        top = int(baseline_px + bbox[1])
        bot = int(baseline_px + bbox[3])
        x0 = cx - tw // 2
        return x0, baseline_px, tw, 0, x0 + tw + 2, top, bot

    visible = display[-1]
    mask_str = display[:-1]
    vis_bbox = draw.textbbox((0, 0), visible, font=font, anchor="ls")
    vis_w = vis_bbox[2] - vis_bbox[0]
    vis_center_y = baseline_px + (vis_bbox[1] + vis_bbox[3]) * 0.5

    ast_font = _asterisk_font_for_password_mask(
        draw, spec, size_px=size_px, visible=visible, base_font=font
    )
    mask_bbox = draw.textbbox((0, 0), mask_str, font=ast_font, anchor="ls")
    mask_w = mask_bbox[2] - mask_bbox[0]
    mask_center_offset = (mask_bbox[1] + mask_bbox[3]) * 0.5
    mask_y = int(round(vis_center_y - mask_center_offset))

    total_w = mask_w + vis_w
    x0 = cx - total_w // 2
    top = int(min(mask_y + mask_bbox[1], baseline_px + vis_bbox[1]))
    bot = int(max(mask_y + mask_bbox[3], baseline_px + vis_bbox[3]))
    return x0, mask_y, mask_w, vis_w, x0 + total_w + 2, top, bot


def _draw_password_mask_text(
    draw: ImageDraw.ImageDraw,
    *,
    cx: int,
    baseline_px: int,
    display: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    spec: dict[str, float | str | bool],
    size_px: int,
    fill: tuple[int, int, int, int],
) -> tuple[int, int, int]:
    """
    Draw ``***x`` with enlarged, vertically centered asterisks.

    Returns ``(cursor_x, text_top, text_bottom)`` for the insertion caret.
    """
    if not display or "*" not in display:
        bbox = draw.textbbox((0, 0), display, font=font, anchor="ls")
        tw = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, baseline_px), display, font=font, fill=fill, anchor="ls")
        top = baseline_px + bbox[1]
        bot = baseline_px + bbox[3]
        return cx - tw // 2 + tw + 2, int(top), int(bot)

    visible = display[-1]
    mask_str = display[:-1]
    ast_font = _asterisk_font_for_password_mask(
        draw, spec, size_px=size_px, visible=visible, base_font=font
    )
    x0, mask_y, mask_w, _vis_w, cursor_x, top, bot = _password_mask_layout(
        draw,
        cx=cx,
        baseline_px=baseline_px,
        display=display,
        font=font,
        spec=spec,
        size_px=size_px,
    )
    draw.text((x0, mask_y), mask_str, font=ast_font, fill=fill, anchor="ls")
    draw.text((x0 + mask_w, baseline_px), visible, font=font, fill=fill, anchor="ls")
    return cursor_x, top, bot


def _entry_display_text(
    *,
    buffer: str,
    initial: str,
    spec: dict[str, float | str | bool],
    state: MainSettingsState | None = None,
) -> str:
    if (
        state is not None
        and state.network_password_error
        and spec.get("password_mask")
        and not buffer
    ):
        return "incorrect password"
    if buffer:
        if spec.get("password_mask"):
            return _password_mask_display(buffer)
        if spec.get("uppercase_only"):
            return buffer.upper()
        return buffer
    placeholder = str(spec.get("placeholder", "") or "")
    if spec.get("password_mask") and placeholder:
        return placeholder
    if initial:
        if spec.get("uppercase_only"):
            return initial.upper()
        return initial
    return ""


def _entry_field_bounds_px(target: str) -> tuple[int, int]:
    """Pixel bounds for the active dual-bar field (matches ``_draw_text_entry_content``)."""
    if target in ("location", "device_name"):
        return _dual_location_text_bounds_px()
    if target in ("network", "pin", "device_ip"):
        return (
            int(round(_DUAL_NETWORK_TEXT_X0_SVG * DESIGN_W / 800.0)),
            int(round(_DUAL_NETWORK_TEXT_X1_SVG * DESIGN_W / 800.0)),
        )
    spec = _text_field_spec(target)
    if spec is None:
        return 0, DESIGN_W
    return (
        int(round(float(spec["x0_svg"]) * DESIGN_W / 800.0)),
        int(round(float(spec["x1_svg"]) * DESIGN_W / 800.0)),
    )


def _entry_cursor_display(
    *,
    buffer: str,
    initial: str,
    spec: dict[str, float | str | bool],
    state: MainSettingsState | None = None,
) -> str:
    """Rendered string used to place the caret at the end of the editable text."""
    if (
        state is not None
        and state.network_password_error
        and spec.get("password_mask")
        and not buffer
    ):
        return "incorrect password"
    edit = buffer if buffer else initial
    if not edit:
        return ""
    if spec.get("password_mask"):
        return _password_mask_display(edit)
    if spec.get("uppercase_only"):
        return edit.upper()
    return edit


def _clamp_field_cursor_x(cursor_x: int, *, x0_px: int, x1_px: int) -> int:
    return max(x0_px + 2, min(x1_px - 2, int(cursor_x)))


def _draw_text_entry_content(bgra: np.ndarray, state: MainSettingsState) -> None:
    """Paint centered dual-bar text while the keyboard is open (no cursor)."""
    kb = state.keyboard
    if kb is None and not state.wifi_connecting:
        return
    target = ""
    buffer = ""
    initial = ""
    if kb is not None:
        target = str(getattr(kb, "target", "") or "")
        buffer = str(getattr(kb, "buffer", "") or "")
        initial = str(getattr(kb, "initial_text", "") or "")
    if state.wifi_connecting and not target:
        target = "network"
    if target == "wifi_logout" and state.keyboard_open:
        baseline_px = int(round(float(_TEXT_ENTRY_FIELDS["location"]["baseline_y_svg"]) * DESIGN_H / _ARTBOARD_H))
        loc_x0, loc_x1 = _dual_location_text_bounds_px()
        rgb = cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA)
        img = Image.fromarray(rgb)
        draw = ImageDraw.Draw(img)
        ssid = str(state.selected_wifi_ssid or "").strip()
        if ssid:
            loc_spec = _TEXT_ENTRY_FIELDS["location"]
            ssid_size = _entry_content_font_size_px(
                loc_spec,
                buffer=ssid,
                display=ssid,
                max_width_px=max(24, loc_x1 - loc_x0 - 56),
            )
            ssid_font = _field_font(loc_spec, ssid_size)
            _draw_centered_field_text(
                draw,
                x0_px=loc_x0,
                x1_px=loc_x1,
                baseline_px=baseline_px,
                text=ssid,
                font=ssid_font,
                fill=(255, 255, 255, 255),
            )
        bgra[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)
        return
    spec = _text_field_spec(target)
    if spec is None:
        return
    baseline_px = int(round(float(spec["baseline_y_svg"]) * DESIGN_H / _ARTBOARD_H))
    rgb = cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA)
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)

    if state.wifi_connecting and not state.keyboard_open:
        loc_x0, loc_x1 = _dual_location_text_bounds_px()
        net_x0 = int(round(_DUAL_NETWORK_TEXT_X0_SVG * DESIGN_W / 800.0))
        net_x1 = int(round(_DUAL_NETWORK_TEXT_X1_SVG * DESIGN_W / 800.0))
        loc_spec = _TEXT_ENTRY_FIELDS["location"]
        loc_name = str(state.location_name or "nest 1").strip() or "nest 1"
        loc_size = _entry_content_font_size_px(
            loc_spec,
            buffer=loc_name,
            display=loc_name.upper(),
            max_width_px=max(24, loc_x1 - loc_x0 - 16),
        )
        loc_font = _field_font(loc_spec, loc_size)
        _draw_centered_field_text(
            draw,
            x0_px=loc_x0,
            x1_px=loc_x1,
            baseline_px=baseline_px,
            text=loc_name.upper(),
            font=loc_font,
            fill=(255, 255, 255, 255),
        )
        ssid = str(state.pending_wifi_ssid or state.selected_wifi_ssid or "").strip()
        if ssid:
            net_spec = _TEXT_ENTRY_FIELDS["network"]
            ssid_size = _entry_content_font_size_px(
                net_spec,
                buffer=ssid,
                display=ssid,
                max_width_px=max(24, net_x1 - net_x0 - 16),
            )
            ssid_font = _field_font(net_spec, ssid_size)
            _draw_centered_field_text(
                draw,
                x0_px=net_x0,
                x1_px=net_x1,
                baseline_px=baseline_px,
                text=ssid,
                font=ssid_font,
                fill=_COLOR_GRAY_RGBA,
            )
        bgra[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)
        return

    if target == "network" and state.keyboard_open:
        ssid = str(state.pending_wifi_ssid or state.selected_wifi_ssid or "").strip()
        if ssid:
            loc_x0, loc_x1 = _dual_location_text_bounds_px()
            loc_spec = _TEXT_ENTRY_FIELDS["location"]
            ssid_size = _entry_content_font_size_px(
                loc_spec,
                buffer=ssid,
                display=ssid,
                max_width_px=max(24, loc_x1 - loc_x0 - 56),
            )
            ssid_font = _field_font(loc_spec, ssid_size)
            ssid_fill = _COLOR_GRAY_RGBA if state.network_password_error else (255, 255, 255, 255)
            _draw_centered_field_text(
                draw,
                x0_px=loc_x0,
                x1_px=loc_x1,
                baseline_px=baseline_px,
                text=ssid.upper(),
                font=ssid_font,
                fill=ssid_fill,
            )
    elif target == "location":
        loc_x0, loc_x1 = _dual_location_text_bounds_px()
        loc_spec = _TEXT_ENTRY_FIELDS["location"]
        loc_display = _entry_display_text(buffer=buffer, initial=initial, spec=loc_spec, state=state)
        if loc_display:
            loc_size = _entry_content_font_size_px(
                loc_spec,
                buffer=buffer,
                display=loc_display,
                max_width_px=max(24, loc_x1 - loc_x0 - 16),
            )
            loc_font = _field_font(loc_spec, loc_size)
            loc_fill = (
                _COLOR_GRAY_RGBA
                if (not buffer and _location_text_is_grayed(state))
                else (255, 255, 255, 255)
            )
            _draw_centered_field_text(
                draw,
                x0_px=loc_x0,
                x1_px=loc_x1,
                baseline_px=baseline_px,
                text=loc_display,
                font=loc_font,
                fill=loc_fill,
            )
        bgra[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)
        return

    if kb is None and state.manual_device_entry is not None:
        entry = state.manual_device_entry
        loc_x0, loc_x1 = _dual_location_text_bounds_px()
        net_x0 = int(round(_DUAL_NETWORK_TEXT_X0_SVG * DESIGN_W / 800.0))
        net_x1 = int(round(_DUAL_NETWORK_TEXT_X1_SVG * DESIGN_W / 800.0))
        loc_spec = _TEXT_ENTRY_FIELDS["device_name"]
        net_spec = _TEXT_ENTRY_FIELDS["device_ip"]
        loc_font = _field_font(loc_spec, _entry_content_font_size_px(
            loc_spec, buffer="", display="NEW DEVICE", max_width_px=max(24, loc_x1 - loc_x0 - 16)
        ))
        _draw_centered_field_text(
            draw,
            x0_px=loc_x0,
            x1_px=loc_x1,
            baseline_px=baseline_px,
            text="NEW DEVICE",
            font=loc_font,
            fill=_COLOR_GRAY_RGBA,
        )
        ip_text = str(entry.ip or "").strip()
        if ip_text:
            ip_size = _entry_content_font_size_px(
                net_spec, buffer=ip_text, display=ip_text, max_width_px=max(24, net_x1 - net_x0 - 16)
            )
            ip_font = _field_font(net_spec, ip_size)
            _draw_centered_field_text(
                draw,
                x0_px=net_x0,
                x1_px=net_x1,
                baseline_px=baseline_px,
                text=ip_text,
                font=ip_font,
                fill=(255, 255, 255, 255),
            )
        bgra[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)
        return

    if target == "pin":
        loc_x0, loc_x1 = _dual_location_text_bounds_px()
        net_x0 = int(round(_DUAL_NETWORK_TEXT_X0_SVG * DESIGN_W / 800.0))
        net_x1 = int(round(_DUAL_NETWORK_TEXT_X1_SVG * DESIGN_W / 800.0))
        device_name = ""
        if state.box_pairing is not None:
            device_name = str(state.box_pairing.device_name or "").strip().upper()
        if device_name:
            loc_spec = _TEXT_ENTRY_FIELDS["location"]
            loc_size = _entry_content_font_size_px(
                loc_spec,
                buffer=device_name,
                display=device_name,
                max_width_px=max(24, loc_x1 - loc_x0 - 16),
            )
            loc_font = _field_font(loc_spec, loc_size)
            _draw_centered_field_text(
                draw,
                x0_px=loc_x0,
                x1_px=loc_x1,
                baseline_px=baseline_px,
                text=device_name,
                font=loc_font,
                fill=(255, 255, 255, 255),
            )
        pin_spec = _TEXT_ENTRY_FIELDS["pin"]
        pin_display = _entry_display_text(buffer=buffer, initial=initial, spec=pin_spec, state=state)
        if pin_display:
            pin_size = _entry_content_font_size_px(
                pin_spec,
                buffer=buffer,
                display=pin_display,
                max_width_px=max(24, net_x1 - net_x0 - 16),
            )
            pin_font = _field_font(pin_spec, pin_size)
            pin_fill = _COLOR_GRAY_RGBA if not buffer else (255, 255, 255, 255)
            _draw_centered_field_text(
                draw,
                x0_px=net_x0,
                x1_px=net_x1,
                baseline_px=baseline_px,
                text=pin_display,
                font=pin_font,
                fill=pin_fill,
            )
        bgra[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)
        return

    if target == "device_ip":
        loc_x0, loc_x1 = _dual_location_text_bounds_px()
        net_x0 = int(round(_DUAL_NETWORK_TEXT_X0_SVG * DESIGN_W / 800.0))
        net_x1 = int(round(_DUAL_NETWORK_TEXT_X1_SVG * DESIGN_W / 800.0))
        loc_spec = _TEXT_ENTRY_FIELDS["device_name"]
        loc_font = _field_font(loc_spec, _entry_content_font_size_px(
            loc_spec, buffer="", display="NEW DEVICE", max_width_px=max(24, loc_x1 - loc_x0 - 16)
        ))
        _draw_centered_field_text(
            draw,
            x0_px=loc_x0,
            x1_px=loc_x1,
            baseline_px=baseline_px,
            text="NEW DEVICE",
            font=loc_font,
            fill=_COLOR_GRAY_RGBA,
        )
        ip_spec = _TEXT_ENTRY_FIELDS["device_ip"]
        ip_display = _entry_display_text(buffer=buffer, initial=initial, spec=ip_spec, state=state)
        if ip_display:
            ip_size = _entry_content_font_size_px(
                ip_spec, buffer=buffer, display=ip_display, max_width_px=max(24, net_x1 - net_x0 - 16)
            )
            ip_font = _field_font(ip_spec, ip_size)
            _draw_centered_field_text(
                draw,
                x0_px=net_x0,
                x1_px=net_x1,
                baseline_px=baseline_px,
                text=ip_display,
                font=ip_font,
                fill=(255, 255, 255, 255),
            )
        bgra[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)
        return

    if target == "device_name":
        entry = state.manual_device_entry
        loc_x0, loc_x1 = _dual_location_text_bounds_px()
        net_x0 = int(round(_DUAL_NETWORK_TEXT_X0_SVG * DESIGN_W / 800.0))
        net_x1 = int(round(_DUAL_NETWORK_TEXT_X1_SVG * DESIGN_W / 800.0))
        name_spec = _TEXT_ENTRY_FIELDS["device_name"]
        name_display = _entry_display_text(buffer=buffer, initial=initial, spec=name_spec, state=state)
        if name_display:
            name_size = _entry_content_font_size_px(
                name_spec, buffer=buffer, display=name_display, max_width_px=max(24, loc_x1 - loc_x0 - 16)
            )
            name_font = _field_font(name_spec, name_size)
            name_fill = _COLOR_GRAY_RGBA if (not buffer and name_display == "NEW DEVICE") else (255, 255, 255, 255)
            _draw_centered_field_text(
                draw,
                x0_px=loc_x0,
                x1_px=loc_x1,
                baseline_px=baseline_px,
                text=name_display,
                font=name_font,
                fill=name_fill,
            )
        ip_text = str(entry.ip or "").strip() if entry is not None else ""
        if ip_text:
            ip_spec = _TEXT_ENTRY_FIELDS["device_ip"]
            ip_size = _entry_content_font_size_px(
                ip_spec, buffer=ip_text, display=ip_text, max_width_px=max(24, net_x1 - net_x0 - 16)
            )
            ip_font = _field_font(ip_spec, ip_size)
            _draw_centered_field_text(
                draw,
                x0_px=net_x0,
                x1_px=net_x1,
                baseline_px=baseline_px,
                text=ip_text,
                font=ip_font,
                fill=(255, 255, 255, 255),
            )
        bgra[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)
        return

    if target != "network":
        bgra[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)
        return

    x0_px = int(round(float(spec["x0_svg"]) * DESIGN_W / 800.0))
    x1_px = int(round(float(spec["x1_svg"]) * DESIGN_W / 800.0))
    display = _entry_display_text(buffer=buffer, initial=initial, spec=spec, state=state)
    placeholder = str(spec.get("placeholder", "") or "")
    max_field_w = max(24, x1_px - x0_px - 8)
    size_px = _entry_content_font_size_px(
        spec, buffer=buffer, display=display, max_width_px=max_field_w
    )
    font = _field_font(spec, size_px)
    cx = (x0_px + x1_px) // 2
    if display and state.keyboard_open:
        is_password_error = (
            state.network_password_error
            and spec.get("password_mask")
            and display == "incorrect password"
        )
        is_placeholder = (
            not buffer
            and spec.get("password_mask")
            and display == placeholder
        )
        is_initial_gray = not buffer and bool(initial) and not spec.get("password_mask")
        fill = _COLOR_GRAY_RGBA if (is_placeholder or is_initial_gray or is_password_error) else (255, 255, 255, 255)
        text_y = baseline_px
        if is_placeholder:
            text_y += int(spec.get("placeholder_baseline_offset_px", 0))
        use_mask_center = bool(spec.get("password_mask") and buffer and "*" in display)
        if use_mask_center:
            _draw_password_mask_text(
                draw,
                cx=cx,
                baseline_px=baseline_px,
                display=display,
                font=font,
                spec=spec,
                size_px=size_px,
                fill=fill,
            )
        else:
            _draw_centered_field_text(
                draw,
                x0_px=x0_px,
                x1_px=x1_px,
                baseline_px=text_y,
                text=display,
                font=font,
                fill=fill,
            )
    bgra[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)


def _centered_field_cursor_x(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    x0_px: int,
    x1_px: int,
) -> int:
    """Insertion caret immediately after the last rendered character."""
    if not text:
        return x0_px + 8
    bbox = draw.textbbox((0, 0), text, font=font, anchor="ls")
    tw = bbox[2] - bbox[0]
    cx = (x0_px + x1_px) // 2
    return cx - tw // 2 + tw + 1


def _draw_text_entry_cursor(
    bgra: np.ndarray, state: MainSettingsState, *, force: bool = False
) -> None:
    """Blinking insertion caret aligned with the 1280 dual-bar field text."""
    from pigeon.settings_layout import DUAL_SLOT_A, DUAL_SLOT_B, dual_slot_design
    from pigeon.widgets.settings_main_1280 import (
        _fit_font,
        _location_field_boxes,
        _network_field_boxes,
        _pin_digits_box,
    )

    kb = state.keyboard
    if kb is None:
        return
    if not force and int(time.monotonic() * 2) % 2:
        return
    target = str(getattr(kb, "target", "") or "")
    if target not in ("location", "device_name", "network", "pin", "device_ip"):
        return
    buffer = str(getattr(kb, "buffer", "") or "")
    initial = str(getattr(kb, "initial_text", "") or "")
    if target in ("location", "device_name"):
        _dots, box = _location_field_boxes(dual_slot_design(DUAL_SLOT_A))
        display = (buffer or initial).upper()
    elif target == "pin":
        box = _pin_digits_box(dual_slot_design(DUAL_SLOT_B))
        display = buffer
    else:
        _wifi, box = _network_field_boxes(dual_slot_design(DUAL_SLOT_B))
        display = ("*" * len(buffer)) if target == "network" else (buffer or initial).upper()
    x, y, w, h = box
    if w < 8 or h < 8:
        return
    if display:
        font, tw, th, top, left = _fit_font(
            display, max_w=w - 10, max_h=h - 4, start=48, digital=True
        )
        tx = (w - tw) // 2 - left
        ty = (h - th) // 2 - top
        probe = Image.new("L", (max(1, w), max(1, h)), 0)
        ImageDraw.Draw(probe).text((tx, ty), display, font=font, fill=255)
        # Ignore the font's anti-alias fringe so the bar matches the glyph body.
        ys, xs = np.where(np.asarray(probe) > 170)
        if ys.size:
            caret_x = x + int(xs.max()) + 3
            caret_top = y + int(ys.min())
            caret_bot = y + int(ys.max()) + 1
        else:
            caret_x = x + tx + tw + 2
            caret_top = y + max(8, h // 4)
            caret_bot = y + h - max(8, h // 4)
    else:
        caret_x = x + w // 2
        caret_top = y + max(8, h // 4)
        caret_bot = y + h - max(8, h // 4)
    caret_x = max(x + 4, min(x + w - 4, caret_x))
    rgb = cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA)
    img = Image.fromarray(rgb)
    ImageDraw.Draw(img).line(
        [(caret_x, caret_top), (caret_x, caret_bot)], fill=(0, 0, 0, 255), width=2
    )
    bgra[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGBA2BGRA)
