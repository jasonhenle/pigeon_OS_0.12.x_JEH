"""
TMDb match mode: literal (default) vs forgiving heuristics.

Owns the one piece of mutable state behind that choice: the session override set by
:func:`toggle_tmdb_match_mode`, falling back to ``PIGEON_TMDB_MATCH_MODE``. Kept apart
from ``tmdb_poster`` so the query rules in ``tmdb_query`` can read the mode without
importing the network / cache layer.

``pigeon.tmdb_poster`` re-exports the public functions.
"""

from __future__ import annotations

import os

# Session override set by :func:`toggle_tmdb_match_mode` (``None`` = follow env only).
_tmdb_match_runtime_forgiving: bool | None = None

_FORGIVING_ENV_TOKENS = frozenset(("forgiving", "loose", "legacy", "1", "true", "yes", "on"))


def _env_wants_forgiving() -> bool:
    v = (os.environ.get("PIGEON_TMDB_MATCH_MODE") or "literal").strip().lower()
    return v in _FORGIVING_ENV_TOKENS


def tmdb_match_forgiving(*, override: bool | None = None) -> bool:
    """
    False = literal/strict matching (default from env). True = legacy forgiving heuristics.

    ``override`` forces the mode regardless of env and runtime toggle.

    After :func:`toggle_tmdb_match_mode`, the runtime choice wins over ``PIGEON_TMDB_MATCH_MODE``
    until the process exits.
    """
    if override is not None:
        return override
    if _tmdb_match_runtime_forgiving is not None:
        return _tmdb_match_runtime_forgiving
    return _env_wants_forgiving()


def toggle_tmdb_match_mode() -> str:
    """
    Flip literal ↔ forgiving for this session.

    Returns ``literal`` or ``forgiving`` (the mode after the toggle).
    """
    global _tmdb_match_runtime_forgiving
    if _tmdb_match_runtime_forgiving is None:
        current = _env_wants_forgiving()
    else:
        current = _tmdb_match_runtime_forgiving
    _tmdb_match_runtime_forgiving = not current
    return "forgiving" if _tmdb_match_runtime_forgiving else "literal"
