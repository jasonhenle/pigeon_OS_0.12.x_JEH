"""
Main settings menu state.

``MainSettingsState`` (focus, text-entry buffers, wifi / device-search / pairing
session fields), ``MainSettingsFocus``, ``SettingsTheme``, and the colour, focus-order
and location-name constants those types own. Holds no rendering code: the SVG
renderer in ``main_settings`` reads this state.

``pigeon.widgets.main_settings`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from pigeon.widgets.box_device_pairing import BoxPairingSession
from pigeon.widgets.box_device_search import (
    BoxDevicePanelState,
    ManualDeviceEntry,
    _BOX_DEVICE_ROW_COUNT,
    _BOX_SCAN_MAX_DURATION_S,
    box_devices_with_special_rows,
    device_row_from_pick,
)


_LOCATION_SLOT_DEFAULT_NAMES: tuple[str, ...] = ("ROOM 1", "ROOM 2", "ROOM 3")


_NEST_OR_ROOM_RE = re.compile(r"^(?:nest|room)\s*(\d+)$", re.IGNORECASE)


def location_name_is_default(name: str) -> bool:
    """True for placeholder room names (ROOM N / nest N / blank) — never renamed."""
    raw = str(name or "").strip()
    if not raw or raw.lower() in ("room", "nest"):
        return True
    return _NEST_OR_ROOM_RE.fullmatch(raw) is not None


def location_room_label(name: str, *, slot_index: int | None = None) -> str:
    """Show ROOM N for leftover nest/room placeholders; keep custom names."""
    raw = str(name or "").strip()
    match = _NEST_OR_ROOM_RE.fullmatch(raw)
    if match:
        return f"ROOM {int(match.group(1))}"
    if not raw or raw.lower() in ("room", "nest"):
        return f"ROOM {max(1, int(slot_index or 1))}"
    return raw


# --- Colors (settingInstructions_0.8.0) ---
COLOR_SELECTED = "#FFFFFF"


COLOR_DESELECTED = "#000013"


COLOR_UI_DEFAULT = "#4EA6F7"


COLOR_ACCENT_DEFAULT = "#FFFFFF"


COLOR_INACTIVE = "#404040"


# Primary nav ring (left/right). Network picker joins only when visible.
_PRIMARY_FOCUS_CANDIDATES: tuple[str, ...] = (
    "main_exit_button",
    "main_dual_location_button",
    "main_dual_network_button",
    "main_box1_button",
    "main_box2_button",
    "main_box3_button",
)


# Location switch: show centered search spinner only if reload takes this long.
_LOCATION_SWITCH_SPINNER_DELAY_S = 2.0


_WIFI_ONBOARDING_FOCUS: tuple[str, ...] = (
    "main_exit_button",
    "main_dual_location_button",
    "main_dual_network_button",
    "main_box1_button",
    "main_box2_button",
    "main_box3_button",
)


_PICKER_ROW_MINI_BUTTONS: tuple[str, ...] = (
    "main_network_picker_row1_mini_button",
    "main_network_picker_row2_mini_button",
    "main_network_picker_row3_mini_button",
)


_PICKER_ROW_TEXTS: tuple[str, ...] = (
    "main_network_picker_row1_text",
    "main_network_picker_row2_text",
    "main_network_picker_row3_text",
)


@dataclass(frozen=True)
class SettingsTheme:
    """User-themeable colors for main settings."""

    ui: str = COLOR_UI_DEFAULT
    selected: str = COLOR_SELECTED
    deselected: str = COLOR_DESELECTED
    inactive: str = COLOR_INACTIVE
    accent: str = COLOR_ACCENT_DEFAULT


class MainSettingsFocus(IntEnum):
    """Index into the live focus ring (see ``MainSettingsState.focus_ring``)."""

    FIRST = 0


@dataclass
class MainSettingsState:
    """Interactive state for the main settings SVG menu."""

    focus_index: int = 0
    theme: SettingsTheme = field(default_factory=SettingsTheme)
    wifi_level: int = 3  # stub 0–3
    location_name: str = "ROOM 1"
    selected_wifi_ssid: str = ""
    live_wifi_ssid: str = ""
    wifi_logged_out: bool = False
    pending_wifi_ssid: str = ""
    wifi_password: str = ""
    network_password_error: bool = False
    pending_network_password: str = ""
    wifi_connecting: bool = False
    wifi_connect_started_mono: float = 0.0
    network_name: str = ""  # legacy alias; kept for cache sig compatibility
    version_string: str = "0.8.0"
    exit_enabled: bool = True
    show_network_picker: bool = False
    network_picker_row: int = 0
    network_picker_scroll: int = 0
    network_picker_arrow: str = ""
    show_instructions: bool = False
    wifi_onboarding: bool = False
    wifi_scanning: bool = False
    wifi_scan_started_mono: float = 0.0
    wifi_scan_angle_deg: float = 0.0
    wifi_networks: tuple[str, ...] = ()
    show_box1_panel: bool = False
    show_box2_panel: bool = False
    show_box3_panel: bool = False
    show_location_picker: bool = False
    # Up to three (id, name) slots shown in box1–3 while picking/renaming.
    location_slots: tuple[tuple[str, str], ...] = ()
    renaming_location_id: str = ""
    renaming_location_slot: int = 0  # 1–3 while keyboard is open for a slot
    # True while applying a location change (devices / LEDs / runtime reload).
    location_switching: bool = False
    location_switch_started_mono: float = 0.0
    location_switch_angle_deg: float = 0.0
    box2_devices: BoxDevicePanelState = field(default_factory=BoxDevicePanelState)
    box3_devices: BoxDevicePanelState = field(default_factory=BoxDevicePanelState)
    box_pairing: BoxPairingSession | None = None
    manual_device_entry: ManualDeviceEntry | None = None
    # Title pinned from the SEARCH button (persisted by ``pigeon.manual_search``).
    manual_search_title: str = ""
    box2_ip_invalid: bool = False
    box3_ip_invalid: bool = False
    show_pigeon_settings: bool = False
    pigeon_focus_index: int = 0
    # Menu section1 of settings_pigeon shows: general | theme | clock.
    pigeon_view: str = "general"
    # Silent GitHub poll when opening settings_pigeon (badge without popup).
    pigeon_needs_update_prefetch: bool = False
    # settings_pigeon status lights: metadata / audio seen in the last 60 s,
    # and whether the host has a network route (wifi light).
    pigeon_metadata_ok: bool | None = None
    pigeon_audio_ok: bool = False
    pigeon_network_ok: bool = False
    # UI color the page falls back to when focus leaves the color row.
    ui_color_committed_key: str = ""
    # Timezone list over section1 (clock menu's TIME ZONE tile).
    tz_dropdown_open: bool = False
    tz_dropdown_index: int = 0
    # Live-games list over the page (general menu's SPORTS tile).
    sports_dropdown_open: bool = False
    sports_dropdown_index: int = 0
    # Sports page team list: league id while open ("" = closed), focused row.
    sports_team_league: str = ""
    sports_team_index: int = 0
    # NCAA lists: the letter picked on the A–Z grid ("" = showing the grid).
    sports_team_letter: str = ""
    show_preferences: bool = False
    # Metadata inspector ([4]): pages 0=player, 1=hdmi, 2=pigeon.
    show_metadata_debug: bool = False
    metadata_debug_page: int = 0
    # "zones" = navigation A; "widgets" = navigation B after a zone is activated.
    preferences_nav: str = "zones"
    preferences_focus_index: int = 0
    preferences_active_zone: int = 0  # 1–5 while in widgets nav; else 0
    preferences_zone_widgets: tuple[str, str, str, str, str] = (
        "tt_countdown_16x9",
        "",
        "volume",
        "cast_info",
        "status_bar",
    )
    # Live playback progress 0..1 for prefs circular now-playing; None → idle demo.
    preferences_np_progress: float | None = None
    # When True, prefs preview uses live poster / volume / cast / bar (not SVG demos).
    preferences_live_content: bool = False
    preferences_poster_bgra: object | None = None  # np.ndarray | None
    preferences_volume: str | None = None
    preferences_volume_fraction: float | None = None
    preferences_incoming: str | None = None
    preferences_config: str | None = None
    preferences_cast: tuple[tuple[str, str], ...] | None = None
    preferences_elapsed_text: str | None = None
    preferences_remaining_text: str | None = None
    preferences_service_name: str | None = None
    preferences_content_mode: str | None = None  # video | music
    preferences_song_title: str | None = None
    preferences_album_title: str | None = None
    preferences_artist_title: str | None = None
    preferences_tt_bgra: object | None = None  # np.ndarray | None
    # Legacy: settings box1 no longer shows TMDb title treatment.
    zone2_tt_bgra: object | None = None  # np.ndarray | None
    # Theme color keys (settings_pigeon color row sets ``ui``).
    ui_color_accent_key: str = "white"
    ui_color_ui_key: str = "blue"
    ui_color_button_key: str = "black"
    # settings_pigeon option toggles (12/24 h, °F/°C, auto/manual update, digital/analog).
    options_values: dict[str, object] = field(default_factory=dict)
    show_update_popup: bool = False
    update_popup_focus_index: int = 0
    update_available: bool = False
    update_checking: bool = False
    update_applying: bool = False
    update_progress: float = 0.0  # 0..1 while applying
    update_local_version: str = ""
    update_remote_version: str | None = None
    update_changelog: str = ""
    update_error: str | None = None
    update_github_branch: str | None = None
    # time.monotonic() when the current GitHub check began (status bar sweep).
    update_check_started_mono: float = 0.0
    # A check this visit found no newer build: version_update is pulled from
    # the ring and reads "latest version" until the screen is reopened.
    update_latest_confirmed: bool = False
    spinner_glyph_capture: bool = False
    # Focus ring rebuilt when panel visibility changes.
    focus_ring: tuple[str, ...] = field(default_factory=tuple)
    # Text-entry keyboard overlay (None = closed).
    keyboard: object | None = None

    @property
    def keyboard_open(self) -> bool:
        return self.keyboard is not None

    @property
    def wifi_configured(self) -> bool:
        return bool(self.displayed_wifi_ssid())

    def displayed_wifi_ssid(self) -> str:
        """SSID shown on settings_main: live radio, else saved location wifi."""
        if self.wifi_logged_out:
            return str(self.selected_wifi_ssid or "").strip()
        return str(self.live_wifi_ssid or self.selected_wifi_ssid or "").strip()

    def refresh_network_ssid(self) -> None:
        """Reload saved location wifi and the OS association for the dual bar."""
        try:
            from pigeon.app_state import read_location_wifi

            wifi = read_location_wifi()
        except Exception:
            wifi = None
        loc_ssid = ""
        if wifi is not None:
            loc_ssid = str(wifi.get("ssid") or "").strip()
            if loc_ssid:
                self.wifi_logged_out = False
                if not str(self.selected_wifi_ssid or "").strip():
                    self.selected_wifi_ssid = loc_ssid
                    self.wifi_password = str(wifi.get("password") or "")
        if self.wifi_logged_out:
            self.live_wifi_ssid = ""
            return
        try:
            from pigeon.wifi_scan import current_connected_ssid

            self.live_wifi_ssid = str(current_connected_ssid() or "").strip()
        except Exception:
            self.live_wifi_ssid = ""

    def reload_location_wifi(self) -> None:
        """Replace in-memory wifi with the current location record, then probe live."""
        self.wifi_logged_out = False
        try:
            from pigeon.app_state import read_location_wifi

            wifi = read_location_wifi()
        except Exception:
            wifi = None
        if wifi is not None:
            self.selected_wifi_ssid = str(wifi.get("ssid") or "").strip()
            self.wifi_password = str(wifi.get("password") or "")
        else:
            self.selected_wifi_ssid = ""
            self.wifi_password = ""
        self.refresh_network_ssid()

    def needs_wifi_setup(self) -> bool:
        """True until the user has chosen a WiFi network (SSID)."""
        return not self.wifi_configured

    def _box_panel(self, box_num: int) -> BoxDevicePanelState:
        return self.box2_devices if box_num == 2 else self.box3_devices

    def box_has_saved_device(self, box_num: int) -> bool:
        return self.saved_box_device(box_num) is not None

    def saved_box_device(self, box_num: int) -> tuple[str, str] | None:
        """Return the currently paired device for a box column, if any."""
        panel = self._box_panel(box_num)
        if panel.picked is not None:
            return panel.picked
        try:
            from pigeon.app_state import read_saved_av_receiver, read_saved_streaming_device

            row = read_saved_streaming_device() if box_num == 2 else read_saved_av_receiver()
            if not row:
                return None
            name = str(row.get("name") or row.get("label") or "Device").strip()
            ip = str(row.get("address") or "").strip()
            if name or ip:
                return (name or ip, ip or name)
        except Exception:
            pass
        return None

    def restore_box_device_panel(self, box_num: int) -> None:
        """Leave search/results and return the column to its last idle/device state."""
        panel = self._box_panel(box_num)
        saved = self.saved_box_device(box_num)
        panel.active = False
        panel.phase = "idle"
        panel.scanning = False
        panel.scan_angle_deg = 0.0
        panel.devices = ()
        panel.device_rows = ()
        panel.scroll = 0
        panel.row = 0
        panel.arrow = ""
        panel.picked = saved
        if box_num == 2:
            self.show_box2_panel = False
        elif box_num == 3:
            self.show_box3_panel = False
        self.ensure_focus_ring()
        btn = f"main_box{box_num}_button"
        if btn in self.focus_ring:
            self.focus_index = self.focus_ring.index(btn)

    def device_row_matches_saved(self, box_num: int, row: dict[str, str]) -> bool:
        saved = self.saved_box_device(box_num)
        if saved is None:
            return False
        saved_name, saved_ip = saved
        row_name = str(row.get("name") or row.get("label") or "").strip()
        row_ip = str(row.get("address") or "").strip()
        if row_ip and saved_ip and row_ip == saved_ip:
            return True
        return bool(row_name) and row_name.lower() == saved_name.lower() and row_ip == saved_ip

    def load_saved_box_devices(self) -> None:
        """Sync both box columns to the saved devices of the *current* room.

        A box with no saved device is cleared, so switching to a room that has no
        player or receiver does not keep showing the previous room's device.
        """
        try:
            from pigeon.app_state import read_saved_av_receiver, read_saved_streaming_device

            stream = read_saved_streaming_device()
            avr = read_saved_av_receiver()
        except Exception:
            return  # unreadable state: leave what is shown untouched
        for box_num, row in ((2, stream), (3, avr)):
            panel = self._box_panel(box_num)
            if row:
                name = str(row.get("name") or row.get("label") or "Device").strip()
                ip = str(row.get("address") or "").strip()
                panel.picked = (name, ip)
            else:
                panel.picked = None
            if box_num == 2:
                self.box2_ip_invalid = False
            else:
                self.box3_ip_invalid = False

    def reset_box_device_panel(self, box_num: int) -> None:
        panel = self._box_panel(box_num)
        panel.active = False
        panel.phase = "idle"
        panel.scanning = False
        panel.scan_angle_deg = 0.0
        panel.devices = ()
        panel.device_rows = ()
        panel.scroll = 0
        panel.row = 0
        panel.arrow = ""
        if box_num == 2:
            self.show_box2_panel = False
        elif box_num == 3:
            self.show_box3_panel = False

    def start_manual_device_entry(self, box_num: int) -> None:
        panel = self._box_panel(box_num)
        panel.active = False
        panel.phase = "idle"
        panel.scanning = False
        panel.devices = ()
        panel.device_rows = ()
        panel.scroll = 0
        panel.row = 0
        self.manual_device_entry = ManualDeviceEntry(box_num=int(box_num), step="ip")
        if box_num == 2:
            self.show_box2_panel = False
        elif box_num == 3:
            self.show_box3_panel = False

    def finish_manual_device_entry(self, *, name: str, ip: str, ip_valid: bool) -> None:
        entry = self.manual_device_entry
        if entry is None:
            return
        box_num = int(entry.box_num)
        panel = self._box_panel(box_num)
        clean_name = str(name or "Device").strip() or "Device"
        clean_ip = str(ip or "").strip()
        panel.picked = (clean_name, clean_ip)
        panel.active = False
        panel.phase = "idle"
        panel.scanning = False
        if box_num == 2:
            self.box2_ip_invalid = not ip_valid
            self.show_box2_panel = True
        elif box_num == 3:
            self.box3_ip_invalid = not ip_valid
            self.show_box3_panel = True
        self.manual_device_entry = None
        try:
            from pigeon.app_state import write_saved_av_receiver, write_saved_streaming_device

            row = {"name": clean_name, "label": clean_name, "address": clean_ip}
            if box_num == 2:
                write_saved_streaming_device(row)
            elif box_num == 3:
                write_saved_av_receiver(row)
        except Exception:
            pass
        self.ensure_focus_ring()
        btn = f"main_box{box_num}_button"
        if btn in self.focus_ring:
            self.focus_index = self.focus_ring.index(btn)

    def box_device_results_locked(self) -> int | None:
        for box in (2, 3):
            if self._box_panel(box).results_locked:
                return box
        return None

    def refresh_location_slots(self) -> None:
        """Load (and pad to three) location slots for the dual-location picker."""
        from pigeon.app_state import add_empty_location_v2, read_all_locations_v2

        locs = read_all_locations_v2()
        while len(locs) < 3:
            add_empty_location_v2(_LOCATION_SLOT_DEFAULT_NAMES[len(locs)])
            locs = read_all_locations_v2()
        slots: list[tuple[str, str]] = []
        for i, loc in enumerate(locs[:3]):
            lid = str(loc.get("id") or "").strip()
            raw = str(loc.get("name") or "").strip() or _LOCATION_SLOT_DEFAULT_NAMES[i]
            name = location_room_label(raw, slot_index=i + 1)
            if lid:
                slots.append((lid, name))
        self.location_slots = tuple(slots)

    def location_slot(self, box_num: int) -> tuple[str, str] | None:
        idx = int(box_num) - 1
        if 0 <= idx < len(self.location_slots):
            return self.location_slots[idx]
        return None

    def enter_location_picker(self) -> None:
        self.show_network_picker = False
        self.close_update_popup()
        self.close_preferences()
        self.show_pigeon_settings = False
        self._set_mono_preview_off(False)
        self.show_location_picker = True
        self.renaming_location_id = ""
        self.renaming_location_slot = 0
        self.show_box1_panel = False
        self.show_box2_panel = False
        self.show_box3_panel = False
        for box_num in (2, 3):
            panel = self._box_panel(box_num)
            panel.active = False
            panel.scanning = False
            if panel.phase == "scanning":
                panel.phase = "idle"
        self.refresh_location_slots()
        self.ensure_focus_ring()
        current_lid = ""
        try:
            from pigeon.app_state import read_current_location_id

            current_lid = str(read_current_location_id() or "").strip()
        except Exception:
            current_lid = ""
        box_btn = "main_box1_button"
        for i, (sid, _name) in enumerate(self.location_slots):
            if current_lid and str(sid) == current_lid:
                box_btn = ("main_box1_button", "main_box2_button", "main_box3_button")[i]
                break
        if box_btn in self.focus_ring:
            self.focus_index = self.focus_ring.index(box_btn)
        elif "main_dual_location_button" in self.focus_ring:
            self.focus_index = self.focus_ring.index("main_dual_location_button")

    def exit_location_picker(self) -> None:
        self.show_location_picker = False
        self.renaming_location_id = ""
        self.renaming_location_slot = 0
        self.ensure_focus_ring()
        if "main_dual_location_button" in self.focus_ring:
            self.focus_index = self.focus_ring.index("main_dual_location_button")

    def begin_rename_location_slot(self, box_num: int) -> bool:
        slot = self.location_slot(box_num)
        if slot is None:
            self.refresh_location_slots()
            slot = self.location_slot(box_num)
        if slot is None:
            return False
        lid, name = slot
        self.renaming_location_id = lid
        self.renaming_location_slot = int(box_num)
        self.location_name = location_room_label(name, slot_index=box_num)
        return True

    def select_location_slot(self, box_num: int) -> bool:
        """Make the room in ``box_num`` the active location (dual-location picker)."""
        if self.location_switching:
            return False
        if not self.location_slots:
            try:
                self.refresh_location_slots()
            except Exception:
                pass
        slot = self.location_slot(box_num)
        if slot is None:
            try:
                self.refresh_location_slots()
            except Exception:
                pass
            slot = self.location_slot(box_num)
        if slot is None:
            return False
        lid, name = slot
        try:
            from pigeon.app_state import set_current_location_id

            if lid:
                set_current_location_id(str(lid))
        except Exception:
            pass
        self.location_name = location_room_label(name, slot_index=box_num) or self.location_name
        self.renaming_location_id = ""
        self.renaming_location_slot = 0
        try:
            self.load_saved_box_devices()
        except Exception:
            pass
        return True

    def begin_location_switching(self) -> None:
        """Mark a location reload in progress (spinner appears after a short delay)."""
        self.location_switching = True
        self.location_switch_started_mono = time.monotonic()
        self.location_switch_angle_deg = 0.0

    def finish_location_switching(self) -> None:
        self.location_switching = False
        self.location_switch_angle_deg = 0.0

    def location_switch_spinner_visible(self) -> bool:
        if not self.location_switching:
            return False
        return (time.monotonic() - float(self.location_switch_started_mono)) >= float(
            _LOCATION_SWITCH_SPINNER_DELAY_S
        )

    def begin_rename_current_location(self) -> bool:
        """Prepare rename keyboard for the currently active location."""
        try:
            from pigeon.app_state import read_current_location_id, read_current_location_name

            lid = str(read_current_location_id() or "").strip()
            name = str(read_current_location_name() or "").strip()
        except Exception:
            lid, name = "", ""
        if not lid:
            # Fall back to slot 1 if current id is missing.
            slot = self.location_slot(1)
            if slot is None:
                self.refresh_location_slots()
                slot = self.location_slot(1)
            if slot is None:
                return False
            lid, name = slot
        self.renaming_location_id = lid
        self.renaming_location_slot = 0
        for box_num in (1, 2, 3):
            slot = self.location_slot(box_num)
            if slot is not None and str(slot[0]) == str(lid):
                self.renaming_location_slot = int(box_num)
                if not name:
                    name = str(slot[1] or "")
                break
        self.location_name = location_room_label(
            name, slot_index=self.renaming_location_slot or 1
        )
        return True

    def search_bar_visible(self) -> bool:
        """SEARCH bar shares the columns' rows, so it yields to any list view."""
        if not self.wifi_configured or self.wifi_connecting or self.wifi_scanning:
            return False
        if self.show_location_picker or self.show_network_picker:
            return False
        if self.manual_device_entry is not None:
            return False
        for box_num in (2, 3):
            panel = self._box_panel(box_num)
            if (
                panel.scanning
                or panel.results_locked
                or str(getattr(panel, "phase", "") or "") in ("scanning", "results")
                or bool(getattr(panel, "active", False))
            ):
                return False
        return True

    def ensure_focus_ring(self) -> None:
        locked_box = self.box_device_results_locked()
        if locked_box is not None:
            self.focus_ring = (f"main_box{locked_box}_device_results",)
            self.focus_index = 0
            return
        if not self.wifi_configured and self.show_network_picker:
            self.focus_ring = ("main_network_picker_button",)
            self.focus_index = 0
            return
        if not self.wifi_configured:
            ring = list(_WIFI_ONBOARDING_FOCUS)
            self.focus_ring = tuple(ring)
        else:
            ring = list(_PRIMARY_FOCUS_CANDIDATES)
            if self.show_network_picker:
                # Insert after dual network when present.
                if "main_dual_network_button" in ring:
                    i = ring.index("main_dual_network_button") + 1
                    ring.insert(i, "main_network_picker_button")
                else:
                    ring.append("main_network_picker_button")
            if self.search_bar_visible():
                ring.append("main_search_button")
                if self.manual_search_title:
                    ring.append("main_search_clear_button")
            self.focus_ring = tuple(ring)
        if not self.exit_enabled:
            self.focus_ring = tuple(
                fid for fid in self.focus_ring if fid != "main_exit_button"
            )
        if not self.focus_ring:
            self.focus_ring = (
                ("main_exit_button",)
                if self.exit_enabled
                else ("main_dual_location_button",)
            )
        self.focus_index = int(self.focus_index) % len(self.focus_ring)

    def focus_main_button(self, logical_id: str) -> bool:
        """Put main-page focus on ``logical_id`` when it is in the current ring."""
        self.ensure_focus_ring()
        if logical_id not in self.focus_ring:
            return False
        self.focus_index = self.focus_ring.index(logical_id)
        return True

    @property
    def focused_id(self) -> str:
        self.ensure_focus_ring()
        return self.focus_ring[int(self.focus_index) % len(self.focus_ring)]

    @property
    def pigeon_focused_id(self) -> str:
        from pigeon.widgets.pigeon_settings import pigeon_focus_ring

        ring = pigeon_focus_ring(self.pigeon_view)
        return ring[int(self.pigeon_focus_index) % len(ring)]

    def set_pigeon_view(self, view: str, *, focus: str = "") -> None:
        """Load a menu into section1; ``focus`` is the id to keep focus on."""
        from pigeon.widgets.pigeon_settings import normalize_view, pigeon_focus_ring

        self.pigeon_view = normalize_view(view)
        ring = pigeon_focus_ring(self.pigeon_view)
        self.pigeon_focus_index = ring.index(focus) if focus in ring else 0
        self.sync_pigeon_color_preview()

    def enter_pigeon_settings(self) -> None:
        from pigeon.widgets.options_settings import load_options_into_state
        from pigeon.widgets.pigeon_settings import pigeon_focus_ring
        from pigeon.widgets.ui_color_settings import load_persisted_theme_into_state

        self.show_pigeon_settings = True
        self.pigeon_view = "general"
        self.show_box1_panel = False
        self.close_update_popup()
        self.close_preferences()
        self.close_tz_dropdown()
        self.close_sports_dropdown()
        self.close_sports_teams()
        self.close_metadata_debug()
        load_persisted_theme_into_state(self)
        self.ui_color_committed_key = str(self.ui_color_ui_key or "blue")
        load_options_into_state(self)
        try:
            self.refresh_network_ssid()
        except Exception:
            pass
        self.refresh_pigeon_status()
        try:
            from pigeon.pigeon_locale import ensure_location_detected

            ensure_location_detected()
        except Exception:
            pass
        # Land on the first tile; EXIT stays one step back.
        self.pigeon_focus_index = 1 if len(pigeon_focus_ring(self.pigeon_view)) > 1 else 0
        # Prefetch update availability so the badge is ready without opening the popup.
        self.pigeon_needs_update_prefetch = True

    def refresh_pigeon_status(self) -> None:
        """Network / metadata / audio lights."""
        try:
            from pigeon.source_status import apply_source_status_to_settings_state

            apply_source_status_to_settings_state(self)
        except Exception:
            pass

    def open_metadata_debug(self) -> None:
        """Open the metadata inspector ([0]) on its first page (player)."""
        if not self.show_pigeon_settings:
            self.enter_pigeon_settings()
        self.close_update_popup()
        self.close_preferences()
        self.close_tz_dropdown()
        self.close_sports_dropdown()
        self.close_sports_teams()
        self.show_metadata_debug = True
        self.metadata_debug_page = 0
        try:
            from pigeon.hdmi_capture import probe_hdmi_presence

            probe_hdmi_presence(force=True)
        except Exception:
            pass

    def close_metadata_debug(self) -> None:
        self.show_metadata_debug = False
        self.metadata_debug_page = 0

    def navigate_metadata_debug(self, *, forward: bool = True) -> None:
        """Cycle player → hdmi → pigeon, wrapping in both directions."""
        step = 1 if forward else -1
        self.metadata_debug_page = (int(self.metadata_debug_page) + step) % 3

    def exit_pigeon_settings(self) -> None:
        self.close_update_popup()
        self.close_preferences()
        self.close_tz_dropdown()
        self.close_sports_dropdown()
        self.close_sports_teams()
        self.close_metadata_debug()
        self._restore_committed_ui_color()
        self.show_pigeon_settings = False
        self._set_mono_preview_off(False)
        self.pigeon_view = "general"
        self.pigeon_needs_update_prefetch = False
        self.ensure_focus_ring()
        if "main_box1_button" in self.focus_ring:
            self.focus_index = self.focus_ring.index("main_box1_button")

    def open_preferences(self) -> None:
        """Open the now-playing zone widget selector (prefs / settings)."""
        from pigeon.widgets.preferences_settings import (
            preferences_zone_focus_ring,
            read_now_playing_zone_widgets,
        )

        self.show_preferences = True
        self.preferences_nav = "zones"
        self.preferences_active_zone = 0
        self.preferences_zone_widgets = read_now_playing_zone_widgets()
        ring = preferences_zone_focus_ring()
        # Land on zone1 — first editable target.
        self.preferences_focus_index = ring.index("zone1") if "zone1" in ring else 0

    def close_preferences(self) -> None:
        self.show_preferences = False
        self.preferences_nav = "zones"
        self.preferences_active_zone = 0
        self.preferences_focus_index = 0

    def _restore_committed_ui_color(self) -> None:
        """Drop a live color preview back to the committed theme."""
        committed = str(self.ui_color_committed_key or "")
        if not committed or committed == str(self.ui_color_ui_key or ""):
            return
        from pigeon.widgets.ui_color_settings import apply_color_keys_to_state

        apply_color_keys_to_state(
            self,
            {
                "accent": self.ui_color_accent_key,
                "ui": committed,
                "button": self.ui_color_button_key,
            },
            persist=False,
        )

    @staticmethod
    def _set_mono_preview_off(off: bool) -> None:
        from pigeon.widgets.options_settings import set_mono_preview_off

        set_mono_preview_off(off)

    def sync_pigeon_color_preview(self) -> None:
        """Color row: focused swatch themes the UI live; elsewhere the committed one."""
        from pigeon.widgets.pigeon_settings import color_key_for_focus
        from pigeon.widgets.ui_color_settings import apply_color_keys_to_state

        preview = color_key_for_focus(self.pigeon_focused_id)
        # In dark mode a focused color tile shows as that color, not dimmed.
        self._set_mono_preview_off(self.show_pigeon_settings and preview is not None)
        if preview is None:
            self._restore_committed_ui_color()
            return
        if preview == str(self.ui_color_ui_key or ""):
            return
        apply_color_keys_to_state(
            self,
            {
                "accent": self.ui_color_accent_key,
                "ui": preview,
                "button": self.ui_color_button_key,
            },
            persist=False,
        )

    def commit_pigeon_color(self, key: str) -> None:
        from pigeon.widgets.ui_color_settings import apply_color_keys_to_state

        apply_color_keys_to_state(
            self,
            {
                "accent": self.ui_color_accent_key,
                "ui": key,
                "button": self.ui_color_button_key,
            },
            persist=True,
        )
        self.ui_color_committed_key = str(self.ui_color_ui_key or key)

    def open_sports_dropdown(self) -> None:
        from pigeon.sports_scores import refresh_events

        refresh_events()
        self.sports_dropdown_open = True
        self.sports_dropdown_index = 0

    def close_sports_dropdown(self) -> None:
        self.sports_dropdown_open = False
        self.sports_dropdown_index = 0

    def navigate_sports_dropdown(self, *, forward: bool = True) -> None:
        from pigeon.widgets.pigeon_settings import sports_dropdown_entries

        n = len(sports_dropdown_entries())
        step = 1 if forward else -1
        self.sports_dropdown_index = (int(self.sports_dropdown_index) + step) % max(1, n)

    def activate_sports_dropdown(self) -> str:
        """Pick the focused game (leaves settings for the board), or turn it off.
        Message rows (loading / no games) just close the list."""
        from pigeon.sports_scores import SportsEvent, clear_selection, select_event
        from pigeon.widgets.pigeon_settings import SPORTS_OFF, sports_dropdown_entries

        entries = sports_dropdown_entries()
        payload = entries[int(self.sports_dropdown_index) % len(entries)][2]
        self.close_sports_dropdown()
        if payload == SPORTS_OFF:
            clear_selection()
            return "sports_off"
        if isinstance(payload, SportsEvent):
            select_event(payload)
            self.exit_pigeon_settings()
            return "exit" if self.exit_enabled else "pigeon_settings_back"
        return "sports_dropdown_close"

    def open_sports_page(self) -> None:
        from pigeon.sports_teams import FOLLOW_LEAGUES
        from pigeon.widgets.sports_settings import SPORTS_VIEW, league_focus_id

        self.close_sports_teams()
        self.set_pigeon_view(SPORTS_VIEW, focus=league_focus_id(FOLLOW_LEAGUES[0].league_id))
        # Warm LIVE GAMES while the page is up.
        try:
            from pigeon.sports_scores import refresh_events

            refresh_events()
        except Exception:
            pass

    def close_sports_page(self) -> None:
        self.close_sports_teams()
        self.close_sports_dropdown()
        self.set_pigeon_view("general", focus="sports")

    def open_sports_teams(self, league_id: str) -> None:
        self.sports_team_league = str(league_id)
        self.sports_team_letter = ""
        self.sports_team_index = 0

    def close_sports_teams(self) -> None:
        self.sports_team_league = ""
        self.sports_team_letter = ""
        self.sports_team_index = 0

    def navigate_sports_teams(self, *, forward: bool = True) -> None:
        from pigeon.widgets.sports_settings import current_entries

        n = len(current_entries(self))
        step = 1 if forward else -1
        self.sports_team_index = (int(self.sports_team_index) + step) % max(1, n)

    def activate_sports_teams(self) -> str:
        """BACK steps out (teams → letter grid → page); a letter opens its
        teams; a team is followed / unfollowed in place."""
        from pigeon.sports_follow import toggle_follow
        from pigeon.widgets.sports_settings import (
            LETTER_PREFIX,
            TEAM_BACK,
            current_entries,
            letter_entries,
            uses_letters,
        )

        league_id = self.sports_team_league
        entries = current_entries(self)
        payload = entries[int(self.sports_team_index) % len(entries)][0]
        if payload.startswith(LETTER_PREFIX):
            self.sports_team_letter = payload[len(LETTER_PREFIX) :]
            self.sports_team_index = 0
            return f"sports_letter:{self.sports_team_letter}"
        if payload == TEAM_BACK:
            letter = self.sports_team_letter
            if letter and uses_letters(league_id):
                self.sports_team_letter = ""
                keys = [p for p, _label in letter_entries(league_id)]
                want = f"{LETTER_PREFIX}{letter}"
                self.sports_team_index = keys.index(want) if want in keys else 0
                return "sports_letters_back"
            self.close_sports_teams()
            return "sports_teams_back"
        on = toggle_follow(league_id, payload)
        return f"sports_follow:{league_id}:{payload}:{'on' if on else 'off'}"

    def open_tz_dropdown(self) -> None:
        from pigeon.pigeon_locale import current_timezone_choice_index

        self.tz_dropdown_open = True
        self.tz_dropdown_index = int(current_timezone_choice_index())

    def close_tz_dropdown(self) -> None:
        self.tz_dropdown_open = False
        self.tz_dropdown_index = 0

    def navigate_tz_dropdown(self, *, forward: bool = True) -> None:
        from pigeon.pigeon_locale import timezone_choices

        n = len(timezone_choices())
        if n <= 0:
            return
        step = 1 if forward else -1
        self.tz_dropdown_index = (int(self.tz_dropdown_index) + step) % n

    def activate_tz_dropdown(self) -> str:
        from pigeon.pigeon_locale import set_timezone_manual, timezone_choices

        choices = timezone_choices()
        name = choices[int(self.tz_dropdown_index) % len(choices)] if choices else ""
        if name:
            set_timezone_manual(name)
        self.close_tz_dropdown()
        return f"timezone_set:{name}"

    @property
    def preferences_focused_id(self) -> str:
        from pigeon.widgets.preferences_settings import (
            preferences_widget_focus_ring,
            preferences_zone_focus_ring,
        )

        if str(self.preferences_nav or "") == "widgets":
            ring = preferences_widget_focus_ring(int(self.preferences_active_zone))
        else:
            ring = preferences_zone_focus_ring()
        if not ring:
            return "exit"
        return ring[int(self.preferences_focus_index) % len(ring)]

    def navigate_preferences(self, *, forward: bool = True) -> None:
        from pigeon.widgets.preferences_settings import (
            preferences_widget_focus_ring,
            preferences_zone_focus_ring,
            write_now_playing_zone_widgets,
        )

        step = 1 if forward else -1
        if str(self.preferences_nav or "") == "widgets":
            zone = int(self.preferences_active_zone)
            ring = preferences_widget_focus_ring(zone)
            if not ring:
                return
            self.preferences_focus_index = (
                int(self.preferences_focus_index) + step
            ) % len(ring)
            focused = ring[self.preferences_focus_index]
            # Live-assign the focused widget (skip BACK). Preview only — persist on activate.
            if focused != "exit" and 1 <= zone <= 5:
                widgets = list(self.preferences_zone_widgets)
                widgets[zone - 1] = focused
                self.preferences_zone_widgets = (
                    widgets[0],
                    widgets[1],
                    widgets[2],
                    widgets[3],
                    widgets[4],
                )
                write_now_playing_zone_widgets(
                    self.preferences_zone_widgets, persist=False
                )
            return
        ring = preferences_zone_focus_ring()
        if not ring:
            return
        self.preferences_focus_index = (
            int(self.preferences_focus_index) + step
        ) % len(ring)

    def activate_preferences(self) -> str:
        """Handle activate while the preferences selector is open."""
        from pigeon.widgets.preferences_settings import (
            preferences_widget_focus_ring,
            write_now_playing_zone_widgets,
        )

        focused = self.preferences_focused_id
        if str(self.preferences_nav or "") != "widgets":
            if focused == "exit":
                self.close_preferences()
                return "preferences_exit"
            if focused.startswith("zone"):
                try:
                    zone = int(focused.replace("zone", ""))
                except ValueError:
                    return "preferences_noop"
                self.preferences_nav = "widgets"
                self.preferences_active_zone = zone
                ring = preferences_widget_focus_ring(zone)
                current = (
                    self.preferences_zone_widgets[zone - 1]
                    if 1 <= zone <= 5
                    else "exit"
                )
                if current in ring:
                    self.preferences_focus_index = ring.index(current)
                else:
                    self.preferences_focus_index = 0
                return f"preferences_zone:{zone}"
            return "preferences_noop"

        # Widget navigation — BACK always returns to pigeon settings.
        if focused == "exit":
            write_now_playing_zone_widgets(self.preferences_zone_widgets)
            self.close_preferences()
            return "preferences_exit"
        # Confirm focused widget, persist, and return to zone navigation.
        zone = int(self.preferences_active_zone)
        if 1 <= zone <= 5 and focused and focused != "exit":
            widgets = list(self.preferences_zone_widgets)
            widgets[zone - 1] = focused
            self.preferences_zone_widgets = (
                widgets[0],
                widgets[1],
                widgets[2],
                widgets[3],
                widgets[4],
            )
        write_now_playing_zone_widgets(self.preferences_zone_widgets)
        self.preferences_nav = "zones"
        self.preferences_active_zone = 0
        from pigeon.widgets.preferences_settings import preferences_zone_focus_ring

        zring = preferences_zone_focus_ring()
        zid = f"zone{zone}"
        self.preferences_focus_index = zring.index(zid) if zid in zring else 0
        return f"preferences_widget:{focused}"

    def open_update_popup(self) -> None:
        """Show the update screen.

        Nothing known yet: start a GitHub check (the icon click *is* the
        check). An update already found by the badge prefetch / background
        poll: no re-check — the screen opens with an empty bar so the next
        click confirms installing that update.
        """
        self.show_update_popup = True
        self.update_applying = False
        self.update_progress = 0.0
        self.update_local_version = self.version_string
        self.update_latest_confirmed = False
        if self.update_available and not self.update_error:
            self.show_known_update_for_install()
        else:
            self.begin_update_check()
        self.set_update_popup_focus("update")

    def show_known_update_for_install(self) -> None:
        """Ready to install the update already found: no check, empty bar."""
        from pigeon.widgets.update_popup import DEFAULT_CHANGELOG

        self.update_checking = False
        self.update_error = None
        self.update_progress = 0.0
        self.update_changelog = DEFAULT_CHANGELOG

    def begin_update_check(self) -> None:
        self.update_checking = True
        self.update_error = None
        self.update_check_started_mono = time.monotonic()
        self.update_changelog = "Checking GitHub for updates…"

    def close_update_popup(self) -> None:
        # Keep update_available / remote version: they seed the next open.
        self.show_update_popup = False
        self.update_checking = False
        self.update_applying = False
        self.update_progress = 0.0
        self.update_popup_focus_index = 0

    def _update_popup_ring(self) -> tuple[str, ...]:
        from pigeon.widgets.update_popup import update_popup_focus_ring

        return update_popup_focus_ring(
            update_available=bool(self.update_available),
            checking=bool(self.update_checking),
            applying=bool(self.update_applying),
            latest=bool(self.update_latest_confirmed),
        )

    def set_update_popup_focus(self, choice: str) -> None:
        """Land on ``choice`` (back / current / update) in the current ring."""
        ring = self._update_popup_ring()
        if choice in ring:
            self.update_popup_focus_index = ring.index(choice)
        elif ring:
            self.update_popup_focus_index = len(ring) - 1

    def navigate_update_popup(self, *, forward: bool = True) -> None:
        ring = self._update_popup_ring()
        if not ring:
            return
        step = 1 if forward else -1
        self.update_popup_focus_index = (int(self.update_popup_focus_index) + step) % len(ring)

    @property
    def update_popup_focused_choice(self) -> str:
        ring = self._update_popup_ring()
        if not ring:
            return "update"
        return ring[int(self.update_popup_focus_index) % len(ring)]

    def navigate_pigeon(self, *, forward: bool = True) -> None:
        from pigeon.widgets.pigeon_settings import pigeon_focus_ring

        if self.show_metadata_debug:
            self.navigate_metadata_debug(forward=forward)
            return
        if self.tz_dropdown_open:
            self.navigate_tz_dropdown(forward=forward)
            return
        if self.sports_dropdown_open:
            self.navigate_sports_dropdown(forward=forward)
            return
        if self.sports_team_league:
            self.navigate_sports_teams(forward=forward)
            return
        if self.show_preferences:
            self.navigate_preferences(forward=forward)
            return
        if self.show_update_popup:
            self.navigate_update_popup(forward=forward)
            return
        ring = pigeon_focus_ring(self.pigeon_view)
        step = 1 if forward else -1
        self.pigeon_focus_index = (int(self.pigeon_focus_index) + step) % len(ring)
        self.sync_pigeon_color_preview()

    def navigate_picker_row(self, *, forward: bool) -> bool:
        """Move selection among picker rows; wraps at the ends of the full list."""
        if not self.show_network_picker:
            return False
        n = len(self.wifi_networks)
        if n <= 0:
            return False
        visible = len(_PICKER_ROW_TEXTS)
        step = 1 if forward else -1
        cur = max(0, min(int(self.network_picker_absolute_row), n - 1))
        abs_row = (cur + step) % n
        max_scroll = max(0, n - visible)
        scroll = int(self.network_picker_scroll)
        if abs_row < scroll:
            scroll = abs_row
        elif abs_row >= scroll + visible:
            scroll = abs_row - visible + 1
        scroll = max(0, min(scroll, max_scroll))
        self.network_picker_scroll = scroll
        self.network_picker_row = abs_row - scroll
        self.network_picker_arrow = ""
        return True

    def navigate_picker_scroll(self, *, up: bool) -> bool:
        """Deprecated: vertical picker scroll disabled (left/right only)."""
        return False

    @property
    def network_picker_can_scroll_up(self) -> bool:
        return int(self.network_picker_scroll) > 0

    @property
    def network_picker_can_scroll_down(self) -> bool:
        n = len(self.wifi_networks)
        max_scroll = max(0, n - len(_PICKER_ROW_TEXTS))
        return int(self.network_picker_scroll) < max_scroll

    @property
    def network_picker_absolute_row(self) -> int:
        return int(self.network_picker_scroll) + int(self.network_picker_row)

    def start_box_device_scan(
        self, box_num: int, *, duration_s: float | None = None
    ) -> None:
        panel = self._box_panel(box_num)
        panel.active = True
        panel.phase = "scanning"
        panel.scanning = True
        panel.scan_started_mono = time.monotonic()
        panel.scan_angle_deg = 0.0
        panel.scan_duration_s = (
            float(duration_s)
            if duration_s is not None and duration_s > 0.0
            else _BOX_SCAN_MAX_DURATION_S
        )
        panel.devices = ()
        panel.device_rows = ()
        panel.scroll = 0
        panel.row = 0
        panel.arrow = ""
        # Keep panel.picked so abort/cancel can restore the prior device view.
        if box_num == 2:
            self.show_box2_panel = True
        elif box_num == 3:
            self.show_box3_panel = True

    def abort_box_device_scan_ui(self, box_num: int) -> bool:
        """Instantly dismiss the scanning UI and restore the prior idle/device screen."""
        panel = self._box_panel(box_num)
        if not panel.scanning:
            return False
        self.restore_box_device_panel(box_num)
        return True

    def complete_box_device_scan(
        self,
        box_num: int,
        scan_result: tuple[tuple[tuple[str, str], ...], tuple[dict[str, str], ...]] | None = None,
    ) -> None:
        panel = self._box_panel(box_num)
        panel.scanning = False
        panel.phase = "results"
        if scan_result and len(scan_result) == 2:
            devices, device_rows = scan_result
            saved = self.saved_box_device(box_num)
            if saved and devices:
                dev_list = list(devices)
                row_list = list(device_rows)
                match_idx: int | None = None
                saved_name, saved_ip = saved
                for i, (name, ip) in enumerate(dev_list):
                    if ip == saved_ip or (
                        name.lower() == saved_name.lower() and ip == saved_ip
                    ):
                        match_idx = i
                        break
                if match_idx is not None and match_idx > 0:
                    dev_item = dev_list.pop(match_idx)
                    dev_list.insert(0, dev_item)
                    if match_idx < len(row_list):
                        row_item = row_list.pop(match_idx)
                        row_list.insert(0, row_item)
                devices = tuple(dev_list)
                device_rows = tuple(row_list)
            panel.devices = box_devices_with_special_rows(devices)
            panel.device_rows = device_rows
        else:
            panel.devices = box_devices_with_special_rows(())
            panel.device_rows = ()
        panel.scroll = 0
        panel.row = 0
        panel.arrow = ""
        self.ensure_focus_ring()

    def navigate_box_device_row(self, box_num: int, *, forward: bool) -> bool:
        """Move selection among device rows; wraps at the ends of the full list."""
        panel = self._box_panel(box_num)
        if not panel.results_locked:
            return False
        n = len(panel.devices)
        if n <= 0:
            return False
        visible = int(_BOX_DEVICE_ROW_COUNT)
        step = 1 if forward else -1
        cur = max(0, min(int(panel.absolute_row()), n - 1))
        abs_row = (cur + step) % n
        max_scroll = panel.max_scroll()
        scroll = int(panel.scroll)
        if abs_row < scroll:
            scroll = abs_row
        elif abs_row >= scroll + visible:
            scroll = abs_row - visible + 1
        scroll = max(0, min(scroll, max_scroll))
        panel.scroll = scroll
        panel.row = abs_row - scroll
        panel.arrow = ""
        return True

    def navigate_box_device_scroll(self, box_num: int, *, up: bool) -> bool:
        """Deprecated: vertical device-list scroll disabled (left/right only)."""
        return False

    def pick_box_device(self, box_num: int) -> dict[str, str] | None:
        panel = self._box_panel(box_num)
        if not panel.results_locked:
            return None
        row = device_row_from_pick(
            panel.devices,
            panel.device_rows,
            scroll=int(panel.scroll),
            row=int(panel.row),
        )
        if row is None:
            return None
        special = str(row.get("special") or "")
        if special == "cancel":
            self.restore_box_device_panel(box_num)
            return None
        if special == "enter_ip":
            self.start_manual_device_entry(box_num)
            self.ensure_focus_ring()
            return None
        if self.device_row_matches_saved(box_num, row):
            self.restore_box_device_panel(box_num)
            return None
        name = str(row.get("name") or row.get("label") or "Device").strip()
        ip = str(row.get("address") or "").strip()
        if name or ip:
            panel.picked = (name or ip, ip or name)
        panel.active = False
        panel.phase = "idle"
        panel.scanning = False
        panel.devices = ()
        panel.device_rows = ()
        panel.scroll = 0
        panel.row = 0
        panel.arrow = ""
        if box_num == 2:
            self.show_box2_panel = False
        elif box_num == 3:
            self.show_box3_panel = False
        self.ensure_focus_ring()
        btn = f"main_box{box_num}_button"
        if btn in self.focus_ring:
            self.focus_index = self.focus_ring.index(btn)
        return row

    def clear_box_pairing(self) -> None:
        self.box_pairing = None

    def start_box_pairing(self, box_num: int, row: dict[str, str]) -> None:
        dn = str(row.get("name") or row.get("label") or row.get("address") or "Device")
        self.box_pairing = BoxPairingSession(box_num=int(box_num), row=dict(row), device_name=dn)

    def navigate(self, *, forward: bool = True) -> None:
        if self.keyboard is not None:
            self.keyboard.navigate(forward=forward)
            return
        locked = self.box_device_results_locked()
        if locked is not None:
            self.navigate_box_device_row(locked, forward=forward)
            return
        if self.show_network_picker and not self.wifi_configured:
            self.navigate_picker_row(forward=forward)
            return
        if (
            self.show_network_picker
            and self.focused_id == "main_network_picker_button"
            and self.navigate_picker_row(forward=forward)
        ):
            return
        self.ensure_focus_ring()
        n = len(self.focus_ring)
        step = 1 if forward else -1
        self.focus_index = (int(self.focus_index) + step) % n

    def open_keyboard(
        self,
        target: str,
        *,
        assets_dir: Path | str | None = None,
        trigger_button: str | None = None,
    ) -> None:
        from pigeon.widgets.settings_keyboard import focus_first_letter, focus_keyboard_go, open_keyboard

        buffer_prefill = ""
        if target == "location":
            initial = location_room_label(
                self.location_name, slot_index=self.renaming_location_slot or None
            )
            buffer_prefill = ""
        elif target == "network":
            initial = ""
            buffer_prefill = self.wifi_password
        elif target == "pin":
            initial = ""
        elif target == "device_name":
            entry = self.manual_device_entry
            initial = str(entry.name or "") if entry is not None else ""
            if initial:
                buffer_prefill = initial
                initial = ""
        else:
            initial = ""
        mode_override = None
        if target == "device_ip":
            from pigeon.widgets.settings_keyboard import KeyboardMode

            mode_override = KeyboardMode.NUMERIC_IP
        elif target == "device_name":
            from pigeon.widgets.settings_keyboard import KeyboardMode

            mode_override = KeyboardMode.QWERTY_UPPER
        elif target == "wifi_logout":
            from pigeon.widgets.settings_keyboard import KeyboardMode

            mode_override = KeyboardMode.YES_NO
        elif target == "zipcode":
            from pigeon.widgets.settings_keyboard import KeyboardMode

            mode_override = KeyboardMode.NUMERIC_ALL
        elif target == "search":
            from pigeon.widgets.settings_keyboard import KeyboardMode

            mode_override = KeyboardMode.QWERTY_UPPER
        self.keyboard = open_keyboard(
            target=target,
            initial_text=initial,
            buffer=buffer_prefill,
            theme=self.theme,
            assets_dir=assets_dir,
            mode=mode_override,
        )
        for box_num in (2, 3):
            panel = self._box_panel(box_num)
            panel.scanning = False
        if target == "network" or trigger_button == "main_dual_network_button":
            focus_keyboard_go(self.keyboard, assets_dir=assets_dir)
        elif trigger_button == "main_dual_location_button":
            focus_first_letter(self.keyboard, assets_dir=assets_dir)
        elif target == "device_ip":
            from pigeon.widgets.settings_keyboard import KeyboardMode, focus_numeric_one

            self.keyboard.set_mode(KeyboardMode.NUMERIC_IP, assets_dir=assets_dir)
            focus_numeric_one(self.keyboard, assets_dir=assets_dir)
        elif target == "device_name":
            focus_first_letter(self.keyboard, assets_dir=assets_dir)
        elif target == "wifi_logout":
            from pigeon.widgets.settings_keyboard import focus_yes_no_yes

            focus_yes_no_yes(self.keyboard, assets_dir=assets_dir)
        elif target == "zipcode":
            from pigeon.widgets.settings_keyboard import KeyboardMode, focus_numeric_one

            self.keyboard.set_mode(KeyboardMode.NUMERIC_ALL, assets_dir=assets_dir)
            focus_numeric_one(self.keyboard, assets_dir=assets_dir)
        else:
            focus_first_letter(self.keyboard, assets_dir=assets_dir)

    def close_keyboard(self, *, commit: bool = False) -> tuple[str, str]:
        """Close keyboard. Returns ``(target, buffer_text)``."""
        kb = self.keyboard
        if kb is None:
            return "", ""
        target = str(getattr(kb, "target", "") or "")
        buffer = str(getattr(kb, "buffer", "") or "")
        if commit:
            if target == "location":
                self.location_name = buffer
            elif target == "network":
                self.wifi_password = buffer
                self.network_name = buffer
        self.keyboard = None
        return target, buffer

    def sync_search_suggestions(self) -> bool:
        """Mirror ``manual_search`` suggestions into the open search keyboard."""
        kb = self.keyboard
        if kb is None or str(getattr(kb, "target", "") or "") != "search":
            return False
        from pigeon.manual_search import suggestions

        rows = tuple(
            f"{r['title']} ({r['year']})" if r.get("year") else str(r["title"])
            for r in suggestions()
        )
        if rows == tuple(getattr(kb, "suggestions", ()) or ()):
            return False
        kb.suggestions = rows
        kb.clamp_focus_to_available()
        return True

    def commit_search(self, entry: dict | None) -> bool:
        """Persist a manual title and return to the main ring on SEARCH."""
        from pigeon import manual_search

        saved = manual_search.set_entry(entry) if entry else None
        self.keyboard = None
        manual_search.reset_suggestions()
        if saved is None:
            return False
        self.manual_search_title = str(saved["title"])
        self.ensure_focus_ring()
        self.focus_main_button("main_search_button")
        return True

    def clear_search(self) -> None:
        from pigeon import manual_search

        manual_search.clear()
        self.manual_search_title = ""
        self.ensure_focus_ring()
        self.focus_main_button("main_search_button")

    def enter_wifi_onboarding(self) -> None:
        if self.wifi_configured:
            return
        self.wifi_onboarding = True
        self.show_instructions = False
        self.show_network_picker = False
        self.wifi_scanning = False
        self.wifi_networks = ()
        self.ensure_focus_ring()
        if "main_dual_network_button" in self.focus_ring:
            self.focus_index = self.focus_ring.index("main_dual_network_button")

    def start_wifi_scan(self) -> None:
        if self.wifi_scanning:
            return
        self.wifi_scanning = True
        self.wifi_scan_started_mono = time.monotonic()
        self.wifi_scan_angle_deg = 0.0
        self.show_network_picker = False
        self.wifi_networks = ()

    def complete_wifi_scan(self, networks: tuple[str, ...] | None = None) -> None:
        from pigeon.wifi_scan import filter_scan_results_for_picker

        self.wifi_scanning = False
        self.wifi_networks = filter_scan_results_for_picker(networks or ())
        self.show_network_picker = True
        self.network_picker_row = 0
        self.network_picker_scroll = 0
        self.ensure_focus_ring()
        if "main_network_picker_button" in self.focus_ring:
            self.focus_index = self.focus_ring.index("main_network_picker_button")

    def select_wifi_network(self, ssid: str) -> None:
        self.pending_wifi_ssid = str(ssid or "").strip()
        self.network_password_error = False
        self.wifi_onboarding = False
        self.show_instructions = False
        self.show_network_picker = False
        self.wifi_scanning = False
        self.wifi_networks = ()
        self.ensure_focus_ring()
