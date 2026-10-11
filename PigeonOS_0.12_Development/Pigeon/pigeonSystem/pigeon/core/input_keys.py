"""Keyboard / mouse / window event handlers.

Extracted verbatim from ``bootstrap()`` in ``pigeon_0_12.py``. Each function
takes the app state it used to close over as keyword-only arguments;
``bootstrap()`` binds them once with ``bind_deps`` so call sites are unchanged.
"""

from __future__ import annotations

import time
import tkinter as tk
import sys
from pigeon.runtime_paths import PIGEON_STATE_DIR_TILDE
import tkinter.messagebox as messagebox


def quit_app(_event=None, *, root) -> None:
    root.quit()


def try_cycle_dev_phase(event: tk.Event | None, *, _last_overlay_mono, cycle_dev_phase) -> str | None:
    """Debounced OFF↔MAIN_SETTINGS cycle (mouse / F9); design grid overlay is key 5."""
    now = time.monotonic()
    if now - _last_overlay_mono[0] < 0.08:
        return "break"
    _last_overlay_mono[0] = now
    cycle_dev_phase()
    return "break"


def on_tab_key(event: tk.Event, *, _last_overlay_mono, cycle_dev_phase) -> str | None:
    """Tab / Shift+Tab / Ctrl+Tab: toggle OFF ↔ MAIN_SETTINGS.

    Tk on X11 (Pi) binds class ``<Tab>`` to focus traversal and returns
    break before ``bind_all``, so this handler is also installed on
    Label/Button/Entry and the other traversal classes.
    """
    st_tab = int(getattr(event, "state", 0) or 0)
    # Ctrl+Shift+Tab opens the advanced matrix (extension build).
    if (st_tab & 0x0004) and (st_tab & 0x0001):
        return None
    now = time.monotonic()
    if now - _last_overlay_mono[0] < 0.08:
        return "break"
    _last_overlay_mono[0] = now
    cycle_dev_phase()
    return "break"


def on_shift_tab_dev_cycle(event: tk.Event, *, on_tab_key) -> str | None:
    """Shift+Tab: same settings toggle as Tab."""
    return on_tab_key(event)


def on_ctrl_tab(event: tk.Event, *, on_tab_key) -> str | None:
    return on_tab_key(event)


def on_s_key(event: tk.Event, *, _design_grid_overlay_active, _last_s_mono, toggle_scene) -> str | None:
    keysym = (getattr(event, "keysym", "") or "").lower()
    ch = (getattr(event, "char", "") or "").lower()
    if keysym != "s" and ch != "s":
        return None
    if not _design_grid_overlay_active():
        return None
    now = time.monotonic()
    if now - _last_s_mono[0] < 0.08:
        return "break"
    _last_s_mono[0] = now
    toggle_scene(require_overlay=True)
    return "break"


def on_f10_key(_event: tk.Event | None = None, *, _design_grid_overlay_active, _last_f10_mono, f10_cycle_scene_grid, toggle_scene) -> str:
    now = time.monotonic()
    if now - _last_f10_mono[0] < 0.12:
        return "break"
    _last_f10_mono[0] = now
    if _design_grid_overlay_active():
        f10_cycle_scene_grid()
    else:
        toggle_scene(require_overlay=False)
    return "break"


def on_click_focus(_event: tk.Event | None = None, *, _bump_pigeon_user_activity, label, root) -> None:
    _bump_pigeon_user_activity(_event)
    try:
        label.focus_set()
    except tk.TclError:
        try:
            root.focus_set()
        except tk.TclError:
            pass


def on_double_click_scene(_event: tk.Event | None = None, *, toggle_scene) -> None:
    toggle_scene(require_overlay=False)


def _on_par_chord_release(event: tk.Event, *, _par_chord_fired, _par_chord_held) -> str | None:
    ks = (getattr(event, "keysym", "") or "").lower()
    if ks in ("p", "a", "r"):
        _par_chord_held.discard(ks)
    if not _par_chord_held:
        _par_chord_fired[0] = False
    return None


