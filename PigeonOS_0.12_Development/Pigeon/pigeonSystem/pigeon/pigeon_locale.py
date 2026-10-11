"""Zip code + timezone for settings_pigeon (0.11).

The zip code is guessed once from the public IP and can be replaced by a
manual entry; it also drives the weather widget. The timezone applies to
Pigeon's own clocks only — the OS clock is never changed.

Persisted under ``pigeon_location`` in state.json::

    {"zip": "21710", "zip_source": "auto" | "manual",
     "timezone": "America/New_York", "tz_source": "auto" | "zip" | "manual"}

Precedence: a manual zip is never replaced by auto-detect; a zip entry sets
the timezone for that zip; the timezone dropdown overrides both.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore[assignment,misc]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment,misc]

_STATE_KEY = "pigeon_location"
_FETCH_TIMEOUT_S = 8.0
# A failed IP lookup (e.g. network not up yet at boot) is retried at most this often.
_DETECT_RETRY_S = 600.0
ZIP_PLACEHOLDER = "ENTER"

# Dropdown choices, west → east. Labels come from the live abbreviation so
# daylight time reads EDT / CDT / ... in summer.
TIMEZONE_CHOICES: tuple[str, ...] = (
    "Pacific/Honolulu",
    "America/Anchorage",
    "America/Los_Angeles",
    "America/Phoenix",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "America/Halifax",
    "America/St_Johns",
    "UTC",
    "Europe/London",
    "Europe/Paris",
    "Europe/Athens",
    "Asia/Kolkata",
    "Asia/Tokyo",
    "Australia/Sydney",
)

_lock = threading.Lock()
_detect_in_flight = False
_detect_last_mono: float | None = None


def _read() -> dict[str, Any]:
    try:
        from pigeon.app_state import read_app_state_shared

        raw = read_app_state_shared().get(_STATE_KEY)
    except Exception:
        raw = None
    return dict(raw) if isinstance(raw, dict) else {}


def _write(**updates: Any) -> None:
    cur = _read()
    cur.update(updates)
    try:
        from pigeon.app_state import write_app_state

        write_app_state(**{_STATE_KEY: cur})
    except Exception:
        pass


def _zone(name: str | None) -> Any:
    if not name or ZoneInfo is None:
        return None
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def normalize_zip(raw: str | None) -> str:
    """Five-digit US zip, or ``""``."""
    digits = "".join(c for c in str(raw or "") if c.isdigit())
    return digits[:5] if len(digits) >= 5 else ""


def read_zipcode() -> str:
    return normalize_zip(_read().get("zip"))


def zipcode_display_text() -> str:
    return read_zipcode() or ZIP_PLACEHOLDER


def read_timezone() -> str | None:
    """IANA name Pigeon clocks use, or None for the system local zone."""
    name = str(_read().get("timezone") or "").strip()
    return name if _zone(name) is not None else None


def weather_zip(default: str) -> str:
    return read_zipcode() or default


def pigeon_now() -> datetime:
    """Naive wall-clock time in Pigeon's timezone (system local if unset)."""
    tz = _zone(read_timezone())
    if tz is None:
        return datetime.now()
    return datetime.now(tz).replace(tzinfo=None)


def _aware_now(name: str | None) -> datetime:
    tz = _zone(name)
    if tz is None:
        return datetime.now().astimezone()
    return datetime.now(tz)


def timezone_abbrev(name: str | None = None) -> str:
    """Short label such as ``EST``; ``name`` defaults to Pigeon's timezone."""
    zone_name = name if name is not None else read_timezone()
    abbr = str(_aware_now(zone_name).tzname() or "").strip()
    if abbr and abbr[0] in "+-":
        # Zones without a letter abbreviation (e.g. ``+0530``): show UTC offset.
        return f"UTC{abbr}"
    return abbr or "UTC"


def _offset(name: str | None) -> timedelta:
    return _aware_now(name).utcoffset() or timedelta(0)


def _format_offset(delta: timedelta) -> str:
    minutes = int(round(delta.total_seconds() / 60.0))
    sign = "-" if minutes < 0 else "+"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60}:{minutes % 60:02d}"


def timezone_choices() -> tuple[str, ...]:
    return tuple(name for name in TIMEZONE_CHOICES if _zone(name) is not None)


def timezone_dropdown_label(name: str, *, relative_to: str | None = None) -> str:
    """``CST -1:00`` — offset from the currently selected timezone."""
    base = relative_to if relative_to is not None else read_timezone()
    return f"{timezone_abbrev(name)} {_format_offset(_offset(name) - _offset(base))}"


