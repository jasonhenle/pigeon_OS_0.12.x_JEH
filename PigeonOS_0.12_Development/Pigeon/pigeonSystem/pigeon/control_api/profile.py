"""Device profile: who this device is and what it can do (Control API ``/capabilities``)."""

from __future__ import annotations

import json
import os
import secrets
import threading

from pigeon.runtime_paths import pigeon_state_dir
from pigeon.version import version_string

API_VERSION = 1
DEFAULT_PORT = 8780
_FILE = "control_api_device.json"
_LOCK = threading.Lock()

# Capabilities by product. Marquee column is a working assumption (see docs).
_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "clock": (
        "now_playing", "manual_search", "clock", "locations", "wifi",
        "pairing_player", "pairing_receiver", "viz", "rotary", "update",
    ),
    "marquee": (
        "now_playing", "manual_search", "locations", "wifi",
        "pairing_player", "pairing_receiver", "update",
    ),
}


def product() -> str:
    raw = (os.environ.get("PIGEON_PRODUCT") or "clock").strip().lower()
    return raw if raw in _CAPABILITIES else "clock"


def capabilities() -> list[str]:
    """Capabilities implemented by *this build* for this product (Phase 1 subset)."""
    implemented = {"now_playing", "manual_search"}
    return [c for c in _CAPABILITIES[product()] if c in implemented]


def has_capability(name: str) -> bool:
    return name in capabilities()


def _path():
    return pigeon_state_dir() / _FILE


def _read() -> dict:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(p)


def device_id() -> str:
    """Stable opaque id, generated once and persisted."""
    with _LOCK:
        data = _read()
        did = str(data.get("id") or "")
        if not did:
            did = "pgn-" + secrets.token_hex(3)
            data["id"] = did
            _write(data)
        return did


def device_name() -> str:
    name = str(_read().get("name") or "").strip()
    if name:
        return name
    return "Pigeon Marquee" if product() == "marquee" else "Pigeon Clock"


def set_device_name(name: str) -> str:
    name = " ".join(str(name or "").split())
    if not 1 <= len(name) <= 40:
        raise ValueError("name must be 1-40 characters")
    with _LOCK:
        data = _read()
        data["name"] = name
        _write(data)
    return name


def version() -> str:
    return version_string()
