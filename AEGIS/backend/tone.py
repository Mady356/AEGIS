"""
AEGIS — Human Tone Layer.

AEGIS must feel calm and usable in chaos, but never overly emotional.
This module attaches a small `guidance` block to any pipeline output.

Public API:
    add_human_guidance(output: dict) -> dict
"""

from __future__ import annotations

from typing import Any


# Tone messages are kept short, direct, and field-appropriate. Tone is
# selected from the crisis_view acuity when present so the message
# matches the situation.
_MESSAGES = {
    "red": ("calm",
            "You are not alone. Work through the steps one at a time. "
            "Re-check the patient as you go."),
    "yellow": ("calm",
               "Take a breath. Follow the steps in order. Re-assess if "
               "anything changes."),
    "green": ("calm",
              "Things look stable. Keep watching the patient and complete "
              "the checks one at a time."),
    "insufficient": ("calm",
                     "It's okay to slow down. Answer the questions first, "
                     "then we will continue."),
}


def _select_tone(output: dict) -> tuple[str, str]:
    if not isinstance(output, dict):
        return _MESSAGES["yellow"]

    # Fail-safe path takes precedence.
    safety = output.get("safety") or {}
    if isinstance(safety, dict) and safety.get("status") == "insufficient_data":
        return _MESSAGES["insufficient"]
    if output.get("status") == "insufficient_data":
        return _MESSAGES["insufficient"]

    crisis = output.get("crisis_view") or {}
    acuity = ""
    if isinstance(crisis, dict):
        acuity = str(crisis.get("acuity") or "").lower()
    if acuity in _MESSAGES:
        return _MESSAGES[acuity]
    return _MESSAGES["yellow"]


def add_human_guidance(output: Any) -> dict:
    """Attach a calm `guidance` block to the output and return it.

    The function is non-destructive in spirit — it only adds the
    `guidance` field. If the input isn't a dict we wrap it.
    """
    if not isinstance(output, dict):
        output = {"result": output}

    tone, message = _select_tone(output)
    output["guidance"] = {
        "tone": tone,
        "message": message,
    }
    return output
