"""Apple TV target selection, HDMI frame-check scheduling, and receiver volume queueing.

Extracted verbatim from ``bootstrap()`` in ``pigeon_0_12.py``. Each function
takes the app state it used to close over as keyword-only arguments;
``bootstrap()`` binds them once with ``bind_deps`` so call sites are unchanged.
"""

from __future__ import annotations

import time
from pigeon.receiver.base import Relocatable
from pigeon.receiver.control import apply_rotary_action
from pigeon.receiver_link import get_receiver_link
from pigeon.app_state import read_last_receiver
from pigeon.app_state import read_saved_av_receiver
from pigeon.app_state import write_last_apple_tv
from pigeon.app_state import write_last_receiver
from pigeon.app_state import row_is_playback_apple_tv
from pigeon.runtime_paths import PIGEON_STATE_DIR_TILDE
import sys
import threading
import tkinter.messagebox as messagebox
from pigeon.app_state import advance_delegation_active
from pigeon.app_state import append_delegation_log_lines
from pigeon.app_state import read_current_location_id
from pigeon.app_state import read_saved_streaming_devices_all
from pigeon.clock_saver_policy import tmdb_should_skip_refetch_on_resume
from pigeon.app_state import clear_last_apple_tv
from pigeon.app_state import clear_last_receiver
from pigeon.app_state import read_saved_streaming_device
from pigeon.app_state import write_saved_av_receiver
import tkinter as tk


def _seed_current_apple_tv_from_streaming_slot(*, current_apple_tv, streaming_slot_holder) -> None:
    """Keep the poll target in sync with the location's saved player.

    ``current_apple_tv`` is initialized from ``last_apple_tv``. That key
    can be missing (Mac state after a location-only save, or a raced
    write) even when FAMILY ROOM still has Downstairs AppleTV. Without
    an identifier the poll tick returns immediately and the inspector
    / now-playing stay empty.
    """
    row = streaming_slot_holder[0]
    if not isinstance(row, dict):
        return
    ident = str(row.get("identifier") or "").strip()
    if not ident:
        return
    if str(current_apple_tv.get("identifier") or "").strip() == ident:
        if not str(current_apple_tv.get("address") or "").strip():
            current_apple_tv["address"] = str(row.get("address") or "").strip()
        return
    current_apple_tv.clear()
    current_apple_tv.update(
        {
            "identifier": ident,
            "address": str(row.get("address") or "").strip(),
            "name": str(row.get("name") or "").strip(),
            "label": str(row.get("label") or "").strip(),
        }
    )
    write_last_apple_tv(
        identifier=ident,
        address=str(row.get("address") or "").strip(),
        name=str(row.get("name") or "").strip() or None,
        label=str(row.get("label") or "").strip() or None,
    )


def describe_current_apple_tv(*, suffix: str | None = None, _refresh_content_indicator, apple_tv_status_var, current_apple_tv, receiver_http_host) -> None:
    if current_apple_tv.get("name"):
        play = f'Playback: {current_apple_tv["name"]}'
    elif current_apple_tv.get("label"):
        play = f'Playback: {current_apple_tv["label"]}'
    else:
        play = "Playback: none"
    rh = str(receiver_http_host.get("host") or "").strip()
    if rh:
        lr = read_last_receiver()
        nm = str(lr.get("name") or lr.get("label") or rh).strip() or rh
        ov = f"Overlay: {nm}"
    else:
        ov = "Overlay: none"
    base = f"{play}  ·  {ov}"
    if suffix:
        base = f"{base} ({suffix})"
    apple_tv_status_var.set(base)
    _refresh_content_indicator()


def begin_apple_tv_operation(status_suffix: str, *, apple_tv_busy, describe_current_apple_tv, set_apple_tv_controls_enabled) -> bool:
    if apple_tv_busy["active"]:
        describe_current_apple_tv(suffix="busy")
        return False
    apple_tv_busy["active"] = True
    set_apple_tv_controls_enabled(False)
    describe_current_apple_tv(suffix=status_suffix)
    return True


def end_apple_tv_operation(*, suffix: str | None = None, apple_tv_busy, describe_current_apple_tv, set_apple_tv_controls_enabled) -> None:
    apple_tv_busy["active"] = False
    set_apple_tv_controls_enabled(True)
    describe_current_apple_tv(suffix=suffix)


def _apply_hdmi_frame_check(changed, *, _bump_clock_saver_significant_device, _note_metadata_activity, _sync_now_playing_screen_state, apple_tv_auto_state) -> None:
    """A changed HDMI picture postpones the 2-minute metadata-idle saver."""
    apple_tv_auto_state["hdmi_check_in_flight"] = False
    if changed:
        _note_metadata_activity()
        _bump_clock_saver_significant_device()
    try:
        _sync_now_playing_screen_state()
    except Exception:
        pass


def _schedule_hdmi_frame_check_from_poll(*, _on_hdmi_frame_checked, apple_tv_auto_state) -> None:
    """Fingerprint an HDMI frame every few seconds (feeds the HDMI clock saver)."""
    try:
        from pigeon.hdmi_capture import frame_check_due, request_frame_check
    except Exception:
        return
    if apple_tv_auto_state.get("hdmi_check_in_flight"):
        return
    if not frame_check_due():
        return
    apple_tv_auto_state["hdmi_check_in_flight"] = True
    if not request_frame_check(_on_hdmi_frame_checked):
        apple_tv_auto_state["hdmi_check_in_flight"] = False


def _queue_receiver_volume_action(action: str, *, avr_slot_holder, receiver_power_on_pending) -> bool:
    """Fold one knob action into the receiver's pending intent (no I/O)."""
    row = avr_slot_holder[0]
    if not row:
        return False
    host = str(row.get("address") or row.get("identifier") or "").strip()
    if not host:
        return False
    rx = get_receiver_link().bind(host)
    if rx is None:
        return False
    return apply_rotary_action(rx, action, wake=bool(receiver_power_on_pending[0]))


def _receiver_readout_superseded(line: str) -> bool:
    """True while the knob is driving to a level ``line`` has not reached."""
    try:
        return get_receiver_link().readout_superseded(line)
    except Exception:
        return False


def _release_receiver(*, denon_vol_cache=None, receiver_overlay_state=None, receiver_standby_holder=None, receiver_debug_holder=None) -> None:
    """No receiver is selected: drop the link and everything derived from the old one."""
    try:
        get_receiver_link().release()
    except Exception:
        pass
    if denon_vol_cache is not None:
        denon_vol_cache["effective"] = ""
        denon_vol_cache["np_hold"] = ""
        denon_vol_cache["mono_usable"] = 0.0
        denon_vol_cache["bound_host"] = ""
    if receiver_overlay_state is not None:
        for key in ("incoming", "config", "volume", "input"):
            receiver_overlay_state[key] = ""
    if receiver_standby_holder is not None:
        receiver_standby_holder[0] = False
    if receiver_debug_holder is not None:
        receiver_debug_holder[0] = {}


def _bind_receiver_volume_hub(host: str) -> None:
    """Make sure the receiver link is bound to ``host`` (or the saved AV receiver).

    A saved location with no receiver releases the link; a failure to *read* the
    settings is temporary and leaves whatever is bound alone.
    """
    h = str(host or "").strip()
    if not h:
        try:
            row = read_saved_av_receiver()
        except Exception:
            return
        h = str((row or {}).get("address") or "").strip()
    if not h:
        _release_receiver()
        return
    try:
        get_receiver_link().bind(h)
    except Exception:
        pass


def _receiver_audio_fallback() -> tuple[str, str]:
    """Incoming format / sound mode straight from the receiver when the overlay has none."""
    st = get_receiver_link().state()
    if not st.connected or st.powered_on is False:
        return "", ""
    return st.audio_format, st.sound_mode


def _resolve_receiver_lines_for_now_playing(*, _clock_saver_volume_raw, _receiver_audio_fallback, apple_tv_auto_state, compose_playback_volume_widget_line, denon_vol_cache, receiver_overlay_state, receiver_standby_holder, streaming_slot_holder) -> tuple[str, str, str]:
    """Incoming/config/volume for View 1, with the receiver's own state as fallback."""
    standby = bool(receiver_standby_holder[0])
    inc = ""
    cfg = ""
    if not standby:
        inc = str(receiver_overlay_state.get("incoming") or "").strip()
        cfg = str(receiver_overlay_state.get("config") or "").strip()
        if not inc and not cfg:
            fb_inc, fb_cfg = _receiver_audio_fallback()
            inc, cfg = fb_inc, fb_cfg
    vol = _clock_saver_volume_raw()
    if not vol and compose_playback_volume_widget_line is not None:
        vol = compose_playback_volume_widget_line(
            stream_row=streaming_slot_holder[0],
            apple_tv_last_metadata=apple_tv_auto_state.get("last_metadata")
            if isinstance(apple_tv_auto_state.get("last_metadata"), dict)
            else None,
            denon_vol_effective=str(denon_vol_cache.get("effective") or ""),
            roku_tv_volume_percent="",
        )
    if not vol:
        raw_vol = str(receiver_overlay_state.get("volume") or "").strip()
        if raw_vol:
            # Accept dB, mute, percent, and bare 0–100 (player-reported).
            low = raw_vol.lower()
            if (
                low in ("mute", "muted", "off")
                or "db" in low
                or raw_vol.endswith("%")
                or (raw_vol.isdigit() and 0 <= int(raw_vol) <= 100)
                or raw_vol[:1] in "+-"
            ):
                vol = raw_vol
    if vol:
        denon_vol_cache["np_hold"] = vol
    else:
        # Keep last good readout so zone3 does not flash an empty ring
        # between AVR polls / while Apple TV reports volume_percent=0.
        held = str(denon_vol_cache.get("np_hold") or "").strip()
        if not held:
            held = str(denon_vol_cache.get("effective") or "").strip()
        vol = held
    return inc, cfg, vol


