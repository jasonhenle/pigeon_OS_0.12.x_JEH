"""Self-signed TLS identity for the Control API.

The device creates its own certificate once (EC P-256, 10 years) and keeps it in the state directory next to
``control_api_device.json``. Nothing is signed by a public CA: companions pin the certificate by SHA-256 of its DER
bytes, which the device publishes in ``GET /hello`` (``tls.fingerprint_sha256``) and the mDNS TXT record. The key
never leaves the device and is written ``0600``. See ``docs/control_api_v1.md`` section 2.3.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import ssl
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

CERT_NAME = "control_api_tls_cert.pem"
KEY_NAME = "control_api_tls_key.pem"
VALID_DAYS = 3650
RENEW_BEFORE_S = 30 * 86400


@dataclass(frozen=True)
class TlsIdentity:
    certfile: str
    keyfile: str
    fingerprint_sha256: str


def fingerprint_of(certfile: Path | str) -> str:
    pem = Path(certfile).read_text(encoding="ascii")
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


def _generate_openssl(cert: Path, key: Path, cn: str) -> bool:
    exe = shutil.which("openssl")
    if not exe:
        return False
    try:
        subprocess.run(
            [exe, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
             # LibreSSL (macOS) otherwise writes explicit curve parameters, which Apple's TLS stack rejects.
             "-pkeyopt", "ec_param_enc:named_curve", "-nodes",
             "-keyout", str(key), "-out", str(cert), "-days", str(VALID_DAYS), "-subj", f"/CN={cn}",
             "-addext", "subjectAltName=DNS:pigeon.local"],
            check=True, capture_output=True, timeout=60,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _generate_cryptography(cert: Path, key: Path, cn: str) -> bool:
    try:
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except Exception:
        return False
    try:
        priv = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        now = datetime.datetime.now(datetime.timezone.utc)
        built = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(priv.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("pigeon.local")]), critical=False)
            .sign(priv, hashes.SHA256())
        )
        key.write_bytes(priv.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        cert.write_bytes(built.public_bytes(serialization.Encoding.PEM))
        return True
    except Exception:
        return False


def _usable(cert: Path, key: Path) -> bool:
    """Loads as a pair and is not about to expire."""
    if not (cert.is_file() and key.is_file()):
        return False
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(str(cert), str(key))
    except (ssl.SSLError, OSError, ValueError):
        return False
    exe = shutil.which("openssl")
    if exe:
        try:
            r = subprocess.run([exe, "x509", "-in", str(cert), "-noout", "-checkend", str(RENEW_BEFORE_S)],
                               capture_output=True, timeout=30)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
    return True


def ensure_identity(state_dir: Path, *, device_id: str = "pigeon") -> TlsIdentity:
    """Return the device's TLS identity, creating it on first use. Raises ``RuntimeError`` if it can't."""
    state_dir.mkdir(parents=True, exist_ok=True)
    cert, key = state_dir / CERT_NAME, state_dir / KEY_NAME
    if not _usable(cert, key):
        # Build in a private (0700) scratch dir, then move into place so a crash never leaves half a pair.
        tmp = Path(tempfile.mkdtemp(prefix=".tls-", dir=state_dir))
        try:
            tcert, tkey = tmp / "c.pem", tmp / "k.pem"
            cn = f"Pigeon {device_id}"
            if not (_generate_openssl(tcert, tkey, cn) or _generate_cryptography(tcert, tkey, cn)):
                raise RuntimeError("cannot create TLS certificate: need the `openssl` command or the "
                                   "`cryptography` package")
            os.chmod(tkey, 0o600)
            os.replace(tkey, key)
            os.replace(tcert, cert)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    try:
        os.chmod(key, 0o600)
    except OSError:
        pass
    return TlsIdentity(str(cert), str(key), fingerprint_of(cert))


def server_context(identity: TlsIdentity) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(identity.certfile, identity.keyfile)
    return ctx
