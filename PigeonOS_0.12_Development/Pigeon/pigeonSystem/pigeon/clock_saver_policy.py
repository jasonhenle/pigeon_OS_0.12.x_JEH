"""Pure rules for when the idle clock saver should arm."""

from __future__ import annotations

# Pausesaver holds for this span, then Clocksaver takes over.
CLOCK_SAVER_PAUSED_AFTER_S = 30.0


def player_reports_playing(
    device_state: object = "",
    *,
    clock_playing: bool = False,
) -> bool:
    """True only for active playback. Paused / Stopped beat a stale clock flag."""
    ds = str(device_state or "")
    if "Paused" in ds or "Stopped" in ds:
        return False
    if bool(clock_playing) or "Playing" in ds:
        return True
    return False


def next_paused_since_mono(paused: bool, now: float, paused_since_mono: float) -> float:
    """Keep the pause-start stamp while paused; clear it on play / idle."""
    if not paused:
        return 0.0
    if float(paused_since_mono) <= 0.0:
        return float(now)
    return float(paused_since_mono)


def tick_pause_hold(
    paused: bool,
    now: float,
    paused_since_mono: float,
    last_hold_mono: float,
    *,
    grace_s: float = 2.5,
) -> tuple[float, float, float]:
    """Age a pausesaver hold, ignoring brief metadata drops.

    Returns ``(age_s, since_mono, last_hold_mono)``.
    """
    t = float(now)
    since = float(paused_since_mono)
    last = float(last_hold_mono)
    if paused:
        if since <= 0.0:
            since = t
        return max(0.0, t - since), since, t
    if since > 0.0 and last > 0.0 and (t - last) < float(grace_s):
        return max(0.0, t - since), since, last
    return 0.0, 0.0, 0.0


def pause_hold_s(paused: bool, now: float, paused_since_mono: float) -> float:
    started = next_paused_since_mono(paused, now, paused_since_mono)
    if started <= 0.0:
        return 0.0
    return max(0.0, float(now) - started)


def clock_saver_due_for_pause(
    paused: bool,
    paused_for_s: float,
    *,
    after_s: float = CLOCK_SAVER_PAUSED_AFTER_S,
) -> bool:
    """True when loaded content has stayed paused long enough to show the saver."""
    return bool(paused) and float(paused_for_s) >= float(after_s)


def pausesaver_due_for_clocksaver(
    held_for_s: float,
    *,
    after_s: float = CLOCK_SAVER_PAUSED_AFTER_S,
) -> bool:
    """True after Pausesaver has been up long enough to hand off to Clocksaver."""
    return float(held_for_s) >= float(after_s)


def pausesaver_hold_from_metadata_class(player_metadata: str) -> bool:
    """True while auto widgets classify this as paused/stopped content.

    A held title can still look like playback. Do not let that veto a
    ``stopped`` classification — otherwise the Clocksaver timer never ages.
    """
    return str(player_metadata or "").strip().lower() == "stopped"


def clock_saver_due_for_no_content(
    *,
    playing: bool,
    paused_with_content: bool,
    live: bool = False,
    content_idle: bool = True,
    incoming_audio: bool = False,
) -> bool:
    """True when nothing is playing and no paused title is holding now-playing."""
    if playing or paused_with_content or live or incoming_audio:
        return False
    return bool(content_idle)


def should_hold_paused_screen(
    *,
    paused_with_content: bool,
    has_backdrop: bool,
    clock_saver_active: bool,
) -> bool:
    """The paused plate yields once the clock saver owns the frame."""
    return bool(paused_with_content and has_backdrop and not clock_saver_active)


def tmdb_should_skip_refetch_on_resume(
    *,
    content_key: object | None,
    prev_content_key: object | None,
    has_tmdb_identity: bool,
) -> bool:
    """Same now-playing identity after pause/resume must not start a new TMDb worker."""
    ck = str(content_key or "").strip()
    prev = str(prev_content_key or "").strip()
    return bool(ck and prev and ck == prev and has_tmdb_identity)
