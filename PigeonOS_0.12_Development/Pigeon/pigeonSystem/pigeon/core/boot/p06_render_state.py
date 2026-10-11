"""Boot phase: render / display state, View 1 layout helpers, clock-saver and idle-dim state.

Phase 6 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from PIL import ImageTk
from pigeon.core import now_playing as _core_now_playing
from pigeon.core import saver_state as _core_saver_state
from pigeon.core import settings_ui as _core_settings_ui
from pigeon.core import stage_render as _core_stage_render
from pigeon.core import startup as _core_startup
from pigeon.core import tmdb_flow as _core_tmdb_flow
from pigeon.core import view_one as _core_view_one
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.core.binding import late as _late
import numpy as np
import sys
import time


def run(ctx) -> None:
    ATV_IDLE_MONO_ANIM_S = ctx.ATV_IDLE_MONO_ANIM_S
    CLOCK_SAVER_BACKDROP_DIM = ctx.CLOCK_SAVER_BACKDROP_DIM
    CLOCK_SAVER_DIM_OPACITY = ctx.CLOCK_SAVER_DIM_OPACITY
    CLOCK_SAVER_POSITION_STALL_GRACE_S = ctx.CLOCK_SAVER_POSITION_STALL_GRACE_S
    CLOCK_STARTUP_FADE_S = ctx.CLOCK_STARTUP_FADE_S
    DevPhase = ctx.DevPhase
    DisplayView = ctx.DisplayView
    LANDING_DISPLAY_BRIGHTNESS = ctx.LANDING_DISPLAY_BRIGHTNESS
    SceneFit = ctx.SceneFit
    THEATER_IDLE_DIM_AFTER_S = ctx.THEATER_IDLE_DIM_AFTER_S
    THEATER_IDLE_DIM_ENABLED = ctx.THEATER_IDLE_DIM_ENABLED
    UI_TARGET_H = ctx.UI_TARGET_H
    UI_TARGET_W = ctx.UI_TARGET_W
    ViewOneLayout = ctx.ViewOneLayout
    WINDOW_H = ctx.WINDOW_H
    WINDOW_W = ctx.WINDOW_W
    _PIGEON_EXT = ctx._PIGEON_EXT
    _apple_tv_is_off = ctx._apple_tv_is_off
    _atv_metadata_is_content_idle = ctx._atv_metadata_is_content_idle
    _boot_clock_saver_until_playback = ctx._boot_clock_saver_until_playback
    _build_landing_design_bgr = ctx._build_landing_design_bgr
    _bump_pigeon_user_activity = ctx._bump_pigeon_user_activity
    _default_render_fps = ctx._default_render_fps
    _load_persisted_scene_enabled = ctx._load_persisted_scene_enabled
    _show_paused_row_overlay = ctx._show_paused_row_overlay
    _splash_reveal_clock = ctx._splash_reveal_clock
    _widget_accepts_typing = ctx._widget_accepts_typing
    active_tmdb_title_key = ctx.active_tmdb_title_key
    apple_tv_auto_state = ctx.apple_tv_auto_state
    apple_tv_playback_clock = ctx.apple_tv_playback_clock
    audio_meter_face_enabled = ctx.audio_meter_face_enabled
    clock_saver_composite_bgra = ctx.clock_saver_composite_bgra
    clock_saver_force_on = ctx.clock_saver_force_on
    current_apple_tv = ctx.current_apple_tv
    dev_phase = ctx.dev_phase
    last_metadata_activity_mono = ctx.last_metadata_activity_mono
    last_pigeon_user_activity_mono = ctx.last_pigeon_user_activity_mono
    main_settings_widget_holder = ctx.main_settings_widget_holder
    post_splash_mono = ctx.post_splash_mono
    prepare_default_poster_at_startup = ctx.prepare_default_poster_at_startup
    program_audio_present = ctx.program_audio_present
    program_audio_session_present = ctx.program_audio_session_present
    scene_enabled = ctx.scene_enabled
    skip_cache = ctx.skip_cache
    startup_ph = ctx.startup_ph
    view_circles_widget_holder = ctx.view_circles_widget_holder

    fps_sched = _default_render_fps()
    display_dims = [WINDOW_W, WINDOW_H]
    fit_holder = [SceneFit(target_w=WINDOW_W, target_h=WINDOW_H)]
    try:
        from pigeon.display_par import read_par_mode, resolve_display_par

        _par0, _par_reason0 = resolve_display_par(
            display_w=int(display_dims[0]), display_h=int(display_dims[1])
        )
        sys.stderr.write(
            f"pigeon: display PAR mode={read_par_mode()}  "
            f"effective={_par0:.4f}  ({_par_reason0})  "
            f"[hold P+A+R to toggle auto/off]\n"
        )
        sys.stderr.flush()
    except Exception:
        pass

    if _PIGEON_EXT:
        from pigeon.design import DESIGN_W as _DESIGN_W_L, DESIGN_H as _DESIGN_H_L

        _land_w, _land_h = int(_DESIGN_W_L), int(_DESIGN_H_L)
    else:
        _land_w, _land_h = UI_TARGET_W, UI_TARGET_H
    # No PNG on the landing plate; playback overlay is badge + receiver lines only.
    landing_scene_design_bgr = _build_landing_design_bgr(_land_w, _land_h, None)

    _disp_fit = _bind_deps(_core_stage_render._disp_fit, fit_holder=fit_holder)

    _black_screen_bgr = _bind_deps(
        _core_stage_render._black_screen_bgr,
        display_dims=display_dims,
    )

    frame_interval_ms = [max(1, int(round(1000.0 / fps_sched)))]

    playing = [False]
    display_view_holder: list[DisplayView] = [DisplayView.ONE]
    # View 4 (key 4): 0=Title Info, 1=Source Info, 2=Playback Info — press 4 again to cycle.
    view_four_subview_holder: list[int] = [0]
    # View 5: 0=viewFive_a, 1=viewFive_b, 2=viewFive_c (testing text view).
    view_five_mode_holder: list[int] = [0]
    # View 1 (Shift+1): cycle a -> b -> c layouts (see ``ViewOneLayout``).
    view_one_layout_holder: list[int] = [int(ViewOneLayout.PIGEON_FULL)]
    # Last view-1 a/b/c while view 1 was live — developer GRID and view-5 grid overlay composite this.
    last_view_one_layout_snapshot: list[int] = [int(ViewOneLayout.PIGEON_FULL)]

    _capture_last_view_one_layout_from_live_view = _bind_deps(
        _core_view_one._capture_last_view_one_layout_from_live_view,
        DisplayView=DisplayView,
        display_view_holder=display_view_holder,
        last_view_one_layout_snapshot=last_view_one_layout_snapshot,
        view_one_layout_holder=view_one_layout_holder,
    )

    _view_one_layout_effective = _bind_deps(
        _core_view_one._view_one_layout_effective,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        _PIGEON_EXT=_PIGEON_EXT,
        dev_phase=dev_phase,
        display_view_holder=display_view_holder,
        last_view_one_layout_snapshot=last_view_one_layout_snapshot,
        view_one_layout_holder=view_one_layout_holder,
    )

    _stage_is_view_one_video_layout = _bind_deps(
        _core_view_one._stage_is_view_one_video_layout,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        _PIGEON_EXT=_PIGEON_EXT,
        dev_phase=dev_phase,
        display_view_holder=display_view_holder,
    )

    _view_one_is_pigeon_full = _bind_deps(
        _core_view_one._view_one_is_pigeon_full,
        ViewOneLayout=ViewOneLayout,
        _stage_is_view_one_video_layout=_stage_is_view_one_video_layout,
        _view_one_layout_effective=_view_one_layout_effective,
    )

    _view_one_is_pigeon_simple = _bind_deps(
        _core_view_one._view_one_is_pigeon_simple,
        ViewOneLayout=ViewOneLayout,
        _stage_is_view_one_video_layout=_stage_is_view_one_video_layout,
        _view_one_layout_effective=_view_one_layout_effective,
    )

    _view_one_is_pigeon_poster = _bind_deps(
        _core_view_one._view_one_is_pigeon_poster,
        ViewOneLayout=ViewOneLayout,
        _stage_is_view_one_video_layout=_stage_is_view_one_video_layout,
        _view_one_layout_effective=_view_one_layout_effective,
    )
    last_frame: list[np.ndarray | None] = [landing_scene_design_bgr]
    brightness_current = [LANDING_DISPLAY_BRIGHTNESS]
    brightness_from = [LANDING_DISPLAY_BRIGHTNESS]
    brightness_target = [LANDING_DISPLAY_BRIGHTNESS]
    brightness_t0 = [time.monotonic()]
    brightness_duration_s = [3.0]
    brightness_duration_up_s = 1.0
    brightness_duration_down_s = 1.0

    last_atv_interaction_mono = [0.0]
    last_timecode_motion_mono = [0.0]
    # ``last_metadata_activity_mono`` is initialized with pigeon user-activity state above.
    last_clock_saver_significant_device_mono = [time.monotonic()]
    # Monotonic start of the current paused-with-content hold; 0 while not paused.
    _paused_row_since_mono = [0.0]
    _paused_row_last_hold_mono = [0.0]
    _cs_sig_init = [False]
    _cs_sig_ck: list[str | None] = [None]
    _cs_sig_ds = [""]
    _cs_sig_vol = [""]
    _cs_sig_fp = [""]
    _atv_ix_sig_ds = [""]
    _atv_ix_sig_ck: list[str | None] = [None]
    _atv_ix_pos: list[float | None] = [None]
    _atv_ix_pos_mono = [0.0]
    _atv_ix_extrap_playing = [False]
    _atv_ix_prev_idle = [True]

    _atv_idle_monochrome_active = _bind_deps(
        _core_saver_state._atv_idle_monochrome_active,
        THEATER_IDLE_DIM_AFTER_S=THEATER_IDLE_DIM_AFTER_S,
        apple_tv_playback_clock=apple_tv_playback_clock,
        current_apple_tv=current_apple_tv,
        last_atv_interaction_mono=last_atv_interaction_mono,
        last_pigeon_user_activity_mono=last_pigeon_user_activity_mono,
    )

    _vol_norm_for_clock_saver = _core_saver_state._vol_norm_for_clock_saver

    _bump_clock_saver_significant_device = _bind_deps(
        _core_saver_state._bump_clock_saver_significant_device,
        last_clock_saver_significant_device_mono=last_clock_saver_significant_device_mono,
    )

    _note_metadata_activity = _bind_deps(
        _core_saver_state._note_metadata_activity,
        last_metadata_activity_mono=last_metadata_activity_mono,
    )

    _clear_reported_position_stall_stamp = _bind_deps(
        _core_saver_state._clear_reported_position_stall_stamp,
        last_metadata_activity_mono=last_metadata_activity_mono,
    )

    _coarse_device_state_for_saver = _core_saver_state._coarse_device_state_for_saver

    _metadata_activity_fingerprint = _bind_deps(
        _core_now_playing._metadata_activity_fingerprint,
        _coarse_device_state_for_saver=_coarse_device_state_for_saver,
        _content_key_from_metadata=_late(lambda: ctx._content_key_from_metadata, "_content_key_from_metadata"),
    )

    _bump_clock_saver_significant_device_from_metadata = _bind_deps(
        _core_saver_state._bump_clock_saver_significant_device_from_metadata,
        _bump_clock_saver_significant_device=_bump_clock_saver_significant_device,
        _coarse_device_state_for_saver=_coarse_device_state_for_saver,
        _content_key_from_metadata=_late(lambda: ctx._content_key_from_metadata, "_content_key_from_metadata"),
        _cs_sig_ck=_cs_sig_ck,
        _cs_sig_ds=_cs_sig_ds,
        _cs_sig_fp=_cs_sig_fp,
        _cs_sig_init=_cs_sig_init,
        _cs_sig_vol=_cs_sig_vol,
        _metadata_activity_fingerprint=_metadata_activity_fingerprint,
        _note_metadata_activity=_note_metadata_activity,
        _vol_norm_for_clock_saver=_vol_norm_for_clock_saver,
    )
        # Receiver / player volume must not dismiss the idle clock saver.

    _reset_clock_saver_device_signal_baseline = _bind_deps(
        _core_saver_state._reset_clock_saver_device_signal_baseline,
        _bump_clock_saver_significant_device=_bump_clock_saver_significant_device,
        _cs_sig_ck=_cs_sig_ck,
        _cs_sig_ds=_cs_sig_ds,
        _cs_sig_fp=_cs_sig_fp,
        _cs_sig_init=_cs_sig_init,
        _cs_sig_vol=_cs_sig_vol,
        _note_metadata_activity=_note_metadata_activity,
    )

    _apply_position_stall_grace_to_clock_saver = _bind_deps(
        _core_saver_state._apply_position_stall_grace_to_clock_saver,
        CLOCK_SAVER_POSITION_STALL_GRACE_S=CLOCK_SAVER_POSITION_STALL_GRACE_S,
        last_clock_saver_significant_device_mono=last_clock_saver_significant_device_mono,
        last_timecode_motion_mono=last_timecode_motion_mono,
    )

    _cs_meta_idle_log_mono = [0.0]
    _cs_meta_idle_was_active = [False]

    _something_playing_now = _bind_deps(
        _core_saver_state._something_playing_now,
        _apple_tv_is_off=_apple_tv_is_off,
        _atv_metadata_is_content_idle=_atv_metadata_is_content_idle,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
    )

    _tmdb_info_current_and_available = _bind_deps(
        _core_tmdb_flow._tmdb_info_current_and_available,
        _tmdb_spawn_identity=_late(lambda: ctx._tmdb_spawn_identity, "_tmdb_spawn_identity"),
        active_tmdb_title_key=active_tmdb_title_key,
        apple_tv_auto_state=apple_tv_auto_state,
    )

    _metadata_drives_clock_saver = _bind_deps(
        _core_saver_state._metadata_drives_clock_saver,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
    )

    _clock_saver_idle_need = _core_saver_state._clock_saver_idle_need

    _clock_saver_user_enabled = _core_saver_state._clock_saver_user_enabled

    _player_metadata_class = _bind_deps(
        _core_now_playing._player_metadata_class,
        _playback_extrapolated_pair=_late(lambda: ctx._playback_extrapolated_pair, "_playback_extrapolated_pair"),
        _show_paused_row_overlay=_show_paused_row_overlay,
        _something_playing_now=_something_playing_now,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
    )

    _pausesaver_is_holding = _bind_deps(
        _core_saver_state._pausesaver_is_holding,
        _player_metadata_class=_player_metadata_class,
        _show_paused_row_overlay=_show_paused_row_overlay,
    )

    _refresh_paused_row_stamp = _bind_deps(
        _core_saver_state._refresh_paused_row_stamp,
        _paused_row_last_hold_mono=_paused_row_last_hold_mono,
        _paused_row_since_mono=_paused_row_since_mono,
        _pausesaver_is_holding=_pausesaver_is_holding,
    )

    _clock_saver_content_is_idle = _bind_deps(
        _core_saver_state._clock_saver_content_is_idle,
        _atv_metadata_is_content_idle=_atv_metadata_is_content_idle,
        apple_tv_auto_state=apple_tv_auto_state,
    )

    _clock_startup_intro_opacity = _bind_deps(
        _core_startup._clock_startup_intro_opacity,
        CLOCK_STARTUP_FADE_S=CLOCK_STARTUP_FADE_S,
        clock_saver_composite_bgra=clock_saver_composite_bgra,
        post_splash_mono=post_splash_mono,
        startup_ph=startup_ph,
    )

    _stage_grid_overlay_mode = _bind_deps(
        _core_stage_render._stage_grid_overlay_mode,
        DisplayView=DisplayView,
        display_view_holder=display_view_holder,
        view_five_mode_holder=view_five_mode_holder,
    )

    _clock_saver_for_compose = _bind_deps(
        _core_saver_state._clock_saver_for_compose,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        _apply_auto_widget_policy=_late(lambda: ctx._apply_auto_widget_policy, "_apply_auto_widget_policy"),
        _clock_saver_active=_late(lambda: ctx._clock_saver_active, "_clock_saver_active"),
        _clock_startup_intro_opacity=_clock_startup_intro_opacity,
        _effective_display_view=_late(lambda: _effective_display_view, "_effective_display_view"),
        _refresh_paused_row_stamp=_refresh_paused_row_stamp,
        _splash_reveal_clock=_splash_reveal_clock,
        _tmdb_info_current_and_available=_tmdb_info_current_and_available,
        clock_saver_composite_bgra=clock_saver_composite_bgra,
        clock_saver_force_on=clock_saver_force_on,
        dev_phase=dev_phase,
        scene_enabled=scene_enabled,
        startup_ph=startup_ph,
    )

    _idle_saver_face_toggle_ok = _bind_deps(
        _core_saver_state._idle_saver_face_toggle_ok,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _clock_startup_intro_opacity=_clock_startup_intro_opacity,
        startup_ph=startup_ph,
    )

    _idle_audio_meter_active = _bind_deps(
        _core_saver_state._idle_audio_meter_active,
        _idle_saver_face_toggle_ok=_idle_saver_face_toggle_ok,
        audio_meter_face_enabled=audio_meter_face_enabled,
    )

    _program_audio_present = _bind_deps(
        _core_now_playing._program_audio_present,
        program_audio_present=program_audio_present,
    )

    _program_audio_session = _bind_deps(
        _core_now_playing._program_audio_session,
        _program_audio_present=_program_audio_present,
        program_audio_session_present=program_audio_session_present,
    )

    _idle_audio_listen = _bind_deps(
        _core_saver_state._idle_audio_listen,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _view_one_uses_now_playing_screen=_late(lambda: ctx._view_one_uses_now_playing_screen, "_view_one_uses_now_playing_screen"),
    )

    _settings_audio_led_listen = _bind_deps(
        _core_settings_ui._settings_audio_led_listen,
        main_settings_widget_holder=main_settings_widget_holder,
    )

    _np_wants_live_audio = _bind_deps(
        _core_now_playing._np_wants_live_audio,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _view_one_uses_now_playing_screen=_late(lambda: ctx._view_one_uses_now_playing_screen, "_view_one_uses_now_playing_screen"),
        view_circles_widget_holder=view_circles_widget_holder,
    )

    _audio_capture_wanted = _bind_deps(
        _core_saver_state._audio_capture_wanted,
        _idle_audio_listen=_idle_audio_listen,
        _idle_audio_meter_active=_idle_audio_meter_active,
        _np_wants_live_audio=_np_wants_live_audio,
        _settings_audio_led_listen=_settings_audio_led_listen,
    )

    _toggle_clock_saver_force = _bind_deps(
        _core_saver_state._toggle_clock_saver_force,
        _PIGEON_EXT=_PIGEON_EXT,
        _boot_clock_saver_until_playback=_boot_clock_saver_until_playback,
        _bump_clock_saver_significant_device=_bump_clock_saver_significant_device,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _note_metadata_activity=_note_metadata_activity,
        _widget_accepts_typing=_widget_accepts_typing,
        clock_saver_composite_bgra=clock_saver_composite_bgra,
        clock_saver_force_on=clock_saver_force_on,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        skip_cache=skip_cache,
    )

    _clock_saver_dim_pre_digit_canvas = _core_saver_state._clock_saver_dim_pre_digit_canvas

    _clock_saver_dim_overlay_bgra = _core_saver_state._clock_saver_dim_overlay_bgra

    idle_dim_anim_strength = [0.0]
    _idle_dim_anim_goal = [0.0]
    _idle_dim_anim_from = [0.0]
    _idle_dim_anim_t0 = [time.monotonic()]

    _update_idle_dim_strength = _bind_deps(
        _core_saver_state._update_idle_dim_strength,
        ATV_IDLE_MONO_ANIM_S=ATV_IDLE_MONO_ANIM_S,
        THEATER_IDLE_DIM_ENABLED=THEATER_IDLE_DIM_ENABLED,
        _atv_idle_monochrome_active=_atv_idle_monochrome_active,
        _idle_dim_anim_from=_idle_dim_anim_from,
        _idle_dim_anim_goal=_idle_dim_anim_goal,
        _idle_dim_anim_t0=_idle_dim_anim_t0,
        idle_dim_anim_strength=idle_dim_anim_strength,
    )

    _compose_idle_strength_holder: list[float] = [0.0]
    _live_perf: list[float] = [0.0, 0.0, 0.0, 0.0, 0.0]
    _hitch_parts: list[float] = [0.0, 0.0]
    _np_state_sync_mono: list[float] = [0.0]
    _np_dump_mono: list[float] = [0.0]

    _record_live_audio_timing = _bind_deps(
        _core_stage_render._record_live_audio_timing,
        _hitch_parts=_hitch_parts,
        _live_perf=_live_perf,
    )

    scaled_display: list[np.ndarray | None] = [None]
    scaled_version = [0]
    if last_frame[0] is not None:
        scaled_display[0] = _disp_fit().scale_and_crop(last_frame[0])
        scaled_version[0] = 1

    _nav_coalescer_holder: list[object] = [None]
    _nav_request: list[object] = [None]
    scene_enabled[0] = _load_persisted_scene_enabled(True)

    _effective_display_view = _bind_deps(
        _core_stage_render._effective_display_view,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        _PIGEON_EXT=_PIGEON_EXT,
        dev_phase=dev_phase,
        display_view_holder=display_view_holder,
    )

    _design_grid_overlay_active = _bind_deps(
        _core_stage_render._design_grid_overlay_active,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        dev_phase=dev_phase,
        display_view_holder=display_view_holder,
    )

    # Advanced matrix: temporarily show GRID behind the dialog when opened from Settings; restore on close.
    advanced_matrix_restore_phase: list[object] = [None]
    advanced_matrix_close_skip: list[bool] = [False]
    location_toast_state: dict[str, object] = {
        "active": False,
        "text": "",
        "t0": 0.0,
        "startup_top_left": False,
    }
    prev_dev_phase_for_location_toast: list[DevPhase] = [DevPhase.OFF]
    clock_saver_peek_until_mono: list[float] = [0.0]

    _clock_saver_layer_opacity = _bind_deps(
        _core_saver_state._clock_saver_layer_opacity,
        CLOCK_SAVER_DIM_OPACITY=CLOCK_SAVER_DIM_OPACITY,
        _boot_clock_saver_until_playback=_boot_clock_saver_until_playback,
        _clock_startup_intro_opacity=_clock_startup_intro_opacity,
        _splash_reveal_clock=_splash_reveal_clock,
        clock_saver_peek_until_mono=clock_saver_peek_until_mono,
    )

    black_photo: list[ImageTk.PhotoImage | None] = [None]
    label_live_photo: list[ImageTk.PhotoImage | None] = [None]
    _render_after_id: list[str | None] = [None]
    use_backdrop_scene = [False]

    _backdrop_active_for_view = _bind_deps(
        _core_stage_render._backdrop_active_for_view,
        DisplayView=DisplayView,
        _effective_display_view=_effective_display_view,
        use_backdrop_scene=use_backdrop_scene,
    )

    backdrop_master_bgr: list[np.ndarray | None] = [None]

    _clock_saver_backdrop_brightness = _bind_deps(
        _core_saver_state._clock_saver_backdrop_brightness,
        CLOCK_SAVER_BACKDROP_DIM=CLOCK_SAVER_BACKDROP_DIM,
        _backdrop_active_for_view=_backdrop_active_for_view,
        _clock_saver_for_compose=_clock_saver_for_compose,
        backdrop_master_bgr=backdrop_master_bgr,
    )

    # Last TMDb backdrop (copy); survives display off so developer-grid F10 can return to backdrop.
    saved_backdrop_master_bgr: list[np.ndarray | None] = [None]
    # True when the saved/current master came from the streaming app logo (not TMDb stills).
    saved_backdrop_app_logo_letterbox_fit: list[bool] = [False]
    backdrop_app_logo_letterbox_fit: list[bool] = [False]

    _app_logo_clock_saver_style_now = _bind_deps(
        _core_saver_state._app_logo_clock_saver_style_now,
        _clock_saver_for_compose=_clock_saver_for_compose,
        backdrop_app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit,
    )

    if _PIGEON_EXT and prepare_default_poster_at_startup is not None:
        try:
            ok_sp, msg_sp, _gc_sp = prepare_default_poster_at_startup()
            sys.stderr.write(f"pigeon: startup poster: {msg_sp}\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"pigeon: startup poster error: {e}\n")
            sys.stderr.flush()

    ctx._app_logo_clock_saver_style_now = _app_logo_clock_saver_style_now
    ctx._apply_position_stall_grace_to_clock_saver = _apply_position_stall_grace_to_clock_saver
    ctx._atv_idle_monochrome_active = _atv_idle_monochrome_active
    ctx._atv_ix_extrap_playing = _atv_ix_extrap_playing
    ctx._atv_ix_pos = _atv_ix_pos
    ctx._atv_ix_pos_mono = _atv_ix_pos_mono
    ctx._atv_ix_prev_idle = _atv_ix_prev_idle
    ctx._atv_ix_sig_ck = _atv_ix_sig_ck
    ctx._atv_ix_sig_ds = _atv_ix_sig_ds
    ctx._audio_capture_wanted = _audio_capture_wanted
    ctx._backdrop_active_for_view = _backdrop_active_for_view
    ctx._black_screen_bgr = _black_screen_bgr
    ctx._bump_clock_saver_significant_device = _bump_clock_saver_significant_device
    ctx._bump_clock_saver_significant_device_from_metadata = _bump_clock_saver_significant_device_from_metadata
    ctx._capture_last_view_one_layout_from_live_view = _capture_last_view_one_layout_from_live_view
    ctx._clear_reported_position_stall_stamp = _clear_reported_position_stall_stamp
    ctx._clock_saver_backdrop_brightness = _clock_saver_backdrop_brightness
    ctx._clock_saver_content_is_idle = _clock_saver_content_is_idle
    ctx._clock_saver_dim_overlay_bgra = _clock_saver_dim_overlay_bgra
    ctx._clock_saver_dim_pre_digit_canvas = _clock_saver_dim_pre_digit_canvas
    ctx._clock_saver_for_compose = _clock_saver_for_compose
    ctx._clock_saver_idle_need = _clock_saver_idle_need
    ctx._clock_saver_layer_opacity = _clock_saver_layer_opacity
    ctx._clock_saver_user_enabled = _clock_saver_user_enabled
    ctx._clock_startup_intro_opacity = _clock_startup_intro_opacity
    ctx._compose_idle_strength_holder = _compose_idle_strength_holder
    ctx._cs_meta_idle_log_mono = _cs_meta_idle_log_mono
    ctx._cs_meta_idle_was_active = _cs_meta_idle_was_active
    ctx._design_grid_overlay_active = _design_grid_overlay_active
    ctx._disp_fit = _disp_fit
    ctx._effective_display_view = _effective_display_view
    ctx._hitch_parts = _hitch_parts
    ctx._idle_audio_listen = _idle_audio_listen
    ctx._idle_audio_meter_active = _idle_audio_meter_active
    ctx._idle_saver_face_toggle_ok = _idle_saver_face_toggle_ok
    ctx._metadata_drives_clock_saver = _metadata_drives_clock_saver
    ctx._nav_coalescer_holder = _nav_coalescer_holder
    ctx._nav_request = _nav_request
    ctx._note_metadata_activity = _note_metadata_activity
    ctx._np_dump_mono = _np_dump_mono
    ctx._np_state_sync_mono = _np_state_sync_mono
    ctx._np_wants_live_audio = _np_wants_live_audio
    ctx._pausesaver_is_holding = _pausesaver_is_holding
    ctx._player_metadata_class = _player_metadata_class
    ctx._program_audio_session = _program_audio_session
    ctx._record_live_audio_timing = _record_live_audio_timing
    ctx._refresh_paused_row_stamp = _refresh_paused_row_stamp
    ctx._render_after_id = _render_after_id
    ctx._reset_clock_saver_device_signal_baseline = _reset_clock_saver_device_signal_baseline
    ctx._settings_audio_led_listen = _settings_audio_led_listen
    ctx._something_playing_now = _something_playing_now
    ctx._stage_grid_overlay_mode = _stage_grid_overlay_mode
    ctx._stage_is_view_one_video_layout = _stage_is_view_one_video_layout
    ctx._tmdb_info_current_and_available = _tmdb_info_current_and_available
    ctx._toggle_clock_saver_force = _toggle_clock_saver_force
    ctx._update_idle_dim_strength = _update_idle_dim_strength
    ctx._view_one_is_pigeon_full = _view_one_is_pigeon_full
    ctx._view_one_is_pigeon_poster = _view_one_is_pigeon_poster
    ctx._view_one_is_pigeon_simple = _view_one_is_pigeon_simple
    ctx._view_one_layout_effective = _view_one_layout_effective
    ctx.advanced_matrix_close_skip = advanced_matrix_close_skip
    ctx.advanced_matrix_restore_phase = advanced_matrix_restore_phase
    ctx.backdrop_app_logo_letterbox_fit = backdrop_app_logo_letterbox_fit
    ctx.backdrop_master_bgr = backdrop_master_bgr
    ctx.black_photo = black_photo
    ctx.brightness_current = brightness_current
    ctx.brightness_duration_down_s = brightness_duration_down_s
    ctx.brightness_duration_s = brightness_duration_s
    ctx.brightness_duration_up_s = brightness_duration_up_s
    ctx.brightness_from = brightness_from
    ctx.brightness_t0 = brightness_t0
    ctx.brightness_target = brightness_target
    ctx.clock_saver_peek_until_mono = clock_saver_peek_until_mono
    ctx.display_dims = display_dims
    ctx.display_view_holder = display_view_holder
    ctx.fit_holder = fit_holder
    ctx.frame_interval_ms = frame_interval_ms
    ctx.label_live_photo = label_live_photo
    ctx.landing_scene_design_bgr = landing_scene_design_bgr
    ctx.last_atv_interaction_mono = last_atv_interaction_mono
    ctx.last_clock_saver_significant_device_mono = last_clock_saver_significant_device_mono
    ctx.last_frame = last_frame
    ctx.last_timecode_motion_mono = last_timecode_motion_mono
    ctx.location_toast_state = location_toast_state
    ctx.playing = playing
    ctx.prev_dev_phase_for_location_toast = prev_dev_phase_for_location_toast
    ctx.saved_backdrop_app_logo_letterbox_fit = saved_backdrop_app_logo_letterbox_fit
    ctx.saved_backdrop_master_bgr = saved_backdrop_master_bgr
    ctx.scaled_display = scaled_display
    ctx.scaled_version = scaled_version
    ctx.use_backdrop_scene = use_backdrop_scene
    ctx.view_five_mode_holder = view_five_mode_holder
    ctx.view_four_subview_holder = view_four_subview_holder
    ctx.view_one_layout_holder = view_one_layout_holder
