"""
AEGIS — Reasoning orchestrator.

Glues the existing offline agent pipeline together and wraps it with
the new safety / clarity layers:

    fail-safe check
        ↓ (if OK)
    deterministic rules → triage → differential → risk scoring →
    protocol validation → missed signal detection → next-question engine
        ↓
    crisis_view + learning + human guidance → final response

The orchestrator does NOT replace any of the existing reasoning agents.
Each stage is pluggable: callers can inject their existing functions,
and any stage that raises or is missing degrades gracefully to an
empty structure. This keeps AEGIS field-safe — partial reasoning is
better than a crashed reasoner.

Public API:
    run_encounter(encounter, agents=None) -> dict
    DEFAULT_AGENTS  (the no-op fallback agent map)
"""

from __future__ import annotations

import asyncio
import inspect
import time
import traceback
from typing import Any, Awaitable, Callable, Union

from . import crisis, failsafe, learning, tone


# A stage is a callable that takes the encounter (plus the accumulated
# pipeline state) and returns a dict. Stages may raise — the
# orchestrator catches and continues so a single failure does not bring
# down the whole reasoner. Stages may be sync or async; the async
# orchestrator awaits as needed.
Stage = Callable[[dict, dict], Union[dict, Awaitable[dict]]]


# --- Default no-op agents --------------------------------------------------
# These exist so the orchestrator runs end-to-end even when the host
# environment hasn't wired up its real agents yet. Each returns an
# empty-but-shaped dict so downstream consumers (frontend, crisis_view)
# never crash on a missing key.

def _noop_rules(encounter: dict, state: dict) -> dict:
    return {"matched_rules": [], "flags": []}


def _noop_triage(encounter: dict, state: dict) -> dict:
    return {"acuity": "yellow", "actions": [], "key_findings": []}


def _noop_differential(encounter: dict, state: dict) -> dict:
    return {"rule_outs": [], "differentials": []}


def _noop_risk(encounter: dict, state: dict) -> dict:
    return {"risk_score": None, "risk_factors": []}


def _noop_protocol(encounter: dict, state: dict) -> dict:
    return {"immediate_actions": [], "steps": [], "compliant": None}


def _noop_missed(encounter: dict, state: dict) -> dict:
    return {"missed_signals": [], "recommended_actions": []}


def _noop_questions(encounter: dict, state: dict) -> dict:
    """Sensible plain-language fallback questions when no agent is
    wired in. Questions are derived from what's missing rather than
    invented."""
    questions: list[str] = []
    if not encounter.get("vitals"):
        questions.append("Can you measure pulse, breathing rate, or oxygen?")
    if encounter.get("mental_status") in (None, "", "unknown"):
        questions.append("Is the patient awake and responding?")
    if encounter.get("breathing") in (None, "", "unknown"):
        questions.append("Is the patient breathing normally?")
    if encounter.get("bleeding") in (None, "", "unknown"):
        questions.append("Is there visible bleeding?")
    if not questions:
        questions.append("Has anything changed since you started?")
    return {"questions": questions[:3]}


DEFAULT_AGENTS: dict[str, Stage] = {
    "rules": _noop_rules,
    "triage": _noop_triage,
    "differential": _noop_differential,
    "risk": _noop_risk,
    "protocol": _noop_protocol,
    "missed_signals": _noop_missed,
    "questions": _noop_questions,
}


# --- Internals -------------------------------------------------------------

def _run_stage(
    name: str,
    stage: Stage,
    encounter: dict,
    state: dict,
    trace: list[dict],
) -> dict:
    started = time.time()
    try:
        result = stage(encounter, state) or {}
    except Exception as exc:
        trace.append({
            "stage": name,
            "status": "error",
            "error": str(exc),
            "trace": traceback.format_exc(limit=2),
            "ms": int((time.time() - started) * 1000),
        })
        return {}
    trace.append({
        "stage": name,
        "status": "ok",
        "ms": int((time.time() - started) * 1000),
    })
    return result


