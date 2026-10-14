"""Clock saver / pausesaver / idle-activity decisions.

Extracted verbatim from ``bootstrap()`` (and, since pass 10, ``main()``) in
``pigeon_0_12.py``. Each function takes the app state it used to close over as
keyword-only arguments; the enclosing function binds them once with
``bind_deps`` so call sites are unchanged.
"""

from __future__ import annotations

import time
import numpy as np
import tkinter as tk
from pigeon.clock_saver_policy import pausesaver_hold_from_metadata_class
from pigeon.clock_saver_policy import player_reports_playing
from pigeon.clock_saver_policy import tick_pause_hold
from PIL import ImageFont
from pigeon.compositing import cv_resize_interp
import cv2
import os
from pigeon.clock_saver_policy import should_hold_paused_screen
from pigeon.clock_saver_policy import CLOCK_SAVER_PAUSED_AFTER_S
from pigeon.clock_saver_policy import clock_saver_due_for_no_content
from pigeon.clock_saver_policy import clock_saver_due_for_pause
import sys


def _bump_pigeon_user_activity(_event: object | None = None, *, _boot_clock_saver_until_playback, last_metadata_activity_mono, last_pigeon_user_activity_mono) -> None:
    """Marks local UI activity (theater idle-dim + dismiss metadata-idle clock saver)."""
    now_act = time.monotonic()
    last_pigeon_user_activity_mono[0] = now_act
    # Any Pigeon control (key, click, rotary, settings) exits the 2-minute saver.
    last_metadata_activity_mono[0] = now_act
    _boot_clock_saver_until_playback[0] = False


def _show_paused_row_overlay(*, _apple_tv_is_off, _atv_metadata_is_content_idle, apple_tv_auto_state, apple_tv_playback_clock) -> bool:
    """True when the player has substantive content loaded but is not actively playing."""
    if _apple_tv_is_off():
        return False
    lm_raw = apple_tv_auto_state.get("last_metadata")
    lm = lm_raw if isinstance(lm_raw, dict) else None
    if lm is None:
        return False
    if _atv_metadata_is_content_idle(lm):
        return False
    clk = apple_tv_playback_clock
    if clk.get("live_mode"):
        return False
    ds = str(lm.get("device_state") or "")
    if "Playing" in ds:
        return False
    if "Idle" in ds:
        try:
            from pigeon.display_confidence import playback_has_concluded

            return bool(playback_has_concluded(lm))
        except Exception:
            return False
    has_title = bool(
        str(lm.get("title") or "").strip()
        or str(lm.get("query") or "").strip()
        or str(lm.get("artist") or "").strip()
    )
    if clk.get("has_sync"):
        # A reported state like Seeking / Loading / Buffering is not paused;
        # only fall back to the clock when the player gave no state at all.
        if ds.strip():
            return "Paused" in ds or "Pause" in ds or "Stopped" in ds
        return not bool(clk.get("playing"))
    if not has_title:
        return False
    return "Paused" in ds or "Pause" in ds or "Stopped" in ds


def _vol_norm_for_clock_saver(vol_raw: object) -> str:
    if vol_raw is None:
        return ""
    try:
        v = float(vol_raw)
        if v != v:
            return ""
        return f"{v:.6g}"
    except (TypeError, ValueError):
        return str(vol_raw).strip()


def _bump_clock_saver_significant_device(*, last_clock_saver_significant_device_mono) -> None:
    last_clock_saver_significant_device_mono[0] = time.monotonic()


def _note_metadata_activity(now: float | None = None, *, last_metadata_activity_mono) -> None:
    """Refresh the 2-minute metadata-idle clock-saver stamp."""
    last_metadata_activity_mono[0] = float(
        time.monotonic() if now is None else now
    )


def _clear_reported_position_stall_stamp(*, last_metadata_activity_mono) -> None:
    """Reset metadata-idle saver stamp (device removed / location change)."""
    last_metadata_activity_mono[0] = time.monotonic()


def _coarse_device_state_for_saver(ds: str) -> str:
    d = str(ds or "").strip().lower()
    if "playing" in d:
        return "playing"
    if "paus" in d:
        return "paused"
    if (not d) or ("idle" in d) or ("stop" in d):
        return "idle"
    return d


def _reset_clock_saver_device_signal_baseline(*, _bump_clock_saver_significant_device, _cs_sig_ck, _cs_sig_ds, _cs_sig_fp, _cs_sig_init, _cs_sig_vol, _note_metadata_activity) -> None:
    _cs_sig_init[0] = False
    _cs_sig_ck[0] = None
    _cs_sig_ds[0] = ""
    _cs_sig_vol[0] = ""
    _cs_sig_fp[0] = ""
    _bump_clock_saver_significant_device()
    _note_metadata_activity()


def _something_playing_now(*, _apple_tv_is_off, _atv_metadata_is_content_idle, apple_tv_auto_state, apple_tv_playback_clock) -> bool:
    """True when the player reports active playback (not idle/home/paused-only).

    MRP often says Idle while HDMI is still playing a titled show. A
    held / displayable identity still counts as playing. A stale
    ``playback_clock.playing`` flag must not win over Paused / Stopped.
    """
    if _apple_tv_is_off():
        return False
    lm = apple_tv_auto_state.get("last_metadata")
    md = lm if isinstance(lm, dict) else {}
    if player_reports_playing(
        md.get("device_state"),
        clock_playing=bool(apple_tv_playback_clock.get("playing")),
    ):
        return True
    if not isinstance(lm, dict):
        return False
    ds = str(lm.get("device_state") or "")
    if "Paused" in ds or "Stopped" in ds:
        return False
    try:
        from pigeon.display_confidence import playback_has_concluded

        if playback_has_concluded(md):
            return False
    except Exception:
        pass
    return not _atv_metadata_is_content_idle(lm)


def _metadata_drives_clock_saver(*, apple_tv_auto_state, apple_tv_playback_clock) -> bool:
    """True when player metadata (not the HDMI unchanged-frame streak) owns clock-saver idle.

    Position progress is the primary signal. When metadata is driving, the
    HDMI 24-frame unchanged rule is ignored.
    """
    if bool(apple_tv_playback_clock.get("has_sync")):
        return True
    md = apple_tv_auto_state.get("last_metadata")
    if not isinstance(md, dict):
        return False
    try:
        from pigeon.display_confidence import player_metadata_adequate

        return bool(player_metadata_adequate(md))
    except Exception:
        return bool(str(md.get("query") or md.get("title") or "").strip())


def _clock_saver_idle_need() -> float:
    try:
        from pigeon.widgets.options_settings import clock_saver_idle_s

        return float(clock_saver_idle_s())
    except Exception:
        return 60.0


