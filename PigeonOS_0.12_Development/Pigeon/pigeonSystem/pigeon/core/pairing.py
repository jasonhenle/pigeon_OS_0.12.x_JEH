"""Device discovery and pairing: the find-device dialog, AirPlay / player pairing wizard, and post-save verification.

Extracted verbatim from ``bootstrap()`` in ``pigeon_0_12.py``. Each function
takes the app state it used to close over as keyword-only arguments;
``bootstrap()`` binds them once with ``bind_deps`` so call sites are unchanged.
"""

from __future__ import annotations

from pigeon.app_state import LOCATION_PRESET_ROOM_NAMES
from pigeon.app_state import append_device_to_location_slot
from pigeon.app_state import read_all_locations_v2
from pigeon.app_state import read_current_location_id
from pigeon.app_state import row_is_playback_apple_tv
from pigeon.app_state import set_current_location_id
import threading
import time
import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.simpledialog as simpledialog
from pigeon.app_state import clear_last_apple_tv
from pigeon.app_state import clear_last_receiver
from pigeon.app_state import read_saved_av_receiver
from pigeon.app_state import read_saved_streaming_device
from pigeon.app_state import read_saved_streaming_devices_all
from pigeon.app_state import remove_device_at_slot_index
from pigeon.app_state import write_last_receiver


def _verify_added_devices_after_save(added: list[dict[str, str]], *, root) -> None:
    if not added:
        return

    def work() -> None:
        bad: list[str] = []
        for row in added:
            addr = str(row.get("address") or "").strip()
            if not addr:
                continue
            try:
                from pigeon.apple_tv_now_playing import probe_pyatv_host

                ok_w, msg_w, _, _ = probe_pyatv_host(addr, scan_timeout_s=6)
            except Exception as e:
                ok_w, msg_w = False, str(e)
            if not ok_w:
                label = str(row.get("label") or row.get("name") or addr)
                tail = (msg_w or "no response")[:160]
                bad.append(f"• {label} ({addr}): {tail}")

        def done() -> None:
            if bad:
                messagebox.showwarning(
                    "Device check",
                    "After saving, a quick follow-up scan could not reach some new entries "
                    "(sleeping, offline, or firewalled):\n\n" + "\n".join(bad),
                    parent=root,
                )

        root.after(0, done)

    threading.Thread(target=work, daemon=True).start()


def _start_airplay_pairing_sequence(row: dict[str, str], dn: str, *, _ask_pairing_pin_modal, _pyatv_install_hint, _schedule_refresh_pairing_leds, begin_apple_tv_operation, describe_current_apple_tv, end_apple_tv_operation, root) -> None:
    if not messagebox.askokcancel(
        "AppleTV AirPlay",
        "Next: AppleTV AirPlay pairing will show a new code on the Apple TV.\n\n"
        "Continue only after the first (Remote) pairing has fully finished on the TV.\n\n"
        "Then open AirPlay / on-screen pairing on the Apple TV so it can show the next code.",
        parent=root,
    ):
        return
    if not begin_apple_tv_operation("starting AppleTV AirPlay"):
        return

    def worker_air_begin() -> None:
        try:
            from pigeon.apple_tv_now_playing import begin_airplay_pairing_for_device

            ok_a, msg_a, sk_a, _r2 = begin_airplay_pairing_for_device(
                device_identifier=row["identifier"],
                device_address=row["address"],
                tv_displays_pin=True,
            )
        except ImportError:
            ok_a, msg_a, sk_a, _r2 = False, _pyatv_install_hint(), None, None
        except Exception as e:
            ok_a, msg_a, sk_a, _r2 = False, str(e), None, None

        def ui_air_b() -> None:
            if not ok_a or not sk_a:
                end_apple_tv_operation()
                messagebox.showerror("AppleTV AirPlay", msg_a or "Pairing failed to start.")
                return
            # Keep apple_tv_busy True until PIN is submitted so auto-poll cannot start a second connection.
            describe_current_apple_tv(suffix="enter AirPlay PIN")
            pin2 = _ask_pairing_pin_modal(
                root,
                title="AppleTV AirPlay",
                device_name=dn,
                pair_kind="AppleTV AirPlay pairing",
                session_key=sk_a,
            )
            if pin2 is None:
                end_apple_tv_operation()
                messagebox.showinfo("AppleTV AirPlay", "Pairing cancelled.")
                _schedule_refresh_pairing_leds()
                return

            def worker_air_finish() -> None:
                try:
                    from pigeon.apple_tv_now_playing import finish_companion_pairing_for_device

                    ok_af, msg_af = finish_companion_pairing_for_device(
                        session_key=sk_a, pin_code=pin2
                    )
                except ImportError:
                    ok_af, msg_af = False, _pyatv_install_hint()
                except Exception as e:
                    ok_af, msg_af = False, str(e)

                def done_af() -> None:
                    end_apple_tv_operation()
                    if ok_af:
                        messagebox.showinfo("AppleTV AirPlay", msg_af)
                    else:
                        messagebox.showerror("AppleTV AirPlay", msg_af)
                    _schedule_refresh_pairing_leds()

                root.after(0, done_af)

            threading.Thread(target=worker_air_finish, daemon=True).start()

        root.after(0, ui_air_b)

    threading.Thread(target=worker_air_begin, daemon=True).start()


