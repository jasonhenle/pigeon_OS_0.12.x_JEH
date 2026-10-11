"""Boot phase: the settings Location section (selector, rename, delete).

Phase 4 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from pigeon.core import settings_ui as _core_settings_ui
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.core.binding import late as _late
import tkinter as tk


def run(ctx) -> None:
    S_FONT_BODY = ctx.S_FONT_BODY
    S_FONT_BTN = ctx.S_FONT_BTN
    S_FONT_MICRO = ctx.S_FONT_MICRO
    S_FONT_SEC = ctx.S_FONT_SEC
    _kiosk_on = ctx._kiosk_on
    settings_inner = ctx.settings_inner

    location_section = tk.Frame(settings_inner, bg="#111")
    location_section.pack(anchor=tk.W, fill=tk.X, pady=(8, 2))
    location_menu_var = tk.StringVar(value="")
    location_name_var = tk.StringVar(value="")
    location_option_holder: list[tk.OptionMenu | None] = [None]
    location_om_parent = tk.Frame(location_section, bg="#111")
    location_om_parent.pack(anchor=tk.W, fill=tk.X)
    tk.Label(
        location_om_parent,
        text="Current location",
        fg="#ccc",
        bg="#111",
        font=S_FONT_SEC,
    ).pack(side=tk.LEFT)
    location_om_frame = tk.Frame(location_om_parent, bg="#111")
    location_om_frame.pack(side=tk.LEFT, padx=(10, 0))
    delete_location_btn = tk.Button(
        location_om_parent,
        text="\u2715",
        font=("Helvetica", 12, "bold"),
        fg="#c44",
        bg="#111",
        activebackground="#2a1a1a",
        activeforeground="#f66",
        highlightthickness=1,
        highlightbackground="#553333",
        bd=0,
        cursor="none" if _kiosk_on else "hand2",
        padx=8,
        pady=0,
        command=lambda: None,
        state=tk.DISABLED,
    )
    delete_location_btn.pack(side=tk.LEFT, padx=(10, 0), anchor=tk.W)
    location_edit_row = tk.Frame(location_section, bg="#111")
    location_edit_row.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))
    tk.Label(
        location_edit_row,
        text="Location name",
        fg="#888",
        bg="#111",
        font=S_FONT_MICRO,
    ).pack(side=tk.LEFT)
    location_name_entry = tk.Entry(
        location_edit_row,
        textvariable=location_name_var,
        width=28,
        bg="#1a1a1e",
        fg="#e8e8e8",
        insertbackground="#e8e8e8",
        highlightthickness=1,
        highlightbackground="#333",
        font=S_FONT_BODY,
    )
    location_name_entry.pack(side=tk.LEFT, padx=(8, 6))

    _apply_location_rename = _bind_deps(
        _core_settings_ui._apply_location_rename,
        _apply_persisted_location_to_runtime=_late(lambda: ctx._apply_persisted_location_to_runtime, "_apply_persisted_location_to_runtime"),
        _refresh_location_selector=_late(lambda: ctx._refresh_location_selector, "_refresh_location_selector"),
        _start_location_toast=_late(lambda: ctx._start_location_toast, "_start_location_toast"),
        location_name_var=location_name_var,
    )

    rename_name_btn = tk.Button(
        location_edit_row,
        text="Save name",
        command=_apply_location_rename,
        font=S_FONT_BTN,
        padx=10,
        pady=2,
    )
    rename_name_btn.pack(side=tk.LEFT)

    _on_location_name_return = _bind_deps(
        _core_settings_ui._on_location_name_return,
        _apply_location_rename=_apply_location_rename,
    )

    location_name_entry.bind("<Return>", _on_location_name_return)
    tk.Label(
        location_section,
        text="Playback and overlay follow the active location. Rename anytime; home room names are not inferred from device scan — set them here or when adding a custom location in Find device.",
        fg="#666",
        bg="#111",
        font=S_FONT_MICRO,
        wraplength=520,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, pady=(2, 0))

    ctx.delete_location_btn = delete_location_btn
    ctx.location_menu_var = location_menu_var
    ctx.location_name_entry = location_name_entry
    ctx.location_name_var = location_name_var
    ctx.location_om_frame = location_om_frame
    ctx.location_option_holder = location_option_holder
    ctx.rename_name_btn = rename_name_btn
