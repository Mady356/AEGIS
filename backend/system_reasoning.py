from __future__ import annotations


def build_reasoning_trace(
    deterministic: dict,
    triage: dict,
    differential: dict,
    protocol: dict,
) -> list[dict]:
    """Produce a structured, non-AI explanation of how the pipeline arrived at its
    current view. Each entry has a `type` so the frontend can render it the same
    way regardless of which module emitted it.
    """
    trace: list[dict] = []

    if deterministic.get("forced_acuity"):
        trace.append({
            "type": "rule",
            "message": f"Deterministic rule forced acuity: {deterministic['forced_acuity']}",
        })

    if triage.get("red_flags"):
        trace.append({
            "type": "triage",
            "message": f"Red flags detected: {', '.join(triage['red_flags'])}",
        })

    if differential.get("differentials"):
        top = differential["differentials"][0]
        trace.append({
            "type": "differential",
            "message": f"Top priority: {top.get('condition')} ({top.get('priority_category')})",
        })

    if protocol.get("protocol_matches"):
        trace.append({
            "type": "protocol",
            "message": "Protocol-backed actions identified",
        })

    return trace
