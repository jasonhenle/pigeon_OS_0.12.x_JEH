"""View 4 (Title Info) text collection.

Extracted verbatim from ``bootstrap()`` in ``pigeon_0_12.py``. Each function
takes the app state it used to close over as keyword-only arguments;
``bootstrap()`` binds them once with ``bind_deps`` so call sites are unchanged.
"""

from __future__ import annotations
import cv2
import numpy as np
import re


def _view_four_text_is_placeholder(s: str) -> bool:
    """Hide rows whose text is empty or ends with ``-`` / ``NONE`` (any case)."""
    t = str(s).strip()
    if not t:
        return True
    while t and t[-1] in {"'", '"'}:
        t = t[:-1].rstrip()
    if not t:
        return True
    up = t.upper()
    return (
        up.endswith("NONE")
        or up.endswith("UNKNOWN")
        or t.endswith("-")
        or t.endswith("—")
    )


def _view_four_display_metadata(*, apple_tv_auto_state) -> dict[str, object] | None:
    """Copy of last_metadata for View 4 / the [4] inspector."""
    md = apple_tv_auto_state.get("last_metadata")
    if not isinstance(md, dict):
        return None
    return dict(md)


def _collect_view_four_raw_title_lines(*, _tmdb_info_current_and_available, _view_four_display_metadata, _view_four_has_value, _view_four_text_is_placeholder, apple_tv_auto_state, apple_tv_playback_clock, receiver_debug_holder, streaming_badge_state) -> list[tuple[str, bool]]:
    """View 4: streaming label, rawTitle fields that have a value, last TMDb fetch."""
    rows: list[tuple[str, bool]] = []

    def _ln(s: str) -> None:
        if _view_four_text_is_placeholder(s):
            return
        rows.append((s, False))

    lm_rt = _view_four_display_metadata()
    if isinstance(lm_rt, dict):
        try:
            from pigeon.display_confidence import scores_for_metadata
            from pigeon.hdmi_capture import hdmi_capture_available
            from pigeon.tmdb_poster import last_trt_comparison

            clk = apple_tv_playback_clock
            advancing = bool(clk.get("has_sync") and clk.get("playing"))
            tmdb_ok = bool(_tmdb_info_current_and_available())
            trt_cmp = last_trt_comparison()

            scores = scores_for_metadata(
                lm_rt,
                position_advancing=advancing,
                tmdb_matches=tmdb_ok,
                hdmi_present=hdmi_capture_available(),
                player_duration_s=trt_cmp.get("player_s"),
                tmdb_runtime_s=trt_cmp.get("tmdb_s"),
            )
            src = str(lm_rt.get("identity_source") or "").strip()
            if src:
                _ln(f"identity.source={src!r}")
            try:
                from pigeon.title_decision import decision_from_metadata

                why = decision_from_metadata(lm_rt) or str(
                    apple_tv_auto_state.get("last_title_decision") or ""
                ).strip()
                if why:
                    _ln(f"title.decision={why}")
            except Exception:
                pass
            for key in ("identity", "position", "art", "app", "trt"):
                val = scores.get(key)
                if val is None:
                    continue
                _ln(f"confidence.{key}={float(val):.2f}")
            if scores.get("hdmi_charge"):
                _ln("hdmi.charge=true")
        except Exception:
            pass
    _svc_label = str(streaming_badge_state.get("label") or "").strip()
    _svc_app = (
        str(lm_rt.get("app_name") or "").strip()
        if isinstance(lm_rt, dict)
        else ""
    )
    if _svc_label:
        _ln(f"streamingService={_svc_label!r}")
    elif _svc_app:
        _ln(f"streamingService={_svc_app!r}")

    if not isinstance(lm_rt, dict):
        _ln("rawTitle: (no last_metadata dict)")
    else:
        try:
            from pigeon.raw_title import raw_title_from_metadata_dict

            rt = raw_title_from_metadata_dict(lm_rt)
            if _view_four_has_value(rt.source):
                _ln(f"rawTitle.source={rt.source!r}")
            for fn in (
                "raw_title",
                "raw_series_name",
                "raw_artist",
                "raw_album",
                "raw_episode_title",
                "raw_query",
                "season_index",
                "episode_index",
                "layer_series_title",
                "layer_series_number",
                "layer_episode_number",
                "layer_episode_title",
                "media_type_label",
            ):
                val = getattr(rt, fn, None)
                if _view_four_has_value(val):
                    _ln(f"rawTitle.{fn}={val!r}")
            if rt.notes:
                _ln(f"rawTitle.notes={rt.notes!r}")
            sig = rt.training_signature_normalized()
            if sig:
                _ln(f"rawTitle.training_signature_normalized={sig!r}")
        except Exception as e:
            _ln(f"rawTitle err={e}")
    if isinstance(lm_rt, dict):
        _pp = str(lm_rt.get("prefer_pyatv_media") or "").strip().lower()
        if _pp in ("auto", "tv", "movie"):
            _ln(f"metadata.prefer_pyatv_media={_pp!r}")
        _ip = str(lm_rt.get("inferred_prefer") or "").strip().lower()
        if _ip in ("auto", "tv", "movie"):
            _ln(f"metadata.prefer_tmdb={_ip!r}")
    _ti = apple_tv_auto_state.get("last_tmdb_fetch_input")
    _tr = apple_tv_auto_state.get("last_tmdb_fetch_refined")
    _tp = apple_tv_auto_state.get("last_tmdb_fetch_prefer")
    if _ti is not None and str(_ti).strip():
        _ln(f"tmdbFetch.input_query={str(_ti)!r}")
    if _tr is not None and str(_tr).strip():
        _ln(f"tmdbFetch.refined_query={str(_tr)!r}")
    if _tp is not None and str(_tp).strip():
        _ln(f"tmdbFetch.prefer={str(_tp)!r}")
    rx_dbg = receiver_debug_holder[0] if receiver_debug_holder else {}
    if isinstance(rx_dbg, dict) and rx_dbg:
        _ln("receiver (debug):")
        for key in ("power", "volume", "input", "audio format", "sound mode"):
            val = str(rx_dbg.get(key) or "").strip()
            if val:
                _ln(f"  {key}={val!r}")
    return rows