def _focus_when_mapped(_event=None, *, root) -> None:
    try:
        root.focus_force()
    except tk.TclError:
        root.focus_set()


def _on_shell_configure(event: tk.Event, *, _apply_shell_size, shell) -> None:
    if event.widget is not shell:
        return
    w, h = int(event.width), int(event.height)
    # Apply on every configure so chrome (buttons, HUD, bars) tracks live resize;
    # debounced after() only ran after drag ended.
    _apply_shell_size(w, h)


def on_tmdb_retry_hotkey(event: tk.Event, *, _PIGEON_EXT, _bump_pigeon_user_activity, _last_tmdb_hotkey_mono, _perform_tmdb_artwork_retry, _widget_accepts_typing) -> str | None:
    _bump_pigeon_user_activity(event)
    if not _PIGEON_EXT:
        return None
    if _widget_accepts_typing(event.widget):
        return None
    now_hk = time.monotonic()
    if now_hk - _last_tmdb_hotkey_mono[0] < 0.15:
        return "break"
    _last_tmdb_hotkey_mono[0] = now_hk
    _perform_tmdb_artwork_retry()
    return "break"


def on_ctrl_shift_tab_advanced(event: tk.Event, *, _PIGEON_EXT, _bump_pigeon_user_activity, _last_adv_shift_tab_mono, _open_advanced_capability_matrix, _widget_accepts_typing) -> str | None:
    if _widget_accepts_typing(event.widget):
        return None
    if not _PIGEON_EXT:
        return None
    st = int(getattr(event, "state", 0))
    if not (st & 0x0004) or not (st & 0x0001):
        return None
    _bump_pigeon_user_activity(event)
    now = time.monotonic()
    if now - _last_adv_shift_tab_mono[0] < 0.35:
        return "break"
    _last_adv_shift_tab_mono[0] = now
    _open_advanced_capability_matrix()
    return "break"


def on_tmdb_match_mode_toggle(event: tk.Event, *, _PIGEON_EXT, _bump_pigeon_user_activity, _last_tmdb_match_toggle_mono, _widget_accepts_typing) -> str | None:
    _bump_pigeon_user_activity(event)
    if not _PIGEON_EXT:
        return None
    if _widget_accepts_typing(event.widget):
        return None
    now_tm = time.monotonic()
    if now_tm - _last_tmdb_match_toggle_mono[0] < 0.2:
        return "break"
    _last_tmdb_match_toggle_mono[0] = now_tm
    try:
        from pigeon.tmdb_poster import toggle_tmdb_match_mode
    except ImportError:
        return None
    mode = toggle_tmdb_match_mode()
    sys.stderr.write(f"pigeon: TMDb title match: {mode} (Ctrl+Shift+M to toggle)\n")
    sys.stderr.flush()
    return "break"


def _on_volume_rotary_action(action: str, *, _bump_pigeon_user_activity, _note_zone3_volume_takeover, _nudge_clock_saver_volume, _queue_receiver_volume_action, _volume_rotary_fail_log_count, apple_tv_busy, current_apple_tv, receiver_power_on_pending, receiver_power_on_until, receiver_standby_holder, streaming_slot_holder) -> None:
    _bump_pigeon_user_activity()
    if action not in ("volume_up", "volume_down", "mute_toggle"):
        return
    _note_zone3_volume_takeover()
    try:
        if receiver_standby_holder[0] or receiver_power_on_pending[0]:
            receiver_power_on_pending[0] = True
            receiver_power_on_until[0] = time.monotonic() + 12.0
            receiver_standby_holder[0] = False
            from pigeon.runtime_state import update_receiver_runtime

            update_receiver_runtime(standby=False, reachable=True)
    except Exception:
        pass
    if _queue_receiver_volume_action(action):
        _nudge_clock_saver_volume(action)
        return
    try:
        from pigeon.player_remote import queue_player_remote_action

        ok = queue_player_remote_action(
            streaming_slot_holder[0],
            current_apple_tv=current_apple_tv,
            action=action,
            apple_tv_busy=apple_tv_busy,
        )
    except Exception as exc:
        ok = False
        if _volume_rotary_fail_log_count[0] < 8:
            sys.stderr.write(f"pigeon: rotary_volume_gpio: {action} failed: {exc}\n")
            sys.stderr.flush()
            _volume_rotary_fail_log_count[0] += 1
    if not ok and _volume_rotary_fail_log_count[0] < 8:
        sys.stderr.write(
            f"pigeon: rotary_volume_gpio: no player remote command for {action!r}\n"
        )
        sys.stderr.flush()
        _volume_rotary_fail_log_count[0] += 1
    _nudge_clock_saver_volume(action)


