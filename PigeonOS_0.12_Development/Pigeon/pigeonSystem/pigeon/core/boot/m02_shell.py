"""Main-window phase: the shell / content frames, the boot clock label, and splash / startup state.

Phase 2 of ``main()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from PIL import ImageTk
from pathlib import Path
import numpy as np
import tkinter as tk


def run(ctx) -> None:
    _PIGEON_EXT = ctx._PIGEON_EXT
    _PROJECT_DIR = ctx._PROJECT_DIR
    resolve_splash_media = ctx.resolve_splash_media
    root = ctx.root

    shell = tk.Frame(root, bg="#111", cursor="none")
    shell.pack(fill=tk.BOTH, expand=True)
    # Main UI is built here; splash overlay sits above until the splash sequence finishes.
    content_host = tk.Frame(shell, bg="#111", cursor="none")
    content_host.pack(fill=tk.BOTH, expand=True)
    # Bridge host so the clock saver is visible the instant splash lifts — even if full
    # bootstrap has not created the real video ``Label`` yet. Bootstrap destroys this.
    _boot_clock_host = tk.Frame(content_host, bg="#000", cursor="none")
    _boot_clock_host.pack(fill=tk.BOTH, expand=True)
    _boot_clock_label = tk.Label(_boot_clock_host, bd=0, highlightthickness=0, bg="#000", cursor="none")
    _boot_clock_label.pack(fill=tk.BOTH, expand=True)
    _boot_clock_photo: list[ImageTk.PhotoImage | None] = [None]

    # Full-window splash: PNG sequence in ``pigeonSplash/`` if present, else H.264/HEVC
    # video (hardware-decoded on macOS), else built-in wordmark.
    startup_ph: list[tk.Widget | None] = [None]
    splash_png_paths: list[Path] = []
    splash_video_path: Path | None = None
    if _PIGEON_EXT:
        try:
            _assets_root = Path(_PROJECT_DIR) / "pigeonAssets"
            splash_png_paths, splash_video_path = resolve_splash_media(_assets_root)
        except Exception:
            splash_png_paths = []
            splash_video_path = None

    bootstrap_done: list[bool] = [False]
    splash_anim_done: list[bool] = [False]
    # Set when the splash parks on its logo hold; bootstrap runs underneath it.
    splash_bootstrap_go: list[bool] = [False]
    # Live underlay composited under splash PNG alpha. Stays black until the reveal frame.
    _splash_underlay_bgr: list[np.ndarray | None] = [None]
    # Live clock buffer (background thread); copied under the splash from the reveal frame.
    _splash_clock_ready_bgr: list[np.ndarray | None] = [None]
    # Stop the live-clock worker once compose owns the display.
    _splash_clock_refresh_stop: list[bool] = [False]
    # True once splash reaches ``SPLASH_CLOCK_REVEAL_FRAME``.
    _splash_reveal_clock: list[bool] = [False]
    # Registered from bootstrap: keep the real video label in sync after reveal.
    _splash_on_reveal_paint: list[object] = [None]
    _splash_underlay_paint_mono: list[float] = [0.0]
    _splash_post_hook_ran: list[bool] = [False]
    # Post-splash UI timing (splash lift).
    post_splash_mono: list[float | None] = [None]
    _post_splash_startup_hook: list[object] = [None]

    ctx._boot_clock_host = _boot_clock_host
    ctx._boot_clock_label = _boot_clock_label
    ctx._boot_clock_photo = _boot_clock_photo
    ctx._post_splash_startup_hook = _post_splash_startup_hook
    ctx._splash_clock_ready_bgr = _splash_clock_ready_bgr
    ctx._splash_clock_refresh_stop = _splash_clock_refresh_stop
    ctx._splash_on_reveal_paint = _splash_on_reveal_paint
    ctx._splash_post_hook_ran = _splash_post_hook_ran
    ctx._splash_reveal_clock = _splash_reveal_clock
    ctx._splash_underlay_bgr = _splash_underlay_bgr
    ctx._splash_underlay_paint_mono = _splash_underlay_paint_mono
    ctx.bootstrap_done = bootstrap_done
    ctx.content_host = content_host
    ctx.post_splash_mono = post_splash_mono
    ctx.shell = shell
    ctx.splash_anim_done = splash_anim_done
    ctx.splash_bootstrap_go = splash_bootstrap_go
    ctx.splash_png_paths = splash_png_paths
    ctx.splash_video_path = splash_video_path
    ctx.startup_ph = startup_ph
