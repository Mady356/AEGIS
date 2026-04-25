from __future__ import annotations

from typing import Any


TRIAGE_SYSTEM = """
You are AEGIS Triage Agent.
You support emergency medical decision-making.
You do NOT diagnose.
Use deterministic red flags if provided.
Identify immediate danger, acuity, red flags, and stabilization priorities.
Be conservative. If deterministic rules force RED acuity, preserve RED acuity.
"""

DIFFERENTIAL_SYSTEM = """
You are AEGIS Differential Agent.
You do NOT give a final diagnosis.
List plausible explanations, especially must-not-miss conditions.
For each differential, include:
- likelihood: low/medium/high
- danger_if_missed: low/medium/high/critical
- least_risky_next_checks
- least_risky_check_safety: high/medium/low
Rank conceptually by urgency to rule out, not likelihood alone.
"""

PROTOCOL_SYSTEM = """
You are AEGIS Protocol Agent.
Only provide guidance supported by the supplied protocol excerpts.
If the excerpts do not justify an action, say insufficient protocol support.
Do not invent citations.
Flag any unsupported or unsafe claims.
"""

MISSED_SIGNAL_SYSTEM = """
You are AEGIS Missed Signal Detector.
Your job is to identify what could be overlooked in this encounter.
Look for repeated symptoms, abnormal vitals, missing follow-ups, contradictions, or dangerous ambiguity.
Do not diagnose.
"""

HANDOFF_SYSTEM = """
You are AEGIS Handoff Agent.
Create a concise emergency handoff.
Use only the encounter facts and prior agent outputs.
Do not add new medical claims.
"""


def _safe_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v is not None]


def run_triage_agent(encounter: dict, deterministic: dict, trend_summary: dict) -> dict:
    red_flags = _safe_text_list(deterministic.get("detected_red_flags"))
    if trend_summary.get("trend_flags"):
        red_flags.extend(_safe_text_list(trend_summary.get("trend_flags")))
    red_flags = sorted(set(red_flags))

    if deterministic.get("forced_acuity") == "red" or len(red_flags) >= 2:
        acuity = "red"
    elif red_flags:
        acuity = "yellow"
    else:
        acuity = "green"

    actions = [
        "Secure airway, breathing, circulation and reassess continuously.",
        "Repeat full vitals and trend at short interval.",
    ]
    if acuity == "red":
        actions.insert(0, "Escalate to highest available level of care now.")

    return {
        "acuity": acuity,
        "red_flags": red_flags,
        "immediate_actions": actions[:3],
        "uncertainties": ["No model-specific diagnosis is produced by design."],
        "brief_rationale": "Acuity is based on deterministic safety checks and trend flags.",
        "deterministic_rules_used": [deterministic.get("rule_source", "deterministic_vitals_and_red_flag_screen")],
        "agent_status": "fallback_local_logic",
    }


