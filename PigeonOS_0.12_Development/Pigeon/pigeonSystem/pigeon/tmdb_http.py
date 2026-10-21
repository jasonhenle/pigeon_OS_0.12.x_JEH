"""
TMDb HTTP transport.

Secret scrubbing for logs, a minimal subprocess environment, the byte GET helper (curl
on Linux, urllib elsewhere) and the binary download helper. Authentication stays in
``tmdb_poster`` (``load_tmdb_api_key`` / ``load_tmdb_read_token`` / ``_request_json``)
so tests can redirect the state directory there.

``pigeon.tmdb_poster`` re-exports every name here for existing importers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


_UA = "Pigeon0.5/1.0 (local; +https://www.themoviedb.org/documentation/api)"


def _sanitize_api_secret(raw: str | bytes) -> str:
    """Strip BOM, whitespace (incl. U+202F), and non-ASCII from pasted API keys/tokens."""
    if not raw:
        return ""
    if isinstance(raw, bytes):
        return bytes(b for b in raw if 32 <= b < 127).decode("ascii")
    cleaned: list[str] = []
    for ch in raw.lstrip("\ufeff"):
        if ch.isspace():
            continue
        if ord(ch) < 128:
            cleaned.append(ch)
    return "".join(cleaned)


def _minimal_subprocess_env() -> dict[str, str]:
    keep = (
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    )
    out: dict[str, str] = {}
    for key in keep:
        val = os.environ.get(key)
        if val:
            out[key] = "".join(ch for ch in str(val) if 32 <= ord(ch) < 127)
    if "PATH" not in out:
        out["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    if "HOME" not in out:
        try:
            out["HOME"] = str(Path.home())
        except RuntimeError:
            pass
    return out


def _http_get_bytes(url: str, *, timeout_s: float = 60.0, headers: dict[str, str] | None = None) -> bytes:
    """HTTPS GET for TMDb API and image CDN (curl on Linux for reliable Pi SSL)."""
    safe_headers = {
        str(k): "".join(ch for ch in str(v) if ord(ch) < 256) for k, v in (headers or {}).items()
    }
    if sys.platform.startswith("linux"):
        curl = shutil.which("curl")
        if not curl:
            raise OSError("curl is required for TMDb downloads on Linux.")
        cmd = [curl, "-fsSL", "--max-time", str(max(1, int(timeout_s)))]
        for hk, hv in safe_headers.items():
            if hk and hv is not None:
                cmd.extend(["-H", f"{hk}: {hv}"])
        cmd.append(url)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            env=_minimal_subprocess_env(),
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace").strip()
        raise OSError(err or f"curl exited {proc.returncode}")

    req = urllib.request.Request(url, headers=safe_headers or {"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read()


def _download_binary(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = _http_get_bytes(url, timeout_s=60.0, headers={"User-Agent": _UA})
    dest.write_bytes(data)
