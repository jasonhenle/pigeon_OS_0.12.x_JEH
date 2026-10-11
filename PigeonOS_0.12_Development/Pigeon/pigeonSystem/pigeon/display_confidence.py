"""How sure we are about each now-playing field.

The player (pyatv / Roku) is trusted when it gives a real title. When that
title is missing or is only a service name, a live HDMI signal with an app in
the foreground still keeps now-playing up. After an app change, leftover
identity is stale until the player confirms it.

The UI should only put up fields at or above ``DISPLAY_MIN``.
"""

from __future__ import annotations

from typing import Any, Mapping

DISPLAY_MIN = 0.50
PYATV_IDENTITY = 0.90
STALE = 0.20
POSITION_LIVE = 0.90
ART_MATCHED = 0.80
APP_BADGE = 0.85
# Apple TV total_time vs TMDb runtime. Ratio of the shorter to the longer.
TRT_AGREE = 0.80
TRT_REJECT = 0.40
# Feature-length / miniseries: 1h45 vs 3h+ must not count as a match.
TRT_LONG_MIN_S = 40.0 * 60.0
TRT_LONG_SLACK_S = 20.0 * 60.0
TRT_LONG_RATIO = 0.75


def is_placeholder_identity(value: str) -> bool:
    """True when a string is empty or only a service name."""
    text = str(value or "").strip()
    if not text:
        return True
    try:
        from pigeon.tmdb_poster import is_degenerate_tmdb_query

        if is_degenerate_tmdb_query(text):
            return True
    except ImportError:
        pass
    return False


def parse_position(metadata: Mapping[str, Any] | None) -> float | None:
    md = metadata if isinstance(metadata, dict) else {}
    raw = md.get("position")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_duration_seconds(value: Any) -> float | None:
    """Normalize a player or clock duration to seconds.

    pyatv ``total_time`` is seconds. Values longer than 20 hours are treated as
    milliseconds (some MRP paths).
    """
    if value is None or value == "":
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0.0:
        return None
    if seconds > 20.0 * 3600.0:
        seconds = seconds / 1000.0
    if seconds <= 0.0:
        return None
    return seconds


def remaining_seconds(
    metadata: Mapping[str, Any] | None,
    *,
    fallback_duration_s: float | None = None,
) -> float | None:
    """Seconds left when both playhead and duration are known."""
    pos = parse_position(metadata)
    dur = player_duration_seconds(metadata, fallbacks=(fallback_duration_s,))
    if pos is None or dur is None:
        return None
    return max(0.0, float(dur) - float(pos))


def playback_has_concluded(
    metadata: Mapping[str, Any] | None,
    *,
    remaining_s: float | None = None,
    slack_s: float = 2.0,
) -> bool:
    """True when a known title has reached the end and is no longer Playing.

    Apple TV often flips to Idle after credits while we still hold the last
    title. That is not still-playing. A remaining of 0 without a duration is
    ignored — some clocks report 0 remaining when ``total_time`` is missing.
    """
    md = metadata if isinstance(metadata, dict) else {}
    ds = str(md.get("device_state") or "")
    if "Playing" in ds and "Paused" not in ds and "Stopped" not in ds:
        return False
    if md.get("playback_concluded"):
        return True
    rem = remaining_s
    if rem is None:
        rem = remaining_seconds(md)
    if rem is None:
        return False
    try:
        rem_f = float(rem)
    except (TypeError, ValueError):
        return False
    dur = player_duration_seconds(md)
    if dur is not None and dur < 30.0:
        return False
    return rem_f <= max(0.0, float(slack_s))


def player_duration_seconds(
    metadata: Mapping[str, Any] | None,
    *,
    fallbacks: tuple[Any, ...] = (),
) -> float | None:
    """Apple TV / player TRT from ``total_time``, then optional clock fallbacks."""
    md = metadata if isinstance(metadata, dict) else {}
    found = parse_duration_seconds(md.get("total_time"))
    if found is not None:
        return found
    for raw in fallbacks:
        found = parse_duration_seconds(raw)
        if found is not None:
            return found
    return None


def trt_similarity(player_s: float, tmdb_s: float) -> float:
    """1.0 when lengths match; shrinks as the two durations diverge."""
    a = float(player_s)
    b = float(tmdb_s)
    if a <= 0.0 or b <= 0.0:
        return 0.0
    return min(a, b) / max(a, b)


def _tmdb_duration_options(
    tmdb_seconds: float | list[float] | tuple[float, ...] | None,
) -> list[float]:
    options: list[float] = []
    if isinstance(tmdb_seconds, (list, tuple)):
        for raw in tmdb_seconds:
            parsed = parse_duration_seconds(raw)
            if parsed is not None:
                options.append(parsed)
    else:
        parsed = parse_duration_seconds(tmdb_seconds)
        if parsed is not None:
            options.append(parsed)
    return options