def run_differential_agent(encounter: dict, triage: dict) -> dict:
    complaint = str(encounter.get("chief_complaint", "")).lower()
    symptoms = " ".join(_safe_text_list(encounter.get("symptoms"))).lower()
    text = f"{complaint} {symptoms}"

    chest_case = "chest pain" in text or "shortness of breath" in text
    bleed_case = "bleeding" in text or "hemorrhage" in text

    differentials: list[dict] = []
    if chest_case:
        differentials.extend([
            {
                "condition": "Acute coronary syndrome pattern",
                "likelihood": "high",
                "danger_if_missed": "critical",
                "supporting_evidence": ["Chest pain", "Autonomic symptoms or dyspnea"],
                "evidence_against": [],
                "must_not_miss": True,
                "least_risky_next_checks": ["Obtain 12-lead ECG", "Repeat blood pressure manually"],
                "least_risky_check_safety": "high",
                "why_prioritized": "Potentially fatal and time-sensitive.",
            },
            {
                "condition": "Pulmonary embolism pattern",
                "likelihood": "medium",
                "danger_if_missed": "high",
                "supporting_evidence": ["Dyspnea", "Tachycardia if present"],
                "evidence_against": [],
                "must_not_miss": True,
                "least_risky_next_checks": ["Assess unilateral leg swelling history", "Check oxygen trend"],
                "least_risky_check_safety": "high",
                "why_prioritized": "High-risk cardiopulmonary deterioration if missed.",
            },
        ])
    elif bleed_case:
        differentials.append(
            {
                "condition": "Hemorrhagic shock pattern",
                "likelihood": "high",
                "danger_if_missed": "critical",
                "supporting_evidence": ["Bleeding history", "Possible hypotension or tachycardia"],
                "evidence_against": [],
                "must_not_miss": True,
                "least_risky_next_checks": ["External bleeding control check", "Serial perfusion exam"],
                "least_risky_check_safety": "high",
                "why_prioritized": "Immediate mortality risk from uncontrolled blood loss.",
            }
        )
    else:
        differentials.append(
            {
                "condition": "Undifferentiated acute illness pattern",
                "likelihood": "medium",
                "danger_if_missed": "medium",
                "supporting_evidence": ["Insufficient specific data"],
                "evidence_against": [],
                "must_not_miss": False,
                "least_risky_next_checks": ["Clarify onset/timeline", "Repeat focused vitals"],
                "least_risky_check_safety": "high",
                "why_prioritized": "Structured data collection is needed before narrowing.",
            }
        )

    return {
        "differentials": differentials,
        "most_urgent_rule_outs": [d["condition"] for d in differentials if d.get("must_not_miss")],
        "uncertainty_summary": "Differential list is pattern-based and intentionally non-diagnostic.",
        "failure_conditions": [
            "Atypical presentation may reduce matching accuracy.",
            "Incomplete vitals can understate risk."
        ],
        "agent_status": "fallback_local_logic",
    }


def run_protocol_agent(encounter: dict, triage: dict, differential: dict, protocol_chunks: list[str]) -> dict:
    matches = []
    for chunk in protocol_chunks:
        if "::" in chunk:
            citation, guidance = chunk.split("::", 1)
            matches.append({
                "topic": citation.strip(),
                "guidance": guidance.strip(),
                "citation": citation.strip(),
            })
    return {
        "protocol_matches": matches,
        "contraindications_or_cautions": [],
        "missing_information_needed": [] if matches else ["No local protocol match found for current pattern."],
        "unsupported_claims_removed": [],
        "safe_next_steps": [m["guidance"] for m in matches[:3]],
        "agent_status": "fallback_local_logic",
    }


def run_missed_signal_agent(encounter: dict, triage: dict, differential: dict, trend_summary: dict) -> dict:
    vitals = encounter.get("vitals") or {}
    missed_signals = []
    if vitals.get("oxygen_saturation") is None:
        missed_signals.append({
            "signal": "Missing oxygen saturation",
            "why_it_matters": "Hypoxia can change priority and intervention urgency.",
            "suggested_low_risk_check": "Obtain pulse oximetry now.",
        })
    if vitals.get("systolic_bp") is None:
        missed_signals.append({
            "signal": "Missing blood pressure",
            "why_it_matters": "Hemodynamic instability may be hidden.",
            "suggested_low_risk_check": "Repeat manual blood pressure.",
        })
    return {
        "missed_signals": missed_signals,
        "dangerous_ambiguities": [] if missed_signals else ["No major data gaps detected in current input."],
        "questions_to_ask_now": [
            "What was the exact symptom onset time?",
            "Has the patient worsened, improved, or stayed stable over the last 15 minutes?",
        ],
        "agent_status": "fallback_local_logic",
    }


def run_handoff_agent(encounter: dict, triage: dict, differential: dict, protocol: dict, missed: dict) -> dict:
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
        "three_questions_for_next_provider": missed.get("questions_to_ask_now", [])[:3],
        "handoff_warnings": missed.get("dangerous_ambiguities", []),
        "agent_status": "fallback_local_logic",
    }