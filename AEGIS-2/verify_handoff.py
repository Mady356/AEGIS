#!/usr/bin/env python3
"""
verify_handoff.py — Standalone signature verifier for an AEGIS handoff packet.

Usage:
    python verify_handoff.py encounter.json [encounter.json.sig] [device.pub]

If the .sig and .pub paths aren't given, defaults to the same directory.

This script has one dependency: cryptography. Install with:
    pip install cryptography

Output ends with VALID or INVALID. Exit code reflects the result.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def _exit(msg: str, code: int = 1) -> None:
    print(msg)
    sys.exit(code)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        _exit(__doc__.strip(), 2)

    encounter_path = Path(argv[1]).resolve()
    sig_path = Path(argv[2]).resolve() if len(argv) > 2 else encounter_path.with_suffix(
        encounter_path.suffix + ".sig"
    )
    pub_path = Path(argv[3]).resolve() if len(argv) > 3 else encounter_path.parent / "device.pub"

    for p in (encounter_path, sig_path, pub_path):
        if not p.exists():
            _exit(f"missing file: {p}", 2)

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        _exit("cryptography library required. pip install cryptography", 3)

    encounter_bytes = encounter_path.read_bytes()
    sig_hex = sig_path.read_text().strip()
    pub_bytes = pub_path.read_bytes()

    print(f"Verifying signature against {pub_path.name}...")
    pk = Ed25519PublicKey.from_public_bytes(pub_bytes)
    try:
        pk.verify(bytes.fromhex(sig_hex), encounter_bytes)
        print("Signature: VALID ✓")
    except Exception as exc:
        print(f"Signature: INVALID ✗ ({exc})")
        return 1

    h = hashlib.sha256(encounter_bytes).hexdigest()
    print(f"Computing integrity hash...")
    print(f"Hash: {h}")

    try:
        import json
        rec = json.loads(encounter_bytes)
        print(f"Encounter: {rec.get('encounter_id', '?')}")
        print(f"Events: {len(rec.get('events') or [])}")
    except Exception:
        pass

    print("This packet has not been modified since signing. VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