def trt_pair_acceptable(player_s: float, tmdb_s: float) -> bool:
    """True when one player length and one TMDb length are about the same."""
    player = float(player_s)
    tmdb = float(tmdb_s)
    if player <= 0.0 or tmdb <= 0.0:
        return False
    ratio = trt_similarity(player, tmdb)
    delta = abs(player - tmdb)
    if player >= TRT_LONG_MIN_S or tmdb >= TRT_LONG_MIN_S:
        if delta <= TRT_LONG_SLACK_S:
            return True
        return ratio >= TRT_LONG_RATIO
    return ratio >= TRT_REJECT


def trt_is_reject(
    player_s: float | None,
    tmdb_seconds: float | list[float] | tuple[float, ...] | None,
) -> bool:
    """True when every known TMDb runtime is too far from Apple TV TRT."""
    player = parse_duration_seconds(player_s)
    options = _tmdb_duration_options(tmdb_seconds)
    if player is None or not options:
        return False
    return not any(trt_pair_acceptable(player, opt) for opt in options)


def trt_confidence(
    player_s: float | None,
    tmdb_seconds: float | list[float] | tuple[float, ...] | None,
) -> float | None:
    """Best duration agreement, or ``None`` when we cannot compare."""
    player = parse_duration_seconds(player_s)
    if player is None:
        return None
    options = _tmdb_duration_options(tmdb_seconds)
    if not options:
        return None
    return max(trt_similarity(player, opt) for opt in options)


def playback_detected(metadata: Mapping[str, Any] | None) -> bool:
    """True when the player reports active playback."""
    md = metadata if isinstance(metadata, dict) else {}
    ds = str(md.get("device_state") or "").lower()
    return "playing" in ds


def has_foreground_app(metadata: Mapping[str, Any] | None) -> bool:
    md = metadata if isinstance(metadata, dict) else {}
    return bool(str(md.get("app_id") or md.get("app_name") or "").strip())


def player_metadata_adequate(metadata: Mapping[str, Any] | None) -> bool:
    """True when the player itself supplied a TMDb-ready title."""
    md = metadata if isinstance(metadata, dict) else {}
    source = str(md.get("identity_source") or "").strip().lower()
    if source == "stale":
        return False
    query = str(md.get("query") or "").strip()
    if is_placeholder_identity(query):
        return False
    return True


def hdmi_in_charge(
    metadata: Mapping[str, Any] | None,
    *,
    hdmi_present: bool = True,
) -> bool:
    """No usable player title, but HDMI is carrying a picture."""
    if not hdmi_present:
        return False
    return not player_metadata_adequate(metadata)


def identity_confidence(metadata: Mapping[str, Any] | None) -> float:
    md = metadata if isinstance(metadata, dict) else {}
    raw = md.get("identity_confidence")
    if raw is not None:
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError):
            pass
    source = str(md.get("identity_source") or "").strip().lower()
    if source == "pyatv" and player_metadata_adequate(md):
        return PYATV_IDENTITY
    if source == "stale":
        return STALE
    if player_metadata_adequate(md):
        return PYATV_IDENTITY
    return 0.0


def identity_displayable(metadata: Mapping[str, Any] | None) -> bool:
    md = metadata if isinstance(metadata, dict) else {}
    query = str(md.get("query") or "").strip()
    if is_placeholder_identity(query):
        return False
    return identity_confidence(md) >= DISPLAY_MIN


def position_confidence(*, advancing: bool, has_position: bool) -> float:
    if advancing and has_position:
        return POSITION_LIVE
    return 0.0


def art_confidence(
    *,
    identity_ok: bool,
    tmdb_matches: bool,
    trt_score: float | None = None,
    player_s: float | None = None,
    tmdb_runtime_s: float | list[float] | tuple[float, ...] | None = None,
) -> float:
    if not identity_ok or not tmdb_matches:
        return 0.0
    if trt_is_reject(player_s, tmdb_runtime_s) or (
        trt_score is not None and float(trt_score) < TRT_REJECT
    ):
        return 0.20
    if trt_score is None:
        return ART_MATCHED
    score = float(trt_score)
    if score < TRT_AGREE:
        return ART_MATCHED * (0.50 + 0.50 * score)
    return min(1.0, ART_MATCHED + 0.10)


def app_confidence(metadata: Mapping[str, Any] | None) -> float:
    return APP_BADGE if has_foreground_app(metadata) else 0.0


def content_should_stay_active(
    metadata: Mapping[str, Any] | None,
    *,
    hdmi_present: bool = True,
) -> bool:
    """Keep now-playing chrome up when we have something we can show or watch."""
    if identity_displayable(metadata):
        return True
    if playback_detected(metadata):
        return True
    if has_foreground_app(metadata) and hdmi_in_charge(
        metadata, hdmi_present=hdmi_present
    ):
        return True
    return False


