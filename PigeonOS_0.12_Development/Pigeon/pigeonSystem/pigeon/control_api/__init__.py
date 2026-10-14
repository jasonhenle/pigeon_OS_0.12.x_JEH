"""Pigeon Control API (companion app interface). See ``docs/control_api_v1.md``.

Off by default. Enable with ``PIGEON_CONTROL_API=1`` or ``"control_api": true``
in the app state file. ``start()`` is safe to call more than once.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

from pigeon.control_api import profile
from pigeon.control_api.discovery import Advertiser
from pigeon.control_api.server import ControlServer, ControlService

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


def start(
    *,
    status_provider: Callable[[], dict[str, Any]] | None = None,
    run_on_ui: Callable[[Callable[[], object]], object] | None = None,
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
            svc = ControlService(status_provider=status_provider, run_on_ui=run_on_ui)
            srv = ControlServer(svc, port=port or int(os.environ.get("PIGEON_CONTROL_PORT") or profile.DEFAULT_PORT))
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
