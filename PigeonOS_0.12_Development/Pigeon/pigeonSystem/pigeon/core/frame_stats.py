"""Opt-in render timing: frame rate and render-time percentiles in the log.

Turn on with ``PIGEON_FRAME_STATS=1`` or by creating ``frame_stats`` in the
Pigeon state dir (no restart needed; the file is checked every few seconds).
Every ``REPORT_S`` seconds one line goes to stderr::

    pigeon: frames 29.7 fps | render p50 21 p95 34 max 48 ms | interval p50 33 p95 40 max 61 ms | slow 3/149

*render* is the time spent in one ``render_once``; *interval* is start-to-start,
which is what the eye sees as stutter. *slow* counts intervals over 1.5× the
33 ms live-audio budget.
"""

from __future__ import annotations

import os
import sys
import time

REPORT_S = 5.0
FLAG_NAME = "frame_stats"
_FLAG_POLL_S = 3.0
BUDGET_MS = 33.0

_enabled = False
_flag_checked = -1e9
_window_start: float | None = None
_last_start: float | None = None
_render_ms: list[float] = []
_interval_ms: list[float] = []


def _check_enabled(now: float) -> bool:
    global _enabled, _flag_checked
    if now - _flag_checked < _FLAG_POLL_S:
        return _enabled
    _flag_checked = now
    env = os.environ.get("PIGEON_FRAME_STATS", "").strip()
    if env:
        _enabled = env not in ("0", "false", "no")
        return _enabled
    try:
        from pigeon.runtime_paths import pigeon_state_dir

        _enabled = (pigeon_state_dir() / FLAG_NAME).exists()
    except Exception:
        _enabled = False
    return _enabled


def _pct(sorted_vals: list[float], frac: float) -> float:
    return sorted_vals[min(len(sorted_vals) - 1, int(frac * len(sorted_vals)))]


def note_render(t_start: float, t_end: float) -> None:
    """Record one ``render_once`` that ran from *t_start* to *t_end* (perf_counter)."""
    global _window_start, _last_start
    if not _check_enabled(time.monotonic()):
        _window_start = _last_start = None
        _render_ms.clear()
        _interval_ms.clear()
        return
    if _last_start is not None:
        _interval_ms.append((t_start - _last_start) * 1000.0)
    _last_start = t_start
    _render_ms.append((t_end - t_start) * 1000.0)
    if _window_start is None:
        _window_start = t_start
        return
    span = t_end - _window_start
    if span < REPORT_S:
        return
    r = sorted(_render_ms)
    iv = sorted(_interval_ms) or [0.0]
    over = sum(1 for v in _interval_ms if v > BUDGET_MS * 1.5)
    try:
        sys.stderr.write(
            f"pigeon: frames {len(r) / span:.1f} fps | "
            f"render p50 {_pct(r, 0.5):.0f} p95 {_pct(r, 0.95):.0f} max {r[-1]:.0f} ms | "
            f"interval p50 {_pct(iv, 0.5):.0f} p95 {_pct(iv, 0.95):.0f} max {iv[-1]:.0f} ms | "
            f"slow {over}/{len(_interval_ms)}\n"
        )
    except Exception:
        pass
    _window_start = None
    _render_ms.clear()
    _interval_ms.clear()
