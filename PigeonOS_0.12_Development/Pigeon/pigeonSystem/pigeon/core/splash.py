"""Startup splash playback: clock prewarm, frame decode / prebake workers, the frame caches, and the splash_tick animation loop.

Extracted verbatim from ``main()`` in ``pigeon_0_12.py``. Each function
takes the app state it used to close over as keyword-only arguments;
``main()`` binds them once with ``bind_deps`` so call sites are unchanged.
"""

from __future__ import annotations

from PIL import Image
from PIL import ImageTk
from pigeon.compositing import cv_resize_interp
import cv2
import numpy as np
import sys
import time
import tkinter as tk

from pigeon.splash_sequence import splash_hold_released


def _prewarm_splash_clock_worker(*, _rasterize_clock_saver_window_bgr, _splash_clock_ready_bgr, _splash_clock_refresh_stop, bootstrap_done) -> None:
    while not _splash_clock_refresh_stop[0]:
        try:
            shown = _rasterize_clock_saver_window_bgr()
            if shown is not None:
                _splash_clock_ready_bgr[0] = shown
        except Exception:
            pass
        if bootstrap_done[0] or _splash_clock_refresh_stop[0]:
            break
        time.sleep(0.25)


def _splash_frame_keeps_live_clock(ii: int, *, _splash_reveal_i, splash_keep_alpha_for_live_clock, splash_png_paths) -> bool:
    if not splash_png_paths:
        return False
    if callable(splash_keep_alpha_for_live_clock):
        return bool(
            splash_keep_alpha_for_live_clock(ii, reveal_frame=_splash_reveal_i)
        )
    return int(ii) >= int(_splash_reveal_i)


def _splash_photo_from_rgb(rgb: np.ndarray) -> ImageTk.PhotoImage:
    return ImageTk.PhotoImage(image=Image.fromarray(rgb, "RGB"))


def _splash_update_photo(rgb: np.ndarray, *, splash_photo) -> ImageTk.PhotoImage:
    """Update the persistent Tk image instead of allocating one per frame."""
    image = Image.fromarray(rgb, "RGB")
    photo = splash_photo[0]
    if photo is None:
        photo = ImageTk.PhotoImage(image=image)
        splash_photo[0] = photo
    else:
        photo.paste(image)
    return photo


def _splash_prebuild_photos(*, limit: int, _splash_frame_keeps_live_clock, _splash_photo_cache, _splash_photo_from_rgb, _splash_rgb_cache, splash_total_frames) -> int:
    """Turn already-decoded RGB frames into Tk images on the UI thread."""
    built = 0
    for ii in range(splash_total_frames):
        if built >= limit:
            break
        if _splash_frame_keeps_live_clock(ii):
            continue
        if ii in _splash_photo_cache:
            continue
        rgb = _splash_rgb_cache.get(ii)
        if rgb is None:
            continue
        try:
            _splash_photo_cache[ii] = _splash_photo_from_rgb(rgb)
        except Exception:
            break
        built += 1
    return built


def _splash_raw_bgra(ii: int, *, UI_TARGET_H, UI_TARGET_W, builtin_splash_bgra_frame, load_splash_bgra, splash_png_paths, splash_total_frames) -> np.ndarray | None:
    """Source-resolution BGRA for frame ``ii`` (PNG / built-in). Video path doesn't use this."""
    if splash_png_paths:
        if 0 <= ii < len(splash_png_paths):
            return load_splash_bgra(splash_png_paths[ii])
        return None
    return builtin_splash_bgra_frame(
        ii, splash_total_frames, width=UI_TARGET_W, height=UI_TARGET_H
    )


def _splash_bgra_over_bgr_to_rgb(bgra: np.ndarray, under_bgr: np.ndarray) -> np.ndarray:
    a = bgra[:, :, 3].astype(np.uint16)
    inv = 255 - a
    blended = (
        bgra[:, :, :3].astype(np.uint16) * a[:, :, None]
        + under_bgr.astype(np.uint16) * inv[:, :, None]
        + 127
    ) // 255
    rgb = cv2.cvtColor(blended.astype(np.uint8), cv2.COLOR_BGR2RGB)
    return np.ascontiguousarray(rgb)