def _clock_saver_user_enabled() -> bool:
    try:
        from pigeon.widgets.options_settings import clock_saver_enabled

        return bool(clock_saver_enabled())
    except Exception:
        return True


def _pausesaver_is_holding(*, _player_metadata_class, _show_paused_row_overlay) -> bool:
    """True while paused/stopped content should age toward Clocksaver.

    A held title can still look like playback. Matching auto widgets'
    ``stopped`` class keeps the pause timer running instead of resetting.
    """
    try:
        return pausesaver_hold_from_metadata_class(_player_metadata_class())
    except Exception:
        return bool(_show_paused_row_overlay())


def _refresh_paused_row_stamp(now: float, *, _paused_row_last_hold_mono, _paused_row_since_mono, _pausesaver_is_holding) -> float:
    """Seconds the current title has stayed on Pausesaver; 0 if not holding."""
    paused = _pausesaver_is_holding()
    age, since, last = tick_pause_hold(
        paused,
        now,
        float(_paused_row_since_mono[0]),
        float(_paused_row_last_hold_mono[0]),
    )
    _paused_row_since_mono[0] = since
    _paused_row_last_hold_mono[0] = last
    return age


def _clock_saver_content_is_idle(*, _atv_metadata_is_content_idle, apple_tv_auto_state) -> bool:
    lm = apple_tv_auto_state.get("last_metadata")
    if not isinstance(lm, dict):
        return True
    return bool(_atv_metadata_is_content_idle(lm))


def _idle_saver_face_toggle_ok(now: float | None = None, *, _clock_saver_for_compose, _clock_startup_intro_opacity, startup_ph) -> bool:
    """Idle clock/meter face is up (not splash intro, not NP chrome)."""
    t = time.monotonic() if now is None else float(now)
    if _clock_startup_intro_opacity(t) is not None:
        return False
    if startup_ph[0] is not None:
        return False
    return bool(_clock_saver_for_compose(t))


def _audio_capture_wanted(now: float | None = None, *, _idle_audio_listen, _idle_audio_meter_active, _np_wants_live_audio, _settings_audio_led_listen) -> bool:
    if _idle_audio_meter_active(now):
        return True
    if _settings_audio_led_listen():
        return True
    if _np_wants_live_audio():
        return True
    return _idle_audio_listen(now)


def _clock_saver_dim_pre_digit_canvas(canvas: np.ndarray, dim: float) -> None:
    """Darken backdrop/gradient/mic before drawing saver glyphs so only the large time reads at full brilliance."""
    d = max(0.0, min(1.0, float(dim)))
    if d >= 1.0 - 1e-9:
        return
    canvas[:] = (canvas.astype(np.float32) * d).clip(0, 255).astype(np.uint8)


def _clock_saver_dim_overlay_bgra(patch_bgra: np.ndarray, dim: float) -> np.ndarray:
    """Idle-dim streaming badge / receiver rows during clock saver (alpha scale; callers may skip if dim≈1)."""
    d = max(0.0, min(1.0, float(dim)))
    if d >= 1.0 - 1e-9:
        return patch_bgra
    out = patch_bgra.copy().astype(np.float32)
    out[:, :, 3] *= d
    return np.clip(out, 0, 255).astype(np.uint8)


def _saver_layer_is_full_frame(
    canvas: np.ndarray,
    overlay_bgra: np.ndarray,
    rect: tuple[int, int, int, int],
) -> bool:
    sx, sy, sw, sh = (int(v) for v in rect)
    return (
        sx == 0
        and sy == 0
        and sw == int(canvas.shape[1])
        and sh == int(canvas.shape[0])
        and int(overlay_bgra.shape[0]) == int(canvas.shape[0])
        and int(overlay_bgra.shape[1]) == int(canvas.shape[1])
        and int(overlay_bgra.shape[2]) >= 3
    )


def _set_playback_overlay_clock_saver_volume_flag(*, _backdrop_active_for_view, _clock_saver_for_compose, _playback_is_netflix_stream, playback_overlay_flags, receiver_overlay_state) -> None:
    """True while clock saver is active and the receiver shows a real volume string."""
    from pigeon.widgets.playback_overlay import _receiver_volume_display_line

    vol = _receiver_volume_display_line(receiver_overlay_state.get("volume", ""))
    cs_ok = _clock_saver_for_compose(time.monotonic())
    nf_bd = bool(cs_ok and _backdrop_active_for_view() and _playback_is_netflix_stream())
    playback_overlay_flags["clock_saver_netflix_full_overlay"] = nf_bd
    playback_overlay_flags["clock_saver_volume_only"] = bool(
        cs_ok and vol and not nf_bd
    )


def _idle_audio_meter_active(now: float | None = None, *, _idle_saver_face_toggle_ok, audio_meter_face_enabled) -> bool:
    """True when the diagnostic SVG meter should replace the idle clock."""
    if audio_meter_face_enabled is None or not audio_meter_face_enabled():
        return False
    return _idle_saver_face_toggle_ok(now)


def _blit_saver_layers_design(
    canvas: np.ndarray,
    time_bgra: np.ndarray,
    t_rect: tuple[int, int, int, int],
    date_bgra: np.ndarray,
    d_rect: tuple[int, int, int, int],
    *,
    copy_full_bgr: bool = False,
    _saver_layer_is_full_frame, alpha_blend_bgra_over_bgr,
) -> None:
    """Blit saver layers. Full-frame meter art is opaque BGR — skip alpha."""
    for cs_bgra, rect in ((date_bgra, d_rect), (time_bgra, t_rect)):
        sx, sy, sw, sh = (int(v) for v in rect)
        if copy_full_bgr and _saver_layer_is_full_frame(canvas, cs_bgra, rect):
            np.copyto(canvas, cs_bgra[:, :, :3])
            continue
        roi2 = canvas[sy : sy + sh, sx : sx + sw]
        roi2[:] = alpha_blend_bgra_over_bgr(roi2, cs_bgra)


