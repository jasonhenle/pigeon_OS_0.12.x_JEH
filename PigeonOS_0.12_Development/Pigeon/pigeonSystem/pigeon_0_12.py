import os
import sys
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

# Tk must initialize before OpenCV on macOS: cv2 pulls X11/SDL dylibs that otherwise break Tcl (Tcl_InitNotifier → abort).
import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox as messagebox
import tkinter.scrolledtext as scrolledtext
import tkinter.simpledialog as simpledialog

import numpy as np
from PIL import Image, ImageTk
import cv2

from pigeon.core import photo_upload as _photo_upload

# Status bar: one black pill cols 3–17, bar-shaped mask hole + translucent bar; rows 6–8 gradient.
# Remaining label spans cols 16–17 (was 17–18) so the right edge has one extra column of margin.
TRT_DISPLAY_ROW = 8.0  # nowPlaying band bottom aligns to row 9 (baseline of canvas)
TRT_PLAYED_COL = 3  # TRTPlayed (elapsed)
TRT_PLAYED_TEXT = "0"
TRT_REMAINING_COL = 16  # TRTRemaining (countdown); 2-wide → ends at col 17 (col 19 = breathing room)
TRT_REMAINING_TEXT = "1:00:00"
TRT_LABEL_SPAN_W = 2
TRT_LABEL_SPAN_H = 1
# Apple TV auto-poll; TRT labels on a steady ~1 Hz metronome (see _playback_ui_tick).
APPLE_TV_POLL_MS = 3000
APPLE_TV_IDLE_POLL_MS = 6000
APPLE_TV_FAIL_POLL_MAX_MS = 15000
RECEIVER_POLL_MS = 750
RECEIVER_VOLUME_POLL_MS = 500
PLAYBACK_UI_TICK_MS = 1000  # fallback first delay only; actual spacing uses monotonic deadlines
# Title / TMDb logo (views 1/3/5; not view 2 visualizer): 5×2 top-right at grid (1.5, 13); top-aligned in cell.
TMDB_LOGO_ANCHOR_ROW = 1.5
TMDB_LOGO_TOP_RIGHT_COL = 13.0
TMDB_LOGO_SPAN_W = 5
TMDB_LOGO_SPAN_H = 2
TMDB_LOGO_FIT_SCALE = 0.88
# View 6 logo constraints: grow as large as possible while staying inside rows 2..5 and cols 2..18.
TMDB_LOGO_VIEW6_ANCHOR_ROW = 2
TMDB_LOGO_VIEW6_ANCHOR_COL = 2
TMDB_LOGO_VIEW6_SPAN_W = 17
TMDB_LOGO_VIEW6_SPAN_H = 4
TMDB_LOGO_VIEW6_FIT_SCALE = 1.0
VIEW_ONE_BADGE_COL_RIGHT = 4.0  # 2-wide badge left-aligns to grid column 2
VIEW_ONE_CLOCK_COL_RIGHT = 19.0  # clock right edge aligns to the right side of column 18
_CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

_PROJECT_DIR = _CODE_DIR
if not os.path.isdir(os.path.join(_PROJECT_DIR, "pigeonAssets")):
    _parent = os.path.dirname(_PROJECT_DIR)
    if os.path.isdir(os.path.join(_parent, "pigeonAssets")):
        _PROJECT_DIR = _parent

from pigeon.app_state import read_app_state, write_app_state
from pigeon.compositing import cv_resize_interp
from pigeon.stage_background import get_stage_bgr
from pigeon.core.binding import bind_deps as _bind_deps
from pigeon.core.binding import late as _late
from pigeon.core.boot.context import BootContext as _BootContext
from pigeon.core.boot import m01_window as _boot_m01_window
from pigeon.core.boot import m02_shell as _boot_m02_shell
from pigeon.core.boot import m03_volume_and_reveal as _boot_m03_volume_and_reveal
from pigeon.core.boot import m04_splash as _boot_m04_splash
from pigeon.core.boot import p01_state as _boot_p01_state
from pigeon.core.boot import p02_video_surface as _boot_p02_video_surface
from pigeon.core.boot import p03_settings_scaffold as _boot_p03_settings_scaffold
from pigeon.core.boot import p04_settings_location as _boot_p04_settings_location
from pigeon.core.boot import p05_devices_panel as _boot_p05_devices_panel
from pigeon.core.boot import p06_render_state as _boot_p06_render_state
from pigeon.core.boot import p07_widgets as _boot_p07_widgets
from pigeon.core.boot import p08_render_pipeline as _boot_p08_render_pipeline
from pigeon.core.boot import p09_command_tmdb as _boot_p09_command_tmdb
from pigeon.core.boot import p10_devices_logic as _boot_p10_devices_logic
from pigeon.core.boot import p11_settings_footer as _boot_p11_settings_footer
from pigeon.core.boot import p12_key_bindings as _boot_p12_key_bindings
from pigeon.core.boot import p13_hardware_inputs as _boot_p13_hardware_inputs
from pigeon.core.boot import p14_first_render as _boot_p14_first_render
from pigeon.core import splash as _core_splash

try:
    from pigeon.tmdb_retry_log import append_entry as _tmdb_retry_log_append
    from pigeon.tmdb_retry_log import read_tail_lines as _tmdb_retry_log_read_tail
except ImportError:

    def _tmdb_retry_log_append(_entry: dict) -> None:
        pass

    def _tmdb_retry_log_read_tail(_max_lines: int = 120) -> list[str]:
        return []


def _log_optional_import_failure(group: str, exc: BaseException) -> None:
    """Report which optional UI group failed without silencing the root cause."""
    import traceback

    name = getattr(exc, "name", None) or ""
    detail = f"{type(exc).__name__}: {exc}"
    if name:
        detail = f"{detail} (module={name})"
    msg = f"pigeon: optional import group {group!r} disabled — {detail}"
    try:
        sys.stderr.write(msg + "\n")
        sys.stderr.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        sys.stderr.flush()
    except Exception:
        pass
    try:
        from pigeon.pi_diagnostics import append_pigeon_log

        append_pigeon_log(msg)
    except Exception:
        pass


