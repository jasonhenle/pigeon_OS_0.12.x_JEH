"""Main-window phase: clock-saver volume state and helpers, and the splash clock-reveal helpers.

Phase 3 of ``main()`` in ``pigeon_0_12.py``, moved verbatim. ``run``
reads the names it needs from the shared boot context, runs the original
statements, and writes back the names later phases read.
"""

from __future__ import annotations

from pigeon.core import saver_state as _core_saver_state
from pigeon.core import startup as _core_startup
from pigeon.core.binding import bind_deps as _bind_deps


def run(ctx) -> None:
    ClockSaverVolumeHold = ctx.ClockSaverVolumeHold
    DESIGN_H = ctx.DESIGN_H
    DESIGN_W = ctx.DESIGN_W
    UI_TARGET_H = ctx.UI_TARGET_H
    UI_TARGET_W = ctx.UI_TARGET_W
    VolumeLineReveal = ctx.VolumeLineReveal
    WINDOW_H = ctx.WINDOW_H
    WINDOW_W = ctx.WINDOW_W
    _bgr_to_tk_image = ctx._bgr_to_tk_image
    _boot_clock_label = ctx._boot_clock_label
    _boot_clock_photo = ctx._boot_clock_photo
    _post_splash_startup_hook = ctx._post_splash_startup_hook
    _present_frame_to_display = ctx._present_frame_to_display
    _splash_clock_ready_bgr = ctx._splash_clock_ready_bgr
    _splash_on_reveal_paint = ctx._splash_on_reveal_paint
    _splash_post_hook_ran = ctx._splash_post_hook_ran
    _splash_reveal_clock = ctx._splash_reveal_clock
    _splash_underlay_bgr = ctx._splash_underlay_bgr
    _splash_underlay_paint_mono = ctx._splash_underlay_paint_mono
    alpha_blend_bgra_over_bgr = ctx.alpha_blend_bgra_over_bgr
    bootstrap_done = ctx.bootstrap_done
    clock_saver_composite_bgra = ctx.clock_saver_composite_bgra
    render_audio_meter_composite_bgra = ctx.render_audio_meter_composite_bgra

    class _NullClockSaverVolumeHold:
        hold = ""
        pre_mute = ""

        def remember(self, raw, *, source="poll", hold_s=None, now=None):
            return str(raw or "")

        def pick(self, candidates, *, now=None, receiver_off=False):
            if receiver_off:
                self.hold = ""
                return ""
            for raw in candidates:
                s = str(raw or "").strip()
                if s:
                    return s
            return ""

        def is_stale_poll(self, raw, *, now=None):
            return False

        def in_nudge_grace(self, now=None):
            return False

        def display_line(self):
            return str(self.hold or "").strip()

        def clear(self):
            self.hold = ""

    _clock_saver_volume = (
        ClockSaverVolumeHold() if ClockSaverVolumeHold is not None else _NullClockSaverVolumeHold()
    )

    class _NullVolumeLineReveal:
        def note(self, raw, *, now=None):
            return None

        def opacity(self, now=None):
            return 0.0

        def fading(self, now=None):
            return False

    _volume_lines = (
        VolumeLineReveal() if VolumeLineReveal is not None else _NullVolumeLineReveal()
    )

    # Shared with bootstrap() and the pigeon.core helpers. Created here (not inside
    # bootstrap()) so the main()-level volume helpers below can read them too.
    # Track the last usable Denon volume reading so the Apple TV metadata poll (which
    # reports ``volume_percent=0`` when an AV receiver owns the volume line) does not
    # briefly overwrite the authoritative dB value on its own cadence. The receiver
    # poll keeps running on its own schedule; this cache only controls *display*.
    denon_vol_cache: dict[str, object] = {
        "effective": "",
        "mono_usable": 0.0,
        # Last volume string shown on View 1 (survives brief empty polls).
        "np_hold": "",
        "heal_quick_mono": 0.0,
        "heal_sweep_mono": 0.0,
        "bound_host": "",
    }
    # True when the last Denon poll answered but reported OFF/STANDBY — hide all
    # receiver metadata and treat the receiver indicator as inactive.
    receiver_standby_holder: list[bool] = [False]
    receiver_overlay_state: dict[str, str] = {
        "incoming": "",
        "config": "",
        "volume": "",
        "input": "",
    }
    view_circles_widget_holder = [None]

    _note_zone3_volume_takeover = _bind_deps(
        _core_saver_state._note_zone3_volume_takeover,
        view_circles_widget_holder=view_circles_widget_holder,
    )

    _note_volume_graphics = _bind_deps(
        _core_saver_state._note_volume_graphics,
        _clock_saver_volume=_clock_saver_volume,
        _note_zone3_volume_takeover=_note_zone3_volume_takeover,
        _volume_lines=_volume_lines,
    )

    _remember_clock_saver_volume = _bind_deps(
        _core_saver_state._remember_clock_saver_volume,
        _clock_saver_volume=_clock_saver_volume,
    )

    _clock_saver_receiver_off = _bind_deps(
        _core_saver_state._clock_saver_receiver_off,
        receiver_standby_holder=receiver_standby_holder,
    )

    _clock_saver_volume_raw = _bind_deps(
        _core_saver_state._clock_saver_volume_raw,
        _clock_saver_volume=_clock_saver_volume,
        denon_vol_cache=denon_vol_cache,
        receiver_overlay_state=receiver_overlay_state,
        view_circles_widget_holder=view_circles_widget_holder,
    )

    _clock_saver_layers = _bind_deps(
        _core_saver_state._clock_saver_layers,
        _clock_saver_volume_raw=_clock_saver_volume_raw,
        _volume_lines=_volume_lines,
        clock_saver_composite_bgra=clock_saver_composite_bgra,
        render_audio_meter_composite_bgra=render_audio_meter_composite_bgra,
    )

    _rasterize_clock_saver_window_bgr = _bind_deps(
        _core_saver_state._rasterize_clock_saver_window_bgr,
        DESIGN_H=DESIGN_H,
        DESIGN_W=DESIGN_W,
        UI_TARGET_H=UI_TARGET_H,
        UI_TARGET_W=UI_TARGET_W,
        WINDOW_H=WINDOW_H,
        WINDOW_W=WINDOW_W,
        _clock_saver_layers=_clock_saver_layers,
        _present_frame_to_display=_present_frame_to_display,
        alpha_blend_bgra_over_bgr=alpha_blend_bgra_over_bgr,
        clock_saver_composite_bgra=clock_saver_composite_bgra,
    )

    _apply_clock_to_bridge_label = _bind_deps(
        _core_startup._apply_clock_to_bridge_label,
        _bgr_to_tk_image=_bgr_to_tk_image,
        _boot_clock_label=_boot_clock_label,
        _boot_clock_photo=_boot_clock_photo,
    )

    _reveal_clock_under_splash = _bind_deps(
        _core_startup._reveal_clock_under_splash,
        _apply_clock_to_bridge_label=_apply_clock_to_bridge_label,
        _rasterize_clock_saver_window_bgr=_rasterize_clock_saver_window_bgr,
        _splash_clock_ready_bgr=_splash_clock_ready_bgr,
        _splash_on_reveal_paint=_splash_on_reveal_paint,
        _splash_reveal_clock=_splash_reveal_clock,
        _splash_underlay_bgr=_splash_underlay_bgr,
        _splash_underlay_paint_mono=_splash_underlay_paint_mono,
        bootstrap_done=bootstrap_done,
    )

    _finish_post_splash_startup_transition = _bind_deps(
        _core_startup._finish_post_splash_startup_transition,
        _post_splash_startup_hook=_post_splash_startup_hook,
        _splash_post_hook_ran=_splash_post_hook_ran,
    )

    ctx._apply_clock_to_bridge_label = _apply_clock_to_bridge_label
    ctx._clock_saver_layers = _clock_saver_layers
    ctx._clock_saver_receiver_off = _clock_saver_receiver_off
    ctx._clock_saver_volume = _clock_saver_volume
    ctx._clock_saver_volume_raw = _clock_saver_volume_raw
    ctx._finish_post_splash_startup_transition = _finish_post_splash_startup_transition
    ctx._note_volume_graphics = _note_volume_graphics
    ctx._note_zone3_volume_takeover = _note_zone3_volume_takeover
    ctx._rasterize_clock_saver_window_bgr = _rasterize_clock_saver_window_bgr
    ctx._remember_clock_saver_volume = _remember_clock_saver_volume
    ctx._reveal_clock_under_splash = _reveal_clock_under_splash
    ctx._volume_lines = _volume_lines
    ctx.denon_vol_cache = denon_vol_cache
    ctx.receiver_overlay_state = receiver_overlay_state
    ctx.receiver_standby_holder = receiver_standby_holder
    ctx.view_circles_widget_holder = view_circles_widget_holder
