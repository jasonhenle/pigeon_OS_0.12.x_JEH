"""Receiver-independent Pigeon behavior, written only against ``Receiver``."""

from __future__ import annotations

from pigeon.receiver.base import Receiver

ROTARY_ACTIONS = ("volume_up", "volume_down", "mute_toggle")


def apply_rotary_action(receiver: Receiver, action: str, *, wake: bool = False) -> bool:
    """Encoder action → receiver call (same vocabulary as the Pigeon rotary handler)."""
    act = str(action or "").strip().lower()
    if act not in ROTARY_ACTIONS:
        return False
    if act == "mute_toggle":
        return receiver.toggle_mute(wake=wake)
    return receiver.step_volume(1 if act == "volume_up" else -1, wake=wake)
