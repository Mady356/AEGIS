"""
V4 — Ed25519 device identity, real implementation.

On first run, generates a device keypair at ~/.aegis/keys/device.{key,pub}
with file mode 0600. Used by the handoff packet pipeline (backend/handoff.py)
to sign the encounter.json payload.

CLI:
    python -m backend.crypto_ed25519 init      # ensure keypair exists
    python -m backend.crypto_ed25519 fingerprint  # print pub-key fingerprint

Used at runtime via the public functions:
    sign_bundle(data: bytes) -> bytes
    verify_signature(data: bytes, signature: bytes, public_key: bytes) -> bool
    public_key_bytes() -> bytes
    public_fingerprint() -> str
    device_pub_path() -> Path
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization
    _CRYPTO_OK = True
except ImportError:
    Ed25519PrivateKey = None  # type: ignore
    Ed25519PublicKey = None  # type: ignore
    serialization = None  # type: ignore
    _CRYPTO_OK = False


def _aegis_home() -> Path:
    return Path(os.environ.get("AEGIS_HOME", str(Path.home() / ".aegis")))


def _keys_dir() -> Path:
    d = _aegis_home() / "keys"
    d.mkdir(parents=True, exist_ok=True)
    return d


def device_priv_path() -> Path:
    return _keys_dir() / "device.key"


def device_pub_path() -> Path:
    return _keys_dir() / "device.pub"


def _ensure_crypto():
    if not _CRYPTO_OK:
        raise RuntimeError(
            "cryptography library is required for Ed25519 signing. "
            "Install with: pip install cryptography"
        )


def init() -> tuple[Path, Path, str]:
    """Generate keypair if missing. Returns (priv_path, pub_path, fingerprint)."""
    _ensure_crypto()
    priv_p = device_priv_path()
    pub_p = device_pub_path()
    if priv_p.exists() and pub_p.exists():
        fp = public_fingerprint()
        return priv_p, pub_p, fp
    priv = Ed25519PrivateKey.generate()
    priv_p.write_bytes(priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    try:
        os.chmod(priv_p, 0o600)
    except Exception:
        pass
    pub = priv.public_key()
    pub_raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_p.write_bytes(pub_raw)
    try:
        os.chmod(pub_p, 0o644)
    except Exception:
        pass
    return priv_p, pub_p, hashlib.sha256(pub_raw).hexdigest()


def _load_priv() -> "Ed25519PrivateKey":
    _ensure_crypto()
    p = device_priv_path()
    if not p.exists():
        init()
    return serialization.load_pem_private_key(p.read_bytes(), password=None)


def _load_pub() -> "Ed25519PublicKey":
    _ensure_crypto()
    p = device_pub_path()
    if not p.exists():
        init()
    return Ed25519PublicKey.from_public_bytes(p.read_bytes())


def public_key_bytes() -> bytes:
    if not device_pub_path().exists():
        init()
    return device_pub_path().read_bytes()


def public_fingerprint() -> str:
    return hashlib.sha256(public_key_bytes()).hexdigest()


def sign_bundle(data: bytes) -> bytes:
    """Sign arbitrary bytes (typically the canonical-JSON encoding of the
    encounter record). Returns the raw 64-byte signature."""
    return _load_priv().sign(data)


def verify_signature(data: bytes, signature: bytes, public_key: bytes) -> bool:
    """Pure verification — independent of the signing key. Used both
    in-process and by the standalone verify_handoff.py script."""
    if not _CRYPTO_OK:
        raise RuntimeError("cryptography library is required for verification")
    pk = Ed25519PublicKey.from_public_bytes(public_key)
    try:
        pk.verify(signature, data)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------
# CLI: python -m backend.crypto_ed25519 init|fingerprint
# ---------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "init"
    if cmd == "init":
        priv, pub, fp = init()
        print(f"[crypto] device key initialized")
        print(f"  priv: {priv}")
        print(f"  pub:  {pub}")
        print(f"  fp:   ed25519/{fp}")
        return 0
    if cmd == "fingerprint":
        print(public_fingerprint())
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