def _blit_saver_layers_target(
    base: np.ndarray,
    time_bgra: np.ndarray,
    t_rect: tuple[int, int, int, int],
    date_bgra: np.ndarray,
    d_rect: tuple[int, int, int, int],
    cap_w: int,
    cap_h: int,
    *,
    copy_full_bgr: bool = False,
    DESIGN_H, DESIGN_W, _design_rect_to_target, alpha_blend_bgra_over_bgr,
) -> None:
    for cs_bgra, rect in ((date_bgra, d_rect), (time_bgra, t_rect)):
        sx, sy, sw, sh = (int(v) for v in rect)
        x, y, rw, rh = _design_rect_to_target(sx, sy, sw, sh, cap_w, cap_h)
        _ch, _cw = cs_bgra.shape[:2]
        if (
            copy_full_bgr
            and sx == 0
            and sy == 0
            and sw == int(DESIGN_W)
            and sh == int(DESIGN_H)
            and int(x) == 0
            and int(y) == 0
            and int(rw) == int(base.shape[1])
            and int(rh) == int(base.shape[0])
        ):
            bgr = cs_bgra[:, :, :3]
            if _cw == rw and _ch == rh:
                np.copyto(base, bgr)
            else:
                np.copyto(
                    base,
                    cv2.resize(
                        bgr,
                        (rw, rh),
                        interpolation=cv_resize_interp(_cw, _ch, rw, rh),
                    ),
                )
            continue
        patch = cv2.resize(
            cs_bgra, (rw, rh), interpolation=cv_resize_interp(_cw, _ch, rw, rh)
        )
        sub = base[y : y + rh, x : x + rw]
        sub[:] = alpha_blend_bgra_over_bgr(sub, patch)


def _paused_screen_font(px: int, *, _paused_screen_font_cache) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(24, int(px))
    cached = _paused_screen_font_cache.get(size)
    if cached is not None:
        return cached
    paths = (
        os.environ.get("PIGEON_FONT_MEDIUM", ""),
        os.environ.get("PIGEON_FONT_EXTRABOLD", ""),
        os.environ.get("PIGEON_FONT", ""),
    )
    for fp in paths:
        if fp and os.path.isfile(fp):
            try:
                font = ImageFont.truetype(fp, size=size)
                _paused_screen_font_cache[size] = font
                return font
            except Exception:
                pass
    font = ImageFont.load_default()
    _paused_screen_font_cache[size] = font
    return font


def _compose_paused_screen(cap_w: int, cap_h: int, *, PAUSED_SCREEN_BACKDROP_DIM, _paused_screen_backdrop_bgr, _paused_screen_font) -> np.ndarray:
    from pigeon.paused_screen import compose_pausesaver_bgr

    src = _paused_screen_backdrop_bgr()
    font = _paused_screen_font(max(52, int(round(float(cap_h) * 0.13))))
    return compose_pausesaver_bgr(
        int(cap_w),
        int(cap_h),
        src,
        font=font,
        dim=PAUSED_SCREEN_BACKDROP_DIM,
    )


def _clock_saver_layer_opacity(now: float, *, CLOCK_SAVER_DIM_OPACITY, _boot_clock_saver_until_playback, _clock_startup_intro_opacity, _splash_reveal_clock, clock_saver_peek_until_mono) -> float:
    intro = _clock_startup_intro_opacity(now)
    if intro is not None:
        return float(intro)
    if now < clock_saver_peek_until_mono[0]:
        return 1.0
    # Boot / splash-reveal: full-on clock (no ease from black, no idle dim).
    if _boot_clock_saver_until_playback[0] or _splash_reveal_clock[0]:
        return 1.0
    return CLOCK_SAVER_DIM_OPACITY


def _paused_screen_active(*, DevPhase, _apply_auto_widget_policy, _clock_saver_active, _clock_saver_user_enabled, _paused_screen_backdrop_bgr, _show_paused_row_overlay, _vv_is_music, clock_saver_composite_bgra, clock_saver_force_on, dev_phase) -> bool:
    try:
        plan = _apply_auto_widget_policy()
        from pigeon.auto_widgets import (
            LAYOUT_ZONE6_PAUSESAVER,
            LAYOUT_ZONE10_PAUSESAVER,
        )

        if plan.layout == LAYOUT_ZONE10_PAUSESAVER:
            # Backdrop + zone-4 plate + zone-5 status are drawn by NP.
            return False
        if plan.layout == LAYOUT_ZONE6_PAUSESAVER:
            return False
    except Exception:
        pass
    if dev_phase[0] != DevPhase.OFF:
        return False
    paused = _show_paused_row_overlay()
    has_backdrop = _paused_screen_backdrop_bgr() is not None
    if paused and _vv_is_music():
        # Music pause still gets the plate even if artwork has not landed.
        has_backdrop = True
    saver_on = False
    if clock_saver_composite_bgra is not None and _clock_saver_user_enabled():
        now_ps = time.monotonic()
        saver_on = bool(_clock_saver_active(now_ps) or clock_saver_force_on[0])
    return should_hold_paused_screen(
        paused_with_content=paused,
        has_backdrop=has_backdrop,
        clock_saver_active=saver_on,
    )


def _apply_position_stall_grace_to_clock_saver(now: float, *, CLOCK_SAVER_POSITION_STALL_GRACE_S, last_clock_saver_significant_device_mono, last_timecode_motion_mono) -> None:
    """Keep the saver device-signal timer pinned to ``now`` while content position is live.

    The saver timer is "paused" (continually bumped to ``now``) for as long as the reported
    content position has advanced within :data:`CLOCK_SAVER_POSITION_STALL_GRACE_S`. Once the
    position stays flat beyond that window, we stop bumping and the existing 300 s
    ``CLOCK_SAVER_AFTER_S`` accumulator begins counting from the last advance. A fresh
    position advance during an already-open saver drops the dev-idle span back to zero here,
    so ``_clock_saver_active`` returns ``False`` on the very next tick → saver ends.
    """
    lm = last_timecode_motion_mono[0]
    if lm <= 0.0:
        return
    if (now - lm) >= CLOCK_SAVER_POSITION_STALL_GRACE_S:
        return
    last_clock_saver_significant_device_mono[0] = now


