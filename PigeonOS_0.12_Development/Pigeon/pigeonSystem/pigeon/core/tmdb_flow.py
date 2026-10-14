"""TMDb lookup flow: spawn identity, match quality overlays, command parsing.

Extracted verbatim from ``bootstrap()`` in ``pigeon_0_12.py``. Each function
takes the app state it used to close over as keyword-only arguments;
``bootstrap()`` binds them once with ``bind_deps`` so call sites are unchanged.
"""

from __future__ import annotations

import re
import time
import tkinter as tk
import cv2
import numpy as np
from pigeon.app_state import read_app_state
from pigeon.runtime_paths import pigeon_state_dir
import sys
from pigeon.app_state import write_app_state
import tkinter.messagebox as messagebox
from pigeon.tmdb_tt_contrast import pick_gradient_bgr
import threading


def _trigger_tmdb_quality_toggle_overlay(mode: str, *, tmdb_quality_overlay_mode, tmdb_quality_overlay_t0) -> None:
    tmdb_quality_overlay_mode[0] = str(mode or "")
    tmdb_quality_overlay_t0[0] = time.monotonic()


def _tmdb_quality_toggle_overlay_state(
    now_mono: float,
    *,
    tmdb_quality_overlay_mode,
    tmdb_quality_overlay_t0,
) -> tuple[tuple[int, int, int], float, str, int]:
    """Return (BGR color, alpha, caption, phase_key) for the toggle-confirmation X overlay."""
    mode = str(tmdb_quality_overlay_mode[0] or "")
    if mode not in ("flag", "undo"):
        return ((255, 255, 255), 0.0, "", 0)
    t0 = float(tmdb_quality_overlay_t0[0] or 0.0)
    dt = max(0.0, now_mono - t0)
    hold_primary = 1.0
    hold_secondary = 3.0
    fade_s = 0.8
    total = hold_primary + hold_secondary + fade_s
    if dt >= total:
        tmdb_quality_overlay_mode[0] = ""
        return ((255, 255, 255), 0.0, "", 0)
    if mode == "flag":
        c1 = (255, 255, 255)  # white first
        c2 = (0, 0, 255)  # red second
        text = "TMDB ERROR FLAGGED"
    else:
        c1 = (0, 0, 255)  # red first
        c2 = (255, 255, 255)  # white second
        text = "TMDB ERROR REPORT UNDONE"
    if dt < hold_primary:
        return (c1, 1.0, text, 1)
    if dt < (hold_primary + hold_secondary):
        return (c2, 1.0, text, 2)
    fade_t = (dt - hold_primary - hold_secondary) / max(1e-6, fade_s)
    alpha = max(0.0, 1.0 - float(fade_t))
    return (c2, alpha, text, 3)