def _on_play_pause_gpio_action(*, _bump_pigeon_user_activity, _play_pause_gpio_last_mono, _send_player_play_pause_hotkey) -> None:
    _bump_pigeon_user_activity()
    now_pp = time.monotonic()
    if now_pp - _play_pause_gpio_last_mono[0] < 0.25:
        return
    _play_pause_gpio_last_mono[0] = now_pp
    ok = _send_player_play_pause_hotkey()
    try:
        sys.stderr.write(
            "pigeon: play_pause_gpio: "
            + ("sent play_pause\n" if ok else "no player remote command\n")
        )
        sys.stderr.flush()
    except Exception:
        pass


def on_dev_series_title_training_hotkey(event: tk.Event, *, DevPhase, DisplayView, _PIGEON_EXT, _bump_pigeon_user_activity, _widget_accepts_typing, apple_tv_auto_state, dev_phase, display_view_holder, root, spawn_tmdb_poster_fetch) -> str | None:
    """Dev-only: map current playback metadata fingerprint → series title (training JSON)."""
    _bump_pigeon_user_activity(event)
    if not _PIGEON_EXT:
        return None
    if dev_phase[0] != DevPhase.GRID and display_view_holder[0] != DisplayView.FIVE:
        return None
    if _widget_accepts_typing(event.widget):
        return None
    lm = apple_tv_auto_state.get("last_metadata")
    if not isinstance(lm, dict) or not any(
        str(lm.get(k) or "").strip()
        for k in ("title", "series_name", "artist", "album", "query")
    ):
        messagebox.showinfo(
            "Series title training",
            "No playback metadata snapshot yet. Start playback and wait for a poll, then try again.",
            parent=root,
        )
        return "break"
    try:
        from pigeon.raw_title import raw_title_from_metadata_dict
        from pigeon.series_title_training import add_training_mapping
    except ImportError:
        messagebox.showinfo(
            "Series title training",
            "Training modules are not available in this build.",
            parent=root,
        )
        return "break"

    rt = raw_title_from_metadata_dict(lm)
    sig = rt.training_signature_normalized()
    if not sig:
        messagebox.showinfo(
            "Series title training",
            "Could not build a stable fingerprint from the current metadata.",
            parent=root,
        )
        return "break"

    tw = tk.Toplevel(root)
    tw.title("Series title training")
    tw.transient(root)
    tk.Label(
        tw,
        text="Map this playback fingerprint to a TMDb series title.\n"
        f"Saved under {PIGEON_STATE_DIR_TILDE}/series_title_training_hints.json",
        justify="center",
    ).pack(padx=12, pady=(10, 4))
    preview = sig[:180] + ("…" if len(sig) > 180 else "")
    tk.Label(
        tw,
        text=f"Key: {preview}",
        fg="#888",
        wraplength=420,
        justify="left",
    ).pack(padx=12, pady=4)
    ent = tk.Entry(tw, width=48)
    ent.pack(padx=12, pady=6)
    hint = (rt.layer_series_title or rt.raw_series_name or rt.raw_title or "").strip()
    if hint:
        ent.insert(0, hint)

    def _save_training() -> None:
        q_sp = ent.get().strip()
        ok_h, msg_h = add_training_mapping(sig, q_sp)
        if ok_h:
            sys.stderr.write(f"pigeon: series title training: {msg_h}\n")
            sys.stderr.flush()
            tw.destroy()
            if q_sp:
                spawn_tmdb_poster_fetch(q_sp, prefer=str(apple_tv_auto_state.get("prefer") or "auto"), force=True)
        else:
            messagebox.showerror("Series title training", msg_h, parent=tw)

    bf = tk.Frame(tw)
    bf.pack(pady=(4, 12))
    tk.Button(bf, text="Save & refetch TMDb", command=_save_training).pack(side=tk.LEFT, padx=6)
    tk.Button(bf, text="Cancel", command=tw.destroy).pack(side=tk.LEFT, padx=6)
    root.after_idle(lambda: ent.focus_set())
    return "break"


