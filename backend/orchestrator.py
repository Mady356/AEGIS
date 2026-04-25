from backend.agents import (
    run_triage_agent,
    run_differential_agent,
    run_protocol_agent,
    run_missed_signal_agent,
    run_handoff_agent,
)
from backend.clinical_rules import deterministic_triage
from backend.retrieval import retrieve_protocol_chunks
from backend.risk_scoring import rank_differentials
from backend.timeline import EncounterTimeline
from backend.system_reasoning import build_reasoning_trace
from backend.safety import enforce_safety
from backend.question_engine import generate_next_questions
from backend.crisis_mode import build_crisis_view
from backend.audit import build_audit_log
from backend.schemas import normalize_encounter
from backend.aegis_adapters import (
    build_integration_snapshot,
    run_calculator,
    check_medication_safety,
)
from backend.contracts import PipelineResponse


def _safe_agent_call(name: str, fn, fallback: dict, **kwargs) -> dict:
    try:
        result = fn(**kwargs)
        if isinstance(result, dict):
            return result
        return {"_error": f"{name} returned non-dict result", **fallback}
    except Exception as exc:  # pragma: no cover - defensive guard for demo reliability.
        return {"_error": f"{name} failed: {exc}", **fallback}


def _derive_calculators(encounter: dict) -> dict:
    vitals = encounter.get("vitals") or {}
    hr = vitals.get("heart_rate")
    sbp = vitals.get("systolic_bp")
    dbp = vitals.get("diastolic_bp")
    rr = vitals.get("respiratory_rate")
    mental = str(vitals.get("mental_status") or "").lower()

    outputs = {}
    if hr is not None and sbp is not None:
        result = run_calculator("shock_index", hr=hr, sbp=sbp)
        if result:
            outputs["shock_index"] = result
    if sbp is not None and dbp is not None:
        result = run_calculator("map", sbp=sbp, dbp=dbp)
        if result:
            outputs["map"] = result
    if rr is not None and sbp is not None:
        result = run_calculator("qsofa", rr=rr, altered=("confused" in mental or "altered" in mental), sbp=sbp)
        if result:
            outputs["qsofa"] = result
    return outputs


def _derive_medication_flags(encounter: dict) -> list[dict]:
    metadata = encounter.get("metadata") or {}
    pending_med = metadata.get("pending_medication")
    if not pending_med:
        return []
    admin_history = metadata.get("admin_history") or []
    allergies = metadata.get("allergies") or []
    return check_medication_safety(str(pending_med), list(admin_history), list(allergies))


def run_aegis_pipeline(encounter: dict) -> PipelineResponse:
    timeline = EncounterTimeline()
    encounter = normalize_encounter(encounter)
    if encounter.get("vitals"):
        timeline.add_event("vitals", encounter["vitals"])

    timeline.add_event("encounter", encounter)

    trend_summary = timeline.summarize_trends()
    deterministic = deterministic_triage(encounter)

    triage = _safe_agent_call(
        "triage",
        run_triage_agent,
        fallback={
            "acuity": deterministic.get("forced_acuity") or "yellow",
            "red_flags": deterministic.get("detected_red_flags", []),
            "immediate_actions": ["Repeat ABC assessment and monitor closely."],
            "uncertainties": ["Agent unavailable; using deterministic fallback."],
            "brief_rationale": "Fallback from deterministic rules.",
            "deterministic_rules_used": [deterministic.get("rule_source")],
        },
        encounter=encounter,
        deterministic=deterministic,
        trend_summary=trend_summary,
    )

    if deterministic.get("forced_acuity") == "red":
        triage["acuity"] = "red"
        triage.setdefault("red_flags", [])
        triage["red_flags"] = list(set(
            triage["red_flags"] + deterministic.get("detected_red_flags", [])
        ))

    differential_raw = _safe_agent_call(
        "differential",
        run_differential_agent,
        fallback={
            "differentials": [],
            "most_urgent_rule_outs": [],
            "uncertainty_summary": "Differential unavailable.",
            "failure_conditions": ["Agent failed; no differential generated."],
        },
        encounter=encounter,
        triage=triage,
    )

    differentials = differential_raw.get("differentials", [])
    ranked_differentials = rank_differentials(differentials)

    differential = dict(differential_raw)
    differential["differentials"] = ranked_differentials
    differential["ranking_method"] = (
        "Risk-weighted priority: balances likelihood, danger if missed, "
        "and safety/cost of least-risky next checks."
    )

    protocol_chunks = retrieve_protocol_chunks(
        encounter=encounter,
        triage=triage,
        differential=differential,
    )

    protocol = _safe_agent_call(
        "protocol",
        run_protocol_agent,
        fallback={
            "protocol_matches": [],
            "contraindications_or_cautions": [],
            "missing_information_needed": ["Protocol layer unavailable."],
            "unsupported_claims_removed": [],
            "safe_next_steps": [],
        },
        encounter=encounter,
        triage=triage,
        differential=differential,
        protocol_chunks=protocol_chunks,
    )

    missed = _safe_agent_call(
        "missed_signals",
        run_missed_signal_agent,
        fallback={
            "missed_signals": [],
            "dangerous_ambiguities": ["Missed signal layer unavailable."],
            "questions_to_ask_now": [],
        },
        encounter=encounter,
        triage=triage,
        differential=differential,
        trend_summary=trend_summary,
    )

    handoff = _safe_agent_call(
        "handoff",
        run_handoff_agent,
        fallback={
            "one_line_summary": "Structured handoff unavailable.",
            "mist": {},
            "sbar": {},
            "three_questions_for_next_provider": [],
            "handoff_warnings": [],
        },
        encounter=encounter,
        triage=triage,
        differential=differential,
        protocol=protocol,
        missed=missed,
    )

    questions = generate_next_questions(differential, missed)

    safety = enforce_safety(triage, protocol)
    medication_flags = _derive_medication_flags(encounter)
    if medication_flags:
        safety.setdefault("warnings", [])
        safety["warnings"].append("Medication interaction/allergy flags detected.")
        safety["medication_flags"] = medication_flags

    reasoning_trace = build_reasoning_trace(deterministic, triage, differential, protocol)
    calculated = _derive_calculators(encounter)
    integrations = build_integration_snapshot(encounter)
    integrations["calculators"] = calculated

    crisis_view = build_crisis_view(triage, differential, questions)
    audit = build_audit_log(encounter, {
        "triage": triage,
        "differential": differential,
        "protocol": protocol,
        "missed_signals": missed,
        "handoff": handoff,
    })

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
        "audit": audit,
        "handoff": handoff,
        "timeline": timeline.get_events(),
        "offline_status": {
            "mode": "OFFLINE ACTIVE",
            "cloud_calls": 0,
        },
        "integrations": integrations,
    }