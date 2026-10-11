"""Boot phase: overlay widgets (clock, TMDb logo, status bar, playback overlay, circles, main settings) and splash warm-up.

Phase 7 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from pathlib import Path
from pigeon.core import device_control as _core_device_control
from pigeon.core import now_playing as _core_now_playing
from pigeon.core import saver_state as _core_saver_state
from pigeon.core import settings_ui as _core_settings_ui
from pigeon.core import stage_render as _core_stage_render
from pigeon.core import startup as _core_startup
from pigeon.core import view_one as _core_view_one
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.core.binding import late as _late
from pigeon.tmdb_tt_contrast import GRADIENT_BGR_DARK
from pigeon.version import version_string


def run(ctx) -> None:
    APP_LOGO_FALLBACK_MAX_RESOLUTION_FRACTION = ctx.APP_LOGO_FALLBACK_MAX_RESOLUTION_FRACTION
    BACKDROP_BRIGHTNESS = ctx.BACKDROP_BRIGHTNESS
    CLOCK_SAVER_METADATA_IDLE_AFTER_S = ctx.CLOCK_SAVER_METADATA_IDLE_AFTER_S
    CLOCK_WIDGET_ROW = ctx.CLOCK_WIDGET_ROW
    ClockCalendarWidget = ctx.ClockCalendarWidget
    DevPhase = ctx.DevPhase
    DisplayView = ctx.DisplayView
    INFO_CLUSTER_CLOCK_ROW_1BASED = ctx.INFO_CLUSTER_CLOCK_ROW_1BASED
    INFO_CLUSTER_COL_RIGHT = ctx.INFO_CLUSTER_COL_RIGHT
    LANDING_DISPLAY_BRIGHTNESS = ctx.LANDING_DISPLAY_BRIGHTNESS
    MainSettingsWidget = ctx.MainSettingsWidget
    PlaybackOverlayWidget = ctx.PlaybackOverlayWidget
    StatusBarWidget = ctx.StatusBarWidget
    TMDB_LOGO_ANCHOR_ROW = ctx.TMDB_LOGO_ANCHOR_ROW
    TMDB_LOGO_FIT_SCALE = ctx.TMDB_LOGO_FIT_SCALE
    TMDB_LOGO_SPAN_H = ctx.TMDB_LOGO_SPAN_H
    TMDB_LOGO_SPAN_W = ctx.TMDB_LOGO_SPAN_W
    TMDB_LOGO_TOP_RIGHT_COL = ctx.TMDB_LOGO_TOP_RIGHT_COL
    TMDB_LOGO_VIEW6_ANCHOR_COL = ctx.TMDB_LOGO_VIEW6_ANCHOR_COL
    TMDB_LOGO_VIEW6_ANCHOR_ROW = ctx.TMDB_LOGO_VIEW6_ANCHOR_ROW
    TMDB_LOGO_VIEW6_FIT_SCALE = ctx.TMDB_LOGO_VIEW6_FIT_SCALE
    TMDB_LOGO_VIEW6_SPAN_H = ctx.TMDB_LOGO_VIEW6_SPAN_H
    TMDB_LOGO_VIEW6_SPAN_W = ctx.TMDB_LOGO_VIEW6_SPAN_W
    TRT_DISPLAY_ROW = ctx.TRT_DISPLAY_ROW
    TRT_LABEL_SPAN_H = ctx.TRT_LABEL_SPAN_H
    TRT_LABEL_SPAN_W = ctx.TRT_LABEL_SPAN_W
    TRT_PLAYED_COL = ctx.TRT_PLAYED_COL
    TRT_PLAYED_TEXT = ctx.TRT_PLAYED_TEXT
    TRT_REMAINING_COL = ctx.TRT_REMAINING_COL
    TRT_REMAINING_TEXT = ctx.TRT_REMAINING_TEXT
    TmdbLogoWidget = ctx.TmdbLogoWidget
    VIEW_ONE_BADGE_COL_RIGHT = ctx.VIEW_ONE_BADGE_COL_RIGHT
    VIEW_ONE_CLOCK_COL_RIGHT = ctx.VIEW_ONE_CLOCK_COL_RIGHT
    ViewCirclesWidget = ctx.ViewCirclesWidget
    _PIGEON_EXT = ctx._PIGEON_EXT
    _PROJECT_DIR = ctx._PROJECT_DIR
    _app_startup_mono = ctx._app_startup_mono
    _apple_tv_is_off = ctx._apple_tv_is_off
    _apply_position_stall_grace_to_clock_saver = ctx._apply_position_stall_grace_to_clock_saver
    _atv_metadata_is_content_idle = ctx._atv_metadata_is_content_idle
    _boot_clock_saver_until_playback = ctx._boot_clock_saver_until_playback
    _clock_saver_content_is_idle = ctx._clock_saver_content_is_idle
    _clock_saver_for_compose = ctx._clock_saver_for_compose
    _clock_saver_idle_need = ctx._clock_saver_idle_need
    _clock_saver_user_enabled = ctx._clock_saver_user_enabled
    _clock_saver_volume_raw = ctx._clock_saver_volume_raw
    _cs_meta_idle_log_mono = ctx._cs_meta_idle_log_mono
    _cs_meta_idle_was_active = ctx._cs_meta_idle_was_active
    _effective_display_view = ctx._effective_display_view
    _format_hmmss = ctx._format_hmmss
    _has_playback_position = ctx._has_playback_position
    _metadata_drives_clock_saver = ctx._metadata_drives_clock_saver
    _metadata_is_netflix_app = ctx._metadata_is_netflix_app
    _nav_coalescer_holder = ctx._nav_coalescer_holder
    _note_metadata_activity = ctx._note_metadata_activity
    _np_dump_mono = ctx._np_dump_mono
    _np_state_sync_mono = ctx._np_state_sync_mono
    _pausesaver_is_holding = ctx._pausesaver_is_holding
    _post_splash_startup_hook = ctx._post_splash_startup_hook
    _program_audio_session = ctx._program_audio_session
    _refresh_paused_row_stamp = ctx._refresh_paused_row_stamp
    _save_persisted_scene_enabled = ctx._save_persisted_scene_enabled
    _show_paused_row_overlay = ctx._show_paused_row_overlay
    _something_playing_now = ctx._something_playing_now
    _splash_reveal_clock = ctx._splash_reveal_clock
    _startup_splash_complete = ctx._startup_splash_complete
    _sync_preferences_now_playing_progress = ctx._sync_preferences_now_playing_progress
    _tmdb_info_current_and_available = ctx._tmdb_info_current_and_available
    active_tmdb_display_title = ctx.active_tmdb_display_title
    active_tmdb_title_key = ctx.active_tmdb_title_key
    apple_tv_auto_state = ctx.apple_tv_auto_state
    apple_tv_playback_clock = ctx.apple_tv_playback_clock
    backdrop_app_logo_letterbox_fit = ctx.backdrop_app_logo_letterbox_fit
    backdrop_master_bgr = ctx.backdrop_master_bgr
    brightness_current = ctx.brightness_current
    brightness_from = ctx.brightness_from
    brightness_t0 = ctx.brightness_t0
    brightness_target = ctx.brightness_target
    cap = ctx.cap
    clock_saver_composite_bgra = ctx.clock_saver_composite_bgra
    compose_playback_volume_widget_line = ctx.compose_playback_volume_widget_line
    current_apple_tv = ctx.current_apple_tv
    denon_vol_cache = ctx.denon_vol_cache
    dev_phase = ctx.dev_phase
    display_dims = ctx.display_dims
    display_view_holder = ctx.display_view_holder
    last_clock_saver_significant_device_mono = ctx.last_clock_saver_significant_device_mono
    last_frame = ctx.last_frame
    last_metadata_activity_mono = ctx.last_metadata_activity_mono
    last_pigeon_user_activity_mono = ctx.last_pigeon_user_activity_mono
    main_settings_widget_holder = ctx.main_settings_widget_holder
    playing = ctx.playing
    receiver_overlay_state = ctx.receiver_overlay_state
    receiver_standby_holder = ctx.receiver_standby_holder
    root = ctx.root
    saved_backdrop_app_logo_letterbox_fit = ctx.saved_backdrop_app_logo_letterbox_fit
    saved_backdrop_master_bgr = ctx.saved_backdrop_master_bgr
    scaled_display = ctx.scaled_display
    scaled_version = ctx.scaled_version
    scene_enabled = ctx.scene_enabled
    skip_cache = ctx.skip_cache
    startup_ph = ctx.startup_ph
    streaming_badge_state = ctx.streaming_badge_state
    streaming_slot_holder = ctx.streaming_slot_holder
    tmdb_logo_patch_bgra = ctx.tmdb_logo_patch_bgra
    use_backdrop_scene = ctx.use_backdrop_scene
    view_circles_widget_holder = ctx.view_circles_widget_holder

    clock_widget = (
        ClockCalendarWidget(
            anchor_row=CLOCK_WIDGET_ROW,
            anchor_col_right=float(VIEW_ONE_CLOCK_COL_RIGHT),
        )
        if _PIGEON_EXT and ClockCalendarWidget is not None
        else None
    )
    info_cluster_clock_widget = (
        ClockCalendarWidget(
            anchor_row=float(INFO_CLUSTER_CLOCK_ROW_1BASED),
            anchor_col_right=float(INFO_CLUSTER_COL_RIGHT),
            placement="overlay",
        )
        if _PIGEON_EXT and ClockCalendarWidget is not None
        else None
    )
    tmdb_logo_widget = (
        TmdbLogoWidget(
            anchor_row=TMDB_LOGO_ANCHOR_ROW,
            anchor_col=0,
            span_wide=TMDB_LOGO_SPAN_W,
            span_tall=TMDB_LOGO_SPAN_H,
            fit_scale=TMDB_LOGO_FIT_SCALE,
            vertical_align="top",
            top_right_col_1based=float(TMDB_LOGO_TOP_RIGHT_COL),
        )
        if _PIGEON_EXT and TmdbLogoWidget is not None
        else None
    )
    tmdb_logo_widget_view_six = (
        TmdbLogoWidget(
            anchor_row=TMDB_LOGO_VIEW6_ANCHOR_ROW,
            anchor_col=TMDB_LOGO_VIEW6_ANCHOR_COL,
            span_wide=TMDB_LOGO_VIEW6_SPAN_W,
            span_tall=TMDB_LOGO_VIEW6_SPAN_H,
            fit_scale=TMDB_LOGO_VIEW6_FIT_SCALE,
            vertical_align="center",
        )
        if _PIGEON_EXT and TmdbLogoWidget is not None
        else None
    )
    # When TMDb returns no match for the current playback title, surface the streaming
    # app's own logo in the content-logo slot instead of popping an error dialog.
    # ``_warm_tmdb_logo_patch`` consults this flag whenever no TMDb logo is active.
    tmdb_logo_app_fallback_active: list[bool] = [False]
    # Contrast-aware bottom gradient tint: ``_warm_tmdb_logo_patch`` evaluates the active
    # TT logo via ``pigeon.tmdb_tt_contrast.pick_gradient_bgr`` and stores the winning
    # ``(B, G, R)`` here. Default black preserves legacy behaviour when no TT is loaded.
    tmdb_tt_gradient_bgr_holder: list[tuple[int, int, int]] = [GRADIENT_BGR_DARK]
    status_bar_widget = (
        StatusBarWidget(
            assets_dir=Path(_PROJECT_DIR) / "pigeonAssets",
            trt_row=TRT_DISPLAY_ROW,
            trt_played_col=TRT_PLAYED_COL,
            trt_remaining_col=TRT_REMAINING_COL,
            trt_played_text=TRT_PLAYED_TEXT,
            trt_remaining_text=TRT_REMAINING_TEXT,
            trt_label_span_wide=TRT_LABEL_SPAN_W,
            trt_label_span_tall=TRT_LABEL_SPAN_H,
        )
        if _PIGEON_EXT and StatusBarWidget is not None
        else None
    )

    receiver_debug_holder: list[dict[str, str]] = [{}]

    _receiver_audio_fallback = _core_device_control._receiver_audio_fallback


    _resolve_receiver_lines_for_now_playing = _bind_deps(
        _core_device_control._resolve_receiver_lines_for_now_playing,
        _clock_saver_volume_raw=_clock_saver_volume_raw,
        _receiver_audio_fallback=_receiver_audio_fallback,
        apple_tv_auto_state=apple_tv_auto_state,
        compose_playback_volume_widget_line=compose_playback_volume_widget_line,
        denon_vol_cache=denon_vol_cache,
        receiver_overlay_state=receiver_overlay_state,
        receiver_standby_holder=receiver_standby_holder,
        streaming_slot_holder=streaming_slot_holder,
    )
    ctx._resolve_receiver_lines_for_now_playing = _resolve_receiver_lines_for_now_playing

    _clock_saver_active = _bind_deps(
        _core_saver_state._clock_saver_active,
        CLOCK_SAVER_METADATA_IDLE_AFTER_S=CLOCK_SAVER_METADATA_IDLE_AFTER_S,
        DevPhase=DevPhase,
        _apple_tv_is_off=_apple_tv_is_off,
        _apply_position_stall_grace_to_clock_saver=_apply_position_stall_grace_to_clock_saver,
        _boot_clock_saver_until_playback=_boot_clock_saver_until_playback,
        _clock_saver_content_is_idle=_clock_saver_content_is_idle,
        _clock_saver_idle_need=_clock_saver_idle_need,
        _clock_saver_user_enabled=_clock_saver_user_enabled,
        _cs_meta_idle_log_mono=_cs_meta_idle_log_mono,
        _cs_meta_idle_was_active=_cs_meta_idle_was_active,
        _metadata_drives_clock_saver=_metadata_drives_clock_saver,
        _note_metadata_activity=_note_metadata_activity,
        _pausesaver_is_holding=_pausesaver_is_holding,
        _program_audio_session=_program_audio_session,
        _refresh_paused_row_stamp=_refresh_paused_row_stamp,
        _resolve_receiver_lines_for_now_playing=_resolve_receiver_lines_for_now_playing,
        _something_playing_now=_something_playing_now,
        _splash_reveal_clock=_splash_reveal_clock,
        _tmdb_info_current_and_available=_tmdb_info_current_and_available,
        apple_tv_playback_clock=apple_tv_playback_clock,
        clock_saver_composite_bgra=clock_saver_composite_bgra,
        dev_phase=dev_phase,
        last_clock_saver_significant_device_mono=last_clock_saver_significant_device_mono,
        last_metadata_activity_mono=last_metadata_activity_mono,
        last_pigeon_user_activity_mono=last_pigeon_user_activity_mono,
        receiver_standby_holder=receiver_standby_holder,
        scene_enabled=scene_enabled,
        startup_ph=startup_ph,
    )
    ctx._clock_saver_active = _clock_saver_active

    _resolve_receiver_input_label = _bind_deps(
        _core_device_control._resolve_receiver_input_label,
        receiver_overlay_state=receiver_overlay_state,
        receiver_standby_holder=receiver_standby_holder,
    )

    _np_widgets_content_active = _bind_deps(
        _core_now_playing._np_widgets_content_active,
        _apple_tv_is_off=_apple_tv_is_off,
        _atv_metadata_is_content_idle=_atv_metadata_is_content_idle,
        _program_audio_session=_program_audio_session,
        _show_paused_row_overlay=_show_paused_row_overlay,
        _something_playing_now=_something_playing_now,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
        receiver_standby_holder=receiver_standby_holder,
    )

    # Volume knob requested PWON; keep sending power-on even if a poll
    # briefly reports STANDBY again before the AVR finishes waking.
    receiver_power_on_pending: list[bool] = [False]
    receiver_power_on_until: list[float] = [0.0]
    playback_overlay_flags: dict[str, bool] = {
        "show_paused_row": False,
        "clock_saver_volume_only": False,
        "clock_saver_netflix_full_overlay": False,
        "badge_live_instead_of_logo": False,
    }
    playback_overlay_widget = (
        PlaybackOverlayWidget(
            assets_dir=Path(_PROJECT_DIR) / "pigeonAssets",
            receiver_state=receiver_overlay_state,
            service_badge=streaming_badge_state,
            overlay_flags=playback_overlay_flags,
            badge_top_right_col_1based=VIEW_ONE_BADGE_COL_RIGHT,
            volume_top_right_col_1based=float(VIEW_ONE_CLOCK_COL_RIGHT),
        )
        if _PIGEON_EXT and PlaybackOverlayWidget is not None
        else None
    )

    # Now-playing: five-zone circles skin only.
    view_circles_widget_holder[0] = (
        ViewCirclesWidget(assets_dir=Path(_PROJECT_DIR) / "pigeonAssets")
        if _PIGEON_EXT and ViewCirclesWidget is not None
        else None
    )
    if view_circles_widget_holder[0] is not None:
        try:
            from pigeon.widgets.preferences_settings import (
                ensure_now_playing_layout_defaults,
            )

            ensure_now_playing_layout_defaults()
        except Exception:
            pass
    main_settings_widget_holder[0] = (
        MainSettingsWidget(assets_dir=Path(_PROJECT_DIR) / "pigeonAssets")
        if _PIGEON_EXT and MainSettingsWidget is not None
        else None
    )
    if main_settings_widget_holder[0] is not None:
        try:
            main_settings_widget_holder[0].state.version_string = version_string()
            main_settings_widget_holder[0].state.update_local_version = version_string()
        except Exception:
            pass

    _view_one_uses_now_playing_screen = _bind_deps(
        _core_view_one._view_one_uses_now_playing_screen,
        DisplayView=DisplayView,
        _effective_display_view=_effective_display_view,
        view_circles_widget=view_circles_widget_holder[0],
    )
    ctx._view_one_uses_now_playing_screen = _view_one_uses_now_playing_screen

    _np_drawing_live_audio = _bind_deps(
        _core_now_playing._np_drawing_live_audio,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        view_circles_widget=view_circles_widget_holder[0],
    )

    _settings_is_native_1280 = _bind_deps(
        _core_settings_ui._settings_is_native_1280,
        DevPhase=DevPhase,
        dev_phase=dev_phase,
        main_settings_widget=main_settings_widget_holder[0],
    )

    _settings_menu_is_static = _bind_deps(
        _core_settings_ui._settings_menu_is_static,
        DevPhase=DevPhase,
        dev_phase=dev_phase,
        main_settings_widget=main_settings_widget_holder[0],
    )

    _composite_settings_on_canvas = _bind_deps(
        _core_settings_ui._composite_settings_on_canvas,
        _nav_coalescer_holder=_nav_coalescer_holder,
        _show_paused_row_overlay=_show_paused_row_overlay,
        _something_playing_now=_something_playing_now,
        _sync_now_playing_screen_state=_late(lambda: _sync_now_playing_screen_state, "_sync_now_playing_screen_state"),
        _sync_preferences_now_playing_progress=_sync_preferences_now_playing_progress,
        _sync_settings_zone2_tt=_late(lambda: ctx._sync_settings_zone2_tt, "_sync_settings_zone2_tt"),
        main_settings_widget=main_settings_widget_holder[0],
        view_circles_widget=view_circles_widget_holder[0],
    )

    _sync_now_playing_screen_state = _bind_deps(
        _core_now_playing._sync_now_playing_screen_state,
        DisplayView=DisplayView,
        _active_tmdb_tt_src_bgra=_late(lambda: ctx._active_tmdb_tt_src_bgra, "_active_tmdb_tt_src_bgra"),
        _atv_metadata_is_content_idle=_atv_metadata_is_content_idle,
        _circles_poster_bgra=_late(lambda: ctx._circles_poster_bgra, "_circles_poster_bgra"),
        _effective_display_view=_effective_display_view,
        _format_hmmss=_format_hmmss,
        _has_playback_position=_has_playback_position,
        _np_dump_mono=_np_dump_mono,
        _np_widgets_content_active=_np_widgets_content_active,
        _paused_screen_backdrop_bgr=_late(lambda: ctx._paused_screen_backdrop_bgr, "_paused_screen_backdrop_bgr"),
        _pausesaver_is_holding=_pausesaver_is_holding,
        _playback_extrapolated_pair=_late(lambda: ctx._playback_extrapolated_pair, "_playback_extrapolated_pair"),
        _playback_progress_fraction_for_bar=_late(lambda: ctx._playback_progress_fraction_for_bar, "_playback_progress_fraction_for_bar"),
        _refresh_paused_row_stamp=_refresh_paused_row_stamp,
        _resolve_receiver_input_label=_resolve_receiver_input_label,
        _resolve_receiver_lines_for_now_playing=_resolve_receiver_lines_for_now_playing,
        _show_paused_row_overlay=_show_paused_row_overlay,
        _spawn_youtube_thumb_fetch=_late(lambda: ctx._spawn_youtube_thumb_fetch, "_spawn_youtube_thumb_fetch"),
        _vv_is_music=_late(lambda: ctx._vv_is_music, "_vv_is_music"),
        _vv_is_youtube=_late(lambda: ctx._vv_is_youtube, "_vv_is_youtube"),
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
        receiver_standby_holder=receiver_standby_holder,
        skip_cache=skip_cache,
        streaming_badge_state=streaming_badge_state,
        view_circles_widget=view_circles_widget_holder[0],
    )

    _sync_now_playing_screen_state_for_frame = _bind_deps(
        _core_now_playing._sync_now_playing_screen_state_for_frame,
        _np_state_sync_mono=_np_state_sync_mono,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        view_circles_widget=view_circles_widget_holder[0],
    )

    _clear_now_playing_view_caches = _bind_deps(
        _core_now_playing._clear_now_playing_view_caches,
        view_circles_widget=view_circles_widget_holder[0],
    )

    _enable_now_playing_screen = _bind_deps(
        _core_now_playing._enable_now_playing_screen,
        DisplayView=DisplayView,
        LANDING_DISPLAY_BRIGHTNESS=LANDING_DISPLAY_BRIGHTNESS,
        _PIGEON_EXT=_PIGEON_EXT,
        _sync_status_bar_visibility_for_playback=_late(lambda: ctx._sync_status_bar_visibility_for_playback, "_sync_status_bar_visibility_for_playback"),
        apple_tv_auto_state=apple_tv_auto_state,
        brightness_current=brightness_current,
        brightness_from=brightness_from,
        brightness_target=brightness_target,
        display_view_holder=display_view_holder,
        last_frame=last_frame,
        scene_enabled=scene_enabled,
        skip_cache=skip_cache,
        view_circles_widget=view_circles_widget_holder[0],
    )

    _activate_now_playing_after_splash = _bind_deps(
        _core_startup._activate_now_playing_after_splash,
        _enable_now_playing_screen=_enable_now_playing_screen,
        _startup_splash_complete=_startup_splash_complete,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        skip_cache=skip_cache,
    )

    _post_splash_startup_hook[0] = _activate_now_playing_after_splash

    _splash_view_one_warm_done: list[bool] = [False]

    _log_view_one_startup_phase = _bind_deps(
        _core_view_one._log_view_one_startup_phase,
        _app_startup_mono=_app_startup_mono,
    )

    _warm_view_one_splash_chrome_only = _bind_deps(
        _core_startup._warm_view_one_splash_chrome_only,
        DisplayView=DisplayView,
        _PIGEON_EXT=_PIGEON_EXT,
        _log_view_one_startup_phase=_log_view_one_startup_phase,
        display_view_holder=display_view_holder,
        root=root,
        view_circles_widget=view_circles_widget_holder[0],
    )

    root.after(150, lambda: _warm_view_one_splash_chrome_only(phase="chrome-early"))

    _playback_is_netflix_stream = _bind_deps(
        _core_now_playing._playback_is_netflix_stream,
        _metadata_is_netflix_app=_metadata_is_netflix_app,
        apple_tv_auto_state=apple_tv_auto_state,
        streaming_badge_state=streaming_badge_state,
    )

    _backdrop_master_from_streaming_app_logo = _bind_deps(
        _core_view_one._backdrop_master_from_streaming_app_logo,
        APP_LOGO_FALLBACK_MAX_RESOLUTION_FRACTION=APP_LOGO_FALLBACK_MAX_RESOLUTION_FRACTION,
        _PROJECT_DIR=_PROJECT_DIR,
        _metadata_is_netflix_app=_metadata_is_netflix_app,
        apple_tv_auto_state=apple_tv_auto_state,
        display_dims=display_dims,
        streaming_badge_state=streaming_badge_state,
    )

    _apply_netflix_backdrop_when_running = _bind_deps(
        _core_stage_render._apply_netflix_backdrop_when_running,
        BACKDROP_BRIGHTNESS=BACKDROP_BRIGHTNESS,
        _backdrop_master_from_streaming_app_logo=_backdrop_master_from_streaming_app_logo,
        _playback_is_netflix_stream=_playback_is_netflix_stream,
        _save_persisted_scene_enabled=_save_persisted_scene_enabled,
        _warm_status_bar_blits=_late(lambda: ctx._warm_status_bar_blits, "_warm_status_bar_blits"),
        _warm_tmdb_logo_patch=_late(lambda: ctx._warm_tmdb_logo_patch, "_warm_tmdb_logo_patch"),
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        backdrop_app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit,
        backdrop_master_bgr=backdrop_master_bgr,
        brightness_current=brightness_current,
        brightness_from=brightness_from,
        brightness_t0=brightness_t0,
        brightness_target=brightness_target,
        cap=cap,
        current_apple_tv=current_apple_tv,
        last_frame=last_frame,
        playing=playing,
        saved_backdrop_app_logo_letterbox_fit=saved_backdrop_app_logo_letterbox_fit,
        saved_backdrop_master_bgr=saved_backdrop_master_bgr,
        scaled_display=scaled_display,
        scaled_version=scaled_version,
        scene_enabled=scene_enabled,
        skip_cache=skip_cache,
        status_bar_widget=status_bar_widget,
        streaming_badge_state=streaming_badge_state,
        tmdb_logo_app_fallback_active=tmdb_logo_app_fallback_active,
        tmdb_logo_patch_bgra=tmdb_logo_patch_bgra,
        tmdb_logo_widget=tmdb_logo_widget,
        tmdb_logo_widget_view_six=tmdb_logo_widget_view_six,
        use_backdrop_scene=use_backdrop_scene,
    )

    ctx._apply_netflix_backdrop_when_running = _apply_netflix_backdrop_when_running
    ctx._backdrop_master_from_streaming_app_logo = _backdrop_master_from_streaming_app_logo
    ctx._clear_now_playing_view_caches = _clear_now_playing_view_caches
    ctx._composite_settings_on_canvas = _composite_settings_on_canvas
    ctx._enable_now_playing_screen = _enable_now_playing_screen
    ctx._log_view_one_startup_phase = _log_view_one_startup_phase
    ctx._np_drawing_live_audio = _np_drawing_live_audio
    ctx._np_widgets_content_active = _np_widgets_content_active
    ctx._playback_is_netflix_stream = _playback_is_netflix_stream
    ctx._settings_is_native_1280 = _settings_is_native_1280
    ctx._settings_menu_is_static = _settings_menu_is_static
    ctx._splash_view_one_warm_done = _splash_view_one_warm_done
    ctx._sync_now_playing_screen_state = _sync_now_playing_screen_state
    ctx._sync_now_playing_screen_state_for_frame = _sync_now_playing_screen_state_for_frame
    ctx._warm_view_one_splash_chrome_only = _warm_view_one_splash_chrome_only
    ctx.clock_widget = clock_widget
    ctx.info_cluster_clock_widget = info_cluster_clock_widget
    ctx.playback_overlay_flags = playback_overlay_flags
    ctx.playback_overlay_widget = playback_overlay_widget
    ctx.receiver_power_on_pending = receiver_power_on_pending
    ctx.receiver_power_on_until = receiver_power_on_until
    ctx.receiver_debug_holder = receiver_debug_holder
    ctx.status_bar_widget = status_bar_widget
    ctx.tmdb_logo_app_fallback_active = tmdb_logo_app_fallback_active
    ctx.tmdb_logo_widget = tmdb_logo_widget
    ctx.tmdb_logo_widget_view_six = tmdb_logo_widget_view_six
    ctx.tmdb_tt_gradient_bgr_holder = tmdb_tt_gradient_bgr_holder
