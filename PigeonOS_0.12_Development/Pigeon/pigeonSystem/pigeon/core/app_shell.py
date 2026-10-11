"""Main window shell: kiosk re-assertion, quit / desktop-chrome restore, and the Tk callback error reporter.

Extracted verbatim from ``main()`` in ``pigeon_0_12.py``. Each function
takes the app state it used to close over as keyword-only arguments;
``main()`` binds them once with ``bind_deps`` so call sites are unchanged.
"""

from __future__ import annotations

from pigeon.linux_kiosk import enforce_kiosk
from pigeon.linux_kiosk import release_kiosk
from pigeon.linux_kiosk import window_covers_display
import sys
import tkinter.messagebox as messagebox


def _reassert_kiosk(_event: object | None = None, *, _kiosk_logged, _kiosk_on, _kiosk_stopped_pids, root) -> None:
    if not _kiosk_on:
        return
    try:
        updated = enforce_kiosk(root, _kiosk_stopped_pids, borderless=True)
    except Exception:
        updated = list(_kiosk_stopped_pids)
    _kiosk_stopped_pids[:] = updated
    if _kiosk_logged[0]:
        return
    try:
        covers = bool(window_covers_display(root))
    except Exception:
        covers = False
    if covers:
        _kiosk_logged[0] = True
        try:
            sys.stderr.write(
                f"pigeon: kiosk {root.winfo_width()}x{root.winfo_height()}"
                f"+{root.winfo_rootx()}+{root.winfo_rooty()} "
                f"screen={root.winfo_screenwidth()}x{root.winfo_screenheight()}\n"
            )
            sys.stderr.flush()
        except Exception:
            pass


def _restore_desktop_chrome(*, _kiosk_on, _kiosk_stopped_pids) -> None:
    if _kiosk_stopped_pids or _kiosk_on:
        release_kiosk(list(_kiosk_stopped_pids))
        _kiosk_stopped_pids.clear()


def _quit_pigeon(*, _restore_desktop_chrome, root, stop_audio_meter_capture) -> None:
    try:
        if stop_audio_meter_capture is not None:
            stop_audio_meter_capture()
    except Exception:
        pass
    _restore_desktop_chrome()
    root.quit()


def _report_callback_exception(exc, val, tb, *, _kiosk_on) -> None:  # type: ignore[no-untyped-def]
    # Tk calls this as report_callback_exception(exc, val, tb) — no bound self.
    import traceback

    text = "".join(traceback.format_exception(exc, val, tb))
    try:
        sys.stderr.write("pigeon: Tk callback exception\n" + text + "\n")
        sys.stderr.flush()
    except Exception:
        pass
    if _kiosk_on:
        return
    try:
        messagebox.showerror("Pigeon error", text)
    except Exception:
        pass
