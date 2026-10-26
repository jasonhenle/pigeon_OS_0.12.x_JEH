"""Pigeon Control API (companion app interface). See ``docs/control_api_v1.md``.

Off by default. Enable with ``PIGEON_CONTROL_API=1`` or ``"control_api": true``
in the app state file. ``start()`` is safe to call more than once.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any, Callable

from pigeon.control_api import profile, tls
from pigeon.control_api.discovery import Advertiser
from pigeon.control_api.server import DEFAULT_TLS_PORT, ControlServer, ControlService
from pigeon.runtime_paths import pigeon_state_dir

_lock = threading.Lock()
_server: ControlServer | None = None
_advertiser: Advertiser | None = None
_service: ControlService | None = None


def enabled() -> bool:
    env = (os.environ.get("PIGEON_CONTROL_API") or "").strip().lower()
    if env:
        return env in ("1", "true", "yes", "on")
    try:
        from pigeon.app_state import read_app_state

        return bool(read_app_state().get("control_api"))
    except Exception:
        return False


def _flag(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    return default if not raw else raw in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def pairing_code() -> str:
    """The code to show on the device's screen while claiming. ``""`` when not running."""
    return _service.auth.pairing_code if _service is not None else ""


def claim_code_to_show() -> str:
    """Code for the on-screen claim hint: only while a claim is actually possible."""
    svc = _service
    if svc is None:
        return ""
    try:
        return svc.auth.pairing_code if svc.auth.claim_open() else ""
    except Exception:
        return ""


def display_code() -> str:
    """Code the device should be showing full screen now (phone is mid-pairing), or ``""``."""
    svc = _service
    return svc.auth.display_code() if svc is not None else ""


def start(
    *,
    status_provider: Callable[[], dict[str, Any]] | None = None,
    run_on_ui: Callable[[Callable[[], object]], object] | None = None,
    metadata_provider: Callable[[], Any] | None = None,
    fetch_provider: Callable[[], dict[str, Any]] | None = None,
    respawn: Callable[[str, str], object] | None = None,
    apply_location: Callable[[], object] | None = None,
    apply_settings: Callable[[], object] | None = None,
    restart: Callable[[], object] | None = None,
    factory_reset: Callable[[], object] | None = None,
    apply_update: Callable[[], object] | None = None,
    update_state: Callable[[], dict[str, Any]] | None = None,
    pair_scan: Callable[[str], object] | None = None,
    port: int | None = None,
) -> ControlServer | None:
    """Start the API (and mDNS advertise) once. Returns the server, or ``None`` if disabled."""
    global _server, _advertiser, _service
    with _lock:
        if _server is not None:
            return _server
        if not enabled():
            return None
        try:
            identity = None
            if _flag("PIGEON_CONTROL_TLS", True):
                try:
                    identity = tls.ensure_identity(pigeon_state_dir(), device_id=profile.device_id())
                except Exception as exc:
                    # Fail closed: never fall back to serving tokens in clear because the cert step failed.
                    print(f"[control_api] not started: TLS unavailable ({exc}). Set PIGEON_CONTROL_TLS=0 to "
                          "run plain HTTP (insecure).", file=sys.stderr)
                    return None
            else:
                print("[control_api] WARNING: PIGEON_CONTROL_TLS=0, bearer tokens travel over plain HTTP.",
                      file=sys.stderr)
            svc = ControlService(
                status_provider=status_provider, run_on_ui=run_on_ui,
                metadata_provider=metadata_provider, fetch_provider=fetch_provider, respawn=respawn,
                apply_location=apply_location, apply_settings=apply_settings,
                restart=restart, factory_reset=factory_reset, apply_update=apply_update, update_state=update_state,
                pair_scan=pair_scan,
            )
            srv = ControlServer(
                svc, port=port or _int_env("PIGEON_CONTROL_PORT", profile.DEFAULT_PORT),
                tls=identity, tls_port=_int_env("PIGEON_CONTROL_TLS_PORT", DEFAULT_TLS_PORT),
                # Legacy escape hatch for companions that predate pinned HTTPS; off unless asked for.
                allow_plain=identity is not None and _flag("PIGEON_CONTROL_ALLOW_PLAIN", False),
            )
            srv.start()
        except Exception:
            return None  # never take the display down for the companion API
        _service, _server = svc, srv
        try:
            from pigeon.local_ip import local_ipv4_address

            adv = Advertiser()
            adv.start(name=profile.device_name(), port=srv.port,
                      ip=local_ipv4_address(), txt=svc.txt_record())
            _advertiser = adv
            svc.txt_listeners.append(adv.update)
        except Exception:
            pass
        return srv


def stop() -> None:
    global _server, _advertiser, _service
    with _lock:
        if _advertiser is not None:
            _advertiser.stop()
        if _server is not None:
            _server.stop()
        _server = _advertiser = _service = None