# Optional UI extension groups. A failure disables only that group.
_PIGEON_EXT = False
alpha_blend_bgra_over_bgr = None  # type: ignore[misc, assignment]
lerp_bgr_red_monochrome = None  # type: ignore[misc, assignment]
scale_bgra_rgb = None  # type: ignore[misc, assignment]
scale_height_and_center_crop = None  # type: ignore[misc, assignment]
scale_cover_center_crop = None  # type: ignore[misc, assignment]
scale_uniform_letterbox = None  # type: ignore[misc, assignment]
rect_for_span_at_cell = None  # type: ignore[misc, assignment]
rect_for_span_top_right_at_cell = None  # type: ignore[misc, assignment]
get_grid_geometry = None  # type: ignore[misc, assignment]
playback_lower_gradient_bgra = None  # type: ignore[misc, assignment]
DESIGN_W = DESIGN_H = 0
blend_overlay_bgr = None  # type: ignore[misc, assignment]
build_stage_overlay_source_bgra = None  # type: ignore[misc, assignment]
ClockCalendarWidget = None  # type: ignore[misc, assignment]
CLOCK_ANCHOR_ROW = 1.0
CLOCK_ANCHOR_COL = int(VIEW_ONE_CLOCK_COL_RIGHT)
LOCATION_TOAST_FULL_S = 15.0
LOCATION_TOAST_FADE_S = 2.0
location_toast_patch_bgra = None  # type: ignore[misc, assignment]
TmdbLogoWidget = None  # type: ignore[misc, assignment]
ViewOneVariant = None  # type: ignore[misc, assignment]
resolve_view_one_variant = None  # type: ignore[misc, assignment]
variant_has_alternate = None  # type: ignore[misc, assignment]
variant_uses_full_path = None  # type: ignore[misc, assignment]
render_ui_text_patch_bgra = None  # type: ignore[misc, assignment]
render_view_one_video_content_b_title_patch_bgra = None  # type: ignore[misc, assignment]
render_ui_music_text_patch_bgra = None  # type: ignore[misc, assignment]
load_pigeon_temp_logo_bgra = None  # type: ignore[misc, assignment]
StatusBarWidget = None  # type: ignore[misc, assignment]
clock_saver_composite_bgra = None  # type: ignore[misc, assignment]
ClockSaverVolumeHold = None  # type: ignore[misc, assignment]
VolumeLineReveal = None  # type: ignore[misc, assignment]
audio_meter_face_enabled = None  # type: ignore[misc, assignment]
latest_meter_cache_key = None  # type: ignore[misc, assignment]
render_audio_meter_composite_bgra = None  # type: ignore[misc, assignment]
stop_audio_meter_capture = None  # type: ignore[misc, assignment]
sync_audio_meter_capture = None  # type: ignore[misc, assignment]
latest_visualizer_cache_key = None  # type: ignore[misc, assignment]
audio_connection_ok = None  # type: ignore[misc, assignment]
program_audio_present = None  # type: ignore[misc, assignment]
program_audio_session_present = None  # type: ignore[misc, assignment]
toggle_audio_meter_face = None  # type: ignore[misc, assignment]
PlaybackOverlayWidget = None  # type: ignore[misc, assignment]
compose_playback_volume_widget_line = None  # type: ignore[misc, assignment]
PATCH_LAYER_RECEIVER_AUDIO = "receiver_audio"  # type: ignore[misc, assignment]
PATCH_LAYER_STREAMING_BADGE = "streaming_badge"  # type: ignore[misc, assignment]
pigeon_wordmark_design_patch = None  # type: ignore[misc, assignment]
ViewCirclesWidget = None  # type: ignore[misc, assignment]
MainSettingsWidget = None  # type: ignore[misc, assignment]
build_info_cluster_design_patches = None  # type: ignore[misc, assignment]
INFO_CLUSTER_COL_RIGHT = 18.0
INFO_CLUSTER_CLOCK_ROW_1BASED = 1.0  # type: ignore[misc, assignment]
prepare_default_poster_at_startup = None  # type: ignore[misc, assignment]
metadata_has_playback_title = None  # type: ignore[misc, assignment]
resolve_metadata_tmdb_query = None  # type: ignore[misc, assignment]

# Splash symbols stay importable when splash group fails (call sites check paths).
FALLBACK_SPLASH_FRAME_COUNT = 0
SPLASH_FADE_OUT_FRAMES = 0
SPLASH_CLOCK_REVEAL_FRAME = 234
SPLASH_FPS = 30
SPLASH_MAX_DURATION_S = 0.0
apply_splash_global_alpha = None  # type: ignore[misc, assignment]
bgra_to_pil_rgba = None  # type: ignore[misc, assignment]
builtin_splash_bgra_frame = None  # type: ignore[misc, assignment]
composite_splash_over_bg = None  # type: ignore[misc, assignment]
find_splash_video_path = None  # type: ignore[misc, assignment]
flatten_bgra_over_bg_to_rgb = None  # type: ignore[misc, assignment]
list_splash_png_paths = None  # type: ignore[misc, assignment]
load_splash_bgra = None  # type: ignore[misc, assignment]
resolve_splash_media = None  # type: ignore[misc, assignment]
resize_bgra_if_needed = None  # type: ignore[misc, assignment]
splash_end_fade_factor = None  # type: ignore[misc, assignment]
splash_effective_frame_count = None  # type: ignore[misc, assignment]
splash_keep_alpha_for_live_clock = None  # type: ignore[misc, assignment]

try:
    from pigeon.compositing import (
        alpha_blend_bgra_over_bgr,
        lerp_bgr_red_monochrome,
        scale_bgra_rgb,
        scale_cover_center_crop,
        scale_height_and_center_crop,
        scale_uniform_letterbox,
    )
    from pigeon.design import (
        DESIGN_H,
        DESIGN_W,
        get_grid_geometry,
        playback_lower_gradient_bgra,
        rect_for_span_at_cell,
        rect_for_span_top_right_at_cell,
    )
    from pigeon.overlay import blend_overlay_bgr, build_stage_overlay_source_bgra

    _PIGEON_EXT = True
except ImportError as _exc:
    _log_optional_import_failure("core_compositing", _exc)


try:
    from pigeon.widgets.clock_calendar import (
        CLOCK_WIDGET_COL_RIGHT,
        CLOCK_WIDGET_ROW,
        ClockCalendarWidget,
    )

    CLOCK_ANCHOR_ROW = CLOCK_WIDGET_ROW
    CLOCK_ANCHOR_COL = int(VIEW_ONE_CLOCK_COL_RIGHT)
    from pigeon.widgets.location_toast import (
        LOCATION_TOAST_FADE_S,
        LOCATION_TOAST_FULL_S,
        location_toast_patch_bgra,
    )
    from pigeon.widgets.logo_tmdb import TmdbLogoWidget
    from pigeon.widgets.status_bar import StatusBarWidget
    from pigeon.widgets.clock_saver import (
        ClockSaverVolumeHold,
        VolumeLineReveal,
        clock_saver_composite_bgra,
    )
except ImportError as _exc:
    _log_optional_import_failure("clock_status_widgets", _exc)

try:
    from pigeon.widgets.audio_meter_saver import (
        audio_connection_ok,
        audio_meter_face_enabled,
        latest_meter_cache_key,
        latest_visualizer_cache_key,
        program_audio_present,
        program_audio_session_present,
        render_audio_meter_composite_bgra,
        stop_audio_meter_capture,
        sync_audio_meter_capture,
        toggle_audio_meter_face,
    )
except ImportError as _exc:
    _log_optional_import_failure("audio_meter_saver", _exc)

try:
    from pigeon.view_one_variants import (
        ViewOneVariant,
        load_pigeon_temp_logo_bgra,
        render_ui_music_text_patch_bgra,
        render_ui_text_patch_bgra,
        render_view_one_video_content_b_title_patch_bgra,
        resolve_view_one_variant,
        variant_has_alternate,
        variant_uses_full_path,
    )
except ImportError as _exc:
    _log_optional_import_failure("view_one_variants", _exc)

try:
    from pigeon.widgets.playback_overlay import (
        PATCH_LAYER_RECEIVER_AUDIO,
        PATCH_LAYER_STREAMING_BADGE,
        PlaybackOverlayWidget,
        compose_playback_volume_widget_line,
        pigeon_wordmark_design_patch,
    )
except ImportError as _exc:
    _log_optional_import_failure("playback_widgets", _exc)

try:
    from pigeon.widgets.view_circles import ViewCirclesWidget
except ImportError as _exc:
    _log_optional_import_failure("view_circles", _exc)
    ViewCirclesWidget = None  # type: ignore[misc, assignment]

try:
    from pigeon.widgets.main_settings import MainSettingsWidget
except ImportError as _exc:
    _log_optional_import_failure("main_settings", _exc)
    MainSettingsWidget = None  # type: ignore[misc, assignment]

try:
    from pigeon.widgets.info_cluster import (
        INFO_CLUSTER_CLOCK_ROW_1BASED,
        INFO_CLUSTER_COL_RIGHT,
        build_info_cluster_design_patches,
    )
    from pigeon.widgets.poster_art import prepare_default_poster_at_startup
    from pigeon.raw_title import metadata_has_playback_title, resolve_metadata_tmdb_query
