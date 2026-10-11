"""Boot phase: settings footer, saved-device seeding, and the device / playback polls.

Phase 11 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from pigeon.app_state import merge_legacy_saved_receivers_into_av_slot
from pigeon.app_state import migrate_device_slots_from_legacy_if_needed
from pigeon.app_state import read_last_receiver
from pigeon.app_state import read_saved_av_receiver
from pigeon.app_state import read_saved_streaming_device
from pigeon.app_state import write_last_receiver
from pigeon.core import tmdb_flow as _core_tmdb_flow
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.version import version_string
import tkinter as tk


def run(ctx) -> None:
    DevPhase = ctx.DevPhase
    DisplayView = ctx.DisplayView
    PLAYBACK_UI_TICK_MS = ctx.PLAYBACK_UI_TICK_MS
    S_FONT_BODY = ctx.S_FONT_BODY
    S_FONT_BTN = ctx.S_FONT_BTN
    _PIGEON_EXT = ctx._PIGEON_EXT
    _apple_tv_auto_poll_tick = ctx._apple_tv_auto_poll_tick
    _attach_hover_tooltip = ctx._attach_hover_tooltip
    _bump_pigeon_user_activity = ctx._bump_pigeon_user_activity
    _last_command_submit_mono = ctx._last_command_submit_mono
    _playback_ui_tick = ctx._playback_ui_tick
    _rebuild_paired_devices_panel = ctx._rebuild_paired_devices_panel
    _refresh_location_selector = ctx._refresh_location_selector
    _schedule_refresh_pairing_leds = ctx._schedule_refresh_pairing_leds
    _seed_current_apple_tv_from_streaming_slot = ctx._seed_current_apple_tv_from_streaming_slot
    avr_slot_holder = ctx.avr_slot_holder
    command_entry = ctx.command_entry
    describe_current_apple_tv = ctx.describe_current_apple_tv
    dev_phase = ctx.dev_phase
    display_view_holder = ctx.display_view_holder
    hide_command_entry = ctx.hide_command_entry
    on_debug_streaming_slot_apple_tv = ctx.on_debug_streaming_slot_apple_tv
    on_reset_pigeon_devices_and_media = ctx.on_reset_pigeon_devices_and_media
    parse_tmdb_command_phrase = ctx.parse_tmdb_command_phrase
    receiver_http_host = ctx.receiver_http_host
    root = ctx.root
    settings_footer_debug_holder = ctx.settings_footer_debug_holder
    settings_footer_reset_holder = ctx.settings_footer_reset_holder
    settings_inner = ctx.settings_inner
    spawn_tmdb_poster_fetch = ctx.spawn_tmdb_poster_fetch
    streaming_slot_holder = ctx.streaming_slot_holder

    settings_footer_row = tk.Frame(settings_inner, bg="#111")
    settings_footer_row.pack(anchor=tk.W, fill=tk.X, pady=(16, 12))
    _frb = tk.Button(
        settings_footer_row,
        text="Reset",
        command=on_reset_pigeon_devices_and_media,
        font=S_FONT_BTN,
        padx=14,
        pady=6,
    )
    _frb.pack(side=tk.LEFT, padx=(0, 12))
    settings_footer_reset_holder[0] = _frb
    _fdb = tk.Button(
        settings_footer_row,
        text="Debug metadata",
        command=on_debug_streaming_slot_apple_tv,
        font=S_FONT_BTN,
        padx=10,
        pady=4,
    )
    _fdb.pack(side=tk.LEFT, padx=(0, 0))
    settings_footer_debug_holder[0] = _fdb
    tk.Label(
        settings_footer_row,
        text=f"Version {version_string()}",
        fg="#6d6d75",
        bg="#111",
        font=S_FONT_BODY,
    ).pack(side=tk.RIGHT, anchor=tk.E)
    _attach_hover_tooltip(
        _frb,
        "Clears all saved devices, pyatv credentials, discovery cache, and purges pigeonTMDB originals/backdrops/title-treatments.",
    )

    migrate_device_slots_from_legacy_if_needed()
    merge_legacy_saved_receivers_into_av_slot()
    streaming_slot_holder[0] = read_saved_streaming_device()
    avr_slot_holder[0] = read_saved_av_receiver()
    _seed_current_apple_tv_from_streaming_slot()
    # Prefer the location AV slot address over last_receiver — the latter can
    # linger on a stale IP after the Denon DHCP/address changes, which leaves
    # zone3 with an empty volume fraction (no red ring).
    _av_boot = avr_slot_holder[0]
    _av_adr = str((_av_boot or {}).get("address") or "").strip() if _av_boot else ""
    _last_rx_host = str(read_last_receiver().get("host") or "").strip()
    if _av_adr:
        if _av_adr != _last_rx_host:
            write_last_receiver(
                host=_av_adr,
                name=str(_av_boot.get("name") or "").strip() or None,
                label=str(_av_boot.get("label") or "").strip() or None,
                device_id=str(_av_boot.get("identifier") or "").strip() or None,
            )
        receiver_http_host["host"] = _av_adr
    else:
        receiver_http_host["host"] = _last_rx_host
    describe_current_apple_tv()
    _refresh_location_selector()
    _rebuild_paired_devices_panel()
    root.after(300, _schedule_refresh_pairing_leds)
    root.after(2500, _apple_tv_auto_poll_tick)
    root.after(PLAYBACK_UI_TICK_MS, _playback_ui_tick)

    submit_command_entry = _bind_deps(
        _core_tmdb_flow.submit_command_entry,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        _PIGEON_EXT=_PIGEON_EXT,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _last_command_submit_mono=_last_command_submit_mono,
        command_entry=command_entry,
        dev_phase=dev_phase,
        display_view_holder=display_view_holder,
        hide_command_entry=hide_command_entry,
        parse_tmdb_command_phrase=parse_tmdb_command_phrase,
        spawn_tmdb_poster_fetch=spawn_tmdb_poster_fetch,
    )

    ctx.settings_footer_row = settings_footer_row
    ctx.submit_command_entry = submit_command_entry