def _clock_saver_active(now: float, *, CLOCK_SAVER_METADATA_IDLE_AFTER_S, DevPhase, _apple_tv_is_off, _apply_position_stall_grace_to_clock_saver, _boot_clock_saver_until_playback, _clock_saver_content_is_idle, _clock_saver_idle_need, _clock_saver_user_enabled, _cs_meta_idle_log_mono, _cs_meta_idle_was_active, _metadata_drives_clock_saver, _note_metadata_activity, _pausesaver_is_holding, _program_audio_session, _refresh_paused_row_stamp, _resolve_receiver_lines_for_now_playing, _something_playing_now, _splash_reveal_clock, _tmdb_info_current_and_available, apple_tv_playback_clock, clock_saver_composite_bgra, dev_phase, last_clock_saver_significant_device_mono, last_metadata_activity_mono, last_pigeon_user_activity_mono, receiver_standby_holder, scene_enabled, startup_ph) -> bool:
    if clock_saver_composite_bgra is None:
        return False
    if not _clock_saver_user_enabled():
        return False
    if dev_phase[0] != DevPhase.OFF:
        return False
    paused_hold = _pausesaver_is_holding()
    paused_age = _refresh_paused_row_stamp(now)
    if clock_saver_due_for_pause(paused_hold, paused_age):
        return True
    if _program_audio_session():
        _boot_clock_saver_until_playback[0] = False
        return False
    try:
        inc_cs, cfg_cs, _vol_cs = _resolve_receiver_lines_for_now_playing()
    except Exception:
        inc_cs, cfg_cs = "", ""
    if (not bool(receiver_standby_holder[0])) and (
        str(inc_cs or "").strip() or str(cfg_cs or "").strip()
    ):
        _boot_clock_saver_until_playback[0] = False
        return False
    if _apple_tv_is_off():
        return True
    # Do not require ``scene_enabled``: view ONE now-playing (circles) commonly
    # runs with the video scene off, and the saver must still arm there.
    _apply_position_stall_grace_to_clock_saver(now)
    # TMDb art dismisses the boot saver, but does not block idle / position stall.
    if _tmdb_info_current_and_available():
        _boot_clock_saver_until_playback[0] = False
    # Boot: if nothing is playing after splash, stay on the saver until playback
    # starts or a local control dismisses it.
    if _boot_clock_saver_until_playback[0]:
        if _something_playing_now() or _program_audio_session():
            _boot_clock_saver_until_playback[0] = False
            _note_metadata_activity(now)
        elif startup_ph[0] is None or _splash_reveal_clock[0]:
            return True
    if clock_saver_due_for_no_content(
        playing=_something_playing_now(),
        paused_with_content=paused_hold,
        live=bool(apple_tv_playback_clock.get("live_mode")),
        content_idle=_clock_saver_content_is_idle(),
        incoming_audio=_program_audio_session(),
    ):
        return True
    # HDMI-only: 24 consecutive unchanged HDMI frames → saver.
    # Ignored while player metadata is driving (position is authoritative).
    if not _metadata_drives_clock_saver():
        try:
            from pigeon.hdmi_capture import hdmi_clock_saver_due
            if hdmi_clock_saver_due():
                return True
        except Exception:
            pass
    # Content metadata + HDMI unchanged for 2 min → saver until content changes
    # **or** any local Pigeon control is used. Position not advancing is primary.
    lma = float(last_metadata_activity_mono[0])
    meta_age = (now - lma) if lma > 0.0 else 0.0
    ui_age = now - float(last_pigeon_user_activity_mono[0])
    meta_idle = (
        lma > 0.0
        and meta_age >= CLOCK_SAVER_METADATA_IDLE_AFTER_S
        and ui_age >= CLOCK_SAVER_METADATA_IDLE_AFTER_S
    )
    if meta_idle != _cs_meta_idle_was_active[0] or (
        now - float(_cs_meta_idle_log_mono[0])
    ) >= 30.0:
        _cs_meta_idle_log_mono[0] = now
        _cs_meta_idle_was_active[0] = bool(meta_idle)
        sys.stderr.write(
            f"pigeon: clock_saver meta_idle age={meta_age:.0f}s "
            f"ui_age={ui_age:.0f}s need={CLOCK_SAVER_METADATA_IDLE_AFTER_S:.0f}s "
            f"pause_age={paused_age:.0f}s pause_need={CLOCK_SAVER_PAUSED_AFTER_S:.0f}s "
            f"active={bool(meta_idle)} boot={bool(_boot_clock_saver_until_playback[0])} "
            f"scene={bool(scene_enabled[0])} phase={dev_phase[0]!s}\n"
        )
        sys.stderr.flush()
    if meta_idle:
        return True
    ui_idle = (now - float(last_pigeon_user_activity_mono[0])) >= _clock_saver_idle_need()
    dev_idle = (now - float(last_clock_saver_significant_device_mono[0])) >= _clock_saver_idle_need()
    return ui_idle and dev_idle


def _atv_idle_monochrome_active(*, THEATER_IDLE_DIM_AFTER_S, apple_tv_playback_clock, current_apple_tv, last_atv_interaction_mono, last_pigeon_user_activity_mono) -> bool:
    """True when theater idle-dim should be fully on (both ATV and Pigeon quiet long enough)."""
    if not current_apple_tv.get("identifier"):
        return False
    # Live TV and some streams never advance ``position``; metadata stays stable for minutes.
    # Without this guard, we never bump ``last_atv_interaction_mono`` and the red idle overlay
    # kicks in after THEATER_IDLE_DIM_AFTER_S even though pyatv still reports Playing.
    if bool(apple_tv_playback_clock.get("playing")):
        return False
    now = time.monotonic()
    pigeon_quiet = (now - last_pigeon_user_activity_mono[0]) >= THEATER_IDLE_DIM_AFTER_S
    if not pigeon_quiet:
        return False
    if last_atv_interaction_mono[0] <= 0.0:
        return True
    return (now - last_atv_interaction_mono[0]) >= THEATER_IDLE_DIM_AFTER_S


def _app_logo_clock_saver_style_now(*, _clock_saver_for_compose, backdrop_app_logo_letterbox_fit) -> bool:
    """Dim, row-2–top app logo layout when there is no TMDb still (letterbox master) in saver contexts."""
    if not backdrop_app_logo_letterbox_fit[0]:
        return False
    return _clock_saver_for_compose(time.monotonic())


def _clock_saver_backdrop_brightness(now: float, *, CLOCK_SAVER_BACKDROP_DIM, _backdrop_active_for_view, _clock_saver_for_compose, backdrop_master_bgr) -> float:
    """1 = full brightness; idle clock-saver on backdrop uses ``CLOCK_SAVER_BACKDROP_DIM``."""
    if not _backdrop_active_for_view() or backdrop_master_bgr[0] is None:
        return 1.0
    if not _clock_saver_for_compose(now):
        return 1.0
    return float(CLOCK_SAVER_BACKDROP_DIM)


def _bump_clock_saver_significant_device_from_metadata(md: dict[str, object], *, _bump_clock_saver_significant_device, _coarse_device_state_for_saver, _content_key_from_metadata, _cs_sig_ck, _cs_sig_ds, _cs_sig_fp, _cs_sig_init, _cs_sig_vol, _metadata_activity_fingerprint, _note_metadata_activity, _vol_norm_for_clock_saver) -> None:
    """Content/play-state changes postpone savers; volume only affects the 300 s path."""
    ck = _content_key_from_metadata(md)
    ds = _coarse_device_state_for_saver(str(md.get("device_state") or ""))
    vk = _vol_norm_for_clock_saver(md.get("volume_percent"))
    fp = _metadata_activity_fingerprint(md)
    if not _cs_sig_init[0]:
        _cs_sig_init[0] = True
        _cs_sig_ck[0] = ck
        _cs_sig_ds[0] = ds
        _cs_sig_vol[0] = vk
        _cs_sig_fp[0] = fp
        _note_metadata_activity()
        return
    content_bump = fp != _cs_sig_fp[0]
    # Keep legacy ck/ds tracking for diagnostics; content fingerprint is authoritative.
    if ck != _cs_sig_ck[0] and (ck or _cs_sig_ck[0]):
        content_bump = True
    if ds != _cs_sig_ds[0]:
        content_bump = True
    _cs_sig_ck[0] = ck
    _cs_sig_ds[0] = ds
    _cs_sig_vol[0] = vk
    _cs_sig_fp[0] = fp
    if content_bump:
        _bump_clock_saver_significant_device()
        _note_metadata_activity()


