"""Boot phase: device list parsing, pairing LEDs, locations, and mid-bootstrap View 1 warm-up.

Phase 10 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from pigeon.core import device_control as _core_device_control
from pigeon.core import input_keys as _core_input_keys
from pigeon.core import now_playing as _core_now_playing
from pigeon.core import pairing as _core_pairing
from pigeon.core import saver_state as _core_saver_state
from pigeon.core import settings_ui as _core_settings_ui
from pigeon.core import stage_render as _core_stage_render
from pigeon.core import tmdb_flow as _core_tmdb_flow
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.core.binding import late as _late
import tkinter as tk


def run(ctx) -> None:
    APPLE_TV_FAIL_POLL_MAX_MS = ctx.APPLE_TV_FAIL_POLL_MAX_MS
    APPLE_TV_IDLE_POLL_MS = ctx.APPLE_TV_IDLE_POLL_MS
    APPLE_TV_POLL_MS = ctx.APPLE_TV_POLL_MS
    DISCOVERY_CACHE_TTL_S = ctx.DISCOVERY_CACHE_TTL_S
    DisplayView = ctx.DisplayView
    RECEIVER_POLL_MS = ctx.RECEIVER_POLL_MS
    S_FONT_BODY = ctx.S_FONT_BODY
    S_FONT_BTN = ctx.S_FONT_BTN
    S_FONT_CAP_BOLD = ctx.S_FONT_CAP_BOLD
    S_FONT_MICRO = ctx.S_FONT_MICRO
    S_FONT_SEC = ctx.S_FONT_SEC
    S_FONT_SMALL = ctx.S_FONT_SMALL
    S_FONT_STATUS = ctx.S_FONT_STATUS
    TMDB_ERROR_FLAG_RETRY_RULES = ctx.TMDB_ERROR_FLAG_RETRY_RULES
    TMDB_QUALITY_UNLOG_WINDOW_S = ctx.TMDB_QUALITY_UNLOG_WINDOW_S
    _LISTBOX_BG = ctx._LISTBOX_BG
    _LISTBOX_FG = ctx._LISTBOX_FG
    _PIGEON_EXT = ctx._PIGEON_EXT
    _PROJECT_DIR = ctx._PROJECT_DIR
    _S = ctx._S
    _adjust_tmdb_quality_failure_delta = ctx._adjust_tmdb_quality_failure_delta
    _advanced_feature_pipeline_ok = ctx._advanced_feature_pipeline_ok
    _alternate_tmdb_query_from_metadata = ctx._alternate_tmdb_query_from_metadata
    _append_tmdb_quality_event_report_log = ctx._append_tmdb_quality_event_report_log
    _append_tmdb_retry_log_ui = ctx._append_tmdb_retry_log_ui
    _apple_tv_scan_timeout_s = ctx._apple_tv_scan_timeout_s
    _apply_netflix_backdrop_when_running = ctx._apply_netflix_backdrop_when_running
    _atv_ix_extrap_playing = ctx._atv_ix_extrap_playing
    _atv_ix_pos = ctx._atv_ix_pos
    _atv_ix_pos_mono = ctx._atv_ix_pos_mono
    _atv_ix_prev_idle = ctx._atv_ix_prev_idle
    _atv_ix_sig_ck = ctx._atv_ix_sig_ck
    _atv_ix_sig_ds = ctx._atv_ix_sig_ds
    _atv_metadata_is_content_idle = ctx._atv_metadata_is_content_idle
    _bump_clock_saver_significant_device = ctx._bump_clock_saver_significant_device
    _bump_clock_saver_significant_device_from_metadata = ctx._bump_clock_saver_significant_device_from_metadata
    _bump_pigeon_user_activity = ctx._bump_pigeon_user_activity
    _clear_displayed_tmdb_art_for_content_change = ctx._clear_displayed_tmdb_art_for_content_change
    _clear_now_playing_view_caches = ctx._clear_now_playing_view_caches
    _clear_playback_artwork_caches = ctx._clear_playback_artwork_caches
    _clear_reported_position_stall_stamp = ctx._clear_reported_position_stall_stamp
    _clear_tmdb_quality_flag = ctx._clear_tmdb_quality_flag
    _content_indicator_ok = ctx._content_indicator_ok
    _disp_fit = ctx._disp_fit
    _effective_display_view = ctx._effective_display_view
    _format_hmmss = ctx._format_hmmss
    _idle_audio_meter_active = ctx._idle_audio_meter_active
    _kiosk_on = ctx._kiosk_on
    _last_tmdb_hotkey_mono = ctx._last_tmdb_hotkey_mono
    _last_tmdb_quality_report_mono = ctx._last_tmdb_quality_report_mono
    _mark_tmdb_missing_art = ctx._mark_tmdb_missing_art
    _note_metadata_activity = ctx._note_metadata_activity
    _np_widgets_content_active = ctx._np_widgets_content_active
    _paint_boolean_led = ctx._paint_boolean_led
    _paint_pair_led = ctx._paint_pair_led
    _pair_led_pending_retry = ctx._pair_led_pending_retry
    _prepend_hotkey_bindtag = ctx._prepend_hotkey_bindtag
    _program_audio_session = ctx._program_audio_session
    _pyatv_install_hint = ctx._pyatv_install_hint
    _raw_title_query_from_metadata = ctx._raw_title_query_from_metadata
    _refresh_content_indicator = ctx._refresh_content_indicator
    _refresh_match_quality_glance_label = ctx._refresh_match_quality_glance_label
    _register_tmdb_adv_widgets = ctx._register_tmdb_adv_widgets
    _reset_clock_saver_device_signal_baseline = ctx._reset_clock_saver_device_signal_baseline
    _resolve_install_root_for_update = ctx._resolve_install_root_for_update
    _resolve_receiver_lines_for_now_playing = ctx._resolve_receiver_lines_for_now_playing
    _schedule_tmdb_quality_auto_expire = ctx._schedule_tmdb_quality_auto_expire
    _start_location_toast = ctx._start_location_toast
    _store_music_artwork_from_metadata = ctx._store_music_artwork_from_metadata
    _sync_now_playing_screen_state = ctx._sync_now_playing_screen_state
    _sync_update_button_style = ctx._sync_update_button_style
    _tmdb_retry_log_append = ctx._tmdb_retry_log_append
    _tmdb_retry_log_read_tail = ctx._tmdb_retry_log_read_tail
    _trigger_tmdb_quality_toggle_overlay = ctx._trigger_tmdb_quality_toggle_overlay
    _unregister_tmdb_adv_widgets = ctx._unregister_tmdb_adv_widgets
    _view_one_uses_now_playing_screen = ctx._view_one_uses_now_playing_screen
    _warm_playback_overlay_blits = ctx._warm_playback_overlay_blits
    _warm_status_bar_blits = ctx._warm_status_bar_blits
    _warm_tmdb_logo_patch = ctx._warm_tmdb_logo_patch
    _warm_view_one_splash_chrome_only = ctx._warm_view_one_splash_chrome_only
    _widget_accepts_typing = ctx._widget_accepts_typing
    active_tmdb_display_title = ctx.active_tmdb_display_title
    active_tmdb_title_key = ctx.active_tmdb_title_key
    advanced_matrix_close_skip = ctx.advanced_matrix_close_skip
    advanced_matrix_restore_phase = ctx.advanced_matrix_restore_phase
    apple_tv_auto_state = ctx.apple_tv_auto_state
    apple_tv_busy = ctx.apple_tv_busy
    apple_tv_dashboard_track = ctx.apple_tv_dashboard_track
    apple_tv_playback_clock = ctx.apple_tv_playback_clock
    apple_tv_status_var = ctx.apple_tv_status_var
    avr_slot_holder = ctx.avr_slot_holder
    backdrop_app_logo_letterbox_fit = ctx.backdrop_app_logo_letterbox_fit
    backdrop_master_bgr = ctx.backdrop_master_bgr
    content_buttons_row = ctx.content_buttons_row
    current_apple_tv = ctx.current_apple_tv
    delete_location_btn = ctx.delete_location_btn
    denon_vol_cache = ctx.denon_vol_cache
    dev_phase = ctx.dev_phase
    discovery_scan_cache = ctx.discovery_scan_cache
    find_device_btn = ctx.find_device_btn
    landing_scene_design_bgr = ctx.landing_scene_design_bgr
    last_atv_interaction_mono = ctx.last_atv_interaction_mono
    last_frame = ctx.last_frame
    last_timecode_motion_mono = ctx.last_timecode_motion_mono
    location_menu_var = ctx.location_menu_var
    location_name_entry = ctx.location_name_entry
    location_name_var = ctx.location_name_var
    location_om_frame = ctx.location_om_frame
    location_option_holder = ctx.location_option_holder
    main_settings_widget_holder = ctx.main_settings_widget_holder
    match_quality_glance_label_holder = ctx.match_quality_glance_label_holder
    on_purge_image_media = ctx.on_purge_image_media
    on_reset_tmdb_match_quality_stats = ctx.on_reset_tmdb_match_quality_stats
    pair_led_busy = ctx.pair_led_busy
    paired_devices_inner = ctx.paired_devices_inner
    paired_observed_led_last_state = ctx.paired_observed_led_last_state
    paired_observed_led_rows = ctx.paired_observed_led_rows
    paired_ui_leds = ctx.paired_ui_leds
    playback_overlay_widget = ctx.playback_overlay_widget
    playing = ctx.playing
    purge_image_media_btn_holder = ctx.purge_image_media_btn_holder
    receiver_http_host = ctx.receiver_http_host
    receiver_overlay_state = ctx.receiver_overlay_state
    receiver_panel_led_holder = ctx.receiver_panel_led_holder
    receiver_standby_holder = ctx.receiver_standby_holder
    rename_name_btn = ctx.rename_name_btn
    resolve_metadata_tmdb_query = ctx.resolve_metadata_tmdb_query
    root = ctx.root
    scaled_display = ctx.scaled_display
    scaled_version = ctx.scaled_version
    scene_enabled = ctx.scene_enabled
    settings_footer_debug_holder = ctx.settings_footer_debug_holder
    settings_footer_reset_holder = ctx.settings_footer_reset_holder
    skip_cache = ctx.skip_cache
    spawn_tmdb_poster_fetch = ctx.spawn_tmdb_poster_fetch
    status_bar_widget = ctx.status_bar_widget
    streaming_badge_state = ctx.streaming_badge_state
    streaming_row_led_canvas_holder = ctx.streaming_row_led_canvas_holder
    streaming_slot_holder = ctx.streaming_slot_holder
    sync_developer_chrome = ctx.sync_developer_chrome
    tmdb_adv_manual_btn_holder = ctx.tmdb_adv_manual_btn_holder
    tmdb_adv_report_btn_holder = ctx.tmdb_adv_report_btn_holder
    tmdb_error_flag_retry_active = ctx.tmdb_error_flag_retry_active
    tmdb_error_flag_retry_rule_idx = ctx.tmdb_error_flag_retry_rule_idx
    tmdb_logo_app_fallback_active = ctx.tmdb_logo_app_fallback_active
    tmdb_logo_patch_bgra = ctx.tmdb_logo_patch_bgra
    tmdb_logo_widget = ctx.tmdb_logo_widget
    tmdb_logo_widget_view_six = ctx.tmdb_logo_widget_view_six
    tmdb_quality_error_flag = ctx.tmdb_quality_error_flag
    tmdb_quality_flag_set_mono = ctx.tmdb_quality_flag_set_mono
    tmdb_retry_rule_idx = ctx.tmdb_retry_rule_idx
    update_check_state = ctx.update_check_state
    use_backdrop_scene = ctx.use_backdrop_scene

    _paint_cred_led_canvas = _core_settings_ui._paint_cred_led_canvas

    _remove_streaming_device_at = _bind_deps(
        _core_pairing._remove_streaming_device_at,
        _clear_reported_position_stall_stamp=_clear_reported_position_stall_stamp,
        _rebuild_paired_devices_panel=_late(lambda: _rebuild_paired_devices_panel, "_rebuild_paired_devices_panel"),
        _schedule_refresh_pairing_leds=_late(lambda: _schedule_refresh_pairing_leds, "_schedule_refresh_pairing_leds"),
        _sync_status_bar_visibility_for_playback=_late(lambda: _sync_status_bar_visibility_for_playback, "_sync_status_bar_visibility_for_playback"),
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_busy=apple_tv_busy,
        apple_tv_dashboard_track=apple_tv_dashboard_track,
        apple_tv_playback_clock=apple_tv_playback_clock,
        current_apple_tv=current_apple_tv,
        describe_current_apple_tv=_late(lambda: describe_current_apple_tv, "describe_current_apple_tv"),
        playback_overlay_widget=playback_overlay_widget,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        root=root,
        skip_cache=skip_cache,
        streaming_slot_holder=streaming_slot_holder,
    )

    _remove_receiver_device_at = _bind_deps(
        _core_pairing._remove_receiver_device_at,
        _rebuild_paired_devices_panel=_late(lambda: _rebuild_paired_devices_panel, "_rebuild_paired_devices_panel"),
        _schedule_refresh_pairing_leds=_late(lambda: _schedule_refresh_pairing_leds, "_schedule_refresh_pairing_leds"),
        apple_tv_busy=apple_tv_busy,
        avr_slot_holder=avr_slot_holder,
        describe_current_apple_tv=_late(lambda: describe_current_apple_tv, "describe_current_apple_tv"),
        playback_overlay_widget=playback_overlay_widget,
        receiver_http_host=receiver_http_host,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        root=root,
        skip_cache=skip_cache,
        denon_vol_cache=denon_vol_cache,
        receiver_overlay_state=receiver_overlay_state,
        receiver_standby_holder=receiver_standby_holder,
        receiver_debug_holder=ctx.receiver_debug_holder,
    )

    _paired_box_close_button = _bind_deps(
        _core_settings_ui._paired_box_close_button,
        _S=_S,
        _kiosk_on=_kiosk_on,
    )

    _settings_parse_device_rows = _core_settings_ui._settings_parse_device_rows

    _settings_parse_receiver_rows = _core_settings_ui._settings_parse_receiver_rows

    _remove_aux_slot_device_at = _bind_deps(
        _core_pairing._remove_aux_slot_device_at,
        _apply_persisted_location_to_runtime=_late(lambda: _apply_persisted_location_to_runtime, "_apply_persisted_location_to_runtime"),
        _rebuild_paired_devices_panel=_late(lambda: _rebuild_paired_devices_panel, "_rebuild_paired_devices_panel"),
        _schedule_refresh_pairing_leds=_late(lambda: _schedule_refresh_pairing_leds, "_schedule_refresh_pairing_leds"),
        apple_tv_busy=apple_tv_busy,
        describe_current_apple_tv=_late(lambda: describe_current_apple_tv, "describe_current_apple_tv"),
        render_once=_late(lambda: ctx.render_once, "render_once"),
        root=root,
        skip_cache=skip_cache,
    )

    _rebuild_paired_devices_panel = _bind_deps(
        _core_settings_ui._rebuild_paired_devices_panel,
        S_FONT_CAP_BOLD=S_FONT_CAP_BOLD,
        S_FONT_SEC=S_FONT_SEC,
        S_FONT_SMALL=S_FONT_SMALL,
        _paint_boolean_led=_paint_boolean_led,
        _paint_cred_led_canvas=_paint_cred_led_canvas,
        _paired_box_close_button=_paired_box_close_button,
        _remove_aux_slot_device_at=_remove_aux_slot_device_at,
        _remove_receiver_device_at=_remove_receiver_device_at,
        _remove_streaming_device_at=_remove_streaming_device_at,
        _settings_parse_device_rows=_settings_parse_device_rows,
        _settings_parse_receiver_rows=_settings_parse_receiver_rows,
        paired_devices_inner=paired_devices_inner,
        paired_observed_led_last_state=paired_observed_led_last_state,
        paired_observed_led_rows=paired_observed_led_rows,
        paired_ui_leds=paired_ui_leds,
        receiver_panel_led_holder=receiver_panel_led_holder,
    )

    _seed_current_apple_tv_from_streaming_slot = _bind_deps(
        _core_device_control._seed_current_apple_tv_from_streaming_slot,
        current_apple_tv=current_apple_tv,
        streaming_slot_holder=streaming_slot_holder,
    )

    describe_current_apple_tv = _bind_deps(
        _core_device_control.describe_current_apple_tv,
        _refresh_content_indicator=_refresh_content_indicator,
        apple_tv_status_var=apple_tv_status_var,
        current_apple_tv=current_apple_tv,
        receiver_http_host=receiver_http_host,
    )

    set_apple_tv_controls_enabled = _bind_deps(
        _core_device_control.set_apple_tv_controls_enabled,
        find_device_btn=find_device_btn,
        purge_image_media_btn_holder=purge_image_media_btn_holder,
        root=root,
        settings_footer_debug_holder=settings_footer_debug_holder,
        settings_footer_reset_holder=settings_footer_reset_holder,
        tmdb_adv_manual_btn_holder=tmdb_adv_manual_btn_holder,
        tmdb_adv_report_btn_holder=tmdb_adv_report_btn_holder,
    )

    begin_apple_tv_operation = _bind_deps(
        _core_device_control.begin_apple_tv_operation,
        apple_tv_busy=apple_tv_busy,
        describe_current_apple_tv=describe_current_apple_tv,
        set_apple_tv_controls_enabled=set_apple_tv_controls_enabled,
    )

    end_apple_tv_operation = _bind_deps(
        _core_device_control.end_apple_tv_operation,
        apple_tv_busy=apple_tv_busy,
        describe_current_apple_tv=describe_current_apple_tv,
        set_apple_tv_controls_enabled=set_apple_tv_controls_enabled,
    )

    set_current_apple_tv = _bind_deps(
        _core_device_control.set_current_apple_tv,
        _atv_ix_extrap_playing=_atv_ix_extrap_playing,
        _atv_ix_pos=_atv_ix_pos,
        _atv_ix_pos_mono=_atv_ix_pos_mono,
        _atv_ix_prev_idle=_atv_ix_prev_idle,
        _atv_ix_sig_ck=_atv_ix_sig_ck,
        _atv_ix_sig_ds=_atv_ix_sig_ds,
        _clear_reported_position_stall_stamp=_clear_reported_position_stall_stamp,
        _rebuild_paired_devices_panel=_rebuild_paired_devices_panel,
        _reset_clock_saver_device_signal_baseline=_reset_clock_saver_device_signal_baseline,
        _schedule_refresh_pairing_leds=_late(lambda: _schedule_refresh_pairing_leds, "_schedule_refresh_pairing_leds"),
        _sync_status_bar_visibility_for_playback=_late(lambda: _sync_status_bar_visibility_for_playback, "_sync_status_bar_visibility_for_playback"),
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_dashboard_track=apple_tv_dashboard_track,
        apple_tv_playback_clock=apple_tv_playback_clock,
        current_apple_tv=current_apple_tv,
        describe_current_apple_tv=describe_current_apple_tv,
        last_atv_interaction_mono=last_atv_interaction_mono,
    )

    _apply_persisted_location_to_runtime = _bind_deps(
        _core_device_control._apply_persisted_location_to_runtime,
        _atv_ix_extrap_playing=_atv_ix_extrap_playing,
        _atv_ix_pos=_atv_ix_pos,
        _atv_ix_pos_mono=_atv_ix_pos_mono,
        _atv_ix_prev_idle=_atv_ix_prev_idle,
        _atv_ix_sig_ck=_atv_ix_sig_ck,
        _atv_ix_sig_ds=_atv_ix_sig_ds,
        _clear_reported_position_stall_stamp=_clear_reported_position_stall_stamp,
        _rebuild_paired_devices_panel=_rebuild_paired_devices_panel,
        _reset_clock_saver_device_signal_baseline=_reset_clock_saver_device_signal_baseline,
        _schedule_refresh_pairing_leds=_late(lambda: _schedule_refresh_pairing_leds, "_schedule_refresh_pairing_leds"),
        _start_location_toast=_start_location_toast,
        _sync_status_bar_visibility_for_playback=_late(lambda: _sync_status_bar_visibility_for_playback, "_sync_status_bar_visibility_for_playback"),
        _warm_playback_overlay_blits=_warm_playback_overlay_blits,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_dashboard_track=apple_tv_dashboard_track,
        apple_tv_playback_clock=apple_tv_playback_clock,
        avr_slot_holder=avr_slot_holder,
        current_apple_tv=current_apple_tv,
        describe_current_apple_tv=describe_current_apple_tv,
        last_atv_interaction_mono=last_atv_interaction_mono,
        playback_overlay_widget=playback_overlay_widget,
        receiver_http_host=receiver_http_host,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        skip_cache=skip_cache,
        streaming_slot_holder=streaming_slot_holder,
        denon_vol_cache=denon_vol_cache,
        receiver_overlay_state=receiver_overlay_state,
        receiver_standby_holder=receiver_standby_holder,
        receiver_debug_holder=ctx.receiver_debug_holder,
    )
    ctx._apply_persisted_location_to_runtime = _apply_persisted_location_to_runtime

    _refresh_location_selector = _bind_deps(
        _core_settings_ui._refresh_location_selector,
        _apply_persisted_location_to_runtime=_apply_persisted_location_to_runtime,
        _refresh_location_selector=_late(lambda: _refresh_location_selector, "_refresh_location_selector"),
        delete_location_btn=delete_location_btn,
        location_menu_var=location_menu_var,
        location_name_entry=location_name_entry,
        location_name_var=location_name_var,
        location_om_frame=location_om_frame,
        location_option_holder=location_option_holder,
        rename_name_btn=rename_name_btn,
        root=root,
    )
    ctx._refresh_location_selector = _refresh_location_selector

    _on_delete_current_location = _bind_deps(
        _core_settings_ui._on_delete_current_location,
        _apply_persisted_location_to_runtime=_apply_persisted_location_to_runtime,
        _refresh_location_selector=_refresh_location_selector,
        _start_location_toast=_start_location_toast,
        root=root,
    )

    delete_location_btn.configure(command=_on_delete_current_location)

    _refresh_observed_pairing_led_rows = _bind_deps(
        _core_settings_ui._refresh_observed_pairing_led_rows,
        _paint_cred_led_canvas=_paint_cred_led_canvas,
        paired_observed_led_last_state=paired_observed_led_last_state,
        paired_observed_led_rows=paired_observed_led_rows,
    )

    _schedule_refresh_pairing_leds = _bind_deps(
        _core_pairing._schedule_refresh_pairing_leds,
        _PIGEON_EXT=_PIGEON_EXT,
        _content_indicator_ok=_content_indicator_ok,
        _paint_boolean_led=_paint_boolean_led,
        _paint_cred_led_canvas=_paint_cred_led_canvas,
        _paint_pair_led=_paint_pair_led,
        _pair_led_pending_retry=_pair_led_pending_retry,
        _refresh_observed_pairing_led_rows=_refresh_observed_pairing_led_rows,
        _schedule_refresh_pairing_leds=_late(lambda: _schedule_refresh_pairing_leds, "_schedule_refresh_pairing_leds"),
        apple_tv_busy=apple_tv_busy,
        apple_tv_dashboard_track=apple_tv_dashboard_track,
        main_settings_widget=main_settings_widget_holder[0],
        pair_led_busy=pair_led_busy,
        paired_ui_leds=paired_ui_leds,
        root=root,
        streaming_row_led_canvas_holder=streaming_row_led_canvas_holder,
        streaming_slot_holder=streaming_slot_holder,
    )

    _verify_added_devices_after_save = _bind_deps(
        _core_pairing._verify_added_devices_after_save,
        root=root,
    )

    describe_current_apple_tv()
    _refresh_location_selector()
    _rebuild_paired_devices_panel()

    _ask_pairing_pin_modal = _bind_deps(
        _core_settings_ui._ask_pairing_pin_modal,
        S_FONT_BODY=S_FONT_BODY,
        S_FONT_BTN=S_FONT_BTN,
        root=root,
    )

    _start_airplay_pairing_sequence = _bind_deps(
        _core_pairing._start_airplay_pairing_sequence,
        _ask_pairing_pin_modal=_ask_pairing_pin_modal,
        _pyatv_install_hint=_pyatv_install_hint,
        _schedule_refresh_pairing_leds=_schedule_refresh_pairing_leds,
        begin_apple_tv_operation=begin_apple_tv_operation,
        describe_current_apple_tv=describe_current_apple_tv,
        end_apple_tv_operation=end_apple_tv_operation,
        root=root,
    )

    _finish_remote_then_start_airplay = _bind_deps(
        _core_pairing._finish_remote_then_start_airplay,
        _pyatv_install_hint=_pyatv_install_hint,
        _schedule_refresh_pairing_leds=_schedule_refresh_pairing_leds,
        _start_airplay_pairing_sequence=_start_airplay_pairing_sequence,
        end_apple_tv_operation=end_apple_tv_operation,
        root=root,
    )

    _run_sequential_player_pairing_wizard = _bind_deps(
        _core_pairing._run_sequential_player_pairing_wizard,
        _ask_pairing_pin_modal=_ask_pairing_pin_modal,
        _finish_remote_then_start_airplay=_finish_remote_then_start_airplay,
        _pyatv_install_hint=_pyatv_install_hint,
        _schedule_refresh_pairing_leds=_schedule_refresh_pairing_leds,
        begin_apple_tv_operation=begin_apple_tv_operation,
        describe_current_apple_tv=describe_current_apple_tv,
        end_apple_tv_operation=end_apple_tv_operation,
        root=root,
    )

    _save_box_pair_device_row = _bind_deps(
        _core_settings_ui._save_box_pair_device_row,
        _rebuild_paired_devices_panel=_rebuild_paired_devices_panel,
        avr_slot_holder=avr_slot_holder,
        describe_current_apple_tv=describe_current_apple_tv,
        receiver_http_host=receiver_http_host,
        streaming_slot_holder=streaming_slot_holder,
    )

    _handle_main_settings_action = _bind_deps(
        _core_settings_ui._handle_main_settings_action,
        _apply_persisted_location_to_runtime=_apply_persisted_location_to_runtime,
        _pyatv_install_hint=_pyatv_install_hint,
        _rebuild_paired_devices_panel=_rebuild_paired_devices_panel,
        _refresh_location_selector=_refresh_location_selector,
        _resolve_install_root_for_update=_resolve_install_root_for_update,
        _save_box_pair_device_row=_save_box_pair_device_row,
        _schedule_refresh_pairing_leds=_schedule_refresh_pairing_leds,
        _sync_update_button_style=_sync_update_button_style,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_dashboard_track=apple_tv_dashboard_track,
        avr_slot_holder=avr_slot_holder,
        begin_apple_tv_operation=begin_apple_tv_operation,
        current_apple_tv=current_apple_tv,
        describe_current_apple_tv=describe_current_apple_tv,
        discovery_scan_cache=discovery_scan_cache,
        end_apple_tv_operation=end_apple_tv_operation,
        main_settings_widget=main_settings_widget_holder[0],
        pair_led_busy=pair_led_busy,
        receiver_http_host=receiver_http_host,
        root=root,
        skip_cache=skip_cache,
        streaming_slot_holder=streaming_slot_holder,
        update_check_state=update_check_state,
    )

    _force_advanced_feature_try = _bind_deps(
        _core_settings_ui._force_advanced_feature_try,
        _apple_tv_auto_poll_tick=_late(lambda: _apple_tv_auto_poll_tick, "_apple_tv_auto_poll_tick"),
        _receiver_poll_tick=_late(lambda: ctx._receiver_poll_tick, "_receiver_poll_tick"),
        on_apple_tv_selected_then_tmdb=_late(lambda: on_apple_tv_selected_then_tmdb, "on_apple_tv_selected_then_tmdb"),
    )

    _on_advanced_matrix_closed = _bind_deps(
        _core_stage_render._on_advanced_matrix_closed,
        advanced_matrix_restore_phase=advanced_matrix_restore_phase,
        dev_phase=dev_phase,
        skip_cache=skip_cache,
        sync_developer_chrome=sync_developer_chrome,
    )

    _open_advanced_capability_matrix = _bind_deps(
        _core_settings_ui._open_advanced_capability_matrix,
        _PIGEON_EXT=_PIGEON_EXT,
        _advanced_feature_pipeline_ok=_advanced_feature_pipeline_ok,
        _force_advanced_feature_try=_force_advanced_feature_try,
        _on_advanced_matrix_closed=_on_advanced_matrix_closed,
        _perform_tmdb_artwork_retry=_late(lambda: _perform_tmdb_artwork_retry, "_perform_tmdb_artwork_retry"),
        _prepend_hotkey_bindtag=_prepend_hotkey_bindtag,
        _register_tmdb_adv_widgets=_register_tmdb_adv_widgets,
        _tmdb_retry_log_read_tail=_tmdb_retry_log_read_tail,
        _unregister_tmdb_adv_widgets=_unregister_tmdb_adv_widgets,
        advanced_matrix_close_skip=advanced_matrix_close_skip,
        on_apple_tv_selected_then_tmdb=_late(lambda: on_apple_tv_selected_then_tmdb, "on_apple_tv_selected_then_tmdb"),
        root=root,
    )
    ctx._open_advanced_capability_matrix = _open_advanced_capability_matrix

    _open_find_device_dialog = _bind_deps(
        _core_pairing._open_find_device_dialog,
        DISCOVERY_CACHE_TTL_S=DISCOVERY_CACHE_TTL_S,
        S_FONT_BODY=S_FONT_BODY,
        S_FONT_BTN=S_FONT_BTN,
        S_FONT_MICRO=S_FONT_MICRO,
        S_FONT_SMALL=S_FONT_SMALL,
        S_FONT_STATUS=S_FONT_STATUS,
        _LISTBOX_BG=_LISTBOX_BG,
        _LISTBOX_FG=_LISTBOX_FG,
        _PIGEON_EXT=_PIGEON_EXT,
        _apply_persisted_location_to_runtime=_apply_persisted_location_to_runtime,
        _pyatv_install_hint=_pyatv_install_hint,
        _refresh_location_selector=_refresh_location_selector,
        _run_sequential_player_pairing_wizard=_run_sequential_player_pairing_wizard,
        _verify_added_devices_after_save=_verify_added_devices_after_save,
        begin_apple_tv_operation=begin_apple_tv_operation,
        discovery_scan_cache=discovery_scan_cache,
        end_apple_tv_operation=end_apple_tv_operation,
        root=root,
    )
    ctx._open_find_device_dialog = _open_find_device_dialog

    on_reset_pigeon_devices_and_media = _bind_deps(
        _core_settings_ui.on_reset_pigeon_devices_and_media,
        _rebuild_paired_devices_panel=_rebuild_paired_devices_panel,
        _refresh_location_selector=_refresh_location_selector,
        _schedule_refresh_pairing_leds=_schedule_refresh_pairing_leds,
        _warm_playback_overlay_blits=_warm_playback_overlay_blits,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_dashboard_track=apple_tv_dashboard_track,
        avr_slot_holder=avr_slot_holder,
        current_apple_tv=current_apple_tv,
        describe_current_apple_tv=describe_current_apple_tv,
        discovery_scan_cache=discovery_scan_cache,
        playback_overlay_widget=playback_overlay_widget,
        receiver_http_host=receiver_http_host,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        root=root,
        skip_cache=skip_cache,
        streaming_slot_holder=streaming_slot_holder,
    )

    on_apple_tv_selected_then_tmdb = _bind_deps(
        _core_device_control.on_apple_tv_selected_then_tmdb,
        _PIGEON_EXT=_PIGEON_EXT,
        _open_find_device_dialog=_open_find_device_dialog,
        _pyatv_install_hint=_pyatv_install_hint,
        apple_tv_busy=apple_tv_busy,
        begin_apple_tv_operation=begin_apple_tv_operation,
        describe_current_apple_tv=describe_current_apple_tv,
        end_apple_tv_operation=end_apple_tv_operation,
        last_atv_interaction_mono=last_atv_interaction_mono,
        root=root,
        set_current_apple_tv=set_current_apple_tv,
        spawn_tmdb_poster_fetch=spawn_tmdb_poster_fetch,
        streaming_slot_holder=streaming_slot_holder,
    )

    _content_key_from_metadata = _bind_deps(
        _core_now_playing._content_key_from_metadata,
        _tmdb_pref_from_metadata=_late(lambda: _tmdb_pref_from_metadata, "_tmdb_pref_from_metadata"),
        resolve_metadata_tmdb_query=resolve_metadata_tmdb_query,
    )
    ctx._content_key_from_metadata = _content_key_from_metadata

    _player_duration_for_tmdb = _bind_deps(
        _core_now_playing._player_duration_for_tmdb,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
    )

    _tmdb_duration_bucket = _bind_deps(
        _core_tmdb_flow._tmdb_duration_bucket,
        _player_duration_for_tmdb=_player_duration_for_tmdb,
    )

    _tmdb_spawn_identity = _bind_deps(
        _core_tmdb_flow._tmdb_spawn_identity,
        _tmdb_duration_bucket=_tmdb_duration_bucket,
    )
    ctx._tmdb_spawn_identity = _tmdb_spawn_identity

    _tmdb_spawn_identity_changed = _bind_deps(
        _core_tmdb_flow._tmdb_spawn_identity_changed,
        _content_key_from_metadata=_content_key_from_metadata,
        _tmdb_spawn_identity=_tmdb_spawn_identity,
        apple_tv_auto_state=apple_tv_auto_state,
    )
    ctx._tmdb_spawn_identity_changed = _tmdb_spawn_identity_changed

    _tmdb_pref_from_metadata = _core_tmdb_flow._tmdb_pref_from_metadata

    _apply_playback_clock_from_poll = _bind_deps(
        _core_now_playing._apply_playback_clock_from_poll,
        _content_key_from_metadata=_content_key_from_metadata,
        apple_tv_playback_clock=apple_tv_playback_clock,
        last_timecode_motion_mono=last_timecode_motion_mono,
    )

    _playback_extrapolated_pair = _bind_deps(
        _core_now_playing._playback_extrapolated_pair,
        apple_tv_playback_clock=apple_tv_playback_clock,
    )
    ctx._playback_extrapolated_pair = _playback_extrapolated_pair

    _sync_trt_text_to_true_once = _bind_deps(
        _core_now_playing._sync_trt_text_to_true_once,
        _format_hmmss=_format_hmmss,
        _playback_extrapolated_pair=_playback_extrapolated_pair,
        _playback_progress_fraction_for_bar=_late(lambda: _playback_progress_fraction_for_bar, "_playback_progress_fraction_for_bar"),
        _refresh_trt_progress_only=_late(lambda: _refresh_trt_progress_only, "_refresh_trt_progress_only"),
        _sync_status_bar_trt_substantive=_late(lambda: _sync_status_bar_trt_substantive, "_sync_status_bar_trt_substantive"),
        _warm_status_bar_blits=_warm_status_bar_blits,
        apple_tv_playback_clock=apple_tv_playback_clock,
        skip_cache=skip_cache,
        status_bar_widget=status_bar_widget,
    )

    _update_status_bar_from_metadata = _bind_deps(
        _core_now_playing._update_status_bar_from_metadata,
        _apply_playback_clock_from_poll=_apply_playback_clock_from_poll,
        _sync_trt_text_to_true_once=_sync_trt_text_to_true_once,
    )

    _playback_progress_fraction_for_bar = _bind_deps(
        _core_now_playing._playback_progress_fraction_for_bar,
        apple_tv_playback_clock=apple_tv_playback_clock,
    )
    ctx._playback_progress_fraction_for_bar = _playback_progress_fraction_for_bar

    _refresh_trt_progress_only = _bind_deps(
        _core_now_playing._refresh_trt_progress_only,
        _playback_progress_fraction_for_bar=_playback_progress_fraction_for_bar,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        _warm_status_bar_blits=_warm_status_bar_blits,
        skip_cache=skip_cache,
        status_bar_widget=status_bar_widget,
    )

    # Mid-bootstrap (~1–2 s in): SVG chrome is warm; full sync is safe now.
    _warm_view_one_splash_chrome_only(phase="chrome-mid-bootstrap")

    _playback_ui_tick = _bind_deps(
        _core_now_playing._playback_ui_tick,
        _idle_audio_meter_active=_idle_audio_meter_active,
        _playback_ui_tick=_late(lambda: _playback_ui_tick, "_playback_ui_tick"),
        _refresh_content_indicator=_refresh_content_indicator,
        _refresh_extrapolated_timecodes=_late(lambda: _refresh_extrapolated_timecodes, "_refresh_extrapolated_timecodes"),
        apple_tv_playback_clock=apple_tv_playback_clock,
        root=root,
    )

    _update_atv_interaction_from_poll_metadata = _bind_deps(
        _core_device_control._update_atv_interaction_from_poll_metadata,
        _atv_ix_extrap_playing=_atv_ix_extrap_playing,
        _atv_ix_pos=_atv_ix_pos,
        _atv_ix_pos_mono=_atv_ix_pos_mono,
        _atv_ix_prev_idle=_atv_ix_prev_idle,
        _atv_ix_sig_ck=_atv_ix_sig_ck,
        _atv_ix_sig_ds=_atv_ix_sig_ds,
        _atv_metadata_is_content_idle=_atv_metadata_is_content_idle,
        _content_key_from_metadata=_content_key_from_metadata,
        current_apple_tv=current_apple_tv,
        last_atv_interaction_mono=last_atv_interaction_mono,
    )

    _trt_substantive_from_clock = _bind_deps(
        _core_now_playing._trt_substantive_from_clock,
        apple_tv_playback_clock=apple_tv_playback_clock,
    )

    _trt_substantive_for_status_bar = _bind_deps(
        _core_now_playing._trt_substantive_for_status_bar,
        _trt_substantive_from_clock=_trt_substantive_from_clock,
    )

    _sync_status_bar_trt_substantive = _bind_deps(
        _core_now_playing._sync_status_bar_trt_substantive,
        _trt_substantive_for_status_bar=_trt_substantive_for_status_bar,
        _warm_status_bar_blits=_warm_status_bar_blits,
        skip_cache=skip_cache,
        status_bar_widget=status_bar_widget,
    )

    _refresh_extrapolated_timecodes = _bind_deps(
        _core_now_playing._refresh_extrapolated_timecodes,
        _format_hmmss=_format_hmmss,
        _idle_audio_meter_active=_idle_audio_meter_active,
        _playback_extrapolated_pair=_playback_extrapolated_pair,
        _playback_progress_fraction_for_bar=_playback_progress_fraction_for_bar,
        _sync_status_bar_trt_substantive=_sync_status_bar_trt_substantive,
        _warm_status_bar_blits=_warm_status_bar_blits,
        apple_tv_playback_clock=apple_tv_playback_clock,
        skip_cache=skip_cache,
        status_bar_widget=status_bar_widget,
    )

    _sync_status_bar_visibility_for_playback = _bind_deps(
        _core_now_playing._sync_status_bar_visibility_for_playback,
        DisplayView=DisplayView,
        _atv_metadata_is_content_idle=_atv_metadata_is_content_idle,
        _effective_display_view=_effective_display_view,
        _np_widgets_content_active=_np_widgets_content_active,
        _resolve_receiver_lines_for_now_playing=_resolve_receiver_lines_for_now_playing,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        _sync_status_bar_trt_substantive=_sync_status_bar_trt_substantive,
        _warm_status_bar_blits=_warm_status_bar_blits,
        apple_tv_playback_clock=apple_tv_playback_clock,
        current_apple_tv=current_apple_tv,
        skip_cache=skip_cache,
        status_bar_widget=status_bar_widget,
    )
    ctx._sync_status_bar_visibility_for_playback = _sync_status_bar_visibility_for_playback

    _sync_streaming_badge_from_playback_sources = _bind_deps(
        _core_now_playing._sync_streaming_badge_from_playback_sources,
        _PROJECT_DIR=_PROJECT_DIR,
        _apply_netflix_backdrop_when_running=_apply_netflix_backdrop_when_running,
        _atv_metadata_is_content_idle=_atv_metadata_is_content_idle,
        _idle_audio_meter_active=_idle_audio_meter_active,
        _warm_playback_overlay_blits=_warm_playback_overlay_blits,
        playback_overlay_widget=playback_overlay_widget,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        skip_cache=skip_cache,
        streaming_badge_state=streaming_badge_state,
    )

    _return_to_landing_if_atv_idle = _bind_deps(
        _core_saver_state._return_to_landing_if_atv_idle,
        _PIGEON_EXT=_PIGEON_EXT,
        _atv_metadata_is_content_idle=_atv_metadata_is_content_idle,
        _clear_playback_artwork_caches=_clear_playback_artwork_caches,
        _disp_fit=_disp_fit,
        _program_audio_session=_program_audio_session,
        _refresh_content_indicator=_refresh_content_indicator,
        _resolve_receiver_lines_for_now_playing=_resolve_receiver_lines_for_now_playing,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        _sync_status_bar_visibility_for_playback=_sync_status_bar_visibility_for_playback,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        _warm_status_bar_blits=_warm_status_bar_blits,
        _warm_tmdb_logo_patch=_warm_tmdb_logo_patch,
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
        backdrop_app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit,
        backdrop_master_bgr=backdrop_master_bgr,
        landing_scene_design_bgr=landing_scene_design_bgr,
        last_frame=last_frame,
        playing=playing,
        receiver_standby_holder=receiver_standby_holder,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        scaled_display=scaled_display,
        scaled_version=scaled_version,
        scene_enabled=scene_enabled,
        skip_cache=skip_cache,
        status_bar_widget=status_bar_widget,
        tmdb_logo_app_fallback_active=tmdb_logo_app_fallback_active,
        tmdb_logo_patch_bgra=tmdb_logo_patch_bgra,
        tmdb_logo_widget=tmdb_logo_widget,
        tmdb_logo_widget_view_six=tmdb_logo_widget_view_six,
        use_backdrop_scene=use_backdrop_scene,
    )

    def _manual_search_redraw() -> None:
        """A suggestion list / poster finished loading off-thread — repaint."""
        skip_cache[0] = None
        try:
            root.after(0, lambda: ctx.render_once())
        except Exception:
            pass

    def _manual_search_clear_display() -> None:
        """SEARCH title cleared while shown — fall back to the idle landing."""
        _return_to_landing_if_atv_idle(apple_tv_auto_state.get("last_metadata") or {})

    from pigeon import manual_search as _manual_search

    _manual_search.install_hooks(
        spawn=lambda q, **kw: spawn_tmdb_poster_fetch(q, **kw),
        refresh=_manual_search_redraw,
        clear_display=_manual_search_clear_display,
    )

    def _control_api_status() -> dict:
        """Read-only now-playing snapshot for the companion API (any thread)."""
        title = str((active_tmdb_display_title[0] or "")).strip()
        lm = apple_tv_auto_state.get("last_metadata")
        if isinstance(lm, dict):
            if not title:
                for key in ("title", "series_name"):
                    title = str(lm.get(key) or "").strip()
                    if title:
                        break
            app = str(lm.get("app") or lm.get("app_name") or "").strip()
        else:
            app = ""
        if not title or _manual_search.is_displaying():
            return {}
        return {"state": "playing", "now_playing": {"title": title, "source": "detected", "app": app or None}}

    try:
        from pigeon import control_api as _control_api

        _control_api.start(
            status_provider=_control_api_status,
            run_on_ui=lambda fn: root.after(0, fn),
        )
    except Exception:
        pass  # the companion API must never block startup

    _apply_hdmi_frame_check = _bind_deps(
        _core_device_control._apply_hdmi_frame_check,
        _bump_clock_saver_significant_device=_bump_clock_saver_significant_device,
        _note_metadata_activity=_note_metadata_activity,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        apple_tv_auto_state=apple_tv_auto_state,
    )

    _on_hdmi_frame_checked = _bind_deps(
        _core_device_control._on_hdmi_frame_checked,
        _apply_hdmi_frame_check=_apply_hdmi_frame_check,
        apple_tv_auto_state=apple_tv_auto_state,
        root=root,
    )

    _schedule_hdmi_frame_check_from_poll = _bind_deps(
        _core_device_control._schedule_hdmi_frame_check_from_poll,
        _on_hdmi_frame_checked=_on_hdmi_frame_checked,
        apple_tv_auto_state=apple_tv_auto_state,
    )

    _apple_tv_auto_poll_tick = _bind_deps(
        _core_device_control._apple_tv_auto_poll_tick,
        APPLE_TV_FAIL_POLL_MAX_MS=APPLE_TV_FAIL_POLL_MAX_MS,
        APPLE_TV_IDLE_POLL_MS=APPLE_TV_IDLE_POLL_MS,
        APPLE_TV_POLL_MS=APPLE_TV_POLL_MS,
        RECEIVER_POLL_MS=RECEIVER_POLL_MS,
        _PIGEON_EXT=_PIGEON_EXT,
        _apple_tv_auto_poll_tick=_late(lambda: _apple_tv_auto_poll_tick, "_apple_tv_auto_poll_tick"),
        _apple_tv_scan_timeout_s=_apple_tv_scan_timeout_s,
        _atv_metadata_is_content_idle=_atv_metadata_is_content_idle,
        _bump_clock_saver_significant_device=_bump_clock_saver_significant_device,
        _bump_clock_saver_significant_device_from_metadata=_bump_clock_saver_significant_device_from_metadata,
        _clear_displayed_tmdb_art_for_content_change=_clear_displayed_tmdb_art_for_content_change,
        _content_key_from_metadata=_content_key_from_metadata,
        _idle_audio_meter_active=_idle_audio_meter_active,
        _pyatv_install_hint=_pyatv_install_hint,
        _refresh_content_indicator=_refresh_content_indicator,
        _refresh_observed_pairing_led_rows=_refresh_observed_pairing_led_rows,
        _return_to_landing_if_atv_idle=_return_to_landing_if_atv_idle,
        _schedule_hdmi_frame_check_from_poll=_schedule_hdmi_frame_check_from_poll,
        _seed_current_apple_tv_from_streaming_slot=_seed_current_apple_tv_from_streaming_slot,
        _store_music_artwork_from_metadata=_store_music_artwork_from_metadata,
        _sync_status_bar_visibility_for_playback=_sync_status_bar_visibility_for_playback,
        _sync_streaming_badge_from_playback_sources=_sync_streaming_badge_from_playback_sources,
        _tmdb_pref_from_metadata=_tmdb_pref_from_metadata,
        _tmdb_spawn_identity_changed=_tmdb_spawn_identity_changed,
        _update_atv_interaction_from_poll_metadata=_update_atv_interaction_from_poll_metadata,
        _update_status_bar_from_metadata=_update_status_bar_from_metadata,
        _warm_playback_overlay_blits=_warm_playback_overlay_blits,
        active_tmdb_title_key=active_tmdb_title_key,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_busy=apple_tv_busy,
        apple_tv_dashboard_track=apple_tv_dashboard_track,
        current_apple_tv=current_apple_tv,
        denon_vol_cache=denon_vol_cache,
        playback_overlay_widget=playback_overlay_widget,
        receiver_overlay_state=receiver_overlay_state,
        receiver_standby_holder=receiver_standby_holder,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        resolve_metadata_tmdb_query=resolve_metadata_tmdb_query,
        root=root,
        skip_cache=skip_cache,
        spawn_tmdb_poster_fetch=spawn_tmdb_poster_fetch,
        streaming_slot_holder=streaming_slot_holder,
    )

    on_debug_streaming_slot_apple_tv = _bind_deps(
        _core_device_control.on_debug_streaming_slot_apple_tv,
        _PIGEON_EXT=_PIGEON_EXT,
        _open_find_device_dialog=_open_find_device_dialog,
        _pyatv_install_hint=_pyatv_install_hint,
        apple_tv_busy=apple_tv_busy,
        begin_apple_tv_operation=begin_apple_tv_operation,
        describe_current_apple_tv=describe_current_apple_tv,
        end_apple_tv_operation=end_apple_tv_operation,
        root=root,
        streaming_slot_holder=streaming_slot_holder,
    )

    _attach_hover_tooltip = _bind_deps(
        _core_settings_ui._attach_hover_tooltip,
        S_FONT_SMALL=S_FONT_SMALL,
        root=root,
    )

    _perform_tmdb_error_flag_retry = _bind_deps(
        _core_tmdb_flow._perform_tmdb_error_flag_retry,
        TMDB_ERROR_FLAG_RETRY_RULES=TMDB_ERROR_FLAG_RETRY_RULES,
        _PIGEON_EXT=_PIGEON_EXT,
        _alternate_tmdb_query_from_metadata=_alternate_tmdb_query_from_metadata,
        _clear_now_playing_view_caches=_clear_now_playing_view_caches,
        _mark_tmdb_missing_art=_mark_tmdb_missing_art,
        _raw_title_query_from_metadata=_raw_title_query_from_metadata,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        _tmdb_retry_log_append=_tmdb_retry_log_append,
        _tmdb_spawn_identity=_tmdb_spawn_identity,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        apple_tv_auto_state=apple_tv_auto_state,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        skip_cache=skip_cache,
        spawn_tmdb_poster_fetch=spawn_tmdb_poster_fetch,
        tmdb_error_flag_retry_active=tmdb_error_flag_retry_active,
        tmdb_error_flag_retry_rule_idx=tmdb_error_flag_retry_rule_idx,
    )
    ctx._perform_tmdb_error_flag_retry = _perform_tmdb_error_flag_retry

    _perform_tmdb_artwork_retry = _bind_deps(
        _core_tmdb_flow._perform_tmdb_artwork_retry,
        _PIGEON_EXT=_PIGEON_EXT,
        _alternate_tmdb_query_from_metadata=_alternate_tmdb_query_from_metadata,
        _append_tmdb_retry_log_ui=_append_tmdb_retry_log_ui,
        _tmdb_retry_log_append=_tmdb_retry_log_append,
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
        spawn_tmdb_poster_fetch=spawn_tmdb_poster_fetch,
        tmdb_retry_rule_idx=tmdb_retry_rule_idx,
    )

    on_tmdb_retry_hotkey = _bind_deps(
        _core_input_keys.on_tmdb_retry_hotkey,
        _PIGEON_EXT=_PIGEON_EXT,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _last_tmdb_hotkey_mono=_last_tmdb_hotkey_mono,
        _perform_tmdb_artwork_retry=_perform_tmdb_artwork_retry,
        _widget_accepts_typing=_widget_accepts_typing,
    )

    on_tmdb_quality_error_report_hotkey = _bind_deps(
        _core_tmdb_flow.on_tmdb_quality_error_report_hotkey,
        TMDB_QUALITY_UNLOG_WINDOW_S=TMDB_QUALITY_UNLOG_WINDOW_S,
        _PIGEON_EXT=_PIGEON_EXT,
        _adjust_tmdb_quality_failure_delta=_adjust_tmdb_quality_failure_delta,
        _append_tmdb_quality_event_report_log=_append_tmdb_quality_event_report_log,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _clear_tmdb_quality_flag=_clear_tmdb_quality_flag,
        _last_tmdb_quality_report_mono=_last_tmdb_quality_report_mono,
        _perform_tmdb_error_flag_retry=_perform_tmdb_error_flag_retry,
        _schedule_tmdb_quality_auto_expire=_schedule_tmdb_quality_auto_expire,
        _trigger_tmdb_quality_toggle_overlay=_trigger_tmdb_quality_toggle_overlay,
        _widget_accepts_typing=_widget_accepts_typing,
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        apple_tv_auto_state=apple_tv_auto_state,
        skip_cache=skip_cache,
        tmdb_error_flag_retry_active=tmdb_error_flag_retry_active,
        tmdb_error_flag_retry_rule_idx=tmdb_error_flag_retry_rule_idx,
        tmdb_quality_error_flag=tmdb_quality_error_flag,
        tmdb_quality_flag_set_mono=tmdb_quality_flag_set_mono,
    )

    purge_image_media_btn_holder[0] = tk.Button(
        content_buttons_row,
        text="Purge Image Media",
        command=on_purge_image_media,
        font=S_FONT_BTN,
        padx=8,
        pady=4,
    )
    purge_image_media_btn_holder[0].pack(side=tk.LEFT, padx=(0, 8))
    if _PIGEON_EXT:
        _mq_glance = tk.Label(
            content_buttons_row,
            text="",
            fg="#e4e6ef",
            bg="#111",
            font=(_S, 13, "bold"),
            anchor=tk.W,
            justify=tk.LEFT,
        )
        _mq_glance.pack(side=tk.LEFT, padx=(8, 0), anchor=tk.CENTER)
        match_quality_glance_label_holder[0] = _mq_glance
        _attach_hover_tooltip(
            _mq_glance,
            "⌘⇧X / Ctrl+Shift+X toggles the quality flag: turning it on adds a persisted failure "
            "immediately; turning it off removes one (not below zero). Each new content event still "
            "scores one outcome after a successful populate (success, or FAILURE log only if the flag "
            "was on). Persisted in state.json; details + log on Advanced → TMDb.",
        )
        reset_mq_stats_btn = tk.Button(
            content_buttons_row,
            text="Reset match stats",
            command=on_reset_tmdb_match_quality_stats,
            font=S_FONT_BTN,
            padx=8,
            pady=4,
        )
        reset_mq_stats_btn.pack(side=tk.LEFT, padx=(10, 0))
        _attach_hover_tooltip(
            reset_mq_stats_btn,
            "Clears the ok / fail counts and % shown here (saved in state.json). Does not change "
            "tmdb_error_report.numbers, pigeonTMDBReport.csv, or tmdb_quality_event_reports.log.",
        )
        root.after_idle(_refresh_match_quality_glance_label)

    ctx._apple_tv_auto_poll_tick = _apple_tv_auto_poll_tick
    ctx._attach_hover_tooltip = _attach_hover_tooltip
    ctx._handle_main_settings_action = _handle_main_settings_action
    ctx._playback_ui_tick = _playback_ui_tick
    ctx._rebuild_paired_devices_panel = _rebuild_paired_devices_panel
    ctx._refresh_observed_pairing_led_rows = _refresh_observed_pairing_led_rows
    ctx._schedule_refresh_pairing_leds = _schedule_refresh_pairing_leds
    ctx._seed_current_apple_tv_from_streaming_slot = _seed_current_apple_tv_from_streaming_slot
    ctx._sync_streaming_badge_from_playback_sources = _sync_streaming_badge_from_playback_sources
    ctx.describe_current_apple_tv = describe_current_apple_tv
    ctx.on_debug_streaming_slot_apple_tv = on_debug_streaming_slot_apple_tv
    ctx.on_reset_pigeon_devices_and_media = on_reset_pigeon_devices_and_media
    ctx.on_tmdb_quality_error_report_hotkey = on_tmdb_quality_error_report_hotkey
    ctx.on_tmdb_retry_hotkey = on_tmdb_retry_hotkey
