"""
AEGIS — One-Screen Crisis Mode.

Compresses the full reasoning pipeline output into a single screen
that a stressed non-expert (refugee aid worker, submariner, soldier,
disaster first responder) can read at a glance.

Design constraints:
    - No diagnoses. Only "rule out", "check next", "escalate".
    - No long paragraphs.
    - Never returns more than 3 items per list.
    - Never raises — always returns a usable view, even on partial data.
    - Offline only. No external calls.

Public API:
    build_crisis_view(triage, differential, protocol, missed_signals,
                      next_questions) -> dict
"""

from __future__ import annotations

from typing import Any, Iterable


# --- Acuity normalization --------------------------------------------------

_ACUITY_MAP = {
    "red": "red", "critical": "red", "immediate": "red", "p1": "red",
    "high": "red", "severe": "red",
    "yellow": "yellow", "urgent": "yellow", "p2": "yellow",
    "moderate": "yellow", "delayed": "yellow",
    "green": "green", "minor": "green", "p3": "green",
    "low": "green", "stable": "green",
}


def _normalize_acuity(value: Any) -> str:
    if not value:
        return "yellow"
    key = str(value).strip().lower()
    return _ACUITY_MAP.get(key, "yellow")


# --- Helpers ---------------------------------------------------------------

def _take_strings(items: Iterable[Any] | None, n: int = 3) -> list[str]:
    """Best-effort coerce an iterable into up to N short strings."""
    out: list[str] = []
    if not items:
        return out
    for item in items:
        if len(out) >= n:
            break
        if item is None:
            continue
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = (
                item.get("action")
                or item.get("text")
                or item.get("label")
                or item.get("name")
                or item.get("description")
                or item.get("question")
                or item.get("rule_out")
                or item.get("diagnosis")
                or ""
            )
            text = str(text).strip()
        else:
            text = str(item).strip()
        if text:
            out.append(text)
    return out


def _take_actions(items: Iterable[Any] | None, n: int = 8) -> list[dict | str]:
    """Take up to N action items, preserving structured form when present.

    When the upstream `protocol.immediate_actions` is a list of
    `{id, label, keywords}` dicts (scenario-aware mode), keep them
    structured so the frontend can use the keywords for extraction
    matching. When the items are bare strings (no scenario context, or
    legacy fallback), pass them through as strings."""
    out: list[dict | str] = []
    if not items:
        return out
    for item in items:
        if len(out) >= n:
            break
        if item is None:
            continue
        if isinstance(item, dict):
            label = str(
                item.get("label")
                or item.get("action")
                or item.get("text")
                or item.get("name")
                or ""
            ).strip()
            if not label:
                continue
            entry: dict = {"label": label}
            if item.get("id"):
                entry["id"] = str(item["id"])
            kw = item.get("keywords")
            if isinstance(kw, list):
                entry["keywords"] = [str(k).strip().lower()
                                     for k in kw if isinstance(k, str) and k.strip()]
            out.append(entry)
        elif isinstance(item, str):
            text = item.strip()
            if text:
                out.append(text)
    return out


def _support_message(acuity: str) -> str:
    if acuity == "red":
        return ("Stay with the patient. Work through the steps one at a "
                "time. You are not alone.")
    if acuity == "yellow":
        return ("Take a breath. Check the items in order. Re-assess if "
                "anything changes.")
    return ("The patient appears stable. Keep watching for changes and "
            "complete the checks one by one.")


# --- Public API ------------------------------------------------------------

def build_crisis_view(
    triage: dict | None = None,
    differential: dict | None = None,
    protocol: dict | None = None,
    missed_signals: dict | None = None,
    next_questions: dict | list | None = None,
) -> dict:
    """Compress pipeline outputs into a single-screen view.

    All arguments are tolerant of None / missing keys so this never
    blocks the orchestrator.
    """
    triage = triage or {}
    differential = differential or {}
    protocol = protocol or {}
    missed_signals = missed_signals or {}

    acuity = _normalize_acuity(
        triage.get("acuity") or triage.get("level") or triage.get("priority")
    )

    # Top actions: prefer protocol immediate steps (which may now be
    # structured {id, label, keywords} dicts when scenario_context drove
    # the LLM bundle), then triage actions, then missed-signal corrective
    # actions. _take_actions preserves the structured form so the
    # frontend's checklist can use per-item keywords for extraction
    # matching; bare-string fallbacks are passed through unchanged.
    actions = _take_actions(
        protocol.get("immediate_actions")
        or protocol.get("steps")
        or triage.get("actions")
        or triage.get("immediate_actions")
        or missed_signals.get("recommended_actions"),
        8,
    )

    # Top rule-outs: from differential (dangerous causes first).
    rule_outs = _take_strings(
        differential.get("rule_outs")
        or differential.get("must_not_miss")
        or differential.get("dangerous")
        or differential.get("differentials")
        or differential.get("hypotheses"),
        3,
    )

    # Top next questions/checks.
    if isinstance(next_questions, dict):
        questions_src = (
            next_questions.get("questions")
            or next_questions.get("next_questions")
            or next_questions.get("checks")
        )
    else:
        questions_src = next_questions
    questions = _take_strings(questions_src, 3)

    return {
        "acuity": acuity,
        "top_actions": actions,
        "top_rule_outs": rule_outs,
        "next_questions": questions,
        "support_message": _support_message(acuity),
    }