def _collect_view_four_source_lines(*, _view_four_display_metadata, _view_four_has_value, _view_four_text_is_placeholder, receiver_overlay_state) -> list[tuple[str, bool]]:
    """View 4 subview: best-effort file/stream stats from poll metadata + receiver text hints."""
    from math import gcd

    rows: list[tuple[str, bool]] = []

    def _ln(s: str, bold: bool = False) -> None:
        if _view_four_text_is_placeholder(s):
            return
        rows.append((s, bold))

    def _md_pick(md: dict[str, object], *keys: str) -> str | None:
        for k in keys:
            if k not in md:
                continue
            v = md[k]
            if v is None:
                continue
            if isinstance(v, (int, float)):
                if isinstance(v, float) and v != v:
                    continue
                t = str(int(v)) if float(v) == int(v) else str(v)
            else:
                t = str(v).strip()
            if t:
                return t
        return None

    def _aspect_from_wh(w_s: str | None, h_s: str | None) -> str | None:
        if not w_s or not h_s:
            return None
        try:
            wi = int(round(float(w_s)))
            hi = int(round(float(h_s)))
        except (TypeError, ValueError):
            return None
        if wi <= 0 or hi <= 0:
            return None
        g = gcd(wi, hi)
        return f"{wi // g}:{hi // g}"

    md = _view_four_display_metadata()
    inc = str(receiver_overlay_state.get("incoming") or "").strip()
    cfg = str(receiver_overlay_state.get("config") or "").strip()
    rx_blob = f"{inc} {cfg}".strip()

    if not isinstance(md, dict):
        _ln("(no last_metadata dict)", False)
        return rows

    w = _md_pick(md, "video_width", "width", "source_width", "ImageWidth", "image_width")
    h = _md_pick(md, "video_height", "height", "source_height", "ImageHeight", "image_height")
    res_one = _md_pick(
        md,
        "video_resolution",
        "source_resolution",
        "resolution",
        "VideoResolution",
    )

    def _ln_val(label: str, value: str | None) -> None:
        if _view_four_has_value(value):
            _ln(f"{label}: {value}", False)

    if res_one:
        _ln_val("Video source resolution", res_one)
    elif w and h:
        _ln_val("Video source resolution", f"{w}×{h}")
    elif w or h:
        _ln_val("Video source resolution", f"{w or '?'}×{h or '?'}")

    ar = _md_pick(md, "aspect_ratio", "video_aspect_ratio", "AspectRatio", "DisplayAspectRatio")
    if not ar:
        ar = _aspect_from_wh(w, h)
    _ln_val("Video source aspect ratio", ar)
    _ln_val(
        "Video source color space",
        _md_pick(
            md,
            "color_space",
            "color_primaries",
            "VideoColorSpace",
            "ColorSpace",
            "colour_space",
        ),
    )
    _ln_val(
        "Video source frame rate",
        _md_pick(
            md,
            "frame_rate",
            "framerate",
            "fps",
            "video_frame_rate",
            "FrameRate",
        ),
    )
    _ln_val(
        "Video source bit depth",
        _md_pick(md, "video_bit_depth", "bit_depth", "bits_per_pixel", "VideoBitDepth"),
    )
    _ln_val(
        "Video source codec",
        _md_pick(md, "video_codec", "codec", "video_format", "VideoCodec", "format"),
    )
    _ln_val(
        "Video source wrapper",
        _md_pick(md, "container", "wrapper", "mime_type", "MimeType", "file_extension"),
    )
    _ln_val(
        "Audio source wrapper",
        _md_pick(md, "audio_container", "audio_wrapper", "AudioContainer"),
    )
    _ln_val(
        "Audio source bit depth",
        _md_pick(md, "audio_bit_depth", "source_audio_bit_depth", "AudioBitDepth"),
    )
    _ln_val(
        "Audio source bit rate",
        _md_pick(md, "audio_bit_rate", "source_audio_bit_rate", "AudioBitrate", "audio_bitrate"),
    )
    _ln_val(
        "Audio source codec",
        _md_pick(md, "audio_codec", "audio_format", "AudioCodec", "AudioFormat"),
    )

    def _lpcm_vs_bitstream(blob: str, md2: dict[str, object]) -> str:
        ac = str(md2.get("audio_codec") or md2.get("audio_format") or "").lower()
        blob_l = blob.lower()
        joined = f"{ac} {blob_l}"
        if "pcm" in joined or "lpcm" in joined or "linear pcm" in joined:
            return "LPCM/PCM (from metadata/receiver text)"
        if any(
            x in joined
            for x in (
                "dolby",
                "dts",
                "truehd",
                "true-hd",
                "eac3",
                "e-ac-3",
                "atmos",
                "bitstream",
                "dd+",
                "dtsx",
            )
        ):
            return "Compressed / bitstream (from metadata/receiver text)"
        if blob:
            return "Unknown (see receiver lines below)"
        return "—"

    _lpcm = _lpcm_vs_bitstream(rx_blob, md)
    if _view_four_has_value(_lpcm):
        _ln(f"Audio source LPCM vs bitstream: {_lpcm}", False)

    proto = _md_pick(md, "protocol")
    if proto:
        _ln(f"Poll protocol: {proto}", False)
    appn = str(md.get("app_name") or "").strip()
    appid = str(md.get("app_id") or "").strip()
    if appn or appid:
        _ln(f"App: {appn!r} id={appid!r}", False)

    if inc:
        _ln(f"Receiver incoming (raw): {inc}", False)
    if cfg:
        _ln(f"Receiver config (raw): {cfg}", False)

    known = {
        "query",
        "title",
        "artist",
        "series_name",
        "album",
        "media_type",
        "total_time",
        "position",
        "device_state",
        "inferred_prefer",
        "prefer_pyatv_media",
        "content_key",
        "app_name",
        "app_id",
        "volume_percent",
        "prefer",
    }
    extra_keys = [
        k
        for k in sorted(md.keys())
        if k not in known
        and not str(k).startswith("_")
        and _view_four_has_value(md.get(k))
    ]
    if extra_keys:
        _ln("other metadata keys", False)
        for k in extra_keys[:36]:
            try:
                vv = md[k]
                rep = repr(vv)
                if len(rep) > 140:
                    rep = rep[:137] + "..."
            except Exception:
                rep = "?"
            _ln(f"  {k}={rep}", False)
        if len(extra_keys) > 36:
            _ln(f"  … ({len(extra_keys) - 36} more keys)", False)
    return rows