def on_escape(event: tk.Event, *, _bump_pigeon_user_activity, command_entry_visible, hide_command_entry, quit_app) -> str | None:
    _bump_pigeon_user_activity(event)
    if command_entry_visible[0]:
        hide_command_entry()
        return "break"
    quit_app()
    return "break"


def _on_label_button_release_peek_or_bump(event: tk.Event, *, CLOCK_SAVER_PEEK_S, _PIGEON_EXT, _bump_pigeon_user_activity, _clock_saver_for_compose, clock_saver_composite_bgra, clock_saver_peek_until_mono, render_once, skip_cache) -> None:
    if _PIGEON_EXT and clock_saver_composite_bgra is not None:
        now_e = time.monotonic()
        if _clock_saver_for_compose(now_e):
            clock_saver_peek_until_mono[0] = now_e + CLOCK_SAVER_PEEK_S
            _bump_pigeon_user_activity(event)
            skip_cache[0] = None
            try:
                render_once()
            except Exception:
                pass
            return
    _bump_pigeon_user_activity(event)


def on_display_view_digit(event: tk.Event, *, DevPhase, DisplayView, ViewOneLayout, _PIGEON_EXT, _bump_pigeon_user_activity, _capture_last_view_one_layout_from_live_view, _current_view_one_variant, _idle_saver_face_toggle_ok, _sync_now_playing_screen_state, _toggle_clock_saver_force, _vv_is_music, _widget_accepts_typing, dev_phase, display_view_holder, main_settings_widget, render_once, skip_cache, sync_developer_chrome, toggle_audio_meter_face, variant_has_alternate, view_circles_widget, view_five_mode_holder, view_four_subview_holder, view_one_layout_holder) -> str | None:
    if _widget_accepts_typing(event.widget):
        return None
    if not _PIGEON_EXT:
        return None
    ch = getattr(event, "char", "") or ""
    if ch not in "012345678":
        return None
    st_md = main_settings_widget.state if main_settings_widget is not None else None
    md_open = bool(
        st_md is not None
        and dev_phase[0] == DevPhase.MAIN_SETTINGS
        and st_md.show_metadata_debug
    )
    if md_open and ch != "0":
        # Inspector is modal: EXIT (or [0] to close) are the only ways out.
        _bump_pigeon_user_activity(event)
        return "break"
    if ch == "0" and st_md is not None:
        if dev_phase[0] == DevPhase.MAIN_SETTINGS and st_md.keyboard is not None:
            return None
        if md_open:
            st_md.close_metadata_debug()
            st_md.exit_pigeon_settings()
            main_settings_widget.invalidate()
            dev_phase[0] = DevPhase.OFF
        else:
            st_md.open_metadata_debug()
            main_settings_widget.invalidate()
            if dev_phase[0] != DevPhase.MAIN_SETTINGS:
                dev_phase[0] = DevPhase.MAIN_SETTINGS
                try:
                    main_settings_widget.prefetch_scans_for_settings()
                except Exception:
                    pass
        skip_cache[0] = None
        sync_developer_chrome()
        _bump_pigeon_user_activity(event)
        _capture_last_view_one_layout_from_live_view()
        render_once()
        return "break"
    if ch == "2":
        st_key = int(getattr(event, "state", 0))
        sh_key = bool(st_key & 0x0001)
        if sh_key:
            return _toggle_clock_saver_force(event)
    if dev_phase[0] != DevPhase.OFF:
        _bump_pigeon_user_activity(event)
        return "break"
    if ch == "1":
        st_key = int(getattr(event, "state", 0))
        sh_key = bool(st_key & 0x0001)
        if (
            not sh_key
            and toggle_audio_meter_face is not None
            and _idle_saver_face_toggle_ok()
        ):
            # Steal [1] only while the idle saver is up so NP zone-1 still works.
            on = toggle_audio_meter_face()
            try:
                sys.stderr.write(
                    "pigeon: idle face "
                    + ("audio meter\n" if on else "clock saver\n")
                )
                sys.stderr.flush()
            except Exception:
                pass
            skip_cache[0] = None
            try:
                render_once()
            except Exception:
                pass
            return "break"
    if ch in "12345678" and display_view_holder[0] == DisplayView.ONE:
        st_key = int(getattr(event, "state", 0))
        sh_key = bool(st_key & 0x0001)
        if ch == "1" and sh_key:
            _vv_now = _current_view_one_variant()
            if (
                _vv_now is not None
                and variant_has_alternate is not None
                and not variant_has_alternate(_vv_now)
            ):
                _bump_pigeon_user_activity(event)
                return "break"
            _cur = int(view_one_layout_holder[0])
            if _cur == int(ViewOneLayout.PIGEON_FULL):
                view_one_layout_holder[0] = int(ViewOneLayout.PIGEON_SIMPLE)
            elif _cur == int(ViewOneLayout.PIGEON_SIMPLE):
                view_one_layout_holder[0] = int(ViewOneLayout.PIGEON_POSTER)
            else:
                view_one_layout_holder[0] = int(ViewOneLayout.PIGEON_FULL)
            skip_cache[0] = None
            _bump_pigeon_user_activity(event)
            _capture_last_view_one_layout_from_live_view()
            return "break"
        try:
            from pigeon.np_zone_keys import cycle_now_playing_zone
            from pigeon.widgets.preferences_settings import (
                read_np_header_clock,
                read_now_playing_zone_widgets,
                write_np_header_clock,
                write_now_playing_zone_widgets,
            )

            mode = "music" if _vv_is_music() else "video"
            cur = read_now_playing_zone_widgets(content_mode=mode)
            header = read_np_header_clock()
            nxt, header_on = cycle_now_playing_zone(
                cur,
                int(ch),
                content_mode=mode,
                header_clock=header,
            )
            write_now_playing_zone_widgets(nxt, content_mode=mode)
            write_np_header_clock(header_on)
            if view_circles_widget is not None:
                view_circles_widget.clear_cache()
            _sync_now_playing_screen_state()
        except Exception:
            pass
        skip_cache[0] = None
        _bump_pigeon_user_activity(event)
        _capture_last_view_one_layout_from_live_view()
        render_once()
        return "break"
    if ch == "4" and display_view_holder[0] == DisplayView.FOUR:
        view_four_subview_holder[0] = (int(view_four_subview_holder[0]) + 1) % 3
        skip_cache[0] = None
        _bump_pigeon_user_activity(event)
        return "break"
    if ch == "5" and display_view_holder[0] == DisplayView.FIVE:
        view_five_mode_holder[0] = (int(view_five_mode_holder[0]) + 1) % 3
        skip_cache[0] = None
        _bump_pigeon_user_activity(event)
        return "break"
    if ch in "145":
        display_view_holder[0] = DisplayView(int(ch))
        if ch == "1":
            view_one_layout_holder[0] = int(ViewOneLayout.PIGEON_FULL)
        if ch == "4":
            view_four_subview_holder[0] = 0
        if ch == "5":
            view_five_mode_holder[0] = 0
        skip_cache[0] = None
        _bump_pigeon_user_activity(event)
        _capture_last_view_one_layout_from_live_view()
        return "break"
    return "break"