def _run_sequential_player_pairing_wizard(row: dict[str, str], *, _ask_pairing_pin_modal, _finish_remote_then_start_airplay, _pyatv_install_hint, _schedule_refresh_pairing_leds, begin_apple_tv_operation, describe_current_apple_tv, end_apple_tv_operation, root) -> None:
    if not row_is_playback_apple_tv(row):
        return
    dn = str(row.get("name") or row.get("label") or "Apple TV")
    if not messagebox.askokcancel(
        "AppleTV Remote",
        "Pair AppleTV Remote first, then AppleTV AirPlay. Codes appear on the Apple TV.\n\n"
        "On the Apple TV: Settings → Remotes and Devices → Remote App and Devices — keep it open until a code appears.\n\n"
        "Continue?",
        parent=root,
    ):
        return
    if not begin_apple_tv_operation("starting AppleTV Remote"):
        return

    def worker_remote_begin() -> None:
        try:
            from pigeon.apple_tv_now_playing import begin_companion_pairing_for_device

            ok_w, msg_w, session_key_w, _rev = begin_companion_pairing_for_device(
                device_identifier=row["identifier"],
                device_address=row["address"],
                tv_displays_pin=True,
            )
        except ImportError:
            ok_w, msg_w, session_key_w, _rev = False, _pyatv_install_hint(), None, None
        except Exception as e:
            ok_w, msg_w, session_key_w, _rev = False, str(e), None, None

        def finish_rb() -> None:
            if not ok_w or not session_key_w:
                end_apple_tv_operation()
                messagebox.showerror("AppleTV Remote", msg_w or "Pairing failed to start.")
                return
            # Stay busy through PIN entry so background Apple TV polling cannot connect yet.
            describe_current_apple_tv(suffix="enter Remote PIN")
            pin = _ask_pairing_pin_modal(
                root,
                title="AppleTV Remote",
                device_name=dn,
                pair_kind="AppleTV Remote pairing",
                session_key=session_key_w,
            )
            if pin is None:
                end_apple_tv_operation()
                messagebox.showinfo("AppleTV Remote", "Pairing cancelled.")
                _schedule_refresh_pairing_leds()
                return
            _finish_remote_then_start_airplay(row, dn, session_key_w, pin)

        root.after(0, finish_rb)

    threading.Thread(target=worker_remote_begin, daemon=True).start()


