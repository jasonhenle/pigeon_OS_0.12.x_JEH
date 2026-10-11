"""View 1 layout and variant selection, streaming-app logo backdrops, and the View 1 canvas.

Extracted verbatim from ``bootstrap()`` in ``pigeon_0_12.py``. Each function
takes the app state it used to close over as keyword-only arguments;
``bootstrap()`` binds them once with ``bind_deps`` so call sites are unchanged.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import sys
import time


def _capture_last_view_one_layout_from_live_view(*, DisplayView, display_view_holder, last_view_one_layout_snapshot, view_one_layout_holder) -> None:
    if display_view_holder[0] == DisplayView.ONE:
        last_view_one_layout_snapshot[0] = int(view_one_layout_holder[0])


def _view_one_is_pigeon_full(*, ViewOneLayout, _stage_is_view_one_video_layout, _view_one_layout_effective) -> bool:
    if not _stage_is_view_one_video_layout():
        return False
    return int(_view_one_layout_effective()) == int(ViewOneLayout.PIGEON_FULL)


def _view_one_is_pigeon_simple(*, ViewOneLayout, _stage_is_view_one_video_layout, _view_one_layout_effective) -> bool:
    if not _stage_is_view_one_video_layout():
        return False
    return int(_view_one_layout_effective()) == int(ViewOneLayout.PIGEON_SIMPLE)


def _view_one_is_pigeon_poster(*, ViewOneLayout, _stage_is_view_one_video_layout, _view_one_layout_effective) -> bool:
    if not _stage_is_view_one_video_layout():
        return False
    return int(_view_one_layout_effective()) == int(ViewOneLayout.PIGEON_POSTER)


def _log_view_one_startup_phase(phase: str, *, _app_startup_mono) -> None:
    try:
        dt = time.monotonic() - _app_startup_mono
        sys.stderr.write(f"pigeon: view1 {phase} +{dt:.3f}s\n")
        sys.stderr.flush()
    except Exception:
        pass


def _backdrop_master_from_streaming_app_logo(*, APP_LOGO_FALLBACK_MAX_RESOLUTION_FRACTION, _PROJECT_DIR, _metadata_is_netflix_app, apple_tv_auto_state, display_dims, streaming_badge_state) -> np.ndarray | None:
    """Letterbox streaming app logo on black; resolves path from metadata when badge file unset."""
    assets_root = Path(_PROJECT_DIR) / "pigeonAssets"
    fn = str(streaming_badge_state.get("filename") or "").strip()
    if not fn:
        lm = apple_tv_auto_state.get("last_metadata")
        if isinstance(lm, dict) and _metadata_is_netflix_app(lm):
            from pigeon.streaming_service_badges import resolve_streaming_badge_media

            fn2, _lbl = resolve_streaming_badge_media(
                assets_root,
                app_name=str(lm.get("app_name") or ""),
                app_id=str(lm.get("app_id") or ""),
            )
            fn = (fn2 or "").strip()
    if not fn:
        return None
    p = assets_root / fn
    if not p.is_file():
        return None
    try:
        from pigeon.image_ui_protocol import (
            app_logo_fallback_master_bgr,
            bgra_to_bgr_on_black,
            load_image_bgra,
        )

        bgra = load_image_bgra(p)
        if bgra is None or bgra.size == 0:
            return None
        bgr = bgra_to_bgr_on_black(bgra)
        return app_logo_fallback_master_bgr(
            bgr,
            display_w=int(display_dims[0]),
            display_h=int(display_dims[1]),
            fraction=float(APP_LOGO_FALLBACK_MAX_RESOLUTION_FRACTION),
        )
    except Exception:
        return None


def _active_tmdb_logo_widget(*, DisplayView, _effective_display_view, tmdb_logo_widget, tmdb_logo_widget_view_six):
    if _effective_display_view() == DisplayView.SIX and tmdb_logo_widget_view_six is not None:
        return tmdb_logo_widget_view_six
    return tmdb_logo_widget


def _resolve_streaming_app_logo_bgra(*, _PROJECT_DIR, apple_tv_auto_state, streaming_badge_state) -> np.ndarray | None:
    """Resolve the streaming-service badge source BGRA (same filename resolution as the
    app-logo backdrop fallback). Returns ``None`` when no usable image is available."""
    assets_root = Path(_PROJECT_DIR) / "pigeonAssets"
    fn = str(streaming_badge_state.get("filename") or "").strip()
    if not fn:
        lm = apple_tv_auto_state.get("last_metadata")
        if isinstance(lm, dict):
            try:
                from pigeon.streaming_service_badges import (
                    resolve_streaming_badge_media,
                )

                fn2, _lbl = resolve_streaming_badge_media(
                    assets_root,
                    app_name=str(lm.get("app_name") or ""),
                    app_id=str(lm.get("app_id") or ""),
                )
                fn = (fn2 or "").strip()
            except Exception:
                fn = ""
    if not fn:
        return None
    p = assets_root / fn
    if not p.is_file():
        return None
    try:
        from pigeon.image_ui_protocol import load_image_bgra

        bgra = load_image_bgra(p)
    except Exception:
        return None
    if bgra is None or bgra.size == 0:
        return None
    return bgra


def _current_view_one_variant(*, ViewOneLayout, _view_one_layout_effective, _vv_has_app_logo, _vv_has_content_title, _vv_has_current_app, _vv_has_tmdb_bd, _vv_has_tmdb_tt, resolve_view_one_variant):
    if resolve_view_one_variant is None:
        return None
    return resolve_view_one_variant(
        layout_is_simple=(
            int(_view_one_layout_effective()) == int(ViewOneLayout.PIGEON_SIMPLE)
        ),
        has_title_meta=_vv_has_content_title(),
        has_app_meta=_vv_has_current_app(),
        has_tmdb_bd=_vv_has_tmdb_bd(),
        has_tmdb_tt=_vv_has_tmdb_tt(),
        has_app_logo=_vv_has_app_logo(),
    )


def _view_one_streaming_logo_duplicate_fallback(*, ViewOneVariant, _current_view_one_variant) -> bool:
    """viewOne.07: no TMDb title; streaming app logo occupies pigeonTMDB_TT (badge would duplicate it)."""
    if ViewOneVariant is None:
        return False
    return _current_view_one_variant() == ViewOneVariant.V07


def _view_one_variant_uses_full_path(*, _current_view_one_variant, _view_one_is_pigeon_full, _view_one_is_pigeon_poster, variant_uses_full_path) -> bool:
    if _view_one_is_pigeon_poster():
        return False
    v = _current_view_one_variant()
    if v is None or variant_uses_full_path is None:
        return _view_one_is_pigeon_full()
    return variant_uses_full_path(v)


def _view_one_variant_uses_simple_path(*, _current_view_one_variant, _stage_is_view_one_video_layout, _view_one_is_pigeon_poster, _view_one_is_pigeon_simple, variant_uses_full_path) -> bool:
    if _view_one_is_pigeon_poster():
        return False
    v = _current_view_one_variant()
    if v is None or variant_uses_full_path is None:
        return _view_one_is_pigeon_simple()
    return _stage_is_view_one_video_layout() and not variant_uses_full_path(v)


def _acquire_view1_canvas(*, DESIGN_H, DESIGN_W, _view1_canvas_bgr) -> np.ndarray:
    h, w = int(DESIGN_H), int(DESIGN_W)
    c = _view1_canvas_bgr[0]
    if c is None or int(c.shape[0]) != h or int(c.shape[1]) != w:
        c = np.zeros((h, w, 3), dtype=np.uint8)
        _view1_canvas_bgr[0] = c
    return c


def _view_one_uses_now_playing_screen(*, DisplayView, _effective_display_view, view_circles_widget) -> bool:
    return (
        _effective_display_view() == DisplayView.ONE
        and view_circles_widget is not None
    )


def _view_one_video_content_a_tt_contain_rect_design(*, DESIGN_H, DESIGN_W, PATCH_LAYER_RECEIVER_AUDIO, VIEW_ONE_BADGE_COL_RIGHT, get_grid_geometry, playback_lower_gradient_bgra, playback_overlay_widget, rect_for_span_at_cell, rect_for_span_top_right_at_cell, tmdb_tt_gradient_bgr_holder) -> tuple[int, int, int, int]:
    """Design-pixel (x, y, w, h) for pigeonTMDB_TT uniform contain-fit on viewOne.videoContent_a.

    Horizontally the slot is **10 design cells wide**, centered on column **7.5**
    (≈ columns 2.5–12.5): uniform-contain–fit, as large as that band and vertical clearance
    allow. Vertically it clears the streaming badge, receiver-driven overlay lines, and the
    gradient / status region (with a slightly lower floor and tighter gap to the gradient).
    """
    if (
        get_grid_geometry is None
        or rect_for_span_top_right_at_cell is None
        or rect_for_span_at_cell is None
    ):
        return (0, 0, max(1, int(DESIGN_W)), max(1, int(DESIGN_H)))
    g = get_grid_geometry()
    pad = max(4, int(round(0.12 * float(g.cell))))

    bx, by, bw, bh = rect_for_span_top_right_at_cell(
        2,
        1,
        row_1based=0.5,
        col_right_1based=float(VIEW_ONE_BADGE_COL_RIGHT),
    )

    top_min = int(by) + int(bh) + pad
    top_min = max(
        top_min,
        int(round(float(g.y0) + (3.0 - 1.0) * float(g.cell))),
    )
    if playback_overlay_widget is not None:
        try:
            for _p in playback_overlay_widget.design_blits():
                if getattr(_p, "layer", "") != PATCH_LAYER_RECEIVER_AUDIO:
                    continue
                py1 = int(_p.y) + int(_p.h) + pad
                if py1 > top_min:
                    top_min = min(py1, int(DESIGN_H) - 8)
        except Exception:
            pass

    # Allow the title treatment to use more vertical band (still below TRT / status row).
    bottom_max = int(round(float(g.y0) + (7.45 - 1.0) * float(g.cell)))
    try:
        if playback_lower_gradient_bgra is not None:
            _gx, gy, _gw, _gh, _grad = playback_lower_gradient_bgra(
                gradient_bgr=tmdb_tt_gradient_bgr_holder[0]
            )
            # Tighter than ``pad`` so the logo can sit closer to the gradient top edge.
            _grad_pad = max(2, int(round(0.04 * float(g.cell))))
            bottom_max = min(bottom_max, int(gy) - _grad_pad)
    except Exception:
        pass
    bottom_max = max(top_min + 8, min(int(DESIGN_H) - pad, bottom_max))

    # Columns 2.5–12.5 (10 cells wide, centered on the former 3–12 band): wider slot → larger TT.
    _tt_span_w = 10.0
    _tt_col_center = 7.5
    gx_tt, _gy_tt, gw_tt, _gh_tt = rect_for_span_at_cell(
        float(_tt_span_w),
        1.0,
        row_1based=1.0,
        col_1based=float(_tt_col_center) - 0.5 * float(_tt_span_w),
    )
    x0 = int(gx_tt)
    x1 = int(gx_tt) + int(gw_tt)
    y0 = max(0, top_min)
    y1 = bottom_max
    rw = int(x1 - x0)
    rh = int(y1 - y0)
    if rw < 48 or rh < 48 or x1 <= x0:
        _legacy = rect_for_span_top_right_at_cell(
            14, 4, row_1based=2, col_right_1based=17.5
        )
        _rt = int(round(float(g.y0) + (2.5 - 1.0) * float(g.cell)))
        _rb = int(round(float(g.y0) + (6.0 - 1.0) * float(g.cell)))
        _rh = max(1, _rb - _rt)
        return (
            int(_legacy[0]),
            int(_rt),
            int(_legacy[2]),
            int(_rh),
        )
    return (x0, y0, rw, rh)


def _view_one_layout_effective(*, DevPhase, DisplayView, _PIGEON_EXT, dev_phase, display_view_holder, last_view_one_layout_snapshot, view_one_layout_holder) -> int:
    if _PIGEON_EXT and (
        dev_phase[0] == DevPhase.GRID or display_view_holder[0] == DisplayView.FIVE
    ):
        return int(last_view_one_layout_snapshot[0])
    return int(view_one_layout_holder[0])


def _stage_is_view_one_video_layout(*, DevPhase, DisplayView, _PIGEON_EXT, dev_phase, display_view_holder) -> bool:
    if not _PIGEON_EXT:
        return False
    if dev_phase[0] == DevPhase.GRID or display_view_holder[0] == DisplayView.FIVE:
        return True
    return display_view_holder[0] == DisplayView.ONE