def _idle_audio_listen(now: float | None = None, *, _clock_saver_for_compose, _view_one_uses_now_playing_screen) -> bool:
    """Keep ALSA open on the clock saver so incoming audio can wake NP."""
    if not _view_one_uses_now_playing_screen():
        return False
    t = time.monotonic() if now is None else float(now)
    try:
        return bool(_clock_saver_for_compose(t))
    except Exception:
        return False


def _nudge_clock_saver_volume(action: str, *, _clock_saver_for_compose, _clock_saver_volume, _clock_saver_volume_raw, _note_volume_graphics, _note_zone3_volume_takeover, _sync_now_playing_screen_state, _view_one_uses_now_playing_screen, clock_saver_force_on, denon_vol_cache, receiver_overlay_state, render_once, skip_cache) -> None:
    """Move the saver line immediately; the AVR poll confirms the real level."""
    from pigeon.widgets.clock_saver import step_clock_saver_volume

    cur = _clock_saver_volume_raw()
    if not cur:
        try:
            cur = str(denon_vol_cache.get("np_hold") or "").strip()
        except NameError:
            cur = ""
        if not cur:
            try:
                cur = str(_clock_saver_volume.hold or "").strip()
            except Exception:
                cur = ""
    nxt = step_clock_saver_volume(
        cur,
        action,
        unmute_to=_clock_saver_volume.pre_mute or None,
    )
    if nxt:
        _clock_saver_volume.remember(nxt, source="nudge")
        _note_zone3_volume_takeover()
        _note_volume_graphics(nxt)
        try:
            receiver_overlay_state["volume"] = nxt
        except NameError:
            pass
        try:
            denon_vol_cache["effective"] = nxt
            denon_vol_cache["np_hold"] = nxt
        except NameError:
            pass
    skip_cache[0] = None
    saver_up = False
    try:
        saver_up = bool(
            _clock_saver_for_compose(time.monotonic()) or clock_saver_force_on[0]
        )
    except Exception:
        saver_up = False
    if not saver_up:
        try:
            if _view_one_uses_now_playing_screen():
                _sync_now_playing_screen_state()
        except Exception:
            pass
    try:
        render_once()
    except Exception:
        pass


def _update_idle_dim_strength(now: float, *, ATV_IDLE_MONO_ANIM_S, THEATER_IDLE_DIM_ENABLED, _atv_idle_monochrome_active, _idle_dim_anim_from, _idle_dim_anim_goal, _idle_dim_anim_t0, idle_dim_anim_strength) -> float:
    """0 = full color, 1 = red luma-mono; eases in/out over ATV_IDLE_MONO_ANIM_S when combined idle state changes."""
    if not THEATER_IDLE_DIM_ENABLED:
        if idle_dim_anim_strength[0] != 0.0 or _idle_dim_anim_goal[0] != 0.0:
            idle_dim_anim_strength[0] = 0.0
            _idle_dim_anim_goal[0] = 0.0
            _idle_dim_anim_from[0] = 0.0
            _idle_dim_anim_t0[0] = now
        return 0.0
    want = 1.0 if _atv_idle_monochrome_active() else 0.0
    if want != _idle_dim_anim_goal[0]:
        _idle_dim_anim_goal[0] = want
        _idle_dim_anim_from[0] = idle_dim_anim_strength[0]
        _idle_dim_anim_t0[0] = now
    dur = float(ATV_IDLE_MONO_ANIM_S)
    t = min(1.0, (now - _idle_dim_anim_t0[0]) / dur) if dur > 0 else 1.0
    idle_dim_anim_strength[0] = _idle_dim_anim_from[0] + (_idle_dim_anim_goal[0] - _idle_dim_anim_from[0]) * t
    return idle_dim_anim_strength[0]


def _paused_screen_backdrop_bgr(*, _circles_poster_bgra, _paused_screen_artwork_bgr, _stable_bgr_from_bgra, _vv_is_music, backdrop_app_logo_letterbox_fit, backdrop_master_bgr, saved_backdrop_app_logo_letterbox_fit, saved_backdrop_master_bgr) -> np.ndarray | None:
    """Full-screen paused still: TMDb backdrop, else poster / YouTube thumb."""
    if _vv_is_music():
        art = _paused_screen_artwork_bgr()
        if art is not None:
            return art
    if backdrop_master_bgr[0] is not None and not backdrop_app_logo_letterbox_fit[0]:
        return backdrop_master_bgr[0]
    if (
        saved_backdrop_master_bgr[0] is not None
        and not saved_backdrop_app_logo_letterbox_fit[0]
    ):
        return saved_backdrop_master_bgr[0]
    try:
        poster = _circles_poster_bgra()
    except Exception:
        poster = None
    return _stable_bgr_from_bgra(poster)


def _toggle_clock_saver_force(event: tk.Event | None = None, *, _PIGEON_EXT, _boot_clock_saver_until_playback, _bump_clock_saver_significant_device, _bump_pigeon_user_activity, _clock_saver_for_compose, _note_metadata_activity, _widget_accepts_typing, clock_saver_composite_bgra, clock_saver_force_on, render_once, skip_cache) -> str | None:
    """Shift+2: force clock saver on/off."""
    if event is not None and _widget_accepts_typing(event.widget):
        return None
    if not _PIGEON_EXT or clock_saver_composite_bgra is None:
        return None
    now = time.monotonic()
    showing = bool(_clock_saver_for_compose(now))
    if showing or clock_saver_force_on[0]:
        clock_saver_force_on[0] = False
        _boot_clock_saver_until_playback[0] = False
        _bump_pigeon_user_activity(event)
        _note_metadata_activity(now)
        _bump_clock_saver_significant_device()
    else:
        clock_saver_force_on[0] = True
        if event is not None:
            _bump_pigeon_user_activity(event)
    skip_cache[0] = None
    try:
        render_once()
    except Exception:
        pass
    return "break"


def _manual_search_fallback() -> None:
    """Nothing is detected any more: show the SEARCH title, if one is pinned."""
    try:
        from pigeon import manual_search

        manual_search.on_content_idle()
    except Exception:
        pass


