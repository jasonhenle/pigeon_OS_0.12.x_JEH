"""First-run setup state: has this Pigeon been set up yet, and how far along is it?

Persisted in ``setup_state.json`` in the state directory (its own file, so ordinary
``state.json`` writes can never clobber it). States:

- ``welcome``: brand new or factory reset. The Welcome screen shows the QR code and
  "Set up manually"; a phone may claim the device from the QR code.
- ``app``: a phone claimed the device from the Welcome screen and is running the setup
  wizard. The screen says "Continue on your iPhone".
- ``done``: set up (by the app, by hand on the encoders, or an install that predates
  this feature).

``resolve_at_boot`` must run before anything writes ``state.json`` at startup: with no
setup file yet, an existing ``state.json`` means an install that was already in use, so
it is recorded as ``done`` instead of showing the Welcome screen after an update. Until
``resolve_at_boot`` (or a reset) writes the file, every reader sees ``done``.

``PIGEON_SETUP=welcome`` forces the Welcome screen at boot (handy on a Mac);
``PIGEON_SETUP=done`` skips it.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable

from pigeon.runtime_paths import pigeon_state_dir

_FILE = "setup_state.json"
WELCOME, APP, DONE = "welcome", "app", "done"
STATES = (WELCOME, APP, DONE)
# Wizard steps the app reports as it goes (``PUT /setup``). Order is the app's to choose.
STEPS = ("network", "location", "player", "audio", "finish")

_lock = threading.RLock()
_cache: dict[str, Any] | None = None
_listeners: list[Callable[[dict[str, Any]], object]] = []


def _path():
    return pigeon_state_dir() / _FILE


def _default_done() -> dict[str, Any]:
    return {"state": DONE, "step": None, "skipped": [], "via": None}


def _normalize(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("state") not in STATES:
        return _default_done()
    step = raw.get("step")
    skipped = raw.get("skipped") if isinstance(raw.get("skipped"), list) else []
    return {
        "state": raw["state"],
        "step": step if step in STEPS else None,
        "skipped": [s for s in skipped if s in STEPS],
        "via": raw.get("via") if isinstance(raw.get("via"), str) else None,
    }


def _read_file() -> dict[str, Any] | None:
    try:
        return _normalize(json.loads(_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def _write(data: dict[str, Any]) -> None:
    global _cache
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({**data, "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}),
                   encoding="utf-8")
    tmp.replace(p)
    _cache = dict(data)
    for fn in list(_listeners):
        try:
            fn(dict(data))
        except Exception:
            pass


def add_listener(fn: Callable[[dict[str, Any]], object]) -> None:
    """Called (on the writing thread) with the new state after every change."""
    _listeners.append(fn)


def _forced() -> str:
    return (os.environ.get("PIGEON_SETUP") or "").strip().lower()


def resolve_at_boot() -> str:
    """Decide once per boot whether the Welcome screen is needed. Returns the state."""
    global _cache
    with _lock:
        forced = _forced()
        if forced in (WELCOME, "1", "on", "yes", "true"):
            _write({"state": WELCOME, "step": None, "skipped": [], "via": None})
            return WELCOME
        if forced in (DONE, "0", "off", "no", "false"):
            _cache = _default_done()
            return DONE
        cur = _read_file()
        if cur is not None:
            _cache = cur
            return cur["state"]
        try:
            from pigeon.app_state import state_file

            sf = state_file()
            in_use = sf.is_file() and sf.stat().st_size > 2
        except OSError:
            in_use = False
        if in_use:
            _write({**_default_done(), "via": "existing"})
            return DONE
        _write({"state": WELCOME, "step": None, "skipped": [], "via": None})
        return WELCOME


def current() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _read_file() or _default_done()
        return dict(_cache, skipped=list(_cache["skipped"]))


def state() -> str:
    return current()["state"]


def needs_setup() -> bool:
    return state() != DONE


def welcome_showing() -> bool:
    """The Welcome screen (QR code + claim code) is up, so a phone may claim the device."""
    return state() == WELCOME


# While the app is on these steps the device shows its own on-screen search, picked with the knob,
# so the "Continue on your iPhone" screen steps aside.
ON_DEVICE_STEPS = ("player", "audio")


def screen_wanted(cur: dict[str, Any] | None = None) -> bool:
    """Whether the Welcome / "Continue on your iPhone" screen should be up right now."""
    c = cur if cur is not None else current()
    if c["state"] == DONE:
        return False
    return not (c["state"] == APP and c["step"] in ON_DEVICE_STEPS)


def public() -> dict[str, Any]:
    """What ``/hello`` and ``/setup`` report."""
    c = current()
    return {"state": c["state"], "step": c["step"], "skipped": c["skipped"]}


def note_claimed() -> bool:
    """A phone claimed the device: Welcome becomes "Continue on your iPhone". True if it changed."""
    with _lock:
        c = current()
        if c["state"] != WELCOME:
            return False
        _write({**c, "state": APP, "via": "app"})
        return True


def set_progress(step: str | None = None, skipped: list[str] | None = None) -> dict[str, Any]:
    """Record the wizard's current step and the steps the user skipped. Raises ValueError."""
    with _lock:
        c = current()
        if c["state"] == DONE:
            raise ValueError("setup is already complete")
        if step is not None and step not in STEPS:
            raise ValueError(f"step must be one of {', '.join(STEPS)}")
        if skipped is not None:
            bad = [s for s in skipped if s not in STEPS]
            if bad:
                raise ValueError(f"unknown step in skipped: {bad[0]}")
        new = {**c, "state": APP}
        if step is not None:
            new["step"] = step
        if skipped is not None:
            new["skipped"] = list(dict.fromkeys(skipped))
        _write(new)
        return public()


def complete(via: str) -> None:
    """Setup finished (``via`` = ``app`` or ``manual``). Skipped steps are kept for the app."""
    with _lock:
        c = current()
        _write({**c, "state": DONE, "step": None, "via": via})


def reset_to_welcome() -> None:
    """Factory reset: show the Welcome screen again."""
    with _lock:
        _write({"state": WELCOME, "step": None, "skipped": [], "via": None})


def _reset_for_tests() -> None:
    global _cache
    with _lock:
        _cache = None
        _listeners.clear()
