"""
Structured decision-support pipeline for AEGIS-2.

This module intentionally keeps outputs as deterministic JSON so the
production backend remains robust even when LLM services are degraded.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import retrieval


LIKELIHOOD = {"low": 1, "medium": 2, "high": 3}
DANGER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
CHECK_SAFETY = {"high": 1, "medium": 2, "low": 3}


def _as_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_bp(value: object) -> tuple[float | None, float | None]:
    if isinstance(value, str) and "/" in value:
        left, right = value.split("/", 1)
        return _as_float(left.strip()), _as_float(right.strip())
    if isinstance(value, dict):
        return _as_float(value.get("systolic")), _as_float(value.get("diastolic"))
    return None, None


def normalize_encounter(encounter: dict | None) -> dict:
    raw = encounter or {}
    vitals_in = raw.get("vitals") or {}
    sbp, dbp = _parse_bp(vitals_in.get("blood_pressure"))
    if sbp is None:
        sbp = _as_float(vitals_in.get("systolic_bp") or vitals_in.get("bp_systolic"))
    if dbp is None:
        dbp = _as_float(vitals_in.get("diastolic_bp") or vitals_in.get("bp_diastolic"))

    return {
        "encounter_id": raw.get("encounter_id", "encounter-local"),
        "age": raw.get("age"),
        "sex": raw.get("sex", "unknown"),
        "chief_complaint": str(raw.get("chief_complaint", "")),
        "symptoms": [str(s) for s in (raw.get("symptoms") or [])],
        "context": str(raw.get("context", "")),
        "notes": str(raw.get("notes", "")),
        "vitals": {
            "heart_rate": _as_float(vitals_in.get("heart_rate") or vitals_in.get("hr")),
            "systolic_bp": sbp,
            "diastolic_bp": dbp,
            "respiratory_rate": _as_float(vitals_in.get("respiratory_rate") or vitals_in.get("rr")),
            "oxygen_saturation": _as_float(vitals_in.get("oxygen_saturation") or vitals_in.get("spo2")),
            "temperature_c": _as_float(vitals_in.get("temperature") or vitals_in.get("temp")),
            "mental_status": str(vitals_in.get("mental_status", "unknown")),
        },
        "metadata": raw.get("metadata") or {},
    }


def deterministic_triage(encounter: dict) -> dict:
    vitals = encounter.get("vitals") or {}
    hr = vitals.get("heart_rate")
    rr = vitals.get("respiratory_rate")
    spo2 = vitals.get("oxygen_saturation")
    sbp = vitals.get("systolic_bp")
    mental = str(vitals.get("mental_status") or "").lower()

    red_flags: list[str] = []
    forced_acuity = None
    if sbp is not None and sbp < 90:
        red_flags.append("Hypotension: systolic blood pressure below 90")
        forced_acuity = "red"
    if hr is not None and hr > 120:
        red_flags.append("Severe tachycardia: heart rate above 120")
        forced_acuity = "red"
    if spo2 is not None and spo2 < 92:
        red_flags.append("Low oxygen saturation below 92%")
        forced_acuity = "red"
    if rr is not None and rr > 30:
        red_flags.append("Severe tachypnea: respiratory rate above 30")
        forced_acuity = "red"
    if any(term in mental for term in ("confused", "unresponsive", "altered", "lethargic")):
        red_flags.append("Altered mental status")
        forced_acuity = "red"

    text = (encounter.get("chief_complaint", "") + " " + " ".join(encounter.get("symptoms") or [])).lower()
    if "chest pain" in text and ("shortness of breath" in text or "sweat" in text):
        red_flags.append("Chest pain with concerning associated symptoms")
    if "bleeding" in text or "hemorrhage" in text:
        red_flags.append("Possible uncontrolled hemorrhage")
        forced_acuity = "red"

    return {
        "forced_acuity": forced_acuity,
        "detected_red_flags": sorted(set(red_flags)),
        "rule_source": "deterministic_vitals_and_red_flag_screen",
    }


def _rank_differentials(differentials: list[dict]) -> list[dict]:
    scored: list[dict] = []
    for item in differentials:
        likelihood = str(item.get("likelihood", "medium")).lower().strip()
        danger = str(item.get("danger_if_missed", "medium")).lower().strip()
        check_safety = str(item.get("least_risky_check_safety", "medium")).lower().strip()
        priority_score = (1.2 * LIKELIHOOD.get(likelihood, 2)) + (2.0 * DANGER.get(danger, 2)) - (
            0.7 * CHECK_SAFETY.get(check_safety, 2)
        )
        out = dict(item)
        out["priority_score"] = round(priority_score, 2)
        if DANGER.get(danger, 2) >= 4:
            out["priority_category"] = "critical rule-out"
        elif priority_score >= 7:
            out["priority_category"] = "high priority"
        elif priority_score >= 5:
            out["priority_category"] = "moderate priority"
        else:
            out["priority_category"] = "lower priority"
        scored.append(out)
    return sorted(scored, key=lambda x: x["priority_score"], reverse=True)


def _differential(encounter: dict) -> dict:
    text = (encounter.get("chief_complaint", "") + " " + " ".join(encounter.get("symptoms") or [])).lower()
    if "chest pain" in text or "shortness of breath" in text:
        candidates = [
            {
                "condition": "Acute coronary syndrome pattern",
                "likelihood": "high",
                "danger_if_missed": "critical",
                "supporting_evidence": ["Chest pain pattern"],
                "evidence_against": [],
                "must_not_miss": True,
                "least_risky_next_checks": ["Obtain ECG", "Repeat blood pressure manually"],
                "least_risky_check_safety": "high",
                "why_prioritized": "Potentially fatal and time-sensitive.",
            },
            {
                "condition": "Pulmonary embolic pattern",
                "likelihood": "medium",
                "danger_if_missed": "high",
                "supporting_evidence": ["Dyspnea/chest discomfort"],
                "evidence_against": [],
                "must_not_miss": True,
                "least_risky_next_checks": ["Check oxygen trend", "Assess unilateral leg swelling history"],
                "least_risky_check_safety": "high",
                "why_prioritized": "High-risk cardiopulmonary compromise if missed.",
            },
        ]
    elif "bleeding" in text or "hemorrhage" in text:
        candidates = [
            {
                "condition": "Hemorrhagic shock pattern",
                "likelihood": "high",
                "danger_if_missed": "critical",
                "supporting_evidence": ["Reported bleeding with hemodynamic concern"],
                "evidence_against": [],
                "must_not_miss": True,
                "least_risky_next_checks": ["External bleed control check", "Serial perfusion exam"],
                "least_risky_check_safety": "high",
                "why_prioritized": "Immediate mortality risk from blood loss.",
            }
        ]
    else:
        candidates = [
            {
                "condition": "Undifferentiated acute illness pattern",
                "likelihood": "medium",
                "danger_if_missed": "medium",
                "supporting_evidence": ["Limited specific findings"],
                "evidence_against": [],
                "must_not_miss": False,
                "least_risky_next_checks": ["Clarify timeline", "Repeat focused vitals"],
                "least_risky_check_safety": "high",
                "why_prioritized": "Requires structured narrowing with low-risk checks.",
            }
        ]
    ranked = _rank_differentials(candidates)
    return {
        "differentials": ranked,
        "most_urgent_rule_outs": [d["condition"] for d in ranked if d.get("must_not_miss")],
        "uncertainty_summary": "Pattern-based differential support; non-diagnostic by design.",
        "ranking_method": "Risk-weighted priority using likelihood, danger, and check safety.",
    }


def _protocol(chunks: list[dict]) -> dict:
    matches = [
        {
            "topic": c.get("section") or c.get("source_short") or c.get("source", ""),
            "guidance": c.get("text", ""),
            "citation": c.get("citation_id", ""),
        }
        for c in chunks
    ]
    return {
        "protocol_matches": matches,
        "contraindications_or_cautions": [],
        "missing_information_needed": [] if matches else ["No matching protocol chunk retrieved."],
        "unsupported_claims_removed": [],
        "safe_next_steps": [m["guidance"] for m in matches[:3]],
    }


def _missed_signals(encounter: dict) -> dict:
    vitals = encounter.get("vitals") or {}
    missed = []
    if vitals.get("oxygen_saturation") is None:
        missed.append({
            "signal": "Missing oxygen saturation",
            "why_it_matters": "Hypoxia changes urgency and intervention sequence.",
            "suggested_low_risk_check": "Obtain pulse oximetry.",
        })
    if vitals.get("systolic_bp") is None:
        missed.append({
            "signal": "Missing blood pressure",
            "why_it_matters": "Potential hemodynamic instability may be hidden.",
            "suggested_low_risk_check": "Repeat manual blood pressure.",
        })
    return {
        "missed_signals": missed,
        "dangerous_ambiguities": [] if missed else ["No major data gaps detected in current input."],
        "questions_to_ask_now": [
            "What was the exact symptom onset time?",
            "Has the patient worsened, improved, or remained stable in the last 15 minutes?",
        ],
    }


def _questions(differential: dict, missed: dict) -> dict:
    out: list[str] = []
    for d in (differential.get("differentials") or [])[:2]:
        out.extend(d.get("least_risky_next_checks") or [])
    out.extend(missed.get("questions_to_ask_now") or [])
    seen = set()
    deduped = []
    for q in out:
        if q and q not in seen:
            deduped.append(q)
            seen.add(q)
    return {"next_best_questions": deduped[:6]}


def _safety(triage: dict, protocol: dict) -> dict:
    warnings = []
    if triage.get("acuity") == "red":
        warnings.append("High acuity case - immediate escalation recommended.")
    if not protocol.get("protocol_matches"):
        warnings.append("No protocol-backed steps matched. Proceed with caution.")
    return {"warnings": warnings, "hard_stops": [], "safe_to_continue": len(warnings) == 0}


def _reasoning_trace(deterministic: dict, triage: dict, differential: dict, protocol: dict) -> list[dict]:
    trace = []
    if deterministic.get("forced_acuity"):
        trace.append({"type": "rule", "message": f"Deterministic rule forced acuity: {deterministic['forced_acuity']}"})
    if triage.get("red_flags"):
        trace.append({"type": "triage", "message": f"Red flags: {', '.join(triage['red_flags'])}"})
    top = (differential.get("differentials") or [None])[0]
    if top:
        trace.append({"type": "differential", "message": f"Top priority: {top.get('condition')} ({top.get('priority_category')})"})
    if protocol.get("protocol_matches"):
        trace.append({"type": "protocol", "message": "Protocol-backed steps identified."})
    return trace


def _crisis_view(triage: dict, differential: dict, questions: dict) -> dict:
    top_diff = (differential.get("differentials") or [])[:3]
    return {
        "acuity": triage.get("acuity"),
        "top_actions": (triage.get("immediate_actions") or [])[:3],
        "top_rule_outs": [d.get("condition") for d in top_diff],
        "next_questions": questions.get("next_best_questions", []),
    }


def _handoff(encounter: dict, triage: dict, differential: dict, protocol: dict, missed: dict) -> dict:
    summary = f"{encounter.get('chief_complaint', 'Undifferentiated complaint')} with {triage.get('acuity', 'unknown')} acuity."
    return {
        "one_line_summary": summary,
        "mist": {
            "mechanism_or_complaint": encounter.get("chief_complaint", ""),
            "injuries_or_findings": triage.get("red_flags", []),
            "signs": encounter.get("vitals", {}),
            "treatment_given": triage.get("immediate_actions", []),
        },
        "sbar": {
            "situation": summary,
            "background": encounter.get("notes", ""),
            "assessment": differential.get("most_urgent_rule_outs", []),
            "recommendation": protocol.get("safe_next_steps", []),
        },
        "three_questions_for_next_provider": (missed.get("questions_to_ask_now") or [])[:3],
        "handoff_warnings": missed.get("dangerous_ambiguities", []),
    }


async def run_decision_support(encounter_input: dict, scenario_id: str | None = None) -> dict:
    encounter = normalize_encounter(encounter_input)
    deterministic = deterministic_triage(encounter)

    red_flags = deterministic.get("detected_red_flags", [])
    if deterministic.get("forced_acuity") == "red" or len(red_flags) >= 2:
        acuity = "red"
    elif red_flags:
        acuity = "yellow"
    else:
        acuity = "green"

    triage = {
        "acuity": acuity,
        "red_flags": red_flags,
        "immediate_actions": (
            ["Escalate to highest available level of care now."] if acuity == "red" else []
        ) + [
            "Secure airway, breathing, and circulation; reassess continuously.",
            "Repeat full vitals and trend at short interval.",
        ],
        "uncertainties": ["Structured support output only; not a definitive diagnosis."],
        "brief_rationale": "Acuity determined by deterministic flags and symptom-risk pattern.",
        "deterministic_rules_used": [deterministic.get("rule_source", "deterministic_vitals_and_red_flag_screen")],
    }

    differential = _differential(encounter)

    query = " ".join(
        [
            encounter.get("chief_complaint", ""),
            " ".join(encounter.get("symptoms") or []),
            encounter.get("notes", ""),
            encounter.get("context", ""),
        ]
    ).strip()
    chunks = await retrieval.retrieve(query or "acute medical triage", scenario_filter=scenario_id, k=8)
    protocol = _protocol(chunks)
    missed = _missed_signals(encounter)
    questions = _questions(differential, missed)
    safety = _safety(triage, protocol)
    reasoning_trace = _reasoning_trace(deterministic, triage, differential, protocol)
    crisis_view = _crisis_view(triage, differential, questions)
    handoff = _handoff(encounter, triage, differential, protocol, missed)

    return {
        "encounter": encounter,
        "crisis_view": crisis_view,
        "triage": triage,
        "differential": differential,
        "protocol": protocol,
        "missed_signals": missed,
        "questions": questions,
        "safety": safety,
        "reasoning_trace": reasoning_trace,
        "audit": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input_summary": encounter.get("chief_complaint"),
            "modules_run": [
                "deterministic_triage",
                "differential",
                "retrieval",
                "missed_signals",
                "safety",
                "reasoning_trace",
                "handoff",
            ],
            "notes": "All outputs generated locally.",
        },
        "handoff": handoff,
        "offline_status": {"mode": "OFFLINE ACTIVE", "cloud_calls": 0},
    }
