"""Settings panel helpers: scrolling, wheel binding, device-row parsing, pairing LEDs, tooltips and update-check UI.

Extracted verbatim from ``bootstrap()`` in ``pigeon_0_12.py``. Each function
takes the app state it used to close over as keyword-only arguments;
``bootstrap()`` binds them once with ``bind_deps`` so call sites are unchanged.

The paired-devices panel, update flow, location management and reset actions now live
in ``settings_devices_panel``, ``settings_updates``, ``settings_locations`` and
``settings_reset``; they are re-exported here so ``settings_ui.<name>`` still resolves.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import time
import tkinter as tk
import tkinter.messagebox as messagebox
from pigeon.app_state import read_all_locations_v2
from pigeon.app_state import read_app_state
from pigeon.app_state import read_current_location_id
from pigeon.media_folders import pigeon_pulled_media_dir
from pigeon.media_folders import pigeon_reformatted_media_dir
from pigeon.media_folders import purge_directory_contents
from pigeon.app_state import delete_location_v2
from pigeon.app_state import row_is_playback_apple_tv
from pigeon.version import version_string
import sys
from pigeon.app_state import clear_last_apple_tv
from pigeon.app_state import clear_last_receiver
from pigeon.app_state import read_saved_av_receiver
import threading
from pigeon.app_state import add_empty_location_v2
from pigeon.app_state import clear_all_persisted_devices_and_targets
from pigeon.app_state import read_current_location_name
from pigeon.app_state import rename_location_v2
from pigeon.app_state import set_current_location_id
from pigeon.app_state import write_location_wifi
from pigeon.runtime_paths import pigeon_state_dir
import os
import queue
import tkinter.simpledialog as simpledialog
from pigeon.core.settings_devices_panel import (  # noqa: F401  (re-exported for existing importers)
    _ask_pairing_pin_modal,
    _device_addr_key,
    _device_row_matches_saved,
    _paint_cred_led_canvas,
    _paint_pair_led,
    _paired_box_close_button,
    _rebuild_paired_devices_panel,
    _refresh_observed_pairing_led_rows,
    _save_box_pair_device_row,
    _settings_audio_led_listen,
    _settings_parse_device_rows,
    _settings_parse_receiver_rows,
)
from pigeon.core.settings_updates import (  # noqa: F401  (re-exported for existing importers)
    _auto_update_tick,
    _begin_apply_update,
    _check_for_updates,
    _finish_update_check,
    _linux_on_updates_button,
    _on_updates_button,
    _run_github_apply_worker,
    _schedule_periodic_update_check,
    _sync_update_button_style,
)
from pigeon.core.settings_locations import (  # noqa: F401  (re-exported for existing importers)
    _apply_location_rename,
    _current_location_display_name,
    _on_delete_current_location,
    _on_location_name_return,
    _refresh_location_selector,
    _start_location_toast,
)
from pigeon.core.settings_reset import (  # noqa: F401  (re-exported for existing importers)
    on_purge_image_media,
    on_reset_pigeon_devices_and_media,
)


def _settings_update_scrollregion(event: tk.Event | None = None, *, _settings_inner_scroll_size, settings_canvas, settings_inner) -> None:
    try:
        if event is not None and getattr(event, "widget", None) is not settings_inner:
            return
        if event is not None:
            settings_inner.update_idletasks()
            rw = int(settings_inner.winfo_reqwidth())
            rh = int(settings_inner.winfo_reqheight())
            if rw == _settings_inner_scroll_size[0] and rh == _settings_inner_scroll_size[1]:
                return
            _settings_inner_scroll_size[0] = rw
            _settings_inner_scroll_size[1] = rh
        settings_canvas.update_idletasks()
        bbox = settings_canvas.bbox("all")
        if bbox:
            settings_canvas.configure(scrollregion=bbox)
    except tk.TclError:
        pass


def _settings_on_canvas_configure(event: tk.Event, *, _settings_inner_win, _settings_update_scrollregion, root, settings_canvas) -> None:
    try:
        inner_w = max(1, int(event.width) - 32)
        settings_canvas.itemconfig(_settings_inner_win, width=inner_w)
    except tk.TclError:
        pass
    root.after_idle(lambda: _settings_update_scrollregion(None))


def _settings_unbind_wheel_globals(*, root, settings_wheel_all_bound) -> None:
    if not settings_wheel_all_bound[0]:
        return
    try:
        root.unbind_all("<MouseWheel>")
        root.unbind_all("<Button-4>")
        root.unbind_all("<Button-5>")
    except tk.TclError:
        pass
    settings_wheel_all_bound[0] = False


def _register_tmdb_adv_widgets(manual: tk.Button, report: tk.Button, log_w: tk.Misc, *, tmdb_adv_log_text_holder, tmdb_adv_manual_btn_holder, tmdb_adv_report_btn_holder) -> None:
    tmdb_adv_manual_btn_holder[0] = manual
    tmdb_adv_report_btn_holder[0] = report
    tmdb_adv_log_text_holder[0] = log_w


def _unregister_tmdb_adv_widgets(*, tmdb_adv_log_text_holder, tmdb_adv_manual_btn_holder, tmdb_adv_report_btn_holder) -> None:
    tmdb_adv_manual_btn_holder[0] = None
    tmdb_adv_report_btn_holder[0] = None
    tmdb_adv_log_text_holder[0] = None


def _append_tmdb_retry_log_ui(line: str, *, tmdb_adv_log_text_holder) -> None:
    w = tmdb_adv_log_text_holder[0]
    if w is None:
        return
    try:
        w.insert(tk.END, line + "\n")
        w.see(tk.END)
        body = w.get("1.0", "end-1c")
        if body.count("\n") > 130:
            w.delete("1.0", "31.0")
    except tk.TclError:
        pass


def _match_neighbor_button_style(btn: tk.Button, *, ref: tk.Button) -> None:
    """Copy default macOS/system button chrome from a sibling (Find device / Advanced)."""
    for key in (
        "bg",
        "fg",
        "activebackground",
        "activeforeground",
        "highlightbackground",
        "highlightcolor",
        "highlightthickness",
        "relief",
        "borderwidth",
        "disabledforeground",
    ):
        try:
            btn.configure(**{key: ref.cget(key)})
        except tk.TclError:
            pass


def _resolve_install_root_for_update() -> Path:
    install_root = Path(__file__).resolve().parent.parent
    try:
        from pigeon.github_update import resolve_install_root

        resolved = resolve_install_root(script_path=__file__)
        if resolved is not None:
            install_root = resolved
    except Exception:
        pass
    return install_root


def _attach_hover_tooltip(widget: tk.Misc, message: str, *, S_FONT_SMALL, root) -> None:
    tip: list[tk.Toplevel | None] = [None]

    def show(_event: tk.Event | None = None) -> None:
        if tip[0] is not None:
            return
        tw = tk.Toplevel(root)
        tw.wm_overrideredirect(True)
        try:
            tw.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        x = widget.winfo_rootx() + 4
        y = widget.winfo_rooty() + int(widget.winfo_height()) + 4
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw,
            text=message,
            bg="#2a2a30",
            fg="#e8e8e8",
            font=S_FONT_SMALL,
            padx=8,
            pady=4,
        ).pack()
        tip[0] = tw

    def hide(_event: tk.Event | None = None) -> None:
        if tip[0] is not None:
            tip[0].destroy()
            tip[0] = None

    widget.bind("<Enter>", show)
    widget.bind("<Leave>", hide)


def _content_indicator_ok(*, _PIGEON_EXT, apple_tv_auto_state, apple_tv_busy, apple_tv_dashboard_track, current_apple_tv) -> bool:
    if not _PIGEON_EXT:
        return False
    if not current_apple_tv.get("identifier"):
        return False
    if apple_tv_busy["active"]:
        return False
    lf = apple_tv_dashboard_track.get("last_poll_ok")
    # Failed poll must not be masked by a stale latched query.
    if lf is False:
        return False
    q = apple_tv_auto_state.get("query")
    if q:
        return True
    return False


def _advanced_feature_pipeline_ok(*, _PIGEON_EXT, _atv_metadata_is_content_idle, apple_tv_auto_state, apple_tv_busy, apple_tv_dashboard_track, current_apple_tv) -> bool:
    """Stricter than the Content LED: last poll succeeded and metadata is active (not idle/unknown)."""
    if not _PIGEON_EXT:
        return False
    if not current_apple_tv.get("identifier"):
        return False
    if apple_tv_busy["active"]:
        return False
    if apple_tv_dashboard_track.get("last_poll_ok") is not True:
        return False
    lm = apple_tv_auto_state.get("last_metadata")
    if not isinstance(lm, dict) or _atv_metadata_is_content_idle(lm):
        return False
    return True


def _refresh_content_indicator(*, _content_indicator_ok, _paint_boolean_led, _refresh_match_quality_glance_label, content_indicator_cv_holder) -> None:
    cv = content_indicator_cv_holder[0]
    if cv is not None:
        try:
            _paint_boolean_led(cv, _content_indicator_ok())
        except tk.TclError:
            pass
    _refresh_match_quality_glance_label()


def _settings_is_native_1280(*, DevPhase, dev_phase, main_settings_widget) -> bool:
    """True when settings is on screen — all current pages are 1280×800."""
    return dev_phase[0] == DevPhase.MAIN_SETTINGS and main_settings_widget is not None


def _settings_menu_is_static(*, DevPhase, dev_phase, main_settings_widget) -> bool:
    """True when settings is up and not running a scan/spinner animation."""
    if dev_phase[0] != DevPhase.MAIN_SETTINGS or main_settings_widget is None:
        return False
    try:
        st = main_settings_widget.state
    except Exception:
        return False
    return not (
        st.wifi_scanning
        or st.wifi_connecting
        or st.box2_devices.scanning
        or st.box3_devices.scanning
        or st.location_switching
    )


def _sync_settings_zone2_tt(*, main_settings_widget) -> None:
    """Box1 stays pigeon wordmark + IP; drop any leftover TT payload."""
    if main_settings_widget is None:
        return
    st_ms = main_settings_widget.state
    if getattr(st_ms, "zone2_tt_bgra", None) is not None:
        st_ms.zone2_tt_bgra = None


def _paint_coalesced_settings_nav(*, _nav_coalescer_holder, main_settings_widget, render_once, skip_cache) -> None:
    skip_cache[0] = None
    coalescer = _nav_coalescer_holder[0]
    if main_settings_widget is not None and (
        coalescer is None or not coalescer.is_hot()
    ):
        main_settings_widget._nav_scrub = False
    render_once()


def _request_settings_nav_paint(*, _nav_coalescer_holder, main_settings_widget, render_once, skip_cache) -> None:
    skip_cache[0] = None
    if main_settings_widget is not None:
        main_settings_widget._nav_scrub = True
    coalescer = _nav_coalescer_holder[0]
    if coalescer is None:
        render_once()
        return
    coalescer.request()


def _handle_main_settings_action(action: str, *, _apply_persisted_location_to_runtime, _pyatv_install_hint, _rebuild_paired_devices_panel, _refresh_location_selector, _resolve_install_root_for_update, _save_box_pair_device_row, _schedule_refresh_pairing_leds, _sync_update_button_style, apple_tv_auto_state, apple_tv_dashboard_track, avr_slot_holder, begin_apple_tv_operation, current_apple_tv, describe_current_apple_tv, discovery_scan_cache, end_apple_tv_operation, main_settings_widget, pair_led_busy, receiver_http_host, root, skip_cache, streaming_slot_holder, update_check_state) -> None:
    if main_settings_widget is None:
        return
    st = main_settings_widget.state

    if action == "manual_search:set":
        # Pinned title: show it in now playing unless content is auto-detected.
        try:
            from pigeon import manual_search

            manual_search.show_in_now_playing()
        except Exception:
            pass
        main_settings_widget.invalidate()
        skip_cache[0] = None
        return

    if action in ("manual_search:clear", "keyboard_open:search"):
        main_settings_widget.invalidate()
        skip_cache[0] = None
        return

    if action == "pigeon_settings":
        # Entered settings_pigeon — seed update badge and refresh in background.
        def _prefetch_pigeon_update_badge() -> None:
            if not getattr(st, "pigeon_needs_update_prefetch", False):
                return
            st.pigeon_needs_update_prefetch = False
            try:
                if update_check_state.get("update_available") and not update_check_state.get(
                    "error"
                ):
                    st.update_available = True
                    st.update_remote_version = update_check_state.get("remote_version")
                    st.update_github_branch = update_check_state.get("github_branch")
                    st.update_error = None
                    main_settings_widget.invalidate()
                    skip_cache[0] = None
            except Exception:
                pass

            def worker_prefetch() -> None:
                try:
                    from pigeon.update_check import check_for_update

                    result = check_for_update(force=False)
                except Exception as e:
                    from pigeon.update_check import UpdateCheckResult

                    result = UpdateCheckResult(
                        local_version=version_string(),
                        remote_version=None,
                        update_available=False,
                        error=str(e),
                    )

                def finish_prefetch() -> None:
                    if main_settings_widget is None:
                        return
                    st2 = main_settings_widget.state
                    if not st2.show_pigeon_settings or st2.show_update_popup:
                        return
                    err = getattr(result, "error", None)
                    available = bool(getattr(result, "update_available", False)) and not err
                    st2.update_available = available
                    st2.update_remote_version = getattr(result, "remote_version", None)
                    st2.update_github_branch = getattr(result, "github_branch", None)
                    st2.update_error = err
                    try:
                        update_check_state["update_available"] = bool(available)
                        update_check_state["remote_version"] = st2.update_remote_version
                        update_check_state["github_branch"] = st2.update_github_branch
                        update_check_state["error"] = err
                        update_check_state["last_check_mono"] = time.monotonic()
                        _sync_update_button_style()
                    except Exception:
                        pass
                    main_settings_widget.invalidate()
                    skip_cache[0] = None

                root.after(0, finish_prefetch)

            threading.Thread(
                target=worker_prefetch, name="pigeon-update-prefetch", daemon=True
            ).start()

        _prefetch_pigeon_update_badge()
        return

    if action == "pigeon_restart":
        # settings_pigeon general → RESTART: relaunch the way the updater does.
        def _restart_pigeon() -> None:
            try:
                from pigeon.github_update import restart_pigeon_after_update

                restart_pigeon_after_update(
                    _resolve_install_root_for_update(), parent_pid=os.getpid()
                )
            except Exception:
                pass
            from pigeon.github_update import exit_code_after_update

            os._exit(exit_code_after_update())

        root.after(200, _restart_pigeon)
        return

    if action == "pigeon_factory_reset":
        from pigeon.widgets.pigeon_settings import factory_reset_pigeon_persisted_state
        from pigeon.widgets.ui_color_settings import (
            apply_color_keys_to_state,
            load_persisted_theme_into_state,
        )

        factory_reset_pigeon_persisted_state()
        try:
            discovery_scan_cache["rows"] = None
            discovery_scan_cache["mono_s"] = 0.0
        except Exception:
            pass
        try:
            streaming_slot_holder[0] = None
            avr_slot_holder[0] = None
        except Exception:
            pass
        try:
            current_apple_tv.clear()
            current_apple_tv.update(
                {"identifier": "", "address": "", "name": "", "label": ""}
            )
        except Exception:
            pass
        try:
            receiver_http_host["host"] = ""
        except Exception:
            pass
        try:
            apple_tv_auto_state["content_key"] = None
            apple_tv_auto_state["tmdb_key"] = None
            apple_tv_auto_state["query"] = None
            apple_tv_auto_state["last_metadata"] = None
            apple_tv_dashboard_track["last_poll_ok"] = None
            apple_tv_dashboard_track["consecutive_fail"] = 0
        except Exception:
            pass
        try:
            load_persisted_theme_into_state(st)
            apply_color_keys_to_state(
                st,
                {"accent": "white", "ui": "blue", "button": "black"},
                persist=False,
            )
            st.ui_color_committed_key = "blue"
            from pigeon.widgets.options_settings import load_options_into_state

            load_options_into_state(st)
        except Exception:
            pass
        try:
            st.reset_box_device_panel(2)
            st.reset_box_device_panel(3)
        except Exception:
            pass
        st.selected_wifi_ssid = ""
        st.live_wifi_ssid = ""
        st.wifi_logged_out = False
        st.pigeon_metadata_ok = False
        st.pigeon_audio_ok = False
        try:
            from pigeon.source_status import apply_source_status_to_settings_state

            apply_source_status_to_settings_state(st)
        except Exception:
            pass
        try:
            describe_current_apple_tv()
            _refresh_location_selector()
            _rebuild_paired_devices_panel()
            _schedule_refresh_pairing_leds()
        except Exception:
            pass
        main_settings_widget.invalidate()
        skip_cache[0] = None
        return

    if action in ("update_popup:open", "update_popup:check"):
        if action == "update_popup:open":
            # Seed with the last background poll so a known update shows its
            # build + red badge at once; the fresh check below replaces it.
            try:
                if float(update_check_state.get("last_check_mono") or 0.0) > 0.0 and not (
                    update_check_state.get("error")
                ):
                    st.update_available = bool(update_check_state.get("update_available"))
                    st.update_remote_version = update_check_state.get("remote_version")
                    st.update_github_branch = update_check_state.get("github_branch")
                    if st.update_available:
                        st.show_known_update_for_install()
                    st.set_update_popup_focus("update")
            except Exception:
                pass
        st.update_local_version = version_string()
        main_settings_widget.invalidate()
        skip_cache[0] = None
        if action == "update_popup:open" and not st.update_checking:
            # An update was already found: the next click confirms installing
            # it; re-checking here would just make the user wait again.
            return

        def worker_ms_update_check() -> None:
            try:
                from pigeon.update_check import check_for_update

                result = check_for_update(force=True)
            except Exception as e:
                from pigeon.update_check import UpdateCheckResult

                result = UpdateCheckResult(
                    local_version=version_string(),
                    remote_version=None,
                    update_available=False,
                    error=str(e),
                )

            def finish_ms_check() -> None:
                from pigeon.widgets.update_popup import (
                    DEFAULT_CHANGELOG,
                    UP_TO_DATE_CHANGELOG,
                )

                if st.update_applying:
                    return
                focus_before = st.update_popup_focused_choice
                st.update_checking = False
                st.update_local_version = str(
                    getattr(result, "local_version", None) or version_string()
                )
                st.update_remote_version = getattr(result, "remote_version", None)
                st.update_github_branch = getattr(result, "github_branch", None)
                st.update_error = getattr(result, "error", None)
                if st.update_error:
                    # The popup only shows a red bar; keep the reason readable.
                    msg_err = (
                        f"update check failed (local {st.update_local_version}): "
                        f"{str(st.update_error)[:300]}"
                    )
                    sys.stderr.write(f"pigeon: {msg_err}\n")
                    sys.stderr.flush()
                    try:
                        from pigeon.pi_diagnostics import append_pigeon_log

                        append_pigeon_log(msg_err)
                    except Exception:
                        pass
                available = bool(getattr(result, "update_available", False))
                st.update_available = available and not st.update_error
                # Confirmed current: pull version_update until the next visit.
                st.update_latest_confirmed = not st.update_available and not st.update_error
                st.update_changelog = (
                    DEFAULT_CHANGELOG if st.update_available else UP_TO_DATE_CHANGELOG
                )
                # Ring grows/shrinks with version_current — keep the same choice.
                st.set_update_popup_focus(focus_before)
                # Keep legacy Tk Updates button in sync when present.
                try:
                    update_check_state["update_available"] = bool(st.update_available)
                    update_check_state["remote_version"] = st.update_remote_version
                    update_check_state["github_branch"] = st.update_github_branch
                    update_check_state["error"] = st.update_error
                    update_check_state["last_check_mono"] = time.monotonic()
                    _sync_update_button_style()
                except Exception:
                    pass
                main_settings_widget.invalidate()
                skip_cache[0] = None

            root.after(0, finish_ms_check)

        threading.Thread(target=worker_ms_update_check, daemon=True).start()
        return

    if action in ("update_popup:back", "update_popup:stay", "update_popup:busy", "reset_confirm:open", "reset_confirm:cancel"):
        main_settings_widget.invalidate()
        skip_cache[0] = None
        return

    if action == "update_popup:now":
        if st.update_applying or st.update_checking:
            return
        if not st.update_available:
            st.close_update_popup()
            main_settings_widget.invalidate()
            skip_cache[0] = None
            return
        remote = str(st.update_remote_version or "?")
        branch = st.update_github_branch
        st.update_applying = True
        st.update_progress = 0.0
        st.update_changelog = f"Downloading {remote}…"
        main_settings_widget.invalidate()
        skip_cache[0] = None
        # Worker never calls root.after — Tk is not thread-safe and flooding
        # after() from download progress can drop the final restart callback.
        _ms_events: queue.Queue = queue.Queue()
        _ms_progress_last = [0.0]
        _ms_progress_label = [""]
        _ms_poll_active = [True]

        def _ms_on_progress(fraction: float, label: str) -> None:
            frac = max(0.0, min(1.0, float(fraction)))
            lab = str(label or "Updating…")[:96]
            if (
                frac < 0.999
                and frac - _ms_progress_last[0] < 0.02
                and lab == _ms_progress_label[0]
            ):
                return
            _ms_progress_last[0] = frac
            _ms_progress_label[0] = lab
            _ms_events.put(("progress", frac, lab))

        def _ms_poll_events() -> None:
            if main_settings_widget is None:
                return
            done_payload = None
            try:
                while True:
                    kind, *payload = _ms_events.get_nowait()
                    if kind == "progress":
                        frac, lab = payload
                        if st.update_applying:
                            st.update_progress = float(frac)
                            st.update_changelog = str(lab)
                            main_settings_widget.invalidate()
                            skip_cache[0] = None
                    elif kind == "done":
                        done_payload = payload[0]
            except queue.Empty:
                pass
            if done_payload is not None:
                _ms_poll_active[0] = False
                result, install_root = done_payload
                if result.ok:
                    st.update_progress = 1.0
                    st.update_changelog = "Update complete — restarting…"
                    st.update_available = False
                    try:
                        update_check_state["update_available"] = False
                        if result.remote_version:
                            update_check_state["remote_version"] = (
                                result.remote_version
                            )
                        _sync_update_button_style()
                    except Exception:
                        pass
                    main_settings_widget.invalidate()
                    skip_cache[0] = None

                    def _restart_ms() -> None:
                        try:
                            # Linux curl|bash updater already schedules
                            # in-app relaunch (PIGEON_UPDATE_IN_APP=1). On
                            # macOS/desktop we must schedule it here.
                            if not sys.platform.startswith("linux"):
                                from pigeon.github_update import (
                                    restart_pigeon_after_update,
                                )

                                restart_pigeon_after_update(
                                    install_root, parent_pid=os.getpid()
                                )
                        except Exception:
                            pass
                        # Exit unconditionally — do not wait on root.destroy().
                        # Non-zero under pigeon.service so systemd restarts us.
                        from pigeon.github_update import exit_code_after_update

                        os._exit(exit_code_after_update())

                    root.after(400, _restart_ms)
                    return

                st.update_applying = False
                st.update_progress = 0.0
                st.update_error = result.message
                st.update_changelog = (result.message or "Update failed.")[:96]
                main_settings_widget.invalidate()
                skip_cache[0] = None
                messagebox.showerror(
                    "Update failed",
                    result.message,
                    parent=root,
                )
                return
            if _ms_poll_active[0]:
                root.after(50, _ms_poll_events)

        def worker_ms_apply() -> None:
            install_root = _resolve_install_root_for_update()
            try:
                from pigeon.github_update import apply_github_update

                apply_branch = branch
                if apply_branch is None:
                    cached = update_check_state.get("github_branch")
                    if isinstance(cached, str) and cached.strip():
                        apply_branch = cached.strip()
                result = apply_github_update(
                    install_root,
                    branch=apply_branch,
                    progress=_ms_on_progress,
                )
            except Exception as e:
                from pigeon.github_update import ApplyUpdateResult

                result = ApplyUpdateResult(False, str(e))
            _ms_events.put(("done", (result, install_root)))

        root.after(50, _ms_poll_events)
        threading.Thread(target=worker_ms_apply, daemon=True).start()
        return

    if action == "keyboard_pin_incomplete":
        messagebox.showwarning("Pairing", "Enter the 4-digit code from the TV.", parent=root)
        return

    if action == "wifi_logout:yes":
        try:
            from pigeon.app_state import clear_location_wifi

            clear_location_wifi()
        except Exception:
            pass
        st.selected_wifi_ssid = ""
        st.live_wifi_ssid = ""
        st.wifi_logged_out = True
        st.wifi_password = ""
        st.pending_wifi_ssid = ""
        st.pending_network_password = ""
        st.network_password_error = False
        st.ensure_focus_ring()
        main_settings_widget.invalidate()
        skip_cache[0] = None
        return

    if action == "wifi_logout:no":
        main_settings_widget.invalidate()
        skip_cache[0] = None
        return

    if action == "keyboard_go:network":
        ssid = str(st.pending_wifi_ssid or "").strip()
        password = str(st.pending_network_password or "")
        if not ssid:
            return

        st.wifi_connecting = True
        st.wifi_connect_started_mono = time.monotonic()
        st.wifi_scan_angle_deg = 0.0
        st.network_password_error = False
        main_settings_widget.invalidate()
        skip_cache[0] = None

        def worker_wifi_join() -> None:
            try:
                from pigeon.wifi_connect import try_join_wifi_network

                ok_w, _msg_w = try_join_wifi_network(ssid, password)
            except Exception:
                ok_w, _msg_w = False, "incorrect password"

            def finish_wifi() -> None:
                st.wifi_connecting = False
                if ok_w:
                    st.wifi_logged_out = False
                    st.selected_wifi_ssid = ssid
                    st.live_wifi_ssid = ssid
                    st.wifi_password = password
                    st.pending_wifi_ssid = ""
                    st.pending_network_password = ""
                    st.network_password_error = False
                    st.wifi_onboarding = False
                    st.show_instructions = False
                    st.ensure_focus_ring()
                    try:
                        write_location_wifi(ssid, password)
                    except Exception:
                        pass
                    try:
                        from pigeon.local_ip import clear_local_ipv4_cache

                        clear_local_ipv4_cache()
                    except Exception:
                        pass
                else:
                    st.network_password_error = True
                    st.pending_network_password = ""
                    st.open_keyboard(
                        "network",
                        assets_dir=main_settings_widget._assets_dir,
                        trigger_button="main_dual_network_button",
                    )
                main_settings_widget.invalidate()
                skip_cache[0] = None

            root.after(0, finish_wifi)

        threading.Thread(target=worker_wifi_join, daemon=True).start()
        return

    if action == "keyboard_go:device_name":
        avr = read_saved_av_receiver()
        if avr:
            avr_slot_holder[0] = avr
            adr = str(avr.get("address") or "").strip()
            if adr:
                receiver_http_host["host"] = adr
        picked = st.box3_devices.picked
        if picked and str(picked[1] or "").strip():
            receiver_http_host["host"] = str(picked[1]).strip()
        main_settings_widget.invalidate()
        skip_cache[0] = None
        return

    if action == "keyboard_go:location":
        nm = str(st.location_name or "").strip() or "Room"
        lid = str(getattr(st, "renaming_location_id", "") or "").strip()
        if not lid:
            lid = read_current_location_id()
        if lid:
            rename_location_v2(lid, nm)
        try:
            st.refresh_location_slots()
        except Exception:
            pass
        st.renaming_location_id = ""
        st.renaming_location_slot = 0
        try:
            st.location_name = read_current_location_name()
        except Exception:
            st.location_name = nm
        if st.show_location_picker:
            st.ensure_focus_ring()
        main_settings_widget.invalidate()
        skip_cache[0] = None
        return

    if action == "location_switch:busy":
        return

    if action == "location_switch":
        if st.location_switching:
            return
        st.begin_location_switching()
        try:
            main_settings_widget._ensure_location_switch_spinner_frames()
        except Exception:
            pass
        main_settings_widget.invalidate()
        skip_cache[0] = None

        def _finish_location_switch() -> None:
            if main_settings_widget is None:
                return
            st_fin = main_settings_widget.state
            # Keep spinner up until pairing LED credential check settles.
            if pair_led_busy.get("active"):
                root.after(100, _finish_location_switch)
                return
            st_fin.finish_location_switching()
            main_settings_widget.invalidate()
            skip_cache[0] = None

        def _run_location_switch() -> None:
            try:
                _apply_persisted_location_to_runtime()
                try:
                    st.load_saved_box_devices()
                    st.location_name = read_current_location_name()
                except Exception:
                    pass
                try:
                    st.reload_location_wifi()
                except Exception:
                    pass
                try:
                    st.refresh_location_slots()
                except Exception:
                    pass
            finally:
                main_settings_widget.invalidate()
                skip_cache[0] = None
                root.after(0, _finish_location_switch)

        # Yield so the UI can paint; spinner appears if reload exceeds ~2s.
        root.after(0, _run_location_switch)
        return

    if action == "box3_pair_start":
        sess = st.box_pairing
        if sess is None or int(sess.box_num) != 3:
            return
        _save_box_pair_device_row(3, sess.row)
        name = str(sess.row.get("name") or sess.row.get("label") or "Receiver").strip()
        ip = str(sess.row.get("address") or "").strip()
        if ip:
            st.box3_devices.picked = (name or ip, ip)
            st.box3_ip_invalid = False
        st.show_box3_panel = True
        st.clear_box_pairing()
        main_settings_widget.invalidate()
        skip_cache[0] = None
        _schedule_refresh_pairing_leds()
        _rebuild_paired_devices_panel()
        return

    if action == "box2_pair_start":
        sess = st.box_pairing
        if sess is None or int(sess.box_num) != 2:
            return
        row = dict(sess.row)
        if not begin_apple_tv_operation("starting AppleTV Remote"):
            return

        def worker_remote_begin_settings() -> None:
            try:
                from pigeon.apple_tv_now_playing import begin_companion_pairing_for_device

                ok_w, msg_w, session_key_w, _rev = begin_companion_pairing_for_device(
                    device_identifier=row["identifier"],
                    device_address=row["address"],
                    tv_displays_pin=True,
                )
            except ImportError:
                ok_w, msg_w, session_key_w = False, _pyatv_install_hint(), None
            except Exception as e:
                ok_w, msg_w, session_key_w = False, str(e), None

            def finish_rb_settings() -> None:
                if not ok_w or not session_key_w:
                    end_apple_tv_operation()
                    st.clear_box_pairing()
                    main_settings_widget.invalidate()
                    skip_cache[0] = None
                    messagebox.showerror("AppleTV Remote", msg_w or "Pairing failed to start.")
                    return
                if st.box_pairing is not None:
                    st.box_pairing.session_key = str(session_key_w)
                    st.box_pairing.step = "remote_pin"
                st.open_keyboard("pin", assets_dir=main_settings_widget._assets_dir)
                main_settings_widget.invalidate()
                skip_cache[0] = None
                describe_current_apple_tv(suffix="enter Remote PIN")

            root.after(0, finish_rb_settings)

        threading.Thread(target=worker_remote_begin_settings, daemon=True).start()
        return

    if action.startswith("keyboard_pin:"):
        pin = action.split(":", 1)[1].strip()
        pin = "".join(c for c in pin if c.isdigit())
        if len(pin) != 4:
            messagebox.showwarning("Pairing", "Enter the 4-digit code from the TV.", parent=root)
            return
        sess = st.box_pairing
        if sess is None or not sess.session_key:
            return
        row = dict(sess.row)
        dn = sess.device_name

        if sess.step == "remote_pin":

            def worker_remote_finish_settings() -> None:
                try:
                    from pigeon.apple_tv_now_playing import begin_airplay_pairing_for_device, finish_companion_pairing_for_device

                    ok_f, msg_f = finish_companion_pairing_for_device(
                        session_key=sess.session_key, pin_code=pin
                    )
                except ImportError:
                    ok_f, msg_f = False, _pyatv_install_hint()
                except Exception as e:
                    ok_f, msg_f = False, str(e)

                if ok_f:
                    time.sleep(1.5)

                def done_rf_settings() -> None:
                    if not ok_f:
                        end_apple_tv_operation()
                        st.clear_box_pairing()
                        main_settings_widget.invalidate()
                        skip_cache[0] = None
                        messagebox.showerror("AppleTV Remote", msg_f)
                        _schedule_refresh_pairing_leds()
                        return
                    try:
                        ok_a, msg_a, sk_a, _r2 = begin_airplay_pairing_for_device(
                            device_identifier=row["identifier"],
                            device_address=row["address"],
                            tv_displays_pin=True,
                        )
                    except ImportError:
                        ok_a, msg_a, sk_a = False, _pyatv_install_hint(), None
                    except Exception as e:
                        ok_a, msg_a, sk_a = False, str(e), None
                    if not ok_a or not sk_a:
                        end_apple_tv_operation()
                        st.clear_box_pairing()
                        main_settings_widget.invalidate()
                        skip_cache[0] = None
                        messagebox.showerror("AppleTV AirPlay", msg_a or "AirPlay pairing failed to start.")
                        _schedule_refresh_pairing_leds()
                        return
                    if st.box_pairing is not None:
                        st.box_pairing.session_key = str(sk_a)
                        st.box_pairing.step = "airplay_pin"
                    st.open_keyboard("pin", assets_dir=main_settings_widget._assets_dir)
                    main_settings_widget.invalidate()
                    skip_cache[0] = None
                    describe_current_apple_tv(suffix="enter AirPlay PIN")

                root.after(0, done_rf_settings)

            threading.Thread(target=worker_remote_finish_settings, daemon=True).start()
            return

        if sess.step == "airplay_pin":

            def worker_air_finish_settings() -> None:
                try:
                    from pigeon.apple_tv_now_playing import finish_companion_pairing_for_device

                    ok_af, msg_af = finish_companion_pairing_for_device(
                        session_key=sess.session_key, pin_code=pin
                    )
                except ImportError:
                    ok_af, msg_af = False, _pyatv_install_hint()
                except Exception as e:
                    ok_af, msg_af = False, str(e)

                def done_air_settings() -> None:
                    end_apple_tv_operation()
                    if ok_af:
                        _save_box_pair_device_row(2, row)
                        st.load_saved_box_devices()
                        st.show_box2_panel = True
                    st.clear_box_pairing()
                    main_settings_widget.invalidate()
                    skip_cache[0] = None
                    if ok_af:
                        try:
                            sys.stderr.write(
                                f"pigeon: Apple TV AirPlay paired for Player {dn!r}: {msg_af}\n"
                            )
                            sys.stderr.flush()
                        except Exception:
                            pass
                    else:
                        messagebox.showerror("AppleTV AirPlay", msg_af)
                    _schedule_refresh_pairing_leds()
                    _rebuild_paired_devices_panel()

                root.after(0, done_air_settings)

            threading.Thread(target=worker_air_finish_settings, daemon=True).start()


def _composite_settings_on_canvas(canvas: np.ndarray, *, _nav_coalescer_holder, _show_paused_row_overlay, _something_playing_now, _sync_now_playing_screen_state, _sync_preferences_now_playing_progress, _sync_settings_zone2_tt, main_settings_widget, view_circles_widget) -> None:
    """Paint settings (no NP status bar overlay)."""
    if main_settings_widget is None:
        return
    coalescer = _nav_coalescer_holder[0]
    nav_hot = bool(coalescer is not None and coalescer.is_hot())
    if not nav_hot:
        try:
            _sync_preferences_now_playing_progress()
            _sync_settings_zone2_tt()
        except Exception:
            pass
    # No NP status bar on settings_main: the SEARCH bar owns that strip.
    main_settings_widget.render(canvas)


def _force_advanced_feature_try(feature_id: str, *, _apple_tv_auto_poll_tick, _receiver_poll_tick, on_apple_tv_selected_then_tmdb) -> None:
    """Advanced matrix refresh: re-run the probe path relevant to this feature row."""
    try:
        if feature_id == "title":
            on_apple_tv_selected_then_tmdb()
        else:
            if feature_id == "volume":
                _receiver_poll_tick()
            _apple_tv_auto_poll_tick()
    except Exception:
        pass


def _enter_main_settings_for_rotary(*, DevPhase, dev_phase, main_settings_widget, render_once, skip_cache, sync_developer_chrome) -> bool:
    """Bring up main settings so the encoder can drive the new menus."""
    if main_settings_widget is None:
        return False
    if dev_phase[0] == DevPhase.MAIN_SETTINGS:
        return True
    try:
        if main_settings_widget.state.keyboard_open:
            main_settings_widget.state.close_keyboard(commit=False)
            main_settings_widget.invalidate()
    except Exception:
        pass
    try:
        from pigeon.widgets.ui_color_settings import load_persisted_theme_into_state

        load_persisted_theme_into_state(main_settings_widget.state)
        main_settings_widget.invalidate()
    except Exception:
        pass
    dev_phase[0] = DevPhase.MAIN_SETTINGS
    try:
        main_settings_widget.prefetch_scans_for_settings()
    except Exception:
        pass
    try:
        from pigeon.weather import refresh_weather

        refresh_weather(force=True)
    except Exception:
        pass
    skip_cache[0] = None
    sync_developer_chrome()
    render_once()
    return True


def _open_advanced_capability_matrix(*, _PIGEON_EXT, _advanced_feature_pipeline_ok, _force_advanced_feature_try, _on_advanced_matrix_closed, _perform_tmdb_artwork_retry, _prepend_hotkey_bindtag, _register_tmdb_adv_widgets, _tmdb_retry_log_read_tail, _unregister_tmdb_adv_widgets, advanced_matrix_close_skip, on_apple_tv_selected_then_tmdb, root) -> None:
    try:
        from settings_advanced_matrix import open_advanced_capability_matrix
    except ImportError as e:
        messagebox.showerror("Advanced", f"Could not open capability matrix:\n{e}", parent=root)
        return
    adv_kw: dict[str, object] = {
        "playback_content_ok": _advanced_feature_pipeline_ok,
        "on_closed": _on_advanced_matrix_closed,
        "close_skip_once": advanced_matrix_close_skip,
        "feature_force_try": _force_advanced_feature_try,
    }
    if _PIGEON_EXT:
        adv_kw.update(
            {
                "tmdb_manual_fetch": on_apple_tv_selected_then_tmdb,
                "tmdb_report_failure": _perform_tmdb_artwork_retry,
                "tmdb_read_log_tail": _tmdb_retry_log_read_tail,
                "tmdb_register_widgets": _register_tmdb_adv_widgets,
                "tmdb_unregister_widgets": _unregister_tmdb_adv_widgets,
                "prepend_hotkey_bindtag": _prepend_hotkey_bindtag,
                "tmdb_quality_stats_read": lambda: {
                    "successes": int(
                        read_app_state().get("tmdb_quality_successes", 0) or 0
                    ),
                    "failures": int(
                        read_app_state().get("tmdb_quality_failures", 0) or 0
                    ),
                },
            }
        )
    open_advanced_capability_matrix(root, **adv_kw)


def _maybe_exit_settings_menus_on_idle(now_mono: float | None = None, *, DevPhase, SETTINGS_MENU_IDLE_EXIT_S, dev_phase, last_pigeon_user_activity_mono, main_settings_widget_holder, skip_cache, sync_developer_chrome) -> bool:
    """Close settings_main after ``SETTINGS_MENU_IDLE_EXIT_S`` without input.

    Returns True when menus were closed (compose should show now-playing or
    clock saver via the normal OFF-phase path).
    """
    if dev_phase[0] != DevPhase.MAIN_SETTINGS:
        return False
    now_i = float(now_mono if now_mono is not None else time.monotonic())
    if (now_i - float(last_pigeon_user_activity_mono[0])) < float(
        SETTINGS_MENU_IDLE_EXIT_S
    ):
        return False
    if main_settings_widget_holder[0] is not None:
        try:
            if not bool(getattr(main_settings_widget_holder[0].state, "exit_enabled", True)):
                return False
        except Exception:
            pass
    if main_settings_widget_holder[0] is not None:
        try:
            st_ms = main_settings_widget_holder[0].state
            if st_ms.keyboard_open:
                st_ms.close_keyboard(commit=False)
            st_ms.exit_pigeon_settings()
            main_settings_widget_holder[0].invalidate()
        except Exception:
            pass
    dev_phase[0] = DevPhase.OFF
    skip_cache[0] = None
    try:
        sync_developer_chrome()
    except Exception:
        pass
    return True


def _sync_preferences_now_playing_progress(*, _active_tmdb_tt_src_bgra, _circles_poster_bgra, _format_hmmss, _playback_extrapolated_pair, _playback_progress_fraction_for_bar, _resolve_receiver_lines_for_now_playing, _vv_is_music, active_tmdb_display_title, active_tmdb_title_key, apple_tv_auto_state, apple_tv_playback_clock, main_settings_widget_holder, streaming_badge_state) -> None:
    """Feed live NP content into prefs; idle keeps SVG demos."""
    if main_settings_widget_holder[0] is None:
        return
    st_ms = main_settings_widget_holder[0].state
    if not st_ms.show_preferences:
        return

    def _clear_prefs_live() -> None:
        st_ms.preferences_live_content = False
        st_ms.preferences_np_progress = None
        st_ms.preferences_poster_bgra = None
        st_ms.preferences_volume = None
        st_ms.preferences_volume_fraction = None
        st_ms.preferences_incoming = None
        st_ms.preferences_config = None
        st_ms.preferences_cast = None
        st_ms.preferences_elapsed_text = None
        st_ms.preferences_remaining_text = None
        st_ms.preferences_service_name = None
        st_ms.preferences_content_mode = None
        st_ms.preferences_song_title = None
        st_ms.preferences_album_title = None
        st_ms.preferences_artist_title = None
        st_ms.preferences_tt_bgra = None

    try:
        prog = _playback_progress_fraction_for_bar()
    except Exception:
        prog = None
    clk = apple_tv_playback_clock
    has_playback = bool(clk.get("has_sync") or clk.get("live_mode"))
    poster = None
    try:
        poster = _circles_poster_bgra()
    except Exception:
        poster = None
    live = bool(
        has_playback
        or prog is not None
        or (poster is not None and getattr(poster, "size", 0) > 0)
        or bool(str(active_tmdb_title_key[0] or "").strip())
    )
    if not live:
        _clear_prefs_live()
        return

    st_ms.preferences_live_content = True
    st_ms.preferences_np_progress = prog
    st_ms.preferences_poster_bgra = poster
    try:
        inc, cfg, vol = _resolve_receiver_lines_for_now_playing()
    except Exception:
        inc, cfg, vol = "", "", ""
    st_ms.preferences_incoming = inc
    st_ms.preferences_config = cfg
    st_ms.preferences_volume = vol
    try:
        from pigeon.widgets.playback_overlay import volume_fraction_from_display_line

        st_ms.preferences_volume_fraction = float(
            volume_fraction_from_display_line(vol)
        )
    except Exception:
        st_ms.preferences_volume_fraction = 0.0

    remaining_text = ""
    played_text = ""
    if clk.get("live_mode"):
        remaining_text = "LIVE"
        played_text = "LIVE"
    else:
        try:
            pair = _playback_extrapolated_pair()
        except Exception:
            pair = None
        if pair is not None:
            played_text = _format_hmmss(int(pair[0]))
            remaining_text = _format_hmmss(int(pair[1]))
    st_ms.preferences_elapsed_text = played_text
    st_ms.preferences_remaining_text = remaining_text

    sb = streaming_badge_state
    svc = str(sb.get("label") or "").strip()
    if not svc:
        lm_svc = apple_tv_auto_state.get("last_metadata")
        if isinstance(lm_svc, dict):
            svc = str(lm_svc.get("app_name") or "").strip()
    st_ms.preferences_service_name = svc

    is_music = bool(_vv_is_music())
    st_ms.preferences_content_mode = "music" if is_music else "video"
    if is_music:
        lm_music = apple_tv_auto_state.get("last_metadata")
        song_t = album_t = artist_t = ""
        if isinstance(lm_music, dict):
            song_t = str(lm_music.get("title") or "").strip()
            album_t = str(lm_music.get("album") or "").strip()
            artist_t = str(lm_music.get("artist") or "").strip()
            if not song_t and album_t:
                song_t, album_t = album_t, ""
        st_ms.preferences_song_title = song_t
        st_ms.preferences_album_title = album_t
        st_ms.preferences_artist_title = artist_t
        st_ms.preferences_cast = ()
        st_ms.preferences_tt_bgra = poster
    else:
        st_ms.preferences_song_title = str(
            active_tmdb_display_title[0] or ""
        ).strip()
        st_ms.preferences_album_title = ""
        st_ms.preferences_artist_title = ""
        cast_rows: list[tuple[str, str]] = []
        try:
            from pigeon.tmdb_poster import get_cached_tmdb_cast

            tk = str(active_tmdb_title_key[0] or "").strip()
            if tk:
                cast_rows = list(get_cached_tmdb_cast(tk) or [])
        except Exception:
            cast_rows = []
        st_ms.preferences_cast = tuple(
            (str(a or ""), str(c or "")) for a, c in cast_rows[:9]
        )
        try:
            st_ms.preferences_tt_bgra = _active_tmdb_tt_src_bgra()
        except Exception:
            st_ms.preferences_tt_bgra = None
