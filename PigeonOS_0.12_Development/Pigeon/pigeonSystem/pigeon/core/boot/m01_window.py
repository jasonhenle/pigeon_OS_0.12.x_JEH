"""Main-window phase: arguments, the Tk root, kiosk guard, quit handling, and the Tk error reporter.

Phase 1 of ``main()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from pigeon.core import app_shell as _core_app_shell
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.linux_kiosk import apply_kiosk_fullscreen
from pigeon.linux_kiosk import linux_kiosk_enabled
from pigeon.linux_kiosk import schedule_kiosk_guard
from pigeon.version import version_string
import argparse
import cv2
import os
import sys
import time
import tkinter as tk


def run(ctx) -> None:
    DISPLAY_H = ctx.DISPLAY_H
    DISPLAY_W = ctx.DISPLAY_W
    WINDOW_H = ctx.WINDOW_H
    WINDOW_W = ctx.WINDOW_W
    _LAUNCH_WINDOW_SCALE = ctx._LAUNCH_WINDOW_SCALE
    __file__ = ctx.__file__
    stop_audio_meter_capture = ctx.stop_audio_meter_capture

    sys.stderr.write(f"pigeon: running script {os.path.abspath(__file__)}\n")
    sys.stderr.flush()
    try:
        from pigeon.pi_diagnostics import run_linux_startup_checks

        run_linux_startup_checks()
    except Exception:
        pass

    parser = argparse.ArgumentParser(prog=f"Pigeon {version_string()}", add_help=True)
    parser.parse_args()

    cap: list[cv2.VideoCapture | None] = [None]

    root = tk.Tk()
    _app_startup_mono = time.monotonic()
    try:
        root.configure(bg="#000", cursor="none")
        root.option_add("*cursor", "none")
    except tk.TclError:
        pass
    root.title("")
    root.geometry(f"{WINDOW_W}x{WINDOW_H}")
    root.minsize(
        int(round((DISPLAY_W // 2) * _LAUNCH_WINDOW_SCALE)),
        int(round((DISPLAY_H // 2) * _LAUNCH_WINDOW_SCALE)),
    )
    root.resizable(True, True)
    _kiosk_stopped_pids: list[int] = []
    _kiosk_on = bool(linux_kiosk_enabled())
    if not _kiosk_on:
        try:
            root.wm_aspect(5, 3, 5, 3)
        except tk.TclError:
            pass

    _kiosk_logged = [False]

    _reassert_kiosk = _bind_deps(
        _core_app_shell._reassert_kiosk,
        _kiosk_logged=_kiosk_logged,
        _kiosk_on=_kiosk_on,
        _kiosk_stopped_pids=_kiosk_stopped_pids,
        root=root,
    )

    if _kiosk_on:
        apply_kiosk_fullscreen(root, borderless=False)
        try:
            root.bind("<Map>", _reassert_kiosk)
        except tk.TclError:
            pass
        try:
            root.after(200, _reassert_kiosk)
            root.after(800, _reassert_kiosk)
        except tk.TclError:
            pass
        schedule_kiosk_guard(root, _kiosk_stopped_pids)

    _restore_desktop_chrome = _bind_deps(
        _core_app_shell._restore_desktop_chrome,
        _kiosk_on=_kiosk_on,
        _kiosk_stopped_pids=_kiosk_stopped_pids,
    )

    _quit_pigeon = _bind_deps(
        _core_app_shell._quit_pigeon,
        _restore_desktop_chrome=_restore_desktop_chrome,
        root=root,
        stop_audio_meter_capture=stop_audio_meter_capture,
    )

    root.protocol("WM_DELETE_WINDOW", _quit_pigeon)
    if _kiosk_on:
        import atexit

        atexit.register(_restore_desktop_chrome)
    # Ensure unexpected Tk callback errors are surfaced (and don't silently kill UI behavior).
    _report_callback_exception = _bind_deps(
        _core_app_shell._report_callback_exception,
        _kiosk_on=_kiosk_on,
    )

    root.report_callback_exception = _report_callback_exception  # type: ignore[method-assign]

    ctx._app_startup_mono = _app_startup_mono
    ctx._kiosk_on = _kiosk_on
    ctx._restore_desktop_chrome = _restore_desktop_chrome
    ctx.cap = cap
    ctx.root = root
