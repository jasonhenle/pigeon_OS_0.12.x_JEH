"""Generic receiver interface and adapters (Denon, Fake).

Add a brand by writing an adapter that satisfies ``Receiver`` and registering
a factory in ``ADAPTERS``; no Pigeon or diagnostic-tool code changes.
"""

from __future__ import annotations

from collections.abc import Callable

from pigeon.receiver.base import (
    EVENT_KINDS,
    DiscoveredReceiver,
    InputSelectable,
    Receiver,
    ReceiverEvent,
    ReceiverState,
)


def _denon(host: str, **opts: object) -> Receiver:
    from pigeon.receiver.denon import DenonReceiver

    return DenonReceiver(host, **opts)


def _fake(host: str, **opts: object) -> Receiver:
    from pigeon.receiver.fake import FakeReceiver

    r = FakeReceiver()
    r.start_auto_pump()
    return r


# brand → factory(host). Factories import lazily so unused adapters cost nothing.
ADAPTERS: dict[str, Callable[..., Receiver]] = {"denon": _denon, "fake": _fake}


def _discover_denon() -> list[DiscoveredReceiver]:
    from pigeon.receiver_denon import _canonical_receiver_key, scan_denon_like_receivers_on_lan

    # 0.8s: AVRs can take ~0.5s to answer the first HTTP probe; the 0.4s default misses them.
    _ok, _msg, rows = scan_denon_like_receivers_on_lan(timeout_per_host=0.8)
    # The scan reports the HTTP endpoint (``ip:8080``); the adapter wants the bare host.
    return [
        DiscoveredReceiver("denon", _canonical_receiver_key(str(r.get("host") or "")),
                           str(r.get("name") or ""), str(r.get("id") or ""))
        for r in rows if r.get("host")
    ]


def _discover_fake() -> list[DiscoveredReceiver]:
    return [DiscoveredReceiver("fake", "", "Simulated receiver")]


# brand → discoverer(). Same rule as ADAPTERS: one entry per brand, nothing else changes.
DISCOVERERS: dict[str, Callable[[], list[DiscoveredReceiver]]] = {
    "denon": _discover_denon, "fake": _discover_fake,
}


def discover_receivers(brands: list[str] | None = None) -> list[DiscoveredReceiver]:
    """Search the LAN for receivers of the given brands (default: every brand with a discoverer).

    A brand whose scan raises is skipped so one broken discoverer can't hide the rest.
    """
    found: list[DiscoveredReceiver] = []
    for brand in brands or sorted(DISCOVERERS):
        try:
            found.extend(DISCOVERERS[brand.strip().lower()]())
        except KeyError:
            raise ValueError(f"no discoverer for brand {brand!r}; known: {sorted(DISCOVERERS)}") from None
        except Exception:
            continue
    return found


def create_receiver(brand: str, host: str = "", **opts: object) -> Receiver:
    """``opts`` are adapter tuning knobs (e.g. ``full_poll_s``); adapters ignore ones they lack."""
    try:
        return ADAPTERS[brand.strip().lower()](host, **opts)
    except KeyError:
        raise ValueError(f"unknown receiver brand {brand!r}; known: {sorted(ADAPTERS)}") from None


__all__ = [
    "ADAPTERS", "DISCOVERERS", "DiscoveredReceiver", "discover_receivers", "EVENT_KINDS", "InputSelectable", "Receiver", "ReceiverEvent",
    "ReceiverState", "create_receiver",
]