def on_arrow_remote(event: tk.Event, *, DevPhase, _PIGEON_EXT, _nav_request, _widget_accepts_typing, apple_tv_busy, current_apple_tv, dev_phase, main_settings_widget, render_once, skip_cache, streaming_slot_holder, view_circles_widget_holder=None) -> str | None:
    if _widget_accepts_typing(event.widget):
        return None
    if not _PIGEON_EXT:
        return None
    ks = getattr(event, "keysym", "") or ""
    if ks not in ("Up", "Down", "Left", "Right"):
        return None
    if dev_phase[0] == DevPhase.MAIN_SETTINGS and main_settings_widget is not None:
        if ks == "Right":
            main_settings_widget.navigate(forward=True)
            skip_cache[0] = None
            req = _nav_request[0]
            req() if req is not None else render_once()
            return "break"
        if ks == "Left":
            main_settings_widget.navigate(forward=False)
            skip_cache[0] = None
            req = _nav_request[0]
            req() if req is not None else render_once()
            return "break"
        return "break"
    from pigeon.player_remote import queue_player_remote_action

    st = int(getattr(event, "state", 0))
    if st & 0x0004:
        return None
    if ks in ("Left", "Right") and not (st & (0x0001 | 0x0008 | 0x20000 | 0x080000 | 0x100000)):
        # HID encoder boards turn as Left / Right: pick the visualizer preset.
        try:
            vc = view_circles_widget_holder[0] if view_circles_widget_holder else None
            if vc is not None and vc.rotate_zone6_visualizer(1 if ks == "Right" else -1):
                return "break"
        except Exception:
            pass
    sh = bool(st & 0x0001)
    meta_cmd = (
        bool(st & 0x100000)
        or bool(st & 0x080000)
        or bool(st & 0x0008)
        or bool(st & 0x20000)
    )
    row = streaming_slot_holder[0]
    if meta_cmd:
        cmd_map = {
            "Up": "power_on",
            "Down": "power_off",
            "Left": "back",
            "Right": "home",
        }
        act = cmd_map.get(ks)
        if act:
            queue_player_remote_action(
                row,
                current_apple_tv=current_apple_tv,
                action=act,
                apple_tv_busy=apple_tv_busy,
            )
        return "break"
    if sh:
        if ks == "Up":
            queue_player_remote_action(
                row,
                current_apple_tv=current_apple_tv,
                action="volume_up",
                apple_tv_busy=apple_tv_busy,
            )
        elif ks == "Down":
            queue_player_remote_action(
                row,
                current_apple_tv=current_apple_tv,
                action="volume_down",
                apple_tv_busy=apple_tv_busy,
            )
        elif ks == "Left":
            queue_player_remote_action(
                row,
                current_apple_tv=current_apple_tv,
                action="skip_back",
                apple_tv_busy=apple_tv_busy,
            )
        elif ks == "Right":
            queue_player_remote_action(
                row,
                current_apple_tv=current_apple_tv,
                action="skip_fwd",
                apple_tv_busy=apple_tv_busy,
            )
        return "break"
    nav = {
        "Up": "nav_up",
        "Down": "nav_down",
        "Left": "nav_left",
        "Right": "nav_right",
    }.get(ks)
    if nav:
        queue_player_remote_action(
            row,
            current_apple_tv=current_apple_tv,
            action=nav,
            apple_tv_busy=apple_tv_busy,
        )
    return "break"


