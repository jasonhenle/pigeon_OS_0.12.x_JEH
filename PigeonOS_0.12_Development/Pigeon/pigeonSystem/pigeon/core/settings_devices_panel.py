"""
Paired-devices panel helpers for the settings screen.

Device / receiver row parsing and matching, pairing LED painting, the paired-devices
panel rebuild, the pairing PIN modal and the observed-pairing LED refresh. Same contract
as the rest of ``settings_ui``: each function takes the app state it needs as
keyword-only arguments and ``bootstrap()`` binds them with ``bind_deps``.

``pigeon.core.settings_ui`` re-exports every name here, so the boot phases that look the
functions up on ``settings_ui`` are unchanged.
"""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.messagebox as messagebox

from pigeon.app_state import read_all_locations_v2
from pigeon.app_state import read_app_state
from pigeon.app_state import read_current_location_id
from pigeon.app_state import row_is_playback_apple_tv


def _paint_pair_led(which: int, ok: bool | None, *, pairing_led_holder) -> None:
    """Pairing LED: green=detected+compatible, amber=detected+unknown/incompatible, red=not detected/not compatible."""
    canvas = pairing_led_holder[which] if 0 <= which < len(pairing_led_holder) else None
    if canvas is None:
        return
    try:
        canvas.delete("all")
        if ok is True:
            fill = "#1fcb5d"
        elif ok is None:
            fill = "#f0ad4e"
        else:
            fill = "#e74c3c"
        canvas.create_oval(2, 2, 12, 12, fill=fill, outline="#151518", width=1)
    except tk.TclError:
        pass


def _paint_cred_led_canvas(canvas: tk.Canvas | None, ok: bool | None) -> None:
    """Canvas LED: green=detected+compatible, amber=detected+unknown/incompatible, red=not detected/not compatible."""
    if canvas is None:
        return
    try:
        canvas.delete("all")
        if ok is True:
            fill = "#1fcb5d"
        elif ok is None:
            fill = "#f0ad4e"
        else:
            fill = "#e74c3c"
        canvas.create_oval(2, 2, 12, 12, fill=fill, outline="#151518", width=1)
    except tk.TclError:
        pass


def _paired_box_close_button(parent: tk.Frame, bg: str, command: object, *, _S, _kiosk_on) -> tk.Button:
    return tk.Button(
        parent,
        text="\u00d7",
        command=command,
        font=(_S, 14, "normal"),
        fg="#888",
        bg=bg,
        activebackground=bg,
        activeforeground="#f0f0f0",
        bd=0,
        padx=6,
        pady=0,
        highlightthickness=0,
        cursor="none" if _kiosk_on else "hand2",
    )


def _settings_parse_device_rows(raw: object) -> list[dict[str, str]]:
    """Normalize a location slot (list or legacy dict) to filled device rows."""
    if isinstance(raw, list):
        out: list[dict[str, str]] = []
        for x in raw:
            if not isinstance(x, dict):
                continue
            if str(x.get("identifier") or "").strip() and str(x.get("address") or "").strip():
                out.append(dict(x))
        return out
    if isinstance(raw, dict):
        d = dict(raw)
        if str(d.get("identifier") or "").strip() and str(d.get("address") or "").strip():
            return [d]
    return []


def _settings_parse_receiver_rows(raw: object) -> list[dict[str, str]]:
    """Receivers: show any row with a host/IP (identifier optional for legacy)."""
    if isinstance(raw, list):
        return [
            dict(x)
            for x in raw
            if isinstance(x, dict) and str(x.get("address") or "").strip()
        ]
    if isinstance(raw, dict) and str(raw.get("address") or "").strip():
        return [dict(raw)]
    return []


