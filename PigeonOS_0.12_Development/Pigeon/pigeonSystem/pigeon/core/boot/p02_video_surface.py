"""Boot phase: the video area and label, and the splash-to-label clock handoff.

Phase 2 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from PIL import ImageTk
from pigeon.core import startup as _core_startup
from pigeon.core.binding import bind_deps as _bind_deps
import numpy as np
import tkinter as tk


def run(ctx) -> None:
    WINDOW_H = ctx.WINDOW_H
    WINDOW_W = ctx.WINDOW_W
    _apply_clock_to_bridge_label = ctx._apply_clock_to_bridge_label
    _bgr_to_tk_image = ctx._bgr_to_tk_image
    _boot_clock_host = ctx._boot_clock_host
    _boot_clock_photo = ctx._boot_clock_photo
    _reveal_clock_under_splash = ctx._reveal_clock_under_splash
    _splash_clock_ready_bgr = ctx._splash_clock_ready_bgr
    _splash_on_reveal_paint = ctx._splash_on_reveal_paint
    _splash_reveal_clock = ctx._splash_reveal_clock
    _splash_underlay_bgr = ctx._splash_underlay_bgr
    content_host = ctx.content_host
    root = ctx.root

    # Full-size video area (always WINDOW_H) so scene scale matches non-overlay mode.
    # Paint the clock onto the new label BEFORE destroying the splash bridge — otherwise
    # the screen flashes black between bridge teardown and the first composite.
    video_area = tk.Frame(content_host, bg="#000", cursor="none")
    label = tk.Label(video_area, bd=0, highlightthickness=0, takefocus=True, bg="#000", cursor="none")
    _startup_label_black_photo: list[ImageTk.PhotoImage | None] = [None]
    _early_clock_underlay_photo: list[ImageTk.PhotoImage | None] = [None]
    ready_clock = _splash_clock_ready_bgr[0]
    if ready_clock is not None:
        _splash_underlay_bgr[0] = ready_clock
        _apply_clock_to_bridge_label(ready_clock)
    _handoff_clock = _boot_clock_photo[0]
    if _handoff_clock is None and _splash_underlay_bgr[0] is not None:
        try:
            _handoff_clock = _bgr_to_tk_image(_splash_underlay_bgr[0])
            _boot_clock_photo[0] = _handoff_clock
        except Exception:
            _handoff_clock = None
    if _handoff_clock is not None:
        try:
            label.configure(image=_handoff_clock)
            label.image = _handoff_clock
            _early_clock_underlay_photo[0] = _handoff_clock
        except Exception:
            _handoff_clock = None
    if _handoff_clock is None:
        try:
            _bb = np.zeros((WINDOW_H, WINDOW_W, 3), dtype=np.uint8)
            _startup_label_black_photo[0] = _bgr_to_tk_image(_bb)
            label.configure(image=_startup_label_black_photo[0])
            label.image = _startup_label_black_photo[0]
        except Exception:
            pass
    video_area.pack(fill=tk.BOTH, expand=True)
    label.pack(fill=tk.BOTH, expand=True)
    try:
        root.update_idletasks()
    except tk.TclError:
        pass
    # Bridge can go away only after the real label already shows the clock.
    try:
        if _boot_clock_host.winfo_exists():
            _boot_clock_host.destroy()
    except tk.TclError:
        pass

    _early_splash_clock_underlay = _bind_deps(
        _core_startup._early_splash_clock_underlay,
        _bgr_to_tk_image=_bgr_to_tk_image,
        _early_clock_underlay_photo=_early_clock_underlay_photo,
        _reveal_clock_under_splash=_reveal_clock_under_splash,
        _splash_reveal_clock=_splash_reveal_clock,
        _splash_underlay_bgr=_splash_underlay_bgr,
        label=label,
    )

    # Keep label in sync once splash has reached the reveal frame.
    _splash_on_reveal_paint[0] = _early_splash_clock_underlay
    if _splash_reveal_clock[0]:
        try:
            _early_splash_clock_underlay()
        except Exception:
            pass

    ctx.label = label
    ctx.video_area = video_area