def _resolve_receiver_input_label(*, receiver_overlay_state, receiver_standby_holder) -> str:
    """Current AVR input label for the volume-widget caption."""
    if receiver_standby_holder[0]:
        return ""
    lab = str(receiver_overlay_state.get("input") or "").strip()
    if lab:
        return lab
    st = get_receiver_link().state()
    return st.input_label if st.connected and st.powered_on is not False else ""


def _on_hdmi_frame_checked(changed, *, _apply_hdmi_frame_check, apple_tv_auto_state, root) -> None:
    """Hand a finished HDMI frame check back to the Tk thread."""
    try:
        root.after(0, lambda c=changed: _apply_hdmi_frame_check(c))
    except Exception:
        # Tk gone / shutdown: clear the gate so checks are not stuck off forever.
        apple_tv_auto_state["hdmi_check_in_flight"] = False


def on_apple_tv_selected_then_tmdb(*, _PIGEON_EXT, _open_find_device_dialog, _pyatv_install_hint, apple_tv_busy, begin_apple_tv_operation, describe_current_apple_tv, end_apple_tv_operation, last_atv_interaction_mono, root, set_current_apple_tv, spawn_tmdb_poster_fetch, streaming_slot_holder) -> None:
    """Use the saved streaming slot: pyatv (Apple TV) or Roku ECP, then TMDb + backdrop."""
    if not _PIGEON_EXT:
        messagebox.showinfo("Devices", "Pigeon extensions not loaded.")
        return
    if apple_tv_busy["active"]:
        describe_current_apple_tv(suffix="busy")
        return
    row = streaming_slot_holder[0]
    if row is None:
        _open_find_device_dialog()
        return
    if not begin_apple_tv_operation("detecting content"):
        return

    def worker() -> None:
        ok_w, msg_w, title_w = False, "", None
        if row_is_playback_apple_tv(row):
            try:
                from pigeon.apple_tv_now_playing import fetch_now_playing_title_for_device

                ok_w, msg_w, title_w = fetch_now_playing_title_for_device(
                    device_identifier=row["identifier"],
                    device_address=row["address"],
                )
            except ImportError:
                ok_w, msg_w, title_w = (
                    False,
                    _pyatv_install_hint(),
                    None,
                )
            except Exception as e:
                ok_w, msg_w, title_w = False, str(e), None
        else:
            try:
                from pigeon.roku_ecp import (
                    fetch_roku_title_for_metadata,
                    resolve_roku_ecp_base_url_for_row,
                )

                rbase = resolve_roku_ecp_base_url_for_row(row)
                if not rbase:
                    ok_w, msg_w, title_w = (
                        False,
                        "",
                        None,
                    )
                else:
                    ok_w, msg_w, title_w = fetch_roku_title_for_metadata(
                        rbase, timeout=10.0
                    )
            except Exception as e:
                ok_w, msg_w, title_w = False, str(e), None

        def finish() -> None:
            if not row_is_playback_apple_tv(row) and not ok_w and not msg_w:
                end_apple_tv_operation()
                messagebox.showinfo(
                    "Devices",
                    "This Player is not an Apple TV (pyatv) row, and Pigeon could not use "
                    "Roku ECP on its IP (port 8060).\n\n"
                    "• If this is a Roku / Roku TV (e.g. Onn), ensure the TV’s IP is in the "
                    "Player slot and try again, or set \"roku_ecp_base_url\" in "
                    f"{PIGEON_STATE_DIR_TILDE}/state.json to http://TV_IP:8060\n"
                    "• For an actual Apple TV, re-add it from Find devices so the label "
                    "shows “Apple TV / tvOS”.\n"
                    "• For a receiver only, choose Receiver in Find device for the overlay.",
                )
                return
            if not ok_w:
                end_apple_tv_operation()
                messagebox.showerror("Devices", msg_w or "Could not read now playing.")
                return
            if not title_w:
                end_apple_tv_operation()
                messagebox.showinfo(
                    "Devices",
                    msg_w or "No title reported by the selected device.",
                )
                return
            from pigeon.tmdb_poster import is_degenerate_tmdb_query

            if is_degenerate_tmdb_query(title_w):
                end_apple_tv_operation()
                messagebox.showinfo(
                    "Devices",
                    "The device only reported app or channel branding, not the show or movie "
                    "title, so Pigeon did not search TMDb.\n\n"
                    "On Disney+ via Roku, wait until playback has started and try Manual fetch again.",
                )
                return
            set_current_apple_tv(row, persist=True)
            last_atv_interaction_mono[0] = time.monotonic()
            end_apple_tv_operation(suffix="title detected")
            sys.stderr.write(f"pigeon: {msg_w}\n")
            sys.stderr.flush()
            spawn_tmdb_poster_fetch(title_w, prefer="auto", force=True)

        root.after(0, finish)

    threading.Thread(target=worker, daemon=True).start()


def on_debug_streaming_slot_apple_tv(*, _PIGEON_EXT, _open_find_device_dialog, _pyatv_install_hint, apple_tv_busy, begin_apple_tv_operation, describe_current_apple_tv, end_apple_tv_operation, root, streaming_slot_holder) -> None:
    if not _PIGEON_EXT:
        messagebox.showinfo("Devices", "Pigeon extensions not loaded.")
        return
    if apple_tv_busy["active"]:
        describe_current_apple_tv(suffix="busy")
        return
    row = streaming_slot_holder[0]
    if row is None:
        _open_find_device_dialog()
        return
    if not row_is_playback_apple_tv(row):
        messagebox.showinfo(
            "Devices",
            "Metadata debug applies to Apple TV rows (label shows “Apple TV / tvOS”), not receivers.",
        )
        return
    if not begin_apple_tv_operation("debugging metadata"):
        return

    def worker() -> None:
        try:
            from pigeon.apple_tv_now_playing import debug_metadata_for_device

            ok_w, dump_w = debug_metadata_for_device(
                device_identifier=row["identifier"],
                device_address=row["address"],
            )
        except ImportError:
            ok_w, dump_w = (
                False,
                _pyatv_install_hint(),
            )
        except Exception as e:
            ok_w, dump_w = False, str(e)

        def finish() -> None:
            title = "Apple TV Metadata Debug"
            end_apple_tv_operation()
            if ok_w:
                messagebox.showinfo(title, dump_w)
            else:
                messagebox.showerror(title, dump_w)

        root.after(0, finish)

    threading.Thread(target=worker, daemon=True).start()


def _send_player_play_pause_hotkey(*, _PIGEON_EXT, apple_tv_busy, current_apple_tv, streaming_slot_holder) -> bool:
    """
    If a **Player** slot is set, send play/pause on a worker thread (Apple TV: pyatv;
    Roku: ECP). Returns True when a send was queued (so Space should not fall through).
    """
    if not _PIGEON_EXT:
        return False
    if apple_tv_busy["active"]:
        return False
    row = streaming_slot_holder[0]
    if not row:
        return False
    if row_is_playback_apple_tv(row):
        ident = str(current_apple_tv.get("identifier") or "").strip() or str(
            row.get("identifier") or ""
        ).strip()
        addr = str(current_apple_tv.get("address") or "").strip() or str(
            row.get("address") or ""
        ).strip()
        if not ident:
            return False
        if not addr:
            addr = ident

        try:
            from pigeon.apple_tv_now_playing import enqueue_apple_tv_remote_command

            if enqueue_apple_tv_remote_command(
                device_identifier=ident,
                device_address=addr,
                method_name="play_pause",
                scan_timeout_s=3,
            ):
                return True
        except Exception:
            pass
        return False
    try:
        from pigeon.roku_ecp import resolve_roku_ecp_base_url_for_row, roku_send_play_pause

        rbase = str(resolve_roku_ecp_base_url_for_row(row) or "").strip()
        if not rbase:
            return False
    except Exception:
        return False

    def _work_roku() -> None:
        try:
            from pigeon.roku_ecp import roku_send_play_pause

            roku_send_play_pause(base_url=rbase, timeout=3.0)
        except Exception:
            pass

    threading.Thread(target=_work_roku, daemon=True).start()
    return True


_RENDER_PENDING = [False]