def _splash_store_prebaked(ii: int, bgra_window: np.ndarray, *, _splash_bg_bgr, _splash_bgra_cache, _splash_fade_frames, _splash_fade_zone_start, _splash_frame_keeps_live_clock, _splash_rgb_cache, flatten_bgra_over_bg_to_rgb) -> None:
    """Store a window-sized frame. Pre-reveal → RGB over black; reveal PNGs keep BGRA."""
    if _splash_frame_keeps_live_clock(ii):
        _splash_bgra_cache[ii] = bgra_window
        return
    if ii >= _splash_fade_zone_start and _splash_fade_frames > 0:
        _splash_bgra_cache[ii] = bgra_window
        return
    try:
        _splash_rgb_cache[ii] = flatten_bgra_over_bg_to_rgb(bgra_window, _splash_bg_bgr)
    except Exception:
        _splash_bgra_cache[ii] = bgra_window


def _splash_prebake_reveal_bgra(*, _bgra_to_display_window, _splash_bgra_cache, _splash_photo_cache, _splash_raw_bgra, _splash_reveal_i, _splash_rgb_cache, splash_idx, splash_total_frames) -> None:
    """Warm BGRA for reveal frames; never flatten them over a frozen clock."""
    try:
        # Frames already shown were evicted; don't decode them again.
        for ii in range(max(_splash_reveal_i, int(splash_idx[0])), splash_total_frames):
            _splash_rgb_cache.pop(ii, None)
            _splash_photo_cache.pop(ii, None)
            if ii in _splash_bgra_cache:
                continue
            fr = _splash_raw_bgra(ii)
            if fr is None:
                continue
            _splash_bgra_cache[ii] = _bgra_to_display_window(fr)
    except Exception:
        pass


def _splash_prebake_worker_pngs(*, _bgra_to_display_window, _splash_bgra_cache, _splash_prebake_ahead, _splash_prebake_done, _splash_prebake_reveal_bgra, _splash_raw_bgra, _splash_rgb_cache, _splash_store_prebaked, splash_anim_done, splash_idx, splash_total_frames) -> None:
    """Decode PNGs off the UI thread; flatten early frames over black for a fast blit path.

    Stays at most ``_splash_prebake_ahead`` frames ahead of playback so the full
    sequence is never resident at once (the tick evicts frames once shown).
    """
    try:
        for ii in range(splash_total_frames):
            while (
                _splash_prebake_ahead > 0
                and ii - int(splash_idx[0]) >= _splash_prebake_ahead
                and not splash_anim_done[0]
            ):
                time.sleep(0.01)
            if splash_anim_done[0]:
                break
            if ii < int(splash_idx[0]):
                continue
            if ii in _splash_rgb_cache or ii in _splash_bgra_cache:
                continue
            fr = _splash_raw_bgra(ii)
            if fr is None:
                continue
            fr = _bgra_to_display_window(fr)
            _splash_store_prebaked(ii, fr)
        _splash_prebake_reveal_bgra()
    except Exception:
        pass
    finally:
        _splash_prebake_done[0] = True


def _splash_prebake_worker_video(*, UI_TARGET_H, UI_TARGET_W, _bgra_to_display_window, _splash_bgra_cache, _splash_fade_zone_start, _splash_prebake_done, _splash_rgb_cache, _splash_video_cap_holder, splash_total_frames, splash_video_path) -> None:
    """Sequentially decode the splash video into the fast-path caches.

    Sequential reads on ``VideoCapture`` are hardware-accelerated on macOS
    (AVFoundation/VideoToolbox) and far cheaper than 100+ PNG decodes + resizes.
    """
    cap_v: cv2.VideoCapture | None = None
    try:
        cap_v = cv2.VideoCapture(str(splash_video_path))
        _splash_video_cap_holder[0] = cap_v
        if not cap_v.isOpened():
            return
        for ii in range(splash_total_frames):
            ok, bgr = cap_v.read()
            if not ok or bgr is None:
                break
            if bgr.shape[1] != UI_TARGET_W or bgr.shape[0] != UI_TARGET_H:
                _sw, _sh = int(bgr.shape[1]), int(bgr.shape[0])
                bgr = cv2.resize(
                    bgr,
                    (UI_TARGET_W, UI_TARGET_H),
                    interpolation=cv_resize_interp(_sw, _sh, UI_TARGET_W, UI_TARGET_H),
                )
            bgra_fit = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
            bgra_fit[:, :, 3] = 255
            bgra_win = _bgra_to_display_window(bgra_fit)
            bgr = bgra_win[:, :, :3]
            if ii < _splash_fade_zone_start:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                _splash_rgb_cache[ii] = np.ascontiguousarray(rgb)
            else:
                # Fade-tail wants dynamic alpha, so synthesize opaque BGRA and let the
                # tick multiply the alpha channel each frame.
                h, w = bgr.shape[:2]
                bgra = np.empty((h, w, 4), dtype=np.uint8)
                bgra[:, :, :3] = bgr
                bgra[:, :, 3] = 255
                _splash_bgra_cache[ii] = bgra
    except Exception:
        pass
    finally:
        try:
            if cap_v is not None:
                cap_v.release()
        except Exception:
            pass
        _splash_video_cap_holder[0] = None
        _splash_prebake_done[0] = True


