"""
AEGIS — Learning Loop.

After a case, give the user a short, plain-language takeaway so
non-expert users improve over time. One sentence, no jargon, no
diagnosis claims — uses "rule out", "watch for", "treat as high risk
until ruled out" phrasing.

Public API:
    generate_learning_point(differential: dict, triage: dict) -> dict
"""

from __future__ import annotations

from typing import Any


def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _first_string(items: Any) -> str:
    if not items:
        return ""
    if isinstance(items, str):
        return items.strip()
    if isinstance(items, dict):
        for k in ("name", "label", "diagnosis", "rule_out", "text"):
            if items.get(k):
                return str(items[k]).strip()
        return ""
    if isinstance(items, (list, tuple)):
        for it in items:
            text = _first_string(it)
            if text:
                return text
    return ""


def _top_rule_out(differential: dict | None) -> str:
    differential = differential or {}
    for key in ("rule_outs", "must_not_miss", "dangerous", "differentials",
                "hypotheses"):
        text = _first_string(differential.get(key))
        if text:
            return text
    return ""


def _key_findings(triage: dict | None) -> list[str]:
    triage = triage or {}
    findings: list[str] = []
    for key in ("key_findings", "findings", "red_flags", "concerning"):
        val = triage.get(key)
        if isinstance(val, (list, tuple)):
            for item in val:
                text = _first_string(item)
                if text and text not in findings:
                    findings.append(text)
        elif _str(val):
            findings.append(_str(val))
    return findings[:3]


def generate_learning_point(
    differential: dict | None,
    triage: dict | None,
) -> dict:
    """Build a short, plain-language teaching takeaway."""
    acuity = _str((triage or {}).get("acuity")).lower()
    findings = _key_findings(triage)
    rule_out = _top_rule_out(differential)

    if findings and rule_out:
        finding_phrase = " with ".join(findings[:2]) if len(findings) > 1 else findings[0]
        sentence = (
            f"Key takeaway: {finding_phrase} should be treated as high "
            f"risk until {rule_out} and other dangerous causes are ruled out."
        )
    elif findings:
        finding_phrase = " with ".join(findings[:2]) if len(findings) > 1 else findings[0]
        sentence = (
            f"Key takeaway: when you see {finding_phrase}, slow down, "
            f"re-check the basics, and escalate early if anything worsens."
        )
    elif rule_out:
        sentence = (
            f"Key takeaway: in cases like this, {rule_out} is dangerous "
            f"to miss — keep checking for it until it is ruled out."
        )
    elif acuity == "red":
        sentence = (
            "Key takeaway: when the patient looks critical, work the "
            "basics first — airway, breathing, bleeding — and escalate."
        )
    else:
        sentence = (
            "Key takeaway: re-check the basics often. If anything "
            "changes, treat the new finding as the highest priority."
        )

    return {"learning_point": sentence}