def _request_render(root, render_once) -> None:
    """Paint once for a burst of receiver volume events.

    A full render costs ~200 ms on the Pi; one per confirmation and one per state
    change queue up behind a spinning encoder and the widget trails it by seconds.
    State is committed by the caller first, so the single render that runs sees
    the newest level.
    """
    if _RENDER_PENDING[0]:
        return
    _RENDER_PENDING[0] = True

    def run() -> None:
        _RENDER_PENDING[0] = False
        try:
            render_once()
        except Exception:
            pass

    try:
        root.after_idle(run)
    except Exception:
        _RENDER_PENDING[0] = False


def _commit_receiver_volume(vol: str, *, _clock_saver_volume, _note_volume_graphics, _remember_clock_saver_volume, denon_vol_cache, receiver_overlay_state) -> bool:
    """Write the box-3 AVR level into the widgets. True if it changed."""
    line = str(vol or "").strip()
    if not line:
        return False
    try:
        from pigeon.widgets.playback_overlay import _receiver_volume_display_line

        norm = _receiver_volume_display_line(line)
        if norm:
            line = norm
    except Exception:
        pass
    try:
        if _clock_saver_volume.is_stale_poll(line):
            return False
    except Exception:
        pass
    if _receiver_readout_superseded(line):
        return False
    prev = ""
    try:
        prev = str(denon_vol_cache.get("effective") or "")
    except NameError:
        prev = ""
    try:
        denon_vol_cache["effective"] = line
        denon_vol_cache["np_hold"] = line
    except NameError:
        pass
    try:
        receiver_overlay_state["volume"] = line
    except NameError:
        pass
    _remember_clock_saver_volume(line, source="poll")
    _note_volume_graphics(line)
    return prev != line


def _on_receiver_volume_changed(line: str, *, _clock_saver_for_compose, _commit_receiver_volume, _idle_audio_meter_active, _sync_now_playing_screen_state, _view_one_uses_now_playing_screen, _volume_lines, clock_saver_force_on, render_once, root, skip_cache) -> None:
    """The receiver reported a new level (remote, knob, app) — paint immediately."""
    if not line:
        return

    def apply() -> None:
        changed = _commit_receiver_volume(line)
        if not changed and not _volume_lines.fading():
            return
        if _idle_audio_meter_active():
            return
        skip_cache[0] = None
        try:
            if _view_one_uses_now_playing_screen() and not (
                _clock_saver_for_compose(time.monotonic())
                or clock_saver_force_on[0]
            ):
                _sync_now_playing_screen_state()
        except Exception:
            pass
        _request_render(root, render_once)

    try:
        root.after(0, apply)
    except Exception:
        pass


def _quick_receiver_volume_poll(*, _clock_saver_for_compose, _commit_receiver_volume, _idle_audio_meter_active, _sync_now_playing_screen_state, _view_one_uses_now_playing_screen, _volume_lines, clock_saver_force_on, render_once, skip_cache) -> None:
    """Paint the receiver's current level. Reads the cached state; the adapter does the I/O."""
    vol = get_receiver_link().state().volume_line
    if not vol:
        return
    changed = _commit_receiver_volume(vol)
    if not changed and not _volume_lines.fading():
        return
    if _idle_audio_meter_active():
        return
    skip_cache[0] = None
    try:
        if _view_one_uses_now_playing_screen() and not (
            _clock_saver_for_compose(time.monotonic()) or clock_saver_force_on[0]
        ):
            _sync_now_playing_screen_state()
    except Exception:
        pass
    try:
        render_once()
    except Exception:
        pass


# Longest a metadata poll may run before the worker is considered hung.
_APPLE_TV_POLL_STALL_S = 60.0


