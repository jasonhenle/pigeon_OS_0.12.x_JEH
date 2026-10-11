"""Boot phase: blit caches and the stage / poster / now-playing render pipeline.

Phase 8 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from PIL import ImageFont
from pigeon.core import now_playing as _core_now_playing
from pigeon.core import saver_state as _core_saver_state
from pigeon.core import settings_ui as _core_settings_ui
from pigeon.core import stage_render as _core_stage_render
from pigeon.core import startup as _core_startup
from pigeon.core import tmdb_flow as _core_tmdb_flow
from pigeon.core import view_four as _core_view_four
from pigeon.core import view_one as _core_view_one
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.core.binding import late as _late
import numpy as np


def run(ctx) -> None:
    CLOCK_ANCHOR_COL = ctx.CLOCK_ANCHOR_COL
    CLOCK_ANCHOR_ROW = ctx.CLOCK_ANCHOR_ROW
    DESIGN_H = ctx.DESIGN_H
    DESIGN_W = ctx.DESIGN_W
    DevPhase = ctx.DevPhase
    DisplayView = ctx.DisplayView
    PATCH_LAYER_RECEIVER_AUDIO = ctx.PATCH_LAYER_RECEIVER_AUDIO
    PAUSED_SCREEN_BACKDROP_DIM = ctx.PAUSED_SCREEN_BACKDROP_DIM
    SceneFit = ctx.SceneFit
    VIEW_ONE_BADGE_COL_RIGHT = ctx.VIEW_ONE_BADGE_COL_RIGHT
    ViewOneLayout = ctx.ViewOneLayout
    ViewOneVariant = ctx.ViewOneVariant
    _PIGEON_EXT = ctx._PIGEON_EXT
    _PROJECT_DIR = ctx._PROJECT_DIR
    _app_logo_clock_saver_style_now = ctx._app_logo_clock_saver_style_now
    _apple_tv_is_off = ctx._apple_tv_is_off
    _apply_brightness = ctx._apply_brightness
    _atv_metadata_is_content_idle = ctx._atv_metadata_is_content_idle
    _backdrop_active_for_view = ctx._backdrop_active_for_view
    _black_screen_bgr = ctx._black_screen_bgr
    _clock_saver_active = ctx._clock_saver_active
    _clock_saver_backdrop_brightness = ctx._clock_saver_backdrop_brightness
    _clock_saver_dim_overlay_bgra = ctx._clock_saver_dim_overlay_bgra
    _clock_saver_dim_pre_digit_canvas = ctx._clock_saver_dim_pre_digit_canvas
    _clock_saver_for_compose = ctx._clock_saver_for_compose
    _clock_saver_layer_opacity = ctx._clock_saver_layer_opacity
    _clock_saver_layers = ctx._clock_saver_layers
    _clock_saver_receiver_off = ctx._clock_saver_receiver_off
    _clock_saver_user_enabled = ctx._clock_saver_user_enabled
    _clock_startup_intro_opacity = ctx._clock_startup_intro_opacity
    _composite_cap_dims = ctx._composite_cap_dims
    _composite_settings_on_canvas = ctx._composite_settings_on_canvas
    _design_grid_overlay_active = ctx._design_grid_overlay_active
    _disp_fit = ctx._disp_fit
    _effective_display_view = ctx._effective_display_view
    _enable_now_playing_screen = ctx._enable_now_playing_screen
    _hitch_parts = ctx._hitch_parts
    _idle_audio_meter_active = ctx._idle_audio_meter_active
    _log_view_one_startup_phase = ctx._log_view_one_startup_phase
    _maybe_exit_settings_menus_on_idle = ctx._maybe_exit_settings_menus_on_idle
    _playback_is_netflix_stream = ctx._playback_is_netflix_stream
    _player_metadata_class = ctx._player_metadata_class
    _present_frame_to_display = ctx._present_frame_to_display
    _program_audio_session = ctx._program_audio_session
    _refresh_paused_row_stamp = ctx._refresh_paused_row_stamp
    _settings_is_native_1280 = ctx._settings_is_native_1280
    _show_paused_row_overlay = ctx._show_paused_row_overlay
    _splash_reveal_clock = ctx._splash_reveal_clock
    _splash_view_one_warm_done = ctx._splash_view_one_warm_done
    _stage_grid_overlay_mode = ctx._stage_grid_overlay_mode
    _stage_is_view_one_video_layout = ctx._stage_is_view_one_video_layout
    _sync_now_playing_screen_state = ctx._sync_now_playing_screen_state
    _sync_now_playing_screen_state_for_frame = ctx._sync_now_playing_screen_state_for_frame
    _tmdb_info_current_and_available = ctx._tmdb_info_current_and_available
    _view_one_is_pigeon_full = ctx._view_one_is_pigeon_full
    _view_one_is_pigeon_poster = ctx._view_one_is_pigeon_poster
    _view_one_is_pigeon_simple = ctx._view_one_is_pigeon_simple
    _view_one_layout_effective = ctx._view_one_layout_effective
    _view_one_uses_now_playing_screen = ctx._view_one_uses_now_playing_screen
    active_tmdb_display_title = ctx.active_tmdb_display_title
    active_tmdb_title_key = ctx.active_tmdb_title_key
    alpha_blend_bgra_over_bgr = ctx.alpha_blend_bgra_over_bgr
    apple_tv_auto_state = ctx.apple_tv_auto_state
    apple_tv_playback_clock = ctx.apple_tv_playback_clock
    backdrop_app_logo_letterbox_fit = ctx.backdrop_app_logo_letterbox_fit
    backdrop_master_bgr = ctx.backdrop_master_bgr
    black_photo = ctx.black_photo
    blend_overlay_bgr = ctx.blend_overlay_bgr
    build_info_cluster_design_patches = ctx.build_info_cluster_design_patches
    build_stage_overlay_source_bgra = ctx.build_stage_overlay_source_bgra
    cap = ctx.cap
    clock_saver_composite_bgra = ctx.clock_saver_composite_bgra
    clock_saver_force_on = ctx.clock_saver_force_on
    clock_widget = ctx.clock_widget
    current_apple_tv = ctx.current_apple_tv
    dev_phase = ctx.dev_phase
    display_dims = ctx.display_dims
    frame_interval_ms = ctx.frame_interval_ms
    get_grid_geometry = ctx.get_grid_geometry
    info_cluster_clock_widget = ctx.info_cluster_clock_widget
    label = ctx.label
    last_frame = ctx.last_frame
    load_pigeon_temp_logo_bgra = ctx.load_pigeon_temp_logo_bgra
    location_toast_patch_bgra = ctx.location_toast_patch_bgra
    location_toast_state = ctx.location_toast_state
    main_settings_widget_holder = ctx.main_settings_widget_holder
    playback_lower_gradient_bgra = ctx.playback_lower_gradient_bgra
    playback_overlay_flags = ctx.playback_overlay_flags
    playback_overlay_widget = ctx.playback_overlay_widget
    receiver_overlay_state = ctx.receiver_overlay_state
    receiver_debug_holder = ctx.receiver_debug_holder
    rect_for_span_at_cell = ctx.rect_for_span_at_cell
    rect_for_span_top_right_at_cell = ctx.rect_for_span_top_right_at_cell
    render_ui_music_text_patch_bgra = ctx.render_ui_music_text_patch_bgra
    render_ui_text_patch_bgra = ctx.render_ui_text_patch_bgra
    resolve_view_one_variant = ctx.resolve_view_one_variant
    root = ctx.root
    saved_backdrop_app_logo_letterbox_fit = ctx.saved_backdrop_app_logo_letterbox_fit
    saved_backdrop_master_bgr = ctx.saved_backdrop_master_bgr
    scale_cover_center_crop = ctx.scale_cover_center_crop
    scale_height_and_center_crop = ctx.scale_height_and_center_crop
    scaled_display = ctx.scaled_display
    scaled_version = ctx.scaled_version
    scene_enabled = ctx.scene_enabled
    skip_cache = ctx.skip_cache
    startup_ph = ctx.startup_ph
    status_bar_widget = ctx.status_bar_widget
    streaming_badge_state = ctx.streaming_badge_state
    tmdb_logo_app_fallback_active = ctx.tmdb_logo_app_fallback_active
    tmdb_logo_patch_bgra = ctx.tmdb_logo_patch_bgra
    tmdb_logo_widget = ctx.tmdb_logo_widget
    tmdb_logo_widget_view_six = ctx.tmdb_logo_widget_view_six
    tmdb_tt_gradient_bgr_holder = ctx.tmdb_tt_gradient_bgr_holder
    variant_uses_full_path = ctx.variant_uses_full_path
    video_area = ctx.video_area
    view_circles_widget_holder = ctx.view_circles_widget_holder
    view_four_subview_holder = ctx.view_four_subview_holder

    clock_patch_bgra: list[np.ndarray | None] = [None]
    status_bar_blits: list[list] = [[]]
    playback_overlay_blits: list[list] = [[]]
    info_cluster_blits: list[list] = [[]]
    _info_cluster_blits_sig: list[object | None] = [None]
    # [unix_sec, status_bar accent BGR or None] — clock patch invalidation.
    _clock_patch_sig: list = [-1, None]
    _blend_top_gradient_design = _core_stage_render._blend_top_gradient_design

    _blend_top_gradient_fast = _core_stage_render._blend_top_gradient_fast

    _apply_stage_chrome_colors = _bind_deps(
        _core_stage_render._apply_stage_chrome_colors,
        label=label,
        video_area=video_area,
    )

    _refresh_stage_from_poster = _bind_deps(
        _core_stage_render._refresh_stage_from_poster,
        _PIGEON_EXT=_PIGEON_EXT,
        _apply_stage_chrome_colors=_apply_stage_chrome_colors,
        black_photo=black_photo,
        skip_cache=skip_cache,
    )

    _refresh_stage_from_poster()

    _design_rect_to_target = _bind_deps(
        _core_stage_render._design_rect_to_target,
        DESIGN_H=DESIGN_H,
        DESIGN_W=DESIGN_W,
    )

    _saver_layer_is_full_frame = _core_saver_state._saver_layer_is_full_frame

    _blit_saver_layers_design = _bind_deps(
        _core_saver_state._blit_saver_layers_design,
        _saver_layer_is_full_frame=_saver_layer_is_full_frame,
        alpha_blend_bgra_over_bgr=alpha_blend_bgra_over_bgr,
    )

    _blit_saver_layers_target = _bind_deps(
        _core_saver_state._blit_saver_layers_target,
        DESIGN_H=DESIGN_H,
        DESIGN_W=DESIGN_W,
        _design_rect_to_target=_design_rect_to_target,
        alpha_blend_bgra_over_bgr=alpha_blend_bgra_over_bgr,
    )

    _warm_status_bar_blits = _bind_deps(
        _core_now_playing._warm_status_bar_blits,
        status_bar_blits=status_bar_blits,
        status_bar_widget=status_bar_widget,
    )
    ctx._warm_status_bar_blits = _warm_status_bar_blits

    _warm_view_one_under_splash = _bind_deps(
        _core_startup._warm_view_one_under_splash,
        _PIGEON_EXT=_PIGEON_EXT,
        _enable_now_playing_screen=_enable_now_playing_screen,
        _log_view_one_startup_phase=_log_view_one_startup_phase,
        _splash_view_one_warm_done=_splash_view_one_warm_done,
        _warm_status_bar_blits=_warm_status_bar_blits,
        root=root,
        view_circles_widget=view_circles_widget_holder[0],
    )

    _set_playback_overlay_clock_saver_volume_flag = _bind_deps(
        _core_saver_state._set_playback_overlay_clock_saver_volume_flag,
        _backdrop_active_for_view=_backdrop_active_for_view,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _playback_is_netflix_stream=_playback_is_netflix_stream,
        playback_overlay_flags=playback_overlay_flags,
        receiver_overlay_state=receiver_overlay_state,
    )

    _warm_playback_overlay_blits = _bind_deps(
        _core_stage_render._warm_playback_overlay_blits,
        _set_playback_overlay_clock_saver_volume_flag=_set_playback_overlay_clock_saver_volume_flag,
        _show_paused_row_overlay=_show_paused_row_overlay,
        _view_one_streaming_logo_duplicate_fallback=_late(lambda: _view_one_streaming_logo_duplicate_fallback, "_view_one_streaming_logo_duplicate_fallback"),
        _warm_info_cluster_blits=_late(lambda: _warm_info_cluster_blits, "_warm_info_cluster_blits"),
        playback_overlay_blits=playback_overlay_blits,
        playback_overlay_flags=playback_overlay_flags,
        playback_overlay_widget=playback_overlay_widget,
    )

    _info_cluster_compose_active = _bind_deps(
        _core_stage_render._info_cluster_compose_active,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        _PIGEON_EXT=_PIGEON_EXT,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _effective_display_view=_effective_display_view,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        dev_phase=dev_phase,
    )

    _warm_info_cluster_blits = _bind_deps(
        _core_stage_render._warm_info_cluster_blits,
        _PIGEON_EXT=_PIGEON_EXT,
        _info_cluster_blits_sig=_info_cluster_blits_sig,
        _info_cluster_compose_active=_info_cluster_compose_active,
        _location_toast_alpha=_late(lambda: ctx._location_toast_alpha, "_location_toast_alpha"),
        build_info_cluster_design_patches=build_info_cluster_design_patches,
        info_cluster_blits=info_cluster_blits,
        info_cluster_clock_widget=info_cluster_clock_widget,
        location_toast_state=location_toast_state,
        receiver_overlay_state=receiver_overlay_state,
        status_bar_widget=status_bar_widget,
    )

    _blend_info_cluster_into_target = _bind_deps(
        _core_stage_render._blend_info_cluster_into_target,
        _design_rect_to_target=_design_rect_to_target,
        _info_cluster_compose_active=_info_cluster_compose_active,
        _warm_info_cluster_blits=_warm_info_cluster_blits,
        alpha_blend_bgra_over_bgr=alpha_blend_bgra_over_bgr,
        info_cluster_blits=info_cluster_blits,
    )

    _active_tmdb_logo_widget = _bind_deps(
        _core_view_one._active_tmdb_logo_widget,
        DisplayView=DisplayView,
        _effective_display_view=_effective_display_view,
        tmdb_logo_widget=tmdb_logo_widget,
        tmdb_logo_widget_view_six=tmdb_logo_widget_view_six,
    )

    _tmdb_poster_cache: dict[str, object] = {"key": None, "bgra": None}
    _tmdb_tt_src_cache: dict[str, object] = {"key": None, "bgra": None}

    _styled_video_content_c_poster = _core_stage_render._styled_video_content_c_poster

    _active_tmdb_poster_bgra = _bind_deps(
        _core_tmdb_flow._active_tmdb_poster_bgra,
        _tmdb_poster_cache=_tmdb_poster_cache,
        active_tmdb_title_key=active_tmdb_title_key,
    )

    _active_tmdb_tt_src_bgra = _bind_deps(
        _core_tmdb_flow._active_tmdb_tt_src_bgra,
        _tmdb_tt_src_cache=_tmdb_tt_src_cache,
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
    )
    ctx._active_tmdb_tt_src_bgra = _active_tmdb_tt_src_bgra

    _sync_settings_zone2_tt = _bind_deps(
        _core_settings_ui._sync_settings_zone2_tt,
        main_settings_widget=main_settings_widget_holder[0],
    )
    ctx._sync_settings_zone2_tt = _sync_settings_zone2_tt

    _clear_music_artwork_cache = _bind_deps(
        _core_now_playing._clear_music_artwork_cache,
        apple_tv_auto_state=apple_tv_auto_state,
    )

    _clear_video_artwork_cache = _bind_deps(
        _core_now_playing._clear_video_artwork_cache,
        apple_tv_auto_state=apple_tv_auto_state,
    )

    _clear_playback_artwork_caches = _bind_deps(
        _core_now_playing._clear_playback_artwork_caches,
        _clear_music_artwork_cache=_clear_music_artwork_cache,
        _clear_video_artwork_cache=_clear_video_artwork_cache,
    )

    _music_artwork_track_key = _core_now_playing._music_artwork_track_key

    _decode_artwork_bytes_bgra = _core_now_playing._decode_artwork_bytes_bgra

    _circles_poster_bgra = _bind_deps(
        _core_now_playing._circles_poster_bgra,
        _active_tmdb_poster_bgra=_active_tmdb_poster_bgra,
        _vv_is_music=_late(lambda: _vv_is_music, "_vv_is_music"),
        _vv_is_youtube=_late(lambda: _vv_is_youtube, "_vv_is_youtube"),
        apple_tv_auto_state=apple_tv_auto_state,
    )
    ctx._circles_poster_bgra = _circles_poster_bgra

    _spawn_youtube_thumb_fetch = _bind_deps(
        _core_now_playing._spawn_youtube_thumb_fetch,
        _store_music_artwork_from_metadata=_late(lambda: _store_music_artwork_from_metadata, "_store_music_artwork_from_metadata"),
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        apple_tv_auto_state=apple_tv_auto_state,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        root=root,
        skip_cache=skip_cache,
    )
    ctx._spawn_youtube_thumb_fetch = _spawn_youtube_thumb_fetch

    _resolve_streaming_app_logo_bgra = _bind_deps(
        _core_view_one._resolve_streaming_app_logo_bgra,
        _PROJECT_DIR=_PROJECT_DIR,
        apple_tv_auto_state=apple_tv_auto_state,
        streaming_badge_state=streaming_badge_state,
    )

    _refresh_tmdb_tt_gradient_tint = _bind_deps(
        _core_tmdb_flow._refresh_tmdb_tt_gradient_tint,
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        tmdb_logo_patch_bgra=tmdb_logo_patch_bgra,
        tmdb_tt_gradient_bgr_holder=tmdb_tt_gradient_bgr_holder,
    )

    _warm_tmdb_logo_patch = _bind_deps(
        _core_tmdb_flow._warm_tmdb_logo_patch,
        _active_tmdb_logo_widget=_active_tmdb_logo_widget,
        _refresh_tmdb_tt_gradient_tint=_refresh_tmdb_tt_gradient_tint,
        _resolve_streaming_app_logo_bgra=_resolve_streaming_app_logo_bgra,
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        tmdb_logo_app_fallback_active=tmdb_logo_app_fallback_active,
        tmdb_logo_patch_bgra=tmdb_logo_patch_bgra,
    )
    ctx._warm_tmdb_logo_patch = _warm_tmdb_logo_patch

    # ---- View 1 fallback-variant detection (viewOne.01 .. .09) --------
    # These probe live state so ``_current_view_one_variant`` can route the
    # View-1 composition path through the correct fallback. See
    # ``pigeon/view_one_variants.py`` for the decision table.
    _playback_display_title = _bind_deps(
        _core_now_playing._playback_display_title,
        active_tmdb_display_title=active_tmdb_display_title,
        apple_tv_auto_state=apple_tv_auto_state,
    )

    _vv_has_content_title = _bind_deps(
        _core_now_playing._vv_has_content_title,
        _playback_display_title=_playback_display_title,
    )

    _vv_has_current_app = _bind_deps(
        _core_now_playing._vv_has_current_app,
        apple_tv_auto_state=apple_tv_auto_state,
        streaming_badge_state=streaming_badge_state,
    )

    _vv_has_tmdb_bd = _bind_deps(
        _core_tmdb_flow._vv_has_tmdb_bd,
        backdrop_app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit,
        backdrop_master_bgr=backdrop_master_bgr,
        saved_backdrop_app_logo_letterbox_fit=saved_backdrop_app_logo_letterbox_fit,
        saved_backdrop_master_bgr=saved_backdrop_master_bgr,
    )

    _vv_has_tmdb_tt = _bind_deps(
        _core_tmdb_flow._vv_has_tmdb_tt,
        active_tmdb_title_key=active_tmdb_title_key,
    )

    _vv_has_app_logo = _bind_deps(
        _core_now_playing._vv_has_app_logo,
        _resolve_streaming_app_logo_bgra=_resolve_streaming_app_logo_bgra,
    )

    _vv_is_music = _bind_deps(
        _core_now_playing._vv_is_music,
        apple_tv_auto_state=apple_tv_auto_state,
    )
    ctx._vv_is_music = _vv_is_music

    _vv_is_youtube = _bind_deps(
        _core_now_playing._vv_is_youtube,
        apple_tv_auto_state=apple_tv_auto_state,
        streaming_badge_state=streaming_badge_state,
    )
    ctx._vv_is_youtube = _vv_is_youtube

    _store_music_artwork_from_metadata = _bind_deps(
        _core_now_playing._store_music_artwork_from_metadata,
        _atv_metadata_is_content_idle=_atv_metadata_is_content_idle,
        _clear_music_artwork_cache=_clear_music_artwork_cache,
        _clear_playback_artwork_caches=_clear_playback_artwork_caches,
        _clear_video_artwork_cache=_clear_video_artwork_cache,
        _decode_artwork_bytes_bgra=_decode_artwork_bytes_bgra,
        _music_artwork_track_key=_music_artwork_track_key,
        _vv_is_youtube=_vv_is_youtube,
        apple_tv_auto_state=apple_tv_auto_state,
    )

    _vv_music_text_lines = _bind_deps(
        _core_now_playing._vv_music_text_lines,
        apple_tv_auto_state=apple_tv_auto_state,
    )

    _current_view_one_variant = _bind_deps(
        _core_view_one._current_view_one_variant,
        ViewOneLayout=ViewOneLayout,
        _view_one_layout_effective=_view_one_layout_effective,
        _vv_has_app_logo=_vv_has_app_logo,
        _vv_has_content_title=_vv_has_content_title,
        _vv_has_current_app=_vv_has_current_app,
        _vv_has_tmdb_bd=_vv_has_tmdb_bd,
        _vv_has_tmdb_tt=_vv_has_tmdb_tt,
        resolve_view_one_variant=resolve_view_one_variant,
    )

    _view_one_streaming_logo_duplicate_fallback = _bind_deps(
        _core_view_one._view_one_streaming_logo_duplicate_fallback,
        ViewOneVariant=ViewOneVariant,
        _current_view_one_variant=_current_view_one_variant,
    )

    _view_one_variant_uses_full_path = _bind_deps(
        _core_view_one._view_one_variant_uses_full_path,
        _current_view_one_variant=_current_view_one_variant,
        _view_one_is_pigeon_full=_view_one_is_pigeon_full,
        _view_one_is_pigeon_poster=_view_one_is_pigeon_poster,
        variant_uses_full_path=variant_uses_full_path,
    )

    _view_one_variant_uses_simple_path = _bind_deps(
        _core_view_one._view_one_variant_uses_simple_path,
        _current_view_one_variant=_current_view_one_variant,
        _stage_is_view_one_video_layout=_stage_is_view_one_video_layout,
        _view_one_is_pigeon_poster=_view_one_is_pigeon_poster,
        _view_one_is_pigeon_simple=_view_one_is_pigeon_simple,
        variant_uses_full_path=variant_uses_full_path,
    )

    _view_one_video_content_a_tt_contain_rect_design = _bind_deps(
        _core_view_one._view_one_video_content_a_tt_contain_rect_design,
        DESIGN_H=DESIGN_H,
        DESIGN_W=DESIGN_W,
        PATCH_LAYER_RECEIVER_AUDIO=PATCH_LAYER_RECEIVER_AUDIO,
        VIEW_ONE_BADGE_COL_RIGHT=VIEW_ONE_BADGE_COL_RIGHT,
        get_grid_geometry=get_grid_geometry,
        playback_lower_gradient_bgra=playback_lower_gradient_bgra,
        playback_overlay_widget=playback_overlay_widget,
        rect_for_span_at_cell=rect_for_span_at_cell,
        rect_for_span_top_right_at_cell=rect_for_span_top_right_at_cell,
        tmdb_tt_gradient_bgr_holder=tmdb_tt_gradient_bgr_holder,
    )

    _paste_bgra_contain_on_design = _bind_deps(
        _core_stage_render._paste_bgra_contain_on_design,
        DESIGN_H=DESIGN_H,
        DESIGN_W=DESIGN_W,
        alpha_blend_bgra_over_bgr=alpha_blend_bgra_over_bgr,
    )

    _paused_screen_font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}
    _bgr_from_bgra_cache: dict[str, object] = {"src_id": None, "bgr": None}

    _stable_bgr_from_bgra = _bind_deps(
        _core_now_playing._stable_bgr_from_bgra,
        _bgr_from_bgra_cache=_bgr_from_bgra_cache,
    )

    _paused_screen_artwork_bgr = _bind_deps(
        _core_now_playing._paused_screen_artwork_bgr,
        _stable_bgr_from_bgra=_stable_bgr_from_bgra,
        apple_tv_auto_state=apple_tv_auto_state,
    )

    _paused_screen_backdrop_bgr = _bind_deps(
        _core_saver_state._paused_screen_backdrop_bgr,
        _circles_poster_bgra=_circles_poster_bgra,
        _paused_screen_artwork_bgr=_paused_screen_artwork_bgr,
        _stable_bgr_from_bgra=_stable_bgr_from_bgra,
        _vv_is_music=_vv_is_music,
        backdrop_app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit,
        backdrop_master_bgr=backdrop_master_bgr,
        saved_backdrop_app_logo_letterbox_fit=saved_backdrop_app_logo_letterbox_fit,
        saved_backdrop_master_bgr=saved_backdrop_master_bgr,
    )
    ctx._paused_screen_backdrop_bgr = _paused_screen_backdrop_bgr

    _auto_widget_signals = _bind_deps(
        _core_saver_state._auto_widget_signals,
        _apple_tv_is_off=_apple_tv_is_off,
        _clock_saver_receiver_off=_clock_saver_receiver_off,
        _paused_screen_backdrop_bgr=_paused_screen_backdrop_bgr,
        _player_metadata_class=_player_metadata_class,
        _program_audio_session=_program_audio_session,
        _refresh_paused_row_stamp=_refresh_paused_row_stamp,
        current_apple_tv=current_apple_tv,
        main_settings_widget=main_settings_widget_holder[0],
        view_circles_widget=view_circles_widget_holder[0],
    )

    _apply_auto_widget_policy = _bind_deps(
        _core_saver_state._apply_auto_widget_policy,
        DevPhase=DevPhase,
        _auto_widget_signals=_auto_widget_signals,
        _paused_screen_backdrop_bgr=_paused_screen_backdrop_bgr,
        active_tmdb_title_key=active_tmdb_title_key,
        apple_tv_auto_state=apple_tv_auto_state,
        dev_phase=dev_phase,
        main_settings_widget=main_settings_widget_holder[0],
        skip_cache=skip_cache,
    )
    ctx._apply_auto_widget_policy = _apply_auto_widget_policy

    _paused_screen_active = _bind_deps(
        _core_saver_state._paused_screen_active,
        DevPhase=DevPhase,
        _apply_auto_widget_policy=_apply_auto_widget_policy,
        _clock_saver_active=_clock_saver_active,
        _clock_saver_user_enabled=_clock_saver_user_enabled,
        _paused_screen_backdrop_bgr=_paused_screen_backdrop_bgr,
        _show_paused_row_overlay=_show_paused_row_overlay,
        _vv_is_music=_vv_is_music,
        clock_saver_composite_bgra=clock_saver_composite_bgra,
        clock_saver_force_on=clock_saver_force_on,
        dev_phase=dev_phase,
    )

    _paused_screen_font = _bind_deps(
        _core_saver_state._paused_screen_font,
        _paused_screen_font_cache=_paused_screen_font_cache,
    )

    _compose_paused_screen = _bind_deps(
        _core_saver_state._compose_paused_screen,
        PAUSED_SCREEN_BACKDROP_DIM=PAUSED_SCREEN_BACKDROP_DIM,
        _paused_screen_backdrop_bgr=_paused_screen_backdrop_bgr,
        _paused_screen_font=_paused_screen_font,
    )

    _current_app_display_name = _bind_deps(
        _core_now_playing._current_app_display_name,
        apple_tv_auto_state=apple_tv_auto_state,
        streaming_badge_state=streaming_badge_state,
    )

    _refresh_clock_patch_bgra = _bind_deps(
        _core_stage_render._refresh_clock_patch_bgra,
        _clock_patch_sig=_clock_patch_sig,
        clock_patch_bgra=clock_patch_bgra,
        clock_widget=clock_widget,
        info_cluster_clock_widget=info_cluster_clock_widget,
        status_bar_widget=status_bar_widget,
    )

    _playback_overlay_fast_sig: list[tuple[bool, bool, bool, bool, bool] | None] = [None]
    _view1_canvas_bgr: list[np.ndarray | None] = [None]

    _acquire_view1_canvas = _bind_deps(
        _core_view_one._acquire_view1_canvas,
        DESIGN_H=DESIGN_H,
        DESIGN_W=DESIGN_W,
        _view1_canvas_bgr=_view1_canvas_bgr,
    )

    compose_display_fast_no_grid = _bind_deps(
        _core_stage_render.compose_display_fast_no_grid,
        CLOCK_ANCHOR_COL=CLOCK_ANCHOR_COL,
        CLOCK_ANCHOR_ROW=CLOCK_ANCHOR_ROW,
        DESIGN_H=DESIGN_H,
        DESIGN_W=DESIGN_W,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        PATCH_LAYER_RECEIVER_AUDIO=PATCH_LAYER_RECEIVER_AUDIO,
        SceneFit=SceneFit,
        _PIGEON_EXT=_PIGEON_EXT,
        _acquire_view1_canvas=_acquire_view1_canvas,
        _active_tmdb_logo_widget=_active_tmdb_logo_widget,
        _apply_auto_widget_policy=_apply_auto_widget_policy,
        _apply_brightness=_apply_brightness,
        _backdrop_active_for_view=_backdrop_active_for_view,
        _blend_info_cluster_into_target=_blend_info_cluster_into_target,
        _blend_top_gradient_fast=_blend_top_gradient_fast,
        _blit_saver_layers_design=_blit_saver_layers_design,
        _blit_saver_layers_target=_blit_saver_layers_target,
        _clock_saver_backdrop_brightness=_clock_saver_backdrop_brightness,
        _clock_saver_dim_overlay_bgra=_clock_saver_dim_overlay_bgra,
        _clock_saver_dim_pre_digit_canvas=_clock_saver_dim_pre_digit_canvas,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _clock_saver_layer_opacity=_clock_saver_layer_opacity,
        _clock_saver_layers=_clock_saver_layers,
        _clock_startup_intro_opacity=_clock_startup_intro_opacity,
        _compose_paused_screen=_compose_paused_screen,
        _composite_cap_dims=_composite_cap_dims,
        _composite_settings_on_canvas=_composite_settings_on_canvas,
        _design_rect_to_target=_design_rect_to_target,
        _disp_fit=_disp_fit,
        _effective_display_view=_effective_display_view,
        _hitch_parts=_hitch_parts,
        _idle_audio_meter_active=_idle_audio_meter_active,
        _info_cluster_compose_active=_info_cluster_compose_active,
        _location_toast_alpha=_late(lambda: ctx._location_toast_alpha, "_location_toast_alpha"),
        _paused_screen_active=_paused_screen_active,
        _playback_overlay_fast_sig=_playback_overlay_fast_sig,
        _present_frame_to_display=_present_frame_to_display,
        _refresh_clock_patch_bgra=_refresh_clock_patch_bgra,
        _set_playback_overlay_clock_saver_volume_flag=_set_playback_overlay_clock_saver_volume_flag,
        _show_paused_row_overlay=_show_paused_row_overlay,
        _splash_reveal_clock=_splash_reveal_clock,
        _sync_now_playing_screen_state_for_frame=_sync_now_playing_screen_state_for_frame,
        _view_one_is_pigeon_poster=_view_one_is_pigeon_poster,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        _view_one_video_content_a_tt_contain_rect_design=_view_one_video_content_a_tt_contain_rect_design,
        _vv_is_music=_vv_is_music,
        _warm_playback_overlay_blits=_warm_playback_overlay_blits,
        _warm_tmdb_logo_patch=_warm_tmdb_logo_patch,
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        alpha_blend_bgra_over_bgr=alpha_blend_bgra_over_bgr,
        clock_patch_bgra=clock_patch_bgra,
        clock_saver_composite_bgra=clock_saver_composite_bgra,
        clock_widget=clock_widget,
        dev_phase=dev_phase,
        display_dims=display_dims,
        location_toast_patch_bgra=location_toast_patch_bgra,
        location_toast_state=location_toast_state,
        main_settings_widget=main_settings_widget_holder[0],
        playback_lower_gradient_bgra=playback_lower_gradient_bgra,
        playback_overlay_blits=playback_overlay_blits,
        playback_overlay_flags=playback_overlay_flags,
        playback_overlay_widget=playback_overlay_widget,
        startup_ph=startup_ph,
        status_bar_blits=status_bar_blits,
        status_bar_widget=status_bar_widget,
        tmdb_tt_gradient_bgr_holder=tmdb_tt_gradient_bgr_holder,
        view_circles_widget=view_circles_widget_holder[0],
    )

    compose_display_from_source = _bind_deps(
        _core_stage_render.compose_display_from_source,
        CLOCK_ANCHOR_COL=CLOCK_ANCHOR_COL,
        CLOCK_ANCHOR_ROW=CLOCK_ANCHOR_ROW,
        DESIGN_H=DESIGN_H,
        DESIGN_W=DESIGN_W,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        PATCH_LAYER_RECEIVER_AUDIO=PATCH_LAYER_RECEIVER_AUDIO,
        SceneFit=SceneFit,
        _PIGEON_EXT=_PIGEON_EXT,
        _active_tmdb_logo_widget=_active_tmdb_logo_widget,
        _active_tmdb_poster_bgra=_active_tmdb_poster_bgra,
        _apply_auto_widget_policy=_apply_auto_widget_policy,
        _apply_brightness=_apply_brightness,
        _blend_info_cluster_into_target=_blend_info_cluster_into_target,
        _blend_top_gradient_design=_blend_top_gradient_design,
        _blit_saver_layers_design=_blit_saver_layers_design,
        _clock_saver_backdrop_brightness=_clock_saver_backdrop_brightness,
        _clock_saver_dim_overlay_bgra=_clock_saver_dim_overlay_bgra,
        _clock_saver_dim_pre_digit_canvas=_clock_saver_dim_pre_digit_canvas,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _clock_saver_layer_opacity=_clock_saver_layer_opacity,
        _clock_saver_layers=_clock_saver_layers,
        _clock_startup_intro_opacity=_clock_startup_intro_opacity,
        _compose_paused_screen=_compose_paused_screen,
        _composite_cap_dims=_composite_cap_dims,
        _composite_settings_on_canvas=_composite_settings_on_canvas,
        _effective_display_view=_effective_display_view,
        _hitch_parts=_hitch_parts,
        _idle_audio_meter_active=_idle_audio_meter_active,
        _info_cluster_compose_active=_info_cluster_compose_active,
        _location_toast_alpha=_late(lambda: ctx._location_toast_alpha, "_location_toast_alpha"),
        _maybe_exit_settings_menus_on_idle=_maybe_exit_settings_menus_on_idle,
        _paused_screen_active=_paused_screen_active,
        _present_frame_to_display=_present_frame_to_display,
        _set_playback_overlay_clock_saver_volume_flag=_set_playback_overlay_clock_saver_volume_flag,
        _settings_is_native_1280=_settings_is_native_1280,
        _show_paused_row_overlay=_show_paused_row_overlay,
        _splash_reveal_clock=_splash_reveal_clock,
        _stage_grid_overlay_mode=_stage_grid_overlay_mode,
        _styled_video_content_c_poster=_styled_video_content_c_poster,
        _sync_now_playing_screen_state_for_frame=_sync_now_playing_screen_state_for_frame,
        _view_one_is_pigeon_poster=_view_one_is_pigeon_poster,
        _view_one_uses_now_playing_screen=_view_one_uses_now_playing_screen,
        _view_one_video_content_a_tt_contain_rect_design=_view_one_video_content_a_tt_contain_rect_design,
        _vv_is_music=_vv_is_music,
        _warm_playback_overlay_blits=_warm_playback_overlay_blits,
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        alpha_blend_bgra_over_bgr=alpha_blend_bgra_over_bgr,
        blend_overlay_bgr=blend_overlay_bgr,
        build_stage_overlay_source_bgra=build_stage_overlay_source_bgra,
        clock_widget=clock_widget,
        dev_phase=dev_phase,
        display_dims=display_dims,
        get_grid_geometry=get_grid_geometry,
        location_toast_patch_bgra=location_toast_patch_bgra,
        location_toast_state=location_toast_state,
        main_settings_widget=main_settings_widget_holder[0],
        playback_lower_gradient_bgra=playback_lower_gradient_bgra,
        playback_overlay_flags=playback_overlay_flags,
        playback_overlay_widget=playback_overlay_widget,
        scale_cover_center_crop=scale_cover_center_crop,
        scale_height_and_center_crop=scale_height_and_center_crop,
        startup_ph=startup_ph,
        status_bar_widget=status_bar_widget,
        tmdb_tt_gradient_bgr_holder=tmdb_tt_gradient_bgr_holder,
        view_circles_widget=view_circles_widget_holder[0],
    )

    _view_four_text_is_placeholder = _core_view_four._view_four_text_is_placeholder

    _view_four_has_value = _bind_deps(
        _core_view_four._view_four_has_value,
        _view_four_has_value=_late(lambda: _view_four_has_value, "_view_four_has_value"),
        _view_four_text_is_placeholder=_view_four_text_is_placeholder,
    )

    _view_four_display_metadata = _bind_deps(
        _core_view_four._view_four_display_metadata,
        apple_tv_auto_state=apple_tv_auto_state,
    )

    _collect_view_four_raw_title_lines = _bind_deps(
        _core_view_four._collect_view_four_raw_title_lines,
        _tmdb_info_current_and_available=_tmdb_info_current_and_available,
        _view_four_display_metadata=_view_four_display_metadata,
        _view_four_has_value=_view_four_has_value,
        _view_four_text_is_placeholder=_view_four_text_is_placeholder,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
        receiver_debug_holder=receiver_debug_holder,
        streaming_badge_state=streaming_badge_state,
    )

    _metadata_debug_provider = _bind_deps(
        _core_now_playing._metadata_debug_provider,
        _content_indicator_ok=_late(lambda: ctx._content_indicator_ok, "_content_indicator_ok"),
        _tmdb_info_current_and_available=_tmdb_info_current_and_available,
        _view_four_display_metadata=_view_four_display_metadata,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
        streaming_badge_state=streaming_badge_state,
    )

    try:
        from pigeon.widgets.metadata_debug import set_metadata_debug_data_provider

        set_metadata_debug_data_provider(_metadata_debug_provider)
    except Exception:
        pass

    _collect_view_four_source_lines = _bind_deps(
        _core_view_four._collect_view_four_source_lines,
        _view_four_display_metadata=_view_four_display_metadata,
        _view_four_has_value=_view_four_has_value,
        _view_four_text_is_placeholder=_view_four_text_is_placeholder,
        receiver_overlay_state=receiver_overlay_state,
    )

    _collect_view_four_playback_lines = _bind_deps(
        _core_view_four._collect_view_four_playback_lines,
        _view_four_display_metadata=_view_four_display_metadata,
        _view_four_has_value=_view_four_has_value,
        _view_four_text_is_placeholder=_view_four_text_is_placeholder,
        cap=cap,
        display_dims=display_dims,
        frame_interval_ms=frame_interval_ms,
        receiver_overlay_state=receiver_overlay_state,
    )

    _blend_view_four_debug = _bind_deps(
        _core_view_four._blend_view_four_debug,
        DisplayView=DisplayView,
        _collect_view_four_playback_lines=_collect_view_four_playback_lines,
        _collect_view_four_raw_title_lines=_collect_view_four_raw_title_lines,
        _collect_view_four_source_lines=_collect_view_four_source_lines,
        _effective_display_view=_effective_display_view,
        view_four_subview_holder=view_four_subview_holder,
    )

    _compose_shown_frame = _bind_deps(
        _core_stage_render._compose_shown_frame,
        DESIGN_H=DESIGN_H,
        DESIGN_W=DESIGN_W,
        DisplayView=DisplayView,
        SceneFit=SceneFit,
        ViewOneVariant=ViewOneVariant,
        _PIGEON_EXT=_PIGEON_EXT,
        _PROJECT_DIR=_PROJECT_DIR,
        _app_logo_clock_saver_style_now=_app_logo_clock_saver_style_now,
        _apply_brightness=_apply_brightness,
        _backdrop_active_for_view=_backdrop_active_for_view,
        _black_screen_bgr=_black_screen_bgr,
        _clock_saver_for_compose=_clock_saver_for_compose,
        _composite_cap_dims=_composite_cap_dims,
        _current_app_display_name=_current_app_display_name,
        _current_view_one_variant=_current_view_one_variant,
        _design_grid_overlay_active=_design_grid_overlay_active,
        _effective_display_view=_effective_display_view,
        _paste_bgra_contain_on_design=_paste_bgra_contain_on_design,
        _playback_display_title=_playback_display_title,
        _present_frame_to_display=_present_frame_to_display,
        _resolve_streaming_app_logo_bgra=_resolve_streaming_app_logo_bgra,
        _view_one_is_pigeon_poster=_view_one_is_pigeon_poster,
        _view_one_variant_uses_full_path=_view_one_variant_uses_full_path,
        _view_one_variant_uses_simple_path=_view_one_variant_uses_simple_path,
        _view_one_video_content_a_tt_contain_rect_design=_view_one_video_content_a_tt_contain_rect_design,
        _vv_has_content_title=_vv_has_content_title,
        _vv_has_tmdb_bd=_vv_has_tmdb_bd,
        _vv_is_music=_vv_is_music,
        _vv_music_text_lines=_vv_music_text_lines,
        backdrop_app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit,
        backdrop_master_bgr=backdrop_master_bgr,
        compose_display_fast_no_grid=compose_display_fast_no_grid,
        compose_display_from_source=compose_display_from_source,
        display_dims=display_dims,
        load_pigeon_temp_logo_bgra=load_pigeon_temp_logo_bgra,
        render_ui_music_text_patch_bgra=render_ui_music_text_patch_bgra,
        render_ui_text_patch_bgra=render_ui_text_patch_bgra,
        status_bar_widget=status_bar_widget,
        view_circles_widget=view_circles_widget_holder[0],
    )

    if _PIGEON_EXT:
        _warm_status_bar_blits()
        _warm_playback_overlay_blits()

    # Display off: no landing art (black / stage composite only in render_once).
    if not scene_enabled[0]:
        last_frame[0] = None
        scaled_display[0] = None
        scaled_version[0] = 0

    ctx._blend_view_four_debug = _blend_view_four_debug
    ctx._clear_playback_artwork_caches = _clear_playback_artwork_caches
    ctx._compose_shown_frame = _compose_shown_frame
    ctx._current_view_one_variant = _current_view_one_variant
    ctx._set_playback_overlay_clock_saver_volume_flag = _set_playback_overlay_clock_saver_volume_flag
    ctx._store_music_artwork_from_metadata = _store_music_artwork_from_metadata
    ctx._tmdb_poster_cache = _tmdb_poster_cache
    ctx._tmdb_tt_src_cache = _tmdb_tt_src_cache
    ctx._warm_playback_overlay_blits = _warm_playback_overlay_blits
    ctx._warm_view_one_under_splash = _warm_view_one_under_splash
