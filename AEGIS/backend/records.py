"""
Encounter + event persistence with SHA-256 chain.

Every event's `hash` is computed as
    SHA-256(canonical_payload || prev_hash || t_offset_ms || event_type)

The first event's prev_hash is derived from the encounter's started_at.
The chain validates with a single forward walk; corruption is detected
at the first event whose recomputed hash diverges.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from . import crypto, db
try:
    from .models import IntegrityResult
except ImportError:
    # Fallback for environments without pydantic — runtime tests use this.
    from dataclasses import dataclass
    from typing import Optional as _Optional
    @dataclass
    class IntegrityResult:  # type: ignore
        valid: bool
        event_count: int
        first_break_event_id: _Optional[int]
        verified_at: str
        chain_root: _Optional[str] = None
        def model_dump(self) -> dict:
            return {
                "valid": self.valid, "event_count": self.event_count,
                "first_break_event_id": self.first_break_event_id,
                "verified_at": self.verified_at, "chain_root": self.chain_root,
            }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _new_id() -> str:
    return f"ENC-{uuid.uuid4().hex[:12]}"


def create_encounter(scenario_id: str, patient_label: str) -> dict:
    eid = _new_id()
    started = _now_iso()
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO encounters (id, scenario_id, patient_label, started_at) "
            "VALUES (?, ?, ?, ?)",
            (eid, scenario_id, patient_label, started),
        )
        conn.execute(
            "INSERT INTO audit_log (encounter_id, action, actor, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (eid, "encounter_create", "operator", started),
        )
        conn.commit()
    # First event records the start. Its prev_hash seeds from started_at.
    add_event(eid, "encounter_started",
              {"scenario_id": scenario_id, "patient_label": patient_label}, 0)
    return {
        "id": eid,
        "scenario_id": scenario_id,
        "patient_label": patient_label,
        "started_at": started,
    }


def end_encounter(encounter_id: str) -> dict:
    ended = _now_iso()
    add_event(encounter_id, "encounter_ended", {}, _t_offset(encounter_id, ended))
    integrity = _compute_integrity_hash(encounter_id)
    with db.connection() as conn:
        conn.execute(
            "UPDATE encounters SET ended_at = ?, integrity_hash = ? WHERE id = ?",
            (ended, integrity, encounter_id),
        )
        conn.commit()
    return {"id": encounter_id, "ended_at": ended, "integrity_hash": integrity}


def _last_hash(conn: sqlite3.Connection, encounter_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT hash FROM events WHERE encounter_id = ? ORDER BY id DESC LIMIT 1",
        (encounter_id,),
    ).fetchone()
    return row["hash"] if row else None


def _started_at(conn: sqlite3.Connection, encounter_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT started_at FROM encounters WHERE id = ?", (encounter_id,)
    ).fetchone()
    return row["started_at"] if row else None


def _t_offset(encounter_id: str, now_iso: str) -> int:
    with db.connection() as conn:
        started = _started_at(conn, encounter_id)
    if not started:
        return 0
    s = datetime.fromisoformat(started)
    n = datetime.fromisoformat(now_iso)
    return int((n - s).total_seconds() * 1000)


def add_event(encounter_id: str,
              event_type: str,
              payload: dict,
              t_offset_ms: Optional[int] = None) -> int:
    """Append an event. Returns the event id."""
    created = _now_iso()
    if t_offset_ms is None:
        t_offset_ms = _t_offset(encounter_id, created)

    with db.connection() as conn:
        prev = _last_hash(conn, encounter_id)
        if prev is None:
            # First event seeds from started_at
            seed = _started_at(conn, encounter_id) or created
            prev = crypto.chain_root(seed)
        h = crypto.event_hash(event_type, t_offset_ms, payload, prev)
        cur = conn.execute(
            "INSERT INTO events (encounter_id, event_type, t_offset_ms, "
            "payload_json, hash, prev_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (encounter_id, event_type, t_offset_ms,
             crypto.canonical_payload(payload), h, prev, created),
        )
        conn.commit()
        return cur.lastrowid


def get_encounter(encounter_id: str) -> Optional[dict]:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM encounters WHERE id = ?", (encounter_id,)
        ).fetchone()
        if not row:
            return None
        events = [
            _row_to_event(r) for r in conn.execute(
                "SELECT * FROM events WHERE encounter_id = ? ORDER BY id",
                (encounter_id,),
            ).fetchall()
        ]
    return {
        "id": row["id"],
        "scenario_id": row["scenario_id"],
        "patient_label": row["patient_label"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "integrity_hash": row["integrity_hash"],
        "events": events,
    }


def _row_to_event(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "encounter_id": r["encounter_id"],
        "event_type": r["event_type"],
        "t_offset_ms": r["t_offset_ms"],
        "payload": json.loads(r["payload_json"]),
        "hash": r["hash"],
        "prev_hash": r["prev_hash"],
        "created_at": r["created_at"],
    }


def get_encounter_steps(encounter_id: str) -> Optional[dict]:
    """V6 — Return the most recent ``encounter_steps_set`` event payload,
    or None if the encounter is hardcoded-scenario-driven (or unknown).

    The payload shape, as written by ``/api/encounter/begin``:
        {"title": str, "steps": [step_dict, ...]}
    """
    rec = get_encounter(encounter_id)
    if rec is None:
        return None
    latest: Optional[dict] = None
    latest_t = -1
    for ev in rec.get("events") or []:
        if ev.get("event_type") != "encounter_steps_set":
            continue
        t = int(ev.get("t_offset_ms") or 0)
        if t >= latest_t:
            latest_t = t
            latest = ev.get("payload") or {}
    return latest


def list_encounters(active_only: bool = False) -> list[dict]:
    with db.connection() as conn:
        q = "SELECT * FROM encounters"
        if active_only:
            q += " WHERE ended_at IS NULL"
        q += " ORDER BY started_at DESC"
        rows = conn.execute(q).fetchall()
        out = []
        for r in rows:
            cnt = conn.execute(
                "SELECT COUNT(*) AS c FROM events WHERE encounter_id = ?",
                (r["id"],),
            ).fetchone()["c"]
            out.append({
                "id": r["id"],
                "scenario_id": r["scenario_id"],
                "patient_label": r["patient_label"],
                "started_at": r["started_at"],
                "ended_at": r["ended_at"],
                "event_count": cnt,
            })
        return out


def verify_encounter_integrity(encounter_id: str) -> IntegrityResult:
    """Walk the chain, return result. The most-called expensive function;
    measured at ~3ms for a 200-event encounter."""
    verified_at = _now_iso()
    with db.connection() as conn:
        started = _started_at(conn, encounter_id)
        if started is None:
            return IntegrityResult(
                valid=False, event_count=0,
                first_break_event_id=None, verified_at=verified_at,
            )
        rows = conn.execute(
            "SELECT * FROM events WHERE encounter_id = ? ORDER BY id",
            (encounter_id,),
        ).fetchall()

    expected_prev = crypto.chain_root(started)
    chain_root = expected_prev
    for r in rows:
        # V4 §2.4 fix — single hash implementation. Verifier reuses
        # crypto.event_hash exclusively. Two-implementation drift eliminated.
        try:
            payload = json.loads(r["payload_json"])
        except Exception:
            # Broken JSON is itself a tamper — feed an empty dict so the
            # canonical recomputation is well-defined and the mismatch
            # reports the break at this event.
            payload = {"__corrupt__": r["payload_json"]}
        recomputed = crypto.event_hash(
            r["event_type"], r["t_offset_ms"], payload, expected_prev,
        )
        if recomputed != r["hash"] or r["prev_hash"] != expected_prev:
            return IntegrityResult(
                valid=False, event_count=len(rows),
                first_break_event_id=r["id"], verified_at=verified_at,
                chain_root=chain_root,
            )
        expected_prev = r["hash"]
    return IntegrityResult(
        valid=True, event_count=len(rows),
        first_break_event_id=None, verified_at=verified_at,
        chain_root=chain_root,
    )


def _compute_integrity_hash(encounter_id: str) -> str:
    """Cumulative hash over the chain — stored on encounter close."""
    import hashlib
    h = hashlib.sha256()
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT hash FROM events WHERE encounter_id = ? ORDER BY id",
            (encounter_id,),
        ).fetchall()
    for r in rows:
        h.update(r["hash"].encode()); h.update(b"\n")
    return h.hexdigest()


def event_counts() -> dict:
    with db.connection() as conn:
        ec = conn.execute("SELECT COUNT(*) AS c FROM encounters").fetchone()["c"]
        evc = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
    return {"encounters": ec, "events": evc, "encrypted": db.is_encrypted()}


# ----- Tampering helper for the demo (V3-style Ctrl+Shift+T) -----

def tamper_byte(encounter_id: str, event_id: int) -> bool:
    """Flip a single byte in payload_json of the given event. Used by
    the live tamper demo. Returns True if the byte was successfully
    mutated."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT payload_json FROM events WHERE id = ? AND encounter_id = ?",
            (event_id, encounter_id),
        ).fetchone()
        if not row:
            return False
        payload = row["payload_json"]
        if not payload:
            return False
        # Flip the last byte (preserves JSON shape if last is a digit/letter)
        b = bytearray(payload, "utf-8")
        b[-1] = b[-1] ^ 0x01
        new = b.decode("utf-8", errors="replace")
        conn.execute(
            "UPDATE events SET payload_json = ? WHERE id = ?", (new, event_id),
        )
        conn.commit()
    return True


def heal_byte(encounter_id: str, event_id: int) -> bool:
    """Inverse of tamper_byte — flip the same bit back."""
    return tamper_byte(encounter_id, event_id)