def current_timezone_choice_index() -> int:
    """Row to highlight when the dropdown opens (current zone, or same offset)."""
    choices = timezone_choices()
    if not choices:
        return 0
    current = read_timezone()
    if current in choices:
        return choices.index(current)
    here = _offset(current)
    for i, name in enumerate(choices):
        if _offset(name) == here:
            return i
    return 0


def set_timezone_manual(name: str) -> bool:
    if _zone(name) is None:
        return False
    _write(timezone=str(name), tz_source="manual")
    return True


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "Pigeon/0.11 (locale)"})
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


_NET_ERRORS = (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError)


def _lookup_ip_location() -> tuple[str, str]:
    """(zip, IANA timezone) for the public IP; empty strings when unknown."""
    try:
        data = _http_json("https://ipapi.co/json/")
        if isinstance(data, dict) and not data.get("error"):
            return normalize_zip(data.get("postal")), str(data.get("timezone") or "")
    except _NET_ERRORS:
        pass
    try:
        # ip-api's free tier is HTTP only; nothing but our public IP is sent.
        data = _http_json("http://ip-api.com/json/?fields=status,zip,timezone")
        if isinstance(data, dict) and data.get("status") == "success":
            return normalize_zip(data.get("zip")), str(data.get("timezone") or "")
    except _NET_ERRORS:
        pass
    return "", ""


def _lookup_zip_timezone(zip_code: str) -> str:
    """IANA timezone for a US zip (Zippopotam lat/lon → Open-Meteo)."""
    from pigeon.weather import _geocode_zip

    coords = _geocode_zip(zip_code)
    if coords is None:
        return ""
    lat, lon = coords
    try:
        data = _http_json(
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat:.4f}&longitude={lon:.4f}&timezone=auto&forecast_days=1"
        )
    except _NET_ERRORS:
        return ""
    return str(data.get("timezone") or "") if isinstance(data, dict) else ""


def detect_location_blocking() -> bool:
    """Fill zip / timezone from the public IP unless the user set them."""
    cur = _read()
    if normalize_zip(cur.get("zip")) and cur.get("zip_source") == "manual":
        return False
    zip_code, tz_name = _lookup_ip_location()
    updates: dict[str, Any] = {}
    if zip_code:
        updates.update(zip=zip_code, zip_source="auto")
    if _zone(tz_name) is not None and cur.get("tz_source") not in ("manual", "zip"):
        updates.update(timezone=tz_name, tz_source="auto")
    if updates:
        _write(**updates)
    return bool(updates)


def ensure_location_detected(on_done: Any = None) -> bool:
    """Start a background IP lookup when no zip is saved. True if started."""
    global _detect_in_flight, _detect_last_mono
    if read_zipcode():
        return False
    now = time.monotonic()
    with _lock:
        if _detect_in_flight:
            return False
        if _detect_last_mono is not None and now - _detect_last_mono < _DETECT_RETRY_S:
            return False
        _detect_in_flight = True
        _detect_last_mono = now

    def worker() -> None:
        global _detect_in_flight
        changed = False
        try:
            changed = detect_location_blocking()
        finally:
            with _lock:
                _detect_in_flight = False
        if changed and on_done is not None:
            try:
                on_done()
            except Exception:
                pass

    threading.Thread(target=worker, name="pigeon-locale-detect", daemon=True).start()
    return True


def set_zipcode_manual(raw: str, on_done: Any = None) -> bool:
    """Save a typed zip; resolve its timezone in the background."""
    zip_code = normalize_zip(raw)
    if not zip_code:
        return False
    _write(zip=zip_code, zip_source="manual")

    def worker() -> None:
        tz_name = _lookup_zip_timezone(zip_code)
        if _zone(tz_name) is not None and read_zipcode() == zip_code:
            _write(timezone=tz_name, tz_source="zip")
        try:
            from pigeon.weather import refresh_weather

            refresh_weather(zip_code=zip_code, force=True)
        except Exception:
            pass
        if on_done is not None:
            try:
                on_done()
            except Exception:
                pass

    threading.Thread(target=worker, name="pigeon-zip-timezone", daemon=True).start()
    return True


def clear_location() -> None:
    try:
        from pigeon.app_state import pop_app_state_keys

        pop_app_state_keys(_STATE_KEY)
    except Exception:
        pass


__all__ = [
    "TIMEZONE_CHOICES",
    "ZIP_PLACEHOLDER",
    "clear_location",
    "current_timezone_choice_index",
    "detect_location_blocking",
    "ensure_location_detected",
    "normalize_zip",
    "pigeon_now",
    "read_timezone",
    "read_zipcode",
    "set_timezone_manual",
    "set_zipcode_manual",
    "timezone_abbrev",
    "timezone_choices",
    "timezone_dropdown_label",
    "weather_zip",
    "zipcode_display_text",
]