def _collect_view_four_playback_lines(*, _view_four_display_metadata, _view_four_has_value, _view_four_text_is_placeholder, cap, display_dims, frame_interval_ms, receiver_overlay_state) -> list[tuple[str, bool]]:
    rows: list[tuple[str, bool]] = []

    def _ln(s: str, bold: bool = False) -> None:
        if _view_four_text_is_placeholder(s):
            return
        rows.append((s, bold))

    md_raw = _view_four_display_metadata()
    md = md_raw if isinstance(md_raw, dict) else None
    inc = str(receiver_overlay_state.get("incoming") or "").strip()
    cfg = str(receiver_overlay_state.get("config") or "").strip()
    vol_line = str(receiver_overlay_state.get("volume") or "").strip()
    blob = f"{inc} {cfg}".lower()

    def _channels_guess(s: str) -> str:
        if "7.1" in s or "7_1" in s:
            return "7.1 (hint)"
        if "5.1" in s or "5_1" in s:
            return "5.1 (hint)"
        if "2.0" in s or "stereo" in s or "2ch" in s:
            return "2.0 / stereo (hint)"
        if "atmos" in s:
            return "Atmos (hint)"
        return "—"

    fmt_parts: list[str] = []
    if md:
        mt = str(md.get("media_type") or "").strip()
        if mt:
            fmt_parts.append(mt)
    if inc or cfg:
        fmt_parts.append(f"receiver: {(inc + ' ' + cfg).strip()[:120]}")
    if fmt_parts:
        _ln(f"Audio playback format: {' | '.join(fmt_parts)}", False)

    if md and md.get("audio_playback_bit_rate") is not None:
        _ln(f"Audio playback bit rate: {str(md.get('audio_playback_bit_rate')).strip()}", False)
    if md and md.get("audio_playback_bit_depth") is not None:
        _ln(f"Audio playback bit depth: {str(md.get('audio_playback_bit_depth')).strip()}", False)
    ch = _channels_guess(blob)
    if _view_four_has_value(ch):
        _ln(f"Audio playback available channels: {ch}", False)
        _ln(f"Audio playback active channels: {ch}", False)

    if vol_line:
        scale = "dB scale" if ("db" in vol_line.lower() or re.search(r"-?\d+\.\d+\s*d", vol_line.lower())) else (
            "0–100" if re.search(r"\b\d{1,3}\b", vol_line) and "%" not in vol_line and "db" not in vol_line.lower() else "receiver raw"
        )
        _ln(f"Audio playback volume: {vol_line}", False)
        _ln(f"Audio playback volume scale: {scale}", False)
    elif md and md.get("volume_percent") is not None:
        try:
            vp = int(max(0, min(100, round(float(md["volume_percent"])))))
            _ln(f"Audio playback volume: {vp}", False)
            _ln("Audio playback volume scale: Apple TV 0–100", False)
        except (TypeError, ValueError):
            pass

    dw, dh = int(display_dims[0]), int(display_dims[1])
    if dw > 0 and dh > 0:
        _ln(f"Video playback resolution (window): {dw}×{dh}", False)

    cap_fps = None
    try:
        if cap[0] is not None and cap[0].isOpened():
            cf = float(cap[0].get(cv2.CAP_PROP_FPS) or 0.0)
            if cf > 1.0:
                cap_fps = cf
    except Exception:
        cap_fps = None
    if cap_fps is not None:
        _ln(f"Video capture nominal FPS: {cap_fps:.3g}", False)

    ui_hz = 1000.0 / float(frame_interval_ms[0]) if frame_interval_ms[0] else 0.0
    if ui_hz > 0:
        _ln(f"UI composite cadence: ~{ui_hz:.2f} Hz (frame_interval_ms={frame_interval_ms[0]})", False)

    if md:
        ds = str(md.get("device_state") or "").strip()
        pos = md.get("position")
        tot = md.get("total_time")
        if ds:
            _ln(f"Device state: {ds}", False)
        if _view_four_has_value(pos) or _view_four_has_value(tot):
            _ln(f"Position / duration: {pos!r} / {tot!r}", False)
    return rows


