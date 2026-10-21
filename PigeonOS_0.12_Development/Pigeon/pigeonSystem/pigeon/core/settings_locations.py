"""
Location management for the settings screen.

Current-location display name, rename and delete actions, the location selector refresh
and the location-switch toast. Same contract as the rest of ``settings_ui``: keyword-only
dependencies bound with ``bind_deps`` in the boot phases.

``pigeon.core.settings_ui`` re-exports every name here, so the boot phases that look the
functions up on ``settings_ui`` are unchanged.
"""

from __future__ import annotations

import time
import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.simpledialog as simpledialog

from pigeon.app_state import add_empty_location_v2
from pigeon.app_state import delete_location_v2
from pigeon.app_state import read_all_locations_v2
from pigeon.app_state import read_current_location_id
from pigeon.app_state import rename_location_v2
from pigeon.app_state import set_current_location_id


def _on_location_name_return(_event: tk.Event, *, _apply_location_rename) -> str:
    _apply_location_rename()
    return "break"


def _current_location_display_name() -> str:
    cid = (read_current_location_id() or "").strip()
    for L in read_all_locations_v2():
        if str(L.get("id") or "") == cid:
            n = str(L.get("name") or "").strip()
            return n or "Room"
    return "Location"


def _on_delete_current_location(*, _apply_persisted_location_to_runtime, _refresh_location_selector, _start_location_toast, root) -> None:
    locs = read_all_locations_v2()
    if len(locs) <= 1:
        messagebox.showinfo(
            "Delete location",
            "You cannot delete the only location. Add another room first, then remove this one.",
            parent=root,
        )
        return
    cid = (read_current_location_id() or "").strip()
    if not cid:
        return
    nm = "this location"
    for L in locs:
        if str(L.get("id") or "").strip() == cid:
            nm = str(L.get("name") or "Room").strip() or "Room"
            break
    if not messagebox.askyesno(
        "Delete location",
        f'Delete "{nm}" and remove all saved devices and Advanced (delegation) data '
        f"for that room?\n\nThis cannot be undone.",
        parent=root,
    ):
        return
    try:
        from pigeon.observed_capability import clear_observed_capabilities_for_location

        if not delete_location_v2(cid):
            messagebox.showerror(
                "Delete location",
                "Could not delete that location.",
                parent=root,
            )
            return
        clear_observed_capabilities_for_location(cid)
    except Exception as e:
        messagebox.showerror("Delete location", str(e), parent=root)
        return
    _apply_persisted_location_to_runtime()
    _refresh_location_selector()
    _start_location_toast()
    messagebox.showinfo("Delete location", f'"{nm}" was deleted.')


def _start_location_toast(*, startup: bool = False, _PIGEON_EXT, _current_location_display_name, location_toast_state, skip_cache) -> None:
    if not _PIGEON_EXT:
        return
    st = location_toast_state
    st["text"] = _current_location_display_name()
    st["active"] = True
    st["t0"] = time.monotonic()
    st["startup_top_left"] = bool(startup)
    st["hold_full_s"] = 15.0 if startup else 5.0
    skip_cache[0] = None


def _apply_location_rename(*, _apply_persisted_location_to_runtime, _refresh_location_selector, _start_location_toast, location_name_var) -> None:
    cid = (read_current_location_id() or "").strip()
    if not cid:
        return
    new_nm = (location_name_var.get() or "").strip() or "Room"
    if not rename_location_v2(cid, new_nm):
        return
    _refresh_location_selector()
    _apply_persisted_location_to_runtime()
    _start_location_toast()


def _refresh_location_selector(*, _apply_persisted_location_to_runtime, _refresh_location_selector, delete_location_btn, location_menu_var, location_name_entry, location_name_var, location_om_frame, location_option_holder, rename_name_btn, root) -> None:
    for w in location_om_frame.winfo_children():
        try:
            w.destroy()
        except tk.TclError:
            pass
    locs = read_all_locations_v2()
    labels: list[str] = []
    ids: list[str] = []
    counts: dict[str, int] = {}
    for L in locs:
        base = str(L.get("name") or "Room").strip() or "Room"
        counts[base] = counts.get(base, 0) + 1
        c = counts[base]
        lab = base if c == 1 else f"{base} ({c})"
        labels.append(lab)
        ids.append(str(L.get("id") or ""))
    labels.append("+ Custom location…")
    ids.append("__custom__")
    cur_id = read_current_location_id()

    def _pick(label_val: str) -> None:
        if label_val == "+ Custom location…":
            name = simpledialog.askstring(
                "Custom location",
                "Name for this location:",
                parent=root,
            )
            if name and str(name).strip():
                add_empty_location_v2(str(name).strip())
                _apply_persisted_location_to_runtime()
            _refresh_location_selector()
            return
        idx = labels.index(label_val) if label_val in labels else -1
        if idx < 0 or idx >= len(ids):
            return
        lid = ids[idx]
        if lid == "__custom__":
            return
        if lid == read_current_location_id():
            return
        if lid and set_current_location_id(lid):
            _apply_persisted_location_to_runtime()
            _refresh_location_selector()

    if not locs:
        location_menu_var.set("+ Custom location…")

        def _pick_empty(val: str) -> None:
            if val == "+ Custom location…":
                name = simpledialog.askstring(
                    "Custom location",
                    "Name for this location:",
                    parent=root,
                )
                if name and str(name).strip():
                    add_empty_location_v2(str(name).strip())
                    _apply_persisted_location_to_runtime()
                _refresh_location_selector()

        om = tk.OptionMenu(
            location_om_frame,
            location_menu_var,
            "+ Custom location…",
            command=_pick_empty,
        )
        om.pack(side=tk.LEFT)
        location_option_holder[0] = om
        location_name_var.set("")
        try:
            location_name_entry.configure(state=tk.DISABLED)
            rename_name_btn.configure(state=tk.DISABLED)
            delete_location_btn.configure(state=tk.DISABLED)
        except tk.TclError:
            pass
        return

    cur_label = labels[0]
    if cur_id:
        for i, xid in enumerate(ids):
            if xid == cur_id and i < len(labels) - 1:
                cur_label = labels[i]
                break
    location_menu_var.set(cur_label)
    om = tk.OptionMenu(location_om_frame, location_menu_var, *labels, command=_pick)
    om.pack(side=tk.LEFT)
    location_option_holder[0] = om
    cid_nm = (read_current_location_id() or "").strip()
    raw_nm = ""
    if cid_nm:
        for L in read_all_locations_v2():
            if str(L.get("id") or "").strip() == cid_nm:
                raw_nm = str(L.get("name") or "Room").strip() or "Room"
                break
    location_name_var.set(raw_nm)
    try:
        location_name_entry.configure(state=tk.NORMAL if cid_nm else tk.DISABLED)
        rename_name_btn.configure(state=tk.NORMAL if cid_nm else tk.DISABLED)
        delete_location_btn.configure(
            state=tk.NORMAL if len(locs) > 1 and cid_nm else tk.DISABLED
        )
    except tk.TclError:
        pass
