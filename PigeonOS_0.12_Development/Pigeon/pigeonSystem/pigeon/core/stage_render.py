"""Stage / frame rendering helpers and render scheduling.

Extracted verbatim from ``bootstrap()`` in ``pigeon_0_12.py``. Each function
takes the app state it used to close over as keyword-only arguments;
``bootstrap()`` binds them once with ``bind_deps`` so call sites are unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import tkinter as tk
import cv2
import numpy as np
from pigeon.stage_background import bgr_to_tk_hex
from pigeon.stage_background import get_stage_bgr
from pigeon.compositing import cv_resize_interp
import sys
from pigeon.version import version_string
from pathlib import Path
from pigeon.stage_background import set_stage_bgr
import time

from pigeon.core import frame_scope as _frame_scope
from pigeon.core import frame_stats as _frame_stats

if TYPE_CHECKING:
    from pigeon_0_12 import DisplayView, SceneFit


def _black_screen_bgr(*, display_dims) -> np.ndarray:
    sb, sg, sr = get_stage_bgr()
    out = np.empty((display_dims[1], display_dims[0], 3), dtype=np.uint8)
    out[:] = (sb, sg, sr)
    return out


# TopGradient.png removed — top gradient overlay disabled (no-op).
def _blend_top_gradient_design(canvas: np.ndarray) -> None:
    return


def _blend_top_gradient_fast(base: np.ndarray, cap_w: int, cap_h: int) -> None:
    return


def _apply_stage_chrome_colors(*, label, video_area) -> None:
    b, g, r = get_stage_bgr()
    hx = bgr_to_tk_hex(b, g, r)
    try:
        video_area.configure(bg=hx)
        label.configure(bg=hx)
    except tk.TclError:
        pass


def _styled_video_content_c_poster(src_bgra: np.ndarray | None) -> np.ndarray | None:
    """Return poster BGRA with rounded corners + faint white border for viewOne.videoContent_c."""
    if src_bgra is None or src_bgra.size == 0 or src_bgra.ndim != 3:
        return None
    if src_bgra.shape[2] == 4:
        out = src_bgra.copy()
    elif src_bgra.shape[2] == 3:
        out = cv2.cvtColor(src_bgra, cv2.COLOR_BGR2BGRA)
    else:
        return None
    h, w = int(out.shape[0]), int(out.shape[1])
    if h < 4 or w < 4:
        return out

    radius = max(6, int(round(min(w, h) * 0.035)))
    radius = min(radius, max(1, (min(w, h) // 2) - 1))

    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.rectangle(mask, (radius, 0), (w - radius, h), 255, thickness=-1)
    cv2.rectangle(mask, (0, radius), (w, h - radius), 255, thickness=-1)
    cv2.circle(mask, (radius, radius), radius, 255, thickness=-1)
    cv2.circle(mask, (w - radius, radius), radius, 255, thickness=-1)
    cv2.circle(mask, (radius, h - radius), radius, 255, thickness=-1)
    cv2.circle(mask, (w - radius, h - radius), radius, 255, thickness=-1)

    out_alpha = out[:, :, 3].astype(np.float32) * (mask.astype(np.float32) / 255.0)
    out[:, :, 3] = np.clip(out_alpha, 0, 255).astype(np.uint8)

    stroke = max(1, int(round(min(w, h) * 0.006)))
    if stroke > 0 and (h - 2 * stroke) > 2 and (w - 2 * stroke) > 2:
        inner = np.zeros((h, w), dtype=np.uint8)
        ir = max(1, radius - stroke)
        cv2.rectangle(inner, (stroke + ir, stroke), (w - stroke - ir, h - stroke), 255, thickness=-1)
        cv2.rectangle(inner, (stroke, stroke + ir), (w - stroke, h - stroke - ir), 255, thickness=-1)
        cv2.circle(inner, (stroke + ir, stroke + ir), ir, 255, thickness=-1)
        cv2.circle(inner, (w - stroke - ir, stroke + ir), ir, 255, thickness=-1)
        cv2.circle(inner, (stroke + ir, h - stroke - ir), ir, 255, thickness=-1)
        cv2.circle(inner, (w - stroke - ir, h - stroke - ir), ir, 255, thickness=-1)
        border = cv2.subtract(mask, inner)
    else:
        border = np.zeros((h, w), dtype=np.uint8)
    if np.any(border > 0):
        out[border > 0, 0] = 255
        out[border > 0, 1] = 255
        out[border > 0, 2] = 255
        out[border > 0, 3] = np.maximum(out[border > 0, 3], 96)
    return out


def place_command_bar(*, _ui_scale, command_bar, display_dims) -> None:
    dw, dh = display_dims[0], display_dims[1]
    ui = _ui_scale()
    bar_h = max(24, int(32 * ui))
    yb = dh - bar_h - int(4 * ui)
    command_bar.place(x=0, y=yb, width=dw, height=bar_h)


def _apply_dev_phase_widgets(*, label, settings_frame) -> None:
    # settings_main composites onto the video label; never pack the Tk form.
    try:
        settings_frame.pack_forget()
    except tk.TclError:
        pass
    label.pack(fill=tk.BOTH, expand=True)


# Next live-audio frame deadline (perf_counter seconds), or None.
_LIVE_PACE: list[float | None] = [None]


def _live_pace_delay_ms(frame_t0: float, now: float, interval_ms: int) -> int:
    """Delay to the next slot on a fixed ``interval_ms`` grid.

    Scheduling each frame "interval minus this render" let Tk timer latency
    and the label redraw add ~2 ms to every frame (35 ms, not 33). Deadlines
    step from the previous deadline instead, so that slack is absorbed. A
    frame that misses a whole slot re-anchors the grid (no catch-up burst).
    """
    step = interval_ms / 1000.0
    prev = _LIVE_PACE[0]
    nxt = (prev + step) if prev is not None else (frame_t0 + step)
    if nxt < now - step or nxt > now + 2 * step:
        nxt = max(now, frame_t0 + step)
    _LIVE_PACE[0] = nxt
    return max(1, int(round((nxt - now) * 1000.0)))


def _invoke_render_after(*, _render_after_id, render_once) -> None:
    _render_after_id[0] = None
    t0 = time.perf_counter()
    with _frame_scope.render_frame():
        render_once()
    _frame_stats.note_render(t0, time.perf_counter())


def _schedule_render_oneshot(delay_ms: int, *, _invoke_render_after, _render_after_id, root) -> None:
    if _render_after_id[0] is not None:
        try:
            root.after_cancel(_render_after_id[0])
        except tk.TclError:
            pass
    _render_after_id[0] = root.after(max(1, int(delay_ms)), _invoke_render_after)


def _disp_fit(*, fit_holder) -> SceneFit:
    return fit_holder[0]


def _stage_grid_overlay_mode(*, DisplayView, display_view_holder, view_five_mode_holder) -> str:
    """Overlay mode for grid rendering."""
    if display_view_holder[0] == DisplayView.FIVE:
        vf = int(view_five_mode_holder[0])
        if vf == 1:
            return "absolute_lines_fractional"
        if vf == 2:
            return "absolute_lines_test"
        return "absolute_lines"
    return "legacy_grid"


def _record_live_audio_timing(t0: float, t1: float, t2: float, *, _hitch_parts, _live_perf) -> None:
    compose_ms = (t1 - t0) * 1000.0
    upload_ms = (t2 - t1) * 1000.0
    _live_perf[1] += 1.0
    _live_perf[2] += compose_ms
    _live_perf[3] += upload_ms
    if compose_ms > _live_perf[4]:
        _live_perf[4] = compose_ms
    if compose_ms >= 40.0:
        try:
            sys.stderr.write(
                "pigeon: live hitch "
                f"compose={compose_ms:.1f}ms "
                f"sync={_hitch_parts[0]:.1f}ms "
                f"render={_hitch_parts[1]:.1f}ms "
                f"upload={upload_ms:.1f}ms\n"
            )
        except Exception:
            pass
    if t2 - _live_perf[0] < 2.0 or _live_perf[1] < 1.0:
        return
    n = max(1.0, _live_perf[1])
    try:
        sys.stderr.write(
            "pigeon: live audio "
            f"{int(n)}f compose={_live_perf[2] / n:.1f}ms "
            f"max={_live_perf[4]:.1f}ms "
            f"upload={_live_perf[3] / n:.1f}ms\n"
        )
    except Exception:
        pass
    _live_perf[0] = t2
    _live_perf[1] = 0.0
    _live_perf[2] = 0.0
    _live_perf[3] = 0.0
    _live_perf[4] = 0.0


def _design_rect_to_target(
    wx: int, wy: int, ww: int, wh: int, Wt: int, Ht: int
, *, DESIGN_H, DESIGN_W) -> tuple[int, int, int, int]:
    """Map a design-canvas rectangle to target size Wt×Ht (same math as final window mapping)."""
    Wd, Hd = DESIGN_W, DESIGN_H
    scaled_w = int(round(Wd * Ht / float(Hd)))
    x_off = max(0, (scaled_w - Wt) // 2)

    def mx(xd: float) -> int:
        return int(round(xd * scaled_w / float(Wd))) - x_off

    def my(yd: float) -> int:
        return int(round(yd * Ht / float(Hd)))

    x0, y0 = mx(wx), my(wy)
    x1, y1 = mx(wx + ww), my(wy + wh)
    rw = max(1, x1 - x0)
    rh = max(1, y1 - y0)
    if x0 < 0:
        rw += x0
        x0 = 0
    if y0 < 0:
        rh += y0
        y0 = 0
    rw = min(rw, Wt - x0)
    rh = min(rh, Ht - y0)
    if rw < 1 or rh < 1:
        return (0, 0, 1, 1)
    return (x0, y0, rw, rh)


def _paste_bgra_contain_on_design(
    canvas_bgr: np.ndarray,
    patch_bgra: np.ndarray | None,
    rect: tuple[int, int, int, int] | list[int],
    *, DESIGN_H, DESIGN_W, alpha_blend_bgra_over_bgr,
) -> None:
    """Paste ``patch_bgra`` centered inside ``rect`` on a design-sized
    BGR canvas using uniform contain-fit (no crop)."""
    if patch_bgra is None or alpha_blend_bgra_over_bgr is None:
        return
    rx, ry, rw, rh = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
    if rw < 1 or rh < 1:
        return
    ph, pw = int(patch_bgra.shape[0]), int(patch_bgra.shape[1])
    if pw < 1 or ph < 1:
        return
    scale = min(rw / float(pw), rh / float(ph))
    nw = max(1, int(round(pw * scale)))
    nh = max(1, int(round(ph * scale)))
    rsz = cv2.resize(
        patch_bgra,
        (nw, nh),
        interpolation=cv_resize_interp(pw, ph, nw, nh),
    )
    ox = rx + (rw - nw) // 2
    oy = ry + (rh - nh) // 2
    dst_x0 = max(0, ox)
    dst_y0 = max(0, oy)
    dst_x1 = min(DESIGN_W, ox + nw)
    dst_y1 = min(DESIGN_H, oy + nh)
    if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
        return
    src_x0 = dst_x0 - ox
    src_y0 = dst_y0 - oy
    cw = dst_x1 - dst_x0
    ch = dst_y1 - dst_y0
    crop = rsz[src_y0 : src_y0 + ch, src_x0 : src_x0 + cw]
    sub = canvas_bgr[dst_y0:dst_y1, dst_x0:dst_x1]
    sub[:] = alpha_blend_bgra_over_bgr(sub, crop)


def _ui_scale(*, WINDOW_H, WINDOW_W, display_dims) -> float:
    dw, dh = display_dims[0], display_dims[1]
    return max(0.45, min(min(dw / float(WINDOW_W), dh / float(WINDOW_H)), 5.0))


def _location_toast_alpha(now: float, *, LOCATION_TOAST_FADE_S, LOCATION_TOAST_FULL_S, location_toast_state) -> float:
    st = location_toast_state
    if not st["active"]:
        return 0.0
    hold = float(st.get("hold_full_s", LOCATION_TOAST_FULL_S))
    elapsed = now - float(st["t0"])
    if elapsed < hold:
        return 1.0
    if elapsed < hold + LOCATION_TOAST_FADE_S:
        return max(0.0, 1.0 - (elapsed - hold) / LOCATION_TOAST_FADE_S)
    st["active"] = False
    return 0.0


def _info_cluster_compose_active(now_mono: float, *, DevPhase, DisplayView, _PIGEON_EXT, _clock_saver_for_compose, _effective_display_view, _view_one_uses_now_playing_screen, dev_phase) -> bool:
    if not _PIGEON_EXT:
        return False
    if dev_phase[0] != DevPhase.OFF:
        return False
    if _effective_display_view() == DisplayView.FOUR:
        return False
    if _clock_saver_for_compose(now_mono):
        return False
    # New now-playing screen (070326) draws clock, audio config, and volume.
    if _view_one_uses_now_playing_screen():
        return False
    return True


def _effective_display_view(*, DevPhase, DisplayView, _PIGEON_EXT, dev_phase, display_view_holder) -> DisplayView:
    """Logical display for composition. GRID / view 5 overlay preview as view 1 + snapshot layout."""
    if _PIGEON_EXT and (
        dev_phase[0] == DevPhase.GRID or display_view_holder[0] == DisplayView.FIVE
    ):
        return DisplayView.ONE
    return display_view_holder[0]


def _design_grid_overlay_active(*, DevPhase, DisplayView, dev_phase, display_view_holder) -> bool:
    """Grid overlay on the composite (developer GRID phase or view 5)."""
    return dev_phase[0] == DevPhase.GRID or display_view_holder[0] == DisplayView.FIVE


def _blend_info_cluster_into_target(
    target: np.ndarray, cap_w: int, cap_h: int, now_mono: float
, *, _design_rect_to_target, _info_cluster_compose_active, _warm_info_cluster_blits, alpha_blend_bgra_over_bgr, info_cluster_blits) -> None:
    if not _info_cluster_compose_active(now_mono):
        return
    _warm_info_cluster_blits(now_mono)
    if not info_cluster_blits[0] or alpha_blend_bgra_over_bgr is None:
        return
    for ib in info_cluster_blits[0]:
        x0b, y0b, wwb, whb = int(ib.x), int(ib.y), int(ib.w), int(ib.h)
        x2, y2, rw2, rh2 = _design_rect_to_target(x0b, y0b, wwb, whb, cap_w, cap_h)
        _ph2, _pw2 = ib.bgra.shape[:2]
        patch = cv2.resize(
            ib.bgra,
            (rw2, rh2),
            interpolation=cv_resize_interp(_pw2, _ph2, rw2, rh2),
        )
        sub = target[y2 : y2 + rh2, x2 : x2 + rw2]
        sub[:] = alpha_blend_bgra_over_bgr(sub, patch)


def sync_developer_chrome(*, DevPhase, _PIGEON_EXT, _apply_dev_phase_widgets, _layout_chrome, _settings_unbind_wheel_globals, _start_location_toast, command_bar, command_entry_visible, dev_phase, hide_command_entry, label, place_command_bar, prev_dev_phase_for_location_toast, root) -> None:
    was_phase = prev_dev_phase_for_location_toast[0]
    _apply_dev_phase_widgets()
    _layout_chrome()
    if dev_phase[0] == DevPhase.GRID:
        root.title(f"Pigeon {version_string()} — Developer mode (grid)")
        label.configure(
            highlightthickness=3,
            highlightbackground="#0a84ff",
            highlightcolor="#0a84ff",
        )
    elif dev_phase[0] == DevPhase.MAIN_SETTINGS:
        root.title(f"Pigeon {version_string()} — settings")
        try:
            label.configure(highlightthickness=0)
        except tk.TclError:
            pass
    else:
        root.title("")
        label.configure(highlightthickness=0)
        hide_command_entry()
    _settings_unbind_wheel_globals()
    if command_entry_visible[0]:
        place_command_bar()
        command_bar.lift()
    if _PIGEON_EXT and dev_phase[0] == DevPhase.OFF and was_phase != DevPhase.OFF:
        # Keep the same launch placement after leaving Settings.
        _start_location_toast(startup=True)
    prev_dev_phase_for_location_toast[0] = dev_phase[0]


def _on_advanced_matrix_closed(*, advanced_matrix_restore_phase, dev_phase, skip_cache, sync_developer_chrome) -> None:
    tgt = advanced_matrix_restore_phase[0]
    if tgt is not None:
        advanced_matrix_restore_phase[0] = None
        dev_phase[0] = tgt  # type: ignore[assignment]
        skip_cache[0] = None
        sync_developer_chrome()


def _refresh_stage_from_poster(*, _PIGEON_EXT, _apply_stage_chrome_colors, black_photo, skip_cache) -> None:
    if not _PIGEON_EXT:
        set_stage_bgr(0, 0, 0)
    else:
        from pigeon.widgets.poster_art import sync_stage_background_from_active_poster

        sync_stage_background_from_active_poster()
    _apply_stage_chrome_colors()
    black_photo[0] = None
    skip_cache[0] = None


def _compose_shown_frame(frame_bgr: np.ndarray | None, brightness: float, *, DESIGN_H, DESIGN_W, DisplayView, SceneFit, ViewOneVariant, _PIGEON_EXT, _PROJECT_DIR, _app_logo_clock_saver_style_now, _apply_brightness, _backdrop_active_for_view, _black_screen_bgr, _clock_saver_for_compose, _composite_cap_dims, _current_app_display_name, _current_view_one_variant, _design_grid_overlay_active, _effective_display_view, _paste_bgra_contain_on_design, _playback_display_title, _present_frame_to_display, _resolve_streaming_app_logo_bgra, _view_one_is_pigeon_poster, _view_one_variant_uses_full_path, _view_one_variant_uses_simple_path, _view_one_video_content_a_tt_contain_rect_design, _vv_has_content_title, _vv_has_tmdb_bd, _vv_is_music, _vv_music_text_lines, backdrop_app_logo_letterbox_fit, backdrop_master_bgr, compose_display_fast_no_grid, compose_display_from_source, display_dims, load_pigeon_temp_logo_bgra, render_ui_music_text_patch_bgra, render_ui_text_patch_bgra, status_bar_widget, view_circles_widget) -> np.ndarray:
    if (
        _PIGEON_EXT
        and view_circles_widget is not None
        and _effective_display_view() == DisplayView.ONE
    ):
        return compose_display_fast_no_grid(
            frame_bgr,
            brightness,
            frame_is_display_sized=bool(
                frame_bgr is not None
                and frame_bgr.size > 0
                and int(frame_bgr.shape[0]) == int(DESIGN_H)
                and int(frame_bgr.shape[1]) == int(DESIGN_W)
            ),
        )

    def _view_one_dark_accent_bg_bgr() -> tuple[int, int, int]:
        """Darker variant of the current accent color for viewOne video a/c backgrounds.

        Stays black until ``pigeonTMDB_BD`` is ready (so the accent is actually
        sampled from a real backdrop, not the orange fallback).
        """
        if not _vv_has_tmdb_bd():
            return (0, 0, 0)
        if status_bar_widget is None:
            return (0, 0, 0)
        base = tuple(int(v) & 255 for v in status_bar_widget.accent_bgr)
        # Keep the hue but darken enough to sit behind TT/poster overlays.
        darken = 0.42
        return (
            int(round(base[0] * darken)),
            int(round(base[1] * darken)),
            int(round(base[2] * darken)),
        )

    if _PIGEON_EXT and _effective_display_view() == DisplayView.FOUR:
        return _black_screen_bgr()
    if (
        _PIGEON_EXT
        and _effective_display_view() != DisplayView.ONE
        and _view_one_is_pigeon_poster()
        and not _vv_is_music()
        and _vv_has_content_title()
    ):
        # viewOne.videoContent_c: black base + active TMDb poster only
        # (no pigeonTMDB_TT / no pigeonTMDB_BD), with the same chrome stack
        # as the other View One layouts. Poster occupies y=[0, top(row 7)].
        sb, sg, sr = _view_one_dark_accent_bg_bgr()
        black = np.empty((DESIGN_H, DESIGN_W, 3), dtype=np.uint8)
        black[:] = (sb, sg, sr)
        return compose_display_from_source(
            black,
            brightness,
            show_grid=_design_grid_overlay_active(),
            frame_is_design_sized=True,
        )
    if (
        _PIGEON_EXT
        and _effective_display_view() != DisplayView.ONE
        and _view_one_variant_uses_simple_path()
        and not _backdrop_active_for_view()
    ):
        sb, sg, sr = _view_one_dark_accent_bg_bgr()
        black = np.empty((DESIGN_H, DESIGN_W, 3), dtype=np.uint8)
        black[:] = (sb, sg, sr)
        sub2_logo_rect = _view_one_video_content_a_tt_contain_rect_design()
        # MediaType.Music override (viewOne.01): TMDb doesn't index music
        # tracks, so no pigeonTMDB_TT is available. Substitute a two-line
        # text patch (track title large; "Artist - Album" smaller beneath)
        # inside the same rect pigeonTMDB_TT would occupy. Short-circuits
        # the V# resolver dispatch below so Music content consistently
        # renders text regardless of which fallback variant would otherwise
        # apply. The single-small-line case in ``render_ui_music_text_patch_bgra``
        # gives the title ~76% of the box height and the subtitle the rest.
        if _vv_is_music() and render_ui_music_text_patch_bgra is not None:
            _m_title, _m_subtitle = _vv_music_text_lines()
            if _m_title or _m_subtitle:
                _music_bgra = render_ui_music_text_patch_bgra(
                    _m_title,
                    _m_subtitle,
                    "",
                    int(sub2_logo_rect[2]),
                    int(sub2_logo_rect[3]),
                )
                if _music_bgra is not None:
                    _paste_bgra_contain_on_design(
                        black, _music_bgra, sub2_logo_rect
                    )
                    return compose_display_from_source(
                        black,
                        brightness,
                        show_grid=_design_grid_overlay_active(),
                        frame_is_design_sized=True,
                    )
        # Variant-aware TT-slot content. V01/V04 draw the real pigeonTMDB_TT via
        # compose_display_from_source (post–v0.6.14 swap: V01 is the TT-only default,
        # V04 is the BD-missing alternate); V06/.07/.08/.09 substitute a generated
        # patch (title text / appLogo / app name / pigeonTempLogo).
        _vv_simple = _current_view_one_variant()
        _vv_use_default_tt = ViewOneVariant is None or _vv_simple in (
            ViewOneVariant.V01,
            ViewOneVariant.V04,
        )
        if not _vv_use_default_tt:
            _override_bgra = None
            if _vv_simple == ViewOneVariant.V06 and render_ui_text_patch_bgra is not None:
                _override_bgra = render_ui_text_patch_bgra(
                    _playback_display_title(),
                    int(sub2_logo_rect[2]),
                    int(sub2_logo_rect[3]),
                )
            elif _vv_simple == ViewOneVariant.V07:
                _override_bgra = _resolve_streaming_app_logo_bgra()
            elif _vv_simple == ViewOneVariant.V08 and render_ui_text_patch_bgra is not None:
                _override_bgra = render_ui_text_patch_bgra(
                    _current_app_display_name(),
                    int(sub2_logo_rect[2]),
                    int(sub2_logo_rect[3]),
                )
            elif _vv_simple == ViewOneVariant.V09 and load_pigeon_temp_logo_bgra is not None:
                # Keep startup/no-content logo treatment centered, matching other app-logo
                # presentations, while preserving the same max slot size.
                _rw = max(1, int(sub2_logo_rect[2]))
                _rh = max(1, int(sub2_logo_rect[3]))
                _rx = max(0, (int(DESIGN_W) - _rw) // 2)
                _ry = max(0, (int(DESIGN_H) - _rh) // 2)
                sub2_logo_rect = (_rx, _ry, _rw, _rh)
                _override_bgra = load_pigeon_temp_logo_bgra(
                    Path(_PROJECT_DIR) / "pigeonAssets"
                )
                if _override_bgra is None:
                    print(
                        "pigeon: pigeonAssets/App logos/AppLogo_Pigeon.png not found — "
                        "viewOne.noContent will render black only.",
                        file=sys.stderr,
                    )
                else:
                    # viewOne.noContent: Pigeon logo at 30% opacity.
                    _override_bgra = _override_bgra.copy()
                    _override_bgra[..., 3] = (
                        _override_bgra[..., 3].astype(np.float32) * 0.30
                    ).clip(0, 255).astype(np.uint8)
            _v07_skip_tt_for_clock_saver = (
                _vv_simple == ViewOneVariant.V07
                and _clock_saver_for_compose(time.monotonic())
            )
            if not _v07_skip_tt_for_clock_saver:
                _paste_bgra_contain_on_design(
                    black, _override_bgra, sub2_logo_rect
                )
            return compose_display_from_source(
                black,
                brightness,
                show_grid=_design_grid_overlay_active(),
                frame_is_design_sized=True,
            )
        return compose_display_from_source(
            black,
            brightness,
            show_grid=_design_grid_overlay_active(),
            frame_is_design_sized=True,
            tmdb_logo_cover_design_xywh=sub2_logo_rect,
        )
    # View 2 backdrop + visualizer-only is handled in ``compose_display_fast_no_grid``.
    # View 1 pigeonFull also uses that backdrop fast path.
    if (
        _backdrop_active_for_view()
        and backdrop_master_bgr[0] is not None
        and _effective_display_view() != DisplayView.TWO
        and not _view_one_variant_uses_full_path()
    ):
        from pigeon.image_ui_protocol import build_backdrop_design_layer_bgr

        if not _PIGEON_EXT:
            # Legacy path: use backdrop-only display if extension isn't available.
            bd = build_backdrop_design_layer_bgr(
                backdrop_master_bgr[0],
                app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit[0],
                app_logo_clock_saver_style=_app_logo_clock_saver_style_now(),
            )
            return compose_display_from_source(bd, brightness, show_grid=False, frame_is_design_sized=True)
        bd = build_backdrop_design_layer_bgr(
            backdrop_master_bgr[0],
            app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit[0],
            app_logo_clock_saver_style=_app_logo_clock_saver_style_now(),
        )
        return compose_display_from_source(
            bd,
            brightness,
            show_grid=_design_grid_overlay_active(),
            frame_is_design_sized=True,
        )

    if not _PIGEON_EXT:
        if frame_bgr is None or frame_bgr.size == 0:
            return _black_screen_bgr()
        lit = _apply_brightness(frame_bgr, brightness)
        dw, dh = display_dims[0], display_dims[1]
        cw, ch, cap_down = _composite_cap_dims(dw, dh)
        small = SceneFit(target_w=cw, target_h=ch).scale_and_crop(lit)
        if cap_down:
            return _present_frame_to_display(small, dw, dh)
        return small
    if _PIGEON_EXT and _design_grid_overlay_active():
        return compose_display_from_source(frame_bgr, brightness, show_grid=True)
    return compose_display_fast_no_grid(frame_bgr, brightness)


def _backdrop_active_for_view(*, DisplayView, _effective_display_view, use_backdrop_scene) -> bool:
    """True when backdrop scene should be used by the current effective view."""
    return bool(use_backdrop_scene[0] and _effective_display_view() != DisplayView.SIX)


def _warm_info_cluster_blits(now_mono: float, *, _PIGEON_EXT, _info_cluster_blits_sig, _info_cluster_compose_active, _location_toast_alpha, build_info_cluster_design_patches, info_cluster_blits, info_cluster_clock_widget, location_toast_state, receiver_overlay_state, status_bar_widget) -> None:
    if (
        not _PIGEON_EXT
        or build_info_cluster_design_patches is None
        or info_cluster_clock_widget is None
    ):
        info_cluster_blits[0] = []
        _info_cluster_blits_sig[0] = None
        return
    if not _info_cluster_compose_active(now_mono):
        info_cluster_blits[0] = []
        _info_cluster_blits_sig[0] = None
        return
    st = location_toast_state
    startup_tl = bool(st.get("startup_top_left"))
    ta = (
        _location_toast_alpha(now_mono)
        if (bool(st.get("active")) and not startup_tl)
        else 0.0
    )
    acc: tuple[int, int, int] | None = (
        tuple(status_bar_widget.accent_bgr)
        if status_bar_widget is not None
        else None
    )
    sig = (
        int(time.time()),
        str(receiver_overlay_state.get("config", "")),
        str(receiver_overlay_state.get("volume", "")),
        str(st.get("text", "")),
        int(round(float(ta) * 1000.0)),
        int(bool(startup_tl)),
        acc,
    )
    if sig == _info_cluster_blits_sig[0]:
        return
    _info_cluster_blits_sig[0] = sig
    info_cluster_blits[0] = build_info_cluster_design_patches(
        clock_widget=info_cluster_clock_widget,
        audio_config=str(receiver_overlay_state.get("config", "")),
        volume=str(receiver_overlay_state.get("volume", "")),
        location=str(st.get("text", "")),
        location_alpha=float(ta),
        shadow_bgr=acc,
    )


def compose_display_from_source(
    frame_bgr: np.ndarray | None,
    brightness: float,
    *,
    show_grid: bool,
    frame_is_design_sized: bool = False,
    tmdb_logo_cover_design_xywh: tuple[int, int, int, int] | None = None,
    CLOCK_ANCHOR_COL, CLOCK_ANCHOR_ROW, DESIGN_H, DESIGN_W, DevPhase, DisplayView, PATCH_LAYER_RECEIVER_AUDIO, SceneFit, _PIGEON_EXT, _active_tmdb_logo_widget, _active_tmdb_poster_bgra, _apply_auto_widget_policy, _apply_brightness, _blend_info_cluster_into_target, _blend_top_gradient_design, _blit_saver_layers_design, _clock_saver_backdrop_brightness, _clock_saver_dim_overlay_bgra, _clock_saver_dim_pre_digit_canvas, _clock_saver_for_compose, _clock_saver_layer_opacity, _clock_saver_layers, _clock_startup_intro_opacity, _compose_paused_screen, _composite_cap_dims, _composite_settings_on_canvas, _effective_display_view, _hitch_parts, _idle_audio_meter_active, _info_cluster_compose_active, _location_toast_alpha, _maybe_exit_settings_menus_on_idle, _paused_screen_active, _present_frame_to_display, _set_playback_overlay_clock_saver_volume_flag, _settings_is_native_1280, _show_paused_row_overlay, _splash_reveal_clock, _stage_grid_overlay_mode, _styled_video_content_c_poster, _sync_now_playing_screen_state_for_frame, _view_one_is_pigeon_poster, _view_one_uses_now_playing_screen, _view_one_video_content_a_tt_contain_rect_design, _vv_is_music, _warm_playback_overlay_blits, active_tmdb_display_title, active_tmdb_title_key, alpha_blend_bgra_over_bgr, blend_overlay_bgr, build_stage_overlay_source_bgra, clock_widget, dev_phase, display_dims, get_grid_geometry, location_toast_patch_bgra, location_toast_state, main_settings_widget, playback_lower_gradient_bgra, playback_overlay_flags, playback_overlay_widget, scale_cover_center_crop, scale_height_and_center_crop, startup_ph, status_bar_widget, tmdb_tt_gradient_bgr_holder, view_circles_widget,
) -> np.ndarray:
    """
    Build display output: scale **source** video to design, draw widgets, optionally grid,
    then scale down. Using the raw frame avoids letterboxing an already 800×480 image (which shifted
    the grid/poster and cropped them on the left). Developer grid mode uses uniform letterboxing so
    the full design width (including grid column 1) is visible on narrow windows.
    """
    assert _PIGEON_EXT
    try:
        _apply_auto_widget_policy()
    except Exception:
        pass
    assert scale_height_and_center_crop is not None
    assert scale_cover_center_crop is not None
    assert blend_overlay_bgr is not None
    assert build_stage_overlay_source_bgra is not None

    def _paste_tmdb_logo_uniform_cover_design(
        canvas_bgr: np.ndarray,
        logo_w,
        rx: int,
        ry: int,
        rw: int,
        rh: int,
    ) -> None:
        if (
            logo_w is None
            or rw < 1
            or rh < 1
            or not active_tmdb_title_key[0]
            or alpha_blend_bgra_over_bgr is None
        ):
            return
        patch_bgra = logo_w.bgra_patch_for_title(
            active_tmdb_title_key[0],
            display_title=active_tmdb_display_title[0],
            patch_wh=(rw, rh),
        )
        ph, pw = int(patch_bgra.shape[0]), int(patch_bgra.shape[1])
        if pw < 1 or ph < 1:
            return
        # Uniform fit inside the grid box (no crop): largest scale where both dimensions fit;
        # centers the patch so ascenders / top caps are not clipped (cover would crop).
        scale_c = min(rw / float(pw), rh / float(ph))
        nw = max(1, int(round(pw * scale_c)))
        nh = max(1, int(round(ph * scale_c)))
        rsz = cv2.resize(
            patch_bgra,
            (nw, nh),
            interpolation=cv_resize_interp(pw, ph, nw, nh),
        )
        ox = rx + (rw - nw) // 2
        oy = ry + (rh - nh) // 2
        dst_x0 = max(0, ox)
        dst_y0 = max(0, oy)
        dst_x1 = min(DESIGN_W, ox + nw)
        dst_y1 = min(DESIGN_H, oy + nh)
        if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
            return
        src_x0 = dst_x0 - ox
        src_y0 = dst_y0 - oy
        cw = dst_x1 - dst_x0
        ch = dst_y1 - dst_y0
        crop2 = rsz[src_y0 : src_y0 + ch, src_x0 : src_x0 + cw]
        sub = canvas_bgr[dst_y0:dst_y1, dst_x0:dst_x1]
        sub[:] = alpha_blend_bgra_over_bgr(sub, crop2)

    def _paste_video_content_c_poster_above_top_gradient(canvas_bgr: np.ndarray) -> None:
        if (
            not _view_one_is_pigeon_poster()
            or _effective_display_view() != DisplayView.ONE
            or alpha_blend_bgra_over_bgr is None
            or get_grid_geometry is None
        ):
            return
        g = get_grid_geometry()
        # Full-width band, vertically centered in rows 1→7.5 so the poster reads centered
        # on the canvas (not biased toward the top margin above row 1).
        top_y = int(round(g.y0 + (1.0 - 1.0) * float(g.cell)))
        bottom_y = int(round(g.y0 + (7.5 - 1.0) * float(g.cell)))
        poster_h = max(1, bottom_y - top_y)
        rect = (0, int(top_y), int(DESIGN_W), int(poster_h))
        patch_bgra = _styled_video_content_c_poster(_active_tmdb_poster_bgra())
        if patch_bgra is None:
            return
        rx, ry, rw, rh = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
        ph, pw = int(patch_bgra.shape[0]), int(patch_bgra.shape[1])
        if rw < 1 or rh < 1 or pw < 1 or ph < 1:
            return
        scale = min(rw / float(pw), rh / float(ph))
        nw = max(1, int(round(pw * scale)))
        nh = max(1, int(round(ph * scale)))
        rsz = cv2.resize(
            patch_bgra,
            (nw, nh),
            interpolation=cv_resize_interp(pw, ph, nw, nh),
        )
        ox = rx + (rw - nw) // 2
        oy = ry + (rh - nh) // 2
        dst_x0 = max(0, ox)
        dst_y0 = max(0, oy)
        dst_x1 = min(DESIGN_W, ox + nw)
        dst_y1 = min(DESIGN_H, oy + nh)
        if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
            return
        src_x0 = dst_x0 - ox
        src_y0 = dst_y0 - oy
        cw = dst_x1 - dst_x0
        ch = dst_y1 - dst_y0
        crop2 = rsz[src_y0 : src_y0 + ch, src_x0 : src_x0 + cw]
        sub = canvas_bgr[dst_y0:dst_y1, dst_x0:dst_x1]
        sub[:] = alpha_blend_bgra_over_bgr(sub, crop2)
    if _paused_screen_active() and not show_grid:
        tw, th = display_dims[0], display_dims[1]
        cap_w, cap_h, use_cap = _composite_cap_dims(tw, th)
        base_pause = _compose_paused_screen(cap_w, cap_h)
        if use_cap:
            return _present_frame_to_display(base_pause, tw, th)
        return base_pause
    if frame_bgr is None or frame_bgr.size == 0:
        sb, sg, sr = get_stage_bgr()
        canvas = np.empty((DESIGN_H, DESIGN_W, 3), dtype=np.uint8)
        canvas[:] = (sb, sg, sr)
    else:
        lit = _apply_brightness(frame_bgr, brightness)
        if frame_is_design_sized:
            canvas = lit
        else:
            fit_d = SceneFit(target_w=DESIGN_W, target_h=DESIGN_H)
            canvas = fit_d.scale_and_crop(lit)
    # All widget/grid math is in design pixels (DESIGN_W×DESIGN_H). If the base layer is off-size
    # (e.g. a bad master path), resize so overlays are not clipped on the left before scaling to the window.
    ch_can, cw_can = int(canvas.shape[0]), int(canvas.shape[1])
    if cw_can != DESIGN_W or ch_can != DESIGN_H:
        canvas = cv2.resize(
            canvas,
            (DESIGN_W, DESIGN_H),
            interpolation=cv_resize_interp(cw_can, ch_can, DESIGN_W, DESIGN_H),
        )
    if not canvas.flags["C_CONTIGUOUS"]:
        canvas = np.ascontiguousarray(canvas)
    if _maybe_exit_settings_menus_on_idle():
        pass
    if dev_phase[0] == DevPhase.MAIN_SETTINGS and main_settings_widget is not None:
        _composite_settings_on_canvas(canvas)
        dw, dh = display_dims[0], display_dims[1]
        cap_w, cap_h, use_cap = _composite_cap_dims(dw, dh)
        if (
            int(cap_w) == int(DESIGN_W)
            and int(cap_h) == int(DESIGN_H)
        ):
            base2 = canvas
        else:
            base2 = cv2.resize(
                canvas,
                (cap_w, cap_h),
                interpolation=cv_resize_interp(
                    int(DESIGN_W), int(DESIGN_H), cap_w, cap_h
                ),
            )
        if use_cap:
            return _present_frame_to_display(
                base2, dw, dh, native_now_playing=True
            )
        return base2
    _set_playback_overlay_clock_saver_volume_flag()
    now_cs = time.monotonic()
    cs = _clock_saver_for_compose(now_cs) and not show_grid
    intro_op = _clock_startup_intro_opacity(now_cs)
    bdim_c = _clock_saver_backdrop_brightness(now_cs)
    if intro_op is not None:
        canvas[:] = 0
    elif bdim_c < 1.0 - 1e-6:
        canvas = (canvas.astype(np.float32) * bdim_c).astype(np.uint8)
    # Layer order: top gradient first, then bottom gradient (in the
    # non-saver branch below), then the mic/EQ visualizer on top of
    # the gradient, then clock saver / clock widget / overlays on
    # top of the visualizer. See the saver branch for the no-gradient
    # variant.
    if intro_op is None and not (_view_one_uses_now_playing_screen() and not cs):
        _blend_top_gradient_design(canvas)
    if not cs and _view_one_uses_now_playing_screen():
        canvas[:] = (0, 0, 0)
        if startup_ph[0] is not None and not _splash_reveal_clock[0]:
            # Pre-reveal splash underlay stays black.
            pass
        elif dev_phase[0] == DevPhase.MAIN_SETTINGS and main_settings_widget is not None:
            _composite_settings_on_canvas(canvas)
        else:
            t_sync0 = time.perf_counter()
            _sync_now_playing_screen_state_for_frame()
            t_sync1 = time.perf_counter()
            if view_circles_widget is not None:
                view_circles_widget.render(canvas)
            _hitch_parts[0] = (t_sync1 - t_sync0) * 1000.0
            _hitch_parts[1] = (time.perf_counter() - t_sync1) * 1000.0
    elif cs:
        if alpha_blend_bgra_over_bgr is not None:
            acc_cs = (
                tuple(status_bar_widget.accent_bgr)
                if status_bar_widget is not None
                else None
            )
            _cs_dim_d = _clock_saver_layer_opacity(now_cs)
            _meter_face_d = _idle_audio_meter_active(now_cs)
            if intro_op is None and not _meter_face_d:
                _clock_saver_dim_pre_digit_canvas(canvas, _cs_dim_d)
            _time_op_d = float(intro_op) if intro_op is not None else 1.0
            _date_op_d = float(intro_op) if intro_op is not None else _cs_dim_d
            (time_bgra, t_rect), (date_bgra, d_rect) = _clock_saver_layers(
                shadow_bgr=acc_cs,
                layer_opacity=_cs_dim_d,
                time_layer_opacity=_time_op_d,
                date_layer_opacity=_date_op_d,
                date_anchor_row=CLOCK_ANCHOR_ROW,
                date_anchor_col=CLOCK_ANCHOR_COL,
                replace_with_meter=_meter_face_d,
            )
            _blit_saver_layers_design(
                canvas,
                time_bgra,
                t_rect,
                date_bgra,
                d_rect,
                copy_full_bgr=_meter_face_d,
            )
            if playback_overlay_widget is not None and (
                playback_overlay_flags.get("clock_saver_volume_only")
                or playback_overlay_flags.get("clock_saver_netflix_full_overlay")
            ):
                ch, cw = canvas.shape[:2]
                for p in playback_overlay_widget.design_blits():
                    x, y, w, h = p.x, p.y, p.w, p.h
                    if w < 1 or h < 1:
                        continue
                    x0 = max(0, x)
                    y0 = max(0, y)
                    x1 = min(cw, x + w)
                    y1 = min(ch, y + h)
                    if x0 >= x1 or y0 >= y1:
                        continue
                    sx0 = x0 - x
                    sy0 = y0 - y
                    roi = canvas[y0:y1, x0:x1]
                    src = _clock_saver_dim_overlay_bgra(p.bgra, _cs_dim_d)
                    patch = src[sy0 : sy0 + (y1 - y0), sx0 : sx0 + (x1 - x0)]
                    roi[:] = alpha_blend_bgra_over_bgr(roi, patch)
    else:
        if (
            playback_lower_gradient_bgra is not None
            and alpha_blend_bgra_over_bgr is not None
            and not _vv_is_music()
        ):
            gx, gy, gw, gh, grad_bgra = playback_lower_gradient_bgra(
                gradient_bgr=tmdb_tt_gradient_bgr_holder[0]
            )
            sub = canvas[gy : gy + gh, gx : gx + gw]
            sub[:] = alpha_blend_bgra_over_bgr(sub, grad_bgra)
        # viewOne.videoContent_c poster: sits above the top gradient and
        # below the nowPlaying widget (status bar + playback overlay).
        _paste_video_content_c_poster_above_top_gradient(canvas)
        _warm_playback_overlay_blits()
        if clock_widget is not None and _effective_display_view() != DisplayView.FOUR:
            if _info_cluster_compose_active(now_cs):
                _blend_info_cluster_into_target(
                    canvas, int(DESIGN_W), int(DESIGN_H), now_cs
                )
            else:
                clock_widget.render(canvas)
        if status_bar_widget is not None:
            status_bar_widget.render(canvas)
        if playback_overlay_widget is not None and alpha_blend_bgra_over_bgr is not None:
            playback_overlay_flags["show_paused_row"] = _show_paused_row_overlay()
            ch, cw = canvas.shape[:2]
            for p in playback_overlay_widget.design_blits():
                if (
                    _info_cluster_compose_active(now_cs)
                    and getattr(p, "layer", "") == PATCH_LAYER_RECEIVER_AUDIO
                ):
                    continue
                x, y, w, h = p.x, p.y, p.w, p.h
                if w < 1 or h < 1:
                    continue
                x0 = max(0, x)
                y0 = max(0, y)
                x1 = min(cw, x + w)
                y1 = min(ch, y + h)
                if x0 >= x1 or y0 >= y1:
                    continue
                sx0 = x0 - x
                sy0 = y0 - y
                roi = canvas[y0:y1, x0:x1]
                patch = p.bgra[sy0 : sy0 + (y1 - y0), sx0 : sx0 + (x1 - x0)]
                roi[:] = alpha_blend_bgra_over_bgr(roi, patch)
        if (
            dev_phase[0] == DevPhase.OFF
            and location_toast_patch_bgra is not None
            and alpha_blend_bgra_over_bgr is not None
            and (
                not _info_cluster_compose_active(now_cs)
                or bool(location_toast_state.get("startup_top_left"))
            )
        ):
            now_lt = time.monotonic()
            ta = _location_toast_alpha(now_lt)
            if ta > 1e-6:
                acc = (
                    tuple(status_bar_widget.accent_bgr)
                    if status_bar_widget is not None
                    else None
                )
                patch_lt, (lwx, lwy, lww, lwh) = location_toast_patch_bgra(
                    str(location_toast_state["text"]),
                    alpha=ta,
                    shadow_bgr=acc,
                    col_right_offset_cells=0.0,
                    row_offset_cells=0.0,
                    startup_top_left=bool(
                        location_toast_state.get("startup_top_left")
                    ),
                )
                if patch_lt is not None:
                    sub = canvas[lwy : lwy + lwh, lwx : lwx + lww]
                    sub[:] = alpha_blend_bgra_over_bgr(sub, patch_lt)
        _logo_w2 = _active_tmdb_logo_widget()
        if _logo_w2 is not None and _effective_display_view() not in (
            DisplayView.FOUR,
            DisplayView.TWO,
            DisplayView.THREE,
        ) and not _view_one_is_pigeon_poster() and not _view_one_uses_now_playing_screen():
            if tmdb_logo_cover_design_xywh is not None:
                lx, ly, lw, lh = tmdb_logo_cover_design_xywh
                _paste_tmdb_logo_uniform_cover_design(
                    canvas, _logo_w2, int(lx), int(ly), int(lw), int(lh)
                )
            elif (
                _effective_display_view() == DisplayView.ONE
                and active_tmdb_title_key[0]
            ):
                _dwx, _dwy, _dww, _dwh = _view_one_video_content_a_tt_contain_rect_design()
                _paste_tmdb_logo_uniform_cover_design(
                    canvas, _logo_w2, int(_dwx), int(_dwy), int(_dww), int(_dwh)
                )
            else:
                _logo_w2.render(
                    canvas,
                    title_key_str=active_tmdb_title_key[0],
                    display_title=active_tmdb_display_title[0],
                )
    if show_grid:
        ov = build_stage_overlay_source_bgra(_stage_grid_overlay_mode())
        canvas = blend_overlay_bgr(canvas, ov)
    tw, th = display_dims[0], display_dims[1]
    native_np = (
        _view_one_uses_now_playing_screen()
        and dev_phase[0] == DevPhase.OFF
    ) or _settings_is_native_1280()
    return _present_frame_to_display(
        canvas, tw, th, native_now_playing=bool(native_np)
    )


def _layout_chrome(*, _ui_scale, command_entry_visible, display_dims, place_command_bar) -> None:
    dw, dh = display_dims[0], display_dims[1]
    _ui_scale()
    if command_entry_visible[0]:
        place_command_bar()


def cycle_dev_phase(_event=None, *, DevPhase, _bump_pigeon_user_activity, dev_phase, main_settings_widget, render_once, skip_cache, sync_developer_chrome) -> str:
    """Toggle OFF ↔ MAIN_SETTINGS (also exits GRID → OFF)."""
    _bump_pigeon_user_activity()
    if dev_phase[0] == DevPhase.MAIN_SETTINGS:
        if main_settings_widget is not None:
            try:
                if not bool(getattr(main_settings_widget.state, "exit_enabled", True)):
                    return "settings"
            except Exception:
                pass
        if main_settings_widget is not None:
            try:
                st_ms = main_settings_widget.state
                if st_ms.keyboard_open:
                    st_ms.close_keyboard(commit=False)
                st_ms.exit_pigeon_settings()
                main_settings_widget.invalidate()
            except Exception:
                pass
        dev_phase[0] = DevPhase.OFF
    elif dev_phase[0] == DevPhase.GRID:
        dev_phase[0] = DevPhase.OFF
    else:
        if main_settings_widget is not None:
            try:
                if main_settings_widget.state.keyboard_open:
                    main_settings_widget.state.close_keyboard(commit=False)
                    main_settings_widget.invalidate()
            except Exception:
                pass
            try:
                from pigeon.widgets.ui_color_settings import (
                    load_persisted_theme_into_state,
                )

                load_persisted_theme_into_state(main_settings_widget.state)
                main_settings_widget.invalidate()
            except Exception:
                pass
            try:
                main_settings_widget.prefetch_scans_for_settings()
            except Exception:
                pass
        dev_phase[0] = DevPhase.MAIN_SETTINGS
    skip_cache[0] = None
    sync_developer_chrome()
    if dev_phase[0] == DevPhase.MAIN_SETTINGS:
        try:
            from pigeon.weather import refresh_weather

            refresh_weather(force=True)
        except Exception:
            pass
        render_once()
    return "break"


def _refresh_clock_patch_bgra(*, _clock_patch_sig, clock_patch_bgra, clock_widget, info_cluster_clock_widget, status_bar_widget) -> None:
    if clock_widget is None:
        return
    t = int(time.time())
    if status_bar_widget is not None:
        acc: tuple[int, int, int] | None = tuple(status_bar_widget.accent_bgr)
        clock_widget.set_shadow_accent_bgr(acc)
        if info_cluster_clock_widget is not None:
            info_cluster_clock_widget.set_shadow_accent_bgr(acc)
    else:
        acc = None
    if (
        clock_patch_bgra[0] is not None
        and t == _clock_patch_sig[0]
        and acc == _clock_patch_sig[1]
    ):
        return
    clock_patch_bgra[0] = clock_widget.bgra_patch().copy()
    _clock_patch_sig[0] = t
    _clock_patch_sig[1] = acc


def toggle_play(_event=None, *, LANDING_DIM_BRIGHTNESS, LANDING_DISPLAY_BRIGHTNESS, _bump_pigeon_user_activity, brightness_current, brightness_duration_down_s, brightness_duration_s, brightness_duration_up_s, brightness_from, brightness_t0, brightness_target, last_frame, playing, scene_enabled, use_backdrop_scene) -> None:
    _bump_pigeon_user_activity()
    if not scene_enabled[0] or use_backdrop_scene[0] or last_frame[0] is None:
        return
    playing[0] = not playing[0]
    brightness_from[0] = brightness_current[0]
    # False → full brightness; True → slightly dimmed (inverse of old “video playing” semantics).
    brightness_target[0] = LANDING_DIM_BRIGHTNESS if playing[0] else LANDING_DISPLAY_BRIGHTNESS
    brightness_duration_s[0] = (
        brightness_duration_up_s if brightness_target[0] > brightness_from[0] else brightness_duration_down_s
    )
    brightness_t0[0] = time.monotonic()


def _open_landing_scene(*, _PIGEON_EXT, _default_render_fps, _disp_fit, backdrop_master_bgr, frame_interval_ms, landing_scene_design_bgr, last_frame, scaled_display, scaled_version, use_backdrop_scene) -> bool:
    """Black landing page + centered logo; clears TMDb backdrop display flags."""
    use_backdrop_scene[0] = False
    backdrop_master_bgr[0] = None
    last_frame[0] = landing_scene_design_bgr
    frame_interval_ms[0] = max(1, int(round(1000.0 / _default_render_fps())))
    if not _PIGEON_EXT:
        scaled_display[0] = _disp_fit().scale_and_crop(last_frame[0])
    else:
        scaled_display[0] = None
    scaled_version[0] += 1
    return True


def toggle_scene(_event=None, *, require_overlay: bool = True, _PIGEON_EXT, _apply_brightness, _bgr_to_tk_image, _black_screen_bgr, _bump_pigeon_user_activity, _compose_shown_frame, _design_grid_overlay_active, _open_landing_scene, _save_persisted_scene_enabled, _update_label_photo_from_bgr, backdrop_master_bgr, black_photo, brightness_current, label, label_live_photo, last_frame, playing, scaled_display, scene_enabled, skip_cache, use_backdrop_scene) -> None:
    _bump_pigeon_user_activity()
    if require_overlay and not _design_grid_overlay_active():
        return

    if scene_enabled[0]:
        playing[0] = False
        scene_enabled[0] = False
        use_backdrop_scene[0] = False
        backdrop_master_bgr[0] = None
    else:
        if not _open_landing_scene():
            return
        scene_enabled[0] = True

    _save_persisted_scene_enabled(scene_enabled[0])
    skip_cache[0] = None

    if not scene_enabled[0]:
        if _PIGEON_EXT:
            out_bgr = _compose_shown_frame(None, 1.0)
            _update_label_photo_from_bgr(label, out_bgr, label_live_photo)
        else:
            if black_photo[0] is None:
                black_photo[0] = _bgr_to_tk_image(_black_screen_bgr())
            label.configure(image=black_photo[0])
            label.image = black_photo[0]
    elif scaled_display[0] is not None:
        if _PIGEON_EXT:
            shown = _compose_shown_frame(last_frame[0], brightness_current[0])
        else:
            shown = _apply_brightness(scaled_display[0], brightness_current[0])
        _update_label_photo_from_bgr(label, shown, label_live_photo)


def _apply_shell_size(w: int, h: int, *, SceneFit, _PIGEON_EXT, _app_logo_clock_saver_style_now, backdrop_app_logo_letterbox_fit, backdrop_master_bgr, black_photo, display_dims, fit_holder, scaled_display, scaled_version, skip_cache, sync_developer_chrome, use_backdrop_scene) -> None:
    if w < 32 or h < 32:
        return
    if display_dims[0] == w and display_dims[1] == h:
        return
    display_dims[0] = w
    display_dims[1] = h
    # Display geometry changed — re-resolve auto PAR next present.
    try:
        from pigeon.display_par import clear_auto_par_cache

        clear_auto_par_cache()
    except Exception:
        pass
    fit_holder[0] = SceneFit(target_w=w, target_h=h)
    black_photo[0] = None
    skip_cache[0] = None
    if use_backdrop_scene[0] and backdrop_master_bgr[0] is not None and not _PIGEON_EXT:
        from pigeon.image_ui_protocol import backdrop_scene_bgr_for_display

        scaled_display[0] = backdrop_scene_bgr_for_display(
            backdrop_master_bgr[0],
            w,
            h,
            app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit[0],
            app_logo_clock_saver_style=_app_logo_clock_saver_style_now(),
        )
        scaled_version[0] += 1
    sync_developer_chrome()


def _warm_playback_overlay_blits(*, _set_playback_overlay_clock_saver_volume_flag, _show_paused_row_overlay, _view_one_streaming_logo_duplicate_fallback, _warm_info_cluster_blits, playback_overlay_blits, playback_overlay_flags, playback_overlay_widget) -> None:
    if playback_overlay_widget is None:
        playback_overlay_blits[0] = []
    else:
        try:
            playback_overlay_flags["show_paused_row"] = _show_paused_row_overlay()
            playback_overlay_flags["badge_live_instead_of_logo"] = (
                _view_one_streaming_logo_duplicate_fallback()
            )
            _set_playback_overlay_clock_saver_volume_flag()
            playback_overlay_blits[0] = list(playback_overlay_widget.design_blits())
        except Exception as exc:
            print(f"[pigeon] playback overlay blit warmup failed: {exc}", flush=True)
            playback_overlay_blits[0] = []
    try:
        _warm_info_cluster_blits(time.monotonic())
    except Exception as exc:
        print(f"[pigeon] info cluster blit warmup failed: {exc}", flush=True)


def compose_display_fast_no_grid(
    frame_bgr: np.ndarray | None,
    brightness: float,
    *,
    frame_is_display_sized: bool = False,
    CLOCK_ANCHOR_COL, CLOCK_ANCHOR_ROW, DESIGN_H, DESIGN_W, DevPhase, DisplayView, PATCH_LAYER_RECEIVER_AUDIO, SceneFit, _PIGEON_EXT, _acquire_view1_canvas, _active_tmdb_logo_widget, _apply_auto_widget_policy, _apply_brightness, _backdrop_active_for_view, _blend_info_cluster_into_target, _blend_top_gradient_fast, _blit_saver_layers_design, _blit_saver_layers_target, _clock_saver_backdrop_brightness, _clock_saver_dim_overlay_bgra, _clock_saver_dim_pre_digit_canvas, _clock_saver_for_compose, _clock_saver_layer_opacity, _clock_saver_layers, _clock_startup_intro_opacity, _compose_paused_screen, _composite_cap_dims, _composite_settings_on_canvas, _design_rect_to_target, _disp_fit, _effective_display_view, _hitch_parts, _idle_audio_meter_active, _info_cluster_compose_active, _location_toast_alpha, _paused_screen_active, _playback_overlay_fast_sig, _present_frame_to_display, _refresh_clock_patch_bgra, _set_playback_overlay_clock_saver_volume_flag, _show_paused_row_overlay, _splash_reveal_clock, _sync_now_playing_screen_state_for_frame, _view_one_is_pigeon_poster, _view_one_uses_now_playing_screen, _view_one_video_content_a_tt_contain_rect_design, _vv_is_music, _warm_playback_overlay_blits, _warm_tmdb_logo_patch, active_tmdb_display_title, active_tmdb_title_key, alpha_blend_bgra_over_bgr, clock_patch_bgra, clock_saver_composite_bgra, clock_widget, dev_phase, display_dims, location_toast_patch_bgra, location_toast_state, main_settings_widget, playback_lower_gradient_bgra, playback_overlay_blits, playback_overlay_flags, playback_overlay_widget, startup_ph, status_bar_blits, status_bar_widget, tmdb_tt_gradient_bgr_holder, view_circles_widget,
) -> np.ndarray:
    """Video at display size + poster/clock blits (no full design canvas). Used when developer grid is off."""
    assert _PIGEON_EXT
    try:
        _apply_auto_widget_policy()
    except Exception:
        pass
    dw, dh = display_dims[0], display_dims[1]
    cap_w, cap_h, use_cap = _composite_cap_dims(dw, dh)
    if _paused_screen_active():
        base_pause = _compose_paused_screen(cap_w, cap_h)
        if use_cap:
            return _present_frame_to_display(base_pause, dw, dh)
        return base_pause
    # View 1: 070326 now-playing screen only (no classic chrome / TMDB backdrop stack).
    if _effective_display_view() == DisplayView.ONE:
        now_cs = time.monotonic()
        meter_v1 = _idle_audio_meter_active(now_cs)
        if not meter_v1:
            _set_playback_overlay_clock_saver_volume_flag()
            _warm_tmdb_logo_patch()
        canvas_np = _acquire_view1_canvas()
        intro_op = _clock_startup_intro_opacity(now_cs)
        cs_v1 = _clock_saver_for_compose(now_cs)
        np_live = (
            not meter_v1
            and intro_op is None
            and not (dev_phase[0] == DevPhase.MAIN_SETTINGS and main_settings_widget is not None)
            and not cs_v1
        )
        if not meter_v1 and not np_live:
            canvas_np[:] = (0, 0, 0)
        # Pre-reveal splash: black underlay. From the reveal frame: full UI under PNG alpha.
        if startup_ph[0] is not None and not _splash_reveal_clock[0]:
            pass
        elif intro_op is not None and clock_saver_composite_bgra is not None and alpha_blend_bgra_over_bgr is not None:
            acc_cs = (
                tuple(status_bar_widget.accent_bgr)
                if status_bar_widget is not None
                else None
            )
            (time_bgra, t_rect), (date_bgra, d_rect) = _clock_saver_layers(
                shadow_bgr=acc_cs,
                layer_opacity=float(intro_op),
                time_layer_opacity=float(intro_op),
                date_layer_opacity=float(intro_op),
                date_anchor_row=CLOCK_ANCHOR_ROW,
                date_anchor_col=CLOCK_ANCHOR_COL,
            )
            for cs_bgra, (sx, sy, sw, sh) in (
                (date_bgra, d_rect),
                (time_bgra, t_rect),
            ):
                roi2 = canvas_np[sy : sy + sh, sx : sx + sw]
                roi2[:] = alpha_blend_bgra_over_bgr(roi2, cs_bgra)
        elif dev_phase[0] == DevPhase.MAIN_SETTINGS and main_settings_widget is not None:
            _composite_settings_on_canvas(canvas_np)
        elif (
            cs_v1
            and clock_saver_composite_bgra is not None
            and alpha_blend_bgra_over_bgr is not None
        ):
            # Idle / position-stall saver replaces circles / now-playing chrome.
            acc_cs = (
                tuple(status_bar_widget.accent_bgr)
                if status_bar_widget is not None
                else None
            )
            _cs_dim_v1 = _clock_saver_layer_opacity(now_cs)
            _meter_face_v1 = meter_v1
            if not _meter_face_v1:
                _clock_saver_dim_pre_digit_canvas(canvas_np, _cs_dim_v1)
            (time_bgra, t_rect), (date_bgra, d_rect) = _clock_saver_layers(
                shadow_bgr=acc_cs,
                layer_opacity=_cs_dim_v1,
                time_layer_opacity=1.0,
                date_layer_opacity=_cs_dim_v1,
                date_anchor_row=CLOCK_ANCHOR_ROW,
                date_anchor_col=CLOCK_ANCHOR_COL,
                replace_with_meter=_meter_face_v1,
            )
            _blit_saver_layers_design(
                canvas_np,
                time_bgra,
                t_rect,
                date_bgra,
                d_rect,
                copy_full_bgr=_meter_face_v1,
            )
        else:
            t_sync0 = time.perf_counter()
            _sync_now_playing_screen_state_for_frame()
            t_sync1 = time.perf_counter()
            if view_circles_widget is not None:
                view_circles_widget.render(canvas_np)
            _hitch_parts[0] = (t_sync1 - t_sync0) * 1000.0
            _hitch_parts[1] = (time.perf_counter() - t_sync1) * 1000.0
        if (
            int(cap_w) == int(DESIGN_W)
            and int(cap_h) == int(DESIGN_H)
        ):
            base2 = canvas_np
        else:
            base2 = cv2.resize(
                canvas_np,
                (cap_w, cap_h),
                interpolation=cv_resize_interp(
                    int(DESIGN_W), int(DESIGN_H), cap_w, cap_h
                ),
            )
        if use_cap:
            return _present_frame_to_display(
                base2,
                dw,
                dh,
                native_now_playing=True,
            )
        return base2
    _set_playback_overlay_clock_saver_volume_flag()
    fast_sig = (
        bool(_backdrop_active_for_view()),
        _show_paused_row_overlay(),
        bool(playback_overlay_flags["clock_saver_volume_only"]),
        bool(playback_overlay_flags["clock_saver_netflix_full_overlay"]),
        bool(playback_overlay_flags.get("badge_live_instead_of_logo")),
    )
    if playback_overlay_widget is not None and _playback_overlay_fast_sig[0] != fast_sig:
        _playback_overlay_fast_sig[0] = fast_sig
        _warm_playback_overlay_blits()
    if frame_bgr is None or frame_bgr.size == 0:
        sb, sg, sr = get_stage_bgr()
        base = np.empty((cap_h, cap_w, 3), dtype=np.uint8)
        base[:] = (sb, sg, sr)
    else:
        lit = _apply_brightness(frame_bgr, brightness)
        if frame_is_display_sized:
            if use_cap and (
                int(lit.shape[1]) != cap_w or int(lit.shape[0]) != cap_h
            ):
                _lh, _lw = lit.shape[:2]
                base = cv2.resize(
                    lit,
                    (cap_w, cap_h),
                    interpolation=cv_resize_interp(_lw, _lh, cap_w, cap_h),
                )
            else:
                base = lit
        else:
            fit = SceneFit(target_w=cap_w, target_h=cap_h) if use_cap else _disp_fit()
            base = fit.scale_and_crop(lit)
    now_cs = time.monotonic()
    cs = _clock_saver_for_compose(now_cs)
    intro_op = _clock_startup_intro_opacity(now_cs)
    bdim = _clock_saver_backdrop_brightness(now_cs)
    if intro_op is not None:
        base[:] = 0
    elif bdim < 1.0 - 1e-6:
        base = (base.astype(np.float32) * bdim).astype(np.uint8)
    # Composite order: clock saver / small clock / overlays sit above
    # the bottom gradient.
    if intro_op is None:
        _blend_top_gradient_fast(base, cap_w, cap_h)
    if cs:
        if alpha_blend_bgra_over_bgr is not None:
            acc_cs = (
                tuple(status_bar_widget.accent_bgr)
                if status_bar_widget is not None
                else None
            )
            _cs_dim = _clock_saver_layer_opacity(now_cs)
            _meter_face = _idle_audio_meter_active(now_cs)
            if intro_op is None and not _meter_face:
                _clock_saver_dim_pre_digit_canvas(base, _cs_dim)
            _time_op = float(intro_op) if intro_op is not None else 1.0
            _date_op = float(intro_op) if intro_op is not None else _cs_dim
            (time_bgra, t_rect), (date_bgra, d_rect) = _clock_saver_layers(
                shadow_bgr=acc_cs,
                layer_opacity=_cs_dim,
                time_layer_opacity=_time_op,
                date_layer_opacity=_date_op,
                date_anchor_row=CLOCK_ANCHOR_ROW,
                date_anchor_col=CLOCK_ANCHOR_COL,
                replace_with_meter=_meter_face,
            )
            _blit_saver_layers_target(
                base,
                time_bgra,
                t_rect,
                date_bgra,
                d_rect,
                cap_w,
                cap_h,
                copy_full_bgr=_meter_face,
            )
            if (
                (
                    playback_overlay_flags.get("clock_saver_volume_only")
                    or playback_overlay_flags.get("clock_saver_netflix_full_overlay")
                )
                and playback_overlay_blits[0]
                and alpha_blend_bgra_over_bgr is not None
            ):
                for pb in playback_overlay_blits[0]:
                    x0, y0, ww, wh = int(pb.x), int(pb.y), int(pb.w), int(pb.h)
                    x, y, rw, rh = _design_rect_to_target(x0, y0, ww, wh, cap_w, cap_h)
                    _ph, _pw = pb.bgra.shape[:2]
                    patch = cv2.resize(
                        _clock_saver_dim_overlay_bgra(pb.bgra, _cs_dim),
                        (rw, rh),
                        interpolation=cv_resize_interp(_pw, _ph, rw, rh),
                    )
                    sub = base[y : y + rh, x : x + rw]
                    sub[:] = alpha_blend_bgra_over_bgr(sub, patch)
    else:
        if (
            playback_lower_gradient_bgra is not None
            and alpha_blend_bgra_over_bgr is not None
            and not _vv_is_music()
        ):
            gx, gy, gw, gh, grad_bgra = playback_lower_gradient_bgra(
                gradient_bgr=tmdb_tt_gradient_bgr_holder[0]
            )
            x, y, rw, rh = _design_rect_to_target(gx, gy, gw, gh, cap_w, cap_h)
            _gh, _gw = grad_bgra.shape[:2]
            patch = cv2.resize(
                grad_bgra, (rw, rh), interpolation=cv_resize_interp(_gw, _gh, rw, rh)
            )
            sub = base[y : y + rh, x : x + rw]
            sub[:] = alpha_blend_bgra_over_bgr(sub, patch)
        if _effective_display_view() != DisplayView.FOUR:
            if _info_cluster_compose_active(now_cs):
                _blend_info_cluster_into_target(base, cap_w, cap_h, now_cs)
            else:
                _refresh_clock_patch_bgra()
                if (
                    clock_patch_bgra[0] is not None
                    and clock_widget is not None
                    and alpha_blend_bgra_over_bgr is not None
                ):
                    dr = getattr(clock_widget, "design_rect", None)
                    wx, wy, ww, wh = dr() if callable(dr) else (0, 0, 0, 0)
                    if ww >= 1 and wh >= 1:
                        x, y, rw, rh = _design_rect_to_target(wx, wy, ww, wh, cap_w, cap_h)
                        _kh, _kw = clock_patch_bgra[0].shape[:2]
                        patch = cv2.resize(
                            clock_patch_bgra[0],
                            (rw, rh),
                            interpolation=cv_resize_interp(_kw, _kh, rw, rh),
                        )
                        sub = base[y : y + rh, x : x + rw]
                        sub[:] = alpha_blend_bgra_over_bgr(sub, patch)
        if status_bar_blits[0] and alpha_blend_bgra_over_bgr is not None:
            for sb in status_bar_blits[0]:
                x0, y0, ww, wh = int(sb.x), int(sb.y), int(sb.w), int(sb.h)
                x, y, rw, rh = _design_rect_to_target(x0, y0, ww, wh, cap_w, cap_h)
                _bh, _bw = sb.bgra.shape[:2]
                patch = cv2.resize(
                    sb.bgra,
                    (rw, rh),
                    interpolation=cv_resize_interp(_bw, _bh, rw, rh),
                )
                sub = base[y : y + rh, x : x + rw]
                sub[:] = alpha_blend_bgra_over_bgr(sub, patch)
        if playback_overlay_blits[0] and alpha_blend_bgra_over_bgr is not None:
            for pb in playback_overlay_blits[0]:
                if (
                    _info_cluster_compose_active(now_cs)
                    and getattr(pb, "layer", "") == PATCH_LAYER_RECEIVER_AUDIO
                ):
                    continue
                x0, y0, ww, wh = int(pb.x), int(pb.y), int(pb.w), int(pb.h)
                x, y, rw, rh = _design_rect_to_target(x0, y0, ww, wh, cap_w, cap_h)
                _ph, _pw = pb.bgra.shape[:2]
                patch = cv2.resize(
                    pb.bgra,
                    (rw, rh),
                    interpolation=cv_resize_interp(_pw, _ph, rw, rh),
                )
                sub = base[y : y + rh, x : x + rw]
                sub[:] = alpha_blend_bgra_over_bgr(sub, patch)
        if (
            dev_phase[0] == DevPhase.OFF
            and location_toast_patch_bgra is not None
            and alpha_blend_bgra_over_bgr is not None
            and (
                not _info_cluster_compose_active(now_cs)
                or bool(location_toast_state.get("startup_top_left"))
            )
        ):
            now_lt = time.monotonic()
            ta = _location_toast_alpha(now_lt)
            if ta > 1e-6:
                acc = (
                    tuple(status_bar_widget.accent_bgr)
                    if status_bar_widget is not None
                    else None
                )
                patch_lt, (lwx, lwy, lww, lwh) = location_toast_patch_bgra(
                    str(location_toast_state["text"]),
                    alpha=ta,
                    shadow_bgr=acc,
                    col_right_offset_cells=0.0,
                    row_offset_cells=0.0,
                    startup_top_left=bool(
                        location_toast_state.get("startup_top_left")
                    ),
                )
                if patch_lt is not None:
                    x, y, rw, rh = _design_rect_to_target(lwx, lwy, lww, lwh, cap_w, cap_h)
                    _th, _tw = patch_lt.shape[:2]
                    patch = cv2.resize(
                        patch_lt,
                        (rw, rh),
                        interpolation=cv_resize_interp(_tw, _th, rw, rh),
                    )
                    sub = base[y : y + rh, x : x + rw]
                    sub[:] = alpha_blend_bgra_over_bgr(sub, patch)
        if (
            _effective_display_view() not in (DisplayView.FOUR, DisplayView.TWO)
            and (_logo_w := _active_tmdb_logo_widget()) is not None
            and active_tmdb_title_key[0]
            and alpha_blend_bgra_over_bgr is not None
            and not _view_one_uses_now_playing_screen()
        ):
            if (
                _effective_display_view() == DisplayView.ONE
                and not _view_one_is_pigeon_poster()
            ):
                dwx, dwy, dww, dwh = _view_one_video_content_a_tt_contain_rect_design()
            else:
                dwx, dwy, dww, dwh = _logo_w.design_rect()
            x, y, rw, rh = _design_rect_to_target(dwx, dwy, dww, dwh, cap_w, cap_h)
            _logo_patch = _logo_w.bgra_patch_for_title(
                active_tmdb_title_key[0],
                display_title=active_tmdb_display_title[0],
                patch_wh=(int(dww), int(dwh)),
            )
            _ph, _pw = int(_logo_patch.shape[0]), int(_logo_patch.shape[1])
            if _pw >= 1 and _ph >= 1 and rw >= 1 and rh >= 1:
                _sc = min(rw / float(_pw), rh / float(_ph))
                _nw = max(1, int(round(_pw * _sc)))
                _nh = max(1, int(round(_ph * _sc)))
                patch = cv2.resize(
                    _logo_patch,
                    (_nw, _nh),
                    interpolation=cv_resize_interp(_pw, _ph, _nw, _nh),
                )
                _ox = x + (rw - _nw) // 2
                _oy = y + (rh - _nh) // 2
                _dx0 = max(0, _ox)
                _dy0 = max(0, _oy)
                _dx1 = min(cap_w, _ox + _nw)
                _dy1 = min(cap_h, _oy + _nh)
                if _dx1 > _dx0 and _dy1 > _dy0:
                    _sx0 = _dx0 - _ox
                    _sy0 = _dy0 - _oy
                    _cw = _dx1 - _dx0
                    _ch = _dy1 - _dy0
                    _crop = patch[_sy0 : _sy0 + _ch, _sx0 : _sx0 + _cw]
                    sub = base[_dy0:_dy1, _dx0:_dx1]
                    sub[:] = alpha_blend_bgra_over_bgr(sub, _crop)
    if use_cap:
        return _present_frame_to_display(base, dw, dh)
    return base


def f10_cycle_scene_grid(*, LANDING_DISPLAY_BRIGHTNESS, _bump_pigeon_user_activity, _open_landing_scene, _save_persisted_scene_enabled, apply_saved_tmdb_backdrop_to_display, backdrop_master_bgr, brightness_current, brightness_from, brightness_t0, brightness_target, last_frame, playing, render_once, saved_backdrop_master_bgr, scaled_display, scene_enabled, skip_cache, use_backdrop_scene) -> None:
    """
    Developer grid only: F10 cycles display on (landing) → off → backdrop (if saved) → landing.
    """

    _bump_pigeon_user_activity()
    landing_on = scene_enabled[0] and (not use_backdrop_scene[0]) and last_frame[0] is not None

    if use_backdrop_scene[0] and backdrop_master_bgr[0] is not None:
        if not _open_landing_scene():
            scene_enabled[0] = False
            _save_persisted_scene_enabled(False)
            skip_cache[0] = None
            render_once()
            return
        scene_enabled[0] = True
        playing[0] = False
        brightness_current[0] = brightness_from[0] = brightness_target[0] = LANDING_DISPLAY_BRIGHTNESS
        brightness_t0[0] = time.monotonic()
        _save_persisted_scene_enabled(True)
        skip_cache[0] = None
        render_once()
        return

    if landing_on:
        playing[0] = False
        scene_enabled[0] = False
        use_backdrop_scene[0] = False
        backdrop_master_bgr[0] = None
        last_frame[0] = None
        scaled_display[0] = None
        _save_persisted_scene_enabled(False)
        skip_cache[0] = None
        render_once()
        return

    if saved_backdrop_master_bgr[0] is not None:
        apply_saved_tmdb_backdrop_to_display()
        return

    if not _open_landing_scene():
        scene_enabled[0] = False
        _save_persisted_scene_enabled(False)
        skip_cache[0] = None
        render_once()
        return
    scene_enabled[0] = True
    _save_persisted_scene_enabled(True)
    skip_cache[0] = None
    render_once()


def render_once(*, BACKDROP_BRIGHTNESS, DevPhase, DisplayView, SKIP_POST_SPLASH_STARTUP_TRANSITION, STARTUP_AUTO_RESTORE_SAVED_BACKDROP, STARTUP_PIGEON_WORDMARK_MAX_S, THEATER_IDLE_DIM_ENABLED, _PIGEON_EXT, _apply_brightness, _atv_idle_monochrome_active, _audio_capture_wanted, _backdrop_active_for_view, _bgr_to_tk_image, _black_screen_bgr, _blend_tmdb_quality_flag_badge, _blend_tmdb_quality_toggle_overlay, _blend_view_four_debug, _capture_splash_underlay, _clock_saver_for_compose, _clock_saver_volume_raw, _clock_startup_intro_opacity, _compose_idle_strength_holder, _compose_shown_frame, _effective_display_view, _idle_audio_listen, _idle_audio_meter_active, _location_toast_alpha, _maybe_exit_settings_menus_on_idle, _np_drawing_live_audio, _np_wants_live_audio, _record_live_audio_timing, _render_after_id, _schedule_render_oneshot, _set_playback_overlay_clock_saver_volume_flag, _settings_audio_led_listen, _settings_menu_is_static, _show_paused_row_overlay, _startup_splash_complete, _tmdb_quality_toggle_overlay_state, _update_idle_dim_strength, _update_label_photo_from_bgr, _view_one_uses_now_playing_screen, _volume_lines, _warm_playback_overlay_blits, _warm_status_bar_blits, apply_saved_tmdb_backdrop_to_display, backdrop_master_bgr, black_photo, brightness_current, brightness_duration_s, brightness_from, brightness_t0, brightness_target, clock_saver_peek_until_mono, dev_phase, display_dims, display_view_holder, frame_interval_ms, label, label_live_photo, last_frame, latest_meter_cache_key, latest_visualizer_cache_key, lerp_bgr_red_monochrome, main_settings_widget, paused_interval_ms, playback_overlay_flags, playing, post_splash_mono, receiver_overlay_state, root, saved_backdrop_master_bgr, scaled_display, scaled_version, scene_enabled, skip_cache, status_bar_widget, sync_audio_meter_capture, tmdb_quality_error_flag, use_backdrop_scene, view_circles_widget, view_five_mode_holder, view_four_subview_holder, view_one_layout_holder) -> None:

    if _render_after_id[0] is not None:
        try:
            root.after_cancel(_render_after_id[0])
        except tk.TclError:
            pass
        _render_after_id[0] = None

    _render_tick_t0 = time.perf_counter()
    now = time.monotonic()
    _intro_mono = post_splash_mono[0]
    if sync_audio_meter_capture is not None:
        try:
            sync_audio_meter_capture(_audio_capture_wanted(now))
        except Exception:
            pass
    if _maybe_exit_settings_menus_on_idle(now):
        # Fall through to OFF-phase compose (now-playing or clock saver).
        pass

    def _schedule_next_render() -> None:
        elapsed_ms = int((time.perf_counter() - _render_tick_t0) * 1000.0)
        interval = _next_render_ms()
        if _PIGEON_EXT and (
            _idle_audio_meter_active()
            or _np_drawing_live_audio()
            or _np_wants_live_audio()
        ):
            # Aim at *interval* wall time, not compose-duration + interval.
            delay = _live_pace_delay_ms(_render_tick_t0, time.perf_counter(), interval)
        else:
            _LIVE_PACE[0] = None
            delay = max(interval, elapsed_ms + 1)
        _schedule_render_oneshot(delay)

    def _next_render_ms() -> int:
        # Settings must beat the video cadence. ATV "playing" used to keep
        # 12 Hz PhotoImage uploads running under the menus.
        live_audio = _PIGEON_EXT and (
            _idle_audio_meter_active()
            or _np_drawing_live_audio()
            or _np_wants_live_audio()
        )
        if (
            _settings_menu_is_static()
            and sys.platform.startswith("linux")
            and not live_audio
        ):
            if _settings_audio_led_listen():
                return 100
            return 500
        # Meter face needs a tight cadence even if ATV still reports playing.
        if _PIGEON_EXT and _idle_audio_meter_active():
            return 16
        if live_audio:
            return 33
        if _PIGEON_EXT and _idle_audio_listen():
            return 100
        if playing[0]:
            return frame_interval_ms[0]
        # Post-splash clock fade-up needs a smooth cadence.
        if _PIGEON_EXT and _clock_startup_intro_opacity(time.monotonic()) is not None:
            return 33
        # WiFi / box scan spinner: keep responsive without 60 FPS full-frame uploads on Pi.
        if (
            dev_phase[0] == DevPhase.MAIN_SETTINGS
            and main_settings_widget is not None
            and (
                main_settings_widget.state.wifi_scanning
                or main_settings_widget.state.wifi_connecting
                or main_settings_widget.state.box2_devices.scanning
                or main_settings_widget.state.box3_devices.scanning
                or main_settings_widget.state.location_switching
            )
        ):
            return 50 if sys.platform.startswith("linux") else 16
        # Circles loading shimmer while TMDb / artwork is in flight.
        if (
            _view_one_uses_now_playing_screen()
            and view_circles_widget is not None
            and view_circles_widget.searching
        ):
            return 33 if sys.platform.startswith("linux") else 16
        try:
            if _volume_lines.fading():
                return 50
        except Exception:
            pass
        if (
            _PIGEON_EXT
            and view_circles_widget is not None
            and _view_one_uses_now_playing_screen()
        ):
            try:
                if view_circles_widget.volume_takeover_active():
                    return 100
            except Exception:
                pass
        return paused_interval_ms

    # With ext + splash, only count this window **after** splash removal.
    _startup_elapsed = -1.0
    if _PIGEON_EXT:
        _startup_elapsed = (now - _intro_mono) if _intro_mono is not None else -1.0
    if (
        _PIGEON_EXT
        and not _startup_splash_complete[0]
        and _intro_mono is not None
        and (
            SKIP_POST_SPLASH_STARTUP_TRANSITION
            or _startup_elapsed >= STARTUP_PIGEON_WORDMARK_MAX_S
        )
    ):
        _startup_splash_complete[0] = True
        if (
            STARTUP_AUTO_RESTORE_SAVED_BACKDROP
            and saved_backdrop_master_bgr[0] is not None
            and scene_enabled[0]
            and not use_backdrop_scene[0]
        ):
            apply_saved_tmdb_backdrop_to_display()
            # Inner ``render_once`` schedules the loop, but guarantee a timer if that path returns early.
            _schedule_next_render()
            return
        skip_cache[0] = None
        _warm_playback_overlay_blits()

    if _PIGEON_EXT:
        _compose_idle_strength_holder[0] = _update_idle_dim_strength(now)
    else:
        _compose_idle_strength_holder[0] = 0.0
    t = (now - brightness_t0[0]) / brightness_duration_s[0] if brightness_duration_s[0] > 0 else 1.0
    if t <= 0.0:
        brightness_current[0] = brightness_from[0]
    elif t >= 1.0:
        brightness_current[0] = brightness_target[0]
    else:
        brightness_current[0] = brightness_from[0] + (brightness_target[0] - brightness_from[0]) * t

    if not scene_enabled[0]:
        if _PIGEON_EXT:
            settings_tok = (
                main_settings_widget.frame_cache_token()
                if (
                    dev_phase[0] == DevPhase.MAIN_SETTINGS
                    and main_settings_widget is not None
                )
                else ()
            )
            (
                _tmdb_x_bgr_off,
                _tmdb_x_alpha_off,
                _tmdb_x_caption_off,
                _tmdb_x_phase_off,
            ) = _tmdb_quality_toggle_overlay_state(now)
            tmdb_x_animating_off = _tmdb_x_alpha_off > 1e-6
            tmdb_flag_badge_on_off = bool(tmdb_quality_error_flag[0])
            tmdb_x_cache_key_off = (
                int(round(_tmdb_x_alpha_off * 1000.0))
                + (int(_tmdb_x_phase_off) * 2000)
                + (1 if tuple(_tmdb_x_bgr_off) == (0, 0, 255) else 0)
            )
            no_anim = True
            if (
                dev_phase[0] == DevPhase.MAIN_SETTINGS
                and main_settings_widget is not None
            ):
                st_ms = main_settings_widget.state
                no_anim = not (
                    st_ms.wifi_scanning
                    or st_ms.wifi_connecting
                    or st_ms.box2_devices.scanning
                    or st_ms.box3_devices.scanning
                    or st_ms.location_switching
                )
            if (
                no_anim
                and view_circles_widget is not None
                and view_circles_widget.searching
            ):
                no_anim = False
            if tmdb_x_animating_off or tmdb_flag_badge_on_off:
                no_anim = False
            # Must re-evaluate every second: circles clock digits + metadata-idle saver.
            # A static scene_off_key previously froze the UI after the first frame and
            # prevented the 2-minute clock saver from ever arming when scene was off.
            tick_key_off = (
                main_settings_widget.frame_cache_token()
                if (
                    dev_phase[0] == DevPhase.MAIN_SETTINGS
                    and main_settings_widget is not None
                )
                else int(time.time())
            )
            clock_saver_off = 1 if _clock_saver_for_compose(now) else 0
            meter_off_key = 0
            meter_active_off = _PIGEON_EXT and _idle_audio_meter_active(now)
            if meter_active_off and latest_meter_cache_key is not None:
                meter_off_key = int(latest_meter_cache_key())
            if clock_saver_off:
                if meter_active_off:
                    # Meter face has no second-hand clock; skip identical fills.
                    no_anim = True
                    tick_key_off = 0
                else:
                    # Digital clock needs ~1 Hz. Forcing no_anim=False plus a
                    # 1 ms catch-up delay spun the saver at full CPU.
                    no_anim = True
                    tick_key_off = int(time.time())
            live_audio_off = False
            if (
                not meter_active_off
                and not clock_saver_off
                and latest_visualizer_cache_key is not None
                and (
                    _np_drawing_live_audio()
                    or _np_wants_live_audio()
                )
            ):
                # NP keeps scene off; wall-clock tick_key_off was 1 Hz.
                live_audio_off = True
                meter_off_key = int(latest_visualizer_cache_key())
                tick_key_off = 0
            _np_vol_sig = ""
            if view_circles_widget is not None:
                try:
                    _np_vol_sig = (
                        f"{view_circles_widget._state.volume!s}\x1f"
                        f"{round(float(view_circles_widget._state.volume_fraction), 4)}\x1f"
                        f"{int(view_circles_widget.volume_takeover_active())}"
                    )
                except Exception:
                    _np_vol_sig = ""
            scene_off_key = (
                int(dev_phase[0]),
                settings_tok,
                display_dims[0],
                display_dims[1],
                bool(
                    view_circles_widget is not None
                    and view_circles_widget.searching
                ),
                tmdb_x_cache_key_off,
                1 if tmdb_flag_badge_on_off else 0,
                tick_key_off,
                clock_saver_off,
                meter_off_key,
                int(display_view_holder[0]),
                _np_vol_sig,
            )
            if no_anim and skip_cache[0] == scene_off_key:
                _schedule_next_render()
                return
            t_compose0 = time.perf_counter()
            out_bgr = _compose_shown_frame(None, 1.0)
            out_bgr = _blend_view_four_debug(out_bgr)
            sm_off = 0.0
            if lerp_bgr_red_monochrome is not None:
                sm_off = max(0.0, min(1.0, _compose_idle_strength_holder[0]))
                if (
                    sm_off > 1e-6
                    and not meter_active_off
                    and _effective_display_view() != DisplayView.FOUR
                ):
                    out_bgr = lerp_bgr_red_monochrome(out_bgr, sm_off)
            if tmdb_x_animating_off:
                _blend_tmdb_quality_toggle_overlay(
                    out_bgr,
                    color_bgr=_tmdb_x_bgr_off,
                    alpha=_tmdb_x_alpha_off,
                    caption=_tmdb_x_caption_off,
                )
            if tmdb_flag_badge_on_off:
                _blend_tmdb_quality_flag_badge(out_bgr)
            t_compose1 = time.perf_counter()
            _update_label_photo_from_bgr(label, out_bgr, label_live_photo)
            t_compose2 = time.perf_counter()
            if meter_active_off or live_audio_off:
                _record_live_audio_timing(t_compose0, t_compose1, t_compose2)
            skip_cache[0] = scene_off_key
        else:
            if black_photo[0] is None:
                black_photo[0] = _bgr_to_tk_image(_black_screen_bgr())
            label.configure(image=black_photo[0])
            label.image = black_photo[0]
        if _PIGEON_EXT and not meter_active_off:
            try:
                _capture_splash_underlay(out_bgr)
            except NameError:
                pass
            except Exception:
                pass
        _schedule_next_render()
        return

    if _backdrop_active_for_view():
        if backdrop_master_bgr[0] is None:
            use_backdrop_scene[0] = False
    if not _backdrop_active_for_view():
        _static_compose_without_video = (
            _PIGEON_EXT
            and (
                (
                    view_circles_widget is not None
                    and _effective_display_view() == DisplayView.ONE
                )
                or not scene_enabled[0]
                or _effective_display_view() in (
                    DisplayView.TWO,
                    DisplayView.THREE,
                    DisplayView.FOUR,
                    DisplayView.FIVE,
                    DisplayView.SIX,
                )
            )
        )
        if last_frame[0] is None and not _static_compose_without_video:
            _schedule_next_render()
            return
        if not _PIGEON_EXT and scaled_display[0] is None:
            _schedule_next_render()
            return

    brightness_animating = abs(brightness_current[0] - brightness_target[0]) > 1e-4
    # TMDb backdrop: fixed level; paused video uses 0.3.
    _backdrop_active = _backdrop_active_for_view()
    b_scene = BACKDROP_BRIGHTNESS if _backdrop_active else brightness_current[0]
    b_key = round(float(b_scene), 4)
    # Clock text changes every second; include wall time when widgets are active.
    # Main settings has no clock — use its frame token so static UI can skip uploads.
    if (
        _PIGEON_EXT
        and dev_phase[0] == DevPhase.MAIN_SETTINGS
        and main_settings_widget is not None
    ):
        tick_key = main_settings_widget.frame_cache_token()
    elif _PIGEON_EXT and _idle_audio_meter_active(now):
        tick_key = 0
    elif _PIGEON_EXT and _idle_audio_listen(now):
        tick_key = int(now * 5)
    else:
        tick_key = int(time.time()) if _PIGEON_EXT else 0
    idle_s_here = (
        max(0.0, min(1.0, _compose_idle_strength_holder[0])) if _PIGEON_EXT else 0.0
    )
    idle_want_here = (
        (1.0 if _atv_idle_monochrome_active() else 0.0)
        if THEATER_IDLE_DIM_ENABLED
        else 0.0
    )
    # While easing toward dim or back to full bright, always composite (skip-cache can quantize away steps).
    idle_dim_animating = _PIGEON_EXT and abs(idle_s_here - idle_want_here) > 1e-4
    idle_cache_key = int(round(idle_s_here * 500)) if _PIGEON_EXT else 0
    ta_toast = _location_toast_alpha(now) if _PIGEON_EXT else 0.0
    location_toast_animating = _PIGEON_EXT and 0.0 < ta_toast < 1.0
    location_toast_cache_key = int(round(ta_toast * 1000)) if _PIGEON_EXT else 0
    clock_saver_cache_key = 1 if (_PIGEON_EXT and _clock_saver_for_compose(now)) else 0
    clock_intro_op = _clock_startup_intro_opacity(now) if _PIGEON_EXT else None
    clock_intro_cache_key = (
        int(round(float(clock_intro_op) * 1000.0)) if clock_intro_op is not None else -1
    )
    clock_intro_animating = clock_intro_op is not None
    clock_saver_peek_cache_key = (
        1 if (_PIGEON_EXT and now < clock_saver_peek_until_mono[0]) else 0
    )
    startup_wm_cache_key = 0
    paused_row_cache_key = 1 if (_PIGEON_EXT and _show_paused_row_overlay()) else 0
    mic_viz_cache_key = 0
    meter_face_active = False
    live_audio_widgets = False
    if _PIGEON_EXT and _idle_audio_meter_active(now) and latest_meter_cache_key is not None:
        mic_viz_cache_key = int(latest_meter_cache_key())
        meter_face_active = True
    elif _PIGEON_EXT and latest_visualizer_cache_key is not None and (
        _np_drawing_live_audio()
        or _np_wants_live_audio()
    ):
        mic_viz_cache_key = int(latest_visualizer_cache_key())
        live_audio_widgets = True
    meter_skip_ok = (
        (not playing[0] or _settings_menu_is_static())
        or meter_face_active
        or live_audio_widgets
    )
    if _PIGEON_EXT and status_bar_widget is not None:
        if status_bar_widget.set_theater_dim_suppressed(idle_s_here >= 0.5):
            _warm_status_bar_blits()
    theater_dim_key = (
        1
        if (
            _PIGEON_EXT
            and status_bar_widget is not None
            and status_bar_widget.theater_dim_suppressed
        )
        else 0
    )
    # Receiver overlay text must bust skip-cache when paused/backdrop.
    receiver_overlay_skip_sig = ""
    if _PIGEON_EXT:
        _set_playback_overlay_clock_saver_volume_flag()
        receiver_overlay_skip_sig = "\x1e".join(
            str(receiver_overlay_state.get(k, ""))
            for k in ("incoming", "config", "volume", "input")
        )
        _vol_line_key = 0
        try:
            _vol_line_key = int(round(float(_volume_lines.opacity()) * 20.0))
        except Exception:
            _vol_line_key = 0
        receiver_overlay_skip_sig += "\x1e" + (
            f"{int(bool(playback_overlay_flags.get('clock_saver_volume_only')))}"
            f"{int(bool(playback_overlay_flags.get('clock_saver_netflix_full_overlay')))}"
            f"{int(bool(playback_overlay_flags.get('badge_live_instead_of_logo')))}"
            f"\x1e{_clock_saver_volume_raw()}"
            f"\x1e{_vol_line_key}"
        )
    (_tmdb_x_bgr, _tmdb_x_alpha, _tmdb_x_caption, _tmdb_x_phase) = _tmdb_quality_toggle_overlay_state(now)
    tmdb_x_animating = _tmdb_x_alpha > 1e-6
    tmdb_x_cache_key = (
        int(round(_tmdb_x_alpha * 1000.0))
        + (int(_tmdb_x_phase) * 2000)
        + (1 if tuple(_tmdb_x_bgr) == (0, 0, 255) else 0)
    )
    tmdb_flag_badge_on = bool(tmdb_quality_error_flag[0])
    tmdb_flag_badge_cache_key = 1 if tmdb_flag_badge_on else 0

    if (
        meter_skip_ok
        and not brightness_animating
        and not idle_dim_animating
        and not location_toast_animating
        and not tmdb_x_animating
        and not clock_intro_animating
        and skip_cache[0]
        == (
            scaled_version[0],
            b_key,
            int(dev_phase[0]),
            int(display_view_holder[0]),
            int(_effective_display_view()),
            int(view_five_mode_holder[0]),
            int(view_one_layout_holder[0]),
            int(view_four_subview_holder[0]),
            tick_key,
            display_dims[0],
            display_dims[1],
            1 if _backdrop_active else 0,
            idle_cache_key,
            location_toast_cache_key,
            clock_saver_cache_key,
            clock_saver_peek_cache_key,
            startup_wm_cache_key,
            paused_row_cache_key,
            receiver_overlay_skip_sig,
            theater_dim_key,
            mic_viz_cache_key,
            tmdb_x_cache_key,
            tmdb_flag_badge_cache_key,
            clock_intro_cache_key,
        )
    ):
        _schedule_next_render()
        return

    t_compose0 = time.perf_counter()
    if _PIGEON_EXT:
        shown = _compose_shown_frame(
            last_frame[0] if not _backdrop_active else None, b_scene
        )
        shown = _blend_view_four_debug(shown)
        if (
            lerp_bgr_red_monochrome is not None
            and _effective_display_view() != DisplayView.FOUR
            and not meter_face_active
        ):
            sm = max(0.0, min(1.0, _compose_idle_strength_holder[0]))
            if sm > 1e-6:
                shown = lerp_bgr_red_monochrome(shown, sm)
    else:
        shown = _apply_brightness(scaled_display[0], b_scene)
    if tmdb_x_animating:
        _blend_tmdb_quality_toggle_overlay(
            shown,
            color_bgr=_tmdb_x_bgr,
            alpha=_tmdb_x_alpha,
            caption=_tmdb_x_caption,
        )
    if tmdb_flag_badge_on:
        _blend_tmdb_quality_flag_badge(shown)
    t_compose1 = time.perf_counter()
    _update_label_photo_from_bgr(label, shown, label_live_photo)
    t_compose2 = time.perf_counter()
    if _PIGEON_EXT and (meter_face_active or live_audio_widgets):
        _record_live_audio_timing(t_compose0, t_compose1, t_compose2)
    if _PIGEON_EXT and not meter_face_active:
        try:
            _capture_splash_underlay(shown)
        except NameError:
            pass
        except Exception:
            pass

    if (
        meter_skip_ok
        and not brightness_animating
        and not idle_dim_animating
        and not location_toast_animating
        and not tmdb_x_animating
        and not clock_intro_animating
    ):
        skip_cache[0] = (
            scaled_version[0],
            b_key,
            int(dev_phase[0]),
            int(display_view_holder[0]),
            int(_effective_display_view()),
            int(view_five_mode_holder[0]),
            int(view_one_layout_holder[0]),
            int(view_four_subview_holder[0]),
            tick_key,
            display_dims[0],
            display_dims[1],
            1 if _backdrop_active else 0,
            idle_cache_key,
            location_toast_cache_key,
            clock_saver_cache_key,
            clock_saver_peek_cache_key,
            startup_wm_cache_key,
            paused_row_cache_key,
            receiver_overlay_skip_sig,
            theater_dim_key,
            mic_viz_cache_key,
            tmdb_x_cache_key,
            tmdb_flag_badge_cache_key,
            clock_intro_cache_key,
        )
    else:
        skip_cache[0] = None

    _schedule_next_render()


def _apply_netflix_backdrop_when_running(*, BACKDROP_BRIGHTNESS, _backdrop_master_from_streaming_app_logo, _playback_is_netflix_stream, _save_persisted_scene_enabled, _warm_status_bar_blits, _warm_tmdb_logo_patch, active_tmdb_display_title, active_tmdb_title_key, backdrop_app_logo_letterbox_fit, backdrop_master_bgr, brightness_current, brightness_from, brightness_t0, brightness_target, cap, current_apple_tv, last_frame, playing, saved_backdrop_app_logo_letterbox_fit, saved_backdrop_master_bgr, scaled_display, scaled_version, scene_enabled, skip_cache, status_bar_widget, streaming_badge_state, tmdb_logo_app_fallback_active, tmdb_logo_patch_bgra, tmdb_logo_widget, tmdb_logo_widget_view_six, use_backdrop_scene) -> bool:
    """Netflix foreground: letterbox Netflix logo as backdrop (swap if scene exists, else open scene)."""
    if not _playback_is_netflix_stream():
        return False
    logo_bd = _backdrop_master_from_streaming_app_logo()
    if logo_bd is None:
        return False

    fn_sb = str(streaming_badge_state.get("filename") or "").lower()
    if use_backdrop_scene[0] and backdrop_master_bgr[0] is not None:
        if backdrop_app_logo_letterbox_fit[0] and "netflix" in fn_sb:
            return False
        backdrop_master_bgr[0] = logo_bd
        saved_backdrop_master_bgr[0] = np.asarray(logo_bd, dtype=np.uint8).copy()
        saved_backdrop_app_logo_letterbox_fit[0] = True
        backdrop_app_logo_letterbox_fit[0] = True
        scaled_display[0] = None
        scaled_version[0] += 1
        skip_cache[0] = None
        if status_bar_widget is not None:
            bd_arr = np.asarray(logo_bd, dtype=np.uint8)
            if status_bar_widget.set_accent_from_backdrop_bgr(bd_arr):
                _warm_status_bar_blits()
                skip_cache[0] = None
        return True

    if not scene_enabled[0]:
        return False
    if not str(current_apple_tv.get("identifier") or "").strip():
        return False

    active_tmdb_title_key[0] = None
    active_tmdb_display_title[0] = None
    tmdb_logo_app_fallback_active[0] = False
    if tmdb_logo_widget is not None:
        tmdb_logo_widget.clear_cache()
    if tmdb_logo_widget_view_six is not None:
        tmdb_logo_widget_view_six.clear_cache()
    _warm_tmdb_logo_patch()
    tmdb_logo_patch_bgra[0] = None
    if cap[0] is not None:
        try:
            cap[0].release()
        except Exception:
            pass
        cap[0] = None
    backdrop_master_bgr[0] = logo_bd
    saved_backdrop_master_bgr[0] = np.asarray(logo_bd, dtype=np.uint8).copy()
    saved_backdrop_app_logo_letterbox_fit[0] = True
    backdrop_app_logo_letterbox_fit[0] = True
    use_backdrop_scene[0] = True
    scene_enabled[0] = True
    playing[0] = False
    last_frame[0] = None
    scaled_display[0] = None
    scaled_version[0] += 1
    _save_persisted_scene_enabled(True)
    brightness_current[0] = brightness_from[0] = brightness_target[0] = BACKDROP_BRIGHTNESS
    brightness_t0[0] = time.monotonic()
    skip_cache[0] = None
    if status_bar_widget is not None:
        bd_arr = np.asarray(logo_bd, dtype=np.uint8)
        if status_bar_widget.set_accent_from_backdrop_bgr(bd_arr):
            _warm_status_bar_blits()
            skip_cache[0] = None
    return True