def _open_find_device_dialog(*, DISCOVERY_CACHE_TTL_S, S_FONT_BODY, S_FONT_BTN, S_FONT_MICRO, S_FONT_SMALL, S_FONT_STATUS, _LISTBOX_BG, _LISTBOX_FG, _PIGEON_EXT, _apply_persisted_location_to_runtime, _pyatv_install_hint, _refresh_location_selector, _run_sequential_player_pairing_wizard, _verify_added_devices_after_save, begin_apple_tv_operation, discovery_scan_cache, end_apple_tv_operation, root) -> None:
    if not _PIGEON_EXT:
        messagebox.showinfo("Devices", "Pigeon extensions not loaded.")
        return
    top = tk.Toplevel(root)
    top.title("Find device")
    top.configure(bg="#1a1a1e")
    try:
        top.transient(root)
        top.grab_set()
    except tk.TclError:
        pass

    scan_rows: list[list[dict[str, str]]] = [[]]
    busy = {"v": False}
    confirm_holder: list[tk.Button | None] = [None]

    hdr = tk.Frame(top, bg="#1a1a1e")
    hdr.pack(fill=tk.X, padx=12, pady=(12, 8))
    find_btn = tk.Button(hdr, text="Find devices", font=S_FONT_BTN, padx=12, pady=4)
    refresh_btn = tk.Button(hdr, text="Refresh (network scan)", font=S_FONT_BTN, padx=10, pady=4)
    find_btn.pack(side=tk.LEFT, padx=(0, 8))
    refresh_btn.pack(side=tk.LEFT, padx=(0, 0))

    tk.Label(
        top,
        text="Use Find devices (cached scan when available) or Refresh for a live network scan. "
        "The list shows every device the scan returns (nothing is hidden). "
        "Pick a row or enter Host/IP, then Confirm — you will choose the device type and optional nickname. "
        "The same device can be saved more than once for different roles.",
        fg="#888",
        bg="#1a1a1e",
        font=S_FONT_MICRO,
        wraplength=560,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, padx=12, pady=(0, 6))

    search_banner_var = tk.StringVar(value="")
    tk.Label(
        top,
        textvariable=search_banner_var,
        fg="#ffb020",
        bg="#1a1a1e",
        font=("Helvetica", 22, "bold"),
    ).pack(anchor=tk.W, padx=12, pady=(0, 4))

    status_var = tk.StringVar(value="")

    loc_pick_var = tk.StringVar(value="")
    loc_pick_holder: list[list[tuple[str, str | None, str | None]]] = [[]]

    def build_location_pick_choices() -> list[tuple[str, str | None, str | None]]:
        ch: list[tuple[str, str | None, str | None]] = []
        counts: dict[str, int] = {}
        for L in read_all_locations_v2():
            base = str(L.get("name") or "Room").strip() or "Room"
            counts[base] = counts.get(base, 0) + 1
            c = counts[base]
            lab = base if c == 1 else f"{base} ({c})"
            lid_g = str(L.get("id") or "").strip() or None
            ch.append((lab, lid_g, None))
        for p in LOCATION_PRESET_ROOM_NAMES:
            ch.append((f"+ New: {p}", None, p))
        ch.append(("+ New: Custom…", None, "__custom__"))
        return ch

    loc_pick_row = tk.Frame(top, bg="#1a1a1e")
    loc_pick_frame = tk.Frame(loc_pick_row, bg="#1a1a1e")
    btn_row = tk.Frame(loc_pick_row, bg="#1a1a1e")

    def refresh_location_pick_menu() -> None:
        for w in loc_pick_frame.winfo_children():
            try:
                w.destroy()
            except tk.TclError:
                pass
        chs = build_location_pick_choices()
        loc_pick_holder[0] = chs
        labels = [t[0] for t in chs]
        cur = read_current_location_id()
        pick_default = labels[0] if labels else ""
        for disp, lid_g, _nn in chs:
            if lid_g and lid_g == cur:
                pick_default = disp
                break
        if pick_default:
            loc_pick_var.set(pick_default)
        if labels:
            tk.OptionMenu(loc_pick_frame, loc_pick_var, *labels).pack(side=tk.LEFT)

    tk.Label(
        loc_pick_row,
        text="Save to location:",
        fg="#aaa",
        bg="#1a1a1e",
        font=S_FONT_SMALL,
    ).pack(side=tk.LEFT)
    loc_pick_frame.pack(side=tk.LEFT, padx=(8, 0))
    loc_pick_row.pack(anchor=tk.W, padx=12, pady=(0, 6))
    refresh_location_pick_menu()

    def resolve_save_location() -> tuple[str | None, str | None]:
        pick = str(loc_pick_var.get() or "")
        for disp, lid_g, nn in loc_pick_holder[0]:
            if disp != pick:
                continue
            if nn == "__custom__":
                name = simpledialog.askstring(
                    "Location name",
                    "Custom room name:",
                    parent=top,
                )
                return (None, (name or "").strip() or "Room")
            if lid_g:
                return (lid_g, None)
            if nn:
                return (None, nn)
        cur = read_current_location_id()
        return (cur or None, None)

    list_rows_holder: list[list[dict[str, str]]] = [[]]
    lb_frame = tk.Frame(top, bg="#1a1a1e")
    lb_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))
    sb = tk.Scrollbar(lb_frame, orient=tk.VERTICAL)
    lb = tk.Listbox(
        lb_frame,
        height=12,
        bg=_LISTBOX_BG,
        fg=_LISTBOX_FG,
        font=S_FONT_STATUS,
        selectmode=tk.SINGLE,
        highlightthickness=1,
        highlightbackground="#333",
    )
    sb.config(command=lb.yview)
    lb.configure(yscrollcommand=sb.set)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    host_var = tk.StringVar(value="")

    def apply_listbox_rows(rows: list[dict[str, str]], *, empty_message: str | None = None) -> None:
        lb.delete(0, tk.END)
        list_rows_holder[0] = [dict(r) for r in rows]
        if not list_rows_holder[0]:
            lb.insert(tk.END, empty_message or "No devices in list — try Refresh or Host / IP.")
        else:
            for r in list_rows_holder[0]:
                lb.insert(tk.END, str(r.get("label") or r.get("name") or r.get("address")))

    def repopulate_from_scan() -> None:
        rows_full = [dict(r) for r in scan_rows[0]]
        apply_listbox_rows(rows_full)

    def list_selection_row() -> dict[str, str] | None:
        sel = lb.curselection()
        if not sel:
            return None
        idx = int(sel[0])
        rows_now = list_rows_holder[0]
        if idx < 0 or idx >= len(rows_now):
            return None
        return dict(rows_now[idx])

    def set_scan(rows_in: list[dict[str, str]], msg: str) -> None:
        scan_rows[0] = [dict(r) for r in rows_in]
        status_var.set(msg)
        repopulate_from_scan()

    def run_scan(*, force_network: bool) -> None:
        if busy["v"]:
            return
        busy["v"] = True
        now_chk = time.monotonic()
        cached_chk = discovery_scan_cache.get("rows")
        cache_mono_chk = float(discovery_scan_cache.get("mono_s") or 0.0)
        has_cache = (
            not force_network
            and isinstance(cached_chk, list)
            and len(cached_chk) > 0
            and (now_chk - cache_mono_chk) <= DISCOVERY_CACHE_TTL_S
        )
        search_banner_var.set("" if has_cache else "SEARCHING")
        status_var.set("Scanning\u2026" if force_network else "Loading\u2026")
        apply_listbox_rows(
            [],
            empty_message=(
                "SEARCHING \u2014 scanning the network\u2026"
                if not has_cache
                else "Loading cached devices\u2026"
            ),
        )
        for w in (find_btn, refresh_btn):
            w.configure(state=tk.DISABLED)
        c = confirm_holder[0]
        if c is not None:
            c.configure(state=tk.DISABLED)
        result: dict[str, object] = {}

        def worker() -> None:
            now_m = time.monotonic()
            rows_w: list[dict[str, str]] = []
            ok_w = True
            msg_w = ""
            used_cache = False
            cached = discovery_scan_cache.get("rows")
            cache_mono = float(discovery_scan_cache.get("mono_s") or 0.0)
            if (
                not force_network
                and isinstance(cached, list)
                and len(cached) > 0
                and (now_m - cache_mono) <= DISCOVERY_CACHE_TTL_S
            ):
                rows_w = [dict(r) for r in cached]
                used_cache = True
            else:
                try:
                    from pigeon.apple_tv_now_playing import scan_apple_tv_devices

                    ok_w, msg_w, rows_w = scan_apple_tv_devices(scan_timeout_s=15)
                except ImportError:
                    ok_w, msg_w, rows_w = False, _pyatv_install_hint(), []
                except Exception as e:
                    ok_w, msg_w, rows_w = False, str(e), []
                if ok_w and rows_w:
                    discovery_scan_cache["rows"] = [dict(r) for r in rows_w]
                    discovery_scan_cache["mono_s"] = time.monotonic()
            result["ok"] = ok_w
            result["rows"] = rows_w
            result["msg"] = msg_w
            result["used"] = used_cache

        def finish_scan() -> None:
            busy["v"] = False
            search_banner_var.set("")
            for w in (find_btn, refresh_btn):
                w.configure(state=tk.NORMAL)
            c2 = confirm_holder[0]
            if c2 is not None:
                c2.configure(state=tk.NORMAL)
            ok_w = bool(result.get("ok", True))
            rows_w = result.get("rows") or []
            msg_w = str(result.get("msg") or "")
            used_cache = bool(result.get("used"))
            if not isinstance(rows_w, list):
                rows_w = []
            if not ok_w:
                messagebox.showerror("Find device", msg_w)
                status_var.set("Scan failed.")
                apply_listbox_rows([], empty_message="Search failed — try Refresh.")
                return
            if not rows_w:
                messagebox.showinfo("Find device", msg_w or "No devices found.")
                status_var.set("No devices.")
                scan_rows[0] = []
                apply_listbox_rows([], empty_message="No devices found — try Refresh or Host / IP.")
                return
            suffix = f"{len(rows_w)} found" + (" (cached)" if used_cache else "")
            set_scan(rows_w, suffix)

        threading.Thread(target=lambda: (worker(), root.after(0, finish_scan)), daemon=True).start()

    def on_find_devices_click() -> None:
        run_scan(force_network=False)

    def on_refresh_click() -> None:
        run_scan(force_network=True)

    find_btn.configure(command=on_find_devices_click)
    refresh_btn.configure(command=on_refresh_click)

    tk.Label(
        top,
        text="Host / IP (optional, instead of list):",
        fg="#aaa",
        bg="#1a1a1e",
        font=S_FONT_SMALL,
    ).pack(anchor=tk.W, padx=12)
    tk.Entry(
        top,
        textvariable=host_var,
        width=36,
        bg="#252528",
        fg="#e8e8e8",
        insertbackground="#e8e8e8",
        highlightthickness=1,
        highlightbackground="#333",
        font=S_FONT_BODY,
    ).pack(anchor=tk.W, padx=12, pady=(2, 8))

    tk.Label(
        top,
        textvariable=status_var,
        fg="#777",
        bg="#1a1a1e",
        font=S_FONT_MICRO,
        wraplength=500,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, padx=12, pady=(0, 6))

    def close_top() -> None:
        try:
            top.grab_release()
        except tk.TclError:
            pass
        top.destroy()

    def on_cancel() -> None:
        close_top()

    def _after_find_device_save(lid_written: str, verify_rows: list[dict[str, str]]) -> None:
        if lid_written:
            set_current_location_id(lid_written)
        _apply_persisted_location_to_runtime()
        _refresh_location_selector()
        _verify_added_devices_after_save(verify_rows)

    def _ask_save_device_role() -> str | None:
        choice: list[str | None] = [None]
        dlg = tk.Toplevel(top)
        dlg.title("Device type")
        dlg.configure(bg="#1a1a1e")
        try:
            dlg.transient(top)
            dlg.grab_set()
        except tk.TclError:
            pass
        tk.Label(
            dlg,
            text="What kind of device is this?",
            fg="#eee",
            bg="#1a1a1e",
            font=S_FONT_SMALL,
        ).pack(anchor=tk.W, padx=12, pady=(12, 8))
        row_f = tk.Frame(dlg, bg="#1a1a1e")
        row_f.pack(fill=tk.X, padx=12, pady=(0, 8))
        var = tk.StringVar(value="player")
        for lab, val in (
            ("Player (playback / metadata)", "player"),
            ("Receiver (Denon/Marantz-style IP)", "receiver"),
            ("TV", "tv"),
            ("Projector", "projector"),
            ("Game console", "game"),
            ("Other", "other"),
        ):
            tk.Radiobutton(
                row_f,
                text=lab,
                variable=var,
                value=val,
                bg="#1a1a1e",
                fg="#eee",
                selectcolor="#333",
                activebackground="#1a1a1e",
                highlightthickness=0,
                font=S_FONT_SMALL,
            ).pack(anchor=tk.W)

        def ok() -> None:
            choice[0] = str(var.get() or "").strip() or None
            dlg.destroy()

        def cancel() -> None:
            choice[0] = None
            dlg.destroy()

        br = tk.Frame(dlg, bg="#1a1a1e")
        br.pack(pady=(0, 12))
        tk.Button(br, text="OK", command=ok, font=S_FONT_BTN, padx=14, pady=4).pack(
            side=tk.LEFT, padx=6
        )
        tk.Button(br, text="Cancel", command=cancel, font=S_FONT_BTN, padx=14, pady=4).pack(
            side=tk.LEFT, padx=6
        )
        dlg.wait_window(dlg)
        return choice[0]

    def on_confirm() -> None:
        host = str(host_var.get() or "").strip()

        def _tag_row_device_role(row: dict[str, str], dr: str) -> None:
            row["device_role"] = dr

        base_row: dict[str, str] | None = None
        if not host:
            base_row = list_selection_row()
            if base_row is None:
                messagebox.showwarning(
                    "Find device",
                    "Select a device from the list (wait until search finishes), or enter Host / IP.",
                    parent=top,
                )
                return

        r0 = _ask_save_device_role()
        if not r0:
            return

        nick_raw = simpledialog.askstring(
            "Nickname",
            "Optional nickname for this entry (shown in lists and Advanced):",
            parent=top,
        )
        nick = (nick_raw or "").strip()

        def _merge_nick(row: dict[str, str]) -> dict[str, str]:
            m = dict(row)
            if nick:
                m["nickname"] = nick
            return m

        to_id, new_nm = resolve_save_location()

        if r0 in ("tv", "projector", "game", "other"):
            if host:
                ident = f"{r0}:{host.split('%')[0].strip()}"
                nm = r0.capitalize() if r0 != "other" else "Other"
                row_any = {
                    "identifier": ident,
                    "address": host.strip(),
                    "name": nm,
                    "label": f"{nm} — {host.strip()}",
                    "looks_like_apple_tv": "false",
                }
                _tag_row_device_role(row_any, r0)
            else:
                row_any = _merge_nick(dict(base_row or {}))
                _tag_row_device_role(row_any, r0)
            row_any = _merge_nick(row_any)
            slot_key = {"tv": "tv", "projector": "projector", "game": "game", "other": "other"}[r0]
            lid = append_device_to_location_slot(
                slot_key,
                row_any,
                for_location_id=to_id,
                new_location_name=new_nm,
            )
            _after_find_device_save(lid, [row_any])
            close_top()
            return

        if r0 == "receiver":
            if host:
                row_r = {
                    "identifier": f"denon:{host.split('%')[0].strip()}",
                    "address": host.strip(),
                    "name": "Receiver",
                    "label": f"Receiver \u2014 {host.strip()}",
                    "looks_like_apple_tv": "false",
                }
                _tag_row_device_role(row_r, "receiver")
            else:
                row_r = _merge_nick(dict(base_row or {}))
                _tag_row_device_role(row_r, "receiver")
            row_r = _merge_nick(row_r)
            lid = append_device_to_location_slot(
                "av_receiver",
                row_r,
                for_location_id=to_id,
                new_location_name=new_nm,
            )
            _after_find_device_save(lid, [row_r])
            close_top()
            return

        # Player
        if host:
            close_top()
            if not begin_apple_tv_operation("probing address"):
                return

            def w_probe() -> None:
                try:
                    from pigeon.apple_tv_now_playing import probe_pyatv_host

                    ok_w, msg_w, row_w, looks_w = probe_pyatv_host(host, scan_timeout_s=8)
                except ImportError:
                    ok_w, msg_w, row_w, looks_w = False, _pyatv_install_hint(), None, False
                except Exception as e:
                    ok_w, msg_w, row_w, looks_w = False, str(e), None, False

                def d_probe() -> None:
                    end_apple_tv_operation()
                    if not ok_w or row_w is None:
                        messagebox.showerror("Find device", msg_w)
                        return
                    row_d = _merge_nick(dict(row_w))
                    _tag_row_device_role(row_d, "player")
                    lid = append_device_to_location_slot(
                        "streaming",
                        row_d,
                        for_location_id=to_id,
                        new_location_name=new_nm,
                    )
                    _after_find_device_save(lid, [row_d])
                    if row_is_playback_apple_tv(row_d):
                        _run_sequential_player_pairing_wizard(row_d)

                root.after(0, d_probe)

            threading.Thread(target=w_probe, daemon=True).start()
            return

        row_p = _merge_nick(dict(base_row or {}))
        _tag_row_device_role(row_p, "player")
        lid = append_device_to_location_slot(
            "streaming",
            row_p,
            for_location_id=to_id,
            new_location_name=new_nm,
        )
        _after_find_device_save(lid, [row_p])
        close_top()
        if row_is_playback_apple_tv(row_p):
            _run_sequential_player_pairing_wizard(row_p)

    confirm_btn = tk.Button(btn_row, text="Confirm", command=on_confirm, font=S_FONT_BTN, padx=12, pady=4)
    confirm_holder[0] = confirm_btn
    cancel_btn = tk.Button(btn_row, text="Cancel", command=on_cancel, font=S_FONT_BTN, padx=12, pady=4)
    confirm_btn.pack(side=tk.LEFT, padx=(0, 8))
    cancel_btn.pack(side=tk.LEFT)
    btn_row.pack(side=tk.LEFT, padx=(16, 0))
    top.protocol("WM_DELETE_WINDOW", on_cancel)
    run_scan(force_network=False)


