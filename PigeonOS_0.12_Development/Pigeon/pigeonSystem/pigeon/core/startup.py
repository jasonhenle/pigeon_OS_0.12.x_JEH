"""Splash / startup choreography: clock underlay capture and the post-splash clock fade-in.

Extracted verbatim from ``bootstrap()`` (and, since pass 10, ``main()``) in
``pigeon_0_12.py``. Each function takes the app state it used to close over as
keyword-only arguments; the enclosing function binds them once with
``bind_deps`` so call sites are unchanged.
"""

from __future__ import annotations

import numpy as np
import time
import tkinter as tk
import sys


def _early_splash_clock_underlay(*, _bgr_to_tk_image, _early_clock_underlay_photo, _reveal_clock_under_splash, _splash_reveal_clock, _splash_underlay_bgr, label) -> None:
    """Copy clock underlay onto the real video label (under splash / after lift)."""
    if not _splash_reveal_clock[0]:
        return
    under = _splash_underlay_bgr[0]
    if under is None:
        _reveal_clock_under_splash(refresh=False)
        under = _splash_underlay_bgr[0]
    if under is None:
        return
    try:
        _early_clock_underlay_photo[0] = _bgr_to_tk_image(under)
        label.configure(image=_early_clock_underlay_photo[0])
        label.image = _early_clock_underlay_photo[0]
    except Exception:
        pass


def _clock_startup_intro_opacity(now: float, *, CLOCK_STARTUP_FADE_S, clock_saver_composite_bgra, post_splash_mono, startup_ph) -> float | None:
    """Smooth 0→1 while the post-splash clock is the first reveal; else ``None``."""
    t0 = post_splash_mono[0]
    if t0 is None or startup_ph[0] is not None:
        return None
    if clock_saver_composite_bgra is None:
        return None
    elapsed = now - float(t0)
    if elapsed >= float(CLOCK_STARTUP_FADE_S):
        return None
    u = max(0.0, min(1.0, elapsed / max(1e-6, float(CLOCK_STARTUP_FADE_S))))
    return u * u * (3.0 - 2.0 * u)


def _capture_splash_underlay(out_bgr: np.ndarray, *, WINDOW_H, WINDOW_W, _present_frame_to_display, _splash_underlay_bgr, startup_ph) -> None:
    """Keep a window-sized UI snapshot for the splash fade unveil."""
    if startup_ph[0] is None or out_bgr is None or out_bgr.size == 0:
        return
    try:
        if out_bgr.shape[0] == WINDOW_H and out_bgr.shape[1] == WINDOW_W:
            _splash_underlay_bgr[0] = np.ascontiguousarray(out_bgr)
        else:
            _splash_underlay_bgr[0] = np.ascontiguousarray(
                _present_frame_to_display(
                    out_bgr, WINDOW_W, WINDOW_H, native_now_playing=True
                )
            )
    except Exception:
        pass


def _warm_view_one_splash_chrome_only(*, phase: str = "chrome-only", DisplayView, _PIGEON_EXT, _log_view_one_startup_phase, display_view_holder, root, view_circles_widget) -> None:
    """Rasterize View 1 SVG chrome early (no playback poll helpers required)."""
    if not _PIGEON_EXT or view_circles_widget is None:
        return
    t0 = time.monotonic()
    display_view_holder[0] = DisplayView.ONE
    # Clock-only until content is live — do not force the empty status bar on.
    if view_circles_widget.set_now_playing_chrome_visible(True):
        view_circles_widget.clear_cache()
    try:
        view_circles_widget.bgra_frame()
    except Exception:
        pass
    try:
        root.update_idletasks()
    except tk.TclError:
        pass
    _log_view_one_startup_phase(f"{phase} ({(time.monotonic() - t0) * 1000.0:.0f} ms raster)")


def _warm_view_one_under_splash(*, phase: str = "full-warm", _PIGEON_EXT, _enable_now_playing_screen, _log_view_one_startup_phase, _splash_view_one_warm_done, _warm_status_bar_blits, root, view_circles_widget) -> None:
    """Full View 1 enable + state sync once playback helpers exist."""
    if not _PIGEON_EXT:
        return
    t0 = time.monotonic()
    _enable_now_playing_screen()
    _warm_status_bar_blits()
    try:
        if view_circles_widget is not None:
            view_circles_widget.bgra_frame()
    except Exception:
        pass
    try:
        root.update_idletasks()
    except tk.TclError:
        pass
    _splash_view_one_warm_done[0] = True
    _log_view_one_startup_phase(f"{phase} ({(time.monotonic() - t0) * 1000.0:.0f} ms)")


def _splash_paint_view_one_under_overlay(*, _PIGEON_EXT, _warm_view_one_under_splash, render_once, root, skip_cache) -> None:
    """First full View 1 paint after splash (helpers now exist)."""
    if not _PIGEON_EXT:
        return
    _warm_view_one_under_splash()
    skip_cache[0] = None
    render_once()
    try:
        root.update_idletasks()
    except tk.TclError:
        pass


def _activate_now_playing_after_splash(*, _enable_now_playing_screen, _startup_splash_complete, render_once, skip_cache) -> None:
    """Splash lifted — now-playing should already be live under the overlay."""
    _enable_now_playing_screen()
    _startup_splash_complete[0] = True
    skip_cache[0] = None
    render_once()


def _apply_clock_to_bridge_label(shown: np.ndarray, *, _bgr_to_tk_image, _boot_clock_label, _boot_clock_photo) -> None:
    """Push clock pixels onto the content_host bridge (under the splash overlay)."""
    try:
        _boot_clock_photo[0] = _bgr_to_tk_image(shown)
        if _boot_clock_label.winfo_exists():
            _boot_clock_label.configure(image=_boot_clock_photo[0])
            _boot_clock_label.image = _boot_clock_photo[0]  # type: ignore[attr-defined]
    except tk.TclError:
        pass