def metadata_is_playback_idle(metadata: Mapping[str, Any] | None) -> bool:
    """True when the player has no usable title and reports idle/stopped.

    A real title wins even if ``device_state`` says Idle (Netflix / YouTube MRP).
    """
    md = metadata if isinstance(metadata, dict) else {}
    if identity_displayable(md) or player_metadata_adequate(md):
        return False
    q = str(md.get("query") or md.get("title") or "").strip()
    if q and not is_placeholder_identity(q):
        return False
    ds = str(md.get("device_state") or "")
    if "Playing" in ds:
        return False
    if "Idle" in ds or "Stopped" in ds:
        return True
    return not q


_IDENTITY_HOLD_KEYS = (
    "query",
    "title",
    "artist",
    "series_name",
    "album",
    "media_type",
    "total_time",
    "identity_source",
    "identity_confidence",
    "title_decision",
    "title_decision_source",
    "title_decision_reason",
    "title_decision_title",
    "title_decision_at",
    "content_key",
    "prefer_pyatv_media",
    "inferred_prefer",
    "app_name",
    "app_id",
    "position",
)


def _identity_field_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def metadata_has_holdable_identity(metadata: Mapping[str, Any] | None) -> bool:
    """True when this dict still names a show TMDb / NP can use."""
    md = metadata if isinstance(metadata, dict) else {}
    if identity_displayable(md) or player_metadata_adequate(md):
        return True
    q = str(md.get("query") or md.get("title") or "").strip()
    return bool(q) and not is_placeholder_identity(q)


def _switched_apps(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
    """True when both polls name an app and the apps differ."""
    def _app(md: Mapping[str, Any]) -> str:
        return str(md.get("app_id") or md.get("app_name") or "").strip().casefold()

    a, b = _app(old), _app(new)
    return bool(a and b and a != b)


def hold_identity_across_idle_poll(
    previous: Mapping[str, Any] | None,
    incoming: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Keep the last TMDb-ready title when pyatv reports Idle with no name.

    MRP / Companion often return Idle while HDMI is still playing the same show.
    A real incoming title, or a powered-off Apple TV, always wins.
    """
    new = dict(incoming) if isinstance(incoming, dict) else {}
    if metadata_has_holdable_identity(new):
        new.pop("identity_held_across_idle", None)
        return new
    raw = str(new.get("power_state") or "").strip().lower()
    if raw == "off" or raw.endswith(".off") or raw.endswith(" off"):
        return new
    old = previous if isinstance(previous, dict) else None
    if old is None or not metadata_has_holdable_identity(old):
        return new
    if _switched_apps(old, new):
        # A different app (e.g. Netflix, which sends no title) is not the
        # same show going Idle — never carry the old title into it.
        return new
    held = dict(new)
    for key in _IDENTITY_HOLD_KEYS:
        if _identity_field_missing(held.get(key)) and not _identity_field_missing(
            old.get(key)
        ):
            held[key] = old[key]
    old_ds = str(old.get("device_state") or "")
    new_ds = str(held.get("device_state") or "")
    if (
        "Idle" in new_ds
        and "Playing" not in new_ds
        and ("Paused" in old_ds or "Stopped" in old_ds)
    ):
        held["device_state"] = old.get("device_state")
    old_pos = parse_position(old)
    new_pos = parse_position(held)
    dur = player_duration_seconds(held) or player_duration_seconds(old)
    if (
        "Idle" in str(held.get("device_state") or "")
        and dur is not None
        and old_pos is not None
        and old_pos >= float(dur) - 2.0
        and (new_pos is None or new_pos <= 1.0)
    ):
        held["position"] = old_pos
        held["playback_concluded"] = True
    held["identity_held_across_idle"] = True
    return held


def scores_for_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    position_advancing: bool = False,
    tmdb_matches: bool = False,
    hdmi_present: bool = True,
    player_duration_s: float | None = None,
    tmdb_runtime_s: float | list[float] | tuple[float, ...] | None = None,
) -> dict[str, float | None]:
    md = metadata if isinstance(metadata, dict) else {}
    ident = identity_confidence(md)
    has_pos = parse_position(md) is not None
    duration = player_duration_seconds(md, fallbacks=(player_duration_s,))
    if duration is None:
        duration = parse_duration_seconds(player_duration_s)
    trt = trt_confidence(duration, tmdb_runtime_s)
    return {
        "identity": ident,
        "position": position_confidence(advancing=position_advancing, has_position=has_pos),
        "art": art_confidence(
            identity_ok=ident >= DISPLAY_MIN,
            tmdb_matches=tmdb_matches,
            trt_score=trt,
            player_s=duration,
            tmdb_runtime_s=tmdb_runtime_s,
        ),
        "app": app_confidence(md),
        "trt": None if trt is None else float(trt),
        "hdmi_charge": 1.0
        if hdmi_in_charge(md, hdmi_present=hdmi_present)
        else 0.0,
    }


def mark_identity(
    metadata: dict[str, Any],
    *,
    source: str,
    confidence: float,
) -> None:
    metadata["identity_source"] = str(source or "").strip().lower()
    metadata["identity_confidence"] = max(0.0, min(1.0, float(confidence)))


def mark_stale(metadata: dict[str, Any]) -> None:
    mark_identity(metadata, source="stale", confidence=STALE)