def _return_to_landing_if_atv_idle(metadata: dict[str, object], *, _PIGEON_EXT, _atv_metadata_is_content_idle, _clear_playback_artwork_caches, _disp_fit, _program_audio_session, _refresh_content_indicator, _resolve_receiver_lines_for_now_playing, _sync_now_playing_screen_state, _sync_status_bar_visibility_for_playback, _view_one_uses_now_playing_screen, _warm_status_bar_blits, _warm_tmdb_logo_patch, active_tmdb_display_title, active_tmdb_title_key, apple_tv_auto_state, apple_tv_playback_clock, backdrop_app_logo_letterbox_fit, backdrop_master_bgr, landing_scene_design_bgr, last_frame, playing, receiver_standby_holder, render_once, scaled_display, scaled_version, scene_enabled, skip_cache, status_bar_widget, tmdb_logo_app_fallback_active, tmdb_logo_patch_bgra, tmdb_logo_widget, tmdb_logo_widget_view_six, use_backdrop_scene) -> None:
    """When Apple TV reports no playback, drop TMDb backdrop and show the static landing page."""
    if not _atv_metadata_is_content_idle(metadata):
        return
    try:
        from pigeon import manual_search

        if manual_search.is_displaying():
            # Manual SEARCH title is up; idle polls must not wipe it every tick.
            return
    except Exception:
        pass
    try:
        from pigeon.display_confidence import (
            identity_displayable,
            metadata_has_holdable_identity,
            player_metadata_adequate,
        )

        if (
            identity_displayable(metadata)
            or player_metadata_adequate(metadata)
            or metadata_has_holdable_identity(metadata)
        ):
            return
        lm_hold = apple_tv_auto_state.get("last_metadata")
        if isinstance(lm_hold, dict) and (
            identity_displayable(lm_hold)
            or player_metadata_adequate(lm_hold)
            or metadata_has_holdable_identity(lm_hold)
        ):
            return
    except Exception:
        pass
    if _view_one_uses_now_playing_screen():
        if _program_audio_session():
            # Incoming audio is still holding NP through quiet scenes.
            return
        try:
            _inc_idle, _cfg_idle, _vol_idle = _resolve_receiver_lines_for_now_playing()
        except Exception:
            _inc_idle, _cfg_idle = "", ""
        if (not bool(receiver_standby_holder[0])) and (
            str(_inc_idle or "").strip() or str(_cfg_idle or "").strip()
        ):
            return
        # Keep displayed TMDB art through brief idle polls, but clear the spawn
        # identity so the next title is not suppressed as "same tmdb_key".
        apple_tv_auto_state["tmdb_key"] = None
        apple_tv_auto_state["pending_tmdb"] = None
        _clear_playback_artwork_caches()
        clk = apple_tv_playback_clock
        clk["has_sync"] = False
        clk["playing"] = False
        clk["live_mode"] = False
        clk["latched_content_key"] = None
        clk["latched_total"] = None
        clk["display_played_sec"] = None
        clk["trt_next_fire_mono"] = None
        clk["sync_position"] = 0.0
        clk["sync_mono"] = time.monotonic()
        _sync_status_bar_visibility_for_playback(metadata)
        _sync_now_playing_screen_state()
        skip_cache[0] = None
        render_once()
        _manual_search_fallback()
        return
    apple_tv_auto_state["content_key"] = None
    apple_tv_auto_state["tmdb_key"] = None
    apple_tv_auto_state["query"] = None
    apple_tv_auto_state["prefer"] = "auto"
    apple_tv_auto_state["pending_tmdb"] = None
    apple_tv_auto_state["last_tmdb_fetch_input"] = None
    apple_tv_auto_state["last_tmdb_fetch_refined"] = None
    apple_tv_auto_state["last_tmdb_fetch_prefer"] = None
    _clear_playback_artwork_caches()
    lm = apple_tv_auto_state.get("last_metadata")
    if isinstance(lm, dict):
        lm["query"] = ""
        lm["content_key"] = None

    had_art = bool(use_backdrop_scene[0] or backdrop_master_bgr[0] is not None or active_tmdb_title_key[0])

    use_backdrop_scene[0] = False
    backdrop_master_bgr[0] = None
    try:
        from pigeon.paused_screen import set_pausesaver_backdrop

        set_pausesaver_backdrop(None, clear=True)
    except Exception:
        pass
    backdrop_app_logo_letterbox_fit[0] = False
    playing[0] = False
    active_tmdb_title_key[0] = None
    active_tmdb_display_title[0] = None
    tmdb_logo_app_fallback_active[0] = False
    if tmdb_logo_widget is not None:
        tmdb_logo_widget.clear_cache()
    if tmdb_logo_widget_view_six is not None:
        tmdb_logo_widget_view_six.clear_cache()
    tmdb_logo_patch_bgra[0] = None
    _warm_tmdb_logo_patch()

    clk = apple_tv_playback_clock
    clk["has_sync"] = False
    clk["playing"] = False
    clk["live_mode"] = False
    clk["latched_content_key"] = None
    clk["latched_total"] = None
    clk["display_played_sec"] = None
    clk["trt_next_fire_mono"] = None
    clk["sync_position"] = 0.0
    clk["sync_mono"] = time.monotonic()

    if status_bar_widget is not None and status_bar_widget.set_accent_from_backdrop_bgr(None):
        _warm_status_bar_blits()

    _sync_status_bar_visibility_for_playback(metadata)

    if scene_enabled[0]:
        last_frame[0] = landing_scene_design_bgr
        if not _PIGEON_EXT:
            scaled_display[0] = _disp_fit().scale_and_crop(last_frame[0])
        else:
            scaled_display[0] = None
    scaled_version[0] += 1
    skip_cache[0] = None
    _refresh_content_indicator()

    if had_art:
        render_once()
    _manual_search_fallback()


