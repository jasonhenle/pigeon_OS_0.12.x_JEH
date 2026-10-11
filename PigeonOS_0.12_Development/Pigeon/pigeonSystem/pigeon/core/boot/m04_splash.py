"""Main-window phase: splash caches, the Tk pack / grid / place pump, splash playback, and the first paint.

Phase 4 of ``main()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from PIL import ImageTk
from pigeon.core import splash as _core_splash
from pigeon.core import startup as _core_startup
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.core.binding import bind_method_deps as _bind_method_deps
from pigeon.core.binding import late as _late
from pigeon.splash_mpv import SplashMpv, splash_mpv_enabled, splash_mpv_video_path
from pigeon.splash_sequence import (
    SPLASH_HOLD_LOGO_FRAME,
    SPLASH_PREBAKE_AHEAD_FRAMES,
    SPLASH_START_LEAD_FRAMES,
)
import cv2
import numpy as np
import sys
import threading
import tkinter as tk


def run(ctx) -> None:
    FALLBACK_SPLASH_FRAME_COUNT = ctx.FALLBACK_SPLASH_FRAME_COUNT
    PAUSED_COMPOSITE_MS = ctx.PAUSED_COMPOSITE_MS
    SPLASH_CLOCK_REVEAL_FRAME = ctx.SPLASH_CLOCK_REVEAL_FRAME
    SPLASH_FADE_OUT_FRAMES = ctx.SPLASH_FADE_OUT_FRAMES
    SPLASH_FPS = ctx.SPLASH_FPS
    SPLASH_MAX_DURATION_S = ctx.SPLASH_MAX_DURATION_S
    UI_TARGET_H = ctx.UI_TARGET_H
    UI_TARGET_W = ctx.UI_TARGET_W
    WINDOW_H = ctx.WINDOW_H
    WINDOW_W = ctx.WINDOW_W
    _PIGEON_EXT = ctx._PIGEON_EXT
    _app_startup_mono = ctx._app_startup_mono
    _bgr_to_tk_image = ctx._bgr_to_tk_image
    _bgra_to_display_window = ctx._bgra_to_display_window
    _boot_clock_label = ctx._boot_clock_label
    _boot_clock_photo = ctx._boot_clock_photo
    _finish_post_splash_startup_transition = ctx._finish_post_splash_startup_transition
    _rasterize_clock_saver_window_bgr = ctx._rasterize_clock_saver_window_bgr
    _reveal_clock_under_splash = ctx._reveal_clock_under_splash
    _splash_clock_ready_bgr = ctx._splash_clock_ready_bgr
    _splash_clock_refresh_stop = ctx._splash_clock_refresh_stop
    _splash_reveal_clock = ctx._splash_reveal_clock
    _splash_underlay_bgr = ctx._splash_underlay_bgr
    _splash_underlay_paint_mono = ctx._splash_underlay_paint_mono
    apply_splash_global_alpha = ctx.apply_splash_global_alpha
    bootstrap_done = ctx.bootstrap_done
    builtin_splash_bgra_frame = ctx.builtin_splash_bgra_frame
    content_host = ctx.content_host
    flatten_bgra_over_bg_to_rgb = ctx.flatten_bgra_over_bg_to_rgb
    load_splash_bgra = ctx.load_splash_bgra
    post_splash_mono = ctx.post_splash_mono
    root = ctx.root
    shell = ctx.shell
    splash_anim_done = ctx.splash_anim_done
    splash_bootstrap_go = ctx.splash_bootstrap_go
    splash_effective_frame_count = ctx.splash_effective_frame_count
    splash_end_fade_factor = ctx.splash_end_fade_factor
    splash_keep_alpha_for_live_clock = ctx.splash_keep_alpha_for_live_clock
    splash_png_paths = ctx.splash_png_paths
    splash_video_path = ctx.splash_video_path
    startup_ph = ctx.startup_ph

    # Splash caches, bound up front (were inside ``if _PIGEON_EXT:``) so helpers
    # defined before that block can take them as dependencies.
    splash_photo: list[ImageTk.PhotoImage | None] = [None]
    # Two parallel caches keyed by frame index:
    #   * _splash_rgb_cache: opaque RGB over black for pre-reveal frames.
    #   * _splash_bgra_cache: keep alpha for reveal frames so they composite over a live clock.
    _splash_rgb_cache: dict[int, np.ndarray] = {}
    _splash_bgra_cache: dict[int, np.ndarray] = {}
    _splash_photo_cache: dict[int, ImageTk.PhotoImage] = {}

    _try_remove_splash_overlay = _bind_deps(
        _core_startup._try_remove_splash_overlay,
        _PIGEON_EXT=_PIGEON_EXT,
        _app_startup_mono=_app_startup_mono,
        _finish_post_splash_startup_transition=_finish_post_splash_startup_transition,
        _reveal_clock_under_splash=_reveal_clock_under_splash,
        _splash_bgra_cache=_splash_bgra_cache,
        _splash_photo_cache=_splash_photo_cache,
        _splash_rgb_cache=_splash_rgb_cache,
        bootstrap_done=bootstrap_done,
        post_splash_mono=post_splash_mono,
        splash_anim_done=splash_anim_done,
        splash_photo=splash_photo,
        startup_ph=startup_ph,
    )

    _live_clock_until_compose = _bind_deps(
        _core_startup._live_clock_until_compose,
        _live_clock_until_compose=_late(lambda: _live_clock_until_compose, "_live_clock_until_compose"),
        _reveal_clock_under_splash=_reveal_clock_under_splash,
        _splash_clock_refresh_stop=_splash_clock_refresh_stop,
        _splash_reveal_clock=_splash_reveal_clock,
        bootstrap_done=bootstrap_done,
        root=root,
        splash_anim_done=splash_anim_done,
    )

    _tk_pack_orig = tk.Widget.pack
    _tk_grid_orig = tk.Widget.grid
    _tk_place_orig = tk.Widget.place
    _splash_pump_next: list[float] = [0.0]

    _splash_pump_maybe = _bind_deps(
        _core_startup._splash_pump_maybe,
        _PIGEON_EXT=_PIGEON_EXT,
        _reveal_clock_under_splash=_reveal_clock_under_splash,
        _splash_pump_next=_splash_pump_next,
        _splash_reveal_clock=_splash_reveal_clock,
        _splash_underlay_paint_mono=_splash_underlay_paint_mono,
        bootstrap_done=bootstrap_done,
        root=root,
        splash_anim_done=splash_anim_done,
    )

    _pack_patched = _bind_method_deps(
        _core_startup._pack_patched,
        _splash_pump_maybe=_splash_pump_maybe,
        _tk_pack_orig=_tk_pack_orig,
    )

    _grid_patched = _bind_method_deps(
        _core_startup._grid_patched,
        _splash_pump_maybe=_splash_pump_maybe,
        _tk_grid_orig=_tk_grid_orig,
    )

    _place_patched = _bind_method_deps(
        _core_startup._place_patched,
        _splash_pump_maybe=_splash_pump_maybe,
        _tk_place_orig=_tk_place_orig,
    )

    if _PIGEON_EXT:
        # Stay a direct child of ``shell`` (placed full-size). Do **not** pack into ``video_area`` after
        # the video ``Label``: two ``pack(..., fill=BOTH, expand=True)`` siblings leave the second with
        # zero height, so the splash would disappear. Transparent PNG / fade pixels show ``content_host``.
        splash_overlay = tk.Frame(shell, bg="#000", highlightthickness=0, bd=0, cursor="none")
        splash_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        # Placed widgets can sit under later-packed siblings (e.g. ``hud_bar``); pin above ``content_host``.
        try:
            splash_overlay.lift(content_host)
        except tk.TclError:
            try:
                splash_overlay.lift()
            except tk.TclError:
                pass
        startup_ph[0] = splash_overlay
        # Opaque black label: splash frames are always composited to RGB (never Tk alpha punch-through).
        splash_label = tk.Label(splash_overlay, bg="#000", bd=0, cursor="none")
        splash_label.pack(expand=True, fill="both")
        splash_idx = [0]
        # Set after a lead buffer is baked so the Pi does not skip/hitch on PNG decode.
        splash_t0: list[float | None] = [None]
        _splash_wait_deadline: list[float | None] = [None]
        _splash_bg_bgr = (0, 0, 0)
        # Black underlay until the reveal frame — transparent early PNG pixels must not show the UI.
        _splash_underlay_bgr[0] = np.zeros((WINDOW_H, WINDOW_W, 3), dtype=np.uint8)
        try:
            _boot_clock_photo[0] = _bgr_to_tk_image(_splash_underlay_bgr[0])
            _boot_clock_label.configure(image=_boot_clock_photo[0])
            _boot_clock_label.image = _boot_clock_photo[0]  # type: ignore[attr-defined]
        except Exception:
            pass
        # Keep rasterizing the live saver off the UI thread so splash reveal (and the
        # post-splash bridge) show wall-clock time and the current color — not a
        # frame frozen at process start.
        _prewarm_splash_clock_worker = _bind_deps(
            _core_splash._prewarm_splash_clock_worker,
            _rasterize_clock_saver_window_bgr=_rasterize_clock_saver_window_bgr,
            _splash_clock_ready_bgr=_splash_clock_ready_bgr,
            _splash_clock_refresh_stop=_splash_clock_refresh_stop,
            bootstrap_done=bootstrap_done,
        )

        try:
            threading.Thread(
                target=_prewarm_splash_clock_worker,
                name="pigeon-splash-clock-prewarm",
                daemon=True,
            ).start()
        except Exception:
            shown = _rasterize_clock_saver_window_bgr()
            if shown is not None:
                _splash_clock_ready_bgr[0] = shown

        # Resolve total frame count AND native fps up front. The PNG / built-in paths lock to
        # SPLASH_FPS, but a video drives its own cadence (e.g. 59.94) so the splash plays at
        # authored speed instead of being stretched or sped up by a hardcoded 30 Hz scheduler.
        _splash_fps_effective = float(max(1, SPLASH_FPS))
        if splash_video_path is not None:
            try:
                _probe = cv2.VideoCapture(str(splash_video_path))
                _vc_total = int(_probe.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                _vc_fps = float(_probe.get(cv2.CAP_PROP_FPS) or 0.0)
                _probe.release()
            except Exception:
                _vc_total = 0
                _vc_fps = 0.0
            splash_total_frames = max(1, _vc_total) if _vc_total > 0 else FALLBACK_SPLASH_FRAME_COUNT
            # Reject obviously-bogus fps values (VideoCapture sometimes returns 0 or 1000 on bad files).
            if 1.0 < _vc_fps < 240.0:
                _splash_fps_effective = _vc_fps
        elif splash_png_paths:
            splash_total_frames = len(splash_png_paths)
            # Drop trailing empty PNG frames (often 1s+ of held "last frame" after the art is gone).
            if callable(splash_effective_frame_count):
                try:
                    _trimmed = int(
                        splash_effective_frame_count(
                            splash_png_paths, reveal_frame=int(SPLASH_CLOCK_REVEAL_FRAME)
                        )
                    )
                    if 1 <= _trimmed < splash_total_frames:
                        sys.stderr.write(
                            f"pigeon: splash trim frames {splash_total_frames} → {_trimmed} "
                            f"(trailing transparent)\n"
                        )
                        sys.stderr.flush()
                        splash_total_frames = _trimmed
                except Exception:
                    pass
        else:
            splash_total_frames = FALLBACK_SPLASH_FRAME_COUNT

        frame_dt = 1.0 / _splash_fps_effective
        frame_ms = max(1, int(round(1000.0 * frame_dt)))

        # Cap by SPLASH_MAX_DURATION_S so a pathological asset can't block startup.
        _max_frames_for_duration = int(float(SPLASH_MAX_DURATION_S) * _splash_fps_effective)
        if _max_frames_for_duration > 0:
            splash_total_frames = min(splash_total_frames, _max_frames_for_duration)

        # Optional software fade-out (0 = none). Scale with source fps when configured.
        _splash_fade_frames = int(
            round(float(SPLASH_FADE_OUT_FRAMES) * _splash_fps_effective / float(max(1, SPLASH_FPS)))
        )
        if _splash_fade_frames < 0:
            _splash_fade_frames = 0
        _splash_fade_zone_start = max(
            0, splash_total_frames - min(_splash_fade_frames, splash_total_frames)
        )
        _splash_reveal_i = int(SPLASH_CLOCK_REVEAL_FRAME)

        _splash_frame_keeps_live_clock = _bind_deps(
            _core_splash._splash_frame_keeps_live_clock,
            _splash_reveal_i=_splash_reveal_i,
            splash_keep_alpha_for_live_clock=splash_keep_alpha_for_live_clock,
            splash_png_paths=splash_png_paths,
        )

        _splash_prebake_done = [False]

        _splash_photo_from_rgb = _core_splash._splash_photo_from_rgb

        _splash_prebuild_photos = _bind_deps(
            _core_splash._splash_prebuild_photos,
            _splash_frame_keeps_live_clock=_splash_frame_keeps_live_clock,
            _splash_photo_cache=_splash_photo_cache,
            _splash_photo_from_rgb=_splash_photo_from_rgb,
            _splash_rgb_cache=_splash_rgb_cache,
            splash_total_frames=splash_total_frames,
        )
        _splash_video_cap_holder: list[cv2.VideoCapture | None] = [None]

        _splash_raw_bgra = _bind_deps(
            _core_splash._splash_raw_bgra,
            UI_TARGET_H=UI_TARGET_H,
            UI_TARGET_W=UI_TARGET_W,
            builtin_splash_bgra_frame=builtin_splash_bgra_frame,
            load_splash_bgra=load_splash_bgra,
            splash_png_paths=splash_png_paths,
            splash_total_frames=splash_total_frames,
        )

        _splash_bgra_over_bgr_to_rgb = _core_splash._splash_bgra_over_bgr_to_rgb

        _splash_store_prebaked = _bind_deps(
            _core_splash._splash_store_prebaked,
            _splash_bg_bgr=_splash_bg_bgr,
            _splash_bgra_cache=_splash_bgra_cache,
            _splash_fade_frames=_splash_fade_frames,
            _splash_fade_zone_start=_splash_fade_zone_start,
            _splash_frame_keeps_live_clock=_splash_frame_keeps_live_clock,
            _splash_rgb_cache=_splash_rgb_cache,
            flatten_bgra_over_bg_to_rgb=flatten_bgra_over_bg_to_rgb,
        )

        _splash_prebake_reveal_bgra = _bind_deps(
            _core_splash._splash_prebake_reveal_bgra,
            _bgra_to_display_window=_bgra_to_display_window,
            _splash_bgra_cache=_splash_bgra_cache,
            _splash_photo_cache=_splash_photo_cache,
            _splash_raw_bgra=_splash_raw_bgra,
            _splash_reveal_i=_splash_reveal_i,
            _splash_rgb_cache=_splash_rgb_cache,
            splash_idx=splash_idx,
            splash_total_frames=splash_total_frames,
        )

        _splash_prebake_worker_pngs = _bind_deps(
            _core_splash._splash_prebake_worker_pngs,
            _bgra_to_display_window=_bgra_to_display_window,
            _splash_bgra_cache=_splash_bgra_cache,
            _splash_prebake_ahead=int(SPLASH_PREBAKE_AHEAD_FRAMES),
            _splash_prebake_done=_splash_prebake_done,
            _splash_prebake_reveal_bgra=_splash_prebake_reveal_bgra,
            _splash_raw_bgra=_splash_raw_bgra,
            _splash_rgb_cache=_splash_rgb_cache,
            _splash_store_prebaked=_splash_store_prebaked,
            splash_anim_done=splash_anim_done,
            splash_idx=splash_idx,
            splash_total_frames=splash_total_frames,
        )

        _splash_hold_released_now = _bind_deps(
            _core_splash._splash_hold_released_now,
            _splash_bgra_cache=_splash_bgra_cache,
            _splash_prebake_done=_splash_prebake_done,
            _splash_rgb_cache=_splash_rgb_cache,
            bootstrap_done=bootstrap_done,
            splash_png_paths=splash_png_paths,
            splash_total_frames=splash_total_frames,
        )
        _splash_hold_since: dict[int, float | None] = {}

        _splash_prebake_worker_video = _bind_deps(
            _core_splash._splash_prebake_worker_video,
            UI_TARGET_H=UI_TARGET_H,
            UI_TARGET_W=UI_TARGET_W,
            _bgra_to_display_window=_bgra_to_display_window,
            _splash_bgra_cache=_splash_bgra_cache,
            _splash_fade_zone_start=_splash_fade_zone_start,
            _splash_prebake_done=_splash_prebake_done,
            _splash_rgb_cache=_splash_rgb_cache,
            _splash_video_cap_holder=_splash_video_cap_holder,
            splash_total_frames=splash_total_frames,
            splash_video_path=splash_video_path,
        )

        # mpv plays the opaque frames (0..reveal) inside the overlay; Tk only plays the
        # see-through outro. Must start before the prebake thread, which then skips to
        # the reveal frame. Any failure leaves the full Tk splash in place.
        _splash_mpv_player: SplashMpv | None = None
        _splash_mpv_host: tk.Frame | None = None
        _splash_mpv_video = (
            splash_mpv_video_path(ctx._PROJECT_DIR)
            if splash_png_paths and splash_total_frames > _splash_reveal_i and splash_mpv_enabled()
            else None
        )
        if _splash_mpv_video is not None:
            _splash_mpv_host = tk.Frame(splash_overlay, bg="#000", highlightthickness=0, bd=0, cursor="none")
            _splash_mpv_host.place(relx=0, rely=0, relwidth=1, relheight=1)
            try:
                root.update_idletasks()
                _splash_mpv_player = SplashMpv(
                    _splash_mpv_video,
                    wid=_splash_mpv_host.winfo_id(),
                    fps=_splash_fps_effective,
                    hold_frame=int(SPLASH_HOLD_LOGO_FRAME),
                    last_frame=_splash_reveal_i,
                    bootstrap_done=bootstrap_done,
                )
                if not _splash_mpv_player.start():
                    _splash_mpv_player = None
            except Exception as e:
                sys.stderr.write(f"pigeon: splash mpv error: {e}\n")
                _splash_mpv_player = None
            if _splash_mpv_player is None:
                _splash_mpv_host.destroy()
                _splash_mpv_host = None
            else:
                splash_idx[0] = _splash_reveal_i
                splash_bootstrap_go[0] = True

        # Kick off the prebake thread immediately so frames are warm before ``splash_tick``
        # starts pulling from the cache post-``after_idle``.
        try:
            _worker = _splash_prebake_worker_video if splash_video_path is not None else _splash_prebake_worker_pngs
            _splash_prebake_thread = threading.Thread(
                target=_worker, name="pigeon-splash-prebake", daemon=True
            )
            _splash_prebake_thread.start()
        except Exception:
            # Fall back to on-demand decode inside ``splash_tick``.
            _splash_prebake_done[0] = True

        _splash_fallback_frame_sync = _bind_deps(
            _core_splash._splash_fallback_frame_sync,
            _bgra_to_display_window=_bgra_to_display_window,
            _splash_raw_bgra=_splash_raw_bgra,
            _splash_store_prebaked=_splash_store_prebaked,
            splash_video_path=splash_video_path,
        )

        _splash_composite_bgra_to_photo = _bind_deps(
            _core_splash._splash_composite_bgra_to_photo,
            _splash_bg_bgr=_splash_bg_bgr,
            _splash_bgra_over_bgr_to_rgb=_splash_bgra_over_bgr_to_rgb,
            _splash_underlay_bgr=_splash_underlay_bgr,
            apply_splash_global_alpha=apply_splash_global_alpha,
            flatten_bgra_over_bg_to_rgb=flatten_bgra_over_bg_to_rgb,
            splash_photo=splash_photo,
        )

        splash_tick = _bind_deps(
            _core_splash.splash_tick,
            SPLASH_HOLD_LOGO_FRAME=int(SPLASH_HOLD_LOGO_FRAME),
            SPLASH_MAX_DURATION_S=SPLASH_MAX_DURATION_S,
            WINDOW_H=WINDOW_H,
            WINDOW_W=WINDOW_W,
            _app_startup_mono=_app_startup_mono,
            _reveal_clock_under_splash=_reveal_clock_under_splash,
            _splash_bg_bgr=_splash_bg_bgr,
            _splash_bgra_cache=_splash_bgra_cache,
            _splash_composite_bgra_to_photo=_splash_composite_bgra_to_photo,
            _splash_fade_frames=_splash_fade_frames,
            _splash_fallback_frame_sync=_splash_fallback_frame_sync,
            _splash_frame_keeps_live_clock=_splash_frame_keeps_live_clock,
            _splash_hold_released_now=_splash_hold_released_now,
            _splash_hold_since=_splash_hold_since,
            _splash_photo_cache=_splash_photo_cache,
            _splash_photo_from_rgb=_splash_photo_from_rgb,
            _splash_prebake_done=_splash_prebake_done,
            _splash_prebake_reveal_bgra=_splash_prebake_reveal_bgra,
            _splash_prebuild_photos=_splash_prebuild_photos,
            _splash_reveal_clock=_splash_reveal_clock,
            _splash_reveal_i=_splash_reveal_i,
            _splash_rgb_cache=_splash_rgb_cache,
            _splash_start_lead=int(SPLASH_START_LEAD_FRAMES),
            _splash_wait_deadline=_splash_wait_deadline,
            _try_remove_splash_overlay=_try_remove_splash_overlay,
            content_host=content_host,
            flatten_bgra_over_bg_to_rgb=flatten_bgra_over_bg_to_rgb,
            frame_dt=frame_dt,
            frame_ms=frame_ms,
            root=root,
            splash_anim_done=splash_anim_done,
            splash_bootstrap_go=splash_bootstrap_go,
            splash_end_fade_factor=splash_end_fade_factor,
            splash_idx=splash_idx,
            splash_label=splash_label,
            splash_photo=splash_photo,
            splash_t0=splash_t0,
            splash_tick=_late(lambda: splash_tick, "splash_tick"),
            splash_total_frames=splash_total_frames,
            startup_ph=startup_ph,
        )

        # Entry point scheduled by main(): mpv first when it is playing, else Tk directly.
        _splash_entry_tick = splash_tick
        if _splash_mpv_player is not None:
            _splash_entry_tick = _bind_deps(
                _core_splash.splash_mpv_tick,
                _app_startup_mono=_app_startup_mono,
                _splash_reveal_i=_splash_reveal_i,
                frame_dt=frame_dt,
                mpv_host=_splash_mpv_host,
                player=_splash_mpv_player,
                root=root,
                splash_idx=splash_idx,
                splash_mpv_tick=_late(lambda: _splash_entry_tick, "_splash_entry_tick"),
                splash_t0=splash_t0,
                splash_tick=splash_tick,
            )

    else:
        loading = tk.Label(
            content_host,
            text="Starting Pigeon…\n\n"
            "Tab / Shift+Tab / F9 toggle settings ↔ off. "
            "Key 5 shows grid overlay (press 5 again to toggle detail lines). "
            "Return opens the command bar in settings or grid overlay (5). "
            "Esc closes the bar or quits. F10 / double-click toggles the display. "
            "Space = activate in settings; else play/pause on the selected Player "
            "(Apple TV / Roku) when set; else TMDb backdrop + logo when loaded; else landing brightness pulse.",
            justify="center",
            fg="#ddd",
            bg="#111",
            cursor="none",
            wraplength=WINDOW_W - 40,
        )
        loading.pack(expand=True, fill="both")
        startup_ph[0] = loading

    root.update_idletasks()
    root.update()
    if _PIGEON_EXT and startup_ph[0] is not None:
        try:
            startup_ph[0].lift(content_host)
        except tk.TclError:
            try:
                startup_ph[0].lift()
            except tk.TclError:
                pass

    # Keep idle/paused composites intentionally slower to reduce Tk PhotoImage upload pressure.
    paused_interval_ms = max(67, PAUSED_COMPOSITE_MS)

    ctx._grid_patched = _grid_patched
    ctx._live_clock_until_compose = _live_clock_until_compose
    ctx._pack_patched = _pack_patched
    ctx._place_patched = _place_patched
    ctx._tk_grid_orig = _tk_grid_orig
    ctx._tk_pack_orig = _tk_pack_orig
    ctx._tk_place_orig = _tk_place_orig
    ctx._try_remove_splash_overlay = _try_remove_splash_overlay
    ctx.paused_interval_ms = paused_interval_ms
    try:
        ctx.splash_tick = _splash_entry_tick
    except NameError:
        pass