def _view_four_has_value(v: object, *, _view_four_has_value, _view_four_text_is_placeholder) -> bool:
    """True when a View 4 debug field should be listed (skip None / empty / NONE / -)."""
    if v is None:
        return False
    if isinstance(v, bool):
        return True
    if isinstance(v, str):
        return not _view_four_text_is_placeholder(v)
    if isinstance(v, (list, tuple, set)):
        return any(_view_four_has_value(x) for x in v)
    if isinstance(v, dict):
        return any(_view_four_has_value(x) for x in v.values())
    if isinstance(v, float) and v != v:
        return False
    return True


def _blend_view_four_debug(bgr: np.ndarray, *, DisplayView, _collect_view_four_playback_lines, _collect_view_four_raw_title_lines, _collect_view_four_source_lines, _effective_display_view, view_four_subview_holder) -> np.ndarray:
    if _effective_display_view() != DisplayView.FOUR:
        return bgr
    out = bgr.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX
    mx = 10
    my_top = 12
    my_bot = 10
    H, W = int(out.shape[0]), int(out.shape[1])
    max_w = max(24, W - 2 * mx)
    sub_i = max(0, min(2, int(view_four_subview_holder[0])))
    sub_titles = ("Title Info", "Source Info", "Playback Info")
    if sub_i == 0:
        raw_debug_lines = [(f"View 4 — {sub_titles[sub_i]}", True)] + _collect_view_four_raw_title_lines()
    elif sub_i == 1:
        raw_debug_lines = [(f"View 4 — {sub_titles[sub_i]}", True)] + _collect_view_four_source_lines()
    else:
        raw_debug_lines = [(f"View 4 — {sub_titles[sub_i]}", True)] + _collect_view_four_playback_lines()
    _any_bold = bool(raw_debug_lines)
    rows = [
        (str(raw).strip(), is_bold)
        for raw, is_bold in raw_debug_lines
        if str(raw).strip()
    ]
    if not rows:
        rows = [("(no rawTitle lines yet)", False)]

    def _vf_thick(sc: float) -> int:
        return 2 if sc >= 0.48 else 1

    def _vf_metrics(sc: float) -> tuple[int, int, int, int]:
        thick_n = _vf_thick(sc)
        thick_b = max(thick_n + 2, 3) if _any_bold else thick_n
        (_rw, th), bl = cv2.getTextSize("|pqgy", font, sc, thick_b)
        line_step = max(th + 8, int(th + bl * 0.5) + 6)
        return thick_n, thick_b, th, line_step

    def _vf_row_width(text: str, sc: float, is_bold: bool) -> int:
        thick_n, thick_b, _th, _ls = _vf_metrics(sc)
        return int(cv2.getTextSize(text, font, sc, thick_b if is_bold else thick_n)[0][0])

    def _vf_wrap(text: str, sc: float, is_bold: bool) -> list[str]:
        """Keep short fields on one line; wrap only when the row is too wide."""
        if _vf_row_width(text, sc, is_bold) <= max_w:
            return [text]
        parts = text.split(" ")
        lines: list[str] = []
        cur = ""

        def _flush() -> None:
            nonlocal cur
            if cur:
                lines.append(cur)
                cur = ""

        def _append_token(token: str) -> None:
            nonlocal cur
            trial = token if not cur else f"{cur} {token}"
            if _vf_row_width(trial, sc, is_bold) <= max_w:
                cur = trial
                return
            _flush()
            if _vf_row_width(token, sc, is_bold) <= max_w:
                cur = token
                return
            chunk = ""
            for ch in token:
                next_chunk = chunk + ch
                if chunk and _vf_row_width(next_chunk, sc, is_bold) > max_w:
                    lines.append(chunk)
                    chunk = ch
                else:
                    chunk = next_chunk
            cur = chunk

        for part in parts:
            _append_token(part)
        _flush()
        return lines or [text]

    # One readable size for every View 4 row. Long values wrap.
    sc = 0.64
    if H < 800:
        sc = 0.56
    elif H > 1400:
        sc = 0.72

    thick_n, _thick_b, th, line_step = _vf_metrics(sc)
    y = my_top + th
    color_dim = (220, 228, 238)
    color_bold = (255, 255, 255)
    y_limit = H - my_bot
    for raw, is_bold in rows:
        t_draw = max(thick_n + 2, 3) if is_bold else thick_n
        c = color_bold if is_bold else color_dim
        for piece in raw.splitlines() or [raw]:
            piece = piece.rstrip()
            if not piece:
                continue
            for row in _vf_wrap(piece, sc, is_bold):
                if y > y_limit:
                    return out
                cv2.putText(out, row, (mx, y), font, sc, c, t_draw, cv2.LINE_AA)
                y += line_step
    return out