def _finish_remote_then_start_airplay(row: dict[str, str], dn: str, session_key_w: str, pin: str, *, _pyatv_install_hint, _schedule_refresh_pairing_leds, _start_airplay_pairing_sequence, end_apple_tv_operation, root) -> None:
    # Caller still holds apple_tv_busy from "starting AppleTV Remote" — do not poll until Remote is fully done.

    def worker_remote_finish() -> None:
        try:
            from pigeon.apple_tv_now_playing import finish_companion_pairing_for_device

            ok_f, msg_f = finish_companion_pairing_for_device(
                session_key=session_key_w, pin_code=pin
            )
        except ImportError:
            ok_f, msg_f = False, _pyatv_install_hint()
        except Exception as e:
            ok_f, msg_f = False, str(e)
        if ok_f:
            time.sleep(1.5)

        def done_rf() -> None:
            end_apple_tv_operation()
            if not ok_f:
                messagebox.showerror("AppleTV Remote", msg_f)
                _schedule_refresh_pairing_leds()
                return
            messagebox.showinfo(
                "AppleTV Remote",
                f"{msg_f}\n\n"
                "Wait until the Apple TV leaves the Remote pairing screen before continuing.",
            )
            _schedule_refresh_pairing_leds()
            _start_airplay_pairing_sequence(row, dn)

        root.after(0, done_rf)

    threading.Thread(target=worker_remote_finish, daemon=True).start()


