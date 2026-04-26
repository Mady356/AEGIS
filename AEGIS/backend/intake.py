"""
AEGIS — Guided Intake / Input Scaffolding.

Free-text input from non-expert users in a crisis is unreliable.
This module provides a small set of structured questions in plain
language and converts the responses into a clean encounter object
that the rest of the pipeline (triage, differential, protocol,
missed-signal detection) can consume.

Public API:
    get_default_intake_questions(context: str | None) -> list[dict]
    build_structured_encounter(responses: dict) -> dict
"""

from __future__ import annotations

from typing import Any


# --- Question bank ---------------------------------------------------------

_BASE_QUESTIONS: list[dict] = [
    {
        "id": "chief_complaint",
        "label": "What is happening?",
        "help": "In a few words. Example: chest pain, bleeding leg, "
                "trouble breathing.",
        "type": "text",
        "required": True,
    },
    {
        "id": "conscious",
        "label": "Is the patient awake and responding to you?",
        "help": "Talks, opens eyes, follows simple instructions.",
        "type": "choice",
        "options": ["yes", "no", "not sure"],
        "required": True,
    },
    {
        "id": "breathing_normal",
        "label": "Is the patient breathing normally?",
        "help": "Calm, steady breaths. Not gasping, not very fast, not stopped.",
        "type": "choice",
        "options": ["yes", "no", "not sure"],
        "required": True,
    },
    {
        "id": "visible_bleeding",
        "label": "Is there visible bleeding?",
        "help": "Any blood you can see on the body or clothes.",
        "type": "choice",
        "options": ["none", "small", "heavy", "not sure"],
        "required": True,
    },
    {
        "id": "vitals",
        "label": "Vitals if you have them.",
        "help": "Pulse (beats per minute), breathing rate, oxygen %, "
                "blood pressure. Skip any you don't have.",
        "type": "vitals",
        "required": False,
    },
    {
        "id": "context",
        "label": "Where are you, and what happened?",
        "help": "Example: refugee camp, submarine, after a fall, "
                "after a blast, in a vehicle.",
        "type": "text",
        "required": False,
    },
]


# Lightweight context-specific hints layered on top of the base questions.
_CONTEXT_HINTS = {
    "combat": "Note any blast, gunshot, or shrapnel exposure.",
    "refugee": "Note exposure: heat, cold, dehydration, days without care.",
    "submarine": "Note CO2, oxygen, and any recent depth or pressure change.",
    "disaster": "Note crush injury, dust inhalation, or trapped time.",
    "remote": "Note travel time to nearest care and available supplies.",
}


def get_default_intake_questions(context: str | None = None) -> list[dict]:
    """Return the structured intake questions, optionally annotated with
    a context-specific hint for the environment field.

    `context` is a free-form string; matching is loose so callers may
    pass scenario IDs ("submarine_co2_event") and still get a useful
    hint.
    """
    questions = [dict(q) for q in _BASE_QUESTIONS]  # shallow copy
    if context:
        ctx = context.lower()
        for key, hint in _CONTEXT_HINTS.items():
            if key in ctx:
                for q in questions:
                    if q["id"] == "context":
                        q["help"] = f"{q['help']} {hint}"
                break
    return questions


# --- Response normalization ------------------------------------------------

_YES = {"yes", "y", "true", "1"}
_NO = {"no", "n", "false", "0"}


def _tristate(value: Any) -> str | None:
    """Map yes/no/not-sure responses to a canonical string."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value).strip().lower()
    if not text:
        return None
    if text in _YES:
        return "yes"
    if text in _NO:
        return "no"
    if "not" in text or "unknown" in text or "?" in text:
        return "unknown"
    return text


def _bleeding(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"none", "no", "0"}:
        return "none"
    if text in {"small", "minor", "light"}:
        return "small"
    if text in {"heavy", "severe", "major", "lots", "lot"}:
        return "heavy"
    if "not" in text or "unknown" in text:
        return "unknown"
    return text


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _vitals(raw: Any) -> dict:
    """Normalize a vitals dict; skip empty fields."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    pulse = _coerce_int(raw.get("pulse") or raw.get("hr") or raw.get("heart_rate"))
    if pulse is not None:
        out["heart_rate"] = pulse
    rr = _coerce_int(raw.get("rr") or raw.get("respiratory_rate") or raw.get("breathing_rate"))
    if rr is not None:
        out["respiratory_rate"] = rr
    spo2 = _coerce_int(raw.get("spo2") or raw.get("oxygen") or raw.get("o2"))
    if spo2 is not None:
        out["spo2"] = spo2
    bp = raw.get("bp") or raw.get("blood_pressure")
    if isinstance(bp, str) and bp.strip():
        out["blood_pressure"] = bp.strip()
    elif isinstance(bp, dict):
        sys_, dia = _coerce_int(bp.get("systolic")), _coerce_int(bp.get("diastolic"))
        if sys_ is not None and dia is not None:
            out["blood_pressure"] = f"{sys_}/{dia}"
    temp = raw.get("temp") or raw.get("temperature")
    try:
        if temp not in (None, ""):
            out["temperature_c"] = float(temp)
    except (TypeError, ValueError):
        pass
    return out