def _failsafe_response(
    safety: dict,
    trace: list[dict],
) -> dict:
    """Build the crisis-style response when fail-safe trips."""
    crisis_view = {
        "acuity": "yellow",
        "top_actions": [
            "Stay with the patient",
            "Answer the safety questions below",
            "Re-check the patient as you answer",
        ],
        "top_rule_outs": [],
        "next_questions": list(safety.get("questions") or []),
        "support_message": (
            "It's okay to slow down. Answering these questions first "
            "keeps the patient safe."
        ),
    }
    response = {
        "crisis_view": crisis_view,
        "triage": {},
        "differential": {},
        "protocol": {},
        "missed_signals": {},
        "questions": {"questions": list(safety.get("questions") or [])},
        "learning": {},
        "safety": safety,
        "reasoning_trace": {"stages": trace, "halted_at": "failsafe"},
        "audit": {
            "halted": True,
            "reason": "insufficient_data",
        },
        "offline_status": {"mode": "OFFLINE ACTIVE", "cloud_calls": 0},
    }
    return tone.add_human_guidance(response)


# --- Public API ------------------------------------------------------------

def run_encounter(
    encounter: dict | None,
    agents: dict[str, Stage] | None = None,
) -> dict:
    """Run the full AEGIS reasoning pipeline on `encounter`.

    Args:
        encounter: Structured encounter dict (e.g. the output of
            `intake.build_structured_encounter`).
        agents:    Optional mapping that overrides any of the default
            stage callables. Keys: "rules", "triage", "differential",
            "risk", "protocol", "missed_signals", "questions". Any
            omitted keys fall back to the safe no-op default.

    Returns:
        A single dict with the full multi-section response. Always
        includes `crisis_view`, `safety`, `offline_status`, and
        `guidance`.
    """
    encounter = encounter or {}
    pipeline = {**DEFAULT_AGENTS, **(agents or {})}
    trace: list[dict] = []

    # 1. Fail-safe check before any agent runs.
    safety = failsafe.check_insufficient_data(encounter)
    if safety:
        trace.append({"stage": "failsafe", "status": "halted",
                      "reasons": safety.get("reasons", [])})
        return _failsafe_response(safety, trace)
    trace.append({"stage": "failsafe", "status": "ok"})

    # 2. Existing agent pipeline (each stage is fault-tolerant).
    state: dict[str, Any] = {}
    rules = _run_stage("rules", pipeline["rules"], encounter, state, trace)
    state["rules"] = rules
    triage = _run_stage("triage", pipeline["triage"], encounter, state, trace)
    state["triage"] = triage
    differential = _run_stage(
        "differential", pipeline["differential"], encounter, state, trace,
    )
    state["differential"] = differential
    risk = _run_stage("risk", pipeline["risk"], encounter, state, trace)
    state["risk"] = risk
    protocol = _run_stage(
        "protocol", pipeline["protocol"], encounter, state, trace,
    )
    state["protocol"] = protocol
    missed = _run_stage(
        "missed_signals", pipeline["missed_signals"], encounter, state, trace,
    )
    state["missed_signals"] = missed
    questions = _run_stage(
        "questions", pipeline["questions"], encounter, state, trace,
    )
    state["questions"] = questions

    # 3. Crisis view + learning takeaway.
    crisis_view = crisis.build_crisis_view(
        triage=triage,
        differential=differential,
        protocol=protocol,
        missed_signals=missed,
        next_questions=questions,
    )
    learn = learning.generate_learning_point(differential, triage)

    response = {
        "crisis_view": crisis_view,
        "triage": triage,
        "differential": differential,
        "protocol": protocol,
        "missed_signals": missed,
        "questions": questions,
        "learning": learn,
        "safety": {"status": "ok"},
        "reasoning_trace": {"stages": trace},
        "audit": {
            "halted": False,
            "stages_run": [t["stage"] for t in trace],
            "stages_with_errors": [
                t["stage"] for t in trace if t.get("status") == "error"
            ],
            "risk": risk,
            "rules": rules,
        },
        "offline_status": {"mode": "OFFLINE ACTIVE", "cloud_calls": 0},
    }

    # 4. Human tone wrapper (always last).
    return tone.add_human_guidance(response)


