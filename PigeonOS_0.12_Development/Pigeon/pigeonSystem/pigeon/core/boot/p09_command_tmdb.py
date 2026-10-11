"""Boot phase: the command bar and the TMDb lookup / match-quality flow.

Phase 9 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from pigeon.core import input_keys as _core_input_keys
from pigeon.core import settings_ui as _core_settings_ui
from pigeon.core import stage_render as _core_stage_render
from pigeon.core import tmdb_flow as _core_tmdb_flow
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.core.binding import late as _late
import tkinter as tk


def run(ctx) -> None:
    BACKDROP_BRIGHTNESS = ctx.BACKDROP_BRIGHTNESS
    DevPhase = ctx.DevPhase
    DisplayView = ctx.DisplayView
    LANDING_DIM_BRIGHTNESS = ctx.LANDING_DIM_BRIGHTNESS
    LANDING_DISPLAY_BRIGHTNESS = ctx.LANDING_DISPLAY_BRIGHTNESS
    LOCATION_TOAST_FADE_S = ctx.LOCATION_TOAST_FADE_S
    LOCATION_TOAST_FULL_S = ctx.LOCATION_TOAST_FULL_S
    WINDOW_H = ctx.WINDOW_H
    WINDOW_W = ctx.WINDOW_W
    _PIGEON_EXT = ctx._PIGEON_EXT
    _app_logo_clock_saver_style_now = ctx._app_logo_clock_saver_style_now
    _apply_brightness = ctx._apply_brightness
    _apply_netflix_backdrop_when_running = ctx._apply_netflix_backdrop_when_running
    _atv_metadata_is_content_idle = ctx._atv_metadata_is_content_idle
    _backdrop_master_from_streaming_app_logo = ctx._backdrop_master_from_streaming_app_logo
    _bgr_to_tk_image = ctx._bgr_to_tk_image
    _black_screen_bgr = ctx._black_screen_bgr
    _bump_pigeon_user_activity = ctx._bump_pigeon_user_activity
    _clear_now_playing_view_caches = ctx._clear_now_playing_view_caches
    _compose_shown_frame = ctx._compose_shown_frame
    _default_render_fps = ctx._default_render_fps
    _design_grid_overlay_active = ctx._design_grid_overlay_active
    _disp_fit = ctx._disp_fit
    _paint_boolean_led = ctx._paint_boolean_led
    _save_persisted_scene_enabled = ctx._save_persisted_scene_enabled
    _settings_unbind_wheel_globals = ctx._settings_unbind_wheel_globals
    _sync_now_playing_screen_state = ctx._sync_now_playing_screen_state
    _tmdb_poster_cache = ctx._tmdb_poster_cache
    _tmdb_tt_src_cache = ctx._tmdb_tt_src_cache
    _update_label_photo_from_bgr = ctx._update_label_photo_from_bgr
    _view_one_uses_now_playing_screen = ctx._view_one_uses_now_playing_screen
    _vv_is_music = ctx._vv_is_music
    _vv_is_youtube = ctx._vv_is_youtube
    _warm_status_bar_blits = ctx._warm_status_bar_blits
    _warm_tmdb_logo_patch = ctx._warm_tmdb_logo_patch
    active_tmdb_display_title = ctx.active_tmdb_display_title
    active_tmdb_title_key = ctx.active_tmdb_title_key
    apple_tv_auto_state = ctx.apple_tv_auto_state
    apple_tv_busy = ctx.apple_tv_busy
    apple_tv_dashboard_track = ctx.apple_tv_dashboard_track
    apple_tv_playback_clock = ctx.apple_tv_playback_clock
    backdrop_app_logo_letterbox_fit = ctx.backdrop_app_logo_letterbox_fit
    backdrop_master_bgr = ctx.backdrop_master_bgr
    black_photo = ctx.black_photo
    brightness_current = ctx.brightness_current
    brightness_duration_down_s = ctx.brightness_duration_down_s
    brightness_duration_s = ctx.brightness_duration_s
    brightness_duration_up_s = ctx.brightness_duration_up_s
    brightness_from = ctx.brightness_from
    brightness_t0 = ctx.brightness_t0
    brightness_target = ctx.brightness_target
    cap = ctx.cap
    content_indicator_cv_holder = ctx.content_indicator_cv_holder
    current_apple_tv = ctx.current_apple_tv
    dev_phase = ctx.dev_phase
    display_dims = ctx.display_dims
    display_view_holder = ctx.display_view_holder
    frame_interval_ms = ctx.frame_interval_ms
    label = ctx.label
    label_live_photo = ctx.label_live_photo
    landing_scene_design_bgr = ctx.landing_scene_design_bgr
    last_frame = ctx.last_frame
    location_toast_state = ctx.location_toast_state
    main_settings_widget_holder = ctx.main_settings_widget_holder
    match_quality_glance_sig = ctx.match_quality_glance_sig
    pairing_led_holder = ctx.pairing_led_holder
    playing = ctx.playing
    prev_dev_phase_for_location_toast = ctx.prev_dev_phase_for_location_toast
    root = ctx.root
    saved_backdrop_app_logo_letterbox_fit = ctx.saved_backdrop_app_logo_letterbox_fit
    saved_backdrop_master_bgr = ctx.saved_backdrop_master_bgr
    scaled_display = ctx.scaled_display
    scaled_version = ctx.scaled_version
    scene_enabled = ctx.scene_enabled
    settings_frame = ctx.settings_frame
    shell = ctx.shell
    skip_cache = ctx.skip_cache
    status_bar_widget = ctx.status_bar_widget
    streaming_badge_state = ctx.streaming_badge_state
    tmdb_logo_app_fallback_active = ctx.tmdb_logo_app_fallback_active
    tmdb_logo_patch_bgra = ctx.tmdb_logo_patch_bgra
    tmdb_logo_widget = ctx.tmdb_logo_widget
    tmdb_logo_widget_view_six = ctx.tmdb_logo_widget_view_six
    use_backdrop_scene = ctx.use_backdrop_scene
    view_circles_widget_holder = ctx.view_circles_widget_holder

    command_entry_visible = [False]
    command_bar = tk.Frame(shell, bg="#1a1a1e", height=30)
    command_bar.pack_propagate(False)
    command_entry = tk.Entry(
        command_bar,
        bg="#2d2d32",
        fg="#f0f0f0",
        insertbackground="#f0f0f0",
        relief=tk.FLAT,
        highlightthickness=1,
        highlightbackground="#0a84ff",
        font=("Helvetica", 12),
    )
    command_entry.pack(fill=tk.BOTH, expand=True, padx=4, pady=3)

    _ui_scale = _bind_deps(
        _core_stage_render._ui_scale,
        WINDOW_H=WINDOW_H,
        WINDOW_W=WINDOW_W,
        display_dims=display_dims,
    )

    _layout_chrome = _bind_deps(
        _core_stage_render._layout_chrome,
        _ui_scale=_ui_scale,
        command_entry_visible=command_entry_visible,
        display_dims=display_dims,
        place_command_bar=_late(lambda: place_command_bar, "place_command_bar"),
    )

    place_command_bar = _bind_deps(
        _core_stage_render.place_command_bar,
        _ui_scale=_ui_scale,
        command_bar=command_bar,
        display_dims=display_dims,
    )

    hide_command_entry = _bind_deps(
        _core_tmdb_flow.hide_command_entry,
        command_bar=command_bar,
        command_entry_visible=command_entry_visible,
        label=label,
    )

    _apply_dev_phase_widgets = _bind_deps(
        _core_stage_render._apply_dev_phase_widgets,
        label=label,
        settings_frame=settings_frame,
    )

    _current_location_display_name = _core_settings_ui._current_location_display_name

    _location_toast_alpha = _bind_deps(
        _core_stage_render._location_toast_alpha,
        LOCATION_TOAST_FADE_S=LOCATION_TOAST_FADE_S,
        LOCATION_TOAST_FULL_S=LOCATION_TOAST_FULL_S,
        location_toast_state=location_toast_state,
    )
    ctx._location_toast_alpha = _location_toast_alpha

    _start_location_toast = _bind_deps(
        _core_settings_ui._start_location_toast,
        _PIGEON_EXT=_PIGEON_EXT,
        _current_location_display_name=_current_location_display_name,
        location_toast_state=location_toast_state,
        skip_cache=skip_cache,
    )
    ctx._start_location_toast = _start_location_toast

    sync_developer_chrome = _bind_deps(
        _core_stage_render.sync_developer_chrome,
        DevPhase=DevPhase,
        _PIGEON_EXT=_PIGEON_EXT,
        _apply_dev_phase_widgets=_apply_dev_phase_widgets,
        _layout_chrome=_layout_chrome,
        _settings_unbind_wheel_globals=_settings_unbind_wheel_globals,
        _start_location_toast=_start_location_toast,
        command_bar=command_bar,
        command_entry_visible=command_entry_visible,
        dev_phase=dev_phase,
        hide_command_entry=hide_command_entry,
        label=label,
        place_command_bar=place_command_bar,
        prev_dev_phase_for_location_toast=prev_dev_phase_for_location_toast,
        root=root,
    )
    ctx.sync_developer_chrome = sync_developer_chrome

    toggle_play = _bind_deps(
        _core_stage_render.toggle_play,
        LANDING_DIM_BRIGHTNESS=LANDING_DIM_BRIGHTNESS,
        LANDING_DISPLAY_BRIGHTNESS=LANDING_DISPLAY_BRIGHTNESS,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        brightness_current=brightness_current,
        brightness_duration_down_s=brightness_duration_down_s,
        brightness_duration_s=brightness_duration_s,
        brightness_duration_up_s=brightness_duration_up_s,
        brightness_from=brightness_from,
        brightness_t0=brightness_t0,
        brightness_target=brightness_target,
        last_frame=last_frame,
        playing=playing,
        scene_enabled=scene_enabled,
        use_backdrop_scene=use_backdrop_scene,
    )

    quit_app = _bind_deps(_core_input_keys.quit_app, root=root)

    cycle_dev_phase = _bind_deps(
        _core_stage_render.cycle_dev_phase,
        DevPhase=DevPhase,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        dev_phase=dev_phase,
        main_settings_widget=main_settings_widget_holder[0],
        render_once=_late(lambda: ctx.render_once, "render_once"),
        skip_cache=skip_cache,
        sync_developer_chrome=sync_developer_chrome,
    )

    _open_landing_scene = _bind_deps(
        _core_stage_render._open_landing_scene,
        _PIGEON_EXT=_PIGEON_EXT,
        _default_render_fps=_default_render_fps,
        _disp_fit=_disp_fit,
        backdrop_master_bgr=backdrop_master_bgr,
        frame_interval_ms=frame_interval_ms,
        landing_scene_design_bgr=landing_scene_design_bgr,
        last_frame=last_frame,
        scaled_display=scaled_display,
        scaled_version=scaled_version,
        use_backdrop_scene=use_backdrop_scene,
    )

    toggle_scene = _bind_deps(
        _core_stage_render.toggle_scene,
        _PIGEON_EXT=_PIGEON_EXT,
        _apply_brightness=_apply_brightness,
        _bgr_to_tk_image=_bgr_to_tk_image,
        _black_screen_bgr=_black_screen_bgr,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _compose_shown_frame=_compose_shown_frame,
        _design_grid_overlay_active=_design_grid_overlay_active,
        _open_landing_scene=_open_landing_scene,
        _save_persisted_scene_enabled=_save_persisted_scene_enabled,
        _update_label_photo_from_bgr=_update_label_photo_from_bgr,
        backdrop_master_bgr=backdrop_master_bgr,
        black_photo=black_photo,
        brightness_current=brightness_current,
        label=label,
        label_live_photo=label_live_photo,
        last_frame=last_frame,
        playing=playing,
        scaled_display=scaled_display,
        scene_enabled=scene_enabled,
        skip_cache=skip_cache,
        use_backdrop_scene=use_backdrop_scene,
    )

    _last_overlay_mono = [0.0]
    _last_s_mono = [0.0]
    _last_f10_mono = [0.0]
    _last_tmdb_hotkey_mono = [0.0]
    _last_tmdb_quality_report_mono = [0.0]
    # Set True by ⌘⇧X / Ctrl+Shift+X; failure count bumps immediately, cleared when a
    # successful TMDb populate is scored for a new content event key.
    tmdb_quality_error_flag: list[bool] = [False]
    tmdb_quality_flag_set_mono: list[float] = [0.0]
    tmdb_quality_auto_unlog_after_id: list[str | None] = [None]
    tmdb_error_flag_retry_rule_idx: list[int] = [0]
    # When True, finish_tmdb auto-advances through one full error-flag rule cycle.
    tmdb_error_flag_retry_active: list[bool] = [False]
    TMDB_QUALITY_UNLOG_WINDOW_S = 20.0
    TMDB_ERROR_FLAG_RETRY_RULES: list[tuple[str, str, str]] = [
        ("tv", "raw_title", "tv+raw_title"),
        ("tv", "alternate", "tv+alternate_query"),
        ("auto", "raw_title", "auto+raw_title"),
        ("auto", "alternate", "auto+alternate_query"),
        ("movie", "raw_title", "movie+raw_title"),
    ]
    # Last content event key that has already been scored for TMDb quality.
    tmdb_quality_last_scored_event_key: list[str] = [""]
    tmdb_quality_overlay_mode: list[str] = [""]
    tmdb_quality_overlay_t0: list[float] = [0.0]
    _last_tmdb_match_toggle_mono = [0.0]
    _last_space_mono = [0.0]
    _last_adv_shift_tab_mono = [0.0]

    _trigger_tmdb_quality_toggle_overlay = _bind_deps(
        _core_tmdb_flow._trigger_tmdb_quality_toggle_overlay,
        tmdb_quality_overlay_mode=tmdb_quality_overlay_mode,
        tmdb_quality_overlay_t0=tmdb_quality_overlay_t0,
    )

    _tmdb_quality_toggle_overlay_state = _bind_deps(
        _core_tmdb_flow._tmdb_quality_toggle_overlay_state,
        tmdb_quality_overlay_mode=tmdb_quality_overlay_mode,
        tmdb_quality_overlay_t0=tmdb_quality_overlay_t0,
    )

    _blend_tmdb_quality_toggle_overlay = _core_tmdb_flow._blend_tmdb_quality_toggle_overlay

    _blend_tmdb_quality_flag_badge = _core_tmdb_flow._blend_tmdb_quality_flag_badge

    try_cycle_dev_phase = _bind_deps(
        _core_input_keys.try_cycle_dev_phase,
        _last_overlay_mono=_last_overlay_mono,
        cycle_dev_phase=cycle_dev_phase,
    )

    on_tab_key = _bind_deps(
        _core_input_keys.on_tab_key,
        _last_overlay_mono=_last_overlay_mono,
        cycle_dev_phase=cycle_dev_phase,
    )

    on_shift_tab_dev_cycle = _bind_deps(
        _core_input_keys.on_shift_tab_dev_cycle,
        on_tab_key=on_tab_key,
    )

    on_ctrl_tab = _bind_deps(_core_input_keys.on_ctrl_tab, on_tab_key=on_tab_key)

    on_s_key = _bind_deps(
        _core_input_keys.on_s_key,
        _design_grid_overlay_active=_design_grid_overlay_active,
        _last_s_mono=_last_s_mono,
        toggle_scene=toggle_scene,
    )

    apply_saved_tmdb_backdrop_to_display = _bind_deps(
        _core_tmdb_flow.apply_saved_tmdb_backdrop_to_display,
        BACKDROP_BRIGHTNESS=BACKDROP_BRIGHTNESS,
        _PIGEON_EXT=_PIGEON_EXT,
        _app_logo_clock_saver_style_now=_app_logo_clock_saver_style_now,
        _apply_netflix_backdrop_when_running=_apply_netflix_backdrop_when_running,
        _save_persisted_scene_enabled=_save_persisted_scene_enabled,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        _warm_status_bar_blits=_warm_status_bar_blits,
        _warm_tmdb_logo_patch=_warm_tmdb_logo_patch,
        backdrop_app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit,
        backdrop_master_bgr=backdrop_master_bgr,
        brightness_current=brightness_current,
        brightness_from=brightness_from,
        brightness_t0=brightness_t0,
        brightness_target=brightness_target,
        display_dims=display_dims,
        last_frame=last_frame,
        playing=playing,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        saved_backdrop_app_logo_letterbox_fit=saved_backdrop_app_logo_letterbox_fit,
        saved_backdrop_master_bgr=saved_backdrop_master_bgr,
        scaled_display=scaled_display,
        scaled_version=scaled_version,
        scene_enabled=scene_enabled,
        skip_cache=skip_cache,
        status_bar_widget=status_bar_widget,
        use_backdrop_scene=use_backdrop_scene,
        view_circles_widget=view_circles_widget_holder[0],
    )

    f10_cycle_scene_grid = _bind_deps(
        _core_stage_render.f10_cycle_scene_grid,
        LANDING_DISPLAY_BRIGHTNESS=LANDING_DISPLAY_BRIGHTNESS,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _open_landing_scene=_open_landing_scene,
        _save_persisted_scene_enabled=_save_persisted_scene_enabled,
        apply_saved_tmdb_backdrop_to_display=apply_saved_tmdb_backdrop_to_display,
        backdrop_master_bgr=backdrop_master_bgr,
        brightness_current=brightness_current,
        brightness_from=brightness_from,
        brightness_t0=brightness_t0,
        brightness_target=brightness_target,
        last_frame=last_frame,
        playing=playing,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        saved_backdrop_master_bgr=saved_backdrop_master_bgr,
        scaled_display=scaled_display,
        scene_enabled=scene_enabled,
        skip_cache=skip_cache,
        use_backdrop_scene=use_backdrop_scene,
    )

    on_f10_key = _bind_deps(
        _core_input_keys.on_f10_key,
        _design_grid_overlay_active=_design_grid_overlay_active,
        _last_f10_mono=_last_f10_mono,
        f10_cycle_scene_grid=f10_cycle_scene_grid,
        toggle_scene=toggle_scene,
    )

    on_click_focus = _bind_deps(
        _core_input_keys.on_click_focus,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        label=label,
        root=root,
    )

    on_double_click_scene = _bind_deps(
        _core_input_keys.on_double_click_scene,
        toggle_scene=toggle_scene,
    )

    show_command_entry = _bind_deps(
        _core_tmdb_flow.show_command_entry,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        command_bar=command_bar,
        command_entry=command_entry,
        command_entry_visible=command_entry_visible,
        dev_phase=dev_phase,
        display_view_holder=display_view_holder,
        place_command_bar=place_command_bar,
        root=root,
    )

    _last_command_submit_mono = [0.0]

    parse_tmdb_command_phrase = _core_tmdb_flow.parse_tmdb_command_phrase

    _escape_log_field = _core_tmdb_flow._escape_log_field

    _append_tmdb_quality_event_report_log = _bind_deps(
        _core_tmdb_flow._append_tmdb_quality_event_report_log,
        _escape_log_field=_escape_log_field,
        apple_tv_auto_state=apple_tv_auto_state,
        streaming_badge_state=streaming_badge_state,
    )

    _clear_displayed_tmdb_art_for_content_change = _bind_deps(
        _core_tmdb_flow._clear_displayed_tmdb_art_for_content_change,
        _clear_now_playing_view_caches=_clear_now_playing_view_caches,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        _tmdb_poster_cache=_tmdb_poster_cache,
        _tmdb_tt_src_cache=_tmdb_tt_src_cache,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        _warm_tmdb_logo_patch=_warm_tmdb_logo_patch,
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        apple_tv_auto_state=apple_tv_auto_state,
        backdrop_master_bgr=backdrop_master_bgr,
        skip_cache=skip_cache,
        tmdb_error_flag_retry_active=tmdb_error_flag_retry_active,
        tmdb_error_flag_retry_rule_idx=tmdb_error_flag_retry_rule_idx,
        tmdb_logo_app_fallback_active=tmdb_logo_app_fallback_active,
        tmdb_logo_patch_bgra=tmdb_logo_patch_bgra,
        tmdb_logo_widget=tmdb_logo_widget,
        tmdb_logo_widget_view_six=tmdb_logo_widget_view_six,
    )

    _mark_tmdb_missing_art = _bind_deps(
        _core_tmdb_flow._mark_tmdb_missing_art,
        apple_tv_auto_state=apple_tv_auto_state,
        tmdb_error_flag_retry_active=tmdb_error_flag_retry_active,
    )

    _clear_tmdb_missing_art = _bind_deps(
        _core_tmdb_flow._clear_tmdb_missing_art,
        apple_tv_auto_state=apple_tv_auto_state,
        tmdb_error_flag_retry_active=tmdb_error_flag_retry_active,
    )

    spawn_tmdb_poster_fetch = _bind_deps(
        _core_tmdb_flow.spawn_tmdb_poster_fetch,
        BACKDROP_BRIGHTNESS=BACKDROP_BRIGHTNESS,
        TMDB_ERROR_FLAG_RETRY_RULES=TMDB_ERROR_FLAG_RETRY_RULES,
        _PIGEON_EXT=_PIGEON_EXT,
        _append_tmdb_quality_event_report_log=_append_tmdb_quality_event_report_log,
        _apply_netflix_backdrop_when_running=_apply_netflix_backdrop_when_running,
        _apply_rawtitle_text_tt_fallback=_late(lambda: _apply_rawtitle_text_tt_fallback, "_apply_rawtitle_text_tt_fallback"),
        _backdrop_master_from_streaming_app_logo=_backdrop_master_from_streaming_app_logo,
        _cancel_tmdb_quality_auto_unlog_timer=_late(lambda: _cancel_tmdb_quality_auto_unlog_timer, "_cancel_tmdb_quality_auto_unlog_timer"),
        _clear_now_playing_view_caches=_clear_now_playing_view_caches,
        _clear_tmdb_missing_art=_clear_tmdb_missing_art,
        _mark_tmdb_missing_art=_mark_tmdb_missing_art,
        _perform_tmdb_error_flag_retry=_late(lambda: ctx._perform_tmdb_error_flag_retry, "_perform_tmdb_error_flag_retry"),
        _save_persisted_scene_enabled=_save_persisted_scene_enabled,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        _tmdb_match_tier_acceptable=_late(lambda: _tmdb_match_tier_acceptable, "_tmdb_match_tier_acceptable"),
        _tmdb_spawn_identity=_late(lambda: ctx._tmdb_spawn_identity, "_tmdb_spawn_identity"),
        _tmdb_spawn_identity_changed=_late(lambda: ctx._tmdb_spawn_identity_changed, "_tmdb_spawn_identity_changed"),
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        _vv_is_music=_vv_is_music,
        _vv_is_youtube=_vv_is_youtube,
        _warm_status_bar_blits=_warm_status_bar_blits,
        _warm_tmdb_logo_patch=_warm_tmdb_logo_patch,
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
        backdrop_app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit,
        backdrop_master_bgr=backdrop_master_bgr,
        brightness_current=brightness_current,
        brightness_from=brightness_from,
        brightness_t0=brightness_t0,
        brightness_target=brightness_target,
        cap=cap,
        last_frame=last_frame,
        playing=playing,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        root=root,
        saved_backdrop_app_logo_letterbox_fit=saved_backdrop_app_logo_letterbox_fit,
        saved_backdrop_master_bgr=saved_backdrop_master_bgr,
        scaled_display=scaled_display,
        scaled_version=scaled_version,
        scene_enabled=scene_enabled,
        skip_cache=skip_cache,
        spawn_tmdb_poster_fetch=_late(lambda: spawn_tmdb_poster_fetch, "spawn_tmdb_poster_fetch"),
        status_bar_widget=status_bar_widget,
        streaming_badge_state=streaming_badge_state,
        tmdb_error_flag_retry_active=tmdb_error_flag_retry_active,
        tmdb_error_flag_retry_rule_idx=tmdb_error_flag_retry_rule_idx,
        tmdb_logo_app_fallback_active=tmdb_logo_app_fallback_active,
        tmdb_logo_widget=tmdb_logo_widget,
        tmdb_logo_widget_view_six=tmdb_logo_widget_view_six,
        tmdb_quality_error_flag=tmdb_quality_error_flag,
        tmdb_quality_last_scored_event_key=tmdb_quality_last_scored_event_key,
        use_backdrop_scene=use_backdrop_scene,
    )

    _content_indicator_ok = _bind_deps(
        _core_settings_ui._content_indicator_ok,
        _PIGEON_EXT=_PIGEON_EXT,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_busy=apple_tv_busy,
        apple_tv_dashboard_track=apple_tv_dashboard_track,
        current_apple_tv=current_apple_tv,
    )
    ctx._content_indicator_ok = _content_indicator_ok

    _advanced_feature_pipeline_ok = _bind_deps(
        _core_settings_ui._advanced_feature_pipeline_ok,
        _PIGEON_EXT=_PIGEON_EXT,
        _atv_metadata_is_content_idle=_atv_metadata_is_content_idle,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_busy=apple_tv_busy,
        apple_tv_dashboard_track=apple_tv_dashboard_track,
        current_apple_tv=current_apple_tv,
    )

    _cancel_tmdb_quality_auto_unlog_timer = _bind_deps(
        _core_tmdb_flow._cancel_tmdb_quality_auto_unlog_timer,
        root=root,
        tmdb_quality_auto_unlog_after_id=tmdb_quality_auto_unlog_after_id,
    )

    _schedule_tmdb_quality_auto_expire = _bind_deps(
        _core_tmdb_flow._schedule_tmdb_quality_auto_expire,
        TMDB_QUALITY_UNLOG_WINDOW_S=TMDB_QUALITY_UNLOG_WINDOW_S,
        _cancel_tmdb_quality_auto_unlog_timer=_cancel_tmdb_quality_auto_unlog_timer,
        root=root,
        skip_cache=skip_cache,
        tmdb_quality_auto_unlog_after_id=tmdb_quality_auto_unlog_after_id,
        tmdb_quality_error_flag=tmdb_quality_error_flag,
    )

    _apply_rawtitle_text_tt_fallback = _bind_deps(
        _core_tmdb_flow._apply_rawtitle_text_tt_fallback,
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        apple_tv_auto_state=apple_tv_auto_state,
        tmdb_logo_app_fallback_active=tmdb_logo_app_fallback_active,
    )

    _tmdb_match_tier_acceptable = _core_tmdb_flow._tmdb_match_tier_acceptable

    _refresh_match_quality_glance_label = _core_tmdb_flow._refresh_match_quality_glance_label

    _adjust_tmdb_quality_failure_delta = _bind_deps(
        _core_tmdb_flow._adjust_tmdb_quality_failure_delta,
        _PIGEON_EXT=_PIGEON_EXT,
        _refresh_match_quality_glance_label=_refresh_match_quality_glance_label,
        match_quality_glance_sig=match_quality_glance_sig,
    )

    _clear_tmdb_quality_flag = _bind_deps(
        _core_tmdb_flow._clear_tmdb_quality_flag,
        _adjust_tmdb_quality_failure_delta=_adjust_tmdb_quality_failure_delta,
        _cancel_tmdb_quality_auto_unlog_timer=_cancel_tmdb_quality_auto_unlog_timer,
        _trigger_tmdb_quality_toggle_overlay=_trigger_tmdb_quality_toggle_overlay,
        skip_cache=skip_cache,
        tmdb_quality_error_flag=tmdb_quality_error_flag,
    )

    on_reset_tmdb_match_quality_stats = _bind_deps(
        _core_tmdb_flow.on_reset_tmdb_match_quality_stats,
        _PIGEON_EXT=_PIGEON_EXT,
        _refresh_match_quality_glance_label=_refresh_match_quality_glance_label,
        match_quality_glance_sig=match_quality_glance_sig,
    )

    _refresh_content_indicator = _bind_deps(
        _core_settings_ui._refresh_content_indicator,
        _content_indicator_ok=_content_indicator_ok,
        _paint_boolean_led=_paint_boolean_led,
        _refresh_match_quality_glance_label=_refresh_match_quality_glance_label,
        content_indicator_cv_holder=content_indicator_cv_holder,
    )

    _paint_pair_led = _bind_deps(
        _core_settings_ui._paint_pair_led,
        pairing_led_holder=pairing_led_holder,
    )

    ctx.TMDB_ERROR_FLAG_RETRY_RULES = TMDB_ERROR_FLAG_RETRY_RULES
    ctx.TMDB_QUALITY_UNLOG_WINDOW_S = TMDB_QUALITY_UNLOG_WINDOW_S
    ctx._adjust_tmdb_quality_failure_delta = _adjust_tmdb_quality_failure_delta
    ctx._advanced_feature_pipeline_ok = _advanced_feature_pipeline_ok
    ctx._append_tmdb_quality_event_report_log = _append_tmdb_quality_event_report_log
    ctx._blend_tmdb_quality_flag_badge = _blend_tmdb_quality_flag_badge
    ctx._blend_tmdb_quality_toggle_overlay = _blend_tmdb_quality_toggle_overlay
    ctx._clear_displayed_tmdb_art_for_content_change = _clear_displayed_tmdb_art_for_content_change
    ctx._clear_tmdb_quality_flag = _clear_tmdb_quality_flag
    ctx._last_adv_shift_tab_mono = _last_adv_shift_tab_mono
    ctx._last_command_submit_mono = _last_command_submit_mono
    ctx._last_space_mono = _last_space_mono
    ctx._last_tmdb_hotkey_mono = _last_tmdb_hotkey_mono
    ctx._last_tmdb_match_toggle_mono = _last_tmdb_match_toggle_mono
    ctx._last_tmdb_quality_report_mono = _last_tmdb_quality_report_mono
    ctx._mark_tmdb_missing_art = _mark_tmdb_missing_art
    ctx._paint_pair_led = _paint_pair_led
    ctx._refresh_content_indicator = _refresh_content_indicator
    ctx._refresh_match_quality_glance_label = _refresh_match_quality_glance_label
    ctx._schedule_tmdb_quality_auto_expire = _schedule_tmdb_quality_auto_expire
    ctx._tmdb_quality_toggle_overlay_state = _tmdb_quality_toggle_overlay_state
    ctx._trigger_tmdb_quality_toggle_overlay = _trigger_tmdb_quality_toggle_overlay
    ctx.apply_saved_tmdb_backdrop_to_display = apply_saved_tmdb_backdrop_to_display
    ctx.command_bar = command_bar
    ctx.command_entry = command_entry
    ctx.command_entry_visible = command_entry_visible
    ctx.hide_command_entry = hide_command_entry
    ctx.on_click_focus = on_click_focus
    ctx.on_ctrl_tab = on_ctrl_tab
    ctx.on_double_click_scene = on_double_click_scene
    ctx.on_f10_key = on_f10_key
    ctx.on_reset_tmdb_match_quality_stats = on_reset_tmdb_match_quality_stats
    ctx.on_s_key = on_s_key
    ctx.on_shift_tab_dev_cycle = on_shift_tab_dev_cycle
    ctx.on_tab_key = on_tab_key
    ctx.parse_tmdb_command_phrase = parse_tmdb_command_phrase
    ctx.quit_app = quit_app
    ctx.show_command_entry = show_command_entry
    ctx.spawn_tmdb_poster_fetch = spawn_tmdb_poster_fetch
    ctx.tmdb_error_flag_retry_active = tmdb_error_flag_retry_active
    ctx.tmdb_error_flag_retry_rule_idx = tmdb_error_flag_retry_rule_idx
    ctx.tmdb_quality_error_flag = tmdb_quality_error_flag
    ctx.tmdb_quality_flag_set_mono = tmdb_quality_flag_set_mono
    ctx.toggle_play = toggle_play
    ctx.toggle_scene = toggle_scene
    ctx.try_cycle_dev_phase = try_cycle_dev_phase