def _reveal_clock_under_splash(*, refresh: bool = False, _apply_clock_to_bridge_label, _rasterize_clock_saver_window_bgr, _splash_clock_ready_bgr, _splash_on_reveal_paint, _splash_reveal_clock, _splash_underlay_bgr, _splash_underlay_paint_mono, bootstrap_done) -> bool:
    """From the reveal frame: put the live clock into the underlay + bridge beneath splash."""
    shown = _splash_clock_ready_bgr[0]
    if shown is None or refresh:
        shown = _rasterize_clock_saver_window_bgr()
        if shown is not None:
            _splash_clock_ready_bgr[0] = shown
    if shown is None:
        return False
    # Compose owns the underlay after bootstrap; do not overwrite it with a stale prewarm.
    if not bootstrap_done[0]:
        _splash_underlay_bgr[0] = shown
        _apply_clock_to_bridge_label(shown)
        _splash_underlay_paint_mono[0] = time.monotonic()
        paint = _splash_on_reveal_paint[0]
        if callable(paint):
            try:
                paint()
            except Exception:
                pass
    _splash_reveal_clock[0] = True
    return True


def _finish_post_splash_startup_transition(*, _post_splash_startup_hook, _splash_post_hook_ran) -> None:
    """Post-splash hook (registered from ``bootstrap``)."""
    if _splash_post_hook_ran[0]:
        return
    hook = _post_splash_startup_hook[0]
    if callable(hook):
        _splash_post_hook_ran[0] = True
        hook()


def _live_clock_until_compose(*, _live_clock_until_compose, _reveal_clock_under_splash, _splash_clock_refresh_stop, _splash_reveal_clock, bootstrap_done, root, splash_anim_done) -> None:
    """Keep the boot/video clock on wall time until compose owns the display.

    Bootstrap waits for splash, then packs widgets with ``root.update()``
    (``_splash_pump_maybe``), which lets this tick run so the saver does not
    freeze again between overlay lift and the first ``render_once``.
    """
    if bootstrap_done[0] or _splash_clock_refresh_stop[0]:
        return
    if _splash_reveal_clock[0] or splash_anim_done[0]:
        _reveal_clock_under_splash(refresh=False)
    if not bootstrap_done[0] and not _splash_clock_refresh_stop[0]:
        try:
            root.after(250, _live_clock_until_compose)
        except tk.TclError:
            pass


def _splash_pump_maybe(*, _PIGEON_EXT, _reveal_clock_under_splash, _splash_pump_next, _splash_reveal_clock, _splash_underlay_paint_mono, bootstrap_done, root, splash_anim_done) -> None:
    if not _PIGEON_EXT or bootstrap_done[0]:
        return
    now = time.monotonic()
    if now < _splash_pump_next[0]:
        return
    _splash_pump_next[0] = now + (1.0 / 30.0)
    if (_splash_reveal_clock[0] or splash_anim_done[0]) and (
        now - float(_splash_underlay_paint_mono[0] or 0.0) >= 0.25
    ):
        _reveal_clock_under_splash(refresh=False)
    try:
        root.update()
    except tk.TclError:
        pass


def _try_remove_splash_overlay(*, _PIGEON_EXT, _app_startup_mono, _finish_post_splash_startup_transition, _reveal_clock_under_splash, _splash_bgra_cache, _splash_photo_cache, _splash_rgb_cache, bootstrap_done, post_splash_mono, splash_anim_done, splash_photo, startup_ph) -> None:
    """Destroy splash the instant the sequence ends (no bootstrap wait)."""
    if not _PIGEON_EXT:
        return
    if not splash_anim_done[0]:
        return
    w = startup_ph[0]
    if w is None:
        return
    # Clock must already be on the bridge underlay before the overlay disappears.
    _reveal_clock_under_splash(refresh=False)
    if bootstrap_done[0]:
        _finish_post_splash_startup_transition()
    try:
        w.destroy()
    except tk.TclError:
        pass
    startup_ph[0] = None
    try:
        sys.stderr.write(
            f"pigeon: splash overlay lifted +{time.monotonic() - _app_startup_mono:.3f}s\n"
        )
        sys.stderr.flush()
    except Exception:
        pass
    # Splash frames can hold tens of MB (full-window RGB/BGRA per frame);
    # release them now that the overlay is gone. NameError guard: the caches
    # only exist when the ext splash path ran.
    try:
        _splash_rgb_cache.clear()
        _splash_bgra_cache.clear()
        _splash_photo_cache.clear()
        splash_photo[0] = None
    except NameError:
        pass
    if post_splash_mono[0] is None:
        post_splash_mono[0] = time.monotonic()


def _pack_patched(self: tk.Misc, *args: object, _splash_pump_maybe, _tk_pack_orig, **kwargs: object) -> object | None:
    r = _tk_pack_orig(self, *args, **kwargs)
    _splash_pump_maybe()
    return r


def _grid_patched(self: tk.Misc, *args: object, _splash_pump_maybe, _tk_grid_orig, **kwargs: object) -> object | None:
    r = _tk_grid_orig(self, *args, **kwargs)
    _splash_pump_maybe()
    return r


def _place_patched(self: tk.Misc, *args: object, _splash_pump_maybe, _tk_place_orig, **kwargs: object) -> object | None:
    r = _tk_place_orig(self, *args, **kwargs)
    _splash_pump_maybe()
    return r
