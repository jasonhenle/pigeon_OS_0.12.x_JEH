"""Boot phase: device state, the Devices section, the Updates flow, and the Content section.

Phase 5 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from pigeon.app_state import read_last_apple_tv
from pigeon.app_state import read_last_receiver
from pigeon.core import device_control as _core_device_control
from pigeon.core import now_playing as _core_now_playing
from pigeon.core import saver_state as _core_saver_state
from pigeon.core import settings_ui as _core_settings_ui
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.core.binding import late as _late
import tkinter as tk


def run(ctx) -> None:
    S_FONT_BTN = ctx.S_FONT_BTN
    S_FONT_MICRO = ctx.S_FONT_MICRO
    S_FONT_SEC = ctx.S_FONT_SEC
    S_FONT_STATUS = ctx.S_FONT_STATUS
    _paint_boolean_led = ctx._paint_boolean_led
    apple_tv_auto_state = ctx.apple_tv_auto_state
    apple_tv_dashboard_track = ctx.apple_tv_dashboard_track
    apple_tv_playback_clock = ctx.apple_tv_playback_clock
    metadata_has_playback_title = ctx.metadata_has_playback_title
    resolve_metadata_tmdb_query = ctx.resolve_metadata_tmdb_query
    root = ctx.root
    settings_inner = ctx.settings_inner
    update_btn_holder = ctx.update_btn_holder

    apple_tv_section = tk.Frame(settings_inner, bg="#111")
    apple_tv_section.pack(anchor=tk.W, pady=(4, 3))
    streaming_slot_holder: list[dict[str, str] | None] = [None]
    avr_slot_holder: list[dict[str, str] | None] = [None]
    receiver_poll_busy = {"active": False}
    # Recent pyatv scan (non-empty results only); avoids full LAN scan when adding more devices.
    DISCOVERY_CACHE_TTL_S = 600.0
    discovery_scan_cache: dict[str, object] = {"rows": None, "mono_s": 0.0}
    pairing_led_holder: list[tk.Canvas | None] = [None, None]
    pair_led_busy = {"active": False}
    _pair_led_pending_retry = [False]
    current_apple_tv = read_last_apple_tv()
    receiver_http_host = {"host": str(read_last_receiver().get("host") or "").strip()}
    apple_tv_status_var = tk.StringVar()
    streaming_row_led_canvas_holder: list[tk.Canvas | None] = [None]
    receiver_panel_led_holder: list[tk.Canvas | None] = [None]
    paired_ui_leds: dict[str, tk.Canvas | None] = {"remote": None, "airplay": None, "receiver": None}
    paired_observed_led_rows: list[tuple[tk.Canvas, str, dict[str, str]]] = []
    paired_observed_led_last_state: dict[int, bool | None] = {}
    settings_footer_debug_holder: list[tk.Button | None] = [None]
    settings_footer_reset_holder: list[tk.Button | None] = [None]
    match_quality_glance_label_holder: list[tk.Label | None] = [None]
    match_quality_glance_sig: list[str] = [""]
    apple_tv_busy = {"active": False}
    tmdb_retry_rule_idx = [0]
    tmdb_adv_manual_btn_holder: list[tk.Button | None] = [None]
    tmdb_adv_report_btn_holder: list[tk.Button | None] = [None]
    tmdb_adv_log_text_holder: list[tk.Misc | None] = [None]

    _register_tmdb_adv_widgets = _bind_deps(
        _core_settings_ui._register_tmdb_adv_widgets,
        tmdb_adv_log_text_holder=tmdb_adv_log_text_holder,
        tmdb_adv_manual_btn_holder=tmdb_adv_manual_btn_holder,
        tmdb_adv_report_btn_holder=tmdb_adv_report_btn_holder,
    )

    _unregister_tmdb_adv_widgets = _bind_deps(
        _core_settings_ui._unregister_tmdb_adv_widgets,
        tmdb_adv_log_text_holder=tmdb_adv_log_text_holder,
        tmdb_adv_manual_btn_holder=tmdb_adv_manual_btn_holder,
        tmdb_adv_report_btn_holder=tmdb_adv_report_btn_holder,
    )

    _append_tmdb_retry_log_ui = _bind_deps(
        _core_settings_ui._append_tmdb_retry_log_ui,
        tmdb_adv_log_text_holder=tmdb_adv_log_text_holder,
    )


    _has_playback_position = _bind_deps(
        _core_now_playing._has_playback_position,
        _playback_progress_fraction_for_bar=_late(lambda: ctx._playback_progress_fraction_for_bar, "_playback_progress_fraction_for_bar"),
    )

    _metadata_is_netflix_app = _core_now_playing._metadata_is_netflix_app

    _atv_metadata_is_content_idle = _bind_deps(
        _core_now_playing._atv_metadata_is_content_idle,
        metadata_has_playback_title=metadata_has_playback_title,
        resolve_metadata_tmdb_query=resolve_metadata_tmdb_query,
    )

    _apple_tv_is_off = _bind_deps(
        _core_device_control._apple_tv_is_off,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_dashboard_track=apple_tv_dashboard_track,
        current_apple_tv=current_apple_tv,
    )

    _show_paused_row_overlay = _bind_deps(
        _core_saver_state._show_paused_row_overlay,
        _apple_tv_is_off=_apple_tv_is_off,
        _atv_metadata_is_content_idle=_atv_metadata_is_content_idle,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
    )

    content_indicator_cv_holder: list[tk.Canvas | None] = [None]
    _LISTBOX_BG = "#1a1a1e"
    _LISTBOX_FG = "#e8e8e8"

    atv_status_row = tk.Frame(apple_tv_section, bg="#111")
    atv_status_row.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
    tk.Label(
        atv_status_row,
        textvariable=apple_tv_status_var,
        fg="#cfcfcf",
        bg="#111",
        font=S_FONT_STATUS,
        wraplength=520,
        justify=tk.LEFT,
    ).pack(anchor=tk.W)

    devices_strip = tk.Frame(apple_tv_section, bg="#111")
    devices_strip.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
    devices_btn_row = tk.Frame(devices_strip, bg="#111")
    devices_btn_row.pack(anchor=tk.W, fill=tk.X, pady=(0, 4))
    find_device_btn = tk.Button(
        devices_btn_row,
        text="Find device",
        command=lambda: ctx._open_find_device_dialog(),
        font=S_FONT_BTN,
        padx=10,
        pady=4,
    )
    find_device_btn.pack(side=tk.LEFT)
    advanced_matrix_btn = tk.Button(
        devices_btn_row,
        text="Advanced",
        command=lambda: ctx._open_advanced_capability_matrix(),
        font=S_FONT_BTN,
        padx=10,
        pady=4,
    )
    advanced_matrix_btn.pack(side=tk.LEFT, padx=(10, 0))
    update_check_state: dict[str, object] = {
        "update_available": False,
        "remote_version": None,
        "github_branch": None,
        "checking": False,
        "last_check_mono": 0.0,
        "error": None,
        "applying": False,
    }
    # Background polls are one cache-busted raw GET (quick mode) — cheap
    # enough to run every couple of minutes on the Pi.
    _UPDATE_CHECK_INTERVAL_S = 2 * 60

    _match_neighbor_button_style = _core_settings_ui._match_neighbor_button_style

    _sync_update_button_style = _bind_deps(
        _core_settings_ui._sync_update_button_style,
        _match_neighbor_button_style=_match_neighbor_button_style,
        find_device_btn=find_device_btn,
        update_btn_holder=update_btn_holder,
        update_check_state=update_check_state,
    )

    _resolve_install_root_for_update = _core_settings_ui._resolve_install_root_for_update

    _run_github_apply_worker = _bind_deps(
        _core_settings_ui._run_github_apply_worker,
        _resolve_install_root_for_update=_resolve_install_root_for_update,
        _sync_update_button_style=_sync_update_button_style,
        root=root,
        update_btn_holder=update_btn_holder,
        update_check_state=update_check_state,
    )

    _linux_on_updates_button = _bind_deps(
        _core_settings_ui._linux_on_updates_button,
        _run_github_apply_worker=_run_github_apply_worker,
        root=root,
        update_check_state=update_check_state,
    )

    _begin_apply_update = _bind_deps(
        _core_settings_ui._begin_apply_update,
        _run_github_apply_worker=_run_github_apply_worker,
        root=root,
    )

    _on_updates_button = _bind_deps(
        _core_settings_ui._on_updates_button,
        _begin_apply_update=_begin_apply_update,
        _finish_update_check=_late(lambda: _finish_update_check, "_finish_update_check"),
        _linux_on_updates_button=_linux_on_updates_button,
        root=root,
        update_btn_holder=update_btn_holder,
        update_check_state=update_check_state,
    )

    _finish_update_check = _bind_deps(
        _core_settings_ui._finish_update_check,
        _sync_update_button_style=_sync_update_button_style,
        update_check_state=update_check_state,
    )

    _check_for_updates = _bind_deps(
        _core_settings_ui._check_for_updates,
        _UPDATE_CHECK_INTERVAL_S=_UPDATE_CHECK_INTERVAL_S,
        _finish_update_check=_finish_update_check,
        root=root,
        update_check_state=update_check_state,
    )

    _schedule_periodic_update_check = _bind_deps(
        _core_settings_ui._schedule_periodic_update_check,
        _UPDATE_CHECK_INTERVAL_S=_UPDATE_CHECK_INTERVAL_S,
        _check_for_updates=_check_for_updates,
        _schedule_periodic_update_check=_late(lambda: _schedule_periodic_update_check, "_schedule_periodic_update_check"),
        root=root,
    )

    update_btn_holder[0] = tk.Button(
        devices_btn_row,
        text="Updates",
        command=_on_updates_button,
        font=S_FONT_BTN,
        padx=10,
        pady=4,
    )
    update_btn_holder[0].pack(side=tk.LEFT, padx=(10, 0))
    _sync_update_button_style()
    root.after(4000, lambda: _check_for_updates(force=True))
    root.after(int(_UPDATE_CHECK_INTERVAL_S * 1000), _schedule_periodic_update_check)
    tk.Label(
        devices_strip,
        text="Choose a device role, pick a device or enter Host/IP, then Confirm to save it to the current location.",
        fg="#666",
        bg="#111",
        font=S_FONT_MICRO,
        wraplength=520,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, pady=(4, 0))
    paired_devices_inner = tk.Frame(apple_tv_section, bg="#111")
    paired_devices_inner.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

    content_section = tk.Frame(apple_tv_section, bg="#111")
    content_section.pack(anchor=tk.W, fill=tk.X, pady=(2, 6))
    content_heading_row = tk.Frame(content_section, bg="#111")
    content_heading_row.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
    tk.Label(
        content_heading_row,
        text="Content",
        fg="#ccc",
        bg="#111",
        font=S_FONT_SEC,
    ).pack(side=tk.LEFT)
    content_indicator_cv = tk.Canvas(
        content_heading_row,
        width=20,
        height=20,
        bg="#111",
        highlightthickness=0,
        bd=0,
    )
    content_indicator_cv.pack(side=tk.LEFT, padx=(10, 6))
    content_indicator_cv_holder[0] = content_indicator_cv
    _paint_boolean_led(content_indicator_cv, False)
    tk.Label(
        content_heading_row,
        text="● green = detected   ● red = not",
        fg="#666",
        bg="#111",
        font=S_FONT_MICRO,
    ).pack(side=tk.LEFT, padx=(6, 0))
    content_buttons_row = tk.Frame(content_section, bg="#111")
    content_buttons_row.pack(anchor=tk.W, pady=(0, 6))
    # Purge is parented here after handlers. TMDb (Manual Fetch, Report Failure, retry log) lives on Advanced.

    ctx.DISCOVERY_CACHE_TTL_S = DISCOVERY_CACHE_TTL_S
    ctx._LISTBOX_BG = _LISTBOX_BG
    ctx._LISTBOX_FG = _LISTBOX_FG
    ctx._append_tmdb_retry_log_ui = _append_tmdb_retry_log_ui
    ctx._apple_tv_is_off = _apple_tv_is_off
    ctx._atv_metadata_is_content_idle = _atv_metadata_is_content_idle
    ctx._has_playback_position = _has_playback_position
    ctx._metadata_is_netflix_app = _metadata_is_netflix_app
    ctx._pair_led_pending_retry = _pair_led_pending_retry
    ctx._register_tmdb_adv_widgets = _register_tmdb_adv_widgets
    ctx._resolve_install_root_for_update = _resolve_install_root_for_update
    ctx._show_paused_row_overlay = _show_paused_row_overlay
    ctx._sync_update_button_style = _sync_update_button_style
    ctx._unregister_tmdb_adv_widgets = _unregister_tmdb_adv_widgets
    ctx.apple_tv_busy = apple_tv_busy
    ctx.apple_tv_status_var = apple_tv_status_var
    ctx.avr_slot_holder = avr_slot_holder
    ctx.content_buttons_row = content_buttons_row
    ctx.content_indicator_cv_holder = content_indicator_cv_holder
    ctx.current_apple_tv = current_apple_tv
    ctx.discovery_scan_cache = discovery_scan_cache
    ctx.find_device_btn = find_device_btn
    ctx.match_quality_glance_label_holder = match_quality_glance_label_holder
    ctx.match_quality_glance_sig = match_quality_glance_sig
    ctx.pair_led_busy = pair_led_busy
    ctx.paired_devices_inner = paired_devices_inner
    ctx.paired_observed_led_last_state = paired_observed_led_last_state
    ctx.paired_observed_led_rows = paired_observed_led_rows
    ctx.paired_ui_leds = paired_ui_leds
    ctx.pairing_led_holder = pairing_led_holder
    ctx.receiver_http_host = receiver_http_host
    ctx.receiver_panel_led_holder = receiver_panel_led_holder
    ctx.receiver_poll_busy = receiver_poll_busy
    ctx.settings_footer_debug_holder = settings_footer_debug_holder
    ctx.settings_footer_reset_holder = settings_footer_reset_holder
    ctx.streaming_row_led_canvas_holder = streaming_row_led_canvas_holder
    ctx.streaming_slot_holder = streaming_slot_holder
    ctx.tmdb_adv_manual_btn_holder = tmdb_adv_manual_btn_holder
    ctx.tmdb_adv_report_btn_holder = tmdb_adv_report_btn_holder
    ctx.tmdb_retry_rule_idx = tmdb_retry_rule_idx
    ctx.update_check_state = update_check_state