def _auto_widget_signals(*, _apple_tv_is_off, _clock_saver_receiver_off, _paused_screen_backdrop_bgr, _player_metadata_class, _program_audio_session, _refresh_paused_row_stamp, current_apple_tv, main_settings_widget, view_circles_widget):
    from pigeon.auto_widgets import (
        AutoWidgetSignals,
        note_wan_status,
        reliable_clock_now,
        room_is_renamed,
    )

    wan_ok = False
    room_name = ""
    if main_settings_widget is not None:
        try:
            st_aw = main_settings_widget.state
            wan_ok = bool(st_aw.wifi_configured)
            room_name = str(st_aw.location_name or "").strip()
        except Exception:
            pass
    if not wan_ok:
        try:
            from pigeon.wifi_scan import current_connected_ssid

            wan_ok = bool(str(current_connected_ssid() or "").strip())
        except Exception:
            pass
    wan_boot = note_wan_status(wan_ok)
    receiver_off = _clock_saver_receiver_off()
    recv_name = ""
    try:
        from pigeon.runtime_state import core_state

        recv_name = str(getattr(core_state().receiver, "name", "") or "").strip()
    except Exception:
        pass
    if not recv_name:
        try:
            stc = getattr(view_circles_widget, "_state", None)
            recv_name = str(getattr(stc, "receiver_name", "") or "").strip()
        except Exception:
            pass
    player_ok = False
    try:
        player_ok = bool(current_apple_tv.get("identifier")) and (
            not _apple_tv_is_off()
        )
    except Exception:
        player_ok = not _apple_tv_is_off()
    audio = False
    try:
        from pigeon.widgets.audio_meter_saver import program_audio_present

        audio = bool(program_audio_present())
    except Exception:
        audio = bool(_program_audio_session())
    if not room_name:
        try:
            from pigeon.app_state import read_current_location_name

            room_name = str(read_current_location_name() or "").strip()
        except Exception:
            pass
    renamed = room_is_renamed(room_name)
    paused_for = 0.0
    try:
        paused_for = _refresh_paused_row_stamp(time.monotonic())
    except Exception:
        paused_for = 0.0
    pausesaver_art = False
    try:
        from pigeon.paused_screen import pausesaver_art_usable, pausesaver_backdrop

        src = _paused_screen_backdrop_bgr()
        pausesaver_art = pausesaver_art_usable(src) or pausesaver_art_usable(
            pausesaver_backdrop()
        )
    except Exception:
        pausesaver_art = False
    return AutoWidgetSignals(
        wan_ok=wan_ok,
        wan_ok_at_startup=wan_boot,
        lan_ok=bool(player_ok or (not receiver_off)),
        reliable_clock=reliable_clock_now(),
        receiver_ok=not receiver_off,
        receiver_name=recv_name,
        player_metadata=_player_metadata_class(),
        audio_levels=audio,
        audio_identification=False,
        room_renamed=renamed,
        room_name=room_name if renamed else "",
        paused_for_s=paused_for,
        pausesaver_art=pausesaver_art,
        visualizer_mode=_visualizer_mode_active(),
        zone11=_zone11_selected(),
    )


def _zone11_selected() -> bool:
    try:
        from pigeon.widgets.options_settings import zone11_selected

        return bool(zone11_selected())
    except Exception:
        return False


def _visualizer_mode_active() -> bool:
    try:
        from pigeon import visualizer_mode

        return visualizer_mode.is_active()
    except Exception:
        return False


# (frame token, plan): the policy resolved once per scheduled render.
_POLICY_THIS_FRAME: list[object] = [None, None]


def _apply_auto_widget_policy(*, DevPhase, _auto_widget_signals, _paused_screen_backdrop_bgr, active_tmdb_title_key, apple_tv_auto_state, dev_phase, main_settings_widget, skip_cache):
    from pigeon.auto_widgets import resolve_auto_widgets, set_live_plan
    from pigeon.core import frame_scope
    from pigeon.paused_screen import set_pausesaver_backdrop

    # Asked ~10 times while one frame is composed; the first answer holds for
    # the rest of that frame. Outside a scheduled render, always recompute.
    tok = frame_scope.token()
    if tok is not None and _POLICY_THIS_FRAME[0] == tok:
        return _POLICY_THIS_FRAME[1]
    plan = resolve_auto_widgets(_auto_widget_signals())
    set_live_plan(plan)
    try:
        src = _paused_screen_backdrop_bgr()
        key = str(active_tmdb_title_key[0] or "").strip()
        if not key:
            md_bd = apple_tv_auto_state.get("last_metadata")
            if isinstance(md_bd, dict):
                key = str(
                    md_bd.get("content_key")
                    or md_bd.get("title")
                    or md_bd.get("query")
                    or ""
                ).strip()
        set_pausesaver_backdrop(src, content_key=key)
    except NameError:
        pass
    except Exception:
        pass
    if main_settings_widget is not None:
        try:
            st_aw = main_settings_widget.state
            want = bool(plan.settings_exit_enabled)
            if bool(st_aw.exit_enabled) != want:
                st_aw.exit_enabled = want
                st_aw.ensure_focus_ring()
                main_settings_widget.invalidate()
        except Exception:
            pass
    if plan.force_settings and dev_phase[0] != DevPhase.MAIN_SETTINGS:
        if main_settings_widget is not None:
            try:
                if main_settings_widget.state.keyboard_open:
                    main_settings_widget.state.close_keyboard(commit=False)
                main_settings_widget.prefetch_scans_for_settings()
            except Exception:
                pass
        dev_phase[0] = DevPhase.MAIN_SETTINGS
        skip_cache[0] = None
    if tok is not None:
        _POLICY_THIS_FRAME[0], _POLICY_THIS_FRAME[1] = tok, plan
    return plan


def _clock_saver_for_compose(now: float, *, DevPhase, DisplayView, _apply_auto_widget_policy, _clock_saver_active, _clock_startup_intro_opacity, _effective_display_view, _refresh_paused_row_stamp, _splash_reveal_clock, _tmdb_info_current_and_available, clock_saver_composite_bgra, clock_saver_force_on, dev_phase, scene_enabled, startup_ph) -> bool:
    """True when the large saver time/date patches should be drawn (idle path)."""
    if clock_saver_composite_bgra is None:
        return False
    if _clock_startup_intro_opacity(now) is not None:
        if _tmdb_info_current_and_available():
            return False
        return True
    if dev_phase[0] != DevPhase.OFF:
        return False
    # Splash overlay: keep underlay black until reveal frame, then paint clock under PNG alpha.
    if startup_ph[0] is not None:
        return bool(_splash_reveal_clock[0])
    ev = _effective_display_view()
    if ev == DisplayView.FOUR:
        return False
    # View ONE now-playing may run with scene off; still allow the idle saver.
    if (not scene_enabled[0]) and ev != DisplayView.ONE:
        return False
    try:
        plan = _apply_auto_widget_policy()
        from pigeon.auto_widgets import (
            LAYOUT_SETTINGS,
            LAYOUT_ZONE6_CLOCKSAVER,
            LAYOUT_ZONE6_PAUSESAVER,
            LAYOUT_ZONE8_CLOCKSAVER,
            LAYOUT_ZONE10_PAUSESAVER,
        )

        if plan.force_settings or plan.layout == LAYOUT_SETTINGS:
            return False
        if plan.layout == LAYOUT_ZONE8_CLOCKSAVER:
            return True
        if plan.layout in (
            LAYOUT_ZONE6_PAUSESAVER,
            LAYOUT_ZONE10_PAUSESAVER,
        ):
            from pigeon.clock_saver_policy import pausesaver_due_for_clocksaver

            if pausesaver_due_for_clocksaver(_refresh_paused_row_stamp(now)):
                return True
            return False
        if plan.layout == LAYOUT_ZONE6_CLOCKSAVER:
            return False
    except Exception:
        pass
    if clock_saver_force_on[0]:
        return True
    return _clock_saver_active(now)


