from __future__ import annotations

from typing import Literal, TypedDict, NotRequired


Acuity = Literal["red", "yellow", "green"]
Likelihood = Literal["low", "medium", "high"]
Danger = Literal["low", "medium", "high", "critical"]
CheckSafety = Literal["high", "medium", "low"]


class Vitals(TypedDict):
    heart_rate: float | None
    systolic_bp: float | None
    diastolic_bp: float | None
    respiratory_rate: float | None
    oxygen_saturation: float | None
    temperature_c: float | None
    mental_status: str


class Encounter(TypedDict):
    encounter_id: str
    age: int | None
    sex: str
    chief_complaint: str
    symptoms: list[str]
    context: str
    notes: str
    vitals: Vitals
    metadata: dict


class DifferentialItem(TypedDict):
    condition: str
    likelihood: Likelihood
    danger_if_missed: Danger
    supporting_evidence: list[str]
    evidence_against: list[str]
    must_not_miss: bool
    least_risky_next_checks: list[str]
    least_risky_check_safety: CheckSafety
    why_prioritized: str
    priority_score: NotRequired[float]
    priority_category: NotRequired[str]


class PipelineResponse(TypedDict):
    encounter: Encounter
    crisis_view: dict
    triage: dict
    differential: dict
    protocol: dict
    missed_signals: dict
    questions: dict
    safety: dict
    reasoning_trace: list[dict]
    audit: dict
    handoff: dict
    timeline: list[dict]
    offline_status: dict
    integrations: dict