# =====================================================================
# Async orchestrator — supports async or sync stage callables.
# Used when stages call out to the local LLM (LM Studio / Ollama).
# =====================================================================

async def _run_stage_async(
    name: str,
    stage: Stage,
    encounter: dict,
    state: dict,
    trace: list[dict],
) -> dict:
    started = time.time()
    try:
        result = stage(encounter, state)
        if inspect.isawaitable(result):
            result = await result
        result = result or {}
    except Exception as exc:
        trace.append({
            "stage": name,
            "status": "error",
            "error": str(exc),
            "trace": traceback.format_exc(limit=2),
            "ms": int((time.time() - started) * 1000),
        })
        return {}
    trace.append({
        "stage": name,
        "status": "ok",
        "ms": int((time.time() - started) * 1000),
    })
    return result


async def run_encounter_async(
    encounter: dict | None,
    agents: dict[str, Stage] | None = None,
    offline_status: dict | None = None,
) -> dict:
    """Async variant of `run_encounter`.

    Identical contract; only difference is that stages may be async
    callables. Use this when one or more stages talk to the local LLM.

    `offline_status` overrides the default offline_status block —
    callers (e.g. the LLM-agent route handler) pass a richer block
    including the LLM endpoint, model, status, and last latency.
    """
    encounter = encounter or {}
    pipeline = {**DEFAULT_AGENTS, **(agents or {})}
    trace: list[dict] = []

    safety = failsafe.check_insufficient_data(encounter)
    if safety:
        trace.append({"stage": "failsafe", "status": "halted",
                      "reasons": safety.get("reasons", [])})
        out = _failsafe_response(safety, trace)
        if offline_status:
            out["offline_status"] = offline_status
        return out
    trace.append({"stage": "failsafe", "status": "ok"})

    state: dict[str, Any] = {}
    order = ["rules", "triage", "differential", "risk",
             "protocol", "missed_signals", "questions"]
    results: dict[str, dict] = {}
    for name in order:
        results[name] = await _run_stage_async(
            name, pipeline[name], encounter, state, trace
        )
        state[name] = results[name]

    crisis_view = crisis.build_crisis_view(
        triage=results["triage"],
        differential=results["differential"],
        protocol=results["protocol"],
        missed_signals=results["missed_signals"],
        next_questions=results["questions"],
    )
    learn = learning.generate_learning_point(
        results["differential"], results["triage"]
    )

    response = {
        "crisis_view": crisis_view,
        "triage": results["triage"],
        "differential": results["differential"],
        "protocol": results["protocol"],
        "missed_signals": results["missed_signals"],
        "questions": results["questions"],
        "learning": learn,
        "safety": {"status": "ok"},
        "reasoning_trace": {"stages": trace, "llm_meta": state.get("llm_meta")},
        "audit": {
            "halted": False,
            "stages_run": [t["stage"] for t in trace],
            "stages_with_errors": [
                t["stage"] for t in trace if t.get("status") == "error"
            ],
            "risk": results["risk"],
            "rules": results["rules"],
        },
        "offline_status": offline_status or {
            "mode": "OFFLINE ACTIVE", "cloud_calls": 0,
        },
    }

    # Refresh offline_status.local_llm with the actual call result if
    # the route passed a placeholder pre-run snapshot.
    llm_meta = state.get("llm_meta") or {}
    if llm_meta and isinstance(response.get("offline_status"), dict):
        ll = response["offline_status"].setdefault("local_llm", {})
        if llm_meta.get("status"):
            ll["status"] = llm_meta["status"]
        if llm_meta.get("latency_ms") is not None:
            ll["last_latency_ms"] = llm_meta["latency_ms"]
        if llm_meta.get("model"):
            ll["model"] = llm_meta["model"]
        if llm_meta.get("endpoint"):
            ll["endpoint"] = llm_meta["endpoint"]

    return tone.add_human_guidance(response)
