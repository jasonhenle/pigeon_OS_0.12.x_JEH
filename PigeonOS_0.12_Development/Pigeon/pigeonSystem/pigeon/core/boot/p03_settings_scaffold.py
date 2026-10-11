"""Boot phase: settings frame, scroll canvas, fonts, mouse-wheel scrolling and activity tracking.

Phase 3 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from pigeon.core import saver_state as _core_saver_state
from pigeon.core import settings_ui as _core_settings_ui
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.core.binding import late as _late
import time
import tkinter as tk
import tkinter.font as tkfont


def run(ctx) -> None:
    DevPhase = ctx.DevPhase
    SETTINGS_MENU_IDLE_EXIT_S = ctx.SETTINGS_MENU_IDLE_EXIT_S
    _format_hmmss = ctx._format_hmmss
    active_tmdb_display_title = ctx.active_tmdb_display_title
    active_tmdb_title_key = ctx.active_tmdb_title_key
    apple_tv_auto_state = ctx.apple_tv_auto_state
    apple_tv_playback_clock = ctx.apple_tv_playback_clock
    dev_phase = ctx.dev_phase
    main_settings_widget_holder = ctx.main_settings_widget_holder
    root = ctx.root
    skip_cache = ctx.skip_cache
    streaming_badge_state = ctx.streaming_badge_state
    video_area = ctx.video_area

    # Deprecated Tk settings form (never packed). Runtime state helpers below still
    # attach holders here; UI is settings_main SVG only (DevPhase.MAIN_SETTINGS).
    settings_frame = tk.Frame(video_area, bg="#111")
    settings_scroll_outer = tk.Frame(settings_frame, bg="#111")
    settings_scroll_outer.pack(fill=tk.BOTH, expand=True)
    settings_canvas = tk.Canvas(
        settings_scroll_outer,
        bg="#111",
        highlightthickness=0,
        bd=0,
    )
    settings_scrollbar = tk.Scrollbar(
        settings_scroll_outer,
        orient=tk.VERTICAL,
        command=settings_canvas.yview,
        bg="#2a2a2e",
        troughcolor="#111",
        activebackground="#3a3a40",
        highlightthickness=0,
    )
    settings_canvas.configure(yscrollcommand=settings_scrollbar.set)
    settings_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    settings_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    settings_inner = tk.Frame(settings_canvas, bg="#111")
    _settings_inner_win = settings_canvas.create_window((16, 12), window=settings_inner, anchor=tk.NW)

    _tk_font_families = frozenset(tkfont.families(root))
    _settings_sans_face = "Helvetica"
    for _cand in (
        "SharpSans",
        "Sharp Sans",
        "SharpSans-Medium",
        "Sharp Sans Medium",
        "SharpSansMedium",
        "Sharp Sans No2",
        "Sharp Sans No1",
    ):
        if _cand in _tk_font_families:
            _settings_sans_face = _cand
            break
    else:
        if "Helvetica Neue" in _tk_font_families:
            _settings_sans_face = "Helvetica Neue"
    _S = _settings_sans_face
    S_FONT_PAGE = (_S, 18, "bold")
    S_FONT_SEC = (_S, 12, "bold")
    S_FONT_BODY = (_S, 10)
    S_FONT_STATUS = (_S, 11)
    S_FONT_BTN = (_S, 11)
    S_FONT_SMALL = (_S, 9)
    S_FONT_MICRO = (_S, 9)
    S_FONT_CAP_BOLD = (_S, 9, "bold")

    tk.Label(
        settings_inner,
        text="Pigeon Settings",
        fg="#f5f5f5",
        bg="#111",
        font=S_FONT_PAGE,
    ).pack(anchor=tk.W, pady=(0, 4))

    # Inner <Configure> fires often while scrolling an embedded window; only refresh scrollregion
    # when the inner frame actually changes size to avoid canvas flicker / jumpy redraws.
    _settings_inner_scroll_size: list[int] = [0, 0]

    _settings_update_scrollregion = _bind_deps(
        _core_settings_ui._settings_update_scrollregion,
        _settings_inner_scroll_size=_settings_inner_scroll_size,
        settings_canvas=settings_canvas,
        settings_inner=settings_inner,
    )

    _settings_on_canvas_configure = _bind_deps(
        _core_settings_ui._settings_on_canvas_configure,
        _settings_inner_win=_settings_inner_win,
        _settings_update_scrollregion=_settings_update_scrollregion,
        root=root,
        settings_canvas=settings_canvas,
    )

    settings_inner.bind("<Configure>", _settings_update_scrollregion)
    settings_canvas.bind("<Configure>", _settings_on_canvas_configure)

    settings_wheel_all_bound = [False]
    last_pigeon_user_activity_mono = [time.monotonic()]
    # Shared with metadata-idle clock saver (defined early so control bumps can dismiss it).
    last_metadata_activity_mono = [time.monotonic()]
    # Until playback is seen (or the user uses a control), stay on the clock saver after splash.
    _boot_clock_saver_until_playback = [True]

    _bump_pigeon_user_activity = _bind_deps(
        _core_saver_state._bump_pigeon_user_activity,
        _boot_clock_saver_until_playback=_boot_clock_saver_until_playback,
        last_metadata_activity_mono=last_metadata_activity_mono,
        last_pigeon_user_activity_mono=last_pigeon_user_activity_mono,
    )

    _maybe_exit_settings_menus_on_idle = _bind_deps(
        _core_settings_ui._maybe_exit_settings_menus_on_idle,
        DevPhase=DevPhase,
        SETTINGS_MENU_IDLE_EXIT_S=SETTINGS_MENU_IDLE_EXIT_S,
        dev_phase=dev_phase,
        last_pigeon_user_activity_mono=last_pigeon_user_activity_mono,
        main_settings_widget_holder=main_settings_widget_holder,
        skip_cache=skip_cache,
        sync_developer_chrome=_late(lambda: ctx.sync_developer_chrome, "sync_developer_chrome"),
    )

    _sync_preferences_now_playing_progress = _bind_deps(
        _core_settings_ui._sync_preferences_now_playing_progress,
        _active_tmdb_tt_src_bgra=_late(lambda: ctx._active_tmdb_tt_src_bgra, "_active_tmdb_tt_src_bgra"),
        _circles_poster_bgra=_late(lambda: ctx._circles_poster_bgra, "_circles_poster_bgra"),
        _format_hmmss=_format_hmmss,
        _playback_extrapolated_pair=_late(lambda: ctx._playback_extrapolated_pair, "_playback_extrapolated_pair"),
        _playback_progress_fraction_for_bar=_late(lambda: ctx._playback_progress_fraction_for_bar, "_playback_progress_fraction_for_bar"),
        _resolve_receiver_lines_for_now_playing=_late(lambda: ctx._resolve_receiver_lines_for_now_playing, "_resolve_receiver_lines_for_now_playing"),
        _vv_is_music=_late(lambda: ctx._vv_is_music, "_vv_is_music"),
        active_tmdb_display_title=active_tmdb_display_title,
        active_tmdb_title_key=active_tmdb_title_key,
        apple_tv_auto_state=apple_tv_auto_state,
        apple_tv_playback_clock=apple_tv_playback_clock,
        main_settings_widget_holder=main_settings_widget_holder,
        streaming_badge_state=streaming_badge_state,
    )

    _settings_unbind_wheel_globals = _bind_deps(
        _core_settings_ui._settings_unbind_wheel_globals,
        root=root,
        settings_wheel_all_bound=settings_wheel_all_bound,
    )

    on_purge_image_media = _bind_deps(_core_settings_ui.on_purge_image_media, root=root)

    ctx.S_FONT_BODY = S_FONT_BODY
    ctx.S_FONT_BTN = S_FONT_BTN
    ctx.S_FONT_CAP_BOLD = S_FONT_CAP_BOLD
    ctx.S_FONT_MICRO = S_FONT_MICRO
    ctx.S_FONT_SEC = S_FONT_SEC
    ctx.S_FONT_SMALL = S_FONT_SMALL
    ctx.S_FONT_STATUS = S_FONT_STATUS
    ctx._S = _S
    ctx._boot_clock_saver_until_playback = _boot_clock_saver_until_playback
    ctx._bump_pigeon_user_activity = _bump_pigeon_user_activity
    ctx._maybe_exit_settings_menus_on_idle = _maybe_exit_settings_menus_on_idle
    ctx._settings_unbind_wheel_globals = _settings_unbind_wheel_globals
    ctx._sync_preferences_now_playing_progress = _sync_preferences_now_playing_progress
    ctx.last_metadata_activity_mono = last_metadata_activity_mono
    ctx.last_pigeon_user_activity_mono = last_pigeon_user_activity_mono
    ctx.on_purge_image_media = on_purge_image_media
    ctx.settings_canvas = settings_canvas
    ctx.settings_frame = settings_frame
    ctx.settings_inner = settings_inner
    ctx.settings_scroll_outer = settings_scroll_outer