def _splash_fallback_frame_sync(ii: int, *, _bgra_to_display_window, _splash_raw_bgra, _splash_store_prebaked, splash_video_path) -> np.ndarray | None:
    """On-demand decode if the worker hasn't populated this index yet (built-in only)."""
    if splash_video_path is not None:
        # We can't safely random-seek while the worker owns the VideoCapture.
        return None
    fr = _splash_raw_bgra(ii)
    if fr is None:
        return None
    fr = _bgra_to_display_window(fr)
    _splash_store_prebaked(ii, fr)
    return fr


def _splash_hold_released_now(held_frame: int, *, _splash_bgra_cache, _splash_prebake_done, _splash_rgb_cache, bootstrap_done, splash_png_paths, splash_total_frames) -> bool:
    """Whether playback may leave ``held_frame`` (073 / 148 park; PNG sequence only)."""
    if not splash_png_paths:
        return True
    return splash_hold_released(
        held_frame,
        total_frames=splash_total_frames,
        is_cached=lambda k: k in _splash_rgb_cache or k in _splash_bgra_cache,
        prebake_done=bool(_splash_prebake_done[0]),
        bootstrap_done=bool(bootstrap_done[0]),
    )


def _splash_composite_bgra_to_photo(bgra_hit: np.ndarray | None, fade_mul: float, *, _splash_bg_bgr, _splash_bgra_over_bgr_to_rgb, _splash_underlay_bgr, apply_splash_global_alpha, flatten_bgra_over_bg_to_rgb, splash_photo) -> None:
    """Composite splash BGRA over underlay into an opaque RGB ``splash_photo``.

    Before the reveal frame the underlay is black; from it, the UI compose output.
    Always bake to RGB so the splash layer fully covers content_host.
    """
    if bgra_hit is None:
        return
    bgra_out = (
        apply_splash_global_alpha(bgra_hit, fade_mul)
        if fade_mul < 0.999 and apply_splash_global_alpha is not None
        else bgra_hit
    )
    under = _splash_underlay_bgr[0]
    if under is None or under.ndim != 3 or under.shape[:2] != bgra_out.shape[:2]:
        rgb = flatten_bgra_over_bg_to_rgb(bgra_out, _splash_bg_bgr)
    else:
        rgb = _splash_bgra_over_bgr_to_rgb(bgra_out, under)
    _splash_update_photo(rgb, splash_photo=splash_photo)