except ImportError as _exc:
    _log_optional_import_failure("info_poster_metadata", _exc)

try:
    from pigeon.splash_sequence import (
        FALLBACK_SPLASH_FRAME_COUNT,
        SPLASH_CLOCK_REVEAL_FRAME,
        SPLASH_FADE_OUT_FRAMES,
        SPLASH_FPS,
        SPLASH_MAX_DURATION_S,
        apply_splash_global_alpha,
        bgra_to_pil_rgba,
        builtin_splash_bgra_frame,
        composite_splash_over_bg,
        find_splash_video_path,
        flatten_bgra_over_bg_to_rgb,
        list_splash_png_paths,
        load_splash_bgra,
        resolve_splash_media,
        resize_bgra_if_needed,
        splash_effective_frame_count,
        splash_end_fade_factor,
        splash_keep_alpha_for_live_clock,
    )
except ImportError as _exc:
    _log_optional_import_failure("splash_sequence", _exc)

if not callable(splash_keep_alpha_for_live_clock):
    def splash_keep_alpha_for_live_clock(  # type: ignore[misc]
        frame_index: int,
        reveal_frame: int = SPLASH_CLOCK_REVEAL_FRAME,
    ) -> bool:
        return int(frame_index) >= int(reveal_frame)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# Native UI composes at 1280×800. Window/display target follows the panel (env override).
UI_TARGET_W = 1280
UI_TARGET_H = 800
DISPLAY_W = _env_int("PIGEON_DISPLAY_W", 1280)
DISPLAY_H = _env_int("PIGEON_DISPLAY_H", 800)
try:
    _LAUNCH_WINDOW_SCALE = float(os.environ.get("PIGEON_WINDOW_SCALE", "1.0") or "1.0")
except ValueError:
    _LAUNCH_WINDOW_SCALE = 1.0
_LAUNCH_WINDOW_SCALE = max(0.25, min(_LAUNCH_WINDOW_SCALE, 4.0))
WINDOW_W = int(round(DISPLAY_W * _LAUNCH_WINDOW_SCALE))
WINDOW_H = int(round(DISPLAY_H * _LAUNCH_WINDOW_SCALE))


def _apple_tv_scan_timeout_s() -> int:
    default = 12 if sys.platform == "linux" else 6
    return _env_int("PIGEON_APPLE_TV_SCAN_TIMEOUT", default)


def _resize_bgr_to_dims(dst_w: int, dst_h: int, src: np.ndarray) -> np.ndarray:
    """Resize to window/cap size; LANCZOS4 when upscaling, AREA when downscaling."""
    sh, sw = int(src.shape[0]), int(src.shape[1])
    if sw == dst_w and sh == dst_h:
        return src
    return cv2.resize(
        src,
        (dst_w, dst_h),
        interpolation=cv_resize_interp(sw, sh, dst_w, dst_h),
    )


def _composite_cap_dims(display_w: int, display_h: int) -> tuple[int, int, bool]:
    """
    Internal composite size for video + mic EQ + UI blits.

    Always composes at the native 1280×800 design resolution, then
    ``_present_frame_to_display`` letterboxes/pillarboxes to the live window when needed.
    """
    dw = max(1, int(display_w))
    dh = max(1, int(display_h))
    if dw == UI_TARGET_W and dh == UI_TARGET_H:
        return UI_TARGET_W, UI_TARGET_H, False
    return UI_TARGET_W, UI_TARGET_H, True


def _present_frame_to_display(
    image: np.ndarray,
    display_w: int,
    display_h: int,
    *,
    native_now_playing: bool = False,
) -> np.ndarray:
    """Scale entire frame into the window with black letterbox/pillarbox bars.

    Applies pixel-aspect compensation when the panel PAR is non-square (e.g. official
    Pi 7″ touchscreen) so designed circles stay round on glass.

    Leftover 800×480 screens get a red square at (0, 0). Native 1280×800
    frames (now-playing, clock saver, splash) are already at design size
    and must not be stamped.
    """
    dw = max(1, int(display_w))
    dh = max(1, int(display_h))
    if not native_now_playing:
        try:
            from pigeon.np_layout import is_native_design_frame, stamp_legacy_update_mark

            if not is_native_design_frame(image):
                image = np.ascontiguousarray(image.copy())
                stamp_legacy_update_mark(image)
        except Exception:
            pass
    try:
        from pigeon.display_par import apply_par_compensation

        return apply_par_compensation(image, display_w=dw, display_h=dh)
    except Exception:
        pass
    if int(image.shape[1]) == dw and int(image.shape[0]) == dh:
        return image
    if _PIGEON_EXT and scale_uniform_letterbox is not None:
        return scale_uniform_letterbox(image, dw, dh)
    return _resize_bgr_to_dims(dw, dh, image)


def _bgra_to_display_window(bgra: np.ndarray) -> np.ndarray:
    """Fit splash/UI BGRA (design size) into the live display window with black bars when needed."""
    if not _PIGEON_EXT:
        return bgra
    assert resize_bgra_if_needed is not None
    fitted = resize_bgra_if_needed(bgra, UI_TARGET_W, UI_TARGET_H)
    try:
        from pigeon.display_par import apply_par_compensation

        return apply_par_compensation(fitted, display_w=WINDOW_W, display_h=WINDOW_H)
    except Exception:
        pass
    if scale_uniform_letterbox is not None:
        return scale_uniform_letterbox(fitted, WINDOW_W, WINDOW_H)
    return resize_bgra_if_needed(fitted, WINDOW_W, WINDOW_H)


# App-logo backdrop when TMDb has no art: letterbox canvas is at most this fraction of the live window.
APP_LOGO_FALLBACK_MAX_RESOLUTION_FRACTION = 0.9
# Reserved strip at bottom when developer mode is on (must not sit under the full-bleed video label).
OVERLAY_HUD_H = 52


class DevPhase(IntEnum):
    OFF = 0
    GRID = 1  # rare: Advanced matrix may stash this while open
    MAIN_SETTINGS = 2  # SVG settings_main + pigeon / prefs / update / keyboard


class DisplayView(IntEnum):
    """User-selectable display layout (keys 1, 4, 5). Unused values kept for stable ints."""

    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6


class ViewOneLayout(IntEnum):
    """
    When ``DisplayView.ONE`` is active, Shift+1 cycles the layout toggle (historical
    full / simple / poster modes). View 1 always renders the 070326 now-playing screen.

    Member names are **historical** — they describe the happy-path visual that
    shipped before the v0.6.14 V01 ↔ V02 swap and the v0.6.19 view-naming
    refactor. The toggle's real meaning in the new vocabulary is
    ``viewOne.videoContent_a`` (initial) vs. ``viewOne.videoContent_b``
    (alternate). The V# variant that actually renders depends on this toggle
    *and* on which content assets are live (see
    ``pigeon.view_one_variants.resolve_view_one_variant``).

    ``PIGEON_FULL`` (0, initial) → ``viewOne.videoContent_a``: default mode.
    When all TMDb assets are present renders V01 — minimal pigeonTMDB_TT on
    black. With missing assets routes to V03 / V05 / V07 / V08 / V09.
    ``PIGEON_SIMPLE`` (1) → ``viewOne.videoContent_b``: alternate mode.
    Toggled on by pressing Shift+``1`` while on view 1. When all TMDb assets are
    present renders V02 — the full pigeonTMDB_BD + pigeonTMDB_TT + appLogo
    composition. With missing assets routes to V04 / V06.

    ``PIGEON_POSTER`` (2) → ``viewOne.videoContent_c``: poster mode. Keeps the
    same chrome stack as viewOne.videoContent_b but replaces TMDb TT/BD with
    ``pigeonTMDB_Poster`` centered horizontally in the top 7 rows.

    Related view identifiers in the new vocabulary (not modeled by this enum
    because they're driven by content presence or idle timers rather than a
    user toggle):

    * ``viewOne.audioContent`` — music-only content. A MediaType.Music
      override in ``_compose_shown_frame`` substitutes a two-line text patch
      ("Track title" + "Artist - Album") inside the pigeonTMDB_TT rect and
      suppresses the bottom gradient.
    * ``viewOne.startup`` / ``viewOne.noContent`` — V09 fallback; static Pigeon logo at 30% alpha.
    * ``viewOne.clockSaver_a`` / ``viewOne.clockSaver_b`` — the idle clock
      saver composites over whichever base (black or pigeonTMDB_BD) the
      active videoContent variant produced.
    """

    PIGEON_FULL = 0
    PIGEON_SIMPLE = 1
    PIGEON_POSTER = 2


