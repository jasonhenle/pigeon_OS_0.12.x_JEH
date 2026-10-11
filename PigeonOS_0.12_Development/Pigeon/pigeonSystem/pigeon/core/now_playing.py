"""Now-playing metadata queries: app detection, music/video artwork caches, playback clock maths.

Extracted verbatim from ``bootstrap()`` in ``pigeon_0_12.py``. Each function
takes the app state it used to close over as keyword-only arguments;
``bootstrap()`` binds them once with ``bind_deps`` so call sites are unchanged.
"""

from __future__ import annotations

import time
import cv2
import numpy as np
from pathlib import Path
from pigeon.app_state import read_saved_av_receiver
import json
import threading


def _metadata_is_netflix_app(metadata: dict[str, object] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    bid = str(metadata.get("app_id") or "").strip().lower()
    bid2 = str(
        metadata.get("bundle_identifier")
        or metadata.get("app_identifier")
        or metadata.get("bundle_id")
        or ""
    ).strip().lower()
    an = str(metadata.get("app_name") or "").strip().lower()
    return "netflix" in an or "netflix" in bid or "netflix" in bid2


def _playback_is_netflix_stream(*, _metadata_is_netflix_app, apple_tv_auto_state, streaming_badge_state) -> bool:
    lm = apple_tv_auto_state.get("last_metadata")
    if _metadata_is_netflix_app(lm if isinstance(lm, dict) else None):
        return True
    sb = streaming_badge_state
    lbl = str(sb.get("label") or "").strip().lower()
    fn = str(sb.get("filename") or "").strip().lower()
    return "netflix" in lbl or "netflix" in fn


def _clear_music_artwork_cache(*, apple_tv_auto_state) -> None:
    """Drop cached pyatv music artwork (leaving music / idle / track miss)."""
    if (
        apple_tv_auto_state.get("music_artwork_bgra") is None
        and apple_tv_auto_state.get("music_artwork_key") is None
    ):
        return
    apple_tv_auto_state["music_artwork_bgra"] = None
    apple_tv_auto_state["music_artwork_key"] = None


def _clear_video_artwork_cache(*, apple_tv_auto_state) -> None:
    """Drop cached pyatv YouTube / 16×9 artwork."""
    if (
        apple_tv_auto_state.get("video_artwork_bgra") is None
        and apple_tv_auto_state.get("video_artwork_key") is None
        and apple_tv_auto_state.get("youtube_thumb_key") is None
    ):
        return
    apple_tv_auto_state["video_artwork_bgra"] = None
    apple_tv_auto_state["video_artwork_key"] = None
    apple_tv_auto_state["youtube_thumb_key"] = None


def _clear_playback_artwork_caches(*, _clear_music_artwork_cache, _clear_video_artwork_cache) -> None:
    _clear_music_artwork_cache()
    _clear_video_artwork_cache()


def _music_artwork_track_key(md: dict[str, object]) -> str:
    return "|".join(
        (
            str(md.get("hash") or "").strip(),
            str(md.get("artwork_id") or "").strip(),
            str(md.get("title") or "").strip(),
            str(md.get("artist") or "").strip(),
            str(md.get("album") or "").strip(),
        )
    )


def _decode_artwork_bytes_bgra(raw: object) -> np.ndarray | None:
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return None
    try:
        data = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except Exception:
        return None
    if img is None or img.size == 0:
        return None
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    if img.shape[2] >= 4:
        return img[:, :, :4].copy()
    return None


def _vv_has_content_title(*, _playback_display_title) -> bool:
    return bool(_playback_display_title())


def _vv_has_current_app(*, apple_tv_auto_state, streaming_badge_state) -> bool:
    if str(streaming_badge_state.get("filename") or "").strip():
        return True
    lm = apple_tv_auto_state.get("last_metadata")
    if isinstance(lm, dict):
        if str(lm.get("app_name") or "").strip():
            return True
        if str(lm.get("app_id") or "").strip():
            return True
    return False


def _vv_has_app_logo(*, _resolve_streaming_app_logo_bgra) -> bool:
    return _resolve_streaming_app_logo_bgra() is not None


def _vv_is_music(*, apple_tv_auto_state) -> bool:
    """True when the currently playing media is of type Music.

    Reads ``last_metadata['media_type']`` (populated via pyatv) and accepts
    both the pyatv ``MediaType.Music`` stringified form and the bare ``Music``
    label to be robust across metadata sources.
    """
    lm = apple_tv_auto_state.get("last_metadata")
    if not isinstance(lm, dict):
        return False
    mt = str(lm.get("media_type") or "").strip().lower()
    if not mt:
        return False
    return mt == "music" or mt.endswith(".music")


def _vv_is_youtube(*, apple_tv_auto_state, streaming_badge_state) -> bool:
    """True when the foreground streaming app is YouTube."""
    try:
        from pigeon.streaming_service_badges import is_youtube_streaming_service
    except Exception:
        is_youtube_streaming_service = None  # type: ignore[assignment]
    sb = streaming_badge_state
    label = str(sb.get("label") or "").strip()
    filename = str(sb.get("filename") or "").strip()
    app_name = ""
    app_id = ""
    lm = apple_tv_auto_state.get("last_metadata")
    if isinstance(lm, dict):
        app_name = str(lm.get("app_name") or "")
        app_id = str(lm.get("app_id") or "")
    if is_youtube_streaming_service is not None:
        if is_youtube_streaming_service(
            app_name=app_name,
            app_id=app_id,
            label=label,
            filename=filename,
        ):
            return True
    else:
        blob = f"{label} {filename} {app_name} {app_id}".lower()
        if "youtube" in blob:
            return True
    if isinstance(lm, dict):
        try:
            from pigeon.apple_tv_now_playing import youtube_video_id_from_metadata

            if youtube_video_id_from_metadata(lm):
                return True
        except Exception:
            pass
    return False


def _vv_music_text_lines(*, apple_tv_auto_state) -> tuple[str, str]:
    """Return ``(title, subtitle)`` for Music text rendering.

    ``title`` is the track title (large top line); ``subtitle`` is the
    composed ``"Artist - Album"`` string (smaller line beneath) with a
    graceful collapse when either field is missing:

    * both present  → ``"Artist - Album"``
    * artist only   → ``"Artist"``
    * album only    → ``"Album"``
    * neither       → ``""``

    If ``title`` is empty but ``album`` is populated, ``album`` is
    promoted to ``title`` so the large line is never blank; the
    subtitle then collapses to just the artist (if any).
    """
    lm = apple_tv_auto_state.get("last_metadata")
    if not isinstance(lm, dict):
        return ("", "")
    title = str(lm.get("title") or "").strip()
    artist = str(lm.get("artist") or "").strip()
    album = str(lm.get("album") or "").strip()
    if not title and album:
        title, album = album, ""
    if artist and album:
        subtitle = f"{artist} - {album}"
    elif artist:
        subtitle = artist
    elif album:
        subtitle = album
    else:
        subtitle = ""
    return (title, subtitle)


def _stable_bgr_from_bgra(bgra: np.ndarray | None, *, _bgr_from_bgra_cache) -> np.ndarray | None:
    """BGR for a BGRA still. Same source array keeps the same destination."""
    if not isinstance(bgra, np.ndarray) or bgra.size == 0 or bgra.ndim != 3:
        _bgr_from_bgra_cache["src_id"] = None
        _bgr_from_bgra_cache["bgr"] = None
        return None
    sid = id(bgra)
    cached = _bgr_from_bgra_cache["bgr"]
    if sid == _bgr_from_bgra_cache["src_id"] and isinstance(cached, np.ndarray):
        return cached
    if bgra.shape[2] >= 4:
        out = np.ascontiguousarray(bgra[:, :, :3])
    elif bgra.shape[2] == 3:
        out = np.ascontiguousarray(bgra)
    else:
        _bgr_from_bgra_cache["src_id"] = None
        _bgr_from_bgra_cache["bgr"] = None
        return None
    _bgr_from_bgra_cache["src_id"] = sid
    _bgr_from_bgra_cache["bgr"] = out
    return out


def _paused_screen_artwork_bgr(*, _stable_bgr_from_bgra, apple_tv_auto_state) -> np.ndarray | None:
    """Album art as BGR, or None."""
    art = apple_tv_auto_state.get("music_artwork_bgra")
    return _stable_bgr_from_bgra(art if isinstance(art, np.ndarray) else None)


def _current_app_display_name(*, apple_tv_auto_state, streaming_badge_state) -> str:
    """Human-readable name for the currently foregrounded streaming app."""
    label = str(streaming_badge_state.get("label") or "").strip()
    if label:
        return label
    lm = apple_tv_auto_state.get("last_metadata")
    if isinstance(lm, dict):
        for k in ("app_name", "app_id"):
            v = str(lm.get(k) or "").strip()
            if v:
                return v
    return ""


def _player_duration_for_tmdb(*, apple_tv_auto_state, apple_tv_playback_clock) -> float | None:
    try:
        from pigeon.display_confidence import player_duration_seconds
    except ImportError:
        return None
    md = apple_tv_auto_state.get("last_metadata")
    clk = apple_tv_playback_clock
    return player_duration_seconds(
        md if isinstance(md, dict) else None,
        fallbacks=(clk.get("latched_total"), clk.get("last_reported_total")),
    )


def _playback_extrapolated_pair(*, apple_tv_playback_clock) -> tuple[int, int] | None:
    clk = apple_tv_playback_clock
    if clk.get("live_mode"):
        return None
    if not clk.get("has_sync"):
        return None
    now_m = time.monotonic()
    sp = float(clk["sync_position"])
    sm = float(clk["sync_mono"])
    pos = sp + (now_m - sm) if clk.get("playing") else sp
    pos = max(0.0, pos)
    lt = clk.get("latched_total")
    if lt is None:
        lt = clk.get("last_reported_total")
    if lt is not None:
        try:
            tft = float(lt)
            pos = min(pos, tft)
        except (TypeError, ValueError):
            tft = None
        else:
            played = int(pos)
            remaining = max(0, int(tft) - played)
            return played, remaining
    return int(pos), 0


def _playback_progress_fraction_for_bar(*, apple_tv_playback_clock) -> float | None:
    """Integer-second played / total for progress bar (None if duration unknown)."""
    clk = apple_tv_playback_clock
    if clk.get("live_mode"):
        return None
    if not clk.get("has_sync"):
        return None
    lt = clk.get("latched_total")
    if lt is None:
        lt = clk.get("last_reported_total")
    if lt is None:
        return None
    try:
        total_f = float(lt)
    except (TypeError, ValueError):
        return None
    if total_f <= 0:
        return None
    now_m = time.monotonic()
    sp = float(clk["sync_position"])
    sm = float(clk["sync_mono"])
    pos = sp + (now_m - sm) if clk.get("playing") else sp
    pos = max(0.0, min(pos, total_f))
    played_i = int(pos)
    total_i = max(1, int(round(total_f)))
    return max(0.0, min(1.0, played_i / float(total_i)))


def _trt_substantive_from_clock(*, apple_tv_playback_clock) -> bool:
    """True when we have duration-based played/remaining timecodes (not live / unknown TRT)."""
    clk = apple_tv_playback_clock
    if clk.get("live_mode"):
        return False
    if not clk.get("has_sync"):
        return False
    lt = clk.get("latched_total")
    if lt is None:
        lt = clk.get("last_reported_total")
    if lt is not None:
        try:
            if float(lt) > 0.0:
                return True
        except (TypeError, ValueError):
            pass
    # Position-only streams: show elapsed TRT even when total_time never arrives.
    if clk.get("playing"):
        try:
            return float(clk.get("sync_position") or 0.0) >= 0.0
        except (TypeError, ValueError):
            return False
    return False


def _trt_substantive_for_status_bar(*, _trt_substantive_from_clock) -> bool:
    return _trt_substantive_from_clock()


def _atv_metadata_is_content_idle(metadata: dict[str, object], *, metadata_has_playback_title, resolve_metadata_tmdb_query) -> bool:
    try:
        from pigeon.apple_tv_now_playing import apple_tv_power_is_off

        if apple_tv_power_is_off(metadata):
            return True
    except Exception:
        pass
    try:
        from pigeon.display_confidence import content_should_stay_active
        from pigeon.hdmi_capture import hdmi_capture_available

        if content_should_stay_active(
            metadata,
            hdmi_present=hdmi_capture_available(),
        ):
            return False
    except Exception:
        pass
    try:
        from pigeon.display_confidence import metadata_is_playback_idle

        return bool(metadata_is_playback_idle(metadata))
    except Exception:
        pass
    ds = str(metadata.get("device_state") or "")
    if resolve_metadata_tmdb_query is not None and resolve_metadata_tmdb_query(metadata):
        return False
    if metadata_has_playback_title is not None and metadata_has_playback_title(metadata):
        return False
    q = str(metadata.get("query") or "").strip()
    if q:
        return False
    if "Idle" in ds or "Stopped" in ds:
        return True
    if "Playing" in ds:
        return False
    return not q


def _program_audio_present(*, program_audio_present) -> bool:
    if program_audio_present is None:
        return False
    try:
        return bool(program_audio_present())
    except Exception:
        return False


def _program_audio_session(*, _program_audio_present, program_audio_session_present) -> bool:
    """True through quiet scenes after program audio has been heard."""
    if program_audio_session_present is not None:
        try:
            return bool(program_audio_session_present())
        except Exception:
            pass
    return _program_audio_present()


def _np_widgets_content_active(*, incoming: str = "", config: str = "", _apple_tv_is_off, _atv_metadata_is_content_idle, _program_audio_session, _show_paused_row_overlay, _something_playing_now, apple_tv_auto_state, apple_tv_playback_clock, receiver_standby_holder) -> bool:
    """True when NP should show more than the clock (title / play / AVR / audio)."""
    if _program_audio_session():
        return True
    if _apple_tv_is_off():
        return False
    if _something_playing_now() or _show_paused_row_overlay():
        return True
    if bool(apple_tv_playback_clock.get("live_mode")):
        return True
    lm = apple_tv_auto_state.get("last_metadata")
    if isinstance(lm, dict) and not _atv_metadata_is_content_idle(lm):
        return True
    if apple_tv_auto_state.get("tmdb_fetch_in_flight") or apple_tv_auto_state.get(
        "pending_tmdb"
    ):
        q = ""
        if isinstance(lm, dict):
            q = str(lm.get("query") or lm.get("title") or "").strip()
        if not q:
            q = str(apple_tv_auto_state.get("query") or "").strip()
        if q:
            return True
    if not bool(receiver_standby_holder[0]):
        if str(incoming or "").strip() or str(config or "").strip():
            return True
    return False


def _store_music_artwork_from_metadata(md: dict[str, object] | None, *, _atv_metadata_is_content_idle, _clear_music_artwork_cache, _clear_playback_artwork_caches, _clear_video_artwork_cache, _decode_artwork_bytes_bgra, _music_artwork_track_key, _vv_is_youtube, apple_tv_auto_state) -> None:
    """Decode/store pyatv artwork for Music covers or YouTube 16×9 thumbs."""
    if not isinstance(md, dict):
        _clear_playback_artwork_caches()
        return
    if _atv_metadata_is_content_idle(md):
        # YouTube often reports Idle on MRP while HDMI/Companion still play.
        # Keep a thumb we already have instead of flashing an empty zone 6.
        if not _vv_is_youtube():
            _clear_playback_artwork_caches()
            return
        if not md.get("artwork_bytes"):
            return
    mt = str(md.get("media_type") or "").strip().lower()
    is_music = mt == "music" or mt.endswith(".music")
    is_youtube = False
    try:
        from pigeon.streaming_service_badges import is_youtube_streaming_service

        is_youtube = bool(
            is_youtube_streaming_service(
                app_name=str(md.get("app_name") or ""),
                app_id=str(md.get("app_id") or ""),
            )
        )
    except Exception:
        blob = f"{md.get('app_name') or ''} {md.get('app_id') or ''}".lower()
        is_youtube = "youtube" in blob
    if not is_youtube:
        try:
            is_youtube = bool(_vv_is_youtube())
        except Exception:
            pass
    track_key = _music_artwork_track_key(md)
    art_bytes = md.get("artwork_bytes")
    art_id = md.get("artwork_id")
    sig = (
        track_key,
        str(art_id or ""),
        int(len(art_bytes)) if isinstance(art_bytes, (bytes, bytearray)) else 0,
    )
    have = apple_tv_auto_state.get("music_artwork_bgra")
    if not isinstance(have, np.ndarray) or have.size == 0:
        have = apple_tv_auto_state.get("video_artwork_bgra")
    if (
        apple_tv_auto_state.get("decoded_artwork_sig") == sig
        and isinstance(have, np.ndarray)
        and have.size > 0
    ):
        return
    bgra = _decode_artwork_bytes_bgra(art_bytes)
    apple_tv_auto_state["decoded_artwork_sig"] = sig
    if is_music:
        _clear_video_artwork_cache()
        prev_key = apple_tv_auto_state.get("music_artwork_key")
        if bgra is not None:
            apple_tv_auto_state["music_artwork_bgra"] = bgra
            apple_tv_auto_state["music_artwork_key"] = track_key
            return
        if track_key != prev_key:
            apple_tv_auto_state["music_artwork_bgra"] = None
            apple_tv_auto_state["music_artwork_key"] = track_key
        return
    if is_youtube:
        _clear_music_artwork_cache()
        prev_key = apple_tv_auto_state.get("video_artwork_key")
        if bgra is not None:
            apple_tv_auto_state["video_artwork_bgra"] = bgra
            apple_tv_auto_state["video_artwork_key"] = track_key
            return
        if track_key != prev_key:
            apple_tv_auto_state["video_artwork_bgra"] = None
            apple_tv_auto_state["video_artwork_key"] = track_key
        return
    # Unknown-app landscape art from pyatv is treated as a 16×9 thumb.
    try:
        from pigeon.np_layout import poster_image_is_16x9

        landscape = bool(bgra is not None and poster_image_is_16x9(bgra))
    except Exception:
        landscape = False
    if landscape:
        _clear_music_artwork_cache()
        apple_tv_auto_state["video_artwork_bgra"] = bgra
        apple_tv_auto_state["video_artwork_key"] = track_key
        return
    _clear_playback_artwork_caches()


def _update_status_bar_from_metadata(metadata: dict[str, object] | None, *, _apply_playback_clock_from_poll, _sync_trt_text_to_true_once) -> None:
    if metadata:
        from pigeon.source_status import note_metadata_received

        note_metadata_received()
        _apply_playback_clock_from_poll(metadata)
    # Sync TRT digits to the latest polled integer second. The steady 1 Hz metronome
    # continues stepping from this anchor.
    _sync_trt_text_to_true_once()


def _sync_now_playing_screen_state_for_frame(*, _np_state_sync_mono, _sync_now_playing_screen_state, view_circles_widget) -> None:
    """Throttle NP metadata while live audio widgets are painting at 30 Hz."""
    live = False
    try:
        live = bool(
            view_circles_widget is not None
            and view_circles_widget._live_audio_widgets_on()
        )
    except Exception:
        live = False
    if live:
        t_sync = time.monotonic()
        if t_sync - _np_state_sync_mono[0] < 1.0:
            return
        _np_state_sync_mono[0] = t_sync
    _sync_now_playing_screen_state()


def _clear_now_playing_view_caches(*, view_circles_widget) -> None:
    if view_circles_widget is not None:
        view_circles_widget.clear_cache()


def _playback_display_title(*, active_tmdb_display_title, apple_tv_auto_state) -> str:
    """Best on-screen title: TMDb display name, else Apple TV metadata."""
    if (active_tmdb_display_title[0] or "").strip():
        return str(active_tmdb_display_title[0]).strip()
    lm = apple_tv_auto_state.get("last_metadata")
    if isinstance(lm, dict):
        for key in ("title", "series_name", "query", "artist"):
            s = str(lm.get(key) or "").strip()
            if s:
                return s
    return ""


def _np_drawing_live_audio(*, _clock_saver_for_compose, _view_one_uses_now_playing_screen, view_circles_widget) -> bool:
    """True when NP is actually painting visualizer / VU / levels this frame.

    Capture can stay on for countdown widgets; skip-cache cadence follows
    what is on screen. Now-playing forces ``scene_enabled`` off, so this
    must also drive the scene-off skip key (otherwise the well is 1 Hz).
    """
    if view_circles_widget is None:
        return False
    if not _view_one_uses_now_playing_screen():
        return False
    try:
        if _clock_saver_for_compose(time.monotonic()):
            return False
    except Exception:
        pass
    try:
        return bool(view_circles_widget._live_audio_widgets_on())
    except Exception:
        return False


def _apply_playback_clock_from_poll(metadata: dict[str, object], *, _content_key_from_metadata, apple_tv_playback_clock, last_timecode_motion_mono) -> None:
    """Anchor wall clock to last reported position; polls resync and correct drift."""
    clk = apple_tv_playback_clock
    ds = str(metadata.get("device_state") or "")
    playing_now = "Playing" in ds
    now_m = time.monotonic()
    content_key = _content_key_from_metadata(metadata)
    prev_has_sync = bool(clk.get("has_sync"))
    prev_pos = float(clk.get("sync_position") or 0.0)

    tt_raw = metadata.get("total_time")
    try:
        reported_total = float(tt_raw) if tt_raw is not None else None
    except (TypeError, ValueError):
        reported_total = None
    if reported_total is not None:
        try:
            if float(reported_total) > 0:
                clk["last_reported_total"] = reported_total
        except (TypeError, ValueError):
            pass
    elif content_key and content_key == clk.get("latched_content_key"):
        # pyatv on some paths (often Linux) omits total_time while still reporting position.
        for key in ("latched_total", "last_reported_total"):
            prev = clk.get(key)
            if prev is None:
                continue
            try:
                pf = float(prev)
            except (TypeError, ValueError):
                continue
            if pf > 0:
                reported_total = pf
                break

    pos_raw = metadata.get("position")
    pos_f: float | None = None
    if pos_raw is not None:
        try:
            pos_f = max(0.0, float(pos_raw))
        except (TypeError, ValueError):
            pos_f = None

    # Live/continuous content: playing with no duration and no scrub position.
    live_now = bool(playing_now) and (reported_total is None or reported_total <= 0)
    if live_now and pos_f is not None:
        live_now = False
    if live_now:
        clk["live_mode"] = True
        clk["has_sync"] = False
        clk["latched_total"] = None
        clk["display_played_sec"] = None
        clk["trt_next_fire_mono"] = None
        clk["playing"] = True
        # Still latch content so TMDb artwork doesn't keep swapping.
        if content_key and content_key != clk.get("latched_content_key"):
            clk["latched_content_key"] = content_key
        # Live has no position; metadata fingerprint (title/state) alone
        # decides whether the 2-minute idle saver arms.
        return
    clk["live_mode"] = False

    if content_key and content_key != clk.get("latched_content_key"):
        clk["latched_content_key"] = content_key
        clk["latched_total"] = reported_total
        clk["display_played_sec"] = None
        clk["trt_next_fire_mono"] = None

    if pos_f is not None:
        clk["sync_mono"] = now_m
        clk["sync_position"] = pos_f
        clk["playing"] = playing_now
        clk["has_sync"] = True
        pos_moved = not prev_has_sync or abs(pos_f - prev_pos) >= 0.25
        if playing_now and pos_moved:
            last_timecode_motion_mono[0] = now_m
        # Metadata-idle saver stamp is refreshed via fingerprint (incl. position)
        # in ``_bump_clock_saver_significant_device_from_metadata``.
        return

    if not clk.get("has_sync"):
        clk["playing"] = playing_now
        return

    sp = float(clk["sync_position"])
    sm = float(clk["sync_mono"])
    extrap = sp + (now_m - sm) if clk.get("playing") else sp
    extrap = max(0.0, extrap)
    lt = clk.get("latched_total")
    if lt is not None:
        try:
            extrap = min(extrap, float(lt))
        except (TypeError, ValueError):
            pass
    clk["sync_position"] = extrap
    clk["sync_mono"] = now_m
    clk["playing"] = playing_now
    if playing_now and abs(extrap - sp) >= 0.25:
        last_timecode_motion_mono[0] = now_m


def _sync_status_bar_trt_substantive(*, _trt_substantive_for_status_bar, _warm_status_bar_blits, skip_cache, status_bar_widget) -> None:
    if status_bar_widget is None:
        return
    if status_bar_widget.set_trt_substantive(_trt_substantive_for_status_bar()):
        _warm_status_bar_blits()
        skip_cache[0] = None


def _sync_status_bar_visibility_for_playback(metadata: dict[str, object] | None, *, DisplayView, _atv_metadata_is_content_idle, _effective_display_view, _np_widgets_content_active, _resolve_receiver_lines_for_now_playing, _sync_now_playing_screen_state, _sync_status_bar_trt_substantive, _warm_status_bar_blits, apple_tv_playback_clock, current_apple_tv, skip_cache, status_bar_widget) -> None:
    """Hide now-playing bar + TRT pills when idle; show when content / AVR is live."""
    if status_bar_widget is None:
        return
    if _effective_display_view() == DisplayView.ONE:
        try:
            inc, cfg, _vol = _resolve_receiver_lines_for_now_playing()
        except Exception:
            inc, cfg = "", ""
        show = _np_widgets_content_active(incoming=inc, config=cfg)
    elif not current_apple_tv.get("identifier"):
        show = False
    elif metadata is not None:
        show = not _atv_metadata_is_content_idle(metadata)
    else:
        clk = apple_tv_playback_clock
        show = bool(clk.get("has_sync"))
    if status_bar_widget.set_now_playing_chrome_visible(show):
        _warm_status_bar_blits()
        skip_cache[0] = None
    _sync_status_bar_trt_substantive()
    _sync_now_playing_screen_state()


def _refresh_trt_progress_only(*, _playback_progress_fraction_for_bar, _sync_now_playing_screen_state, _warm_status_bar_blits, skip_cache, status_bar_widget) -> None:
    if status_bar_widget is None:
        return
    pfrac = _playback_progress_fraction_for_bar()
    prog = pfrac if pfrac is not None else 0.0
    if status_bar_widget.set_now_playing_display(progress=prog):
        _warm_status_bar_blits()
        skip_cache[0] = None
    _sync_now_playing_screen_state()


def _refresh_extrapolated_timecodes(*, tick_steps: int = 1, _format_hmmss, _idle_audio_meter_active, _playback_extrapolated_pair, _playback_progress_fraction_for_bar, _sync_status_bar_trt_substantive, _warm_status_bar_blits, apple_tv_playback_clock, skip_cache, status_bar_widget) -> None:
    """Update TRT labels + progress using stepped display time (steady rhythm)."""
    if status_bar_widget is None:
        return
    if _idle_audio_meter_active():
        return
    try:
        clk = apple_tv_playback_clock
        if clk.get("live_mode"):
            if status_bar_widget.set_now_playing_display(
                played_text="LIVE",
                remaining_text="",
                progress=0.0,
            ):
                _warm_status_bar_blits()
                skip_cache[0] = None
            return
        pair = _playback_extrapolated_pair()
        pfrac = _playback_progress_fraction_for_bar()
        if pair is None:
            clk["display_played_sec"] = None
            clk["trt_next_fire_mono"] = None
            if status_bar_widget.set_now_playing_display(progress=0.0):
                _warm_status_bar_blits()
                skip_cache[0] = None
            return
        played_true, _rem_true = pair
        lt_use = clk.get("latched_total")
        if lt_use is None:
            lt_use = clk.get("last_reported_total")
        playing = bool(clk.get("playing"))
        disp = clk.get("display_played_sec")

        if disp is None:
            disp = int(played_true)
        elif not playing:
            disp = int(played_true)
        else:
            pt = int(played_true)
            diff = pt - disp
            # Keep the on-screen cadence steady: at most ±1 per tick for small drift.
            # Snap only for major seeks (e.g. user scrubs).
            if diff >= 10:
                disp = pt
            elif diff > 0:
                disp = min(pt, disp + 1)
            elif diff <= -10:
                disp = pt
            elif diff < 0:
                disp = max(pt, disp - 1)
        clk["display_played_sec"] = disp

        if lt_use is not None:
            try:
                tft = int(round(float(lt_use)))
                remaining_secs = max(0, tft - disp)
            except (TypeError, ValueError):
                remaining_secs = max(0, int(_rem_true) + int(played_true) - disp)
        else:
            remaining_secs = max(0, int(_rem_true) + int(played_true) - disp)

        played_text = _format_hmmss(disp)
        remaining_text = _format_hmmss(remaining_secs)
        prog = pfrac if pfrac is not None else 0.0
        if status_bar_widget.set_now_playing_display(
            played_text=played_text,
            remaining_text=remaining_text,
            progress=prog,
        ):
            _warm_status_bar_blits()
            skip_cache[0] = None
    finally:
        _sync_status_bar_trt_substantive()


def _warm_status_bar_blits(*, status_bar_blits, status_bar_widget) -> None:
    if status_bar_widget is None:
        status_bar_blits[0] = []
        return
    status_bar_blits[0] = list(status_bar_widget.design_blits())


def _has_playback_position(*, _playback_progress_fraction_for_bar) -> bool:
    """True when zone5 can draw a real progress bar (not LIVE / empty)."""
    return _playback_progress_fraction_for_bar() is not None


def _metadata_activity_fingerprint(md: dict[str, object], *, _coarse_device_state_for_saver, _content_key_from_metadata) -> str:
    """Content/playback signature for the 2-minute metadata-idle saver.

    Volume is excluded (receiver/ATV level noise must not reset the timer).
    Position is only included while Playing so Idle/home None↔0 flaps are ignored.
    TMDb art presence is ignored.
    """
    ck = _content_key_from_metadata(md) or ""
    ds = _coarse_device_state_for_saver(str(md.get("device_state") or ""))
    title = str(md.get("title") or "").strip().lower()
    artist = str(md.get("artist") or "").strip().lower()
    album = str(md.get("album") or "").strip().lower()
    series = str(md.get("series_name") or "").strip().lower()
    app = str(md.get("app_name") or md.get("app") or "").strip().lower()
    app_id = str(md.get("app_id") or "").strip().lower()
    query = str(md.get("query") or "").strip().lower()
    pos_tok = ""
    if ds == "playing":
        pos_raw = md.get("position")
        if pos_raw is not None:
            try:
                pos_tok = f"{int(max(0.0, float(pos_raw)) * 4.0)}"
            except (TypeError, ValueError):
                pos_tok = ""
    return "|".join(
        (ck, ds, title, artist, album, series, app, app_id, query, pos_tok)
    )


_last_player_class_log: list = [None]


def _log_player_metadata_class(cls, md, paused, playing, rem, clk) -> None:
    """Log each change of the ok/stopped/absent class with the inputs behind it."""
    md = md if isinstance(md, dict) else {}
    key = (
        cls,
        str(md.get("device_state") or ""),
        bool(paused),
        bool(playing),
        bool(md.get("playback_concluded")),
    )
    if _last_player_class_log[0] == key:
        return
    _last_player_class_log[0] = key
    import sys

    sys.stderr.write(
        f"pigeon: player_class={cls} device_state={md.get('device_state')!r} "
        f"paused_overlay={bool(paused)} playing={bool(playing)} "
        f"concluded_flag={bool(md.get('playback_concluded'))} "
        f"remaining={rem if rem is None else round(float(rem), 1)} "
        f"title={str(md.get('title') or md.get('query') or '')[:40]!r} "
        f"identity_source={md.get('identity_source')!r} "
        f"held={bool(md.get('identity_held_across_idle'))} "
        f"clock_sync={bool(clk.get('has_sync'))} clock_playing={bool(clk.get('playing'))} "
        f"total={clk.get('latched_total') or clk.get('last_reported_total')}\n"
    )


def _player_metadata_class(*, _playback_extrapolated_pair, _show_paused_row_overlay, _something_playing_now, apple_tv_auto_state, apple_tv_playback_clock) -> str:
    """Same ok/stopped/absent class auto widgets use for the live layout."""
    lm = apple_tv_auto_state.get("last_metadata")
    md = lm if isinstance(lm, dict) else None
    try:
        from pigeon.auto_widgets import classify_player_metadata

        rem = None
        try:
            from pigeon.display_confidence import remaining_seconds

            rem = remaining_seconds(md)
        except Exception:
            rem = None
        if rem is None:
            pair = _playback_extrapolated_pair()
            clk = apple_tv_playback_clock
            has_total = (
                clk.get("latched_total") is not None
                or clk.get("last_reported_total") is not None
            )
            if pair is not None and has_total:
                rem = float(pair[1])
        paused_now = _show_paused_row_overlay()
        playing_now = _something_playing_now()
        cls = classify_player_metadata(
            md,
            paused=paused_now,
            playing=playing_now,
            remaining_s=rem,
        )
        _log_player_metadata_class(cls, md, paused_now, playing_now, rem, apple_tv_playback_clock)
        return cls
    except Exception:
        from pigeon.auto_widgets import METADATA_ABSENT, METADATA_OK, METADATA_STOPPED

        ds = str((md or {}).get("device_state") or "")
        if _show_paused_row_overlay() or "Paused" in ds or "Stopped" in ds:
            return METADATA_STOPPED
        if md and (
            str(md.get("title") or "").strip() or str(md.get("query") or "").strip()
        ):
            return METADATA_OK
        return METADATA_ABSENT


def _sync_now_playing_screen_state(*, DisplayView, _active_tmdb_tt_src_bgra, _atv_metadata_is_content_idle, _circles_poster_bgra, _effective_display_view, _format_hmmss, _has_playback_position, _np_dump_mono, _np_widgets_content_active, _paused_screen_backdrop_bgr, _pausesaver_is_holding, _playback_extrapolated_pair, _playback_progress_fraction_for_bar, _refresh_paused_row_stamp, _resolve_receiver_input_label, _resolve_receiver_lines_for_now_playing, _show_paused_row_overlay, _spawn_youtube_thumb_fetch, _vv_is_music, _vv_is_youtube, active_tmdb_display_title, active_tmdb_title_key, apple_tv_auto_state, apple_tv_playback_clock, receiver_standby_holder, skip_cache, streaming_badge_state, view_circles_widget) -> None:
    if view_circles_widget is None:
        return
    try:
        from pigeon.hdmi_capture import probe_hdmi_presence

        # HDMI probe grabs a capture frame on a worker; numpy on that
        # frame holds the GIL and hitchs live widgets every ~1.5 s.
        probe_hdmi_presence()
    except Exception:
        pass
    prog = _playback_progress_fraction_for_bar()
    progress = float(prog) if prog is not None else 0.0
    remaining_text = ""
    played_text = ""
    clk = apple_tv_playback_clock
    if clk.get("live_mode"):
        remaining_text = "LIVE"
        played_text = "LIVE"
    else:
        pair = _playback_extrapolated_pair()
        if pair is not None:
            played_text = _format_hmmss(int(pair[0]))
            remaining_text = _format_hmmss(int(pair[1]))
    inc, cfg, vol = _resolve_receiver_lines_for_now_playing()
    recv_input = _resolve_receiver_input_label()
    circles_poster_bgra = _circles_poster_bgra()
    has_np = _effective_display_view() == DisplayView.ONE
    sb = streaming_badge_state
    badge_label = str(sb.get("label") or "").strip()
    changed = False
    vol_frac = 0.0
    try:
        from pigeon.widgets.playback_overlay import volume_fraction_from_display_line

        vol_frac = float(volume_fraction_from_display_line(vol))
    except Exception:
        vol_frac = 0.0
    try:
        from pigeon.runtime_state import update_receiver_runtime

        update_receiver_runtime(
            incoming=inc,
            config=cfg,
            volume=vol,
            volume_fraction=vol_frac,
            muted=vol.strip().lower() in ("mute", "muted", "off"),
        )
    except Exception:
        pass
    circles_paused = bool(_show_paused_row_overlay())
    circles_service = badge_label
    if not circles_service:
        lm_svc = apple_tv_auto_state.get("last_metadata")
        if isinstance(lm_svc, dict):
            circles_service = str(lm_svc.get("app_name") or "").strip()
    yt_now = bool(_vv_is_youtube())
    video_art = apple_tv_auto_state.get("video_artwork_bgra")
    if (
        not yt_now
        and isinstance(video_art, np.ndarray)
        and video_art.size > 0
    ):
        try:
            from pigeon.np_layout import poster_image_is_16x9

            yt_now = bool(poster_image_is_16x9(video_art))
        except Exception:
            yt_now = False
    if yt_now and "youtube" not in str(circles_service or "").lower():
        circles_service = "YouTube"
    if yt_now:
        try:
            _spawn_youtube_thumb_fetch()
        except Exception:
            pass
    np_active = _np_widgets_content_active(incoming=inc, config=cfg)
    recv_name = ""
    try:
        _avr_row = read_saved_av_receiver()
        if isinstance(_avr_row, dict):
            recv_name = str(
                _avr_row.get("name") or _avr_row.get("label") or ""
            ).strip()
    except Exception:
        recv_name = ""
    if not str(circles_service or "").strip() and inc:
        circles_service = inc
    svc_l = str(circles_service or "").strip().casefold()
    recv_l = recv_name.casefold()
    if svc_l and recv_l and (svc_l == recv_l or svc_l in recv_l or recv_l in svc_l):
        circles_service = ""
    if _vv_is_music():
        lm_music = apple_tv_auto_state.get("last_metadata")
        song_t = album_t = artist_t = ""
        if isinstance(lm_music, dict):
            song_t = str(lm_music.get("title") or "").strip()
            album_t = str(lm_music.get("album") or "").strip()
            artist_t = str(lm_music.get("artist") or "").strip()
            # Match classic music text: promote album when title is empty.
            if not song_t and album_t:
                song_t, album_t = album_t, ""
        if view_circles_widget.update_state(
            progress=progress,
            elapsed_text=played_text,
            remaining_text=remaining_text,
            volume_text=vol,
            volume_fraction=vol_frac,
            incoming_audio=inc,
            playback_config=cfg,
            cast=[],
            poster_bgra=circles_poster_bgra,
            has_now_playing=has_np,
            searching=False,
            missing_art=False,
            content_mode="music",
            song_title=song_t,
            album_title=album_t,
            artist_title=artist_t,
            paused=circles_paused,
            service_name=circles_service,
            has_position=_has_playback_position(),
            content_active=np_active,
            is_youtube=False,
            tt_bgra=circles_poster_bgra,
            tt_title=song_t,
            backdrop_bgr=_paused_screen_backdrop_bgr(),
            receiver_name=recv_name,
            receiver_input=recv_input,
            has_receiver=(
                not bool(receiver_standby_holder[0])
                and bool(recv_name or recv_input or inc or cfg or vol)
            ),
        ):
            changed = True
    else:
        cast_rows: list[tuple[str, str]] = []
        try:
            from pigeon.tmdb_poster import get_cached_tmdb_cast

            tk = str(active_tmdb_title_key[0] or "").strip()
            if tk:
                cast_rows = get_cached_tmdb_cast(tk)
        except Exception:
            cast_rows = []
        fetch_busy = bool(
            apple_tv_auto_state.get("tmdb_fetch_in_flight")
            or apple_tv_auto_state.get("pending_tmdb")
        )
        missing_art = bool(apple_tv_auto_state.get("tmdb_missing_art"))
        song_t = album_t = artist_t = ""
        if yt_now:
            fetch_busy = bool(apple_tv_auto_state.get("youtube_thumb_in_flight"))
            missing_art = False
            cast_rows = []
            lm_yt = apple_tv_auto_state.get("last_metadata")
            if isinstance(lm_yt, dict):
                song_t = str(lm_yt.get("title") or "").strip()
                artist_t = str(lm_yt.get("artist") or "").strip()
                album_t = str(lm_yt.get("album") or "").strip()
                if not song_t:
                    try:
                        from pigeon.apple_tv_now_playing import (
                            youtube_title_from_metadata,
                        )

                        song_t = youtube_title_from_metadata(lm_yt)
                    except Exception:
                        song_t = ""
                if not song_t and album_t:
                    song_t, album_t = album_t, ""
        tt_src = None
        try:
            tt_src = _active_tmdb_tt_src_bgra()
        except Exception:
            tt_src = None
        atv_title = ""
        if not yt_now:
            lm_vid = apple_tv_auto_state.get("last_metadata")
            if isinstance(lm_vid, dict) and not _atv_metadata_is_content_idle(lm_vid):
                atv_title = str(
                    lm_vid.get("title")
                    or lm_vid.get("query")
                    or ""
                ).strip()
        tt_fallback = (
            str(active_tmdb_display_title[0] or "").strip() or song_t or atv_title
        )
        if view_circles_widget.update_state(
            progress=progress,
            elapsed_text=played_text,
            remaining_text=remaining_text,
            volume_text=vol,
            volume_fraction=vol_frac,
            incoming_audio=inc,
            playback_config=cfg,
            cast=cast_rows,
            poster_bgra=circles_poster_bgra,
            has_now_playing=has_np,
            searching=fetch_busy and not missing_art,
            missing_art=missing_art and not fetch_busy,
            content_mode="video",
            song_title=song_t if yt_now else "",
            album_title=album_t if yt_now else "",
            artist_title=artist_t if yt_now else "",
            paused=circles_paused,
            service_name=circles_service,
            has_position=_has_playback_position(),
            content_active=np_active,
            is_youtube=yt_now,
            tt_bgra=tt_src,
            tt_title=tt_fallback,
            backdrop_bgr=_paused_screen_backdrop_bgr(),
            receiver_name=recv_name,
            receiver_input=recv_input,
            has_receiver=(
                not bool(receiver_standby_holder[0])
                and bool(recv_name or recv_input or inc or cfg or vol)
            ),
        ):
            changed = True
    if changed:
        skip_cache[0] = None
    try:
        t_dump = time.monotonic()
        if t_dump - _np_dump_mono[0] >= 5.0:
            _np_dump_mono[0] = t_dump
            lm = apple_tv_auto_state.get("last_metadata")
            lm_d = lm if isinstance(lm, dict) else {}
            st = view_circles_widget._state if view_circles_widget is not None else None
            from pigeon.auto_widgets import live_plan as _dump_live_plan

            _dump_plan = _dump_live_plan()
            Path("/tmp/pigeon-np-zones.json").write_text(
                json.dumps(
                    {
                        "title_key": active_tmdb_title_key[0],
                        "display_title": active_tmdb_display_title[0],
                        "tt_title": getattr(st, "tt_title", None),
                        "cast_n": len(getattr(st, "cast", None) or []),
                        "cast0": (getattr(st, "cast", None) or [None])[0],
                        "has_position": bool(getattr(st, "has_position", False)),
                        "remaining": getattr(st, "remaining_text", ""),
                        "incoming": getattr(st, "incoming", ""),
                        "config": getattr(st, "config", ""),
                        "input": getattr(st, "receiver_input", ""),
                        "service": getattr(st, "service_name", ""),
                        "mode": getattr(st, "content_mode", ""),
                        "youtube": bool(getattr(st, "is_youtube", False)),
                        "searching": bool(getattr(st, "searching", False)),
                        "md_state": str(lm_d.get("device_state") or ""),
                        "md_title": str(lm_d.get("title") or ""),
                        "md_query": str(lm_d.get("query") or ""),
                        "md_app": str(lm_d.get("app_name") or ""),
                        "layout": getattr(_dump_plan, "layout", None),
                        "pause_age": round(
                            float(_refresh_paused_row_stamp(t_dump)), 1
                        ),
                        "pausesaver_hold": bool(_pausesaver_is_holding()),
                        "assignments": list(view_circles_widget._assignments())
                        if view_circles_widget is not None
                        else [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
    except Exception:
        pass


def _circles_poster_bgra(*, _active_tmdb_poster_bgra, _vv_is_music, _vv_is_youtube, apple_tv_auto_state) -> np.ndarray | None:
    """Poster slot for view_circles — poster art only (no backdrop fill)."""
    if _vv_is_music():
        bgra = apple_tv_auto_state.get("music_artwork_bgra")
        if isinstance(bgra, np.ndarray) and bgra.size > 0:
            return bgra
        return None
    if _vv_is_youtube():
        bgra = apple_tv_auto_state.get("video_artwork_bgra")
        if isinstance(bgra, np.ndarray) and bgra.size > 0:
            return bgra
        return None
    bgra = apple_tv_auto_state.get("video_artwork_bgra")
    if isinstance(bgra, np.ndarray) and bgra.size > 0:
        try:
            from pigeon.np_layout import poster_image_is_16x9

            if poster_image_is_16x9(bgra):
                return bgra
        except Exception:
            pass
    if apple_tv_auto_state.get("tmdb_fetch_in_flight") or apple_tv_auto_state.get(
        "pending_tmdb"
    ):
        return None
    return _active_tmdb_poster_bgra()


def _spawn_youtube_thumb_fetch(*, _store_music_artwork_from_metadata, _sync_now_playing_screen_state, apple_tv_auto_state, render_once, root, skip_cache) -> None:
    """Fill zone 6 from YouTube's CDN when pyatv artwork() is empty."""
    bgra = apple_tv_auto_state.get("video_artwork_bgra")
    if isinstance(bgra, np.ndarray) and bgra.size > 0:
        return
    if apple_tv_auto_state.get("youtube_thumb_in_flight"):
        return
    md_raw = apple_tv_auto_state.get("last_metadata")
    md = dict(md_raw) if isinstance(md_raw, dict) else {}
    try:
        from pigeon.apple_tv_now_playing import (
            download_youtube_thumbnail_bytes,
            youtube_thumb_identity,
            youtube_title_from_metadata,
            youtube_video_id_from_metadata,
        )
    except Exception:
        return
    if not youtube_video_id_from_metadata(md) and not youtube_title_from_metadata(md):
        return
    key = youtube_thumb_identity(md)
    if not key or key == apple_tv_auto_state.get("youtube_thumb_key"):
        return
    apple_tv_auto_state["youtube_thumb_in_flight"] = True

    def worker() -> None:
        raw: bytes | None = None
        try:
            raw = download_youtube_thumbnail_bytes(md)
        except Exception:
            raw = None

        def finish() -> None:
            apple_tv_auto_state["youtube_thumb_in_flight"] = False
            apple_tv_auto_state["youtube_thumb_key"] = key
            if raw:
                art_md = dict(md)
                art_md["artwork_bytes"] = raw
                try:
                    _store_music_artwork_from_metadata(art_md)
                except Exception:
                    pass
            try:
                _sync_now_playing_screen_state()
            except Exception:
                pass
            skip_cache[0] = None
            try:
                render_once()
            except Exception:
                pass

        try:
            root.after(0, finish)
        except Exception:
            finish()

    threading.Thread(target=worker, daemon=True, name="youtube-thumb").start()


def _content_key_from_metadata(metadata: dict[str, object], *, _tmdb_pref_from_metadata, resolve_metadata_tmdb_query) -> str | None:
    pyatv_q = str(metadata.get("query") or "").strip()
    if resolve_metadata_tmdb_query is not None:
        query = pyatv_q or resolve_metadata_tmdb_query(metadata)
    else:
        query = pyatv_q
    if not query:
        return None
    prefer = _tmdb_pref_from_metadata(metadata)
    title = str(metadata.get("title") or "").strip()
    try:
        from pigeon.raw_title import (
            _title_looks_like_episode_in_metadata,
            raw_title_from_metadata_dict,
        )
        from pigeon.tmdb_poster import is_degenerate_tmdb_query

        rt = raw_title_from_metadata_dict(metadata)
        if _title_looks_like_episode_in_metadata(metadata, rt):
            for key in ("album", "series_name", "artist"):
                val = str(metadata.get(key) or "").strip()
                if val and not is_degenerate_tmdb_query(val):
                    title = val
                    break
    except ImportError:
        pass
    return "|".join((query, prefer, title))


def _sync_trt_text_to_true_once(*, _format_hmmss, _playback_extrapolated_pair, _playback_progress_fraction_for_bar, _refresh_trt_progress_only, _sync_status_bar_trt_substantive, _warm_status_bar_blits, apple_tv_playback_clock, skip_cache, status_bar_widget) -> None:
    """Set TRT text to the latest polled integer second (used to recover from missed metronome ticks)."""
    try:
        if status_bar_widget is None:
            return
        clk = apple_tv_playback_clock
        if clk.get("live_mode"):
            # Live: digits are suppressed; show LIVE.
            if status_bar_widget.set_now_playing_display(
                played_text="LIVE",
                remaining_text="",
                progress=0.0,
            ):
                _warm_status_bar_blits()
                skip_cache[0] = None
            return

        pair = _playback_extrapolated_pair()
        if pair is None:
            return
        played_true, rem_true = pair
        disp_true = int(played_true)

        # If we're already showing this second, avoid touching TRT text cadence.
        disp_cur = clk.get("display_played_sec")
        if disp_cur is not None and int(disp_cur) == disp_true:
            _refresh_trt_progress_only()
            return

        clk["display_played_sec"] = disp_true
        played_text = _format_hmmss(disp_true)
        remaining_text = _format_hmmss(int(rem_true))
        pfrac = _playback_progress_fraction_for_bar()
        prog = pfrac if pfrac is not None else 0.0
        if status_bar_widget.set_now_playing_display(
            played_text=played_text,
            remaining_text=remaining_text,
            progress=prog,
        ):
            _warm_status_bar_blits()
            skip_cache[0] = None
    finally:
        _sync_status_bar_trt_substantive()


def _playback_ui_tick(*, _idle_audio_meter_active, _playback_ui_tick, _refresh_content_indicator, _refresh_extrapolated_timecodes, apple_tv_playback_clock, root) -> None:
    try:
        clk = apple_tv_playback_clock
        now_m = time.monotonic()
        nf = clk.get("trt_next_fire_mono")
        if nf is None:
            nf = now_m + 1.0
            clk["trt_next_fire_mono"] = nf
        nf = float(nf)
        tick_steps = 0
        while nf <= now_m and tick_steps < 12:
            nf += 1.0
            tick_steps += 1
        if tick_steps == 0:
            root.after(max(1, int(round((nf - now_m) * 1000))), _playback_ui_tick)
            return
        clk["trt_next_fire_mono"] = nf
        if not _idle_audio_meter_active():
            _refresh_extrapolated_timecodes(tick_steps=tick_steps)
            _refresh_content_indicator()
        now2 = time.monotonic()
        next_nf_raw = clk.get("trt_next_fire_mono")
        if next_nf_raw is None:
            next_nf_raw = now2 + 1.0
            clk["trt_next_fire_mono"] = next_nf_raw
        next_nf = float(next_nf_raw)
        delay_ms = max(1, min(120_000, int(round((next_nf - now2) * 1000))))
        root.after(delay_ms, _playback_ui_tick)
    except Exception:
        # Never let TRT tick crashes take down the UI loop (discovery/pairing run on Tk too).
        try:
            clk = apple_tv_playback_clock
            clk["trt_next_fire_mono"] = time.monotonic() + 1.0
        except Exception:
            pass
        root.after(1000, _playback_ui_tick)


def _sync_streaming_badge_from_playback_sources(
    md: dict[str, object] | None,
    *,
    roku_app_name: str | None = None,
    _PROJECT_DIR, _apply_netflix_backdrop_when_running, _atv_metadata_is_content_idle, _idle_audio_meter_active, _warm_playback_overlay_blits, playback_overlay_widget, render_once, skip_cache, streaming_badge_state,
) -> None:
    """Streaming-service badge: pyatv metadata when present, else Roku ECP active-app name."""
    if playback_overlay_widget is None:
        return
    from pigeon.streaming_service_badges import resolve_streaming_badge_media

    assets = Path(_PROJECT_DIR) / "pigeonAssets"
    prev_show = bool(streaming_badge_state.get("show"))
    prev_filename = str(streaming_badge_state.get("filename") or "")
    prev_label = str(streaming_badge_state.get("label") or "")
    show = False
    filename = ""
    label = ""
    md_active = md is not None and not _atv_metadata_is_content_idle(md)
    pyatv_app = False
    if md_active:
        an = str(md.get("app_name") or "").strip()
        bid = str(md.get("app_id") or "").strip()
        pyatv_app = bool(an or bid)
        if pyatv_app:
            fn, label = resolve_streaming_badge_media(
                assets,
                app_name=an,
                app_id=bid,
            )
            if fn or label:
                show = True
                filename = fn or ""
    if not show and roku_app_name and str(roku_app_name).strip():
        ra = str(roku_app_name).strip()
        fn, label = resolve_streaming_badge_media(
            assets,
            app_name=ra,
            app_id="",
        )
        if fn or label:
            show = True
            filename = fn or ""
    if not show and md_active:
        fn, label = resolve_streaming_badge_media(
            assets,
            app_name=str(md.get("app_name") or ""),
            app_id=str(md.get("app_id") or ""),
        )
        if fn or label:
            show = True
            filename = fn or ""
    if not show and isinstance(md, dict):
        an = str(md.get("app_name") or "").strip()
        bid = str(md.get("app_id") or "").strip()
        if an or bid:
            fn, label = resolve_streaming_badge_media(
                assets,
                app_name=an,
                app_id=bid,
            )
            if fn or label:
                show = True
                filename = fn or ""
    streaming_badge_state["show"] = show
    streaming_badge_state["filename"] = filename
    streaming_badge_state["label"] = label
    if (
        prev_show == show
        and prev_filename == filename
        and prev_label == label
    ):
        return
    if _idle_audio_meter_active():
        return
    _warm_playback_overlay_blits()
    skip_cache[0] = None
    _apply_netflix_backdrop_when_running()
    try:
        render_once()
    except Exception:
        pass


def _metadata_debug_provider(*, _content_indicator_ok, _tmdb_info_current_and_available, _view_four_display_metadata, apple_tv_auto_state, apple_tv_playback_clock, streaming_badge_state) -> dict[str, object]:
    """Rows for the [4] metadata inspector (player / hdmi / pigeon pages)."""
    from pigeon.hdmi_capture import hdmi_capture_available

    lm = _view_four_display_metadata() or {}
    try:
        player_active = bool(_content_indicator_ok())
    except Exception:
        player_active = False
    try:
        hdmi_active = bool(hdmi_capture_available())
    except Exception:
        hdmi_active = False

    rt = None
    if lm:
        try:
            from pigeon.raw_title import raw_title_from_metadata_dict

            rt = raw_title_from_metadata_dict(lm)
        except Exception:
            rt = None

    def _rt(field: str) -> str:
        return str(getattr(rt, field, "") or "").strip() if rt is not None else ""

    # --- player: network metadata exactly as the box broadcasts it ---
    p_title = str(lm.get("title") or "").strip()
    p_series = str(lm.get("series_name") or "").strip()
    is_tv = bool(p_series) or "tv" in _rt("media_type_label").casefold()
    if is_tv and not p_series:
        # layer_series_title falls back to the plain title for movies,
        # so only trust it once we know this is episodic content.
        p_series = _rt("layer_series_title")
    p_episode = (
        (_rt("raw_episode_title") or _rt("layer_episode_title") or p_title)
        if is_tv
        else p_title
    )
    player_rows = {
        "service": str(lm.get("app_name") or "").strip(),
        "series": p_series,
        "title": p_title,
        "episode": p_episode,
    }

    # --- hdmi: signal only (LED). HDMI no longer supplies metadata
    # since OCR was retired, so every field stays blank.
    hdmi_rows = {
        "service": "",
        "series": "",
        "title": "",
        "episode": "",
        "year": "",
    }

    # --- pigeon: the final verdict (search terms + confidence) ---
    refined = str(
        apple_tv_auto_state.get("last_tmdb_fetch_refined")
        or apple_tv_auto_state.get("last_tmdb_fetch_input")
        or ""
    ).strip()
    g_title = refined or _rt("raw_query") or p_title
    g_year = ""
    try:
        from pigeon.tmdb_poster import split_query_and_year

        cleaned, year = split_query_and_year(g_title)
        if cleaned:
            g_title = cleaned.strip()
        if year:
            g_year = str(year)
    except Exception:
        pass
    g_series = p_series
    g_episode = ""
    se_i, ep_i = getattr(rt, "season_index", None), getattr(rt, "episode_index", None)
    if is_tv:
        g_episode = _rt("layer_episode_title") or _rt("raw_episode_title")
        if not g_episode and se_i is not None and ep_i is not None:
            g_episode = f"S{se_i} E{ep_i}"
    g_episode = g_episode or g_title
    svc_label = str(streaming_badge_state.get("label") or "").strip()
    pigeon_rows: dict[str, object] = {
        "service": svc_label or player_rows["service"],
        "series": g_series,
        "title": g_title,
        "episode": g_episode,
        "year": g_year,
    }
    try:
        from pigeon.title_decision import decision_from_metadata

        why = decision_from_metadata(lm) or str(
            apple_tv_auto_state.get("last_title_decision") or ""
        ).strip()
        if why:
            pigeon_rows["decision"] = why
    except Exception:
        pass
    try:
        from pigeon.display_confidence import scores_for_metadata
        from pigeon.tmdb_poster import last_trt_comparison

        clk = apple_tv_playback_clock
        advancing = bool(clk.get("has_sync") and clk.get("playing"))
        trt_cmp = last_trt_comparison()
        scores = scores_for_metadata(
            lm,
            position_advancing=advancing,
            tmdb_matches=bool(_tmdb_info_current_and_available()),
            hdmi_present=hdmi_capture_available(),
            player_duration_s=trt_cmp.get("player_s"),
            tmdb_runtime_s=trt_cmp.get("tmdb_s"),
        )
        pigeon_rows["confidence"] = {
            "service": scores.get("app"),
            "series": scores.get("identity"),
            "title": scores.get("identity"),
            "episode": scores.get("position"),
            "year": scores.get("art"),
            "trt": scores.get("trt"),
        }
    except Exception:
        pigeon_rows["confidence"] = {}

    return {
        "player": player_rows,
        "hdmi": hdmi_rows,
        "pigeon": pigeon_rows,
        "player_active": player_active,
        "hdmi_active": hdmi_active,
    }


def _enable_now_playing_screen(*, DisplayView, LANDING_DISPLAY_BRIGHTNESS, _PIGEON_EXT, _sync_status_bar_visibility_for_playback, apple_tv_auto_state, brightness_current, brightness_from, brightness_target, display_view_holder, last_frame, scene_enabled, skip_cache, view_circles_widget) -> None:
    """Show View 1 now-playing chrome (circles skin). Idempotent."""
    if not _PIGEON_EXT or view_circles_widget is None:
        return
    display_view_holder[0] = DisplayView.ONE
    # View 1 chrome composites without a video ``last_frame``; keep scene off so
    # ``render_once`` does not early-return before painting the now-playing screen.
    scene_enabled[0] = False
    last_frame[0] = None
    brightness_current[0] = brightness_from[0] = brightness_target[0] = LANDING_DISPLAY_BRIGHTNESS
    md_sb = apple_tv_auto_state.get("last_metadata")
    _sync_status_bar_visibility_for_playback(
        md_sb if isinstance(md_sb, dict) else None
    )
    skip_cache[0] = None


def _np_wants_live_audio(*, _clock_saver_for_compose, _view_one_uses_now_playing_screen, view_circles_widget_holder) -> bool:
    if view_circles_widget_holder[0] is None:
        return False
    if not _view_one_uses_now_playing_screen():
        return False
    try:
        if _clock_saver_for_compose(time.monotonic()):
            return False
    except Exception:
        pass
    try:
        return bool(view_circles_widget_holder[0].wants_live_audio())
    except Exception:
        return False