def _apple_tv_auto_poll_tick(*, APPLE_TV_FAIL_POLL_MAX_MS, APPLE_TV_IDLE_POLL_MS, APPLE_TV_POLL_MS, RECEIVER_POLL_MS, _PIGEON_EXT, _apple_tv_auto_poll_tick, _apple_tv_scan_timeout_s, _atv_metadata_is_content_idle, _bump_clock_saver_significant_device, _bump_clock_saver_significant_device_from_metadata, _clear_displayed_tmdb_art_for_content_change, _content_key_from_metadata, _idle_audio_meter_active, _pyatv_install_hint, _refresh_content_indicator, _refresh_observed_pairing_led_rows, _return_to_landing_if_atv_idle, _schedule_hdmi_frame_check_from_poll, _seed_current_apple_tv_from_streaming_slot, _store_music_artwork_from_metadata, _sync_status_bar_visibility_for_playback, _sync_streaming_badge_from_playback_sources, _tmdb_pref_from_metadata, _tmdb_spawn_identity_changed, _update_atv_interaction_from_poll_metadata, _update_status_bar_from_metadata, _warm_playback_overlay_blits, active_tmdb_title_key, apple_tv_auto_state, apple_tv_busy, apple_tv_dashboard_track, current_apple_tv, denon_vol_cache, playback_overlay_widget, receiver_overlay_state, receiver_standby_holder, render_once, resolve_metadata_tmdb_query, root, skip_cache, spawn_tmdb_poster_fetch, streaming_slot_holder) -> None:
    if apple_tv_auto_state.get("running"):
        stalled_s = time.monotonic() - float(
            apple_tv_auto_state.get("running_since") or time.monotonic()
        )
        if stalled_s < _APPLE_TV_POLL_STALL_S:
            root.after(APPLE_TV_POLL_MS, _apple_tv_auto_poll_tick)
            return
        # A hung worker would otherwise block every later poll, so the display
        # never sees another title. Abandon it; its late ``finish`` is ignored.
        sys.stderr.write(
            f"pigeon: apple_tv poll stalled {stalled_s:.0f}s; abandoning worker\n"
        )
        sys.stderr.flush()
        apple_tv_auto_state["running"] = False
    # Avoid overlapping pyatv scan/connect with discover / pairing / probe — reduces spurious TV pairing prompts.
    if apple_tv_busy["active"]:
        root.after(APPLE_TV_POLL_MS, _apple_tv_auto_poll_tick)
        return
    if not current_apple_tv.get("identifier"):
        _seed_current_apple_tv_from_streaming_slot()
    if not current_apple_tv.get("identifier") or not _PIGEON_EXT:
        _sync_streaming_badge_from_playback_sources(None)
        _sync_status_bar_visibility_for_playback(None)
        if _PIGEON_EXT:
            try:
                _schedule_hdmi_frame_check_from_poll()
            except Exception:
                pass
        root.after(APPLE_TV_POLL_MS, _apple_tv_auto_poll_tick)
        return
    apple_tv_auto_state["running"] = True
    apple_tv_auto_state["running_since"] = time.monotonic()
    poll_gen = int(apple_tv_auto_state.get("poll_gen") or 0) + 1
    apple_tv_auto_state["poll_gen"] = poll_gen
    next_poll_holder = [APPLE_TV_POLL_MS]
    device_identifier = current_apple_tv.get("identifier", "")
    device_address = current_apple_tv.get("address", "")

    def _poll_worker_body() -> None:
        try:
            from pigeon.apple_tv_now_playing import fetch_now_playing_info_for_device

            ok_w, msg_w, metadata_w = fetch_now_playing_info_for_device(
                device_identifier=device_identifier,
                device_address=device_address,
                scan_timeout_s=_apple_tv_scan_timeout_s(),
            )
        except ImportError:
            ok_w, msg_w, metadata_w = (
                False,
                _pyatv_install_hint(),
                None,
            )
        except Exception as e:
            ok_w, msg_w, metadata_w = False, str(e), None

        # Roku ECP calls can block for multi-second HTTP timeouts; never run them on the Tk thread
        # or the whole UI (including the mic visualizer) freezes on every poll cadence.
        wk_roku_nm: str | None = None
        md_poll_w = metadata_w if isinstance(metadata_w, dict) else None
        md_act_w = md_poll_w is not None and not _atv_metadata_is_content_idle(md_poll_w)
        pyatv_has_app_w = False
        if md_act_w:
            pyatv_has_app_w = bool(
                str(md_poll_w.get("app_name") or "").strip()
                or str(md_poll_w.get("app_id") or "").strip()
            )
        if not pyatv_has_app_w:
            try:
                from pigeon.roku_ecp import (
                    fetch_roku_active_app_name,
                    resolve_roku_ecp_base_url_for_row,
                )

                row0_wk = streaming_slot_holder[0]
                rb_wk = resolve_roku_ecp_base_url_for_row(row0_wk) if row0_wk else ""
                if rb_wk:
                    t_nm = fetch_roku_active_app_name(rb_wk)
                    if t_nm:
                        wk_roku_nm = t_nm
            except Exception:
                wk_roku_nm = None

        pyatv_tmdb_eligible_w = False
        if isinstance(metadata_w, dict):
            from pigeon.tmdb_poster import is_degenerate_tmdb_query

            _q_wk = (
                resolve_metadata_tmdb_query(metadata_w)
                if resolve_metadata_tmdb_query is not None
                else str(metadata_w.get("query") or "").strip()
            )
            if (
                _q_wk
                and not is_degenerate_tmdb_query(_q_wk)
                and not _atv_metadata_is_content_idle(metadata_w)
            ):
                pyatv_tmdb_eligible_w = True

        wk_roku_title: tuple[bool, str, str | None] | None = None
        if not pyatv_tmdb_eligible_w:
            row0_nf_wk = streaming_slot_holder[0]
            if row0_nf_wk is not None and not row_is_playback_apple_tv(row0_nf_wk):
                try:
                    from pigeon.roku_ecp import (
                        fetch_roku_title_for_metadata,
                        resolve_roku_ecp_base_url_for_row,
                    )

                    rb_nf_wk = resolve_roku_ecp_base_url_for_row(row0_nf_wk)
                    if rb_nf_wk:
                        wk_roku_title = fetch_roku_title_for_metadata(rb_nf_wk, timeout=6.0)
                except Exception:
                    wk_roku_title = None

        def _finish_body() -> None:
            meter_up = bool(_idle_audio_meter_active())
            pyatv_ok = bool(ok_w and isinstance(metadata_w, dict))
            md_for_status: dict[str, object] | None = metadata_w if pyatv_ok else None
            next_poll_ms = APPLE_TV_POLL_MS
            next_poll_holder[0] = next_poll_ms
            if current_apple_tv.get("identifier"):
                if pyatv_ok:
                    apple_tv_dashboard_track["last_poll_ok"] = True
                    apple_tv_dashboard_track["consecutive_fail"] = 0
                    if isinstance(metadata_w, dict) and _atv_metadata_is_content_idle(metadata_w):
                        # Idle Apple TV metadata does not need aggressive 3s reconnect cadence.
                        next_poll_ms = max(APPLE_TV_POLL_MS, APPLE_TV_IDLE_POLL_MS)
                else:
                    apple_tv_dashboard_track["last_poll_ok"] = False
                    apple_tv_dashboard_track["consecutive_fail"] = int(
                        apple_tv_dashboard_track.get("consecutive_fail", 0)
                    ) + 1
                    cf = int(apple_tv_dashboard_track.get("consecutive_fail", 0) or 0)
                    if cf == 1 or cf % 5 == 0:
                        try:
                            from pigeon.pi_diagnostics import append_pigeon_log

                            append_pigeon_log(
                                f"metadata poll failed ({cf}×): {str(msg_w or '')[:240]}"
                            )
                        except Exception:
                            pass
                    # Back off repeated connect attempts to reduce socket churn and UI pressure.
                    next_poll_ms = min(
                        APPLE_TV_FAIL_POLL_MAX_MS,
                        APPLE_TV_POLL_MS * max(2, min(cf, 5)),
                    )
                    if cf == 3:
                        try:
                            from device_capability_matrix import (
                                FEATURES as _delegation_feature_rows,
                                active_device_columns as _adv_dev_cols,
                            )

                            lid_log = str(read_current_location_id() or "").strip()
                            if lid_log:
                                _poll_entries = [
                                    (
                                        str(fid),
                                        f"{_fn}: player poll failed ({cf}\u00d7) while using this "
                                        f"delegation chain \u2014 {str(msg_w or '')[:120]}",
                                    )
                                    for _fn, fid in _delegation_feature_rows
                                ]
                                append_delegation_log_lines(lid_log, _poll_entries)
                                ndev = len(_adv_dev_cols())
                                if ndev > 1:
                                    advance_delegation_active(lid_log, "title", ndev)
                        except Exception:
                            pass
            if not meter_up:
                try:
                    from pigeon.observed_capability import (
                        update_observed_capabilities_from_player_poll,
                    )

                    _lid_ob = str(read_current_location_id() or "").strip()
                    if _lid_ob and device_identifier and device_address:
                        row_poll: dict[str, str] | None = None
                        for _r in read_saved_streaming_devices_all():
                            if (
                                str(_r.get("identifier") or "").strip()
                                == str(device_identifier).strip()
                                and str(_r.get("address") or "").strip()
                                == str(device_address).strip()
                            ):
                                row_poll = dict(_r)
                                break
                        if row_poll is None:
                            row_poll = {
                                "identifier": str(device_identifier).strip(),
                                "address": str(device_address).strip(),
                                "name": str(current_apple_tv.get("name") or "").strip(),
                                "label": str(current_apple_tv.get("label") or "").strip(),
                            }
                        update_observed_capabilities_from_player_poll(
                            _lid_ob,
                            row_poll,
                            ok=bool(ok_w),
                            metadata=metadata_w if isinstance(metadata_w, dict) else None,
                        )
                except Exception:
                    pass
                _refresh_observed_pairing_led_rows()
                _refresh_content_indicator()
            md_for_spawn: dict[str, object] | None = None
            if metadata_w:
                if ok_w:
                    _update_atv_interaction_from_poll_metadata(metadata_w)
                prefer_snap = _tmdb_pref_from_metadata(metadata_w)
                _ppm = str(metadata_w.get("prefer_pyatv_media") or "").strip().lower()
                if _ppm not in ("auto", "tv", "movie"):
                    _ppm = "auto"
                # Keep full poll dict for view-4 diagnostics; normalize the fields Pigeon logic relies on.
                merged_md: dict[str, object] = dict(metadata_w)
                pyatv_query = str(metadata_w.get("query") or "").strip()
                resolved_query = (
                    resolve_metadata_tmdb_query(metadata_w)
                    if resolve_metadata_tmdb_query is not None
                    else pyatv_query
                )
                merged_md["query"] = pyatv_query or resolved_query
                merged_md["title"] = str(metadata_w.get("title") or "").strip()
                merged_md["artist"] = str(metadata_w.get("artist") or "").strip()
                merged_md["series_name"] = str(metadata_w.get("series_name") or "").strip()
                merged_md["album"] = str(metadata_w.get("album") or "").strip()
                merged_md["media_type"] = str(metadata_w.get("media_type") or "").strip()
                merged_md["total_time"] = metadata_w.get("total_time")
                merged_md["position"] = metadata_w.get("position")
                merged_md["device_state"] = str(metadata_w.get("device_state") or "").strip()
                merged_md["power_state"] = str(metadata_w.get("power_state") or "").strip()
                merged_md["inferred_prefer"] = prefer_snap
                merged_md["prefer_pyatv_media"] = _ppm
                merged_md["content_key"] = _content_key_from_metadata(merged_md)
                merged_md["app_name"] = str(metadata_w.get("app_name") or "").strip()
                merged_md["app_id"] = str(metadata_w.get("app_id") or "").strip()
                merged_md["volume_percent"] = metadata_w.get("volume_percent")
                prev_md = apple_tv_auto_state.get("last_metadata")
                try:
                    from pigeon.display_confidence import (
                        hold_identity_across_idle_poll,
                    )

                    merged_md = hold_identity_across_idle_poll(
                        prev_md if isinstance(prev_md, dict) else None,
                        merged_md,
                    )
                    merged_md["content_key"] = _content_key_from_metadata(
                        merged_md
                    )
                except Exception:
                    pass
                if ok_w:
                    _bump_clock_saver_significant_device_from_metadata(merged_md)
                md_for_spawn = merged_md
                try:
                    from pigeon.display_confidence import (
                        PYATV_IDENTITY,
                        mark_identity,
                        mark_stale,
                        player_metadata_adequate,
                    )
                    prev_app = ""
                    if isinstance(prev_md, dict):
                        prev_app = str(
                            prev_md.get("app_id")
                            or prev_md.get("app_name")
                            or ""
                        ).strip().casefold()
                    new_app = str(
                        merged_md.get("app_id") or merged_md.get("app_name") or ""
                    ).strip().casefold()
                    app_changed = bool(prev_app and new_app and prev_app != new_app)
                    player_ok = player_metadata_adequate(merged_md)
                    if player_ok:
                        mark_identity(
                            merged_md, source="pyatv", confidence=PYATV_IDENTITY
                        )
                        try:
                            from pigeon.title_decision import (
                                apply_decision_to_metadata,
                                record_title_decision,
                            )

                            q_py = str(
                                merged_md.get("query")
                                or merged_md.get("title")
                                or ""
                            ).strip()
                            prev_dec = str(
                                merged_md.get("title_decision_title") or ""
                            ).strip()
                            if q_py and q_py.casefold() != prev_dec.casefold():
                                decision = record_title_decision(
                                    q_py,
                                    source="pyatv",
                                    reason="player metadata supplied a usable title",
                                )
                                apply_decision_to_metadata(merged_md, decision)
                                apple_tv_auto_state["last_title_decision"] = (
                                    decision.explain()
                                )
                        except Exception:
                            pass
                    if app_changed and not player_ok:
                        # Metadata-rich app → no-meta app: drop stale
                        # identity/art.
                        mark_stale(merged_md)
                        _clear_displayed_tmdb_art_for_content_change()
                except Exception:
                    pass
                apple_tv_auto_state["last_metadata"] = merged_md
                if not meter_up:
                    try:
                        _schedule_hdmi_frame_check_from_poll()
                    except Exception:
                        pass
                    # Music artwork (bytes live only on the poll dict; not stored in last_metadata).
                    try:
                        art_md = dict(merged_md)
                        if isinstance(metadata_w, dict) and metadata_w.get("artwork_bytes"):
                            art_md["artwork_bytes"] = metadata_w.get("artwork_bytes")
                            if metadata_w.get("artwork_id"):
                                art_md["artwork_id"] = metadata_w.get("artwork_id")
                        _store_music_artwork_from_metadata(art_md)
                    except Exception:
                        pass
                    _update_status_bar_from_metadata(metadata_w)
                    if playback_overlay_widget is not None:
                        row_av = streaming_slot_holder[0]
                        if row_av and row_is_playback_apple_tv(row_av):
                            from pigeon.widgets.playback_overlay import (
                                volume_percent_to_widget_line,
                            )

                            v_line = volume_percent_to_widget_line(
                                metadata_w.get("volume_percent")
                            )
                            # The Denon poll runs on its own short cadence and is the
                            # authoritative source whenever it has produced a usable
                            # reading recently — Apple TV's ``volume_percent`` reads 0
                            # when a physical AV receiver owns the volume, which would
                            # otherwise flash "0" over the correct dB value every
                            # metadata tick. Keep polling (scale-change detection stays
                            # active) but do not let that poll update the widget while
                            # Denon still owns the line.
                            last_denon_usable = float(
                                denon_vol_cache.get("mono_usable") or 0.0
                            )
                            denon_staleness_s = time.monotonic() - last_denon_usable
                            denon_authoritative = (
                                not receiver_standby_holder[0]
                                and bool(denon_vol_cache.get("effective"))
                                and denon_staleness_s
                                < (RECEIVER_POLL_MS / 1000.0) * 6
                            )
                            if v_line and not denon_authoritative:
                                old_v = str(receiver_overlay_state.get("volume", ""))
                                if old_v != v_line:
                                    receiver_overlay_state["volume"] = v_line
                                    _bump_clock_saver_significant_device()
                                    _warm_playback_overlay_blits()
                                    skip_cache[0] = None
                                    render_once()
            md_poll = metadata_w if isinstance(metadata_w, dict) else None
            _sync_streaming_badge_from_playback_sources(
                md_poll,
                roku_app_name=wk_roku_nm,
            )
            pyatv_tmdb_eligible = False
            if isinstance(md_for_spawn, dict):
                from pigeon.tmdb_poster import is_degenerate_tmdb_query

                query = str(md_for_spawn.get("query") or "").strip()
                content_key = _content_key_from_metadata(md_for_spawn)
                prefer = _tmdb_pref_from_metadata(md_for_spawn)
                if (
                    query
                    and not is_degenerate_tmdb_query(query)
                    and not _atv_metadata_is_content_idle(md_for_spawn)
                ):
                    pyatv_tmdb_eligible = True
                    prev_key = apple_tv_auto_state.get("content_key")
                    content_changed = bool(content_key and content_key != prev_key)
                    if content_changed:
                        apple_tv_auto_state["content_key"] = content_key
                        # Clear prior poster/cast and unlock spawn identity so the
                        # new title can fetch (force-quit was previously the only
                        # path that cleared tmdb_key after a stuck empty state).
                        if not meter_up:
                            _clear_displayed_tmdb_art_for_content_change()
                    apple_tv_auto_state["query"] = query
                    apple_tv_auto_state["prefer"] = prefer
                    needs_spawn = bool(
                        content_changed
                        or _tmdb_spawn_identity_changed(
                            query,
                            prefer,
                            md_for_spawn,
                            prev_content_key=prev_key,
                        )
                    )
                    # Empty display with active playback: retry once per identity.
                    # After a no-match / exhausted error-flag cycle we set
                    # ``tmdb_missing_art`` so this path cannot spin forever.
                    if (
                        not needs_spawn
                        and active_tmdb_title_key[0] is None
                        and not apple_tv_auto_state.get("tmdb_fetch_in_flight")
                        and not apple_tv_auto_state.get("pending_tmdb")
                        and not apple_tv_auto_state.get("tmdb_missing_art")
                    ):
                        needs_spawn = True
                    if tmdb_should_skip_refetch_on_resume(
                        content_key=content_key,
                        prev_content_key=prev_key,
                        has_tmdb_identity=bool(
                            apple_tv_auto_state.get("tmdb_key")
                            or active_tmdb_title_key[0]
                        ),
                    ):
                        needs_spawn = False
                    if needs_spawn:
                        spawn_tmdb_poster_fetch(
                            query, prefer=prefer, force=content_changed
                        )
                if ok_w:
                    _return_to_landing_if_atv_idle(md_for_spawn)
            if not pyatv_tmdb_eligible and wk_roku_title is not None:
                try:
                    from pigeon.tmdb_poster import is_degenerate_tmdb_query

                    r_ok, _rmsg, rtitle = wk_roku_title
                    if (
                        r_ok
                        and rtitle
                        and not is_degenerate_tmdb_query(rtitle)
                    ):
                        r_md: dict[str, object] = {
                            "query": str(rtitle).strip(),
                            "title": str(rtitle).strip(),
                            "artist": "",
                            "series_name": "",
                            "album": "",
                            "media_type": "",
                            "total_time": None,
                            "position": None,
                            "device_state": "Playing",
                            "app_name": str(wk_roku_nm or ""),
                            "app_id": "",
                            "prefer_pyatv_media": "auto",
                        }
                        prefer_r = _tmdb_pref_from_metadata(r_md)
                        r_md["inferred_prefer"] = prefer_r
                        r_md["content_key"] = _content_key_from_metadata(r_md)
                        apple_tv_auto_state["last_metadata"] = r_md
                        if not meter_up:
                            _update_status_bar_from_metadata(r_md)
                        md_for_status = r_md
                        prev_rk = apple_tv_auto_state.get("content_key")
                        r_ck = r_md.get("content_key")
                        r_changed = bool(r_ck and r_ck != prev_rk)
                        if r_changed:
                            apple_tv_auto_state["content_key"] = r_ck
                            _clear_displayed_tmdb_art_for_content_change()
                        r_q = str(rtitle).strip()
                        apple_tv_auto_state["query"] = r_q
                        apple_tv_auto_state["prefer"] = "auto"
                        r_needs = bool(
                            r_changed
                            or _tmdb_spawn_identity_changed(
                                r_q, "auto", r_md, prev_content_key=prev_rk
                            )
                        )
                        if (
                            not r_needs
                            and active_tmdb_title_key[0] is None
                            and not apple_tv_auto_state.get("tmdb_fetch_in_flight")
                            and not apple_tv_auto_state.get("pending_tmdb")
                            and not apple_tv_auto_state.get("tmdb_missing_art")
                        ):
                            r_needs = True
                        if tmdb_should_skip_refetch_on_resume(
                            content_key=r_ck,
                            prev_content_key=prev_rk,
                            has_tmdb_identity=bool(
                                apple_tv_auto_state.get("tmdb_key")
                                or active_tmdb_title_key[0]
                            ),
                        ):
                            r_needs = False
                        if r_needs:
                            spawn_tmdb_poster_fetch(
                                r_q, prefer="auto", force=r_changed
                            )
                        if not pyatv_ok:
                            apple_tv_dashboard_track["last_poll_ok"] = True
                            apple_tv_dashboard_track["consecutive_fail"] = 0
                except Exception:
                    pass
            if not meter_up:
                _sync_status_bar_visibility_for_playback(md_for_status)
                try:
                    _schedule_hdmi_frame_check_from_poll()
                except Exception:
                    pass
            next_poll_holder[0] = int(next_poll_ms)

        def finish() -> None:
            if apple_tv_auto_state.get("poll_gen") != poll_gen:
                return  # superseded by the stall watchdog
            apple_tv_auto_state["running"] = False
            try:
                _finish_body()
            except Exception as e:
                sys.stderr.write(f"pigeon: apple_tv poll finish failed: {e!r}\n")
                sys.stderr.flush()
            finally:
                # One failed poll must never end polling for good.
                root.after(
                    max(APPLE_TV_POLL_MS, int(next_poll_holder[0])),
                    _apple_tv_auto_poll_tick,
                )

        root.after(0, finish)

    def worker() -> None:
        try:
            _poll_worker_body()
        except Exception as e:
            sys.stderr.write(f"pigeon: apple_tv poll worker failed: {e!r}\n")
            sys.stderr.flush()

            def _recover() -> None:
                if apple_tv_auto_state.get("poll_gen") != poll_gen:
                    return
                apple_tv_auto_state["running"] = False
                root.after(
                    max(APPLE_TV_POLL_MS, APPLE_TV_FAIL_POLL_MAX_MS),
                    _apple_tv_auto_poll_tick,
                )

            try:
                root.after(0, _recover)
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True).start()


