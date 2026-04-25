"""
Multi-patient encounter queue.

Wraps the records subsystem with queue-specific logic: list active
encounters ordered by triage severity, set/clear triage category,
restore active encounters on app boot.
"""

from __future__ import annotations
from . import records, scenarios

TRIAGE_ORDER = {"red": 0, "yellow": 1, "green": 2, "black": 3, None: 4}


def list_active() -> list[dict]:
    rows = records.list_active_encounters()
    out = []
    for r in rows:
        sc = scenarios.get(r["scenario_id"]) or {}
        out.append({
            "id": r["id"],
            "patient_label": r["patient_label"],
            "scenario_id": r["scenario_id"],
            "scenario_name": sc.get("name", r["scenario_id"]),
            "domain": sc.get("domain", ""),
            "case": sc.get("case", ""),
            "started_at": r["started_at"],
            "triage": r.get("triage"),
            "interactions_pending": r.get("interactions_pending", 0),
            "rppg_active": r.get("rppg_active", False),
        })
    out.sort(key=lambda x: TRIAGE_ORDER.get(x["triage"], 4))
    return out


def set_triage(encounter_id: int, category: str) -> None:
    if category not in ("red", "yellow", "green", "black"):
        raise ValueError(f"invalid triage category: {category}")
    records.update_encounter(encounter_id, triage=category)
    records.add_event(encounter_id, "triage", {"category": category})


def restore_on_boot() -> list[dict]:
    """Called at app startup to restore queue from any encounters with
    no ended_at timestamp."""
    return list_active()
