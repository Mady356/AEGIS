from __future__ import annotations


def build_crisis_view(triage: dict, differential: dict, questions: dict) -> dict:
    """Compact view used by the high-stress emergency UI. Strict JSON shape so the
    frontend never has to parse free-form text.
    """
    top_diff = differential.get("differentials", [])[:3]
    return {
        "acuity": triage.get("acuity"),
        "top_actions": triage.get("immediate_actions", [])[:3],
        "top_rule_outs": [d.get("condition") for d in top_diff],
        "next_questions": questions.get("next_best_questions", []),
    }
