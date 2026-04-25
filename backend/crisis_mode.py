from __future__ import annotations


def build_crisis_view(triage: dict, differential: dict, questions: dict) -> dict:
    top_diff = differential.get("differentials", [])[:3]
    return {
        "acuity": triage.get("acuity"),
        "top_actions": triage.get("immediate_actions", [])[:3],
        "top_rule_outs": [d.get("condition") for d in top_diff],
        "next_questions": questions.get("next_best_questions", []),
    }
def build_crisis_view(triage, differential, questions):
    top_diff = differential.get("differentials", [])[:3]

    return {
        "acuity": triage.get("acuity"),
        "top_actions": triage.get("immediate_actions", [])[:3],
        "top_rule_outs": [d.get("condition") for d in top_diff],
        "next_questions": questions.get("next_best_questions", [])
    }