def _register_receiver_callbacks(*, _clock_saver_volume, _note_volume_graphics, _volume_rotary_fail_log_count, _volume_rotary_ok_log_count, denon_vol_cache, receiver_overlay_state, receiver_power_on_pending, receiver_standby_holder, render_once, root) -> None:
    """Paint confirmed AVR levels and note command results; fed by the receiver link."""

    def on_confirmed(v: str) -> None:
        def _apply_confirmed_volume() -> None:
            try:
                denon_vol_cache["effective"] = v
                denon_vol_cache["np_hold"] = v
            except NameError:
                pass
            try:
                receiver_overlay_state["volume"] = v
            except NameError:
                pass
            try:
                _clock_saver_volume.remember(v, source="poll")
                _note_volume_graphics(v)
            except Exception:
                pass
            _request_render(root, render_once)

        try:
            root.after(0, _apply_confirmed_volume)
        except Exception:
            pass

    def on_result(ok: bool, msg: str) -> None:
        if ok:
            receiver_standby_holder[0] = False
            receiver_power_on_pending[0] = False
            try:
                from pigeon.runtime_state import update_receiver_runtime

                update_receiver_runtime(standby=False, reachable=True)
            except Exception:
                pass
            if _volume_rotary_ok_log_count[0] < 8:
                sys.stderr.write(f"pigeon: rotary_volume_gpio: receiver: {msg}\n")
                sys.stderr.flush()
                _volume_rotary_ok_log_count[0] += 1
            return
        if _volume_rotary_fail_log_count[0] < 16:
            sys.stderr.write(f"pigeon: rotary_volume_gpio: receiver failed: {msg}\n")
            sys.stderr.flush()
            _volume_rotary_fail_log_count[0] += 1

    link = get_receiver_link()
    link.on_volume_confirmed(on_confirmed)
    link.on_command_result(on_result)


