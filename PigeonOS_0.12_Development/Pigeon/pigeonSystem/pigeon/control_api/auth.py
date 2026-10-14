"""Claim code, bearer tokens (stored hashed) and failed-attempt rate limiting."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time

from pigeon.runtime_paths import pigeon_state_dir

_FILE = "control_api_auth.json"
MAX_FAILS = 5
LOCKOUT_S = 60.0


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthStore:
    """Controllers (hashed tokens) plus the in-memory pairing code."""

    def __init__(self, path=None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._code = self._new_code()
        self._fails = 0
        self._locked_until = 0.0
        self._invite_until = 0.0

    # ---- persistence
    def _file(self):
        return self._path or (pigeon_state_dir() / _FILE)

    def _load(self) -> list[dict]:
        try:
            raw = json.loads(self._file().read_text(encoding="utf-8"))
            rows = raw.get("controllers") if isinstance(raw, dict) else None
            return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, rows: list[dict]) -> None:
        p = self._file()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"controllers": rows}), encoding="utf-8")
        tmp.replace(p)

    # ---- state
    @staticmethod
    def _new_code() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    @property
    def pairing_code(self) -> str:
        """Shown on the device's own screen; regenerated at boot and after lockout."""
        return self._code

    def claimed(self) -> bool:
        with self._lock:
            return bool(self._load())

    def controllers(self) -> list[dict]:
        with self._lock:
            return [
                {"id": r.get("id"), "name": r.get("name"), "added": r.get("added")}
                for r in self._load()
            ]

    # ---- claim
    def retry_after(self) -> float:
        return max(0.0, self._locked_until - time.monotonic())

    def claim(self, code: str, controller_name: str, controller_id: str) -> str | None:
        """Return a new token, or ``None`` if the code is wrong. Raises PermissionError when locked."""
        with self._lock:
            if self.retry_after() > 0:
                raise PermissionError("locked")
            ok = hmac.compare_digest(str(code or ""), self._code)
            if not ok:
                self._fails += 1
                if self._fails >= MAX_FAILS:
                    self._fails = 0
                    self._locked_until = time.monotonic() + LOCKOUT_S
                    self._code = self._new_code()
                return None
            rows = self._load()
            token = "pgt_" + secrets.token_urlsafe(32)
            cid = str(controller_id or "") or secrets.token_hex(4)
            rows = [r for r in rows if r.get("id") != cid]
            rows.append(
                {
                    "id": cid,
                    "name": str(controller_name or "Controller")[:40],
                    "hash": _hash(token),
                    "added": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )
            self._save(rows)
            self._code = self._new_code()
            self._fails = 0
            return token

    def invite(self, ttl_s: float = 300.0) -> str:
        """Fresh code for adding another controller; valid for ``ttl_s``."""
        with self._lock:
            self._code = self._new_code()
            self._invite_until = time.monotonic() + ttl_s
            return self._code

    def claim_open(self) -> bool:
        """Claims are accepted while unclaimed, or during an invite window."""
        with self._lock:
            return not self._load() or time.monotonic() < self._invite_until

    # ---- verify / revoke
    def verify(self, token: str) -> dict | None:
        if not token:
            return None
        h = _hash(token)
        with self._lock:
            for r in self._load():
                if hmac.compare_digest(str(r.get("hash") or ""), h):
                    return {"id": r.get("id"), "name": r.get("name")}
        return None

    def revoke(self, controller_id: str) -> bool:
        with self._lock:
            rows = self._load()
            keep = [r for r in rows if r.get("id") != controller_id]
            if len(keep) == len(rows):
                return False
            self._save(keep)
            return True
