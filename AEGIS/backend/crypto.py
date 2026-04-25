"""
Ed25519 device identity and event signing chain.

Production-grade crypto. Loads a per-device Ed25519 keypair (generates one
on first boot), signs each event in the chain with its predecessor's
signature mixed in, verifies chains on read.

Falls back gracefully if `cryptography` is not installed by raising at
import time — the FastAPI app should refuse to boot rather than ship
unsigned events. The preview server uses an HMAC-SHA256 chain instead;
see preview_server.py.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "cryptography library is required for production records. "
        "Install with `pip install cryptography`."
    ) from exc


KEYS_DIR = Path(__file__).resolve().parent.parent / "aegis_data" / "keys"
PRIV_PATH = KEYS_DIR / "device.key"
PUB_PATH = KEYS_DIR / "device.pub"


def _ensure_keys() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    if PRIV_PATH.exists():
        with PRIV_PATH.open("rb") as fh:
            priv = serialization.load_pem_private_key(fh.read(), password=None)
    else:
        priv = Ed25519PrivateKey.generate()
        with PRIV_PATH.open("wb") as fh:
            fh.write(priv.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ))
        os.chmod(PRIV_PATH, 0o600)
    pub = priv.public_key()
    if not PUB_PATH.exists():
        PUB_PATH.write_bytes(pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ))
    return priv, pub


_PRIV, _PUB = _ensure_keys()
_PUB_RAW = _PUB.public_bytes(encoding=serialization.Encoding.Raw,
                             format=serialization.PublicFormat.Raw)
_PUB_FP = hashlib.sha256(_PUB_RAW).hexdigest()


def public_fingerprint() -> str:
    return _PUB_FP


def public_key_pem() -> str:
    return _PUB.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def event_canonical(ev: dict, prev_sig: str) -> bytes:
    return json.dumps({
        "et": ev["event_type"],
        "t":  ev.get("t_offset_ms"),
        "p":  json.dumps(ev.get("payload") or {}, sort_keys=True),
        "c":  ev["created_at"],
        "ps": prev_sig,
    }, sort_keys=True, separators=(",", ":")).encode()


def sign_event(ev: dict, prev_sig: str) -> str:
    canonical = event_canonical(ev, prev_sig)
    sig = _PRIV.sign(canonical)
    return sig.hex()


def sign_bytes(data: bytes) -> str:
    return _PRIV.sign(data).hex()


def verify_event(ev: dict, prev_sig: str, signature_hex: str) -> bool:
    canonical = event_canonical(ev, prev_sig)
    try:
        _PUB.verify(bytes.fromhex(signature_hex), canonical)
        return True
    except Exception:
        return False


def verify_chain(events: list[dict]) -> tuple[bool, Optional[int]]:
    """Walk the chain. Return (ok, broken_event_id_or_None)."""
    prev_sig = "GENESIS"
    for ev in events:
        if not verify_event(ev, prev_sig, ev.get("signature", "")):
            return False, ev["id"]
        prev_sig = ev["signature"]
    return True, None