def _receiver_volume_poll_tick(*, RECEIVER_VOLUME_POLL_MS, _PIGEON_EXT, _bind_receiver_volume_hub, _quick_receiver_volume_poll, _receiver_volume_poll_tick, receiver_http_host, root) -> None:
    root.after(RECEIVER_VOLUME_POLL_MS, _receiver_volume_poll_tick)
    if not _PIGEON_EXT:
        return
    _bind_receiver_volume_hub(str(receiver_http_host.get("host") or "").strip())
    _quick_receiver_volume_poll()


def _apple_tv_is_off(*, apple_tv_auto_state, apple_tv_dashboard_track, current_apple_tv) -> bool:
    """True when the selected Apple TV is powered off or has gone unreachable."""
    if not current_apple_tv.get("identifier"):
        return False
    md = apple_tv_auto_state.get("last_metadata")
    md_dict = md if isinstance(md, dict) else None
    try:
        from pigeon.apple_tv_now_playing import apple_tv_should_show_idle_clock

        cf = int(apple_tv_dashboard_track.get("consecutive_fail", 0) or 0)
        return bool(apple_tv_should_show_idle_clock(md_dict, consecutive_fail=cf))
    except Exception:
        raw = str((md_dict or {}).get("power_state") or "").lower()
        return raw == "off" or raw.endswith(".off")


def _update_atv_interaction_from_poll_metadata(metadata: dict[str, object], *, _atv_ix_extrap_playing, _atv_ix_pos, _atv_ix_pos_mono, _atv_ix_prev_idle, _atv_ix_sig_ck, _atv_ix_sig_ds, _atv_metadata_is_content_idle, _content_key_from_metadata, current_apple_tv, last_atv_interaction_mono) -> None:
    """Approximate Siri Remote / UI use from pyatv poll deltas (not plain playback time)."""
    if not current_apple_tv.get("identifier"):
        return
    now = time.monotonic()
    ds = str(metadata.get("device_state") or "")
    ck = _content_key_from_metadata(metadata)
    idle_now = _atv_metadata_is_content_idle(metadata)
    pos_raw = metadata.get("position")
    try:
        pos = float(pos_raw) if pos_raw is not None else None
    except (TypeError, ValueError):
        pos = None

    bump = False
    if _atv_ix_sig_ds[0] and ds != _atv_ix_sig_ds[0]:
        bump = True
    if ck != _atv_ix_sig_ck[0] and (ck or _atv_ix_sig_ck[0]):
        bump = True
    if not idle_now and _atv_ix_prev_idle[0]:
        bump = True
    if (
        pos is not None
        and _atv_ix_pos[0] is not None
        and 0 < (now - _atv_ix_pos_mono[0]) < 60.0
    ):
        dt = now - _atv_ix_pos_mono[0]
        expected = _atv_ix_pos[0] + (dt if _atv_ix_extrap_playing[0] else 0.0)
        if abs(pos - expected) > 3.0:
            bump = True

    if bump:
        last_atv_interaction_mono[0] = now

    _atv_ix_sig_ds[0] = ds
    _atv_ix_sig_ck[0] = ck
    _atv_ix_prev_idle[0] = idle_now
    if pos is not None:
        _atv_ix_pos[0] = pos
        _atv_ix_pos_mono[0] = now
    _atv_ix_extrap_playing[0] = "Playing" in ds


def set_current_apple_tv(row: dict[str, str], *, persist: bool, _atv_ix_extrap_playing, _atv_ix_pos, _atv_ix_pos_mono, _atv_ix_prev_idle, _atv_ix_sig_ck, _atv_ix_sig_ds, _clear_reported_position_stall_stamp, _rebuild_paired_devices_panel, _reset_clock_saver_device_signal_baseline, _schedule_refresh_pairing_leds, _sync_status_bar_visibility_for_playback, apple_tv_auto_state, apple_tv_dashboard_track, apple_tv_playback_clock, current_apple_tv, describe_current_apple_tv, last_atv_interaction_mono) -> None:
    current_apple_tv.clear()
    current_apple_tv.update(
        {
            "identifier": row.get("identifier", ""),
            "address": row.get("address", ""),
            "name": row.get("name", ""),
            "label": row.get("label", ""),
        }
    )
    if persist:
        write_last_apple_tv(
            identifier=row.get("identifier", ""),
            address=row.get("address", ""),
            name=row.get("name"),
            label=row.get("label"),
        )
    apple_tv_auto_state["content_key"] = None
    apple_tv_auto_state["tmdb_key"] = None
    apple_tv_auto_state["query"] = None
    apple_tv_auto_state["last_metadata"] = None
    apple_tv_auto_state["last_tmdb_fetch_input"] = None
    apple_tv_auto_state["last_tmdb_fetch_refined"] = None
    apple_tv_auto_state["last_tmdb_fetch_prefer"] = None
    apple_tv_playback_clock.clear()
    apple_tv_playback_clock.update(
        {
            "has_sync": False,
            "sync_mono": 0.0,
            "sync_position": 0.0,
            "live_mode": False,
            "playing": False,
            "latched_total": None,
            "latched_content_key": None,
            "last_reported_total": None,
            "display_played_sec": None,
            "trt_next_fire_mono": None,
        }
    )
    _clear_reported_position_stall_stamp()
    apple_tv_dashboard_track["last_poll_ok"] = None
    apple_tv_dashboard_track["consecutive_fail"] = 0
    last_atv_interaction_mono[0] = 0.0
    _atv_ix_sig_ds[0] = ""
    _atv_ix_sig_ck[0] = None
    _atv_ix_pos[0] = None
    _atv_ix_pos_mono[0] = time.monotonic()
    _atv_ix_extrap_playing[0] = False
    _atv_ix_prev_idle[0] = True
    _reset_clock_saver_device_signal_baseline()
    _sync_status_bar_visibility_for_playback(None)
    describe_current_apple_tv()
    _rebuild_paired_devices_panel()
    _schedule_refresh_pairing_leds()


