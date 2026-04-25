"""
Local wound and lesion image analysis via Ollama-served Qwen2-VL.

The image is sent to the same local Ollama instance that serves the LLM.
Output is parsed into a structured response: free-text description,
constrained classification, severity tier, recommended next-step
protocols (each tagged with retrieval IDs from the RAG corpus), and
confidence assessment.
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
VISION_MODEL = os.environ.get("AEGIS_VISION_MODEL", "qwen2-vl:7b-instruct-q4_K_M")


SCENARIO_CLASSES = {
    "battlefield": [
        "laceration", "avulsion", "amputation",
        "burn-1", "burn-2", "burn-3",
        "penetrating", "blunt", "abrasion", "unknown",
    ],
    "disaster": [
        "laceration", "abrasion", "burn-1", "burn-2", "rash",
        "fracture-suspected", "dehydration-clinical-signs", "unknown",
    ],
    "maritime": [
        "cyanosis", "decompression-skin-bend", "barotrauma-skin",
        "thermal-burn", "unknown",
    ],
}


def _system_prompt(scenario_id: str) -> str:
    classes = SCENARIO_CLASSES.get(scenario_id, SCENARIO_CLASSES["battlefield"])
    return (
        "You are AEGIS, analyzing a clinical image. Produce STRICT JSON with fields: "
        "description (string), classification (one of: " + ", ".join(classes) + "), "
        "severity (one of: 'category I — immediate', 'category II — urgent', 'category III — delayed'), "
        "next_steps (list of {text, cite}), confidence (0-1 float). "
        "Cite each next-step from retrieval IDs in the form [TCCC-3.2] or [WHO-EC-p84]. "
        "Output JSON only — no prose preamble."
    )


async def analyze(image_bytes: bytes, scenario_id: str = "battlefield") -> dict:
    b64 = base64.b64encode(image_bytes).decode()
    body = {
        "model": VISION_MODEL,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 800},
        "messages": [
            {"role": "system", "content": _system_prompt(scenario_id)},
            {"role": "user", "content": "Analyze this image.",
             "images": [b64]},
        ],
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=body)
        r.raise_for_status()
        msg = r.json().get("message", {})
        text = msg.get("content", "")

    return _parse_response(text, scenario_id)


def _parse_response(text: str, scenario_id: str) -> dict:
    # Try to extract a JSON block from the model output
    m = re.search(r"\{[\s\S]+\}", text)
    if not m:
        return _empty_result(scenario_id, text)
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return _empty_result(scenario_id, text)

    # Normalize / validate
    classes = SCENARIO_CLASSES.get(scenario_id, SCENARIO_CLASSES["battlefield"])
    cls = str(data.get("classification", "unknown")).strip().lower()
    if cls not in classes: cls = "unknown"
    sev = str(data.get("severity", "")).strip()
    desc = str(data.get("description", "")).strip()
    conf = float(data.get("confidence", 0.0) or 0.0)
    next_steps = data.get("next_steps") or []
    if not isinstance(next_steps, list):
        next_steps = []
    cleaned_steps = []
    for s in next_steps[:6]:
        if isinstance(s, dict) and "text" in s:
            cleaned_steps.append({
                "text": str(s["text"]),
                "cite": str(s.get("cite", "")),
            })
    return {
        "description": desc, "classification": cls, "severity": sev,
        "next_steps": cleaned_steps, "confidence": conf,
    }


def _empty_result(scenario_id: str, raw: str) -> dict:
    return {
        "description": "Vision analysis returned non-JSON output.",
        "classification": "unknown",
        "severity": "category II — urgent",
        "next_steps": [],
        "confidence": 0.0,
        "raw": raw[:500],
    }
