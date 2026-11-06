"""The full-screen visualizers: list the rotation, pick one, VIZ LOCK.

``GET /visualizer``::

    {"presets": [{"index": 0, "name": "Spectrum", "style": "dots",
                  "kind": "Dot matrix"}, ...],
     "active": 0, "viz_lock": false}

``PATCH /visualizer`` takes ``active`` (a preset index) and / or ``viz_lock``
(bool). ``active`` moves the zone-6 visualizer and the clocksaver backdrop at
once and is kept like an encoder pick; ``viz_lock`` is settings_pigeon option 8.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def read_visualizer() -> dict[str, Any]:
    from pigeon import fullscreen_viz as fv
    from pigeon.widgets.options_settings import viz_lock_on

    items = fv.presets()
    return {
        "presets": [
            {
                "index": i,
                "name": str(p.get("name") or f"Preset {i + 1}"),
                "style": str(p.get("style", "")),
                "kind": str(fv.STYLES.get(str(p.get("style")), {}).get("label", "")),
            }
            for i, p in enumerate(items)
        ],
        "active": fv.active_preset_index(),
        "viz_lock": viz_lock_on(),
    }


def patch_visualizer(body: Mapping[str, Any]) -> None:
    """Raises ValueError with the bad field names."""
    from pigeon import fullscreen_viz as fv
    from pigeon.widgets.options_settings import set_option_value

    errors = sorted(set(body) - {"active", "viz_lock"})
    active = body.get("active")
    if "active" in body and (
        isinstance(active, bool) or not isinstance(active, int) or not 0 <= active < len(fv.presets())
    ):
        errors.append("active")
    if "viz_lock" in body and not isinstance(body["viz_lock"], bool):
        errors.append("viz_lock")
    if errors or not body:
        raise ValueError(",".join(errors) or "active")
    if "viz_lock" in body:
        set_option_value("viz_lock", "on" if body["viz_lock"] else "off")
    if "active" in body:
        fv.select_preset(int(active))


__all__ = ["patch_visualizer", "read_visualizer"]