def _apply_persisted_location_to_runtime(*, _atv_ix_extrap_playing, _atv_ix_pos, _atv_ix_pos_mono, _atv_ix_prev_idle, _atv_ix_sig_ck, _atv_ix_sig_ds, _clear_reported_position_stall_stamp, _rebuild_paired_devices_panel, _reset_clock_saver_device_signal_baseline, _schedule_refresh_pairing_leds, _start_location_toast, _sync_status_bar_visibility_for_playback, _warm_playback_overlay_blits, apple_tv_auto_state, apple_tv_dashboard_track, apple_tv_playback_clock, avr_slot_holder, current_apple_tv, describe_current_apple_tv, last_atv_interaction_mono, playback_overlay_widget, receiver_http_host, render_once, skip_cache, streaming_slot_holder, denon_vol_cache=None, receiver_overlay_state=None, receiver_standby_holder=None, receiver_debug_holder=None) -> None:
    """Reload holders and runtime targets from the persisted current location."""
    streaming_slot_holder[0] = read_saved_streaming_device()
    avr_slot_holder[0] = read_saved_av_receiver()
    st2 = streaming_slot_holder[0]
    av2 = avr_slot_holder[0]
    if st2:
        current_apple_tv.clear()
        current_apple_tv.update(
            {
                "identifier": st2.get("identifier", ""),
                "address": st2.get("address", ""),
                "name": st2.get("name", ""),
                "label": st2.get("label", ""),
            }
        )
        write_last_apple_tv(
            identifier=st2.get("identifier", ""),
            address=st2.get("address", ""),
            name=st2.get("name"),
            label=st2.get("label"),
        )
    else:
        clear_last_apple_tv()
        current_apple_tv.clear()
        current_apple_tv.update({"identifier": "", "address": "", "name": "", "label": ""})
    apple_tv_auto_state["content_key"] = None
    apple_tv_auto_state["tmdb_key"] = None
    apple_tv_auto_state["query"] = None
    apple_tv_auto_state["last_metadata"] = None
    apple_tv_auto_state["last_tmdb_fetch_input"] = None
    apple_tv_auto_state["last_tmdb_fetch_refined"] = None
    apple_tv_auto_state["last_tmdb_fetch_prefer"] = None
    apple_tv_playback_clock.clear()
    apple_tv_playback_clock.update(
        {
            "has_sync": False,
            "sync_mono": 0.0,
            "sync_position": 0.0,
            "live_mode": False,
            "playing": False,
            "latched_total": None,
            "latched_content_key": None,
            "last_reported_total": None,
            "display_played_sec": None,
            "trt_next_fire_mono": None,
        }
    )
    _clear_reported_position_stall_stamp()
    apple_tv_dashboard_track["last_poll_ok"] = None
    apple_tv_dashboard_track["consecutive_fail"] = 0
    last_atv_interaction_mono[0] = 0.0
    _atv_ix_sig_ds[0] = ""
    _atv_ix_sig_ck[0] = None
    _atv_ix_pos[0] = None
    _atv_ix_pos_mono[0] = time.monotonic()
    _atv_ix_extrap_playing[0] = False
    _atv_ix_prev_idle[0] = True
    _reset_clock_saver_device_signal_baseline()
    adr = str((av2 or {}).get("address") or "").strip()
    if adr:
        write_last_receiver(
            host=adr,
            name=str(av2.get("name") or "").strip() or None,
            label=str(av2.get("label") or "").strip() or None,
            device_id=str(av2.get("identifier") or "").strip() or None,
        )
        receiver_http_host["host"] = adr
    else:
        clear_last_receiver()
        receiver_http_host["host"] = ""
        _release_receiver(
            denon_vol_cache=denon_vol_cache,
            receiver_overlay_state=receiver_overlay_state,
            receiver_standby_holder=receiver_standby_holder,
            receiver_debug_holder=receiver_debug_holder,
        )
    if playback_overlay_widget is not None:
        playback_overlay_widget.clear_cache()
    try:
        _warm_playback_overlay_blits()
    except Exception:
        pass
    skip_cache[0] = None
    _start_location_toast()
    _sync_status_bar_visibility_for_playback(None)
    try:
        render_once()
    except Exception:
        pass
    describe_current_apple_tv()
    _rebuild_paired_devices_panel()
    _schedule_refresh_pairing_leds()


def _receiver_debug_fields(st) -> dict[str, str]:
    """Receiver state as strings for the View 4 developer dump."""
    return {
        "power": "" if st.powered_on is None else ("on" if st.powered_on else "standby"),
        "volume": st.volume_line,
        "input": st.input_label,
        "audio format": st.audio_format,
        "sound mode": st.sound_mode,
    }