def _refresh_observed_pairing_led_rows(*, _paint_cred_led_canvas, paired_observed_led_last_state, paired_observed_led_rows) -> None:
    if not paired_observed_led_rows:
        return
    try:
        from device_capability_matrix import device_row_stable_key
    except Exception:
        for cv, _lid, _row in paired_observed_led_rows:
            try:
                _paint_cred_led_canvas(cv, False)
            except tk.TclError:
                pass
        return
    try:
        app_state = read_app_state()
    except Exception:
        app_state = {}
    observed_store_by_loc: dict[str, dict[str, object]] = {}
    for cv, lid, row in paired_observed_led_rows:
        try:
            tri_state: bool | None = False
            lid_s = str(lid or "").strip()
            if lid_s:
                if lid_s not in observed_store_by_loc:
                    raw_blob = app_state.get(f"observed_capability_live_v1.{lid_s}")
                    observed_store_by_loc[lid_s] = raw_blob if isinstance(raw_blob, dict) else {}
                blob = observed_store_by_loc.get(lid_s, {})
                sk = str(device_row_stable_key(row) or "").strip()
                if sk:
                    feats = blob.get(sk) if isinstance(blob, dict) else None
                    if isinstance(feats, dict) and feats:
                        has_full = any(
                            isinstance(v, str) and v == "full" for v in feats.values()
                        )
                        tri_state = True if has_full else None
            k = id(cv)
            if paired_observed_led_last_state.get(k, "__missing__") == tri_state:
                continue
            _paint_cred_led_canvas(cv, tri_state)
            paired_observed_led_last_state[k] = tri_state
        except tk.TclError:
            pass


def _device_addr_key(addr: str) -> str:
    s = str(addr or "").strip().lower()
    if not s:
        return ""
    if s.startswith("["):
        return s
    if s.count(":") == 1:
        left, right = s.rsplit(":", 1)
        if right.isdigit():
            return left
    return s.split("%")[0]


def _device_row_matches_saved(row: dict[str, str], saved: dict[str, str], *, _device_addr_key) -> bool:
    ri = str(row.get("identifier") or "").strip()
    si = str(saved.get("identifier") or "").strip()
    if ri and si and ri == si:
        return True
    ra = _device_addr_key(str(row.get("address") or ""))
    sa = _device_addr_key(str(saved.get("address") or ""))
    return bool(ra and sa and ra == sa)


def _save_box_pair_device_row(box_num: int, row: dict[str, str], *, _rebuild_paired_devices_panel, avr_slot_holder, describe_current_apple_tv, receiver_http_host, streaming_slot_holder) -> None:
    from pigeon.app_state import (
        append_device_to_location_slot,
        read_current_location_id,
        read_saved_av_receiver,
        read_saved_streaming_device,
        write_saved_av_receiver,
        write_saved_streaming_device,
    )

    saved = dict(row)
    saved["device_role"] = "player" if box_num == 2 else "receiver"
    lid = read_current_location_id() or None
    if box_num == 2:
        append_device_to_location_slot(
            "streaming",
            saved,
            for_location_id=lid,
            new_location_name=None,
        )
        write_saved_streaming_device(saved, for_location_id=lid)
        streaming_slot_holder[0] = read_saved_streaming_device()
    else:
        write_saved_av_receiver(saved, for_location_id=lid)
        avr_slot_holder[0] = read_saved_av_receiver()
        adr = str((avr_slot_holder[0] or saved).get("address") or "").strip()
        if adr:
            receiver_http_host["host"] = adr
    describe_current_apple_tv()
    _rebuild_paired_devices_panel()


