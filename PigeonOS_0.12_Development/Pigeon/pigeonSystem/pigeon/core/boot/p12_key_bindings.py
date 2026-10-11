"""Boot phase: mouse and keyboard bindings (Tab, Return, Space, view keys, hotkeys, chords).

Phase 12 of ``bootstrap()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from pigeon.core import device_control as _core_device_control
from pigeon.core import input_keys as _core_input_keys
from pigeon.core import settings_ui as _core_settings_ui
from pigeon.core import tmdb_flow as _core_tmdb_flow
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.core.binding import late as _late
import tkinter as tk


def run(ctx) -> None:
    CLOCK_SAVER_PEEK_S = ctx.CLOCK_SAVER_PEEK_S
    DevPhase = ctx.DevPhase
    DisplayView = ctx.DisplayView
    HOTKEY_BINDTAG = ctx.HOTKEY_BINDTAG
    ViewOneLayout = ctx.ViewOneLayout
    _PIGEON_EXT = ctx._PIGEON_EXT
    _bump_pigeon_user_activity = ctx._bump_pigeon_user_activity
    _capture_last_view_one_layout_from_live_view = ctx._capture_last_view_one_layout_from_live_view
    _clock_saver_for_compose = ctx._clock_saver_for_compose
    _current_view_one_variant = ctx._current_view_one_variant
    _handle_main_settings_action = ctx._handle_main_settings_action
    _idle_saver_face_toggle_ok = ctx._idle_saver_face_toggle_ok
    _last_adv_shift_tab_mono = ctx._last_adv_shift_tab_mono
    _last_space_mono = ctx._last_space_mono
    _last_tmdb_match_toggle_mono = ctx._last_tmdb_match_toggle_mono
    _nav_request = ctx._nav_request
    _open_advanced_capability_matrix = ctx._open_advanced_capability_matrix
    _prepend_hotkey_bindtag = ctx._prepend_hotkey_bindtag
    _sync_now_playing_screen_state = ctx._sync_now_playing_screen_state
    _toggle_clock_saver_force = ctx._toggle_clock_saver_force
    _vv_is_music = ctx._vv_is_music
    _widget_accepts_typing = ctx._widget_accepts_typing
    apple_tv_auto_state = ctx.apple_tv_auto_state
    apple_tv_busy = ctx.apple_tv_busy
    apply_saved_tmdb_backdrop_to_display = ctx.apply_saved_tmdb_backdrop_to_display
    clock_saver_composite_bgra = ctx.clock_saver_composite_bgra
    clock_saver_peek_until_mono = ctx.clock_saver_peek_until_mono
    command_bar = ctx.command_bar
    command_entry = ctx.command_entry
    command_entry_visible = ctx.command_entry_visible
    current_apple_tv = ctx.current_apple_tv
    dev_phase = ctx.dev_phase
    display_view_holder = ctx.display_view_holder
    hide_command_entry = ctx.hide_command_entry
    label = ctx.label
    main_settings_widget_holder = ctx.main_settings_widget_holder
    on_click_focus = ctx.on_click_focus
    on_ctrl_tab = ctx.on_ctrl_tab
    on_double_click_scene = ctx.on_double_click_scene
    on_f10_key = ctx.on_f10_key
    on_s_key = ctx.on_s_key
    on_shift_tab_dev_cycle = ctx.on_shift_tab_dev_cycle
    on_tab_key = ctx.on_tab_key
    on_tmdb_quality_error_report_hotkey = ctx.on_tmdb_quality_error_report_hotkey
    on_tmdb_retry_hotkey = ctx.on_tmdb_retry_hotkey
    quit_app = ctx.quit_app
    root = ctx.root
    saved_backdrop_master_bgr = ctx.saved_backdrop_master_bgr
    settings_canvas = ctx.settings_canvas
    settings_footer_row = ctx.settings_footer_row
    settings_frame = ctx.settings_frame
    settings_inner = ctx.settings_inner
    settings_scroll_outer = ctx.settings_scroll_outer
    shell = ctx.shell
    show_command_entry = ctx.show_command_entry
    skip_cache = ctx.skip_cache
    spawn_tmdb_poster_fetch = ctx.spawn_tmdb_poster_fetch
    streaming_slot_holder = ctx.streaming_slot_holder
    submit_command_entry = ctx.submit_command_entry
    sync_developer_chrome = ctx.sync_developer_chrome
    toggle_audio_meter_face = ctx.toggle_audio_meter_face
    toggle_play = ctx.toggle_play
    toggle_scene = ctx.toggle_scene
    try_cycle_dev_phase = ctx.try_cycle_dev_phase
    use_backdrop_scene = ctx.use_backdrop_scene
    variant_has_alternate = ctx.variant_has_alternate
    video_area = ctx.video_area
    view_circles_widget_holder = ctx.view_circles_widget_holder
    view_five_mode_holder = ctx.view_five_mode_holder
    view_four_subview_holder = ctx.view_four_subview_holder
    view_one_layout_holder = ctx.view_one_layout_holder

    for _seq in ("<Return>", "<KeyPress-Return>"):
        command_entry.bind(_seq, submit_command_entry)
    command_entry.bind("<KP_Enter>", submit_command_entry)
    command_entry.bind("<KeyPress-KP_Enter>", submit_command_entry)

    label.bind("<Button-1>", on_click_focus, add="+")
    # Tap-to-wake: some platforms deliver release more reliably for “tap” than press alone.
    # While the saver layer is visible, a tap brightens it briefly (see CLOCK_SAVER_PEEK_S).
    _on_label_button_release_peek_or_bump = _bind_deps(
        _core_input_keys._on_label_button_release_peek_or_bump,
        CLOCK_SAVER_PEEK_S=CLOCK_SAVER_PEEK_S,
        _PIGEON_EXT=_PIGEON_EXT,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _clock_saver_for_compose=_clock_saver_for_compose,
        clock_saver_composite_bgra=clock_saver_composite_bgra,
        clock_saver_peek_until_mono=clock_saver_peek_until_mono,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        skip_cache=skip_cache,
    )

    label.bind("<ButtonRelease-1>", _on_label_button_release_peek_or_bump, add="+")
    label.bind("<Double-Button-1>", on_double_click_scene, add="+")
    label.bind("<Button-3>", lambda e: try_cycle_dev_phase(None))

    # Omit command_entry: it needs local <Return> to submit before bind_all runs.
    for w in (
        root,
        shell,
        video_area,
        label,
        command_bar,
        settings_frame,
        settings_scroll_outer,
        settings_canvas,
        settings_inner,
        settings_footer_row,
    ):
        if w is not None:
            _prepend_hotkey_bindtag(w)

    _TAB_SEQS = (
        "<Tab>",
        "<KeyPress-Tab>",
        "<Key-Tab>",
        "<ISO_Left_Tab>",
        "<KeyPress-ISO_Left_Tab>",
        "<Shift-Tab>",
        "<Shift-KeyPress-Tab>",
        "<Shift-Key-Tab>",
        "<KP_Tab>",
        "<KeyPress-KP_Tab>",
    )
    for seq in _TAB_SEQS:
        root.bind_class(HOTKEY_BINDTAG, seq, on_tab_key)
    root.bind_class(HOTKEY_BINDTAG, "<Control-KeyPress-Tab>", on_ctrl_tab)
    root.bind_class(HOTKEY_BINDTAG, "<Control-Key-Tab>", on_ctrl_tab)
    # X11/Pi: class <Tab> is tk_focusNext and returns break before bind_all.
    for _tab_cls in (
        "Button",
        "Label",
        "Frame",
        "Canvas",
        "Toplevel",
        "Tk",
        "TFrame",
        "TLabel",
        "TButton",
        "TCheckbutton",
        "TRadiobutton",
        "Radiobutton",
        "Checkbutton",
        "Scale",
        "Listbox",
        "Entry",
        "TEntry",
        "Text",
    ):
        for seq in _TAB_SEQS:
            try:
                root.bind_class(_tab_cls, seq, on_tab_key)
            except tk.TclError:
                pass
    root.bind_class(HOTKEY_BINDTAG, "<KeyPress-s>", on_s_key)
    root.bind_class(HOTKEY_BINDTAG, "<KeyPress-S>", on_s_key)

    on_return_overlay_command = _bind_deps(
        _core_tmdb_flow.on_return_overlay_command,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        _PIGEON_EXT=_PIGEON_EXT,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _widget_accepts_typing=_widget_accepts_typing,
        apple_tv_busy=apple_tv_busy,
        command_entry=command_entry,
        command_entry_visible=command_entry_visible,
        current_apple_tv=current_apple_tv,
        dev_phase=dev_phase,
        display_view_holder=display_view_holder,
        show_command_entry=show_command_entry,
        streaming_slot_holder=streaming_slot_holder,
    )

    for seq in _TAB_SEQS:
        root.bind_all(seq, on_tab_key)
    # Do not bind_all(Return): on macOS that can run before the Entry binding and swallow the key.
    for _rseq in ("<Return>", "<KeyPress-Return>", "<KP_Enter>", "<KeyPress-KP_Enter>"):
        root.bind_class(HOTKEY_BINDTAG, _rseq, on_return_overlay_command)

    _send_player_play_pause_hotkey = _bind_deps(
        _core_device_control._send_player_play_pause_hotkey,
        _PIGEON_EXT=_PIGEON_EXT,
        apple_tv_busy=apple_tv_busy,
        current_apple_tv=current_apple_tv,
        streaming_slot_holder=streaming_slot_holder,
    )

    on_space_play = _bind_deps(
        _core_input_keys.on_space_play,
        DevPhase=DevPhase,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _handle_main_settings_action=_handle_main_settings_action,
        _last_space_mono=_last_space_mono,
        _send_player_play_pause_hotkey=_send_player_play_pause_hotkey,
        _widget_accepts_typing=_widget_accepts_typing,
        apply_saved_tmdb_backdrop_to_display=apply_saved_tmdb_backdrop_to_display,
        dev_phase=dev_phase,
        main_settings_widget=main_settings_widget_holder[0],
        render_once=_late(lambda: ctx.render_once, "render_once"),
        saved_backdrop_master_bgr=saved_backdrop_master_bgr,
        skip_cache=skip_cache,
        sync_developer_chrome=sync_developer_chrome,
        toggle_play=toggle_play,
        use_backdrop_scene=use_backdrop_scene,
    )

    # <KeyPress-Space> is invalid on some Tk builds (TclError: bad keysym "Space").
    for _space_seq in ("<space>", "<KeyPress-space>"):
        root.bind_all(_space_seq, on_space_play)

    on_display_view_digit = _bind_deps(
        _core_input_keys.on_display_view_digit,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        ViewOneLayout=ViewOneLayout,
        _PIGEON_EXT=_PIGEON_EXT,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _capture_last_view_one_layout_from_live_view=_capture_last_view_one_layout_from_live_view,
        _current_view_one_variant=_current_view_one_variant,
        _idle_saver_face_toggle_ok=_idle_saver_face_toggle_ok,
        _sync_now_playing_screen_state=_sync_now_playing_screen_state,
        _toggle_clock_saver_force=_toggle_clock_saver_force,
        _vv_is_music=_vv_is_music,
        _widget_accepts_typing=_widget_accepts_typing,
        dev_phase=dev_phase,
        display_view_holder=display_view_holder,
        main_settings_widget=main_settings_widget_holder[0],
        render_once=_late(lambda: ctx.render_once, "render_once"),
        skip_cache=skip_cache,
        sync_developer_chrome=sync_developer_chrome,
        toggle_audio_meter_face=toggle_audio_meter_face,
        variant_has_alternate=variant_has_alternate,
        view_circles_widget=view_circles_widget_holder[0],
        view_five_mode_holder=view_five_mode_holder,
        view_four_subview_holder=view_four_subview_holder,
        view_one_layout_holder=view_one_layout_holder,
    )

    for _dv_ch in ("0", "1", "2", "3", "4", "5", "6", "7", "8"):
        root.bind_all(f"<KeyPress-{_dv_ch}>", on_display_view_digit)

    on_arrow_remote = _bind_deps(
        _core_input_keys.on_arrow_remote,
        DevPhase=DevPhase,
        _PIGEON_EXT=_PIGEON_EXT,
        _nav_request=_nav_request,
        _widget_accepts_typing=_widget_accepts_typing,
        apple_tv_busy=apple_tv_busy,
        current_apple_tv=current_apple_tv,
        dev_phase=dev_phase,
        main_settings_widget=main_settings_widget_holder[0],
        render_once=_late(lambda: ctx.render_once, "render_once"),
        skip_cache=skip_cache,
        streaming_slot_holder=streaming_slot_holder,
        view_circles_widget_holder=view_circles_widget_holder,
    )

    for _ak in ("<KeyPress-Up>", "<KeyPress-Down>", "<KeyPress-Left>", "<KeyPress-Right>"):
        root.bind_all(_ak, on_arrow_remote)

    on_escape = _bind_deps(
        _core_input_keys.on_escape,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        command_entry_visible=command_entry_visible,
        hide_command_entry=hide_command_entry,
        quit_app=quit_app,
    )

    root.bind_all("<Escape>", on_escape)
    root.bind_all("<KeyPress-F9>", lambda e: try_cycle_dev_phase(None))
    root.bind_all("<KeyPress-F10>", on_f10_key)

    on_ctrl_shift_tab_advanced = _bind_deps(
        _core_input_keys.on_ctrl_shift_tab_advanced,
        _PIGEON_EXT=_PIGEON_EXT,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _last_adv_shift_tab_mono=_last_adv_shift_tab_mono,
        _open_advanced_capability_matrix=_open_advanced_capability_matrix,
        _widget_accepts_typing=_widget_accepts_typing,
    )

    for _adv_hot in (
        "<Control-Shift-KeyPress-Tab>",
        "<Control-Shift-Key-Tab>",
        "<Control-Shift-KeyPress-ISO_Left_Tab>",
    ):
        root.bind_all(_adv_hot, on_ctrl_shift_tab_advanced)
    for _stab in (
        "<KeyPress-ISO_Left_Tab>",
        "<Shift-KeyPress-Tab>",
        "<Shift-Key-Tab>",
    ):
        root.bind_all(_stab, on_shift_tab_dev_cycle)
    for _tmdb_key in ("<KeyPress-question>", "<Shift-KeyPress-slash>"):
        root.bind_all(_tmdb_key, on_tmdb_retry_hotkey)
    for _tmdb_qx in (
        "<Command-Shift-KeyPress-x>",
        "<Command-Shift-KeyPress-X>",
        "<Control-Shift-KeyPress-x>",
        "<Control-Shift-KeyPress-X>",
    ):
        root.bind_all(_tmdb_qx, on_tmdb_quality_error_report_hotkey)

    on_tmdb_match_mode_toggle = _bind_deps(
        _core_input_keys.on_tmdb_match_mode_toggle,
        _PIGEON_EXT=_PIGEON_EXT,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _last_tmdb_match_toggle_mono=_last_tmdb_match_toggle_mono,
        _widget_accepts_typing=_widget_accepts_typing,
    )

    on_dev_series_title_training_hotkey = _bind_deps(
        _core_input_keys.on_dev_series_title_training_hotkey,
        DevPhase=DevPhase,
        DisplayView=DisplayView,
        _PIGEON_EXT=_PIGEON_EXT,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _widget_accepts_typing=_widget_accepts_typing,
        apple_tv_auto_state=apple_tv_auto_state,
        dev_phase=dev_phase,
        display_view_holder=display_view_holder,
        root=root,
        spawn_tmdb_poster_fetch=spawn_tmdb_poster_fetch,
    )

    for _plus_key in (
        "<KeyPress-plus>",
        "<Shift-KeyPress-equal>",
        "<Shift-KeyPress-plus>",
        "<KeyPress-KP_Add>",
    ):
        root.bind_all(_plus_key, on_dev_series_title_training_hotkey)

    root.bind_all("<Control-Shift-KeyPress-m>", on_tmdb_match_mode_toggle)
    root.bind_all("<Control-Shift-KeyPress-M>", on_tmdb_match_mode_toggle)

    root.bind_all("<Control-Shift-KeyPress-s>", lambda e: toggle_scene(require_overlay=False))
    root.bind_all("<Control-Shift-KeyPress-S>", lambda e: toggle_scene(require_overlay=False))

    # Pixel-aspect override: hold P+A+R together to toggle auto ↔ off.
    _par_chord_held: set[str] = set()
    _par_chord_fired = [False]

    _on_par_chord_press = _bind_deps(
        _core_input_keys._on_par_chord_press,
        _par_chord_fired=_par_chord_fired,
        _par_chord_held=_par_chord_held,
        _widget_accepts_typing=_widget_accepts_typing,
        render_once=_late(lambda: ctx.render_once, "render_once"),
        skip_cache=skip_cache,
    )

    _on_par_chord_release = _bind_deps(
        _core_input_keys._on_par_chord_release,
        _par_chord_fired=_par_chord_fired,
        _par_chord_held=_par_chord_held,
    )

    for _par_ch in ("p", "a", "r", "P", "A", "R"):
        root.bind_all(f"<KeyPress-{_par_ch}>", _on_par_chord_press, add="+")
        root.bind_all(f"<KeyRelease-{_par_ch}>", _on_par_chord_release, add="+")

    _focus_when_mapped = _bind_deps(_core_input_keys._focus_when_mapped, root=root)

    root.bind("<Map>", _focus_when_mapped)
    root.after_idle(_focus_when_mapped)

    for _pigeon_act in ("<Button-1>", "<B1-Motion>", "<KeyPress>"):
        root.bind_all(_pigeon_act, _bump_pigeon_user_activity, add="+")

    # Serial rotary (non-HID USB): CW/CCW/PUSH → navigate / activate.
    # Prefer a direct callback so settings work even when Tk focus is elsewhere.
    _enter_main_settings_for_rotary = _bind_deps(
        _core_settings_ui._enter_main_settings_for_rotary,
        DevPhase=DevPhase,
        dev_phase=dev_phase,
        main_settings_widget=main_settings_widget_holder[0],
        render_once=_late(lambda: ctx.render_once, "render_once"),
        skip_cache=skip_cache,
        sync_developer_chrome=sync_developer_chrome,
    )

    _on_rotary_action = _bind_deps(
        _core_input_keys._on_rotary_action,
        DevPhase=DevPhase,
        _bump_pigeon_user_activity=_bump_pigeon_user_activity,
        _enter_main_settings_for_rotary=_enter_main_settings_for_rotary,
        _handle_main_settings_action=_handle_main_settings_action,
        _nav_request=_nav_request,
        dev_phase=dev_phase,
        main_settings_widget=main_settings_widget_holder[0],
        render_once=_late(lambda: ctx.render_once, "render_once"),
        root=root,
        skip_cache=skip_cache,
        sync_developer_chrome=sync_developer_chrome,
        view_circles_widget_holder=view_circles_widget_holder,
    )

    ctx._on_rotary_action = _on_rotary_action

    def _on_visualizer_key(event: tk.Event) -> str | None:
        """``v``: same as a long encoder press (HID boards send it for a hold)."""
        if _widget_accepts_typing(event.widget):
            return None
        _on_rotary_action("hold")
        return "break"

    for _vk in ("<KeyPress-v>", "<KeyPress-V>"):
        root.bind_all(_vk, _on_visualizer_key)
    ctx._send_player_play_pause_hotkey = _send_player_play_pause_hotkey