def _receiver_poll_tick(*, RECEIVER_POLL_MS, _PIGEON_EXT, _bind_receiver_volume_hub, _bump_clock_saver_significant_device, _clock_saver_for_compose, _clock_saver_receiver_off, _clock_saver_volume, _idle_audio_meter_active, _note_volume_graphics, _paint_boolean_led, _quick_receiver_volume_poll, _receiver_poll_tick, _refresh_observed_pairing_led_rows, _remember_clock_saver_volume, _sync_now_playing_screen_state, _sync_streaming_badge_from_playback_sources, _view_one_uses_now_playing_screen, _warm_playback_overlay_blits, apple_tv_auto_state, avr_slot_holder, clock_saver_force_on, denon_vol_cache, receiver_http_host, receiver_overlay_state, receiver_panel_led_holder, receiver_poll_busy, receiver_power_on_pending, receiver_power_on_until, receiver_standby_holder, receiver_debug_holder, render_once, root, skip_cache, streaming_slot_holder) -> None:
    root.after(RECEIVER_POLL_MS, _receiver_poll_tick)
    if not _PIGEON_EXT:
        return
    if receiver_poll_busy["active"]:
        _quick_receiver_volume_poll()
        return

    # Keep poll host aligned with the saved AV slot (not a stale last_receiver).
    # Re-read from disk so an updated AVR IP (DHCP/move) applies without restart.
    try:
        _av_disk = read_saved_av_receiver()
        _av_read_ok = True
    except Exception:
        _av_disk = None
        _av_read_ok = False  # temporary: keep whatever is bound
    if _av_disk and str(_av_disk.get("address") or "").strip():
        avr_slot_holder[0] = _av_disk
    elif _av_read_ok:
        # Readable settings, no receiver at this location: let go of the old one.
        avr_slot_holder[0] = None
        receiver_http_host["host"] = ""
        _release_receiver(
            denon_vol_cache=denon_vol_cache,
            receiver_overlay_state=receiver_overlay_state,
            receiver_standby_holder=receiver_standby_holder,
            receiver_debug_holder=receiver_debug_holder,
        )
        return
    _av_row = avr_slot_holder[0]
    if _av_row:
        _slot_adr = str(_av_row.get("address") or "").strip()
        _cur_host = str(receiver_http_host.get("host") or "").strip()
        if _slot_adr and _slot_adr != _cur_host:
            bound = str(denon_vol_cache.get("bound_host") or "")
            if bound and bound != _slot_adr:
                denon_vol_cache["effective"] = ""
                denon_vol_cache["np_hold"] = ""
                denon_vol_cache["mono_usable"] = 0.0
                receiver_overlay_state["volume"] = ""
            receiver_http_host["host"] = _slot_adr
            denon_vol_cache["bound_host"] = _slot_adr
    host = str(receiver_http_host.get("host") or "").strip()
    if not host:
        return
    _bind_receiver_volume_hub(host)

    def apply_overlay(
        incoming: str,
        config: str,
        volume: str,
        input_label: str | None = None,
    ) -> None:
        from pigeon.widgets.playback_overlay import _looks_like_receiver_debug_blob

        receiver_poll_busy["active"] = False
        old_vol_raw = str(receiver_overlay_state.get("volume", ""))
        old_in = str(receiver_overlay_state.get("incoming", ""))
        old_cf = str(receiver_overlay_state.get("config", ""))
        old_lab = str(receiver_overlay_state.get("input", ""))
        new_in = "" if _looks_like_receiver_debug_blob(incoming) else str(incoming or "")
        new_cf = "" if _looks_like_receiver_debug_blob(config) else str(config or "")
        new_vol = str(volume or "")
        overlay_unchanged = (
            old_in == new_in and old_cf == new_cf and old_vol_raw == new_vol
        )
        if input_label is not None:
            new_lab = str(input_label or "").strip()
            overlay_unchanged = overlay_unchanged and old_lab == new_lab
            receiver_overlay_state["input"] = new_lab
        receiver_overlay_state["incoming"] = new_in
        receiver_overlay_state["config"] = new_cf
        saver_up = bool(_clock_saver_for_compose(time.monotonic()) or clock_saver_force_on[0])
        stale_poll = _clock_saver_volume.is_stale_poll(
            new_vol
        ) or _receiver_readout_superseded(new_vol)
        if (new_vol or not saver_up) and not stale_poll:
            receiver_overlay_state["volume"] = new_vol
        if not stale_poll:
            if new_vol:
                _note_volume_graphics(new_vol)
            shown_cs = ""
            try:
                shown_cs = str(_clock_saver_volume.display_line() or "").strip()
            except Exception:
                shown_cs = str(getattr(_clock_saver_volume, "hold", "") or "")
            # Do not stamp a stale overlay readout over a newer saver hold
            # (that is what left the Digital-7 number frozen while the
            # volume arms still revealed).
            from pigeon.widgets.clock_saver import _volume_levels_match

            if new_vol and (
                not shown_cs or _volume_levels_match(new_vol, shown_cs)
            ):
                _remember_clock_saver_volume(new_vol, source="poll")
        if overlay_unchanged:
            if _view_one_uses_now_playing_screen() and not saver_up:
                _sync_now_playing_screen_state()
            if saver_up and _clock_saver_receiver_off() and not _idle_audio_meter_active():
                skip_cache[0] = None
                render_once()
            return
        if old_vol_raw != new_vol and not saver_up:
            _bump_clock_saver_significant_device()
        if _idle_audio_meter_active():
            return
        _warm_playback_overlay_blits()
        skip_cache[0] = None
        if _view_one_uses_now_playing_screen() and not saver_up:
            _sync_now_playing_screen_state()
        render_once()

    receiver_poll_busy["active"] = True

    def work() -> None:
        nonlocal host
        from pigeon.widgets.playback_overlay import (
            _receiver_volume_display_line,
            choose_poll_overlay_volume,
            compose_playback_volume_widget_line,
        )

        link = get_receiver_link()
        healed_host = ""
        origin_host = host

        def still_selected() -> bool:
            return str(receiver_http_host.get("host") or "").strip() == origin_host

        if host and still_selected():
            try:
                rx = link.bind(host)
                if not link.state().connected and link.seconds_since_bind() > 8.0:
                    # Still unreachable well after binding: the address may have moved.
                    now_h = time.monotonic()
                    quick_due = now_h - float(
                        denon_vol_cache.get("heal_quick_mono") or 0.0
                    ) >= 15.0
                    sweep_due = now_h - float(
                        denon_vol_cache.get("heal_sweep_mono") or 0.0
                    ) >= 90.0
                    if (quick_due or sweep_due) and isinstance(rx, Relocatable):
                        if quick_due:
                            denon_vol_cache["heal_quick_mono"] = now_h
                        if sweep_due:
                            denon_vol_cache["heal_sweep_mono"] = now_h
                        found = str(
                            rx.relocate(avr_slot_holder[0], sweep=sweep_due) or ""
                        ).strip()
                        if found and found != host and still_selected():
                            healed_host = found
                            host = found
                            link.bind(host)
            except Exception:
                pass

        roku_line = ""
        roku_vol_pct = ""
        roku_app_name = ""
        try:
            from pigeon.roku_ecp import (
                fetch_roku_active_app_name,
                fetch_roku_playback_line,
                resolve_roku_ecp_base_url,
                resolve_roku_ecp_base_url_for_row,
            )

            row_r = streaming_slot_holder[0]
            rbase_line = ""
            if row_r and not row_is_playback_apple_tv(row_r):
                rbase_line = str(resolve_roku_ecp_base_url_for_row(row_r) or "").strip()
            if not rbase_line:
                rbase_line = str(resolve_roku_ecp_base_url() or "").strip()
            if rbase_line:
                rl, rv = fetch_roku_playback_line(rbase_line, timeout=3.0)
                roku_line = rl or ""
                roku_vol_pct = str(rv or "").strip()
                # Keep all Roku ECP I/O off the Tk thread; this call can block on socket connect.
                try:
                    apnm_w = fetch_roku_active_app_name(rbase_line)
                    if apnm_w:
                        roku_app_name = str(apnm_w).strip()
                except Exception:
                    roku_app_name = ""
        except Exception:
            roku_line = ""
            roku_vol_pct = ""
            roku_app_name = ""

        st = link.state()  # read after the slow Roku I/O so the level is current
        denon_vol_picked = st.volume_line if st.connected else ""
        denon_vol_effective = (
            denon_vol_picked
            if _receiver_volume_display_line(denon_vol_picked)
            else ""
        )
        merged_volume = compose_playback_volume_widget_line(
            stream_row=streaming_slot_holder[0],
            apple_tv_last_metadata=apple_tv_auto_state.get("last_metadata"),
            denon_vol_effective=denon_vol_effective,
            roku_tv_volume_percent=roku_vol_pct,
        )

        def apply() -> None:
            rpl = receiver_panel_led_holder[0]
            try:
                _apply_body(rpl)
            except tk.TclError:
                pass
            finally:
                # Never leave the poll loop stuck if anything above threw.
                receiver_poll_busy["active"] = False

        def _apply_body(rpl: object) -> None:
            if not still_selected():
                # Receiver removed or replaced while this poll ran: its result
                # must not repaint the display.
                return
            if healed_host:
                receiver_http_host["host"] = healed_host
                denon_vol_cache["bound_host"] = healed_host
                try:
                    row_h = dict(avr_slot_holder[0] or {})
                    if not row_h:
                        row_h = dict(read_saved_av_receiver() or {})
                    if row_h:
                        row_h["address"] = healed_host
                        write_saved_av_receiver(row_h)
                        avr_slot_holder[0] = read_saved_av_receiver()
                except Exception:
                    pass
            denon_ok = st.connected
            if denon_ok and host:
                denon_vol_cache["bound_host"] = host
            raw_standby = bool(denon_ok and st.powered_on is False)
            if (
                receiver_power_on_pending[0]
                and time.monotonic() > float(receiver_power_on_until[0] or 0.0)
            ):
                receiver_power_on_pending[0] = False
            denon_standby = raw_standby and not receiver_power_on_pending[0]
            receiver_standby_holder[0] = denon_standby
            accept_vol = True
            try:
                # Only ignore a poll that is still the pre-knob level.
                # A new AVR readout (remote, knob, or HEOS) always wins.
                accept_vol = not (
                    _clock_saver_volume.is_stale_poll(denon_vol_effective)
                    or _receiver_readout_superseded(denon_vol_effective)
                )
            except Exception:
                accept_vol = True
            if accept_vol and denon_vol_effective and denon_ok:
                if denon_standby:
                    denon_vol_cache["effective"] = denon_vol_effective
                    denon_vol_cache["np_hold"] = denon_vol_effective
                    denon_vol_cache["mono_usable"] = 0.0
                elif denon_ok:
                    denon_vol_cache["effective"] = denon_vol_effective
                    denon_vol_cache["mono_usable"] = time.monotonic()
                    denon_vol_cache["np_hold"] = denon_vol_effective
            elif denon_standby:
                denon_vol_cache["mono_usable"] = 0.0
            if denon_ok and not raw_standby:
                receiver_power_on_pending[0] = False
            try:
                from pigeon.runtime_state import update_receiver_runtime

                update_receiver_runtime(
                    host=host,
                    reachable=bool(denon_ok and not denon_standby),
                    standby=denon_standby,
                    muted=str(denon_vol_effective).strip().lower()
                    in ("mute", "muted"),
                )
            except Exception:
                pass
            try:
                from pigeon.app_state import (
                    read_current_location_id,
                    read_saved_av_receiver,
                )
                from pigeon.observed_capability import (
                    update_observed_capabilities_from_receiver_poll,
                )

                update_observed_capabilities_from_receiver_poll(
                    str(read_current_location_id() or ""),
                    read_saved_av_receiver(),
                    denon_reachable=denon_ok and not denon_standby,
                    denon_volume_usable=bool(denon_vol_effective),
                    denon_has_incoming=bool(
                        denon_ok and not denon_standby and st.audio_format
                    ),
                    denon_has_config=bool(
                        denon_ok and not denon_standby and st.sound_mode
                    ),
                )
            except Exception:
                pass
            _refresh_observed_pairing_led_rows()
            overlay_vol = choose_poll_overlay_volume(
                merged_volume=merged_volume,
                accept_vol=accept_vol,
                cache_effective=str(denon_vol_cache.get("effective") or ""),
                cache_hold=str(denon_vol_cache.get("np_hold") or ""),
                saver_hold=str(getattr(_clock_saver_volume, "hold", "") or ""),
            )
            if overlay_vol:
                _note_volume_graphics(overlay_vol)
            if denon_standby:
                receiver_debug_holder[0] = _receiver_debug_fields(st)
                apply_overlay(
                    "",
                    "",
                    overlay_vol or str(denon_vol_cache.get("np_hold") or ""),
                    input_label="",
                )
                if rpl is not None:
                    _paint_boolean_led(rpl, False)
            elif denon_ok:
                receiver_debug_holder[0] = _receiver_debug_fields(st)
                poll_inc = str(st.audio_format or "").strip()
                poll_cfg = str(st.sound_mode or "").strip()
                poll_input = str(st.input_label or "").strip()
                apply_overlay(
                    poll_inc,
                    poll_cfg,
                    overlay_vol,
                    input_label=poll_input or None,
                )
                if rpl is not None:
                    _paint_boolean_led(rpl, True)
            elif overlay_vol:
                receiver_debug_holder[0] = {}
                apply_overlay("", "", overlay_vol)
                if rpl is not None:
                    _paint_boolean_led(rpl, False)
            else:
                receiver_debug_holder[0] = {}
                keep_vol = str(
                    receiver_overlay_state.get("volume")
                    or denon_vol_cache.get("np_hold")
                    or ""
                ).strip()
                apply_overlay("", "", keep_vol)
                if rpl is not None:
                    _paint_boolean_led(rpl, False)
            if roku_app_name:
                _sync_streaming_badge_from_playback_sources(
                    None,
                    roku_app_name=roku_app_name,
                )

        root.after(0, apply)

    def work_safe() -> None:
        try:
            work()
        except Exception:
            # Worker died before scheduling apply(); unblock future polls.
            receiver_poll_busy["active"] = False

    threading.Thread(target=work_safe, daemon=True).start()


def set_apple_tv_controls_enabled(enabled: bool, *, find_device_btn, purge_image_media_btn_holder, root, settings_footer_debug_holder, settings_footer_reset_holder, tmdb_adv_manual_btn_holder, tmdb_adv_report_btn_holder) -> None:
    state = tk.NORMAL if enabled else tk.DISABLED
    try:
        find_device_btn.configure(state=state)
        _m = tmdb_adv_manual_btn_holder[0]
        if _m is not None:
            _m.configure(state=state)
        _r = tmdb_adv_report_btn_holder[0]
        if _r is not None:
            _r.configure(state=state)
        purge_image_media_btn_holder[0].configure(state=state)
        _fdb = settings_footer_debug_holder[0]
        if _fdb is not None:
            _fdb.configure(state=state)
        _frb = settings_footer_reset_holder[0]
        if _frb is not None:
            _frb.configure(state=state)
        root.configure(cursor="none")
    except tk.TclError:
        pass
