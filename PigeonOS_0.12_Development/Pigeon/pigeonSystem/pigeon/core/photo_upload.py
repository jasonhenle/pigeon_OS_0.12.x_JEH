"""Find the parts of a frame that changed, so only those go to the Tk photo.

A full 1920x1080 ``PhotoImage.paste`` costs ~16 ms on a Pi 5. During
playback usually only the zone-4 visualizer and the status bar change, and
uploading those bands costs ~3 ms each. :func:`changed_bands` compares the new
frame with what the photo already shows, 8 bytes at a time (~2 ms per frame).

``PIGEON_PARTIAL_UPLOAD=0`` turns partial uploads off.
"""

from __future__ import annotations

import os

import numpy as np

# Changed rows closer than this are uploaded as one band.
MERGE_GAP_ROWS = 24
# More bands than this, or more than this share of the frame: upload it all.
MAX_BANDS = 6
MAX_AREA_FRAC = 0.5


def partial_upload_enabled() -> bool:
    return os.environ.get("PIGEON_PARTIAL_UPLOAD", "1").strip().lower() not in ("0", "false", "no", "off")


def _as_words(frame: np.ndarray) -> np.ndarray | None:
    """``(h, row_bytes // 8)`` uint64 view of a C-contiguous uint8 frame, or None."""
    if frame.dtype != np.uint8 or not frame.flags.c_contiguous:
        return None
    h = int(frame.shape[0])
    row_bytes = frame.size // max(1, h)
    if h < 1 or row_bytes % 8:
        return None
    return frame.reshape(h, row_bytes).view(np.uint64)


def changed_bands(shown: np.ndarray, new: np.ndarray) -> list[tuple[int, int, int, int]] | None:
    """``(y0, y1, x0, x1)`` boxes that together cover every pixel that differs.

    ``[]`` means nothing changed. ``None`` means upload the whole frame: the
    shapes differ, the frame can't be compared word-wise, or the change is big
    enough that one full upload is cheaper.
    """
    if shown.shape != new.shape or shown.ndim != 3:
        return None
    a, b = _as_words(shown), _as_words(new)
    if a is None or b is None:
        return None
    rows = np.flatnonzero(np.any(a != b, axis=1))
    if rows.size == 0:
        return []
    # Split changed rows into bands wherever the gap is wide enough.
    splits = np.flatnonzero(np.diff(rows) > MERGE_GAP_ROWS) + 1
    starts = np.concatenate(([rows[0]], rows[splits]))
    ends = np.concatenate((rows[splits - 1], [rows[-1]])) + 1
    if starts.size > MAX_BANDS:
        return None
    h, w, ch = (int(v) for v in new.shape)
    out: list[tuple[int, int, int, int]] = []
    area = 0
    for y0, y1 in zip(starts.tolist(), ends.tolist()):
        cols = np.flatnonzero(np.any(a[y0:y1] != b[y0:y1], axis=0))
        # Word columns → pixel columns (a word can straddle two pixels).
        x0 = (int(cols[0]) * 8) // ch
        x1 = min(w, -(-(int(cols[-1]) * 8 + 8) // ch))
        out.append((y0, y1, x0, x1))
        area += (y1 - y0) * (x1 - x0)
    if area > MAX_AREA_FRAC * h * w:
        return None
    return out
