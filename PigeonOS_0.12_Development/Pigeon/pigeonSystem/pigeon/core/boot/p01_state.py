"""Boot phase: hoisted shared state, capture reset, and startup-placeholder handling.

Phase 1 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from pigeon.media_folders import consolidate_legacy_pigeondata_media_folders
import numpy as np
import sys
import tkinter as tk


def run(ctx) -> None:
    DevPhase = ctx.DevPhase
    _PIGEON_EXT = ctx._PIGEON_EXT
    _grid_patched = ctx._grid_patched
    _pack_patched = ctx._pack_patched
    _place_patched = ctx._place_patched
    cap = ctx.cap
    startup_ph = ctx.startup_ph

    # State created up front (hoisted; side-effect-free initialisers).
    main_settings_widget_holder = [None]
    update_btn_holder = [None]
    purge_image_media_btn_holder = [None]
    scene_enabled = [None]
    apple_tv_auto_state: dict[str, object] = {
        "running": False,
        "content_key": None,
        "tmdb_key": None,
        "query": None,
        "prefer": "auto",
        "tmdb_fetch_in_flight": False,
        # Latest requested fetch while a worker is already running (drained in finish_tmdb).
        "pending_tmdb": None,
        "last_metadata": None,
        # Last TMDb worker actually started (see spawn_tmdb_poster_fetch); for view 4 debug.
        "last_tmdb_fetch_input": None,
        "last_tmdb_fetch_refined": None,
        "last_tmdb_fetch_prefer": None,
        # Music album art from pyatv ``metadata.artwork()`` (BGRA + track key).
        "music_artwork_bgra": None,
        "music_artwork_key": None,
        # YouTube (and other 16×9) thumbs from pyatv ``metadata.artwork()``.
        "video_artwork_bgra": None,
        "video_artwork_key": None,
        "youtube_thumb_in_flight": False,
        "youtube_thumb_key": None,
        # After no-match / exhausted error-flag retries: stop empty-display poll respawn
        # and show "?" in the circles 2×3 poster slot.
        "tmdb_missing_art": False,
        "tmdb_exhausted_identity": None,
        # One HDMI frame check (clock-saver fingerprint) at a time.
        "hdmi_check_in_flight": False,
        # Last human-readable title decision (also mirrored on last_metadata).
        "last_title_decision": None,
    }
    apple_tv_playback_clock: dict[str, object] = {
        "has_sync": False,
        "sync_mono": 0.0,
        "sync_position": 0.0,
        "live_mode": False,
        "playing": False,
        "latched_total": None,
        "latched_content_key": None,
        "last_reported_total": None,
        # Steady on-screen TRT: integer shown seconds (slewed), not raw extrapolation.
        "display_played_sec": None,
        "trt_next_fire_mono": None,
    }
    apple_tv_dashboard_track: dict[str, object] = {"last_poll_ok": None, "consecutive_fail": 0}
    skip_cache: list[tuple[object, ...] | None] = [None]
    dev_phase = [DevPhase.OFF]
    # Manual [2] force: True = show saver until toggled off (ignores idle timers).
    clock_saver_force_on: list[bool] = [False]
    active_tmdb_title_key: list[str | None] = [None]
    active_tmdb_display_title: list[str | None] = [None]
    streaming_badge_state: dict[str, object] = {
        "show": False,
        "filename": "",
        "label": "",
    }
    _startup_splash_complete: list[bool] = [False]
    tmdb_logo_patch_bgra: list[np.ndarray | None] = [None]

    cap[0] = None

    if not _PIGEON_EXT:
        _w0 = startup_ph[0]
        if _w0 is not None:
            try:
                _w0.destroy()
            except tk.TclError:
                pass
            startup_ph[0] = None
    else:
        tk.Widget.pack = _pack_patched  # type: ignore[method-assign]
        tk.Widget.grid = _grid_patched  # type: ignore[method-assign]
        tk.Widget.place = _place_patched  # type: ignore[method-assign]

    try:
        mig = consolidate_legacy_pigeondata_media_folders()
        for line in mig:
            sys.stderr.write(f"pigeon: media folders: {line}\n")
        if mig:
            sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"pigeon: media folder consolidation: {e}\n")
        sys.stderr.flush()

    ctx._startup_splash_complete = _startup_splash_complete
    ctx.active_tmdb_display_title = active_tmdb_display_title
    ctx.active_tmdb_title_key = active_tmdb_title_key
    ctx.apple_tv_auto_state = apple_tv_auto_state
    ctx.apple_tv_dashboard_track = apple_tv_dashboard_track
    ctx.apple_tv_playback_clock = apple_tv_playback_clock
    ctx.clock_saver_force_on = clock_saver_force_on
    ctx.dev_phase = dev_phase
    ctx.main_settings_widget_holder = main_settings_widget_holder
    ctx.purge_image_media_btn_holder = purge_image_media_btn_holder
    ctx.scene_enabled = scene_enabled
    ctx.skip_cache = skip_cache
    ctx.streaming_badge_state = streaming_badge_state
    ctx.tmdb_logo_patch_bgra = tmdb_logo_patch_bgra
    ctx.update_btn_holder = update_btn_holder