# TMDb static backdrop scene (not paused-video dim 0.3).
BACKDROP_BRIGHTNESS = 0.8
# Static landing logo (no video): full brightness; old 0.3 “paused video” level hid the art.
LANDING_DISPLAY_BRIGHTNESS = 1.0
LANDING_DIM_BRIGHTNESS = 0.78  # Space-bar pulse “off” — still readable vs old 0.3
PAUSED_SCREEN_BACKDROP_DIM = 0.72
# After UI bootstrap, optional auto-restore of saved TMDb backdrop (env-gated) runs after this delay.
STARTUP_PIGEON_WORDMARK_MAX_S = 5.0
# After splash: optional startup transition timing (no mic EQ).
SKIP_POST_SPLASH_STARTUP_TRANSITION = True
# After splash lifts: optional clock ease-up from black (0 = full-on; PNG splash reveals saver).
CLOCK_STARTUP_FADE_S = 0.0
# If True and a saved TMDb backdrop exists, switch to it when this timer elapses.
STARTUP_AUTO_RESTORE_SAVED_BACKDROP = os.environ.get("PIGEON_STARTUP_RESTORE_BACKDROP", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Theater UI: red luma-mono only when neither Apple TV nor Pigeon UI shows activity this long.
# ATV side: poll metadata deltas (see _update_atv_interaction_from_poll_metadata).
# Pigeon side: mouse / keyboard / settings scroll (see _bump_pigeon_user_activity).
# For ATV, 0 = never bumped → treated as idle until the first remote-driven signal (still needs Pigeon idle).
THEATER_IDLE_DIM_AFTER_S = 45.0
# Red idle-dim is **off** by default until an ambient-light (or other) trigger is integrated.
# Re-enable anytime: ``PIGEON_THEATER_IDLE_DIM=1`` (or ``true`` / ``yes`` / ``on``). Explicit ``0`` / ``off`` keeps it off.
_THEATER_IDLE_DIM_ENV = os.environ.get("PIGEON_THEATER_IDLE_DIM", "").strip().lower()
THEATER_IDLE_DIM_ENABLED = (
    _THEATER_IDLE_DIM_ENV in ("1", "true", "yes", "on")
    if _THEATER_IDLE_DIM_ENV
    else False
)
# Ease in/out between full color and red luma-mono when idle-dim target changes.
ATV_IDLE_MONO_ANIM_S = 2.0
# Idle “clock saver” (screensaver): requires both ``CLOCK_SAVER_AFTER_S`` of **UI** inactivity (mouse/keys/etc.;
# mic does not touch those timestamps) **and** the same span without **significant** device signals (content
# selection, ``device_state``, or ``volume_percent`` from the player poll, plus receiver volume line changes).
CLOCK_SAVER_AFTER_S = 300.0
# Leave settings_main after this long with no mouse/key/rotary input.
SETTINGS_MENU_IDLE_EXIT_S = 60.0
# Saver text opacity when idle; tap while saver is up briefly uses 1.0 (see clock_saver_peek_until_mono).
CLOCK_SAVER_DIM_OPACITY = 0.54
CLOCK_SAVER_PEEK_S = 2.5
# With a TMDb backdrop visible: fade backdrop to black under the clock after this idle span on the saver.
# Clock saver: multiply backdrop RGB by this factor (0.3 → 30% brightness) while saver is active.
CLOCK_SAVER_BACKDROP_DIM = 0.3
# Position-stall grace: while content position has advanced within this window, the clock-saver
# "device signal" timestamp keeps being bumped to ``now``, so the 300 s saver timer stays reset.
# Once the reported playback position stays flat for longer than this, the timer resumes counting
# from the last advance toward ``CLOCK_SAVER_AFTER_S``. Tuned to survive short buffering stalls
# (typical re-buffer is < 2 s) without prematurely arming the saver. A position advance while the
# saver is already open ends it on the next render tick via the same bump.
CLOCK_SAVER_POSITION_STALL_GRACE_S = 5.0
# When player poll metadata stays unchanged for this long **and** no local Pigeon
# controls were used for the same span, force the clock saver on (independent of the
# 300 s UI+device idle path). Position not advancing is the primary signal; HDMI
# frame/title changes also refresh the stamp. When metadata is driving the saver,
# the HDMI unchanged-frame streak rule is ignored.
CLOCK_SAVER_METADATA_IDLE_AFTER_S = 120.0
# Pause-hold span is CLOCK_SAVER_PAUSED_AFTER_S (clock_saver_policy).

# Idle composite cadence when video is paused (lower than live playback).
PAUSED_COMPOSITE_MS = 83  # ~12 FPS

HOTKEY_BINDTAG = "Pigeon0_5_hotkeys"

def _paint_boolean_led(canvas: tk.Canvas, ok: bool | None) -> None:
    """Single lamp: green=detected+compatible, amber=detected+unknown/incompatible, red=not detected/not compatible."""
    canvas.delete("all")
    if ok is True:
        fill = "#1fcb5d"
    elif ok is None:
        fill = "#f0ad4e"
    else:
        fill = "#e74c3c"
    canvas.create_oval(2, 2, 14, 14, fill=fill, outline="#151518", width=1)


def _prepend_hotkey_bindtag(widget: tk.Misc, tag: str = HOTKEY_BINDTAG) -> None:
    widget.bindtags((tag,) + widget.bindtags())


def _widget_accepts_typing(widget: tk.Misc) -> bool:
    """True if Return/other keys should go to the widget (not global developer-mode shortcuts)."""
    try:
        cls = widget.winfo_class()
    except tk.TclError:
        return False
    if cls == "Text":
        try:
            if str(widget.cget("state")).lower() == "disabled":
                return False
        except tk.TclError:
            pass
        return True
    if cls in ("Entry",):
        return True
    if cls == "TEntry" or cls == "TCombobox":
        return True
    return False


def _raw_title_query_from_metadata(md: dict | None) -> str | None:
    """Verbatim playback ``title`` (rawTitle layer) refined for TMDb."""
    if not md:
        return None
    try:
        from pigeon.raw_title import raw_title_from_metadata_dict
        from pigeon.tmdb_poster import is_degenerate_tmdb_query, refine_tmdb_search_query

        rt = raw_title_from_metadata_dict(md)
        raw = (rt.raw_title or "").strip()
        if not raw:
            return None
        r = refine_tmdb_search_query(raw) or raw
        return r.strip() if r.strip() and not is_degenerate_tmdb_query(r) else None
    except Exception:
        raw = str(md.get("title") or "").strip()
        return raw or None


def _alternate_tmdb_query_from_metadata(md: dict | None, primary: str) -> str | None:
    """
    Pick a different TMDb query from last Apple TV metadata.

    Order prefers ``series_name`` / ``artist`` before ``title`` (title is often ``Sketch - SNL``).
    Refined strings that mean the same show as the primary (e.g. ``SNL`` vs ``Papyrus - SNL``)
    are skipped so ``?`` retry does not replace a good match with a sketch line.
    """
    if not primary or not md:
        return None
    try:
        from pigeon.tmdb_poster import equivalent_tmdb_search_queries, refine_tmdb_search_query
    except ImportError:

        def refine_tmdb_search_query(x: str | None) -> str | None:  # type: ignore[misc]
            return (str(x).strip() or None) if x else None

        def equivalent_tmdb_search_queries(a: str, b: str) -> bool:  # type: ignore[misc]
            return (a or "").strip().lower() == (b or "").strip().lower()

    pr = refine_tmdb_search_query(primary.strip()) or primary.strip()
    for key in ("series_name", "artist", "album", "title"):
        c = str(md.get(key) or "").strip()
        if not c:
            continue
        cr = refine_tmdb_search_query(c) or c
        if equivalent_tmdb_search_queries(cr, pr):
            continue
        return cr
    return None


def _pyatv_install_hint() -> str:
    exe = sys.executable or "python3"
    return f"Apple TV support requires pyatv.\n\nInstall with:\n  {exe} -m pip install pyatv"


@dataclass(frozen=True)
class SceneFit:
    target_w: int = WINDOW_W
    target_h: int = WINDOW_H

    def scale_and_crop(self, frame_bgr: np.ndarray) -> np.ndarray:
        if frame_bgr is None or frame_bgr.size == 0:
            raise ValueError("Empty frame")

        src_h, src_w = frame_bgr.shape[:2]
        if src_h <= 0 or src_w <= 0:
            raise ValueError(f"Invalid frame size {src_w}x{src_h}")

        scale = self.target_h / float(src_h)
        scaled_w = int(round(src_w * scale))
        scaled_h = self.target_h

        resized = cv2.resize(
            frame_bgr,
            (scaled_w, scaled_h),
            interpolation=cv_resize_interp(src_w, src_h, scaled_w, scaled_h),
        )

        if scaled_w == self.target_w:
            return resized

        if scaled_w < self.target_w:
            pad = self.target_w - scaled_w
            left = pad // 2
            right = pad - left
            sb, sg, sr = get_stage_bgr()
            return cv2.copyMakeBorder(
                resized,
                top=0,
                bottom=0,
                left=left,
                right=right,
                borderType=cv2.BORDER_CONSTANT,
                value=(sb, sg, sr),
            )

        x0 = (scaled_w - self.target_w) // 2
        x1 = x0 + self.target_w
        return resized[:, x0:x1]


def _default_render_fps() -> float:
    """Tk timer cadence for static landing + composited widgets (no scene video)."""
    import os
    import sys

    env = os.environ.get("PIGEON_UI_FPS", "").strip()
    if env:
        try:
            return max(5.0, min(60.0, float(env)))
        except ValueError:
            pass
    # Pi / Linux: keep PhotoImage uploads and settings SVG compositing lighter.
    if sys.platform.startswith("linux"):
        return 12.0
    return 30.0


def _build_landing_design_bgr(design_w: int, design_h: int, logo_path: Path | None) -> np.ndarray:
    """Pure black design-sized canvas with the Pigeon logo centered (alpha-aware)."""
    out = np.zeros((design_h, design_w, 3), dtype=np.uint8)
    if logo_path is None or not logo_path.is_file():
        sys.stderr.write("pigeon: landing logo not found — using black screen only\n")
        sys.stderr.flush()
        return out
    arr: np.ndarray | None = None
    try:
        arr = cv2.imread(str(logo_path), cv2.IMREAD_UNCHANGED)
    except Exception:
        arr = None
    if arr is None or arr.size == 0:
        try:
            pil_img = Image.open(logo_path).convert("RGBA")
            arr = np.asarray(pil_img, dtype=np.uint8)
        except Exception as e:
            sys.stderr.write(f"pigeon: could not load landing logo {logo_path}: {e}\n")
            sys.stderr.flush()
            return out
    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    rh, rw = int(arr.shape[0]), int(arr.shape[1])
    if rw <= 0 or rh <= 0:
        return out
    max_side = int(0.55 * min(design_w, design_h))
    max_side = max(32, max_side)
    scale = min(max_side / float(rw), max_side / float(rh), 1.0)
    nw = max(1, int(round(rw * scale)))
    nh = max(1, int(round(rh * scale)))
    if nw != rw or nh != rh:
        arr = cv2.resize(arr, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
    rh, rw, ch = int(arr.shape[0]), int(arr.shape[1]), int(arr.shape[2])
    if ch >= 4:
        bgr = arr[:, :, :3]
        alpha = arr[:, :, 3:4].astype(np.float32) / 255.0
    else:
        bgr = arr[:, :, :3]
        alpha = np.ones((rh, rw, 1), dtype=np.float32)
    x0 = (design_w - nw) // 2
    y0 = (design_h - nh) // 2
    roi = out[y0 : y0 + nh, x0 : x0 + nw]
    roi[:] = (bgr.astype(np.float32) * alpha + roi.astype(np.float32) * (1.0 - alpha)).astype(np.uint8)
    return out


def _apply_brightness(frame_bgr: np.ndarray, factor: float) -> np.ndarray:
    factor = float(factor)
    if factor >= 0.999:
        return frame_bgr
    if factor <= 0.0:
        return np.zeros_like(frame_bgr)
    return cv2.convertScaleAbs(frame_bgr, alpha=factor, beta=0)


_TK_RGB_SCRATCH: np.ndarray | None = None


def _bgr_to_tk_image(frame_bgr: np.ndarray) -> ImageTk.PhotoImage:
    try:
        from pigeon.widgets.options_settings import apply_ui_look_bgr

        frame_bgr = apply_ui_look_bgr(frame_bgr)
    except Exception:
        pass
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
    return ImageTk.PhotoImage(image=img)


# What the live PhotoImage currently shows (BGR, after the UI look), so the
# next frame can upload only the bands that changed. See pigeon/core/photo_upload.py.
_TK_SHOWN: dict[str, object] = {"photo": None, "bgr": None, "scratch": None}


def _note_photo_shows(photo: ImageTk.PhotoImage | None, src: np.ndarray) -> None:
    if photo is None or not _photo_upload.partial_upload_enabled():
        _TK_SHOWN["photo"] = _TK_SHOWN["bgr"] = None
        return
    shown = _TK_SHOWN["bgr"]
    if isinstance(shown, np.ndarray) and shown.shape == src.shape:
        np.copyto(shown, src)
    else:
        _TK_SHOWN["bgr"] = src.copy()
    _TK_SHOWN["photo"] = photo


def _upload_changed_bands(photo: ImageTk.PhotoImage | None, src: np.ndarray) -> bool:
    """Push only the changed bands of *src* into *photo*. False: caller uploads it all."""
    shown = _TK_SHOWN["bgr"]
    if photo is None or _TK_SHOWN["photo"] is not photo or not isinstance(shown, np.ndarray):
        return False
    if not _photo_upload.partial_upload_enabled():
        _TK_SHOWN["photo"] = _TK_SHOWN["bgr"] = None
        return False
    bands = _photo_upload.changed_bands(shown, src)
    if bands is None:
        return False
    if not bands:
        return True
    h, w = int(src.shape[0]), int(src.shape[1])
    try:
        scratch = _TK_SHOWN["scratch"]
        if scratch is None or scratch.width() != w or scratch.height() != h:
            # Pillow pastes at 0,0 only, so stage each band here and let Tk
            # copy it into place.
            scratch = ImageTk.PhotoImage(image=Image.new("RGB", (w, h)))
            _TK_SHOWN["scratch"] = scratch
        for y0, y1, x0, x1 in bands:
            band = src[y0:y1, x0:x1]
            scratch.paste(Image.fromarray(cv2.cvtColor(band, cv2.COLOR_BGR2RGB)))
            photo.tk.call(
                str(photo), "copy", str(scratch),
                "-from", 0, 0, x1 - x0, y1 - y0,
                "-to", x0, y0,
                "-compositingrule", "set",
            )
            shown[y0:y1, x0:x1] = band
    except (tk.TclError, ValueError):
        _TK_SHOWN["photo"] = _TK_SHOWN["bgr"] = None
        return False
    return True


def _update_label_photo_from_bgr(
    label: tk.Label,
    frame_bgr: np.ndarray,
    holder: list[ImageTk.PhotoImage | None],
) -> None:
    """
    Reuse one ``PhotoImage`` and ``paste`` each frame. Creating hundreds of new
    ``PhotoImage`` objects per second leaks native Tk storage and locks up after a short run.

    Pillow's ``ImageTk.PhotoImage.paste`` on the Pi takes only the image (no dest box).
    """
    try:
        from pigeon.widgets.options_settings import apply_ui_look_bgr

        frame_bgr = apply_ui_look_bgr(frame_bgr)
    except Exception:
        pass
    src = np.ascontiguousarray(frame_bgr)
    h, w = int(src.shape[0]), int(src.shape[1])
    if h < 1 or w < 1:
        return
    global _TK_RGB_SCRATCH
    rgb = _TK_RGB_SCRATCH
    if rgb is None or int(rgb.shape[0]) != h or int(rgb.shape[1]) != w:
        rgb = np.empty((h, w, 3), dtype=np.uint8)
        _TK_RGB_SCRATCH = rgb
    ph = holder[0]
    if not _upload_changed_bands(ph, src):
        cv2.cvtColor(src, cv2.COLOR_BGR2RGB, dst=rgb)
        pil_img = Image.fromarray(rgb)
        try:
            if ph is None or ph.width() != w or ph.height() != h:
                holder[0] = ImageTk.PhotoImage(image=pil_img)
                ph = holder[0]
            else:
                ph.paste(pil_img)
        except tk.TclError:
            holder[0] = ImageTk.PhotoImage(image=pil_img)
            ph = holder[0]
        _note_photo_shows(holder[0], src)
    # Re-configuring the same PhotoImage every tick still stresses Tk; paste updates pixels in place.
    if getattr(label, "image", None) is not ph:
        label.configure(image=ph)
    label.image = ph


def _load_persisted_scene_enabled(default: bool = True) -> bool:
    v = read_app_state().get("scene_enabled")
    if isinstance(v, bool):
        return v
    return default


def _save_persisted_scene_enabled(enabled: bool) -> None:
    write_app_state(scene_enabled=enabled)


def _format_hmmss(seconds_value: float | int | None) -> str:
    """Compact clock for on-screen TRT: drop leading zeros / unused fields (e.g. ``30:00``, ``59:29``)."""
    try:
        total_seconds = max(0, int(float(seconds_value or 0)))
    except (TypeError, ValueError):
        total_seconds = 0
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    if minutes > 0:
        return f"{minutes}:{seconds:02d}"
    return f"{seconds}"


def main() -> int:
    # Setup runs as 4 phases in pigeon/core/boot/ (m*.py, see BootContext);
    # the rest of main() and bootstrap() read their results back below.
    _main_ctx = _BootContext(
        ClockSaverVolumeHold=ClockSaverVolumeHold,
        DESIGN_H=DESIGN_H,
        DESIGN_W=DESIGN_W,
        DISPLAY_H=DISPLAY_H,
        DISPLAY_W=DISPLAY_W,
        FALLBACK_SPLASH_FRAME_COUNT=FALLBACK_SPLASH_FRAME_COUNT,
        PAUSED_COMPOSITE_MS=PAUSED_COMPOSITE_MS,
        SPLASH_CLOCK_REVEAL_FRAME=SPLASH_CLOCK_REVEAL_FRAME,
        SPLASH_FADE_OUT_FRAMES=SPLASH_FADE_OUT_FRAMES,
        SPLASH_FPS=SPLASH_FPS,
        SPLASH_MAX_DURATION_S=SPLASH_MAX_DURATION_S,
        UI_TARGET_H=UI_TARGET_H,
        UI_TARGET_W=UI_TARGET_W,
        VolumeLineReveal=VolumeLineReveal,
        WINDOW_H=WINDOW_H,
        WINDOW_W=WINDOW_W,
        _LAUNCH_WINDOW_SCALE=_LAUNCH_WINDOW_SCALE,
        _PIGEON_EXT=_PIGEON_EXT,
        _PROJECT_DIR=_PROJECT_DIR,
        __file__=__file__,
        _bgr_to_tk_image=_bgr_to_tk_image,
        _bgra_to_display_window=_bgra_to_display_window,
        _present_frame_to_display=_present_frame_to_display,
        alpha_blend_bgra_over_bgr=alpha_blend_bgra_over_bgr,
        apply_splash_global_alpha=apply_splash_global_alpha,
        builtin_splash_bgra_frame=builtin_splash_bgra_frame,
        clock_saver_composite_bgra=clock_saver_composite_bgra,
        flatten_bgra_over_bg_to_rgb=flatten_bgra_over_bg_to_rgb,
        load_splash_bgra=load_splash_bgra,
        render_audio_meter_composite_bgra=render_audio_meter_composite_bgra,
        resolve_splash_media=resolve_splash_media,
        splash_effective_frame_count=splash_effective_frame_count,
        splash_end_fade_factor=splash_end_fade_factor,
        splash_keep_alpha_for_live_clock=splash_keep_alpha_for_live_clock,
        stop_audio_meter_capture=stop_audio_meter_capture,
    )
    _boot_m01_window.run(_main_ctx)
    _boot_m02_shell.run(_main_ctx)
    _boot_m03_volume_and_reveal.run(_main_ctx)
    _boot_m04_splash.run(_main_ctx)

    _app_startup_mono = _main_ctx._app_startup_mono
    _apply_clock_to_bridge_label = _main_ctx._apply_clock_to_bridge_label
    _boot_clock_host = _main_ctx._boot_clock_host
    _boot_clock_photo = _main_ctx._boot_clock_photo
    _clock_saver_layers = _main_ctx._clock_saver_layers
    _clock_saver_receiver_off = _main_ctx._clock_saver_receiver_off
    _clock_saver_volume = _main_ctx._clock_saver_volume
    _clock_saver_volume_raw = _main_ctx._clock_saver_volume_raw
    _finish_post_splash_startup_transition = _main_ctx._finish_post_splash_startup_transition
    _grid_patched = _main_ctx._grid_patched
    _kiosk_on = _main_ctx._kiosk_on
    _live_clock_until_compose = _main_ctx._live_clock_until_compose
    _note_volume_graphics = _main_ctx._note_volume_graphics
    _note_zone3_volume_takeover = _main_ctx._note_zone3_volume_takeover
    _pack_patched = _main_ctx._pack_patched
    _place_patched = _main_ctx._place_patched
    _post_splash_startup_hook = _main_ctx._post_splash_startup_hook
    _remember_clock_saver_volume = _main_ctx._remember_clock_saver_volume
    _restore_desktop_chrome = _main_ctx._restore_desktop_chrome
    _reveal_clock_under_splash = _main_ctx._reveal_clock_under_splash
    _splash_clock_ready_bgr = _main_ctx._splash_clock_ready_bgr
    _splash_clock_refresh_stop = _main_ctx._splash_clock_refresh_stop
    _splash_on_reveal_paint = _main_ctx._splash_on_reveal_paint
    _splash_reveal_clock = _main_ctx._splash_reveal_clock
    _splash_underlay_bgr = _main_ctx._splash_underlay_bgr
    _tk_grid_orig = _main_ctx._tk_grid_orig
    _tk_pack_orig = _main_ctx._tk_pack_orig
    _tk_place_orig = _main_ctx._tk_place_orig
    _try_remove_splash_overlay = _main_ctx._try_remove_splash_overlay
    _volume_lines = _main_ctx._volume_lines
    bootstrap_done = _main_ctx.bootstrap_done
    cap = _main_ctx.cap
    content_host = _main_ctx.content_host
    denon_vol_cache = _main_ctx.denon_vol_cache
    paused_interval_ms = _main_ctx.paused_interval_ms
    post_splash_mono = _main_ctx.post_splash_mono
    receiver_overlay_state = _main_ctx.receiver_overlay_state
    receiver_standby_holder = _main_ctx.receiver_standby_holder
    root = _main_ctx.root
    shell = _main_ctx.shell
    splash_anim_done = _main_ctx.splash_anim_done
    splash_bootstrap_go = _main_ctx.splash_bootstrap_go
    try:
        splash_tick = _main_ctx.splash_tick
    except NameError:
        pass
    startup_ph = _main_ctx.startup_ph
    view_circles_widget_holder = _main_ctx.view_circles_widget_holder


    def bootstrap() -> None:
        # Startup runs as 14 phases in pigeon/core/boot/ (see BootContext). Seed the
        # shared context with the main() locals and module globals they read.
        ctx = _BootContext(
            APPLE_TV_FAIL_POLL_MAX_MS=APPLE_TV_FAIL_POLL_MAX_MS,
            APPLE_TV_IDLE_POLL_MS=APPLE_TV_IDLE_POLL_MS,
            APPLE_TV_POLL_MS=APPLE_TV_POLL_MS,
            APP_LOGO_FALLBACK_MAX_RESOLUTION_FRACTION=APP_LOGO_FALLBACK_MAX_RESOLUTION_FRACTION,
            ATV_IDLE_MONO_ANIM_S=ATV_IDLE_MONO_ANIM_S,
            BACKDROP_BRIGHTNESS=BACKDROP_BRIGHTNESS,
            CLOCK_ANCHOR_COL=CLOCK_ANCHOR_COL,
            CLOCK_ANCHOR_ROW=CLOCK_ANCHOR_ROW,
            CLOCK_SAVER_BACKDROP_DIM=CLOCK_SAVER_BACKDROP_DIM,
            CLOCK_SAVER_DIM_OPACITY=CLOCK_SAVER_DIM_OPACITY,
            CLOCK_SAVER_METADATA_IDLE_AFTER_S=CLOCK_SAVER_METADATA_IDLE_AFTER_S,
            CLOCK_SAVER_PEEK_S=CLOCK_SAVER_PEEK_S,
            CLOCK_SAVER_POSITION_STALL_GRACE_S=CLOCK_SAVER_POSITION_STALL_GRACE_S,
            CLOCK_STARTUP_FADE_S=CLOCK_STARTUP_FADE_S,
            CLOCK_WIDGET_ROW=CLOCK_WIDGET_ROW,
            ClockCalendarWidget=ClockCalendarWidget,
            DESIGN_H=DESIGN_H,
            DESIGN_W=DESIGN_W,
            DevPhase=DevPhase,
            DisplayView=DisplayView,
            HOTKEY_BINDTAG=HOTKEY_BINDTAG,
            INFO_CLUSTER_CLOCK_ROW_1BASED=INFO_CLUSTER_CLOCK_ROW_1BASED,
            INFO_CLUSTER_COL_RIGHT=INFO_CLUSTER_COL_RIGHT,
            LANDING_DIM_BRIGHTNESS=LANDING_DIM_BRIGHTNESS,
            LANDING_DISPLAY_BRIGHTNESS=LANDING_DISPLAY_BRIGHTNESS,
            LOCATION_TOAST_FADE_S=LOCATION_TOAST_FADE_S,
            LOCATION_TOAST_FULL_S=LOCATION_TOAST_FULL_S,
            MainSettingsWidget=MainSettingsWidget,
            PATCH_LAYER_RECEIVER_AUDIO=PATCH_LAYER_RECEIVER_AUDIO,
            PAUSED_SCREEN_BACKDROP_DIM=PAUSED_SCREEN_BACKDROP_DIM,
            PLAYBACK_UI_TICK_MS=PLAYBACK_UI_TICK_MS,
            PlaybackOverlayWidget=PlaybackOverlayWidget,
            RECEIVER_POLL_MS=RECEIVER_POLL_MS,
            RECEIVER_VOLUME_POLL_MS=RECEIVER_VOLUME_POLL_MS,
            SETTINGS_MENU_IDLE_EXIT_S=SETTINGS_MENU_IDLE_EXIT_S,
            SKIP_POST_SPLASH_STARTUP_TRANSITION=SKIP_POST_SPLASH_STARTUP_TRANSITION,
            STARTUP_AUTO_RESTORE_SAVED_BACKDROP=STARTUP_AUTO_RESTORE_SAVED_BACKDROP,
            STARTUP_PIGEON_WORDMARK_MAX_S=STARTUP_PIGEON_WORDMARK_MAX_S,
            SceneFit=SceneFit,
            StatusBarWidget=StatusBarWidget,
            THEATER_IDLE_DIM_AFTER_S=THEATER_IDLE_DIM_AFTER_S,
            THEATER_IDLE_DIM_ENABLED=THEATER_IDLE_DIM_ENABLED,
            TMDB_LOGO_ANCHOR_ROW=TMDB_LOGO_ANCHOR_ROW,
            TMDB_LOGO_FIT_SCALE=TMDB_LOGO_FIT_SCALE,
            TMDB_LOGO_SPAN_H=TMDB_LOGO_SPAN_H,
            TMDB_LOGO_SPAN_W=TMDB_LOGO_SPAN_W,
            TMDB_LOGO_TOP_RIGHT_COL=TMDB_LOGO_TOP_RIGHT_COL,
            TMDB_LOGO_VIEW6_ANCHOR_COL=TMDB_LOGO_VIEW6_ANCHOR_COL,
            TMDB_LOGO_VIEW6_ANCHOR_ROW=TMDB_LOGO_VIEW6_ANCHOR_ROW,
            TMDB_LOGO_VIEW6_FIT_SCALE=TMDB_LOGO_VIEW6_FIT_SCALE,
            TMDB_LOGO_VIEW6_SPAN_H=TMDB_LOGO_VIEW6_SPAN_H,
            TMDB_LOGO_VIEW6_SPAN_W=TMDB_LOGO_VIEW6_SPAN_W,
            TRT_DISPLAY_ROW=TRT_DISPLAY_ROW,
            TRT_LABEL_SPAN_H=TRT_LABEL_SPAN_H,
            TRT_LABEL_SPAN_W=TRT_LABEL_SPAN_W,
            TRT_PLAYED_COL=TRT_PLAYED_COL,
            TRT_PLAYED_TEXT=TRT_PLAYED_TEXT,
            TRT_REMAINING_COL=TRT_REMAINING_COL,
            TRT_REMAINING_TEXT=TRT_REMAINING_TEXT,
            TmdbLogoWidget=TmdbLogoWidget,
            UI_TARGET_H=UI_TARGET_H,
            UI_TARGET_W=UI_TARGET_W,
            VIEW_ONE_BADGE_COL_RIGHT=VIEW_ONE_BADGE_COL_RIGHT,
            VIEW_ONE_CLOCK_COL_RIGHT=VIEW_ONE_CLOCK_COL_RIGHT,
            ViewCirclesWidget=ViewCirclesWidget,
            ViewOneLayout=ViewOneLayout,
            ViewOneVariant=ViewOneVariant,
            WINDOW_H=WINDOW_H,
            WINDOW_W=WINDOW_W,
            _PIGEON_EXT=_PIGEON_EXT,
            _PROJECT_DIR=_PROJECT_DIR,
            _alternate_tmdb_query_from_metadata=_alternate_tmdb_query_from_metadata,
            _app_startup_mono=_app_startup_mono,
            _apple_tv_scan_timeout_s=_apple_tv_scan_timeout_s,
            _apply_brightness=_apply_brightness,
            _apply_clock_to_bridge_label=_apply_clock_to_bridge_label,
            _bgr_to_tk_image=_bgr_to_tk_image,
            _boot_clock_host=_boot_clock_host,
            _boot_clock_photo=_boot_clock_photo,
            _build_landing_design_bgr=_build_landing_design_bgr,
            _clock_saver_layers=_clock_saver_layers,
            _clock_saver_receiver_off=_clock_saver_receiver_off,
            _clock_saver_volume=_clock_saver_volume,
            _clock_saver_volume_raw=_clock_saver_volume_raw,
            _composite_cap_dims=_composite_cap_dims,
            _default_render_fps=_default_render_fps,
            _finish_post_splash_startup_transition=_finish_post_splash_startup_transition,
            _format_hmmss=_format_hmmss,
            _grid_patched=_grid_patched,
            _kiosk_on=_kiosk_on,
            _load_persisted_scene_enabled=_load_persisted_scene_enabled,
            _note_volume_graphics=_note_volume_graphics,
            _note_zone3_volume_takeover=_note_zone3_volume_takeover,
            _pack_patched=_pack_patched,
            _paint_boolean_led=_paint_boolean_led,
            _place_patched=_place_patched,
            _post_splash_startup_hook=_post_splash_startup_hook,
            _prepend_hotkey_bindtag=_prepend_hotkey_bindtag,
            _present_frame_to_display=_present_frame_to_display,
            _pyatv_install_hint=_pyatv_install_hint,
            _raw_title_query_from_metadata=_raw_title_query_from_metadata,
            _remember_clock_saver_volume=_remember_clock_saver_volume,
            _reveal_clock_under_splash=_reveal_clock_under_splash,
            _save_persisted_scene_enabled=_save_persisted_scene_enabled,
            _splash_clock_ready_bgr=_splash_clock_ready_bgr,
            _splash_clock_refresh_stop=_splash_clock_refresh_stop,
            _splash_on_reveal_paint=_splash_on_reveal_paint,
            _splash_reveal_clock=_splash_reveal_clock,
            _splash_underlay_bgr=_splash_underlay_bgr,
            _tk_grid_orig=_tk_grid_orig,
            _tk_pack_orig=_tk_pack_orig,
            _tk_place_orig=_tk_place_orig,
            _tmdb_retry_log_append=_tmdb_retry_log_append,
            _tmdb_retry_log_read_tail=_tmdb_retry_log_read_tail,
            _try_remove_splash_overlay=_try_remove_splash_overlay,
            _update_label_photo_from_bgr=_update_label_photo_from_bgr,
            _volume_lines=_volume_lines,
            _widget_accepts_typing=_widget_accepts_typing,
            alpha_blend_bgra_over_bgr=alpha_blend_bgra_over_bgr,
            audio_meter_face_enabled=audio_meter_face_enabled,
            blend_overlay_bgr=blend_overlay_bgr,
            bootstrap_done=bootstrap_done,
            build_info_cluster_design_patches=build_info_cluster_design_patches,
            build_stage_overlay_source_bgra=build_stage_overlay_source_bgra,
            cap=cap,
            clock_saver_composite_bgra=clock_saver_composite_bgra,
            compose_playback_volume_widget_line=compose_playback_volume_widget_line,
            content_host=content_host,
            denon_vol_cache=denon_vol_cache,
            get_grid_geometry=get_grid_geometry,
            latest_meter_cache_key=latest_meter_cache_key,
            latest_visualizer_cache_key=latest_visualizer_cache_key,
            lerp_bgr_red_monochrome=lerp_bgr_red_monochrome,
            load_pigeon_temp_logo_bgra=load_pigeon_temp_logo_bgra,
            location_toast_patch_bgra=location_toast_patch_bgra,
            metadata_has_playback_title=metadata_has_playback_title,
            paused_interval_ms=paused_interval_ms,
            playback_lower_gradient_bgra=playback_lower_gradient_bgra,
            post_splash_mono=post_splash_mono,
            prepare_default_poster_at_startup=prepare_default_poster_at_startup,
            program_audio_present=program_audio_present,
            program_audio_session_present=program_audio_session_present,
            receiver_overlay_state=receiver_overlay_state,
            receiver_standby_holder=receiver_standby_holder,
            rect_for_span_at_cell=rect_for_span_at_cell,
            rect_for_span_top_right_at_cell=rect_for_span_top_right_at_cell,
            render_ui_music_text_patch_bgra=render_ui_music_text_patch_bgra,
            render_ui_text_patch_bgra=render_ui_text_patch_bgra,
            resolve_metadata_tmdb_query=resolve_metadata_tmdb_query,
            resolve_view_one_variant=resolve_view_one_variant,
            root=root,
            scale_cover_center_crop=scale_cover_center_crop,
            scale_height_and_center_crop=scale_height_and_center_crop,
            shell=shell,
            startup_ph=startup_ph,
            sync_audio_meter_capture=sync_audio_meter_capture,
            toggle_audio_meter_face=toggle_audio_meter_face,
            variant_has_alternate=variant_has_alternate,
            variant_uses_full_path=variant_uses_full_path,
            view_circles_widget_holder=view_circles_widget_holder,
        )
        _boot_p01_state.run(ctx)
        _boot_p02_video_surface.run(ctx)
        _boot_p03_settings_scaffold.run(ctx)
        _boot_p04_settings_location.run(ctx)
        _boot_p05_devices_panel.run(ctx)
        _boot_p06_render_state.run(ctx)
        _boot_p07_widgets.run(ctx)
        _boot_p08_render_pipeline.run(ctx)
        _boot_p09_command_tmdb.run(ctx)
        _boot_p10_devices_logic.run(ctx)
        _boot_p11_settings_footer.run(ctx)
        _boot_p12_key_bindings.run(ctx)
        _boot_p13_hardware_inputs.run(ctx)
        _boot_p14_first_render.run(ctx)

    if _PIGEON_EXT:
        # Play the splash at full rate on a free UI thread. Heavy bootstrap starves ``after()``,
        # so it waits until the splash parks on its still logo-hold frame (148).
        _bootstrap_after_splash = _bind_deps(
            _core_splash._bootstrap_after_splash,
            _app_startup_mono=_app_startup_mono,
            _bootstrap_after_splash=_late(lambda: _bootstrap_after_splash, "_bootstrap_after_splash"),
            bootstrap=bootstrap,
            root=root,
            splash_anim_done=splash_anim_done,
            splash_bootstrap_go=splash_bootstrap_go,
        )

        root.after_idle(splash_tick)
        root.after_idle(_live_clock_until_compose)
        root.after_idle(_bootstrap_after_splash)
    else:
        root.after(1, bootstrap)
    try:
        root.mainloop()
    finally:
        _restore_desktop_chrome()
        if cap[0] is not None:
            cap[0].release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