def _on_par_chord_press(event: tk.Event, *, _par_chord_fired, _par_chord_held, _widget_accepts_typing, render_once, skip_cache) -> str | None:
    if _widget_accepts_typing(event.widget):
        return None
    ks = (getattr(event, "keysym", "") or "").lower()
    if ks not in ("p", "a", "r"):
        return None
    _par_chord_held.add(ks)
    if not ({"p", "a", "r"} <= _par_chord_held) or _par_chord_fired[0]:
        return None
    _par_chord_fired[0] = True
    try:
        from pigeon.display_par import cycle_par_mode

        mode, par, reason = cycle_par_mode()
    except Exception as exc:
        sys.stderr.write(f"pigeon: PAR chord failed: {exc}\n")
        sys.stderr.flush()
        return "break"
    msg = f"pigeon: display PAR → mode={mode}  effective={par:.4f}  ({reason})"
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
    try:
        from pigeon.pi_diagnostics import append_pigeon_log

        append_pigeon_log(msg)
    except Exception:
        pass
    skip_cache[0] = None
    try:
        render_once()
    except Exception:
        pass
    return "break"


def _on_rotary_action(action: str, *, DevPhase, _bump_pigeon_user_activity, _enter_main_settings_for_rotary, _handle_main_settings_action, _nav_request, dev_phase, main_settings_widget, render_once, root, skip_cache, sync_developer_chrome, view_circles_widget_holder=None) -> None:
    _bump_pigeon_user_activity()
    was_main = dev_phase[0] == DevPhase.MAIN_SETTINGS
    if action == "hold":
        # Long press: Now Playing <-> visualizer mode (ignored inside settings).
        if not was_main:
            from pigeon import visualizer_mode

            visualizer_mode.toggle()
            skip_cache[0] = None
            render_once()
        return
    if action in ("forward", "backward") and not was_main:
        # Visualizer showing: turns pick the preset instead of opening settings.
        try:
            vc = view_circles_widget_holder[0] if view_circles_widget_holder else None
            if vc is not None and vc.rotate_zone6_visualizer(1 if action == "forward" else -1):
                return
        except Exception:
            pass
    if not _enter_main_settings_for_rotary():
        try:
            from pigeon.rotary_serial import inject_keysym

            keysym = {
                "forward": "Right",
                "backward": "Left",
                "activate": "space",
            }.get(action)
            if keysym:
                inject_keysym(root, keysym)
        except Exception:
            pass
        return
    # First click that opens settings should not also activate a control;
    # it lands on box1 (settings_pigeon) so a second click opens that page.
    if action == "activate" and not was_main:
        try:
            if main_settings_widget.state.focus_main_button("main_box1_button"):
                main_settings_widget.invalidate()
                skip_cache[0] = None
                render_once()
        except Exception:
            pass
        return
    if action == "forward":
        main_settings_widget.navigate(forward=True)
        skip_cache[0] = None
        req = _nav_request[0]
        req() if req is not None else render_once()
        return
    if action == "backward":
        main_settings_widget.navigate(forward=False)
        skip_cache[0] = None
        req = _nav_request[0]
        req() if req is not None else render_once()
        return
    if action == "activate":
        ms_action = main_settings_widget.activate()
        if ms_action == "exit":
            if main_settings_widget is not None and not bool(
                getattr(main_settings_widget.state, "exit_enabled", True)
            ):
                skip_cache[0] = None
                render_once()
            else:
                dev_phase[0] = DevPhase.OFF
                skip_cache[0] = None
                sync_developer_chrome()
                render_once()
        else:
            _handle_main_settings_action(ms_action)
            skip_cache[0] = None
            render_once()


