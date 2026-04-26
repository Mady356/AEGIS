"""
AEGIS — Fail-Safe Mode.

If there isn't enough information to reason safely, AEGIS must NOT
guess or hallucinate. It stops and asks the essential questions
first.

Public API:
    check_insufficient_data(encounter: dict) -> dict | None

Returns None when the encounter has enough to proceed; otherwise
returns a structured fail-safe response that the orchestrator emits
in place of a normal pipeline result.
"""

from __future__ import annotations

from typing import Any

# Free-text keywords in the chief complaint or environment that mark a
# situation as high-risk. When any of these are present, we require the
# three life-threat screens (conscious / breathing / bleeding) before
# continuing.
_HIGH_RISK_KEYWORDS = (
    "chest pain", "chest", "trauma", "blast", "gunshot", "gsw",
    "stab", "fall", "crush", "unconscious", "unresponsive",
    "not breathing", "no pulse", "severe bleed", "heavy bleed",
    "head injury", "stroke", "seizure", "drown", "burn",
    "anaphyl", "allergic", "overdose", "poison", "shock",
)


# --- Helpers ---------------------------------------------------------------

def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _has_chief_complaint(encounter: dict) -> bool:
    cc = _str(
        encounter.get("chief_complaint")
        or encounter.get("complaint")
        or encounter.get("presenting_complaint")
    )
    return bool(cc)


def _has_symptoms(encounter: dict) -> bool:
    sym = encounter.get("symptoms")
    if isinstance(sym, (list, tuple)):
        return any(_str(s) for s in sym)
    return bool(_str(sym))


def _has_vitals(encounter: dict) -> bool:
    v = encounter.get("vitals")
    if isinstance(v, dict):
        return any(val not in (None, "", {}) for val in v.values())
    if isinstance(v, (list, tuple)):
        return len(v) > 0
    return False


def _is_unknown(value: Any) -> bool:
    """True if the field is missing or explicitly 'not sure / unknown'."""
    if value in (None, "", {}, []):
        return True
    text = _str(value).lower()
    return text in {"unknown", "not sure", "?", "n/a", "na"}


def _is_high_risk_context(encounter: dict) -> bool:
    haystack = " ".join([
        _str(encounter.get("chief_complaint")),
        _str(encounter.get("complaint")),
        _str(encounter.get("context")),
        _str(encounter.get("environment")),
        _str(encounter.get("scenario_id")),
    ]).lower()
    return any(k in haystack for k in _HIGH_RISK_KEYWORDS)


# --- Public API ------------------------------------------------------------

def check_insufficient_data(encounter: dict | None) -> dict | None:
    """Return a fail-safe response if the encounter is too thin to
    reason on, otherwise None.

    Triggers:
        1. Chief complaint is missing.
        2. No symptoms AND no vitals are present.
        3. In a high-risk context, mental status / breathing / bleeding
           are all unknown.
    """
    encounter = encounter or {}

    questions: list[str] = []
    reasons: list[str] = []

    if not _has_chief_complaint(encounter):
        reasons.append("missing_chief_complaint")
        questions.append("What is the main problem right now?")

    if not _has_symptoms(encounter) and not _has_vitals(encounter):
        reasons.append("no_symptoms_or_vitals")
        if "What is the main problem right now?" not in questions:
            questions.append("What is the main problem right now?")
        questions.append(
            "Any vitals you can measure (pulse, breathing rate, oxygen)?"
        )

    # Skip the high-risk life-threats check when the encounter carries
    # an explicit scenario_context — the scenario's primer_prompt and
    # case stand in for the binary safety answers (otherwise selecting
    # a battlefield/maritime scenario without typing in conscious/
    # breathing/bleeding would short-circuit before the LLM ever runs).
    if _is_high_risk_context(encounter) and not encounter.get("scenario_context"):
        unknown_mental = _is_unknown(encounter.get("mental_status"))
        unknown_breathing = _is_unknown(encounter.get("breathing"))
        unknown_bleeding = _is_unknown(encounter.get("bleeding"))
        if unknown_mental and unknown_breathing and unknown_bleeding:
            reasons.append("high_risk_life_threats_unknown")
            for q in (
                "Is the patient conscious?",
                "Is the patient breathing normally?",
                "Is there visible severe bleeding?",
            ):
                if q not in questions:
                    questions.append(q)

    if not reasons:
        return None

    # De-duplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for q in questions:
        if q not in seen:
            seen.add(q)
            deduped.append(q)

    return {
        "status": "insufficient_data",
        "message": "Not enough information to proceed safely.",
        "questions": deduped,
        "reasons": reasons,
    }