def _remove_streaming_device_at(for_location_id: str, index: int, *, _clear_reported_position_stall_stamp, _rebuild_paired_devices_panel, _schedule_refresh_pairing_leds, _sync_status_bar_visibility_for_playback, apple_tv_auto_state, apple_tv_busy, apple_tv_dashboard_track, apple_tv_playback_clock, current_apple_tv, describe_current_apple_tv, playback_overlay_widget, render_once, root, skip_cache, streaming_slot_holder) -> None:
    if apple_tv_busy["active"]:
        describe_current_apple_tv(suffix="busy")
        return
    if not messagebox.askyesno(
        "Remove Player",
        "Remove this Player entry from this location?",
        parent=root,
    ):
        return
    lid = str(for_location_id or "").strip()
    remove_device_at_slot_index("streaming", int(index), for_location_id=lid or None)
    cur = read_current_location_id()
    remaining = read_saved_streaming_devices_all()
    if lid and cur and lid == cur:
        streaming_slot_holder[0] = read_saved_streaming_device()
        if not remaining:
            clear_last_apple_tv()
            current_apple_tv.clear()
            current_apple_tv.update(
                {"identifier": "", "address": "", "name": "", "label": ""}
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
            _sync_status_bar_visibility_for_playback(None)
        if playback_overlay_widget is not None:
            playback_overlay_widget.clear_cache()
    skip_cache[0] = None
    try:
        render_once()
    except Exception:
        pass
    describe_current_apple_tv()
    _rebuild_paired_devices_panel()
    _schedule_refresh_pairing_leds()


def _remove_receiver_device_at(for_location_id: str, index: int, *, _rebuild_paired_devices_panel, _schedule_refresh_pairing_leds, apple_tv_busy, avr_slot_holder, describe_current_apple_tv, playback_overlay_widget, receiver_http_host, render_once, root, skip_cache, denon_vol_cache=None, receiver_overlay_state=None, receiver_standby_holder=None, receiver_debug_holder=None) -> None:
    if apple_tv_busy["active"]:
        describe_current_apple_tv(suffix="busy")
        return
    if not messagebox.askyesno(
        "Remove Receiver",
        "Remove this Receiver entry from this location?",
        parent=root,
    ):
        return
    lid = str(for_location_id or "").strip()
    remove_device_at_slot_index("av_receiver", int(index), for_location_id=lid or None)
    cur = read_current_location_id()
    if lid and cur and lid == cur:
        avr_slot_holder[0] = read_saved_av_receiver()
        if avr_slot_holder[0] is None:
            clear_last_receiver()
            receiver_http_host["host"] = ""
            from pigeon.core.device_control import _release_receiver

            _release_receiver(
                denon_vol_cache=denon_vol_cache,
                receiver_overlay_state=receiver_overlay_state,
                receiver_standby_holder=receiver_standby_holder,
                receiver_debug_holder=receiver_debug_holder,
            )
        else:
            av2 = avr_slot_holder[0]
            adr = str(av2.get("address") or "").strip()
            if adr:
                write_last_receiver(
                    host=adr,
                    name=str(av2.get("name") or "").strip() or None,
                    label=str(av2.get("label") or "").strip() or None,
                    device_id=str(av2.get("identifier") or "").strip() or None,
                )
                receiver_http_host["host"] = adr
        if playback_overlay_widget is not None:
            playback_overlay_widget.clear_cache()
    skip_cache[0] = None
    try:
        render_once()
    except Exception:
        pass
    describe_current_apple_tv()
    _rebuild_paired_devices_panel()
    _schedule_refresh_pairing_leds()


def _remove_aux_slot_device_at(
    for_location_id: str,
    slot_key: str,
    index: int,
    *,
    role_title: str,
    _apply_persisted_location_to_runtime, _rebuild_paired_devices_panel, _schedule_refresh_pairing_leds, apple_tv_busy, describe_current_apple_tv, render_once, root, skip_cache,
) -> None:
    if apple_tv_busy["active"]:
        describe_current_apple_tv(suffix="busy")
        return
    if not messagebox.askyesno(
        f"Remove {role_title}",
        f"Remove this {role_title} entry from this location?",
        parent=root,
    ):
        return
    lid = str(for_location_id or "").strip()
    remove_device_at_slot_index(slot_key, int(index), for_location_id=lid or None)
    _apply_persisted_location_to_runtime()
    describe_current_apple_tv()
    _rebuild_paired_devices_panel()
    _schedule_refresh_pairing_leds()
    skip_cache[0] = None
    try:
        render_once()
    except Exception:
        pass


def _schedule_refresh_pairing_leds(*, _PIGEON_EXT, _content_indicator_ok, _paint_boolean_led, _paint_cred_led_canvas, _paint_pair_led, _pair_led_pending_retry, _refresh_observed_pairing_led_rows, _schedule_refresh_pairing_leds, apple_tv_busy, apple_tv_dashboard_track, main_settings_widget, pair_led_busy, paired_ui_leds, root, streaming_row_led_canvas_holder, streaming_slot_holder) -> None:

    stream_led = streaming_row_led_canvas_holder[0]
    # Extra pyatv scans here during discover/pair overlap the TV; refresh after busy clears instead.
    if apple_tv_busy["active"]:
        return
    if not _PIGEON_EXT:
        if stream_led is not None:
            try:
                _paint_boolean_led(stream_led, False)
            except tk.TclError:
                pass
        _paint_pair_led(0, False)
        _paint_pair_led(1, False)
        _refresh_observed_pairing_led_rows()
        return
    if pair_led_busy["active"]:
        if not _pair_led_pending_retry[0]:
            _pair_led_pending_retry[0] = True

            def _retry_pair_leds() -> None:
                _pair_led_pending_retry[0] = False
                _schedule_refresh_pairing_leds()

            root.after(120, _retry_pair_leds)
        return
    pair_led_busy["active"] = True
    row_snap = streaming_slot_holder[0]

    def work() -> None:
        comp_sel, air_sel = False, False
        both_ok = False
        if row_snap:
            try:
                from pigeon.apple_tv_now_playing import apple_tv_pairing_credentials_status

                c, a = apple_tv_pairing_credentials_status(
                    device_identifier=str(row_snap.get("identifier", "")),
                    device_address=str(row_snap.get("address", "")),
                )
                comp_sel, air_sel = bool(c), bool(a)
                both_ok = comp_sel and air_sel
            except Exception:
                comp_sel, air_sel = False, False

        def apply_leds() -> None:
            pair_led_busy["active"] = False
            lpo = apple_tv_dashboard_track.get("last_poll_ok")
            cf = int(apple_tv_dashboard_track.get("consecutive_fail", 0) or 0)
            poll_unhealthy = lpo is False and cf >= 1

            def _cred_led(has_cred: bool) -> bool | None:
                if not has_cred:
                    return False
                if poll_unhealthy:
                    return None
                return True

            stream_tri: bool | None = False
            if row_snap and comp_sel and air_sel:
                stream_tri = None if poll_unhealthy else True
            elif row_snap and (comp_sel or air_sel):
                stream_tri = False
            if stream_led is not None:
                try:
                    _paint_boolean_led(stream_led, stream_tri)
                except tk.TclError:
                    pass
            _paint_pair_led(0, _cred_led(comp_sel))
            _paint_pair_led(1, _cred_led(air_sel))
            pr = paired_ui_leds.get("remote")
            pa = paired_ui_leds.get("airplay")
            if pr is not None:
                _paint_cred_led_canvas(pr, _cred_led(comp_sel))
            if pa is not None:
                _paint_cred_led_canvas(pa, _cred_led(air_sel))
            _refresh_observed_pairing_led_rows()
            if main_settings_widget is not None:
                try:
                    st_led = main_settings_widget.state
                    if st_led.show_pigeon_settings:
                        from pigeon.source_status import metadata_received_within

                        meta_ok = metadata_received_within()
                        if st_led.pigeon_metadata_ok != meta_ok:
                            st_led.pigeon_metadata_ok = meta_ok
                            main_settings_widget.invalidate()
                except Exception:
                    pass

        root.after(0, apply_leds)

    threading.Thread(target=work, daemon=True).start()
