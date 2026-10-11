"""Boot phase: receiver volume worker, GPIO / rotary / serial inputs, and settings navigation.

Phase 13 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from pigeon.core import device_control as _core_device_control
from pigeon.core import input_keys as _core_input_keys
from pigeon.core import saver_state as _core_saver_state
from pigeon.core import settings_ui as _core_settings_ui
from pigeon.core import stage_render as _core_stage_render
from pigeon.core import startup as _core_startup
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.core.binding import late as _late
import sys
import threading


def run(ctx) -> None:
    BACKDROP_BRIGHTNESS = ctx.BACKDROP_BRIGHTNESS
    DevPhase = ctx.DevPhase
    DisplayView = ctx.DisplayView
    RECEIVER_POLL_MS = ctx.RECEIVER_POLL_MS
    RECEIVER_VOLUME_POLL_MS = ctx.RECEIVER_VOLUME_POLL_MS
    SKIP_POST_SPLASH_STARTUP_TRANSITION = ctx.SKIP_POST_SPLASH_STARTUP_TRANSITION
    STARTUP_AUTO_RESTORE_SAVED_BACKDROP = ctx.STARTUP_AUTO_RESTORE_SAVED_BACKDROP
    STARTUP_PIGEON_WORDMARK_MAX_S = ctx.STARTUP_PIGEON_WORDMARK_MAX_S
    SceneFit = ctx.SceneFit
    THEATER_IDLE_DIM_ENABLED = ctx.THEATER_IDLE_DIM_ENABLED
    WINDOW_H = ctx.WINDOW_H
    WINDOW_W = ctx.WINDOW_W
    _PIGEON_EXT = ctx._PIGEON_EXT
    _app_logo_clock_saver_style_now = ctx._app_logo_clock_saver_style_now
    _apply_brightness = ctx._apply_brightness
    _atv_idle_monochrome_active = ctx._atv_idle_monochrome_active
    _audio_capture_wanted = ctx._audio_capture_wanted
    _backdrop_active_for_view = ctx._backdrop_active_for_view
    _bgr_to_tk_image = ctx._bgr_to_tk_image
    _black_screen_bgr = ctx._black_screen_bgr
    _blend_tmdb_quality_flag_badge = ctx._blend_tmdb_quality_flag_badge
    _blend_tmdb_quality_toggle_overlay = ctx._blend_tmdb_quality_toggle_overlay
    _blend_view_four_debug = ctx._blend_view_four_debug
    _bump_clock_saver_significant_device = ctx._bump_clock_saver_significant_device
    _bump_pigeon_user_activity = ctx._bump_pigeon_user_activity
    _clock_saver_for_compose = ctx._clock_saver_for_compose
    _clock_saver_receiver_off = ctx._clock_saver_receiver_off
    _clock_saver_volume = ctx._clock_saver_volume
    _clock_saver_volume_raw = ctx._clock_saver_volume_raw
    _clock_startup_intro_opacity = ctx._clock_startup_intro_opacity
    _compose_idle_strength_holder = ctx._compose_idle_strength_holder
    _compose_shown_frame = ctx._compose_shown_frame
    _effective_display_view = ctx._effective_display_view
    _idle_audio_listen = ctx._idle_audio_listen
    _idle_audio_meter_active = ctx._idle_audio_meter_active
    _location_toast_alpha = ctx._location_toast_alpha
    _maybe_exit_settings_menus_on_idle = ctx._maybe_exit_settings_menus_on_idle
    _nav_coalescer_holder = ctx._nav_coalescer_holder
    _nav_request = ctx._nav_request
    _note_volume_graphics = ctx._note_volume_graphics
    _note_zone3_volume_takeover = ctx._note_zone3_volume_takeover
    _np_drawing_live_audio = ctx._np_drawing_live_audio
    _np_wants_live_audio = ctx._np_wants_live_audio
    _on_rotary_action = ctx._on_rotary_action
    _paint_boolean_led = ctx._paint_boolean_led
    _present_frame_to_display = ctx._present_frame_to_display
    _record_live_audio_timing = ctx._record_live_audio_timing
    _refresh_observed_pairing_led_rows = ctx._refresh_observed_pairing_led_rows
    _remember_clock_saver_volume = ctx._remember_clock_saver_volume
    _render_after_id = ctx._render_after_id
    _send_player_play_pause_hotkey = ctx._send_player_play_pause_hotkey
    _set_playback_overlay_clock_saver_volume_flag = ctx._set_playback_overlay_clock_saver_volume_flag
    _settings_audio_led_listen = ctx._settings_audio_led_listen
    _settings_menu_is_static = ctx._settings_menu_is_static
    _show_paused_row_overlay = ctx._show_paused_row_overlay
    _splash_underlay_bgr = ctx._splash_underlay_bgr
    _startup_splash_complete = ctx._startup_splash_complete
    _sync_now_playing_screen_state = ctx._sync_now_playing_screen_state
    _sync_streaming_badge_from_playback_sources = ctx._sync_streaming_badge_from_playback_sources
    _tmdb_quality_toggle_overlay_state = ctx._tmdb_quality_toggle_overlay_state
    _update_idle_dim_strength = ctx._update_idle_dim_strength
    _update_label_photo_from_bgr = ctx._update_label_photo_from_bgr
    _view_one_uses_now_playing_screen = ctx._view_one_uses_now_playing_screen
    _volume_lines = ctx._volume_lines
    _warm_playback_overlay_blits = ctx._warm_playback_overlay_blits
    _warm_status_bar_blits = ctx._warm_status_bar_blits
    _warm_view_one_under_splash = ctx._warm_view_one_under_splash
    apple_tv_auto_state = ctx.apple_tv_auto_state
    apple_tv_busy = ctx.apple_tv_busy
    apply_saved_tmdb_backdrop_to_display = ctx.apply_saved_tmdb_backdrop_to_display
    avr_slot_holder = ctx.avr_slot_holder
    backdrop_app_logo_letterbox_fit = ctx.backdrop_app_logo_letterbox_fit
    backdrop_master_bgr = ctx.backdrop_master_bgr
    black_photo = ctx.black_photo
    brightness_current = ctx.brightness_current
    brightness_duration_s = ctx.brightness_duration_s
    brightness_from = ctx.brightness_from
    brightness_t0 = ctx.brightness_t0
    brightness_target = ctx.brightness_target
    clock_saver_force_on = ctx.clock_saver_force_on
    clock_saver_peek_until_mono = ctx.clock_saver_peek_until_mono
    current_apple_tv = ctx.current_apple_tv
    denon_vol_cache = ctx.denon_vol_cache
    dev_phase = ctx.dev_phase
    display_dims = ctx.display_dims
    display_view_holder = ctx.display_view_holder
    fit_holder = ctx.fit_holder
    frame_interval_ms = ctx.frame_interval_ms
    label = ctx.label
    label_live_photo = ctx.label_live_photo
    last_frame = ctx.last_frame
    latest_meter_cache_key = ctx.latest_meter_cache_key
    latest_visualizer_cache_key = ctx.latest_visualizer_cache_key
    lerp_bgr_red_monochrome = ctx.lerp_bgr_red_monochrome
    main_settings_widget_holder = ctx.main_settings_widget_holder
    paused_interval_ms = ctx.paused_interval_ms
    playback_overlay_flags = ctx.playback_overlay_flags
    playing = ctx.playing
    post_splash_mono = ctx.post_splash_mono
    receiver_http_host = ctx.receiver_http_host
    receiver_overlay_state = ctx.receiver_overlay_state
    receiver_panel_led_holder = ctx.receiver_panel_led_holder
    receiver_poll_busy = ctx.receiver_poll_busy
    receiver_power_on_pending = ctx.receiver_power_on_pending
    receiver_power_on_until = ctx.receiver_power_on_until
    receiver_standby_holder = ctx.receiver_standby_holder
    receiver_debug_holder = ctx.receiver_debug_holder
    root = ctx.root
    saved_backdrop_master_bgr = ctx.saved_backdrop_master_bgr
    scaled_display = ctx.scaled_display
    scaled_version = ctx.scaled_version
    scene_enabled = ctx.scene_enabled
    shell = ctx.shell
    skip_cache = ctx.skip_cache
    startup_ph = ctx.startup_ph
    status_bar_widget = ctx.status_bar_widget
    streaming_slot_holder = ctx.streaming_slot_holder
    sync_audio_meter_capture = ctx.sync_audio_meter_capture
    sync_developer_chrome = ctx.sync_developer_chrome
    tmdb_quality_error_flag = ctx.tmdb_quality_error_flag
    use_backdrop_scene = ctx.use_backdrop_scene
    view_circles_widget_holder = ctx.view_circles_widget_holder
    view_five_mode_holder = ctx.view_five_mode_holder
    view_four_subview_holder = ctx.view_four_subview_holder
    view_one_layout_holder = ctx.view_one_layout_holder

    _volume_rotary_fail_log_count = [0]
    _volume_rotary_ok_log_count = [0]
    # The adapter keeps one replaceable volume intent per receiver; Pigeon only
    # registers callbacks on the receiver link.
    from pigeon.receiver_link import get_receiver_link

    _register_receiver_callbacks = _bind_deps(
        _core_device_control._register_receiver_callbacks,
        _clock_saver_volume=_clock_saver_volume,
        _note_volume_graphics=_note_volume_graphics,
        _volume_rotary_fail_log_count=_volume_rotary_fail_log_count,
        _volume_rotary_ok_log_count=_volume_rotary_ok_log_count,
        denon_vol_cache=denon_vol_cache,
        receiver_overlay_state=receiver_overlay_state,
        receiver_power_on_pending=receiver_power_on_pending,
        receiver_standby_holder=receiver_standby_holder,
        render_once=_late(lambda: render_once, "render_once"),
        root=root,
    )
    _register_receiver_callbacks()

    _queue_receiver_volume_action = _bind_deps(
        _core_device_control._queue_receiver_volume_action,
        avr_slot_holder=avr_slot_holder,
        receiver_power_on_pending=receiver_power_on_pending,
    )

    _nudge_clock_saver_volume = _bind_deps(
        _core_saver_state._nudge_clock_saver_volume,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _clock_saver_volume=_clock_saver_volume,
        _clock_saver_volume_raw=_clock_saver_volume_raw,
        _note_volume_graphics=_note_volume_graphics,
        _note_zone3_volume_takeover=_note_zone3_volume_takeover,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        clock_saver_force_on=clock_saver_force_on,
        denon_vol_cache=denon_vol_cache,
        receiver_overlay_state=receiver_overlay_state,
        render_once=_late(lambda: render_once, "render_once"),
        skip_cache=skip_cache,
    )

    _on_volume_rotary_action = _bind_deps(
        _core_input_keys._on_volume_rotary_action,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _note_zone3_volume_takeover=_note_zone3_volume_takeover,
        _nudge_clock_saver_volume=_nudge_clock_saver_volume,
        _queue_receiver_volume_action=_queue_receiver_volume_action,
        _volume_rotary_fail_log_count=_volume_rotary_fail_log_count,
        apple_tv_busy=apple_tv_busy,
        current_apple_tv=current_apple_tv,
        receiver_power_on_pending=receiver_power_on_pending,
        receiver_power_on_until=receiver_power_on_until,
        receiver_standby_holder=receiver_standby_holder,
        streaming_slot_holder=streaming_slot_holder,
    )

    _play_pause_gpio_last_mono = [0.0]

    _on_play_pause_gpio_action = _bind_deps(
        _core_input_keys._on_play_pause_gpio_action,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _play_pause_gpio_last_mono=_play_pause_gpio_last_mono,
        _send_player_play_pause_hotkey=_send_player_play_pause_hotkey,
    )

    try:
        from pigeon.rotary_serial import start_rotary_serial_listener

        start_rotary_serial_listener(
            root,
            on_action=_on_rotary_action,
            on_volume_action=_on_volume_rotary_action,
            on_play_pause_action=_on_play_pause_gpio_action,
        )
    except Exception as _rotary_exc:
        sys.stderr.write(f"pigeon: rotary_serial: not started: {_rotary_exc}\n")
        sys.stderr.flush()

    _apply_shell_size = _bind_deps(
        _core_stage_render._apply_shell_size,
        SceneFit=SceneFit,
        _PIGEON_EXT=_PIGEON_EXT,
        _app_logo_clock_saver_style_now=_app_logo_clock_saver_style_now,
        backdrop_app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit,
        backdrop_master_bgr=backdrop_master_bgr,
        black_photo=black_photo,
        display_dims=display_dims,
        fit_holder=fit_holder,
        scaled_display=scaled_display,
        scaled_version=scaled_version,
        skip_cache=skip_cache,
        sync_developer_chrome=sync_developer_chrome,
        use_backdrop_scene=use_backdrop_scene,
    )

    _on_shell_configure = _bind_deps(
        _core_input_keys._on_shell_configure,
        _apply_shell_size=_apply_shell_size,
        shell=shell,
    )

    sync_developer_chrome()

    render_once = _bind_deps(
        _core_stage_render.render_once,
        BACKDROP_BRIGHTNESS=BACKDROP_BRIGHTNESS,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        SKIP_POST_SPLASH_STARTUP_TRANSITION=SKIP_POST_SPLASH_STARTUP_TRANSITION,
        STARTUP_AUTO_RESTORE_SAVED_BACKDROP=STARTUP_AUTO_RESTORE_SAVED_BACKDROP,
        STARTUP_PIGEON_WORDMARK_MAX_S=STARTUP_PIGEON_WORDMARK_MAX_S,
        THEATER_IDLE_DIM_ENABLED=THEATER_IDLE_DIM_ENABLED,
        _PIGEON_EXT=_PIGEON_EXT,
        _apply_brightness=_apply_brightness,
        _atv_idle_monochrome_active=_atv_idle_monochrome_active,
        _audio_capture_wanted=_audio_capture_wanted,
        _backdrop_active_for_view=_backdrop_active_for_view,
        _bgr_to_tk_image=_bgr_to_tk_image,
        _black_screen_bgr=_black_screen_bgr,
        _blend_tmdb_quality_flag_badge=_blend_tmdb_quality_flag_badge,
        _blend_tmdb_quality_toggle_overlay=_blend_tmdb_quality_toggle_overlay,
        _blend_view_four_debug=_blend_view_four_debug,
        _capture_splash_underlay=_late(lambda: _capture_splash_underlay, "_capture_splash_underlay"),
        _clock_saver_for_compose=_clock_saver_for_compose,
        _clock_saver_volume_raw=_clock_saver_volume_raw,
        _clock_startup_intro_opacity=_clock_startup_intro_opacity,
        _compose_idle_strength_holder=_compose_idle_strength_holder,
        _compose_shown_frame=_compose_shown_frame,
        _effective_display_view=_effective_display_view,
        _idle_audio_listen=_idle_audio_listen,
        _idle_audio_meter_active=_idle_audio_meter_active,
        _location_toast_alpha=_location_toast_alpha,
        _maybe_exit_settings_menus_on_idle=_maybe_exit_settings_menus_on_idle,
        _np_drawing_live_audio=_np_drawing_live_audio,
        _np_wants_live_audio=_np_wants_live_audio,
        _record_live_audio_timing=_record_live_audio_timing,
        _render_after_id=_render_after_id,
        _schedule_render_oneshot=_late(lambda: _schedule_render_oneshot, "_schedule_render_oneshot"),
        _set_playback_overlay_clock_saver_volume_flag=_set_playback_overlay_clock_saver_volume_flag,
        _settings_audio_led_listen=_settings_audio_led_listen,
        _settings_menu_is_static=_settings_menu_is_static,
        _show_paused_row_overlay=_show_paused_row_overlay,
        _startup_splash_complete=_startup_splash_complete,
        _tmdb_quality_toggle_overlay_state=_tmdb_quality_toggle_overlay_state,
        _update_idle_dim_strength=_update_idle_dim_strength,
        _update_label_photo_from_bgr=_update_label_photo_from_bgr,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        _volume_lines=_volume_lines,
        _warm_playback_overlay_blits=_warm_playback_overlay_blits,
        _warm_status_bar_blits=_warm_status_bar_blits,
        apply_saved_tmdb_backdrop_to_display=apply_saved_tmdb_backdrop_to_display,
        backdrop_master_bgr=backdrop_master_bgr,
        black_photo=black_photo,
        brightness_current=brightness_current,
        brightness_duration_s=brightness_duration_s,
        brightness_from=brightness_from,
        brightness_t0=brightness_t0,
        brightness_target=brightness_target,
        clock_saver_peek_until_mono=clock_saver_peek_until_mono,
        dev_phase=dev_phase,
        display_dims=display_dims,
        display_view_holder=display_view_holder,
        frame_interval_ms=frame_interval_ms,
        label=label,
        label_live_photo=label_live_photo,
        last_frame=last_frame,
        latest_meter_cache_key=latest_meter_cache_key,
        latest_visualizer_cache_key=latest_visualizer_cache_key,
        lerp_bgr_red_monochrome=lerp_bgr_red_monochrome,
        main_settings_widget=main_settings_widget_holder[0],
        paused_interval_ms=paused_interval_ms,
        playback_overlay_flags=playback_overlay_flags,
        playing=playing,
        post_splash_mono=post_splash_mono,
        receiver_overlay_state=receiver_overlay_state,
        root=root,
        saved_backdrop_master_bgr=saved_backdrop_master_bgr,
        scaled_display=scaled_display,
        scaled_version=scaled_version,
        scene_enabled=scene_enabled,
        skip_cache=skip_cache,
        status_bar_widget=status_bar_widget,
        sync_audio_meter_capture=sync_audio_meter_capture,
        tmdb_quality_error_flag=tmdb_quality_error_flag,
        use_backdrop_scene=use_backdrop_scene,
        view_circles_widget=view_circles_widget_holder[0],
        view_five_mode_holder=view_five_mode_holder,
        view_four_subview_holder=view_four_subview_holder,
        view_one_layout_holder=view_one_layout_holder,
    )
    ctx.render_once = render_once

    _paint_coalesced_settings_nav = _bind_deps(
        _core_settings_ui._paint_coalesced_settings_nav,
        _nav_coalescer_holder=_nav_coalescer_holder,
        main_settings_widget=main_settings_widget_holder[0],
        render_once=render_once,
        skip_cache=skip_cache,
    )

    try:
        from pigeon.nav_coalesce import NavPaintCoalescer

        _nav_coalescer_holder[0] = NavPaintCoalescer(
            after_idle=root.after_idle,
            after=root.after,
            cancel=root.after_cancel,
            paint=_paint_coalesced_settings_nav,
        )
    except Exception:
        _nav_coalescer_holder[0] = None

    _request_settings_nav_paint = _bind_deps(
        _core_settings_ui._request_settings_nav_paint,
        _nav_coalescer_holder=_nav_coalescer_holder,
        main_settings_widget=main_settings_widget_holder[0],
        render_once=render_once,
        skip_cache=skip_cache,
    )

    _nav_request[0] = _request_settings_nav_paint

    _invoke_render_after = _bind_deps(
        _core_stage_render._invoke_render_after,
        _render_after_id=_render_after_id,
        render_once=render_once,
    )

    _schedule_render_oneshot = _bind_deps(
        _core_stage_render._schedule_render_oneshot,
        _invoke_render_after=_invoke_render_after,
        _render_after_id=_render_after_id,
        root=root,
    )

    _commit_receiver_volume = _bind_deps(
        _core_device_control._commit_receiver_volume,
        _clock_saver_volume=_clock_saver_volume,
        _note_volume_graphics=_note_volume_graphics,
        _remember_clock_saver_volume=_remember_clock_saver_volume,
        denon_vol_cache=denon_vol_cache,
        receiver_overlay_state=receiver_overlay_state,
    )

    _on_receiver_volume_changed = _bind_deps(
        _core_device_control._on_receiver_volume_changed,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _commit_receiver_volume=_commit_receiver_volume,
        _idle_audio_meter_active=_idle_audio_meter_active,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        _volume_lines=_volume_lines,
        clock_saver_force_on=clock_saver_force_on,
        render_once=render_once,
        root=root,
        skip_cache=skip_cache,
    )

    def _on_receiver_state(old, new) -> None:
        """Receiver level moved (remote, knob, app): paint it right away."""
        if new.volume_line and new.volume_line != old.volume_line:
            root.after(0, lambda line=new.volume_line: _on_receiver_volume_changed(line))

    get_receiver_link().on_state(_on_receiver_state)

    _bind_receiver_volume_hub = _core_device_control._bind_receiver_volume_hub

    _quick_receiver_volume_poll = _bind_deps(
        _core_device_control._quick_receiver_volume_poll,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _commit_receiver_volume=_commit_receiver_volume,
        _idle_audio_meter_active=_idle_audio_meter_active,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        _volume_lines=_volume_lines,
        clock_saver_force_on=clock_saver_force_on,
        render_once=render_once,
        skip_cache=skip_cache,
    )

    _receiver_volume_poll_tick = _bind_deps(
        _core_device_control._receiver_volume_poll_tick,
        RECEIVER_VOLUME_POLL_MS=RECEIVER_VOLUME_POLL_MS,
        _PIGEON_EXT=_PIGEON_EXT,
        _bind_receiver_volume_hub=_bind_receiver_volume_hub,
        _quick_receiver_volume_poll=_quick_receiver_volume_poll,
        _receiver_volume_poll_tick=_late(lambda: _receiver_volume_poll_tick, "_receiver_volume_poll_tick"),
        receiver_http_host=receiver_http_host,
        root=root,
    )

    _receiver_poll_tick = _bind_deps(
        _core_device_control._receiver_poll_tick,
        RECEIVER_POLL_MS=RECEIVER_POLL_MS,
        _PIGEON_EXT=_PIGEON_EXT,
        _bind_receiver_volume_hub=_bind_receiver_volume_hub,
        _bump_clock_saver_significant_device=_bump_clock_saver_significant_device,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _clock_saver_receiver_off=_clock_saver_receiver_off,
        _clock_saver_volume=_clock_saver_volume,
        _idle_audio_meter_active=_idle_audio_meter_active,
        _note_volume_graphics=_note_volume_graphics,
        _paint_boolean_led=_paint_boolean_led,
        _quick_receiver_volume_poll=_quick_receiver_volume_poll,
        _receiver_poll_tick=_late(lambda: _receiver_poll_tick, "_receiver_poll_tick"),
        _refresh_observed_pairing_led_rows=_refresh_observed_pairing_led_rows,
        _remember_clock_saver_volume=_remember_clock_saver_volume,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        _sync_streaming_badge_from_playback_sources=_sync_streaming_badge_from_playback_sources,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        _warm_playback_overlay_blits=_warm_playback_overlay_blits,
        apple_tv_auto_state=apple_tv_auto_state,
        avr_slot_holder=avr_slot_holder,
        clock_saver_force_on=clock_saver_force_on,
        denon_vol_cache=denon_vol_cache,
        receiver_http_host=receiver_http_host,
        receiver_overlay_state=receiver_overlay_state,
        receiver_panel_led_holder=receiver_panel_led_holder,
        receiver_poll_busy=receiver_poll_busy,
        receiver_power_on_pending=receiver_power_on_pending,
        receiver_power_on_until=receiver_power_on_until,
        receiver_standby_holder=receiver_standby_holder,
        receiver_debug_holder=receiver_debug_holder,
        render_once=render_once,
        root=root,
        skip_cache=skip_cache,
        streaming_slot_holder=streaming_slot_holder,
    )
    ctx._receiver_poll_tick = _receiver_poll_tick

    _capture_splash_underlay = _bind_deps(
        _core_startup._capture_splash_underlay,
        WINDOW_H=WINDOW_H,
        WINDOW_W=WINDOW_W,
        _present_frame_to_display=_present_frame_to_display,
        _splash_underlay_bgr=_splash_underlay_bgr,
        startup_ph=startup_ph,
    )

    _splash_paint_view_one_under_overlay = _bind_deps(
        _core_startup._splash_paint_view_one_under_overlay,
        _PIGEON_EXT=_PIGEON_EXT,
        _warm_view_one_under_splash=_warm_view_one_under_splash,
        render_once=render_once,
        root=root,
        skip_cache=skip_cache,
    )

    ctx._on_shell_configure = _on_shell_configure
    ctx._receiver_volume_poll_tick = _receiver_volume_poll_tick
    ctx._splash_paint_view_one_under_overlay = _splash_paint_view_one_under_overlay
