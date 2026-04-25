"""
V4 records — round-trip integrity test.

Per V4 §3.4:
  1. Create encounter
  2. Write 20 events of varying types
  3. Verify chain
  4. Manually corrupt a payload byte
  5. Confirm verification fails at the correct event
  6. Repair the byte
  7. Confirm verification succeeds again

Run:
    cd aegis
    python -m tests.test_records

Exits 0 on success, non-zero with a diagnostic on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, db, records  # noqa: E402

# Use a temp DB so the live store is untouched
config.DB_PATH = config.DATA_DIR / "test_records.db"
if config.DB_PATH.exists(): config.DB_PATH.unlink()


def main() -> int:
    db.migrate()

    enc = records.create_encounter("battlefield", "PT-TEST-001")
    eid = enc["id"]
    print(f"created encounter {eid}")

    types = ["vital_reading", "checklist_item_completed",
             "voice_input_started", "voice_input_finalized",
             "intake", "assessment", "guidance",
             "citation_viewed", "record_viewed"]
    for i in range(20):
        records.add_event(eid, types[i % len(types)],
                          {"i": i, "label": f"event-{i}"}, i * 1000)
    print("wrote 20 events")

    r = records.verify_encounter_integrity(eid)
    assert r.valid, f"baseline chain should verify, got: {r}"
    print(f"baseline chain verified — {r.event_count} events, valid={r.valid}")

    # Corrupt event id ~ 12 (zero-indexed by id sequence; the encounter_started
    # event is id 1, so user events start at id 2)
    target_id = 12
    ok = records.tamper_byte(eid, target_id)
    assert ok, "tamper_byte failed"
    r2 = records.verify_encounter_integrity(eid)
    assert not r2.valid, "chain should be broken after tamper"
    assert r2.first_break_event_id == target_id, (
        f"expected break at {target_id}, got {r2.first_break_event_id}"
    )
    print(f"tampered event {target_id} — chain detected break at "
          f"#{r2.first_break_event_id} ✓")

    records.heal_byte(eid, target_id)
    r3 = records.verify_encounter_integrity(eid)
    assert r3.valid, f"chain should verify after heal, got: {r3}"
    print(f"healed — chain verified, valid={r3.valid} ✓")

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