def _note_zone3_volume_takeover(*, view_circles_widget_holder) -> None:
    """Hold the NP volume widget in zone 3 for 7s after an adjustment."""
    try:
        if view_circles_widget_holder[0] is not None:
            view_circles_widget_holder[0].note_volume_adjustment()
    except NameError:
        pass
    except Exception:
        pass


def _note_volume_graphics(raw: object, *, _clock_saver_volume, _note_zone3_volume_takeover, _volume_lines) -> None:
    prev_label = str(getattr(_volume_lines, "last_label", "") or "")
    try:
        _volume_lines.note(raw)
    except Exception:
        pass
    # Arms and Digital-7 must track the same string. A later fat poll
    # must not paint a stale ``effective`` after this reveal.
    new_label = str(getattr(_volume_lines, "last_label", "") or "")
    if not new_label or new_label == prev_label:
        return
    if prev_label:
        _note_zone3_volume_takeover()
    try:
        if _clock_saver_volume.is_stale_poll(raw):
            return
        _clock_saver_volume.remember(raw, source="poll")
    except Exception:
        pass


def _remember_clock_saver_volume(raw: object, *, source: str = "poll", _clock_saver_volume) -> str:
    """Keep the last displayable saver volume; empty / stale polls do not clear it."""
    return _clock_saver_volume.remember(raw, source=source)


def _clock_saver_receiver_off(*, receiver_standby_holder) -> bool:
    """True when the AVR is in standby or not answering — hide the saver volume."""
    try:
        if bool(receiver_standby_holder[0]):
            return True
    except NameError:
        pass
    try:
        from pigeon.runtime_state import core_state

        rx = core_state().receiver
        if bool(getattr(rx, "standby", False)):
            return True
        if not bool(getattr(rx, "reachable", False)):
            return True
    except Exception:
        pass
    return False


def _clock_saver_volume_raw(*, _clock_saver_volume, denon_vol_cache, receiver_overlay_state, view_circles_widget_holder) -> str:
    """AVR master volume for the saver + NP disc (box 3)."""
    try:
        shown = str(_clock_saver_volume.display_line() or "").strip()
        if shown:
            return shown
    except Exception:
        pass
    candidates: list[object] = []
    try:
        candidates.append(denon_vol_cache.get("effective"))
        candidates.append(denon_vol_cache.get("np_hold"))
    except NameError:
        pass
    try:
        candidates.append(receiver_overlay_state.get("volume"))
    except NameError:
        pass
    try:
        from pigeon.runtime_state import core_state

        candidates.append(core_state().receiver.volume)
    except Exception:
        pass
    try:
        st = getattr(view_circles_widget_holder[0], "_state", None)
        candidates.append(getattr(st, "volume", ""))
    except NameError:
        pass
    except Exception:
        pass
    return _clock_saver_volume.pick(candidates)


def _rasterize_clock_saver_window_bgr(*, DESIGN_H, DESIGN_W, UI_TARGET_H, UI_TARGET_W, WINDOW_H, WINDOW_W, _clock_saver_layers, _present_frame_to_display, alpha_blend_bgra_over_bgr, clock_saver_composite_bgra) -> np.ndarray | None:
    """Full-window BGR clock saver, or None."""
    if clock_saver_composite_bgra is None or alpha_blend_bgra_over_bgr is None:
        return None
    try:
        dw = int(DESIGN_W) if int(DESIGN_W) > 0 else int(UI_TARGET_W)
        dh = int(DESIGN_H) if int(DESIGN_H) > 0 else int(UI_TARGET_H)
        canvas = np.zeros((dh, dw, 3), dtype=np.uint8)
        (time_bgra, t_rect), (date_bgra, d_rect) = _clock_saver_layers(
            shadow_bgr=None,
            layer_opacity=1.0,
            time_layer_opacity=1.0,
            date_layer_opacity=1.0,
        )
        for cs_bgra, (sx, sy, sw, sh) in (
            (date_bgra, d_rect),
            (time_bgra, t_rect),
        ):
            x0 = max(0, int(sx))
            y0 = max(0, int(sy))
            x1 = min(dw, x0 + int(sw))
            y1 = min(dh, y0 + int(sh))
            if x1 <= x0 or y1 <= y0:
                continue
            roi = canvas[y0:y1, x0:x1]
            patch = cs_bgra[0 : y1 - y0, 0 : x1 - x0]
            if patch.shape[0] != roi.shape[0] or patch.shape[1] != roi.shape[1]:
                continue
            roi[:] = alpha_blend_bgra_over_bgr(roi, patch)
        return np.ascontiguousarray(
            _present_frame_to_display(
                canvas, WINDOW_W, WINDOW_H, native_now_playing=True
            )
        )
    except Exception:
        return None


def _clock_saver_layers(*, _clock_saver_volume_raw, _volume_lines, clock_saver_composite_bgra, render_audio_meter_composite_bgra, **kwargs):
    try:
        from pigeon.auto_widgets import live_plan

        plan = live_plan()
    except Exception:
        plan = None
    if plan is not None:
        kwargs.setdefault("include_weather", not bool(plan.blank_weather))
        if plan.blank_volume:
            kwargs["volume"] = ""
            kwargs["line_opacity"] = 0.0
    if "volume" not in kwargs:
        kwargs["volume"] = _clock_saver_volume_raw()
    if "line_opacity" not in kwargs:
        try:
            kwargs["line_opacity"] = _volume_lines.opacity()
        except Exception:
            kwargs["line_opacity"] = 0.0
    replace = bool(kwargs.pop("replace_with_meter", False))
    if replace and render_audio_meter_composite_bgra is not None:
        op = kwargs.get("time_layer_opacity")
        if op is None:
            op = kwargs.get("layer_opacity", 1.0)
        return render_audio_meter_composite_bgra(layer_opacity=float(op))
    composite = clock_saver_composite_bgra(**kwargs)
    try:
        from pigeon import manual_search

        if manual_search.current_title() and manual_search.poster_allowed():
            poster = manual_search.poster_bgr()
            if poster is not None:
                from pigeon.widgets.clock_saver import compose_clock_with_poster

                op = kwargs.get("time_layer_opacity")
                if op is None:
                    op = kwargs.get("layer_opacity", 1.0)
                (frame, rect), date = composite
                frame = compose_clock_with_poster(frame, poster, opacity=float(op))
                return (frame, rect), date
    except Exception:
        pass
    return composite
