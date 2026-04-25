"""
Deployment profile loader.

Profiles are JSON documents under aegis_data/profiles/. Each defines:
  - corpus tag filters (which RAG chunks are eligible)
  - default scenario set
  - available calculators
  - formulary filter for the interaction engine
  - default system prompt modifiers
  - network monitor probe configuration
  - UI customizations (within the established visual vocabulary)

Switching profiles ends the active encounter, archives or hands off,
reloads the affected subsystems, and re-runs the boot sequence.
"""

from __future__ import annotations
import json
from pathlib import Path

PROFILES_DIR = Path(__file__).resolve().parent.parent / "aegis_data" / "profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

DEFAULTS = {
    "combat_medic": {
        "id": "combat_medic",
        "name": "Combat Medic",
        "description": "TCCC-prioritized corpus, combat trauma formulary, military triage doctrine.",
        "corpus_summary": "TCCC · JTS CPG · NAVMED",
        "corpus_tags": ["combat"],
        "scenarios": ["battlefield", "maritime"],
        "default_scenario": "battlefield",
        "calculators": ["gcs", "shock_index", "map", "parkland", "ped_dose"],
        "formulary": ["txa", "ketamine", "fentanyl", "midazolam",
                      "ondansetron", "ceftriaxone", "morphine", "epinephrine"],
        "probe_targets": ["1.1.1.1:53", "8.8.8.8:53"],
        "system_prompt_modifier": "EMCON-aware: prefer brief responses; cite TCCC liberally.",
    },
    "submarine_corpsman": {
        "id": "submarine_corpsman",
        "name": "Submarine Corpsman",
        "description": "Submarine medicine, limited onboard formulary, decompression and cardiac priorities.",
        "corpus_summary": "NAVMED P-5052 · ILCOR Maritime Addendum",
        "corpus_tags": ["maritime"],
        "scenarios": ["maritime"],
        "default_scenario": "maritime",
        "calculators": ["gcs", "shock_index", "map", "qsofa", "ped_dose"],
        "formulary": ["epinephrine", "amiodarone", "atropine", "lidocaine",
                      "magnesium", "midazolam", "fentanyl"],
        "probe_targets": [],   # no ambient outbound probe under EMCON
        "system_prompt_modifier": "Surface evacuation 90+ minutes out; EMCON; decompression context first.",
    },
    "disaster_response": {
        "id": "disaster_response",
        "name": "Disaster Response",
        "description": "Mass-casualty optimized queue, START/JumpSTART triage, broader formulary.",
        "corpus_summary": "WHO Emergency Care · WHO IMAI",
        "corpus_tags": ["disaster", "pediatric", "pharmacology"],
        "scenarios": ["disaster", "battlefield"],
        "default_scenario": "disaster",
        "calculators": ["gcs", "qsofa", "ped_dose", "ett_size", "shock_index", "map"],
        "formulary": ["paracetamol", "ibuprofen", "epinephrine", "ondansetron",
                      "ceftriaxone", "dexamethasone"],
        "probe_targets": ["1.1.1.1:53", "8.8.8.8:53"],
        "system_prompt_modifier": "Triage doctrine: START/JumpSTART; prefer escalation over guess.",
    },
    "rural_clinic": {
        "id": "rural_clinic",
        "name": "Rural Clinic",
        "description": "Primary care corpus, chronic disease management, referral pathway emphasis.",
        "corpus_summary": "WHO Primary Care · WHO IMAI",
        "corpus_tags": ["disaster", "pediatric", "pharmacology"],
        "scenarios": ["disaster"],
        "default_scenario": "disaster",
        "calculators": ["map", "ped_dose", "wells_pe", "qsofa"],
        "formulary": ["paracetamol", "ibuprofen", "metformin", "warfarin",
                      "ceftriaxone", "dexamethasone"],
        "probe_targets": ["1.1.1.1:53", "8.8.8.8:53"],
        "system_prompt_modifier": "Longer-form responses; emphasize referral pathways.",
    },
    "correctional_facility": {
        "id": "correctional_facility",
        "name": "Correctional Facility",
        "description": "Emergency medicine corpus, careful medication tracking, forensic documentation enabled.",
        "corpus_summary": "Emergency Medicine · DEA scheduling",
        "corpus_tags": ["combat", "disaster"],
        "scenarios": ["battlefield", "disaster"],
        "default_scenario": "battlefield",
        "calculators": ["gcs", "shock_index", "map", "qsofa"],
        "formulary": ["fentanyl", "morphine", "midazolam", "naloxone",
                      "epinephrine", "lorazepam"],
        "probe_targets": [],   # no ambient outbound probe
        "system_prompt_modifier": "Forensic chain-of-custody emphasis; controlled-substance flagging.",
    },
}


def list_profiles() -> list[dict]:
    out = []
    for pid, default in DEFAULTS.items():
        path = PROFILES_DIR / f"{pid}.json"
        if path.exists():
            try:
                with path.open() as fh: out.append(json.load(fh))
                continue
            except Exception:
                pass
        out.append(default)
    return out


def get_profile(pid: str) -> dict | None:
    for p in list_profiles():
        if p["id"] == pid:
            return p
    return None


def write_defaults() -> None:
    """Idempotent: write DEFAULTS to disk if not already present."""
    for pid, p in DEFAULTS.items():
        path = PROFILES_DIR / f"{pid}.json"
        if not path.exists():
            path.write_text(json.dumps(p, indent=2))
