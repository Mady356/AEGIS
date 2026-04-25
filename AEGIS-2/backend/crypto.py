"""
V4 hashing utilities — SHA-256 chain over canonical event JSON.

V5 will upgrade this chain to Ed25519 signatures. The hash column
becomes the canonical input that gets signed; the schema is unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional


def canonical_payload(payload: dict) -> str:
    """Stable, sort_keys serialization. The same payload always hashes
    to the same value regardless of dict insertion order."""
    return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))


def event_hash(event_type: str,
               t_offset_ms: int,
               payload: dict,
               prev_hash: Optional[str]) -> str:
    """SHA-256 over (canonical_payload || prev_hash || t_offset_ms || event_type).

    The first event in an encounter passes the encounter's started_at as
    prev_hash. Each subsequent event chains forward.
    """
    h = hashlib.sha256()
    h.update(canonical_payload(payload).encode("utf-8"))
    h.update(b"|")
    h.update((prev_hash or "GENESIS").encode("utf-8"))
    h.update(b"|")
    h.update(str(t_offset_ms).encode("utf-8"))
    h.update(b"|")
    h.update(event_type.encode("utf-8"))
    return h.hexdigest()


def chain_root(prev_hash: str) -> str:
    """Deterministic root hash for a fresh encounter."""
    return hashlib.sha256((prev_hash + "|root").encode()).hexdigest()
