"""Marks the span of one scheduled render so per-frame work can be shared.

Several checks (clock saver, live audio, auto-widget policy) are asked the
same question many times while one frame is composed. Inside a frame they
can reuse the first answer; outside one (key handlers, timers) :func:`token`
is None and callers compute fresh, as before.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

_frame = 0
_active = False


@contextmanager
def render_frame() -> Iterator[None]:
    """Wrap one scheduled ``render_once``. Not re-entrant (nested frames reuse the outer one)."""
    global _frame, _active
    if _active:
        yield
        return
    _frame += 1
    _active = True
    try:
        yield
    finally:
        _active = False


def token() -> int | None:
    """Id of the frame being rendered, or None outside a scheduled render."""
    return _frame if _active else None