def _rebuild_paired_devices_panel(*, S_FONT_CAP_BOLD, S_FONT_SEC, S_FONT_SMALL, _paint_boolean_led, _paint_cred_led_canvas, _paired_box_close_button, _remove_aux_slot_device_at, _remove_receiver_device_at, _remove_streaming_device_at, _settings_parse_device_rows, _settings_parse_receiver_rows, paired_devices_inner, paired_observed_led_last_state, paired_observed_led_rows, paired_ui_leds, receiver_panel_led_holder) -> None:
    paired_ui_leds["remote"] = None
    paired_ui_leds["airplay"] = None
    paired_ui_leds["receiver"] = None
    paired_observed_led_rows.clear()
    paired_observed_led_last_state.clear()
    receiver_panel_led_holder[0] = None
    for ch in list(paired_devices_inner.winfo_children()):
        try:
            ch.destroy()
        except tk.TclError:
            pass
    locs = read_all_locations_v2()
    cur_id = read_current_location_id()
    if not locs:
        tk.Label(
            paired_devices_inner,
            text="No locations yet — use Find device to add a Player and pick a room.",
            fg="#555",
            bg="#111",
            font=S_FONT_SMALL,
        ).pack(anchor=tk.W)
        return

    tk.Label(
        paired_devices_inner,
        text="Locations & saved devices",
        fg="#aaa",
        bg="#111",
        font=S_FONT_SEC,
    ).pack(anchor=tk.W, pady=(0, 4))

    # Per location: every saved role row is listed (same IP can appear as Player and TV, etc.).
    visible_locs: list[
        tuple[str, str, bool, dict[str, list[dict[str, str]]]]
    ] = []
    for loc in locs:
        loc_id = str(loc.get("id") or "")
        loc_name = str(loc.get("name") or "Room").strip()
        is_cur = bool(cur_id and loc_id == cur_id)
        slots: dict[str, list[dict[str, str]]] = {
            "streaming": _settings_parse_device_rows(loc.get("streaming")),
            "av_receiver": _settings_parse_receiver_rows(loc.get("av_receiver")),
            "tv": _settings_parse_device_rows(loc.get("tv")),
            "projector": _settings_parse_device_rows(loc.get("projector")),
            "game": _settings_parse_device_rows(loc.get("game")),
            "other": _settings_parse_device_rows(loc.get("other")),
        }
        if not any(slots.values()):
            continue
        visible_locs.append((loc_id, loc_name, is_cur, slots))

    if not visible_locs:
        tk.Label(
            paired_devices_inner,
            text="No devices saved in any location yet — use Find device.",
            fg="#555",
            bg="#111",
            font=S_FONT_SMALL,
        ).pack(anchor=tk.W)
        return

    loc_grid = tk.Frame(paired_devices_inner, bg="#111")
    loc_grid.pack(fill=tk.BOTH, expand=True)
    loc_grid.columnconfigure(0, weight=1, uniform="locpair")
    loc_grid.columnconfigure(1, weight=1, uniform="locpair")

    _aux_role_rows_ui: tuple[tuple[str, str, str, str, str], ...] = (
        ("tv", "TV", "#1a2520", "#3a5c4a", "#8fd4a8"),
        ("projector", "Projector", "#25201a", "#5c543a", "#d4c48f"),
        ("game", "Game", "#1a1f28", "#3a445c", "#9ab8ff"),
        ("other", "Other", "#222228", "#444454", "#c0c0d0"),
    )

    for idx, (loc_id, loc_name, is_cur, slots) in enumerate(visible_locs):
        stream_rows = slots["streaming"]
        av_rows = slots["av_receiver"]
        row, col = divmod(idx, 2)
        padx_g = (0, 5) if col == 0 else (5, 0)
        outer_bd = "#4a6a8a" if is_cur else "#3a3a44"
        outer = tk.Frame(
            loc_grid,
            bg="#15151c",
            highlightthickness=1,
            highlightbackground=outer_bd,
        )
        outer.grid(row=row, column=col, sticky="ew", padx=padx_g, pady=(0, 10))
        head_loc = tk.Frame(outer, bg="#15151c")
        head_loc.pack(fill=tk.X, padx=8, pady=(6, 4))
        sub = f"{loc_name}  (active)" if is_cur else loc_name
        tk.Label(
            head_loc,
            text=sub,
            fg="#8ec8ff" if is_cur else "#aaa",
            bg="#15151c",
            font=S_FONT_CAP_BOLD,
        ).pack(side=tk.LEFT)

        inner = tk.Frame(outer, bg="#15151c")
        inner.pack(fill=tk.X, padx=6, pady=(0, 6))

        for si, st in enumerate(stream_rows):
            nick = str(st.get("nickname") or "").strip()
            nm = nick or str(st.get("label") or st.get("name") or "Device").strip()
            ip = str(st.get("address") or "").strip()
            slot_tag = f" #{si + 1}" if len(stream_rows) > 1 else ""
            use_live = bool(is_cur and si == 0)
            if row_is_playback_apple_tv(st):
                grp = tk.Frame(
                    inner,
                    bg="#1a1a24",
                    highlightthickness=1,
                    highlightbackground="#333",
                )
                grp.pack(fill=tk.X, pady=(0, 6))

                def _player_row(
                    parent: tk.Frame,
                    led_key: str,
                    subtitle: str,
                    *,
                    use_live_leds: bool,
                    grp_bg: str,
                    ip_s: str,
                ) -> None:
                    line = tk.Frame(parent, bg=grp_bg)
                    line.pack(fill=tk.X, padx=8, pady=(2, 2))
                    cv = tk.Canvas(line, width=14, height=18, bg=grp_bg, highlightthickness=0, bd=0)
                    cv.pack(side=tk.LEFT)
                    # Never leave this blank while waiting for the first live poll.
                    _paint_cred_led_canvas(cv, False)
                    if use_live_leds:
                        paired_ui_leds[led_key] = cv
                    tk.Label(
                        line,
                        text=f"{subtitle}  ·  {ip_s}",
                        fg="#bbb",
                        bg=grp_bg,
                        font=S_FONT_SMALL,
                    ).pack(side=tk.LEFT, padx=(6, 0))

                head = tk.Frame(grp, bg="#1a1a24")
                head.pack(fill=tk.X, padx=8, pady=(6, 2))
                _paired_box_close_button(
                    head,
                    "#1a1a24",
                    lambda lid=loc_id, ix=si: _remove_streaming_device_at(lid, ix),
                ).pack(side=tk.RIGHT, padx=(8, 0))
                tk.Label(head, text="Player", fg="#7eb8ff", bg="#1a1a24", font=S_FONT_CAP_BOLD).pack(
                    side=tk.LEFT
                )
                tk.Label(head, text=f"{slot_tag}  {nm}", fg="#ccc", bg="#1a1a24", font=S_FONT_SMALL).pack(
                    side=tk.LEFT
                )
                _player_row(
                    grp,
                    "remote",
                    "AppleTV Remote",
                    use_live_leds=use_live,
                    grp_bg="#1a1a24",
                    ip_s=ip,
                )
                _player_row(
                    grp,
                    "airplay",
                    "AppleTV AirPlay",
                    use_live_leds=use_live,
                    grp_bg="#1a1a24",
                    ip_s=ip,
                )
            else:
                grp_o = tk.Frame(
                    inner,
                    bg="#1c1c20",
                    highlightthickness=1,
                    highlightbackground="#3a3a44",
                )
                grp_o.pack(fill=tk.X, pady=(0, 6))
                head_o = tk.Frame(grp_o, bg="#1c1c20")
                head_o.pack(fill=tk.X, padx=8, pady=(6, 6))
                _paired_box_close_button(
                    head_o,
                    "#1c1c20",
                    lambda lid=loc_id, ix=si: _remove_streaming_device_at(lid, ix),
                ).pack(side=tk.RIGHT, padx=(8, 0))
                tk.Label(head_o, text="Player", fg="#7eb8ff", bg="#1c1c20", font=S_FONT_CAP_BOLD).pack(
                    side=tk.LEFT
                )
                line_o = tk.Frame(grp_o, bg="#1c1c20")
                line_o.pack(fill=tk.X, padx=8, pady=(2, 6))
                cv_o = tk.Canvas(line_o, width=14, height=18, bg="#1c1c20", highlightthickness=0, bd=0)
                cv_o.pack(side=tk.LEFT)
                _paint_cred_led_canvas(cv_o, False)
                if is_cur:
                    paired_observed_led_rows.append((cv_o, str(loc_id), dict(st)))
                tk.Label(
                    line_o,
                    text=f"{slot_tag}  {nm}  ·  {ip}",
                    fg="#aaa",
                    bg="#1c1c20",
                    font=S_FONT_SMALL,
                ).pack(side=tk.LEFT, padx=(6, 0))
        for ai, av in enumerate(av_rows):
            grp_r = tk.Frame(
                inner,
                bg="#221a22",
                highlightthickness=1,
                highlightbackground="#5a3d5a",
            )
            grp_r.pack(fill=tk.X, pady=(0, 2))
            head_r = tk.Frame(grp_r, bg="#221a22")
            head_r.pack(fill=tk.X, padx=8, pady=(6, 2))
            _paired_box_close_button(
                head_r,
                "#221a22",
                lambda lid=loc_id, ix=ai: _remove_receiver_device_at(lid, ix),
            ).pack(side=tk.RIGHT, padx=(8, 0))
            tk.Label(head_r, text="Receiver", fg="#c9a0ff", bg="#221a22", font=S_FONT_CAP_BOLD).pack(
                side=tk.LEFT
            )
            rnick = str(av.get("nickname") or "").strip()
            an = rnick or str(av.get("label") or av.get("name") or "Receiver").strip()
            aip = str(av.get("address") or "").strip()
            rtag = f" #{ai + 1}" if len(av_rows) > 1 else ""
            line = tk.Frame(grp_r, bg="#221a22")
            line.pack(fill=tk.X, padx=8, pady=(2, 6))
            cv_r = tk.Canvas(line, width=14, height=18, bg="#221a22", highlightthickness=0, bd=0)
            cv_r.pack(side=tk.LEFT)
            if is_cur and ai == 0:
                paired_ui_leds["receiver"] = cv_r
                receiver_panel_led_holder[0] = cv_r
                _paint_boolean_led(cv_r, False)
            else:
                _paint_cred_led_canvas(cv_r, False)
            tk.Label(
                line,
                text=f"{rtag}  {an}  ·  {aip}",
                fg="#bbb",
                bg="#221a22",
                font=S_FONT_SMALL,
            ).pack(side=tk.LEFT, padx=(6, 0))

        for slot_key, role_title, bg_c, bd_c, title_c in _aux_role_rows_ui:
            aux_rows = slots.get(slot_key) or []
            for ri, arow in enumerate(aux_rows):
                nick_a = str(arow.get("nickname") or "").strip()
                nm_a = nick_a or str(arow.get("label") or arow.get("name") or role_title).strip()
                ip_a = str(arow.get("address") or "").strip()
                tag_a = f" #{ri + 1}" if len(aux_rows) > 1 else ""
                grp_a = tk.Frame(
                    inner,
                    bg=bg_c,
                    highlightthickness=1,
                    highlightbackground=bd_c,
                )
                grp_a.pack(fill=tk.X, pady=(0, 4))
                head_a = tk.Frame(grp_a, bg=bg_c)
                head_a.pack(fill=tk.X, padx=8, pady=(6, 6))
                _paired_box_close_button(
                    head_a,
                    bg_c,
                    lambda lid=loc_id, sk=slot_key, ix=ri, rt=role_title: _remove_aux_slot_device_at(
                        lid, sk, ix, role_title=rt
                    ),
                ).pack(side=tk.RIGHT, padx=(8, 0))
                tk.Label(
                    head_a,
                    text=role_title,
                    fg=title_c,
                    bg=bg_c,
                    font=S_FONT_CAP_BOLD,
                ).pack(side=tk.LEFT)
                line_a = tk.Frame(grp_a, bg=bg_c)
                line_a.pack(fill=tk.X, padx=8, pady=(2, 6))
                cv_a = tk.Canvas(line_a, width=14, height=18, bg=bg_c, highlightthickness=0, bd=0)
                cv_a.pack(side=tk.LEFT)
                _paint_cred_led_canvas(cv_a, False)
                if is_cur:
                    paired_observed_led_rows.append((cv_a, str(loc_id), dict(arow)))
                tk.Label(
                    line_a,
                    text=f"{tag_a}  {nm_a}  ·  {ip_a}",
                    fg="#ccc",
                    bg=bg_c,
                    font=S_FONT_SMALL,
                ).pack(side=tk.LEFT, padx=(6, 0))


