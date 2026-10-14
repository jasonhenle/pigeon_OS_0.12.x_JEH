"""mDNS advertisement of ``_pigeon._tcp``. Uses ``zeroconf`` when installed, else no-op."""

from __future__ import annotations

import socket

SERVICE = "_pigeon._tcp.local."


class Advertiser:
    def __init__(self) -> None:
        self._zc = None
        self._info = None

    def start(self, *, name: str, port: int, ip: str, txt: dict[str, str]) -> bool:
        try:
            from zeroconf import ServiceInfo, Zeroconf  # type: ignore
        except Exception:
            return False
        if not ip:
            return False
        try:
            # The device id is part of the instance name so two devices that share a
            # display name (every new one is "Pigeon Clock") don't collide on the LAN.
            safe = "".join(c for c in name if c.isalnum() or c in " -_")[:32].strip() or "Pigeon"
            uid = "".join(c for c in str(txt.get("id", "")) if c.isalnum())[-6:]
            instance = f"{safe} {uid}" if uid else safe
            self._info = ServiceInfo(
                SERVICE,
                f"{instance}.{SERVICE}",
                addresses=[socket.inet_aton(ip)],
                port=port,
                properties={k: str(v).encode("utf-8") for k, v in txt.items()},
            )
            self._zc = Zeroconf()
            self._zc.register_service(self._info)
            return True
        except Exception:
            self.stop()
            return False

    def update(self, txt: dict[str, str]) -> None:
        zc, info = self._zc, self._info
        if zc is None or info is None:
            return
        try:
            info.properties = {k: str(v).encode("utf-8") for k, v in txt.items()}
            zc.update_service(info)
        except Exception:
            pass

    def stop(self) -> None:
        zc, info = self._zc, self._info
        self._zc = self._info = None
        try:
            if zc is not None:
                if info is not None:
                    zc.unregister_service(info)
                zc.close()
        except Exception:
            pass
