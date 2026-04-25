from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
AEGIS_BACKEND = ROOT / "AEGIS" / "backend"


def _load_module(filename: str, module_name: str) -> ModuleType | None:
    path = AEGIS_BACKEND / filename
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_profiles = _load_module("profiles.py", "aegis_profiles")
_scenarios = _load_module("scenarios.py", "aegis_scenarios")
_calculators = _load_module("calculators.py", "aegis_calculators")
_interactions = _load_module("interactions.py", "aegis_interactions")
_queue = _load_module("queue.py", "aegis_queue")
_handoff = _load_module("handoff.py", "aegis_handoff")


def list_profiles() -> list[dict]:
    if _profiles and hasattr(_profiles, "list_profiles"):
        return _profiles.list_profiles()
    return []


def get_profile(profile_id: str | None) -> dict | None:
    if not profile_id:
        return None
    if _profiles and hasattr(_profiles, "get_profile"):
        return _profiles.get_profile(profile_id)
    return None


def list_scenarios() -> list[dict]:
    if _scenarios and hasattr(_scenarios, "public_list"):
        return _scenarios.public_list()
    return []


def get_scenario(scenario_id: str | None) -> dict | None:
    if not scenario_id:
        return None
    if _scenarios and hasattr(_scenarios, "get"):
        return _scenarios.get(scenario_id)
    return None


def scenario_seed_encounter(scenario_id: str | None) -> dict | None:
    scenario = get_scenario(scenario_id)
    if not scenario:
        return None
    return {
        "encounter_id": f"scenario-{scenario['id']}",
        "age": None,
        "sex": "unknown",
        "chief_complaint": scenario.get("case", ""),
        "symptoms": scenario.get("tags", []),
        "context": scenario.get("domain", ""),
        "notes": scenario.get("primer_prompt", ""),
        "vitals": {},
        "metadata": {"scenario_id": scenario["id"]},
    }


def run_calculator(name: str, **kwargs: Any) -> dict | None:
    if not _calculators or not hasattr(_calculators, "REGISTRY"):
        return None
    fn = _calculators.REGISTRY.get(name)
    if not fn:
        return None
    return fn(**kwargs)


def check_medication_safety(drug: str, admin_history: list[str], allergies: list[str]) -> list[dict]:
    if not _interactions or not hasattr(_interactions, "check"):
        return []
    return _interactions.check(drug, admin_history, allergies)


def build_integration_snapshot(encounter: dict) -> dict:
    metadata = encounter.get("metadata") or {}
    profile_id = metadata.get("profile_id")
    scenario_id = metadata.get("scenario_id")
    return {
        "profile": get_profile(profile_id),
        "scenario": get_scenario(scenario_id),
        "available_profiles": [p.get("id") for p in list_profiles()],
        "available_scenarios": [s.get("id") for s in list_scenarios()],
        "module_availability": {
            "profiles": _profiles is not None,
            "scenarios": _scenarios is not None,
            "calculators": _calculators is not None,
            "interactions": _interactions is not None,
            "queue": _queue is not None,
            "handoff": _handoff is not None,
        },
    }