def splash_tick(*, SPLASH_HOLD_LOGO_FRAME, SPLASH_MAX_DURATION_S, WINDOW_H, WINDOW_W, _app_startup_mono, _reveal_clock_under_splash, _splash_bg_bgr, _splash_bgra_cache, _splash_composite_bgra_to_photo, _splash_fade_frames, _splash_fallback_frame_sync, _splash_frame_keeps_live_clock, _splash_hold_released_now, _splash_hold_since, _splash_photo_cache, _splash_photo_from_rgb, _splash_prebake_done, _splash_prebake_reveal_bgra, _splash_prebuild_photos, _splash_reveal_clock, _splash_reveal_i, _splash_rgb_cache, _splash_start_lead, _splash_wait_deadline, _try_remove_splash_overlay, content_host, flatten_bgra_over_bg_to_rgb, frame_dt, frame_ms, root, splash_anim_done, splash_bootstrap_go, splash_end_fade_factor, splash_idx, splash_label, splash_photo, splash_t0, splash_tick, splash_total_frames, startup_ph) -> None:
    try:
        if not splash_label.winfo_exists():
            return
    except tk.TclError:
        return
    ov_top = startup_ph[0]
    if ov_top is not None:
        try:
            # Bootstrap builds shell widgets under the parked splash; keep it on top of all.
            ov_top.lift()
        except tk.TclError:
            pass
    ntot = splash_total_frames
    now = time.monotonic()
    if splash_t0[0] is None:
        if _splash_wait_deadline[0] is None:
            _splash_wait_deadline[0] = now + 3.6
        # Short decode lead; the 073 hold absorbs the rest of the logo run on the Pi.
        lead_need = min(ntot, max(1, int(_splash_start_lead)))
        lead = 0
        for k in range(lead_need):
            if k in _splash_rgb_cache or k in _splash_bgra_cache:
                lead += 1
        ready0 = 0 in _splash_rgb_cache or 0 in _splash_bgra_cache
        if ready0 and splash_photo[0] is None:
            ph0 = _splash_photo_cache.get(0)
            if ph0 is None:
                rgb0 = _splash_rgb_cache.get(0)
                if rgb0 is not None:
                    try:
                        ph0 = _splash_update_photo(rgb0, splash_photo=splash_photo)
                    except Exception:
                        ph0 = None
            if ph0 is not None:
                splash_photo[0] = ph0
                try:
                    splash_label.configure(image=ph0)
                except Exception:
                    pass
        if (
            lead < lead_need
            and not _splash_prebake_done[0]
            and now < float(_splash_wait_deadline[0])
        ):
            root.after(8, splash_tick)
            return
        splash_t0[0] = now
        try:
            sys.stderr.write(
                f"pigeon: splash play start frames={ntot} lead={lead}/{lead_need} "
                f"photos={len(_splash_photo_cache)} "
                f"+{now - _app_startup_mono:.3f}s\n"
            )
            sys.stderr.flush()
        except Exception:
            pass
    # Park on 073 / 148 (already on screen) until decode / bootstrap catch up. Sliding
    # t0 keeps the timeline parked, so the next frame lands one frame_dt after release
    # and hold time never counts toward SPLASH_MAX_DURATION_S.
    held = min(int(splash_idx[0]), ntot) - 1
    if 0 <= held < ntot - 1:
        if not _splash_hold_released_now(held):
            if held == int(SPLASH_HOLD_LOGO_FRAME):
                # The logo hold is where bootstrap runs; it releases once bootstrap is done.
                splash_bootstrap_go[0] = True
            splash_t0[0] = now - float(held) * frame_dt
            if held not in _splash_hold_since:
                _splash_hold_since[held] = now
                try:
                    sys.stderr.write(
                        f"pigeon: splash hold frame={held} "
                        f"+{now - _app_startup_mono:.3f}s\n"
                    )
                    sys.stderr.flush()
                except Exception:
                    pass
            root.after(16, splash_tick)
            return
        if held in _splash_hold_since and _splash_hold_since[held] is not None:
            try:
                sys.stderr.write(
                    f"pigeon: splash hold frame={held} released after "
                    f"{now - float(_splash_hold_since[held]):.3f}s\n"
                )
                sys.stderr.flush()
            except Exception:
                pass
            _splash_hold_since[held] = None
    t0 = float(splash_t0[0])
    if float(SPLASH_MAX_DURATION_S) > 0 and now - t0 > float(SPLASH_MAX_DURATION_S):
        splash_idx[0] = ntot
    # Strict order. A held frame looks better than a skip on the Pi.
    i = min(int(splash_idx[0]), ntot)
    if i >= ntot:
        splash_anim_done[0] = True
        try:
            sys.stderr.write(
                f"pigeon: splash sequence done +{time.monotonic() - _app_startup_mono:.3f}s "
                f"frames={ntot}\n"
            )
            sys.stderr.flush()
        except Exception:
            pass
        _try_remove_splash_overlay()
        return

    live_clock_underlay = _splash_frame_keeps_live_clock(i)
    rgb_hit = None if live_clock_underlay else _splash_rgb_cache.get(i)
    bgra_hit = _splash_bgra_cache.get(i) if rgb_hit is None else None
    if live_clock_underlay:
        bgra_hit = _splash_bgra_cache.get(i)

    # Worker hasn't reached this index yet: try a short spin before giving up.
    if rgb_hit is None and bgra_hit is None:
        _splash_fallback_frame_sync(i)
        if live_clock_underlay:
            bgra_hit = _splash_bgra_cache.get(i)
        else:
            rgb_hit = _splash_rgb_cache.get(i)
            bgra_hit = _splash_bgra_cache.get(i) if rgb_hit is None else None
        if rgb_hit is None and bgra_hit is None:
            # Wait for the prebake worker instead of jumping — skips look choppy.
            root.after(8, splash_tick)
            return

    # Reveal frame+: UI under the splash PNG alpha. Before that: black only.
    if i >= _splash_reveal_i:
        first_reveal = not _splash_reveal_clock[0]
        _reveal_clock_under_splash(refresh=False)
        if first_reveal:
            try:
                import threading

                threading.Thread(
                    target=_splash_prebake_reveal_bgra,
                    name="pigeon-splash-reveal-bake",
                    daemon=True,
                ).start()
            except Exception:
                _splash_prebake_reveal_bgra()
            try:
                sys.stderr.write(
                    f"pigeon: splash clock reveal frame={i} "
                    f"+{time.monotonic() - _app_startup_mono:.3f}s\n"
                )
                sys.stderr.flush()
            except Exception:
                pass

    splash_idx[0] = i + 1

    try:
        if rgb_hit is not None and not live_clock_underlay:
            _splash_update_photo(rgb_hit, splash_photo=splash_photo)
        else:
            fade_mul = (
                splash_end_fade_factor(i, ntot, min(_splash_fade_frames, ntot))
                if _splash_fade_frames > 0 and splash_end_fade_factor is not None
                else 1.0
            )
            _splash_composite_bgra_to_photo(bgra_hit, float(fade_mul))
    except Exception:
        # Best-effort RGB fallback so a single bad frame doesn't abort the splash.
        try:
            fb = rgb_hit if rgb_hit is not None else flatten_bgra_over_bg_to_rgb(
                bgra_hit if bgra_hit is not None else np.zeros((WINDOW_H, WINDOW_W, 4), np.uint8),
                _splash_bg_bgr,
            )
            _splash_update_photo(fb, splash_photo=splash_photo)
        except Exception:
            pass
    # The label remains bound to the same PhotoImage; paste() updates its pixels.
    # Configure only if this was the first frame and the image was just created.
    if splash_label.cget("image") != str(splash_photo[0]):
        splash_label.configure(image=splash_photo[0])
    # Played frames are never shown again; free them (~3–4 MB each at 1280×800).
    for _cache in (_splash_rgb_cache, _splash_bgra_cache, _splash_photo_cache):
        _cache.pop(i - 1, None)
    # Hold a late frame rather than jumping; catch up on the next tick.
    now2 = time.monotonic()
    next_i = int(splash_idx[0])
    target = t0 + float(next_i) * frame_dt
    delay_ms = int(round((target - now2) * 1000.0))
    if delay_ms < 1:
        delay_ms = 1
    elif delay_ms > frame_ms * 3:
        delay_ms = frame_ms
    root.after(delay_ms, splash_tick)