# --- Symptom expansion -----------------------------------------------------

def _derived_symptoms(
    chief_complaint: str,
    conscious: str | None,
    breathing: str | None,
    bleeding: str | None,
) -> list[str]:
    """Build a coarse symptom list from the structured answers so the
    downstream rule engines have something to match on even when the
    user provides only the guided form."""
    symptoms: list[str] = []
    cc = (chief_complaint or "").strip()
    if cc:
        symptoms.append(cc)
    if conscious == "no":
        symptoms.append("unconscious")
    elif conscious == "unknown":
        symptoms.append("mental status unknown")
    if breathing == "no":
        symptoms.append("abnormal breathing")
    elif breathing == "unknown":
        symptoms.append("breathing status unknown")
    if bleeding == "heavy":
        symptoms.append("severe bleeding")
    elif bleeding == "small":
        symptoms.append("minor bleeding")
    return symptoms


# --- Public API ------------------------------------------------------------

def build_structured_encounter(
    responses: dict | None,
    scenario: dict | None = None,
) -> dict:
    """Convert guided-form responses into a clean encounter object.

    The output shape is intentionally simple and stable so that the
    rest of the pipeline can rely on it:

        {
            "chief_complaint": str,
            "mental_status": "yes" | "no" | "unknown" | None,
            "breathing": "yes" | "no" | "unknown" | None,
            "bleeding": "none" | "small" | "heavy" | "unknown" | None,
            "vitals": {...},
            "context": str,
            "symptoms": [str, ...],
            "source": "guided_intake",
            "scenario_context"?: {id, case, primer_prompt, steps}
        }

    When `scenario` is provided, its primer_prompt fills missing
    chief_complaint, its case/domain hint extends the context, and the
    full scenario context is attached as `scenario_context` so the LLM
    bundle (and downstream consumers) can align with the active
    scenario.
    """
    responses = responses or {}

    chief_complaint = str(
        responses.get("chief_complaint")
        or responses.get("what_is_happening")
        or responses.get("complaint")
        or ""
    ).strip()

    conscious = _tristate(responses.get("conscious") or responses.get("awake"))
    breathing = _tristate(
        responses.get("breathing_normal")
        or responses.get("breathing")
    )
    bleeding = _bleeding(
        responses.get("visible_bleeding") or responses.get("bleeding")
    )
    vitals = _vitals(responses.get("vitals"))
    context = str(
        responses.get("context")
        or responses.get("environment")
        or ""
    ).strip()

    # Scenario backfill: if the operator didn't type a chief complaint,
    # use the scenario's primer_prompt as a stand-in. The "context" is
    # also seeded with the case label so the model has a domain hint.
    if scenario:
        if not chief_complaint:
            chief_complaint = (scenario.get("case")
                               or scenario.get("name")
                               or "").strip()
        if not context:
            domain = (scenario.get("domain") or "").strip()
            primer = (scenario.get("primer_prompt") or "").strip()
            context = " ".join(p for p in (domain, primer) if p).strip()

    symptoms = _derived_symptoms(chief_complaint, conscious, breathing, bleeding)

    encounter: dict = {
        "chief_complaint": chief_complaint,
        "mental_status": conscious,
        "breathing": breathing,
        "bleeding": bleeding,
        "vitals": vitals,
        "context": context,
        "symptoms": symptoms,
        "source": "guided_intake",
    }
    if scenario:
        encounter["scenario_context"] = {
            "id": scenario.get("id"),
            "case": scenario.get("case"),
            "primer_prompt": scenario.get("primer_prompt"),
            "steps": list(scenario.get("steps") or []),
        }
    return encounter