def _blend_tmdb_quality_toggle_overlay(
    frame_bgr: np.ndarray,
    *,
    color_bgr: tuple[int, int, int],
    alpha: float,
    caption: str,
) -> None:
    if frame_bgr is None or frame_bgr.size == 0:
        return
    a = max(0.0, min(1.0, float(alpha)))
    if a <= 1e-6:
        return
    h, w = int(frame_bgr.shape[0]), int(frame_bgr.shape[1])
    if h < 8 or w < 8:
        return
    overlay = frame_bgr.copy()
    margin = max(16, int(round(min(w, h) * 0.24)))
    x0, y0 = margin, margin
    x1, y1 = max(x0 + 1, w - margin), max(y0 + 1, h - margin)
    thick = max(6, int(round(min(w, h) * 0.02)))
    cv2.line(overlay, (x0, y0), (x1, y1), color_bgr, thickness=thick, lineType=cv2.LINE_AA)
    cv2.line(overlay, (x0, y1), (x1, y0), color_bgr, thickness=thick, lineType=cv2.LINE_AA)
    if caption:
        fs = max(0.7, min(2.6, float(min(w, h)) / 520.0))
        txt_th = max(1, int(round(thick * 0.35)))
        tw, th = cv2.getTextSize(caption, cv2.FONT_HERSHEY_SIMPLEX, fs, txt_th)[0]
        tx = max(8, (w - tw) // 2)
        ty = min(h - 10, y1 + max(22, int(round(0.08 * h))))
        cv2.putText(
            overlay,
            caption,
            (tx, ty),
            cv2.FONT_HERSHEY_SIMPLEX,
            fs,
            color_bgr,
            txt_th,
            cv2.LINE_AA,
        )
    cv2.addWeighted(overlay, a, frame_bgr, 1.0 - a, 0.0, dst=frame_bgr)


def _blend_tmdb_quality_flag_badge(frame_bgr: np.ndarray) -> None:
    """Persistent bottom-right red X while the TMDb quality flag is active."""
    if frame_bgr is None or frame_bgr.size == 0:
        return
    h, w = int(frame_bgr.shape[0]), int(frame_bgr.shape[1])
    if h < 16 or w < 16:
        return
    size = max(16, int(round(min(w, h) * 0.06)))
    pad = max(10, int(round(min(w, h) * 0.025)))
    x1 = w - pad
    y1 = h - pad
    x0 = max(0, x1 - size)
    y0 = max(0, y1 - size)
    thick = max(2, int(round(size * 0.22)))
    # Draw directly on the destination frame to avoid per-tick full-frame copies.
    cv2.line(frame_bgr, (x0, y0), (x1, y1), (0, 0, 255), thickness=thick, lineType=cv2.LINE_AA)
    cv2.line(frame_bgr, (x0, y1), (x1, y0), (0, 0, 255), thickness=thick, lineType=cv2.LINE_AA)


def parse_tmdb_command_phrase(phrase: str) -> tuple[str, str]:
    """Return (query, prefer) with prefer one of auto | movie | tv."""
    p = phrase.strip()
    m_tv = re.match(r"(?i)^tv\s+(.+)$", p)
    if m_tv:
        return m_tv.group(1).strip(), "tv"
    m_mov = re.match(r"(?i)^movie\s+(.+)$", p)
    if m_mov:
        return m_mov.group(1).strip(), "movie"
    return p, "auto"


def _escape_log_field(s: str | None) -> str:
    return (s or "").replace("\\", "\\\\").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _clear_tmdb_missing_art(*, apple_tv_auto_state, tmdb_error_flag_retry_active) -> None:
    apple_tv_auto_state["tmdb_missing_art"] = False
    apple_tv_auto_state["tmdb_exhausted_identity"] = None
    tmdb_error_flag_retry_active[0] = False


def _cancel_tmdb_quality_auto_unlog_timer(*, root, tmdb_quality_auto_unlog_after_id) -> None:
    aid = tmdb_quality_auto_unlog_after_id[0]
    if aid:
        try:
            root.after_cancel(aid)
        except tk.TclError:
            pass
    tmdb_quality_auto_unlog_after_id[0] = None


def _tmdb_match_tier_acceptable(query: str, tier: int) -> bool:
    try:
        from pigeon.tmdb_poster import _literal_min_acceptable_tier
    except ImportError:
        return int(tier) >= 4
    return int(tier) >= int(_literal_min_acceptable_tier(query))


def _format_tmdb_match_quality_glance(s: int, f: int) -> str:
    tot = s + f
    if tot <= 0:
        return "TMDb match quality  —  no scored events yet"
    ok_pct = 100.0 * float(s) / float(tot)
    return f"TMDb match quality   {s} ok   {f} fail   {tot} events   {ok_pct:.0f}% ok"


def _refresh_match_quality_glance_label() -> None:
    # Legacy Tk glance label — unused with settings_main.
    return


def _tmdb_duration_bucket(*, _player_duration_for_tmdb) -> int | None:
    dur = _player_duration_for_tmdb()
    if dur is None:
        return None
    return int(round(float(dur) / 120.0))


def _tmdb_spawn_identity(query: str, prefer: str, *, _tmdb_duration_bucket) -> tuple[str, str, int | None]:
    try:
        from pigeon.tmdb_poster import refine_tmdb_search_query

        refined = refine_tmdb_search_query(query) or str(query or "").strip()
    except ImportError:
        refined = str(query or "").strip()
    pref = str(prefer or "auto").strip().lower()
    if pref not in ("auto", "tv", "movie"):
        pref = "auto"
    return (refined, pref, _tmdb_duration_bucket())


def _tmdb_spawn_identity_changed(
    query: str,
    prefer: str,
    metadata: dict[str, object] | None = None,
    *,
    prev_content_key: object | None = None,
    _content_key_from_metadata,
    _tmdb_spawn_identity,
    apple_tv_auto_state,
) -> bool:
    """True when this poll should start a new TMDb worker (equivalent-aware).

    ``prev_content_key`` must be the content_key from *before* this poll
    updates ``apple_tv_auto_state["content_key"]``. Reading the live state
    key here poisons the title-suffix guard (prev and new look identical).
    """
    new_id = _tmdb_spawn_identity(query, prefer)
    prev = apple_tv_auto_state.get("tmdb_key")
    if prev == new_id:
        return False
    if prev and isinstance(prev, tuple) and len(prev) >= 2:
        prev_bucket = prev[2] if len(prev) > 2 else None
        new_bucket = new_id[2] if len(new_id) > 2 else None
        if prev_bucket != new_bucket:
            return True
        try:
            from pigeon.tmdb_poster import equivalent_tmdb_search_queries

            pq, pp = str(prev[0]), str(prev[1])
            if pp == new_id[1] and equivalent_tmdb_search_queries(new_id[0], pq):
                return False
            # HBO/Max: pyatv query may alternate show name vs episode title while
            # candidates still cover the same series — do not re-fetch every poll.
            if metadata is not None:
                from pigeon.raw_title import tmdb_query_candidates_from_metadata

                for cand in tmdb_query_candidates_from_metadata(metadata):
                    if equivalent_tmdb_search_queries(cand, pq):
                        return False
                # Prefer the caller-supplied prior key; fall back only if missing.
                prev_ck = str(
                    prev_content_key
                    if prev_content_key is not None
                    else apple_tv_auto_state.get("content_key")
                    or ""
                )
                new_ck = _content_key_from_metadata(metadata) or ""
                if prev_ck and new_ck and prev_ck == new_ck:
                    return False
                if prev_ck and new_ck:
                    pt = prev_ck.rsplit("|", 1)[-1]
                    nt = new_ck.rsplit("|", 1)[-1]
                    if pt and pt == nt:
                        return False
        except ImportError:
            pass
    return True


def _tmdb_pref_from_metadata(metadata: dict[str, object]) -> str:
    prefer = str(metadata.get("prefer") or "auto").strip().lower()
    if prefer not in ("auto", "tv", "movie"):
        prefer = "auto"
    try:
        from pigeon.tmdb_poster import prefer_media_for_streaming_service

        prefer = prefer_media_for_streaming_service(
            prefer,
            app_name=str(metadata.get("app_name") or "") or None,
            app_id=str(metadata.get("app_id") or "") or None,
        )
    except ImportError:
        pass
    return prefer


def _append_tmdb_quality_event_report_log(
    *,
    outcome: str,
    title_key: str | None,
    display_title: str | None,
    msg_m: str,
    _escape_log_field, apple_tv_auto_state, streaming_badge_state,
) -> None:
    """Append one scored TMDb quality event line (SUCCESS/FAILURE) with metadata context."""
    log_p = pigeon_state_dir() / "tmdb_quality_event_reports.log"
    log_p.parent.mkdir(parents=True, exist_ok=True)
    md_raw = apple_tv_auto_state.get("last_metadata")
    raw_bits: list[str] = []
    app_bits: list[str] = []
    if isinstance(md_raw, dict):
        app_name = str(md_raw.get("app_name") or "").strip()
        app_id = str(md_raw.get("app_id") or "").strip()
        if app_name:
            app_bits.append(f'app_name="{_escape_log_field(app_name)}"')
        if app_id:
            app_bits.append(f'app_id="{_escape_log_field(app_id)}"')
        try:
            from pigeon.raw_title import raw_title_from_metadata_dict

            rt = raw_title_from_metadata_dict(md_raw)
            if (rt.raw_title or "").strip():
                raw_bits.append(f'raw_title="{_escape_log_field(rt.raw_title)}"')
            if (rt.raw_series_name or "").strip():
                raw_bits.append(f'raw_series_name="{_escape_log_field(rt.raw_series_name)}"')
            if (rt.raw_query or "").strip():
                raw_bits.append(f'raw_query="{_escape_log_field(rt.raw_query)}"')
            if (rt.raw_episode_title or "").strip():
                raw_bits.append(f'raw_episode_title="{_escape_log_field(rt.raw_episode_title)}"')
            if (rt.layer_series_title or "").strip():
                raw_bits.append(f'layer_series_title="{_escape_log_field(rt.layer_series_title)}"')
            if not raw_bits:
                raw_bits.append("(rawTitle layers empty for this snapshot)")
        except Exception:
            t_fallback = str(md_raw.get("title") or "").strip()
            q_fallback = str(md_raw.get("query") or "").strip()
            raw_bits.append(
                f'fallback_title="{_escape_log_field(t_fallback)}" query="{_escape_log_field(q_fallback)}"'
            )
    else:
        raw_bits.append("(no last_metadata dict)")
    sb_label = str(streaming_badge_state.get("label") or "").strip()
    sb_filename = str(streaming_badge_state.get("filename") or "").strip()
    if sb_label:
        app_bits.append(f'streaming_service_label="{_escape_log_field(sb_label)}"')
    if sb_filename:
        app_bits.append(f'streaming_service_badge="{_escape_log_field(sb_filename)}"')
    if not app_bits:
        app_bits.append("(streaming_service unknown)")
    fetch_head = (msg_m or "").split("::", 1)[0].strip()
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    out_u = str(outcome or "").strip().upper()
    if out_u not in ("SUCCESS", "FAILURE"):
        out_u = "UNKNOWN"
    line = (
        f"{ts}\t{out_u}\t"
        f'tmdb_title_key="{_escape_log_field(title_key or "")}"\t'
        f'display_title="{_escape_log_field(display_title or "")}"\t'
        f'fetch_summary_head="{_escape_log_field(fetch_head)}"\t'
        f"{' '.join(app_bits)}\t"
        f"{' '.join(raw_bits)}\n"
    )
    with log_p.open("a", encoding="utf-8") as lf:
        lf.write(line)
    try:
        from pigeon.tmdb_desktop_report import append_tmdb_quality_row

        append_tmdb_quality_row(
            outcome=out_u,
            title_key=title_key,
            display_title=display_title,
            fetch_summary_head=fetch_head,
            app_streaming_context=" ".join(app_bits),
            raw_title_context=" ".join(raw_bits),
        )
    except Exception:
        pass
    if out_u == "FAILURE":
        try:
            from pigeon.tmdb_desktop_report import append_tmdb_error_event

            append_tmdb_error_event(
                last_metadata=md_raw if isinstance(md_raw, dict) else None,
                streaming_badge_state=streaming_badge_state,
            )
        except Exception:
            pass


def _mark_tmdb_missing_art(*, identity: object | None = None, apple_tv_auto_state, tmdb_error_flag_retry_active) -> None:
    """Stop empty-display poll respawns and show the circles '?' placeholder."""
    apple_tv_auto_state["tmdb_missing_art"] = True
    if identity is not None:
        apple_tv_auto_state["tmdb_exhausted_identity"] = identity
        apple_tv_auto_state["tmdb_key"] = identity
    tmdb_error_flag_retry_active[0] = False
    try:
        sys.stderr.write(
            "pigeon: TMDb give-up — showing missing-art placeholder (no further auto-retries).\n"
        )
        sys.stderr.flush()
    except Exception:
        pass


def _adjust_tmdb_quality_failure_delta(delta: int, *, _PIGEON_EXT, _refresh_match_quality_glance_label, match_quality_glance_sig) -> None:
    """Persist ±1 failure immediately (⌘⇧X flag on / undo); refreshes Settings glance."""
    if not _PIGEON_EXT or int(delta) == 0:
        return
    try:
        st = read_app_state()
        s = int(st.get("tmdb_quality_successes", 0) or 0)
        f = max(0, int(st.get("tmdb_quality_failures", 0) or 0) + int(delta))
        write_app_state(tmdb_quality_successes=s, tmdb_quality_failures=f)
        match_quality_glance_sig[0] = ""
        _refresh_match_quality_glance_label()
    except Exception:
        pass


def on_reset_tmdb_match_quality_stats(*, _PIGEON_EXT, _refresh_match_quality_glance_label, match_quality_glance_sig) -> None:
    """Zero the Settings success/fail counters (state.json only). Logs and desktop reports unchanged."""
    if not _PIGEON_EXT:
        return
    try:
        write_app_state(tmdb_quality_successes=0, tmdb_quality_failures=0)
        match_quality_glance_sig[0] = ""
        _refresh_match_quality_glance_label()
    except Exception:
        pass


def _active_tmdb_poster_bgra(*, _tmdb_poster_cache, active_tmdb_title_key) -> np.ndarray | None:
    """Return cached TMDb *poster* BGRA for the active title key (or ``None``).

    Tries the active key, then a year-stripped alias — Apple TV raw titles often
    keep ``(YYYY)`` while assets are stored under the clean TMDb display name.
    Never falls back to backdrop art (circles poster slot is poster-only).
    """
    if not active_tmdb_title_key[0]:
        return None
    try:
        from pigeon.media_cache import ASSET_POSTER_ART, find_cached_reformatted_asset_recent
        from pigeon.image_ui_protocol import load_image_bgra
        from pigeon.tmdb_poster import split_query_and_year
    except Exception:
        return None
    keys: list[str] = []
    tk0 = str(active_tmdb_title_key[0]).strip()
    if tk0:
        keys.append(tk0)
    try:
        cleaned, _year = split_query_and_year(tk0)
        cleaned = (cleaned or "").strip()
        if cleaned and cleaned not in keys:
            keys.append(cleaned)
    except Exception:
        pass
    poster_path = None
    for tk in keys:
        poster_path = find_cached_reformatted_asset_recent(tk, ASSET_POSTER_ART)
        if poster_path is not None and poster_path.is_file():
            break
        poster_path = None
    if poster_path is None:
        return None
    try:
        mtime = poster_path.stat().st_mtime
    except OSError:
        return None
    key = (str(poster_path), float(mtime))
    if _tmdb_poster_cache.get("key") == key:
        hit = _tmdb_poster_cache.get("bgra")
        return hit if isinstance(hit, np.ndarray) else None
    raw = load_image_bgra(poster_path)
    if raw is None or raw.size == 0:
        _tmdb_poster_cache["key"] = key
        _tmdb_poster_cache["bgra"] = None
        return None
    _tmdb_poster_cache["key"] = key
    _tmdb_poster_cache["bgra"] = raw
    return raw


def _active_tmdb_tt_src_bgra(*, _tmdb_tt_src_cache, active_tmdb_display_title, active_tmdb_title_key) -> np.ndarray | None:
    """Return cached TMDb title-treatment (LogoEn) BGRA, or ``None``.

    Logo art only — no text fallback and no streaming-app logo substitute.
    Tries the active key, then a year-stripped alias.
    """
    if not active_tmdb_title_key[0]:
        return None
    try:
        from pigeon.media_cache import (
            ASSET_LOGO,
            ASSET_LOGO_EN,
            find_cached_reformatted_asset_recent,
            title_key as tmdb_title_key,
        )
        from pigeon.image_ui_protocol import load_image_bgra
        from pigeon.tmdb_poster import split_query_and_year
    except Exception:
        return None
    keys: list[str] = []
    tk0 = str(active_tmdb_title_key[0]).strip()
    if tk0:
        keys.append(tk0)
    disp = str(active_tmdb_display_title[0] or "").strip()
    if disp:
        try:
            tk_disp = (tmdb_title_key(disp) or "").strip()
        except Exception:
            tk_disp = ""
        if tk_disp and tk_disp not in keys:
            keys.append(tk_disp)
    try:
        cleaned, _year = split_query_and_year(tk0)
        cleaned = (cleaned or "").strip()
        if cleaned and cleaned not in keys:
            keys.append(cleaned)
    except Exception:
        pass
    logo_path = None
    for tk in keys:
        for asset in (ASSET_LOGO_EN, ASSET_LOGO):
            logo_path = find_cached_reformatted_asset_recent(tk, asset)
            if logo_path is not None and logo_path.is_file():
                break
            logo_path = None
        if logo_path is not None:
            break
    if logo_path is None:
        return None
    try:
        mtime = logo_path.stat().st_mtime
    except OSError:
        return None
    key = (str(logo_path), float(mtime))
    if _tmdb_tt_src_cache.get("key") == key:
        hit = _tmdb_tt_src_cache.get("bgra")
        return hit if isinstance(hit, np.ndarray) else None
    raw = load_image_bgra(logo_path)
    if raw is None or raw.size == 0:
        _tmdb_tt_src_cache["key"] = key
        _tmdb_tt_src_cache["bgra"] = None
        return None
    _tmdb_tt_src_cache["key"] = key
    _tmdb_tt_src_cache["bgra"] = raw
    return raw


def _vv_has_tmdb_tt(*, active_tmdb_title_key) -> bool:
    return bool(active_tmdb_title_key[0])


def _perform_tmdb_artwork_retry(*, _PIGEON_EXT, _alternate_tmdb_query_from_metadata, _append_tmdb_retry_log_ui, _tmdb_retry_log_append, active_tmdb_display_title, active_tmdb_title_key, apple_tv_auto_state, apple_tv_playback_clock, spawn_tmdb_poster_fetch, tmdb_retry_rule_idx) -> None:
    if not _PIGEON_EXT:
        return
    rules = [
        ("movie", "primary", "movie+primary"),
        ("tv", "primary", "tv+primary"),
        ("auto", "alternate", "auto+alternate_query"),
        ("auto", "primary", "auto+primary"),
    ]
    idx = tmdb_retry_rule_idx[0] % len(rules)
    prefer, qsource, rule_id = rules[idx]
    primary = str(apple_tv_auto_state.get("query") or "").strip()
    md_raw = apple_tv_auto_state.get("last_metadata")
    md = md_raw if isinstance(md_raw, dict) else {}
    alt = _alternate_tmdb_query_from_metadata(md if md else None, primary)
    if qsource == "primary":
        q = primary
    else:
        q = (alt or primary).strip()
    if not q:
        messagebox.showwarning(
            "TMDb retry",
            "No playback search query yet. Play something on the device and wait for metadata, "
            "or type a query in the command bar (tmdb …).",
        )
        return
    tmdb_retry_rule_idx[0] = idx + 1
    entry = {
        "event": "tmdb_retry_hotkey",
        "rule_index": idx,
        "rule_id": rule_id,
        "prefer": prefer,
        "query_source": qsource,
        "query_sent": q,
        "primary_query": primary,
        "alternate_available": bool(alt),
        "alternate_query": alt,
        "active_tmdb_title_key_before": active_tmdb_title_key[0],
        "active_tmdb_display_title_before": active_tmdb_display_title[0],
        "apple_tv_auto_prefer": apple_tv_auto_state.get("prefer"),
        "content_key": apple_tv_auto_state.get("content_key"),
        "live_mode": apple_tv_playback_clock.get("live_mode"),
        "metadata_excerpt": {
            k: md.get(k)
            for k in ("title", "artist", "series_name", "media_type", "inferred_prefer", "device_state")
            if md.get(k)
        },
    }
    _tmdb_retry_log_append(entry)
    ts = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
    was = active_tmdb_display_title[0] or "—"
    _append_tmdb_retry_log_ui(f"{ts}  {rule_id}  prefer={prefer}  q={q!r}  was={was!r}")
    # Manual "?" / retry hotkey clears give-up so this attempt can run.
    apple_tv_auto_state["tmdb_missing_art"] = False
    apple_tv_auto_state["tmdb_exhausted_identity"] = None
    spawn_tmdb_poster_fetch(q, prefer=prefer, force=True)
    sys.stderr.write(f"pigeon: tmdb retry ({rule_id}) prefer={prefer} q={q!r}\n")
    sys.stderr.flush()


def submit_command_entry(_event=None, *, DevPhase, DisplayView, _PIGEON_EXT, _bump_pigeon_user_activity, _last_command_submit_mono, command_entry, dev_phase, display_view_holder, hide_command_entry, parse_tmdb_command_phrase, spawn_tmdb_poster_fetch) -> str:
    if dev_phase[0] != DevPhase.GRID and display_view_holder[0] != DisplayView.FIVE:
        return "break"
    _bump_pigeon_user_activity()
    now_sub = time.monotonic()
    if now_sub - _last_command_submit_mono[0] < 0.2:
        return "break"
    _last_command_submit_mono[0] = now_sub
    text = command_entry.get().strip()
    key = text.lower()
    if text and _PIGEON_EXT:
        m_tmdb = re.match(r"(?i)tmdb\s+(?P<q>.+)$", text)
        if m_tmdb:
            qrest = m_tmdb.group("q").strip()
            if qrest:
                q2, pref = parse_tmdb_command_phrase(qrest)
                if q2:
                    spawn_tmdb_poster_fetch(q2, prefer=pref, force=True)
            else:
                sys.stderr.write("pigeon: tmdb: empty query (use: tmdb Movie Title)\n")
                sys.stderr.flush()
        else:
            # Plain title or tv/movie hint — TMDb (auto picks movie vs TV by popularity)
            q2, pref = parse_tmdb_command_phrase(text)
            if q2:
                spawn_tmdb_poster_fetch(q2, prefer=pref, force=True)
    elif text:
        sys.stderr.write(f"pigeon: command: {text}\n")
        sys.stderr.flush()
    command_entry.delete(0, tk.END)
    hide_command_entry()
    return "break"


def hide_command_entry(_event=None, *, command_bar, command_entry_visible, label) -> None:
    command_entry_visible[0] = False
    command_bar.place_forget()
    try:
        label.focus_set()
    except tk.TclError:
        pass


def show_command_entry(_event=None, *, DevPhase, DisplayView, command_bar, command_entry, command_entry_visible, dev_phase, display_view_holder, place_command_bar, root) -> None:
    if dev_phase[0] != DevPhase.GRID and display_view_holder[0] != DisplayView.FIVE:
        return
    command_entry_visible[0] = True
    place_command_bar()
    command_bar.lift()
    command_entry.focus_set()

    def _focus_cmd() -> None:
        try:
            command_entry.focus_force()
        except tk.TclError:
            try:
                command_entry.focus_set()
            except tk.TclError:
                pass

    root.after_idle(_focus_cmd)


def on_return_overlay_command(event: tk.Event, *, DevPhase, DisplayView, _PIGEON_EXT, _bump_pigeon_user_activity, _widget_accepts_typing, apple_tv_busy, command_entry, command_entry_visible, current_apple_tv, dev_phase, display_view_holder, show_command_entry, streaming_slot_holder) -> str | None:
    _bump_pigeon_user_activity(event)
    w = event.widget
    if w == command_entry or str(w) == str(command_entry):
        return None
    if _widget_accepts_typing(w):
        return None
    if dev_phase[0] == DevPhase.GRID or display_view_holder[0] == DisplayView.FIVE:
        if command_entry_visible[0]:
            try:
                command_entry.focus_force()
            except tk.TclError:
                command_entry.focus_set()
        else:
            show_command_entry()
        return "break"
    if _PIGEON_EXT:
        from pigeon.player_remote import queue_player_remote_action

        queue_player_remote_action(
            streaming_slot_holder[0],
            current_apple_tv=current_apple_tv,
            action="select",
            apple_tv_busy=apple_tv_busy,
        )
        return "break"
    return None


def _schedule_tmdb_quality_auto_expire(*, TMDB_QUALITY_UNLOG_WINDOW_S, _cancel_tmdb_quality_auto_unlog_timer, root, skip_cache, tmdb_quality_auto_unlog_after_id, tmdb_quality_error_flag) -> None:
    _cancel_tmdb_quality_auto_unlog_timer()
    delay_ms = int(round(TMDB_QUALITY_UNLOG_WINDOW_S * 1000.0))

    def _expire() -> None:
        tmdb_quality_auto_unlog_after_id[0] = None
        if tmdb_quality_error_flag[0]:
            tmdb_quality_error_flag[0] = False
            skip_cache[0] = None

    tmdb_quality_auto_unlog_after_id[0] = root.after(delay_ms, _expire)


def on_tmdb_quality_error_report_hotkey(event: tk.Event, *, TMDB_QUALITY_UNLOG_WINDOW_S, _PIGEON_EXT, _adjust_tmdb_quality_failure_delta, _append_tmdb_quality_event_report_log, _bump_pigeon_user_activity, _clear_tmdb_quality_flag, _last_tmdb_quality_report_mono, _perform_tmdb_error_flag_retry, _schedule_tmdb_quality_auto_expire, _trigger_tmdb_quality_toggle_overlay, _widget_accepts_typing, active_tmdb_display_title, active_tmdb_title_key, apple_tv_auto_state, skip_cache, tmdb_error_flag_retry_active, tmdb_error_flag_retry_rule_idx, tmdb_quality_error_flag, tmdb_quality_flag_set_mono) -> str | None:
    """Flag TMDb artwork error (⌘⇧X); log immediately, retry fetch, 20s undo window.

    Bound only to Control/Command+Shift+X, so trust the binding — Wayland/X11
    often omits modifier bits from ``event.state`` after the combo is matched.
    """
    _bump_pigeon_user_activity(event)
    if not _PIGEON_EXT:
        return None
    if _widget_accepts_typing(event.widget):
        return None
    ks = (getattr(event, "keysym", "") or "").lower()
    if ks not in ("x",):
        return None
    now_q = time.monotonic()
    if now_q - _last_tmdb_quality_report_mono[0] < 0.15:
        return "break"
    _last_tmdb_quality_report_mono[0] = now_q
    if tmdb_quality_error_flag[0]:
        elapsed = now_q - float(tmdb_quality_flag_set_mono[0] or 0.0)
        if elapsed <= TMDB_QUALITY_UNLOG_WINDOW_S:
            _clear_tmdb_quality_flag(undo=True, show_overlay=True)
            skip_cache[0] = None  # force redraw so undo X appears immediately
            try:
                sys.stderr.write(
                    "pigeon: TMDb quality flag undone within 20s window (⌘⇧X).\n"
                )
                sys.stderr.flush()
            except Exception:
                pass
            return "break"
        _clear_tmdb_quality_flag(undo=False, show_overlay=False)
    tmdb_quality_error_flag[0] = True
    tmdb_quality_flag_set_mono[0] = now_q
    _adjust_tmdb_quality_failure_delta(1)
    _trigger_tmdb_quality_toggle_overlay("flag")
    skip_cache[0] = None  # force redraw so confirmation X appears immediately
    try:
        _append_tmdb_quality_event_report_log(
            outcome="FAILURE",
            title_key=active_tmdb_title_key[0],
            display_title=active_tmdb_display_title[0],
            msg_m="user_flagged",
        )
    except Exception:
        pass
    try:
        from pigeon.accuracy_report import report_flag

        report_flag(display_title=active_tmdb_display_title[0])
    except Exception:
        pass
    # One full rule cycle only (auto-chained on failure in finish_tmdb).
    tmdb_error_flag_retry_active[0] = True
    tmdb_error_flag_retry_rule_idx[0] = 0
    apple_tv_auto_state["tmdb_missing_art"] = False
    apple_tv_auto_state["tmdb_exhausted_identity"] = None
    _perform_tmdb_error_flag_retry()
    _schedule_tmdb_quality_auto_expire()
    try:
        sys.stderr.write(
            "pigeon: TMDb material quality issue flagged (⌘⇧X). "
            "Logged immediately; retrying TMDb fetch; undo available for 20s.\n"
        )
        sys.stderr.flush()
    except Exception:
        pass
    return "break"


def _clear_tmdb_quality_flag(*, undo: bool, show_overlay: bool, _adjust_tmdb_quality_failure_delta, _cancel_tmdb_quality_auto_unlog_timer, _trigger_tmdb_quality_toggle_overlay, skip_cache, tmdb_quality_error_flag) -> None:
    if tmdb_quality_error_flag[0] and undo:
        _adjust_tmdb_quality_failure_delta(-1)
    tmdb_quality_error_flag[0] = False
    _cancel_tmdb_quality_auto_unlog_timer()
    if show_overlay:
        _trigger_tmdb_quality_toggle_overlay("undo")
    skip_cache[0] = None


def _refresh_tmdb_tt_gradient_tint(*, active_tmdb_display_title, active_tmdb_title_key, tmdb_logo_patch_bgra, tmdb_tt_gradient_bgr_holder) -> None:
    """Evaluate TT brightness and pick the bottom-gradient tint (black vs white).

    Runs every time ``_warm_tmdb_logo_patch`` refreshes the cached TT patch. Falls
    back to the legacy dark gradient when no TT is available.
    """
    prev = tmdb_tt_gradient_bgr_holder[0]
    chosen, lum = pick_gradient_bgr(tmdb_logo_patch_bgra[0])
    tmdb_tt_gradient_bgr_holder[0] = chosen
    if chosen != prev:
        label = "white" if chosen == (255, 255, 255) else "black"
        title = active_tmdb_display_title[0] or active_tmdb_title_key[0] or "(no-title)"
        lum_s = f"{lum:.3f}" if lum is not None else "n/a"
        print(
            f"pigeon: TT contrast → {label} gradient (luminance={lum_s}, title={title!r})",
            file=sys.stderr,
        )


def _perform_tmdb_error_flag_retry(*, TMDB_ERROR_FLAG_RETRY_RULES, _PIGEON_EXT, _alternate_tmdb_query_from_metadata, _clear_now_playing_view_caches, _mark_tmdb_missing_art, _raw_title_query_from_metadata, _sync_now_playing_screen_state, _tmdb_retry_log_append, _tmdb_spawn_identity, _view_one_uses_now_playing_screen, apple_tv_auto_state, render_once, skip_cache, spawn_tmdb_poster_fetch, tmdb_error_flag_retry_active, tmdb_error_flag_retry_rule_idx) -> None:
    """Second-chance TMDb fetch when the user flags bad artwork (⌘⇧X).

    Runs at most one full pass of ``TMDB_ERROR_FLAG_RETRY_RULES`` (auto-chained
    from ``finish_tmdb`` on failure). After the cycle is exhausted, marks
    missing art so the circles poster shows "?" instead of respawning forever.
    """
    if not _PIGEON_EXT:
        return
    rules = TMDB_ERROR_FLAG_RETRY_RULES
    if not tmdb_error_flag_retry_active[0]:
        return
    idx = int(tmdb_error_flag_retry_rule_idx[0])
    if idx >= len(rules):
        primary = str(apple_tv_auto_state.get("query") or "").strip()
        prefer_ex = str(apple_tv_auto_state.get("prefer") or "auto")
        _mark_tmdb_missing_art(
            identity=_tmdb_spawn_identity(primary, prefer_ex) if primary else None
        )
        if _view_one_uses_now_playing_screen():
            _clear_now_playing_view_caches()
            _sync_now_playing_screen_state()
        skip_cache[0] = None
        try:
            render_once()
        except Exception:
            pass
        return
    prefer, qsource, rule_id = rules[idx]
    primary = str(apple_tv_auto_state.get("query") or "").strip()
    md_raw = apple_tv_auto_state.get("last_metadata")
    md = md_raw if isinstance(md_raw, dict) else {}
    alt = _alternate_tmdb_query_from_metadata(md if md else None, primary)
    raw_q = _raw_title_query_from_metadata(md if md else None)
    if qsource == "raw_title":
        q = (raw_q or primary).strip()
    elif qsource == "alternate":
        q = (alt or raw_q or primary).strip()
    else:
        q = primary
    if not q:
        _mark_tmdb_missing_art(identity=None)
        return
    apple_tv_auto_state["tmdb_missing_art"] = False
    tmdb_error_flag_retry_rule_idx[0] = idx + 1
    _tmdb_retry_log_append(
        {
            "event": "tmdb_error_flag_retry",
            "rule_index": idx,
            "rule_id": rule_id,
            "prefer": prefer,
            "query_source": qsource,
            "query_sent": q,
            "primary_query": primary,
            "raw_title_query": raw_q,
            "alternate_available": bool(alt),
            "alternate_query": alt,
        }
    )
    spawn_tmdb_poster_fetch(q, prefer=prefer, force=True)
    sys.stderr.write(
        f"pigeon: tmdb error-flag retry ({rule_id}) prefer={prefer} q={q!r}\n"
    )
    sys.stderr.flush()


def _warm_tmdb_logo_patch(*, _active_tmdb_logo_widget, _refresh_tmdb_tt_gradient_tint, _resolve_streaming_app_logo_bgra, active_tmdb_display_title, active_tmdb_title_key, tmdb_logo_app_fallback_active, tmdb_logo_patch_bgra) -> None:
    logo_w = _active_tmdb_logo_widget()
    if logo_w is None:
        tmdb_logo_patch_bgra[0] = None
        _refresh_tmdb_tt_gradient_tint()
        return
    patch_wh = None
    if active_tmdb_title_key[0]:
        tmdb_logo_patch_bgra[0] = logo_w.bgra_patch_for_title(
            active_tmdb_title_key[0],
            display_title=active_tmdb_display_title[0],
            patch_wh=patch_wh,
        ).copy()
        _refresh_tmdb_tt_gradient_tint()
        return
    if tmdb_logo_app_fallback_active[0]:
        src = _resolve_streaming_app_logo_bgra()
        if src is not None:
            tmdb_logo_patch_bgra[0] = logo_w.bgra_patch_from_source_bgra(
                src,
                patch_wh=patch_wh,
            ).copy()
            _refresh_tmdb_tt_gradient_tint()
            return
    tmdb_logo_patch_bgra[0] = None
    _refresh_tmdb_tt_gradient_tint()


def _vv_has_tmdb_bd(*, backdrop_app_logo_letterbox_fit, backdrop_master_bgr, saved_backdrop_app_logo_letterbox_fit, saved_backdrop_master_bgr) -> bool:
    # A real TMDb backdrop — NOT the app-logo letterbox fallback that
    # reuses ``backdrop_master_bgr`` as a black-canvas app-logo strip.
    if backdrop_master_bgr[0] is not None and not backdrop_app_logo_letterbox_fit[0]:
        return True
    if (
        saved_backdrop_master_bgr[0] is not None
        and not saved_backdrop_app_logo_letterbox_fit[0]
    ):
        return True
    return False


def _clear_displayed_tmdb_art_for_content_change(*, _clear_now_playing_view_caches, _sync_now_playing_screen_state, _tmdb_poster_cache, _tmdb_tt_src_cache, _view_one_uses_now_playing_screen, _warm_tmdb_logo_patch, active_tmdb_display_title, active_tmdb_title_key, apple_tv_auto_state, backdrop_master_bgr, skip_cache, tmdb_error_flag_retry_active, tmdb_error_flag_retry_rule_idx, tmdb_logo_app_fallback_active, tmdb_logo_patch_bgra, tmdb_logo_widget, tmdb_logo_widget_view_six) -> None:
    """Drop on-screen TMDb art/cast when the playing title changes.

    Clears the active title key and live backdrop master so circles/classic
    stop showing the prior poster/cast. Leaves ``saved_backdrop_master_bgr``
    for classic scene restore after a full idle. Resets ``tmdb_key`` so the
    next spawn is not suppressed as “same identity”.
    """
    active_tmdb_title_key[0] = None
    active_tmdb_display_title[0] = None
    tmdb_logo_app_fallback_active[0] = False
    backdrop_master_bgr[0] = None
    try:
        from pigeon.paused_screen import set_pausesaver_backdrop

        set_pausesaver_backdrop(None, clear=True)
    except Exception:
        pass
    apple_tv_auto_state["tmdb_key"] = None
    apple_tv_auto_state["tmdb_missing_art"] = False
    apple_tv_auto_state["tmdb_exhausted_identity"] = None
    tmdb_error_flag_retry_active[0] = False
    tmdb_error_flag_retry_rule_idx[0] = 0
    _tmdb_poster_cache["key"] = None
    _tmdb_poster_cache["bgra"] = None
    _tmdb_tt_src_cache["key"] = None
    _tmdb_tt_src_cache["bgra"] = None
    if tmdb_logo_widget is not None:
        tmdb_logo_widget.clear_cache()
    if tmdb_logo_widget_view_six is not None:
        tmdb_logo_widget_view_six.clear_cache()
    tmdb_logo_patch_bgra[0] = None
    _warm_tmdb_logo_patch()
    if _view_one_uses_now_playing_screen():
        _clear_now_playing_view_caches()
        _sync_now_playing_screen_state()
    skip_cache[0] = None


def _apply_rawtitle_text_tt_fallback(*, active_tmdb_display_title, active_tmdb_title_key, apple_tv_auto_state, tmdb_logo_app_fallback_active) -> bool:
    try:
        from pigeon.raw_title import raw_title_from_metadata_dict
        from pigeon.tmdb_poster import title_key
    except ImportError:
        return False
    md = apple_tv_auto_state.get("last_metadata")
    if not isinstance(md, dict):
        return False
    rt = raw_title_from_metadata_dict(md)
    raw = (rt.raw_title or "").strip()
    if not raw:
        return False
    # TT/display can use the Apple TV raw label, but do not replace an existing
    # TMDb media key — poster/cast are cached under the clean match title
    # (e.g. ``Game Night``), while raw often keeps ``(YYYY)``.
    if not active_tmdb_title_key[0]:
        active_tmdb_title_key[0] = title_key(raw)
    active_tmdb_display_title[0] = raw
    tmdb_logo_app_fallback_active[0] = False
    return True


def _tmdb_info_current_and_available(*, _tmdb_spawn_identity, active_tmdb_title_key, apple_tv_auto_state) -> bool:
    """True when live TMDb art/title matches the current show and is ready."""
    if apple_tv_auto_state.get("tmdb_missing_art"):
        return False
    if apple_tv_auto_state.get("tmdb_fetch_in_flight"):
        return False
    if not str(active_tmdb_title_key[0] or "").strip():
        return False
    md = apple_tv_auto_state.get("last_metadata")
    query = ""
    if isinstance(md, dict):
        query = str(md.get("query") or "").strip()
    if not query:
        query = str(apple_tv_auto_state.get("query") or "").strip()
    if not query:
        return False
    try:
        from pigeon.tmdb_poster import is_degenerate_tmdb_query

        if is_degenerate_tmdb_query(query):
            return False
    except Exception:
        pass
    prev = apple_tv_auto_state.get("tmdb_key")
    if not prev:
        return True
    prefer = str(apple_tv_auto_state.get("prefer") or "auto")
    new_id = _tmdb_spawn_identity(query, prefer)
    if prev == new_id:
        return True
    if isinstance(prev, tuple) and len(prev) >= 2:
        prev_bucket = prev[2] if len(prev) > 2 else None
        new_bucket = new_id[2] if len(new_id) > 2 else None
        if prev_bucket != new_bucket:
            return False
        try:
            from pigeon.tmdb_poster import equivalent_tmdb_search_queries

            if equivalent_tmdb_search_queries(str(prev[0]), new_id[0]):
                return True
        except Exception:
            pass
    return False


def _streaming_service_label(apple_tv_auto_state, streaming_badge_state) -> str:
    lab = str((streaming_badge_state or {}).get("label") or "").strip()
    if lab:
        return lab
    md = apple_tv_auto_state.get("last_metadata")
    if isinstance(md, dict):
        return str(md.get("app_name") or md.get("app_id") or "").strip()
    return ""


def _report_live_state(
    state: str,
    *,
    apple_tv_auto_state,
    streaming_badge_state,
    query: str = "",
    refined_query: str = "",
    prefer: str = "",
) -> None:
    """Now-playing snapshot for the Mac accuracy report's live view."""
    try:
        from pigeon.accuracy_report import report_live

        md = apple_tv_auto_state.get("last_metadata")
        report_live(
            state=state,
            metadata=md if isinstance(md, dict) else None,
            streaming_service=_streaming_service_label(
                apple_tv_auto_state, streaming_badge_state
            ),
            query=query,
            refined_query=refined_query,
            prefer=prefer,
        )
    except Exception:
        pass


def spawn_tmdb_poster_fetch(
    query: str, *, prefer: str = "auto", force: bool = False
, BACKDROP_BRIGHTNESS, TMDB_ERROR_FLAG_RETRY_RULES, _PIGEON_EXT, _append_tmdb_quality_event_report_log, _apply_netflix_backdrop_when_running, _apply_rawtitle_text_tt_fallback, _backdrop_master_from_streaming_app_logo, _cancel_tmdb_quality_auto_unlog_timer, _clear_now_playing_view_caches, _clear_tmdb_missing_art, _mark_tmdb_missing_art, _perform_tmdb_error_flag_retry, _save_persisted_scene_enabled, _sync_now_playing_screen_state, _tmdb_match_tier_acceptable, _tmdb_spawn_identity, _tmdb_spawn_identity_changed, _view_one_uses_now_playing_screen, _vv_is_music, _vv_is_youtube, _warm_status_bar_blits, _warm_tmdb_logo_patch, active_tmdb_display_title, active_tmdb_title_key, apple_tv_auto_state, apple_tv_playback_clock, backdrop_app_logo_letterbox_fit, backdrop_master_bgr, brightness_current, brightness_from, brightness_t0, brightness_target, cap, last_frame, playing, render_once, root, saved_backdrop_app_logo_letterbox_fit, saved_backdrop_master_bgr, scaled_display, scaled_version, scene_enabled, skip_cache, spawn_tmdb_poster_fetch, status_bar_widget, streaming_badge_state, tmdb_error_flag_retry_active, tmdb_error_flag_retry_rule_idx, tmdb_logo_app_fallback_active, tmdb_logo_widget, tmdb_logo_widget_view_six, tmdb_quality_error_flag, tmdb_quality_last_scored_event_key, use_backdrop_scene) -> None:
    """TMDb search + download + poster pipeline on a worker thread.

    Short-circuits for MediaType.Music and YouTube. Music uses the
    two-line text patch (track title + "Artist – Album") instead of
    TMDb. YouTube uses pyatv 16×9 thumbnail art in ``widget_np_06_16x9``.
    Skipping the fetch also avoids ~1–3 s of background network work
    plus misleading retry-log entries against a TV/movie-only index.

    Only one worker runs at a time. If a fetch is already in flight,
    the latest request is stored in ``pending_tmdb`` and started when
    the current worker finishes (``force`` still queues; it no longer
    starts a concurrent second worker). ``tmdb_key`` is set only when a
    worker actually starts, so a skipped in-flight poll cannot poison
    the next identity check.
    """
    from pigeon.tmdb_poster import is_degenerate_tmdb_query, refine_tmdb_search_query

    del force  # kept for call-site compat; queueing replaces concurrent force

    if _vv_is_music() or _vv_is_youtube():
        # Music / YouTube metadata is still auto-detected content: a title that
        # differs from the manual SEARCH title suppresses the clocksaver poster.
        try:
            from pigeon import manual_search

            manual_search.note_detected_query(query)
        except Exception:
            pass
        sys.stderr.write(
            f"pigeon: tmdb spawn exit: {'youtube' if _vv_is_youtube() else 'music'} "
            f"query={query!r}\n"
        )
        _report_live_state(
            "youtube" if _vv_is_youtube() else "music",
            apple_tv_auto_state=apple_tv_auto_state,
            streaming_badge_state=streaming_badge_state,
        )
        # Clear any prior fetch breadcrumbs so the debug view doesn't
        # show stale values carried over from the previous track/video.
        apple_tv_auto_state["last_tmdb_fetch_input"] = None
        apple_tv_auto_state["last_tmdb_fetch_refined"] = None
        apple_tv_auto_state["last_tmdb_fetch_prefer"] = None
        apple_tv_auto_state["pending_tmdb"] = None
        if _vv_is_youtube():
            _clear_tmdb_missing_art()
        return

    q_in = (query or "").strip()
    q = refine_tmdb_search_query(q_in) or ""
    if not q:
        sys.stderr.write(f"pigeon: tmdb spawn exit: empty refined query for {q_in!r}\n")
        return
    if is_degenerate_tmdb_query(q):
        sys.stderr.write(f"pigeon: tmdb spawn exit: degenerate query {q!r}\n")
        return
    try:
        from pigeon import manual_search

        manual_search.note_detected_query(q_in)
    except Exception:
        pass
    try:
        from pigeon.tmdb_poster import tmdb_is_configured
    except ImportError:
        tmdb_is_configured = lambda: False  # type: ignore[misc, assignment]
    if not tmdb_is_configured():
        if not apple_tv_auto_state.get("tmdb_missing_warned"):
            apple_tv_auto_state["tmdb_missing_warned"] = True
            hint = (
                "pigeon: TMDb not configured — skipping artwork fetch. "
                f"Add API key to {pigeon_state_dir() / 'tmdb_api_key'} "
                "(see installer/setup/README on Pi)."
            )
            sys.stderr.write(hint + "\n")
            sys.stderr.flush()
            try:
                from pigeon.pi_diagnostics import append_pigeon_log

                append_pigeon_log(hint)
            except Exception:
                pass
        return
    prefer_n = str(prefer or "auto").strip() or "auto"
    sys.stderr.write(f"pigeon: tmdb spawn enter: {q_in!r} prefer={prefer_n!r}\n")
    if not _tmdb_spawn_identity_changed(q_in, prefer_n):
        sys.stderr.write(
            f"pigeon: tmdb spawn exit: identity unchanged {q_in!r} prefer={prefer_n!r} "
            f"tmdb_key={apple_tv_auto_state.get('tmdb_key')!r}\n"
        )
        return
    if apple_tv_auto_state.get("tmdb_fetch_in_flight"):
        # Keep spinner up; run this title as soon as the worker ends.
        apple_tv_auto_state["pending_tmdb"] = {"query": q_in, "prefer": prefer_n}
        try:
            from pigeon.pi_diagnostics import append_pigeon_log

            append_pigeon_log(
                f"tmdb fetch queued (in flight): {q!r} prefer={prefer_n!r}"
            )
        except Exception:
            pass
        if _view_one_uses_now_playing_screen():
            _sync_now_playing_screen_state()
            try:
                render_once()
            except Exception:
                pass
        return
    apple_tv_auto_state["pending_tmdb"] = None
    apple_tv_auto_state["tmdb_key"] = _tmdb_spawn_identity(q_in, prefer_n)
    apple_tv_auto_state["query"] = q_in
    apple_tv_auto_state["prefer"] = prefer_n
    apple_tv_auto_state["last_tmdb_fetch_input"] = q_in
    apple_tv_auto_state["last_tmdb_fetch_refined"] = q
    apple_tv_auto_state["last_tmdb_fetch_prefer"] = prefer_n
    apple_tv_auto_state["tmdb_fetch_in_flight"] = True
    try:
        from pigeon.title_decision import (
            apply_decision_to_metadata,
            record_title_decision,
        )

        decision = record_title_decision(
            q,
            source="tmdb",
            reason=f"spawned TMDb search (prefer={prefer_n})",
            extras={"input": q_in, "prefer": prefer_n},
        )
        apple_tv_auto_state["last_title_decision"] = decision.explain()
        md_dec = apple_tv_auto_state.get("last_metadata")
        if isinstance(md_dec, dict):
            apply_decision_to_metadata(md_dec, decision)
    except Exception:
        pass
    try:
        from pigeon.pi_diagnostics import append_pigeon_log

        append_pigeon_log(f"tmdb fetch started: {q!r} prefer={prefer_n!r}")
    except Exception:
        pass
    fetch_t0 = time.monotonic()
    fetch_trigger = "flag_retry" if tmdb_error_flag_retry_active[0] else "auto"
    _report_live_state(
        "searching",
        apple_tv_auto_state=apple_tv_auto_state,
        streaming_badge_state=streaming_badge_state,
        query=q_in,
        refined_query=q,
        prefer=prefer_n,
    )

    def _report_fetch(
        ok_r: bool,
        msg_r: str,
        tier_r: int,
        tier_ok_r: bool,
        used_q_r: str,
        attempts_r: list[dict] | None,
        *,
        tt_source: str,
        backdrop_source: str,
    ) -> None:
        try:
            from pigeon.accuracy_report import report_fetch_event

            md_r = apple_tv_auto_state.get("last_metadata")
            report_fetch_event(
                metadata=md_r if isinstance(md_r, dict) else None,
                streaming_service=_streaming_service_label(
                    apple_tv_auto_state, streaming_badge_state
                ),
                query_in=q_in,
                refined_query=q,
                used_query=used_q_r or q,
                prefer=prefer_n,
                trigger=fetch_trigger,
                ok=ok_r,
                message=msg_r,
                match_tier=tier_r,
                tier_ok=tier_ok_r,
                attempts=attempts_r,
                tt_source=tt_source,
                backdrop_source=backdrop_source,
                started_mono=fetch_t0,
            )
        except Exception:
            pass
    # Show searching spinner in the poster immediately.
    if _view_one_uses_now_playing_screen():
        _sync_now_playing_screen_state()
        try:
            render_once()
        except Exception:
            pass

    def _drain_pending_tmdb_spawn() -> None:
        pend = apple_tv_auto_state.get("pending_tmdb")
        apple_tv_auto_state["pending_tmdb"] = None
        if not isinstance(pend, dict):
            return
        pq = str(pend.get("query") or "").strip()
        pp = str(pend.get("prefer") or "auto").strip() or "auto"
        if not pq:
            return
        root.after(0, lambda: spawn_tmdb_poster_fetch(pq, prefer=pp, force=True))

    def finish_tmdb(
        ok_m: bool,
        msg_m: str,
        backdrop_master: np.ndarray | None = None,
        match_tier: int = 0,
        search_query: str = "",
        attempts: list[dict] | None = None,
    ) -> None:
        apple_tv_auto_state["tmdb_fetch_in_flight"] = False
        sys.stderr.write(f"pigeon: tmdb → {msg_m}\n")
        sys.stderr.flush()
        try:
            from pigeon.pi_diagnostics import append_pigeon_log

            append_pigeon_log(f"tmdb → {msg_m}")
        except Exception:
            pass
        # Only ignore results when a newer title is already queued. Do not use
        # live ``query`` alternation (pyatv show vs episode) — that was marking
        # successful fetches stale and leaving the poster empty forever.
        pending_raw = apple_tv_auto_state.get("pending_tmdb")
        result_stale = False
        if isinstance(pending_raw, dict):
            pq = str(pending_raw.get("query") or "").strip()
            if pq and pq != q_in:
                try:
                    from pigeon.tmdb_poster import equivalent_tmdb_search_queries

                    if not equivalent_tmdb_search_queries(pq, q_in):
                        result_stale = True
                except Exception:
                    result_stale = True
        if result_stale:
            try:
                from pigeon.pi_diagnostics import append_pigeon_log

                append_pigeon_log(
                    f"tmdb result ignored (stale/pending): worker={q_in!r}"
                )
            except Exception:
                pass
            _drain_pending_tmdb_spawn()
            return
        tier_ok = _tmdb_match_tier_acceptable(search_query or q, int(match_tier))
        if not ok_m:
            # No show title found: do not interrupt with an error dialog. Surface the
            # streaming-app logo in the content-logo slot and leave the current scene
            # alone — no new backdrop is enabled here (successful matches still get
            # their own backdrop below).
            sys.stderr.write(
                "pigeon: TMDb search found no match — showing streaming app logo in "
                "the content-logo slot (no backdrop).\n"
            )
            sys.stderr.flush()
            try:
                from pigeon.tmdb_desktop_report import append_tmdb_error_event

                md_err = apple_tv_auto_state.get("last_metadata")
                append_tmdb_error_event(
                    last_metadata=md_err if isinstance(md_err, dict) else None,
                    streaming_badge_state=streaming_badge_state,
                    supplemental_metadata=(
                        f"no_match refined_query={q!r} prefer={prefer!r} msg={msg_m!s}"
                    ),
                )
            except Exception:
                pass
            # The error-flag path retries the next rule before any fallback.
            retrying = bool(
                tmdb_error_flag_retry_active[0]
                and tmdb_error_flag_retry_rule_idx[0] < len(TMDB_ERROR_FLAG_RETRY_RULES)
            )
            text_tt = False if retrying else _apply_rawtitle_text_tt_fallback()
            _report_fetch(
                False,
                msg_m,
                int(match_tier),
                tier_ok,
                search_query,
                attempts,
                tt_source=(
                    "retrying" if retrying else "text_fallback" if text_tt else "app_logo"
                ),
                backdrop_source="none",
            )
            # Error-flag path: auto-advance through one full rule cycle, then give up.
            if tmdb_error_flag_retry_active[0]:
                if tmdb_error_flag_retry_rule_idx[0] < len(TMDB_ERROR_FLAG_RETRY_RULES):
                    _drain_pending_tmdb_spawn()
                    root.after(0, _perform_tmdb_error_flag_retry)
                    return
                _mark_tmdb_missing_art(
                    identity=_tmdb_spawn_identity(q_in, prefer_n)
                )
            else:
                # Ordinary no-match: one attempt per identity — do not let the
                # empty-display poll respawn forever (spinner with blank poster).
                _mark_tmdb_missing_art(
                    identity=_tmdb_spawn_identity(q_in, prefer_n)
                )
            if text_tt:
                if tmdb_logo_widget is not None:
                    tmdb_logo_widget.clear_cache()
                if tmdb_logo_widget_view_six is not None:
                    tmdb_logo_widget_view_six.clear_cache()
                _warm_tmdb_logo_patch()
                if _view_one_uses_now_playing_screen():
                    _clear_now_playing_view_caches()
                    _sync_now_playing_screen_state()
                skip_cache[0] = None
                render_once()
                _drain_pending_tmdb_spawn()
                return
            active_tmdb_title_key[0] = None
            active_tmdb_display_title[0] = None
            tmdb_logo_app_fallback_active[0] = True
            if tmdb_logo_widget is not None:
                tmdb_logo_widget.clear_cache()
            if tmdb_logo_widget_view_six is not None:
                tmdb_logo_widget_view_six.clear_cache()
            _warm_tmdb_logo_patch()
            if _view_one_uses_now_playing_screen():
                _clear_now_playing_view_caches()
                _sync_now_playing_screen_state()
            skip_cache[0] = None
            render_once()
            _drain_pending_tmdb_spawn()
            return
        _clear_tmdb_missing_art()
        tmdb_logo_app_fallback_active[0] = False
        # msg_m includes a prefix when successful: "<title_key>::<display_title>::<summary>"
        parts = msg_m.split("::", 2)
        if len(parts) >= 2:
            active_tmdb_title_key[0] = parts[0].strip() or None
            active_tmdb_display_title[0] = parts[1].strip() or None
        else:
            active_tmdb_title_key[0] = None
            active_tmdb_display_title[0] = None
        if ok_m and not tier_ok:
            sys.stderr.write(
                f"pigeon: TMDb match tier {match_tier} below threshold for {search_query or q!r} "
                "— using rawTitle text TT.\n"
            )
            sys.stderr.flush()
            _apply_rawtitle_text_tt_fallback()
        if tmdb_logo_widget is not None:
            tmdb_logo_widget.clear_cache()
        if tmdb_logo_widget_view_six is not None:
            tmdb_logo_widget_view_six.clear_cache()
        _warm_tmdb_logo_patch()
        bd_use = backdrop_master
        from_app_logo = False
        if bd_use is None:
            bd_use = _backdrop_master_from_streaming_app_logo()
            from_app_logo = bd_use is not None
        if bd_use is not None:
            backdrop_master_bgr[0] = bd_use
            saved_backdrop_master_bgr[0] = np.asarray(bd_use, dtype=np.uint8).copy()
            saved_backdrop_app_logo_letterbox_fit[0] = from_app_logo
            backdrop_app_logo_letterbox_fit[0] = from_app_logo
            scaled_version[0] += 1
            if _view_one_uses_now_playing_screen():
                # View 1 paints TMDB in the now-playing bar only. Keep scene off so
                # render_once always takes the chrome compose path (skip-cache there
                # omits TMDB bar state and would freeze the bar empty).
                use_backdrop_scene[0] = False
                if status_bar_widget is not None:
                    bd_arr = np.asarray(backdrop_master_bgr[0], dtype=np.uint8)
                    if status_bar_widget.set_accent_from_backdrop_bgr(bd_arr):
                        _warm_status_bar_blits()
                        skip_cache[0] = None
            else:
                if cap[0] is not None:
                    try:
                        cap[0].release()
                    except Exception:
                        pass
                    cap[0] = None
                use_backdrop_scene[0] = True
                scene_enabled[0] = True
                playing[0] = False
                last_frame[0] = None
                if not _PIGEON_EXT:
                    scaled_display[0] = None
                else:
                    scaled_display[0] = None
                _save_persisted_scene_enabled(True)
                # Backdrop is static image — not paused-video 0.3; use dedicated backdrop level.
                brightness_current[0] = brightness_from[0] = brightness_target[0] = BACKDROP_BRIGHTNESS
                brightness_t0[0] = time.monotonic()
                if not _apply_netflix_backdrop_when_running():
                    if status_bar_widget is not None:
                        bd_arr = np.asarray(backdrop_master_bgr[0], dtype=np.uint8)
                        if status_bar_widget.set_accent_from_backdrop_bgr(bd_arr):
                            _warm_status_bar_blits()
                            skip_cache[0] = None
        win_trace: dict = {}
        for a in attempts or []:
            if isinstance(a, dict) and a.get("query") == (search_query or q):
                win_trace = a
        # A low tier keeps the match's title key, so a cached logo still wins
        # over the rawTitle text — report what is actually on screen.
        if win_trace.get("logo_ok"):
            tt_src = "tmdb_logo"
        elif not tier_ok:
            tt_src = "text_fallback"
        else:
            tt_src = "title_text"
        if backdrop_master is not None:
            bd_src = "tmdb"
        elif bd_use is not None:
            bd_src = "app_logo"
        else:
            bd_src = "none"
        _report_fetch(
            True,
            msg_m,
            int(match_tier),
            tier_ok,
            search_query,
            attempts,
            tt_source=tt_src,
            backdrop_source=bd_src,
        )
        # Match-quality counters: score only when TMDb material changes to a
        # new content event key (not on same-content retries/refetches).
        if active_tmdb_title_key[0]:
            try:
                ev_key = str(apple_tv_auto_state.get("content_key") or "").strip()
                if not ev_key:
                    # Fallback so manual fetches without poll metadata still have
                    # a deterministic event key.
                    qk = str(apple_tv_auto_state.get("query") or "").strip()
                    ev_key = f"{str(active_tmdb_title_key[0] or '').strip()}::{qk}"
                if ev_key and ev_key != str(tmdb_quality_last_scored_event_key[0] or ""):
                    had_qe = bool(tmdb_quality_error_flag[0])
                    if had_qe:
                        _cancel_tmdb_quality_auto_unlog_timer()
                    tmdb_quality_error_flag[0] = False
                    cur_q = read_app_state()
                    s_q = int(cur_q.get("tmdb_quality_successes", 0) or 0)
                    f_q = int(cur_q.get("tmdb_quality_failures", 0) or 0)
                    if not had_qe:
                        s_q += 1
                        try:
                            _append_tmdb_quality_event_report_log(
                                outcome="SUCCESS",
                                title_key=active_tmdb_title_key[0],
                                display_title=active_tmdb_display_title[0],
                                msg_m=msg_m,
                            )
                        except Exception:
                            pass
                    write_app_state(tmdb_quality_successes=s_q, tmdb_quality_failures=f_q)
                    tmdb_quality_last_scored_event_key[0] = ev_key
            except Exception:
                pass
        if _view_one_uses_now_playing_screen():
            _clear_now_playing_view_caches()
            _sync_now_playing_screen_state()
        skip_cache[0] = None
        render_once()
        _drain_pending_tmdb_spawn()

    def worker() -> None:
        used_q = q
        attempts: list[dict] = []
        # Below-threshold hits, kept only to explain a rejection.
        loose: list[tuple[str, str, int]] = []
        try:
            from pigeon.display_confidence import player_duration_seconds
            from pigeon.raw_title import tmdb_query_candidates_from_metadata
            from pigeon.tmdb_poster import apply_tmdb_movie_query, last_fetch_trace

            candidates: list[str] = []
            md_raw = apple_tv_auto_state.get("last_metadata")
            app_nm: str | None = None
            app_ident: str | None = None
            if isinstance(md_raw, dict):
                app_nm = str(md_raw.get("app_name") or "").strip() or None
                app_ident = str(md_raw.get("app_id") or "").strip() or None
                for cand in tmdb_query_candidates_from_metadata(md_raw):
                    if cand not in candidates:
                        candidates.append(cand)
            if q not in candidates:
                candidates.insert(0, q)
            elif candidates and candidates[0] != q:
                candidates = [q] + [c for c in candidates if c != q]
            if not candidates:
                candidates = [q]
            clk_dur = apple_tv_playback_clock
            player_dur = player_duration_seconds(
                md_raw if isinstance(md_raw, dict) else None,
                fallbacks=(
                    clk_dur.get("latched_total"),
                    clk_dur.get("last_reported_total"),
                ),
            )
            ok_w, msg_w, bd_w, tier_w = False, "No candidates.", None, 0
            used_q = q
            for cand in candidates:
                ok_try, msg_try, bd_try, tier_try = apply_tmdb_movie_query(
                    cand,
                    prefer=prefer,
                    app_name=app_nm,
                    app_id=app_ident,
                    player_duration_s=player_dur,
                )  # type: ignore[arg-type]
                attempts.append(last_fetch_trace())
                used_q = cand
                if ok_try and _tmdb_match_tier_acceptable(cand, int(tier_try)):
                    ok_w, msg_w, bd_w, tier_w = ok_try, msg_try, bd_try, tier_try
                    break
                if ok_try:
                    loose.append((cand, msg_try, int(tier_try)))
            if not ok_w:
                for cand in candidates:
                    ok_try, msg_try, bd_try, tier_try = apply_tmdb_movie_query(
                        cand,
                        prefer=prefer,
                        forgiving=True,
                        app_name=app_nm,
                        app_id=app_ident,
                        player_duration_s=player_dur,
                    )  # type: ignore[arg-type]
                    attempts.append(last_fetch_trace())
                    used_q = cand
                    if ok_try and _tmdb_match_tier_acceptable(cand, int(tier_try)):
                        ok_w, msg_w, bd_w, tier_w = ok_try, msg_try, bd_try, tier_try
                        break
                    if ok_try:
                        loose.append((cand, msg_try, int(tier_try)))
            if not ok_w and loose:
                # A hit whose title does not match the query (It Sounds
                # Incredible for "IT: Welcome to Derry") is not a match: show
                # the raw title as text, never that title's art.
                l_q, l_msg, l_tier = max(loose, key=lambda row: row[2])
                l_title = l_msg.split("::", 2)[1] if "::" in l_msg else l_msg
                used_q = l_q
                tier_w = l_tier
                msg_w = (
                    f"Loose match rejected: {l_title!r} (tier {l_tier}) "
                    f"for {l_q!r}"
                )
        except Exception as e:
            ok_w, msg_w, bd_w, tier_w, used_q = False, str(e), None, 0, q
        root.after(
            0,
            lambda o=ok_w, m=msg_w, b=bd_w, t=tier_w, sq=used_q, at=attempts: finish_tmdb(
                o, m, b, t, sq, at
            ),
        )

    threading.Thread(target=worker, daemon=True).start()


def apply_saved_tmdb_backdrop_to_display(*, BACKDROP_BRIGHTNESS, _PIGEON_EXT, _app_logo_clock_saver_style_now, _apply_netflix_backdrop_when_running, _save_persisted_scene_enabled, _sync_now_playing_screen_state, _view_one_uses_now_playing_screen, _warm_status_bar_blits, _warm_tmdb_logo_patch, backdrop_app_logo_letterbox_fit, backdrop_master_bgr, brightness_current, brightness_from, brightness_t0, brightness_target, display_dims, last_frame, playing, render_once, saved_backdrop_app_logo_letterbox_fit, saved_backdrop_master_bgr, scaled_display, scaled_version, scene_enabled, skip_cache, status_bar_widget, use_backdrop_scene, view_circles_widget) -> None:
    """Apply last TMDb backdrop + title logo (same as F10’s backdrop step)."""
    if saved_backdrop_master_bgr[0] is None:
        return
    playing[0] = False
    backdrop_master_bgr[0] = saved_backdrop_master_bgr[0].copy()
    backdrop_app_logo_letterbox_fit[0] = saved_backdrop_app_logo_letterbox_fit[0]
    if _view_one_uses_now_playing_screen():
        use_backdrop_scene[0] = False
        scaled_version[0] += 1
        _warm_tmdb_logo_patch()
        if view_circles_widget is not None:
            view_circles_widget.clear_cache()
        _sync_now_playing_screen_state()
        skip_cache[0] = None
        render_once()
        return
    use_backdrop_scene[0] = True
    scene_enabled[0] = True
    last_frame[0] = None
    if status_bar_widget is not None and status_bar_widget.set_accent_from_backdrop_bgr(
        backdrop_master_bgr[0]
    ):
        _warm_status_bar_blits()
    if not _PIGEON_EXT:
        from pigeon.image_ui_protocol import backdrop_scene_bgr_for_display

        scaled_display[0] = backdrop_scene_bgr_for_display(
            backdrop_master_bgr[0],
            display_dims[0],
            display_dims[1],
            app_logo_letterbox_fit=backdrop_app_logo_letterbox_fit[0],
            app_logo_clock_saver_style=_app_logo_clock_saver_style_now(),
        )
    else:
        scaled_display[0] = None
    scaled_version[0] += 1
    brightness_current[0] = brightness_from[0] = brightness_target[0] = BACKDROP_BRIGHTNESS
    brightness_t0[0] = time.monotonic()
    _warm_tmdb_logo_patch()
    _save_persisted_scene_enabled(True)
    skip_cache[0] = None
    _apply_netflix_backdrop_when_running()
    render_once()