def splash_mpv_tick(*, _app_startup_mono, _splash_reveal_i, frame_dt, mpv_host, player, root, splash_idx, splash_mpv_tick, splash_t0, splash_tick) -> None:
    """Wait for mpv to land on the reveal frame, then hand playback to ``splash_tick``.

    mpv plays frames ``0.._splash_reveal_i`` in ``mpv_host``; ``splash_idx`` already
    points at the reveal frame so the prebake worker only decodes the outro.
    """
    if not player.done:
        root.after(16, splash_mpv_tick)
        return
    try:
        sys.stderr.write(
            f"pigeon: splash mpv handoff frame={_splash_reveal_i} "
            f"{'ok' if player.ended else 'early (mpv failed)'} "
            f"+{time.monotonic() - _app_startup_mono:.3f}s\n"
        )
        sys.stderr.flush()
    except Exception:
        pass
    # Timeline as if Tk had played every frame up to the reveal frame.
    splash_t0[0] = time.monotonic() - float(_splash_reveal_i) * frame_dt
    splash_tick()

    def _drop_mpv() -> None:
        # Keep mpv on top until Tk has the reveal frame painted underneath it.
        if int(splash_idx[0]) <= int(_splash_reveal_i):
            root.after(4, _drop_mpv)
            return
        try:
            root.update_idletasks()
            mpv_host.destroy()
        except tk.TclError:
            pass
        player.stop()

    _drop_mpv()


def _bootstrap_after_splash(*, _app_startup_mono, _bootstrap_after_splash, bootstrap, root, splash_anim_done, splash_bootstrap_go) -> None:
    """Run bootstrap once the splash parks on its logo hold (or ends, for short splashes).

    With the mpv splash, ``splash_bootstrap_go`` is set up front: mpv plays on its own
    threads, so bootstrap runs from the first frame.
    """
    if not (splash_anim_done[0] or splash_bootstrap_go[0]):
        root.after(16, _bootstrap_after_splash)
        return
    try:
        sys.stderr.write(
            f"pigeon: starting bootstrap under splash "
            f"+{time.monotonic() - _app_startup_mono:.3f}s\n"
        )
        sys.stderr.flush()
    except Exception:
        pass
    bootstrap()
