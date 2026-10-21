"""
Destructive reset / purge actions for the settings screen.

Purging cached image media and resetting paired devices and media. Same contract as the
rest of ``settings_ui``: keyword-only dependencies bound with ``bind_deps``.

``pigeon.core.settings_ui`` re-exports every name here, so the boot phases that look the
functions up on ``settings_ui`` are unchanged.
"""

from __future__ import annotations

import tkinter.messagebox as messagebox

from pigeon.app_state import clear_all_persisted_devices_and_targets
from pigeon.app_state import clear_last_apple_tv
from pigeon.app_state import clear_last_receiver
from pigeon.media_folders import pigeon_pulled_media_dir
from pigeon.media_folders import pigeon_reformatted_media_dir
from pigeon.media_folders import purge_directory_contents
from pigeon.runtime_paths import pigeon_state_dir


def on_purge_image_media(*, root) -> None:
    if not messagebox.askokcancel(
        "Purge image media",
        "Delete all files in pigeonPulledMedia and pigeonReformattedMedia?",
        parent=root,
    ):
        return
    ok1, msg1 = purge_directory_contents(pigeon_pulled_media_dir())
    ok2, msg2 = purge_directory_contents(pigeon_reformatted_media_dir())
    if ok1 and ok2:
        messagebox.showinfo("Purge image media", f"{msg1}\n{msg2}")
    else:
        messagebox.showerror("Purge image media", f"{msg1}\n{msg2}")


def on_reset_pigeon_devices_and_media(*, _rebuild_paired_devices_panel, _refresh_location_selector, _schedule_refresh_pairing_leds, _warm_playback_overlay_blits, apple_tv_auto_state, apple_tv_dashboard_track, avr_slot_holder, current_apple_tv, describe_current_apple_tv, discovery_scan_cache, playback_overlay_widget, receiver_http_host, render_once, root, skip_cache, streaming_slot_holder) -> None:
    if not messagebox.askokcancel(
        "Reset",
        "This wipes everything Pigeon has stored for devices and local image media:\n\n"
        "• Saved locations, Players, and Receivers\n"
        "• pyatv credentials\n"
        "• Discovery cache\n"
        "• pigeonPulledMedia and pigeonReformattedMedia\n\n"
        "This cannot be undone. Continue?",
        parent=root,
    ):
        return
    ok1, msg1 = purge_directory_contents(pigeon_pulled_media_dir())
    ok2, msg2 = purge_directory_contents(pigeon_reformatted_media_dir())
    cred_path = pigeon_state_dir() / "pyatv_credentials"
    cred_err = ""
    try:
        if cred_path.is_file():
            cred_path.unlink()
    except OSError as e:
        cred_err = str(e)
    clear_all_persisted_devices_and_targets()
    clear_last_apple_tv()
    clear_last_receiver()
    discovery_scan_cache["rows"] = None
    discovery_scan_cache["mono_s"] = 0.0
    streaming_slot_holder[0] = None
    avr_slot_holder[0] = None
    current_apple_tv.clear()
    current_apple_tv.update(
        {"identifier": "", "address": "", "name": "", "label": ""}
    )
    receiver_http_host["host"] = ""
    apple_tv_auto_state["content_key"] = None
    apple_tv_auto_state["tmdb_key"] = None
    apple_tv_auto_state["query"] = None
    apple_tv_auto_state["last_metadata"] = None
    apple_tv_auto_state["last_tmdb_fetch_input"] = None
    apple_tv_auto_state["last_tmdb_fetch_refined"] = None
    apple_tv_auto_state["last_tmdb_fetch_prefer"] = None
    apple_tv_dashboard_track["last_poll_ok"] = None
    apple_tv_dashboard_track["consecutive_fail"] = 0
    if playback_overlay_widget is not None:
        playback_overlay_widget.clear_cache()
    describe_current_apple_tv()
    _refresh_location_selector()
    _rebuild_paired_devices_panel()
    _schedule_refresh_pairing_leds()
    try:
        _warm_playback_overlay_blits()
    except Exception:
        pass
    skip_cache[0] = None
    try:
        render_once()
    except Exception:
        pass
    tail = f"{msg1}\n{msg2}"
    if cred_err:
        tail += f"\nCredentials file: {cred_err}"
    if ok1 and ok2 and not cred_err:
        messagebox.showinfo("Reset", tail)
    else:
        messagebox.showwarning("Reset", tail)