def _ask_pairing_pin_modal(
    parent: tk.Misc,
    *,
    title: str,
    device_name: str,
    pair_kind: str,
    session_key: str | None,
    S_FONT_BODY, S_FONT_BTN, root,
) -> str | None:
    out: list[str | None] = [None]
    closed = [False]
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg="#1a1a1e")
    try:
        dlg.transient(root)
        dlg.grab_set()
    except tk.TclError:
        pass
    tk.Label(
        dlg,
        text=f"{pair_kind}\nDevice: {device_name}\nEnter the 4-digit code shown on the television.",
        fg="#ddd",
        bg="#1a1a1e",
        font=S_FONT_BODY,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, padx=14, pady=(12, 8))
    pin_var = tk.StringVar(value="")

    def _close() -> None:
        if closed[0]:
            return
        closed[0] = True
        try:
            dlg.grab_release()
        except tk.TclError:
            pass
        dlg.destroy()

    ent = tk.Entry(
        dlg,
        textvariable=pin_var,
        width=12,
        font=("Menlo", 18) if sys.platform == "darwin" else ("Consolas", 18),
        justify=tk.CENTER,
        bg="#252528",
        fg="#e8e8e8",
        insertbackground="#e8e8e8",
    )
    ent.pack(padx=14, pady=(0, 8))

    def on_pin_write(*_args: object) -> None:
        raw = pin_var.get()
        d = "".join(c for c in raw if c.isdigit())[:4]
        if raw != d:
            pin_var.set(d)
            return
        if len(d) == 4 and not closed[0]:
            out[0] = d
            _close()

    pin_var.trace_add("write", on_pin_write)

    def append_digit(ch: str) -> None:
        cur = "".join(c for c in pin_var.get() if c.isdigit())
        if len(cur) < 4:
            pin_var.set(cur + ch)

    def backspace() -> None:
        cur = "".join(c for c in pin_var.get() if c.isdigit())
        pin_var.set(cur[:-1])

    pad = tk.Frame(dlg, bg="#1a1a1e")
    pad.pack(padx=10, pady=(0, 10))
    for keys in (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9")):
        rf = tk.Frame(pad, bg="#1a1a1e")
        rf.pack()
        for d in keys:
            tk.Button(
                rf,
                text=d,
                width=4,
                command=lambda x=d: append_digit(x),
                font=S_FONT_BTN,
            ).pack(side=tk.LEFT, padx=4, pady=4)
    rowz = tk.Frame(pad, bg="#1a1a1e")
    rowz.pack()
    tk.Button(rowz, text="\u232b", width=4, command=backspace, font=S_FONT_BTN).pack(
        side=tk.LEFT, padx=4, pady=4
    )
    tk.Button(rowz, text="0", width=4, command=lambda: append_digit("0"), font=S_FONT_BTN).pack(
        side=tk.LEFT, padx=4, pady=4
    )

    bf = tk.Frame(dlg, bg="#1a1a1e")
    bf.pack(pady=(0, 14))

    def on_ok() -> None:
        d = "".join(c for c in pin_var.get() if c.isdigit())
        if len(d) != 4:
            messagebox.showwarning("Pairing", "Enter the 4-digit code from the TV.", parent=dlg)
            return
        out[0] = d
        _close()

    def on_cancel() -> None:
        if session_key:
            try:
                from pigeon.apple_tv_now_playing import abandon_pairing_session

                abandon_pairing_session(session_key)
            except Exception:
                pass
        out[0] = None
        _close()

    tk.Button(bf, text="OK", command=on_ok, font=S_FONT_BTN, padx=12, pady=4).pack(
        side=tk.LEFT, padx=8
    )
    tk.Button(bf, text="Cancel", command=on_cancel, font=S_FONT_BTN, padx=12, pady=4).pack(
        side=tk.LEFT, padx=8
    )
    dlg.protocol("WM_DELETE_WINDOW", on_cancel)
    ent.focus_set()
    dlg.wait_window()
    return out[0]


def _settings_audio_led_listen(*, main_settings_widget_holder) -> bool:
    """Keep ALSA open on settings_pigeon so the audio LED can follow signal."""
    if main_settings_widget_holder[0] is None:
        return False
    try:
        st = main_settings_widget_holder[0].state
    except Exception:
        return False
    if not bool(getattr(st, "show_pigeon_settings", False)):
        return False
    if bool(getattr(st, "show_preferences", False)):
        return False
    if bool(getattr(st, "show_metadata_debug", False)):
        return False
    return True
