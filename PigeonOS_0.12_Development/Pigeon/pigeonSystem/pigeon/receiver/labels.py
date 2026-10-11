"""Brand-neutral display helpers for receiver text.

Widgets use these instead of importing a brand module. Today the only rules
are the Denon ones; a new brand's rules would be OR-ed in here.
"""

from __future__ import annotations


def looks_like_input_selector(value: str) -> bool:
    """True when ``value`` names a receiver input (SAT/CBL, HDMI 3, …) rather than an audio format."""
    from pigeon.receiver_denon import looks_like_hdmi_input_selector

    return looks_like_hdmi_input_selector(value)