def on_space_play(event: tk.Event, *, DevPhase, _bump_pigeon_user_activity, _handle_main_settings_action, _last_space_mono, _send_player_play_pause_hotkey, _widget_accepts_typing, apply_saved_tmdb_backdrop_to_display, dev_phase, main_settings_widget, render_once, saved_backdrop_master_bgr, skip_cache, sync_developer_chrome, toggle_play, use_backdrop_scene) -> str | None:
    if _widget_accepts_typing(event.widget):
        return None
    _bump_pigeon_user_activity(event)
    now = time.monotonic()
    if now - _last_space_mono[0] < 0.12:
        return "break"
    _last_space_mono[0] = now
    if dev_phase[0] == DevPhase.MAIN_SETTINGS and main_settings_widget is not None:
        action = main_settings_widget.activate()
        if action == "exit":
            if main_settings_widget is not None and not bool(
                getattr(main_settings_widget.state, "exit_enabled", True)
            ):
                skip_cache[0] = None
                render_once()
            else:
                dev_phase[0] = DevPhase.OFF
                skip_cache[0] = None
                sync_developer_chrome()
                render_once()
        else:
            _handle_main_settings_action(action)
            skip_cache[0] = None
            render_once()
        return "break"
    if _send_player_play_pause_hotkey():
        return "break"
    # After a TMDb fetch, bring backdrop + title logo to the screen (toggle_play often no-ops here).
    if saved_backdrop_master_bgr[0] is not None and not use_backdrop_scene[0]:
        apply_saved_tmdb_backdrop_to_display()
        return "break"
    toggle_play()
    return "break"
