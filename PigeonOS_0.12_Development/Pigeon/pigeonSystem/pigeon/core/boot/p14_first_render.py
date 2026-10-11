"""Boot phase: first render, receiver polls, and the bootstrap-done handoff to the splash.

Phase 14 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

import time
import tkinter as tk


def run(ctx) -> None:
    _PIGEON_EXT = ctx._PIGEON_EXT
    _enable_now_playing_screen = ctx._enable_now_playing_screen
    _finish_post_splash_startup_transition = ctx._finish_post_splash_startup_transition
    _log_view_one_startup_phase = ctx._log_view_one_startup_phase
    _on_shell_configure = ctx._on_shell_configure
    _receiver_poll_tick = ctx._receiver_poll_tick
    _receiver_volume_poll_tick = ctx._receiver_volume_poll_tick
    _splash_clock_refresh_stop = ctx._splash_clock_refresh_stop
    _splash_paint_view_one_under_overlay = ctx._splash_paint_view_one_under_overlay
    _tk_grid_orig = ctx._tk_grid_orig
    _tk_pack_orig = ctx._tk_pack_orig
    _tk_place_orig = ctx._tk_place_orig
    _try_remove_splash_overlay = ctx._try_remove_splash_overlay
    _warm_view_one_under_splash = ctx._warm_view_one_under_splash
    bootstrap_done = ctx.bootstrap_done
    render_once = ctx.render_once
    root = ctx.root
    shell = ctx.shell
    skip_cache = ctx.skip_cache
    startup_ph = ctx.startup_ph

    root.after(0, _splash_paint_view_one_under_overlay)

    shell.bind("<Configure>", _on_shell_configure)

    _warm_view_one_under_splash(phase="full-warm-bootstrap-end")
    _enable_now_playing_screen()
    skip_cache[0] = None
    t_render0 = time.monotonic()
    render_once()
    _log_view_one_startup_phase(f"first-render ({(time.monotonic() - t_render0) * 1000.0:.0f} ms)")
    root.after(600, _receiver_poll_tick)
    root.after(700, _receiver_volume_poll_tick)

    if _PIGEON_EXT:
        tk.Widget.pack = _tk_pack_orig  # type: ignore[method-assign]
        tk.Widget.grid = _tk_grid_orig  # type: ignore[method-assign]
        tk.Widget.place = _tk_place_orig  # type: ignore[method-assign]
        try:
            root.update()
        except tk.TclError:
            pass
    bootstrap_done[0] = True
    _splash_clock_refresh_stop[0] = True
    _log_view_one_startup_phase("bootstrap-done")
    # Splash already finished before bootstrap started; run the deferred post-splash hook.
    if startup_ph[0] is None:
        _finish_post_splash_startup_transition()
    else:
        _try_remove_splash_overlay()
