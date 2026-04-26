"""
AEGIS — LLM-backed stage agents for the orchestrator.

Drops into orchestrator.run_encounter_async() via the `agents=` map.
Talks to the locally-hosted OpenAI-compatible endpoint already
configured in `config.LLM_ENDPOINT` (LM Studio on the dev Mac, Ollama
on the GX10). No external/cloud calls.

Design choices:
    - **Single round-trip.** The seven pipeline stages share one LLM
      call. The first stage to run primes a cached "bundle" inside the
      orchestrator's `state` dict; the rest slice their own section
      out of it. This keeps the pluggable-stage abstraction intact
      while reducing latency from ~7 sequential calls to one.
    - **Fail-soft.** If the LLM is unreachable / timed out / returns
      malformed JSON, every stage degrades to its no-op fallback so
      the rest of the pipeline (failsafe, crisis_view, learning,
      tone) still produces a usable response.
    - **No diagnosis claims.** The system prompt enforces "rule out",
      "check next", "escalate" language and forbids definitive
      diagnoses. The model is asked for plain-language top-3 lists
      so the crisis_view layer has clean input.
    - **Offline aware.** `LLM_LAST_STATUS` is updated on every call
      so callers can surface it in `offline_status`.

Public API:
    LLM_AGENTS                  → dict[str, async stage]
    LLM_LAST_STATUS             → "ok" | "unreachable" | "invalid" | "unknown"
    health_check_sync()         → quick ping for status snapshots
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from . import config, inference, retrieval

LOG = logging.getLogger("aegis.llm_agents")

# Updated by every reasoning pass so the route handler can surface
# status (e.g. "unreachable" → frontend shows a degraded badge).
LLM_LAST_STATUS: str = "unknown"
LLM_LAST_LATENCY_MS: int | None = None
LLM_LAST_MODEL: str | None = None


# ---------------------------------------------------------------------
# System prompt (single-call bundle)
# ---------------------------------------------------------------------
_SYSTEM_PROMPT = """You are AEGIS, an offline clinical decision-support reasoner.

You are NOT a chatbot and you are NOT a diagnostic engine. You help
non-expert first responders in austere environments (refugee zones,
submarines, combat, disaster, remote) decide what to check next and
what is dangerous to miss.

Hard rules:
  1. Never make a diagnostic claim. Use "rule out", "check next",
     "consider", "treat as high risk until ruled out", "escalate".
  2. Use short plain-language items. Each list item must be one short
     phrase a non-expert can act on. No long sentences. No jargon.
  3. If information is missing, prefer asking a question over guessing.
  4. The most dangerous causes go first in rule-outs.
  5. Output STRICT JSON ONLY. No prose, no markdown, no code fences.
  6. If the encounter contains a `scenario_context` block, treat its
     `case` and `primer_prompt` as ground truth about the patient and
     align `protocol.immediate_actions` with the procedural intent of
     `scenario_context.steps`. You may reorder, refine wording, or
     consolidate; do NOT introduce protocol items unrelated to the
     scenario. Emit 4 to 8 immediate_actions when scenario_context is
     present, otherwise emit up to 3.

Output schema (every key present, even if empty):
{
  "triage": {
    "acuity": "red" | "yellow" | "green",
    "actions": [string, ...],          // up to 3 immediate actions
    "key_findings": [string, ...]      // up to 3 short concerning findings
  },
  "differential": {
    "rule_outs": [string, ...]         // up to 3, dangerous-first
  },
  "risk": {
    "risk_score": "high" | "medium" | "low",
    "risk_factors": [string, ...]      // up to 3 short phrases
  },
  "protocol": {
    "immediate_actions": [
      {
        "label": string,        // one short imperative phrase
        "keywords": [string]    // 2-5 lowercase trigger words a voice
                                // extractor would emit for this step
                                // (e.g. ["tourniquet", "cat"] for a
                                // tourniquet step). Required when
                                // scenario_context is present.
      },
      ...
    ]
  },
  "missed_signals": {
    "missed_signals": [string, ...],   // up to 3 things often missed
    "recommended_actions": [string, ...]
  },
  "questions": {
    "questions": [string, ...]         // up to 3 next questions/checks
  }
}

Acuity guidance:
  - red: airway/breathing/circulation threat, severe bleeding,
    altered mental status, shock signs, suspected MI/PE/stroke.
  - yellow: significant symptoms but stable, vitals slightly off,
    pain without instability.
  - green: minor or stable presentation.

Remember: every list item is short, plain, actionable. Output JSON only."""


def _build_user_prompt(encounter: dict) -> str:
    """Compact, deterministic dump of the encounter for the model.

    When `scenario_context` is present on the encounter, it is included
    verbatim so the model can align `protocol.immediate_actions` with
    the scenario's expected procedural steps.
    """
    payload = {
        "chief_complaint": encounter.get("chief_complaint", ""),
        "context": encounter.get("context", ""),
        "mental_status": encounter.get("mental_status"),
        "breathing": encounter.get("breathing"),
        "bleeding": encounter.get("bleeding"),
        "vitals": encounter.get("vitals") or {},
        "symptoms": encounter.get("symptoms") or [],
    }
    sc = encounter.get("scenario_context")
    if sc:
        payload["scenario_context"] = sc
    return (
        "Encounter:\n"
        + json.dumps(payload, indent=2, ensure_ascii=False)
        + "\n\nReturn the JSON object now."
    )


# Empty bundle returned when the LLM is unreachable or returns garbage.
_EMPTY_BUNDLE: dict[str, dict] = {
    "triage":         {"acuity": "yellow", "actions": [], "key_findings": []},
    "differential":   {"rule_outs": []},
    "risk":           {"risk_score": None, "risk_factors": []},
    "protocol":       {"immediate_actions": []},
    "missed_signals": {"missed_signals": [], "recommended_actions": []},
    "questions":      {"questions": []},
}


_KEYWORD_STOPWORDS = frozenset({
    "and", "the", "for", "with", "from", "into", "over", "this",
    "that", "your", "any", "all", "some", "are", "was", "were",
    "have", "has", "had", "you", "her", "his", "its", "now", "next",
    "then", "after", "before", "place", "apply", "begin", "start",
    "stop", "check", "verify", "ensure", "every", "each", "use",
    "using", "until", "when", "while", "patient", "casualty",
})


def _derive_keywords(label: str) -> list[str]:
    """Tokenize a label into 2-5 lowercase trigger words for extraction
    matching. Used as a fallback when the model omits the keywords field."""
    if not label:
        return []
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in label.lower().replace("/", " ").replace("-", " ").split():
        tok = "".join(ch for ch in raw if ch.isalpha())
        if len(tok) < 4:
            continue
        if tok in _KEYWORD_STOPWORDS:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        tokens.append(tok)
        if len(tokens) >= 5:
            break
    return tokens


def _normalize_action_item(item: Any, idx: int) -> dict | None:
    """Coerce a single immediate_actions item into {id, label, keywords}.

    Accepts either a bare string (legacy) or a dict with `label` (and
    optionally `keywords`). IDs are assigned by the backend regardless
    of what the model emitted — never trust LLM-supplied IDs."""
    if isinstance(item, str):
        label = item.strip()
        keywords: list[str] = []
    elif isinstance(item, dict):
        label = str(item.get("label") or item.get("text")
                    or item.get("action") or item.get("name") or "").strip()
        kw_raw = item.get("keywords") or []
        keywords = []
        if isinstance(kw_raw, list):
            seen: set[str] = set()
            for k in kw_raw:
                if not isinstance(k, str):
                    continue
                k = k.strip().lower()
                if not k or k in seen:
                    continue
                seen.add(k)
                keywords.append(k)
                if len(keywords) >= 5:
                    break
    else:
        return None
    if not label:
        return None
    if not keywords:
        keywords = _derive_keywords(label)
    return {
        "id": f"ai-{idx:03d}",
        "label": label,
        "keywords": keywords,
    }


def _normalize_bundle(raw: Any) -> dict:
    """Coerce model output into the schema, trimming to top-3 everywhere
    except protocol.immediate_actions which can grow to 8 when scenario
    context is in play (the procedural checklist needs more items)."""
    if not isinstance(raw, dict):
        return dict(_EMPTY_BUNDLE)
    out = {k: dict(v) for k, v in _EMPTY_BUNDLE.items()}

    def _trim(items: Any, n: int = 3) -> list[str]:
        if not isinstance(items, list):
            return []
        result: list[str] = []
        for item in items:
            if len(result) >= n:
                break
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif isinstance(item, dict):
                text = (item.get("text") or item.get("label")
                        or item.get("name") or "")
                if text:
                    result.append(str(text).strip())
        return result

    t = raw.get("triage") or {}
    if isinstance(t, dict):
        ac = str(t.get("acuity") or "yellow").lower()
        if ac not in {"red", "yellow", "green"}:
            ac = "yellow"
        out["triage"] = {
            "acuity": ac,
            "actions": _trim(t.get("actions"), 3),
            "key_findings": _trim(t.get("key_findings"), 3),
        }

    d = raw.get("differential") or {}
    if isinstance(d, dict):
        out["differential"] = {"rule_outs": _trim(d.get("rule_outs"), 3)}

    r = raw.get("risk") or {}
    if isinstance(r, dict):
        rs = r.get("risk_score")
        if isinstance(rs, str):
            rs = rs.lower() if rs.lower() in {"high", "medium", "low"} else None
        out["risk"] = {
            "risk_score": rs,
            "risk_factors": _trim(r.get("risk_factors"), 3),
        }

    p = raw.get("protocol") or {}
    if isinstance(p, dict):
        raw_actions = p.get("immediate_actions") or p.get("steps") or []
        actions: list[dict] = []
        if isinstance(raw_actions, list):
            for item in raw_actions:
                if len(actions) >= 8:
                    break
                normalized = _normalize_action_item(item, len(actions) + 1)
                if normalized:
                    actions.append(normalized)
        out["protocol"] = {"immediate_actions": actions}

    m = raw.get("missed_signals") or {}
    if isinstance(m, dict):
        out["missed_signals"] = {
            "missed_signals": _trim(m.get("missed_signals"), 3),
            "recommended_actions": _trim(m.get("recommended_actions"), 3),
        }

    q = raw.get("questions") or {}
    if isinstance(q, dict):
        out["questions"] = {"questions": _trim(q.get("questions"), 3)}

    return out


# ---------------------------------------------------------------------
# Bundle priming (called by the first stage to run)
# ---------------------------------------------------------------------
async def _ensure_bundle(encounter: dict, state: dict) -> dict:
    """Populate state['llm_bundle'] with a single LLM call. Idempotent."""
    global LLM_LAST_STATUS, LLM_LAST_LATENCY_MS, LLM_LAST_MODEL

    if "llm_bundle" in state:
        return state["llm_bundle"]

    user_prompt = _build_user_prompt(encounter)

    try:
        # 4096 tokens budget: Gemma 4 31B emits a separate `reasoning`
        # chain-of-thought field that consumes tokens *before* the
        # visible `content` JSON. With the richer scenario-aware schema
        # (immediate_actions = [{label, keywords}, ...]) the prior 900
        # cap was tight enough to truncate `content` mid-object.
        parsed, meta = await inference.call_llm_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=config.LLM_TEMPERATURE_STRUCTURED,
            max_tokens=4096,
        )
    except inference.LLMError as exc:
        LOG.warning("LLM agents unreachable, falling back to empty bundle: %s", exc)
        LLM_LAST_STATUS = "unreachable"
        LLM_LAST_LATENCY_MS = None
        LLM_LAST_MODEL = config.LLM_MODEL
        bundle = dict(_EMPTY_BUNDLE)
        state["llm_bundle"] = bundle
        state["llm_meta"] = {"status": "unreachable", "error": str(exc)}
        return bundle
    except Exception as exc:                              # noqa: BLE001
        LOG.exception("LLM agents unexpected error: %s", exc)
        LLM_LAST_STATUS = "invalid"
        bundle = dict(_EMPTY_BUNDLE)
        state["llm_bundle"] = bundle
        state["llm_meta"] = {"status": "invalid", "error": str(exc)}
        return bundle

    LLM_LAST_STATUS = "ok"
    LLM_LAST_LATENCY_MS = meta.get("latency_ms")
    LLM_LAST_MODEL = meta.get("model") or config.LLM_MODEL

    bundle = _normalize_bundle(parsed)
    state["llm_bundle"] = bundle
    state["llm_meta"] = {
        "status": "ok",
        "latency_ms": meta.get("latency_ms"),
        "prompt_tokens": meta.get("prompt_tokens"),
        "completion_tokens": meta.get("completion_tokens"),
        "model": meta.get("model"),
        "endpoint": meta.get("endpoint"),
    }
    return bundle


# ---------------------------------------------------------------------
# Stage agents (each slices its section from the shared bundle)
# ---------------------------------------------------------------------
async def llm_rules(encounter: dict, state: dict) -> dict:
    # Rules stage: keep deterministic — no LLM. Surface what the
    # encounter explicitly told us as "matched_rules" (so the audit
    # trail shows what the structured intake captured).
    flags: list[str] = []
    if encounter.get("mental_status") == "no":
        flags.append("unconscious")
    if encounter.get("breathing") == "no":
        flags.append("abnormal_breathing")
    if encounter.get("bleeding") == "heavy":
        flags.append("severe_bleeding")
    return {"matched_rules": flags, "flags": flags}


async def llm_triage(encounter: dict, state: dict) -> dict:
    bundle = await _ensure_bundle(encounter, state)
    return dict(bundle["triage"])


async def llm_differential(encounter: dict, state: dict) -> dict:
    bundle = await _ensure_bundle(encounter, state)
    return dict(bundle["differential"])


async def llm_risk(encounter: dict, state: dict) -> dict:
    bundle = await _ensure_bundle(encounter, state)
    return dict(bundle["risk"])


async def llm_protocol(encounter: dict, state: dict) -> dict:
    bundle = await _ensure_bundle(encounter, state)
    return dict(bundle["protocol"])


async def llm_missed(encounter: dict, state: dict) -> dict:
    bundle = await _ensure_bundle(encounter, state)
    return dict(bundle["missed_signals"])


async def llm_questions(encounter: dict, state: dict) -> dict:
    bundle = await _ensure_bundle(encounter, state)
    return dict(bundle["questions"])


LLM_AGENTS = {
    "rules":          llm_rules,
    "triage":         llm_triage,
    "differential":   llm_differential,
    "risk":           llm_risk,
    "protocol":       llm_protocol,
    "missed_signals": llm_missed,
    "questions":      llm_questions,
}


# ---------------------------------------------------------------------
# V6 — Intake-driven encounter generation
# ---------------------------------------------------------------------
# When the operator types a situation on cockpit boot, we ask the LLM
# to produce an encounter title, patient label, ordered procedural
# steps, and an initial brief. The cockpit renders these instead of
# falling back to a hardcoded scenario.
_INTAKE_SYSTEM_PROMPT = """You are AEGIS, an offline clinical decision-support reasoner for non-expert first responders in austere environments.

The operator will type a brief description of the situation they are facing. Produce a JSON object that drives the cockpit for the rest of this encounter. Output STRICT JSON ONLY — no prose, no markdown, no code fences.

You will receive a [CORPUS] block containing excerpts from authoritative medical guidelines (TCCC, AHA, WHO, ILCOR). Each excerpt is tagged with a citation id like `[AHA-COMPRESSION-RATE]`. Use these excerpts as the source of truth for the procedural detail (rates, depths, doses, ratios) that you write into instructions and the brief. Embed the citation id in square brackets at the end of any sentence whose specific number, technique, or claim came from a chunk. Do NOT cite chunks you didn't use.

Schema (every key required):
{
  "title": "<2-4 word scenario title, e.g. 'Pediatric Asthma' or 'Penetrating Chest Wound'>",
  "patient_label": "<short label like PT-RESP-001 (max 24 chars)>",
  "steps": [
    {
      "id": "step_1",
      "title": "<UPPERCASE 1-3 WORD STEP TITLE>",
      "icon": "<one of: crosshair, pulse, breath, drop, bolt, shield, ruler, pill, ambulance, tag>",
      "instruction": "<~50 word how-to that a complete layperson can carry out, with [CITATION_ID] tags after any specific number/technique drawn from the corpus>",
      "checklist_text": "<one-line corresponding checklist row, plain language>",
      "why_matters": "<2-3 sentence clinical context, with [CITATION_ID] where relevant>",
      "affirmation": "<6-10 word past-tense first-person sentence the operator says when they finish this step, e.g. 'I have started chest compressions.' or 'The airway is open.'>"
    }
  ],
  "brief": {
    "acuity": "red" | "yellow" | "green",
    "top_actions": [string, ...],
    "rule_outs": [string, ...],
    "summary": "<1-3 sentence acuity rationale referencing the situation, with [CITATION_ID] where relevant>"
  }
}

Hard rules:
  - 4 to 6 ordered steps. First step is the most time-critical action.
  - Step ids must be unique slugs like step_1, step_2, ...
  - **Each `instruction` must be 40 to 60 words** (target ~50). Write it as if speaking to a panicked bystander with zero medical training. Spell out:
      • exactly where to put hands / what to look at
      • exactly what counts as success ("until you see the chest rise", "until you feel a strong pulse for at least 10 seconds")
      • a concrete number when one exists (depth, rate, count, seconds)
      • what to do if the obvious approach fails (one short fallback)
  - Use everyday words. No clinical jargon unless you immediately define it in the same sentence (e.g. "the carotid pulse — the one on the side of the neck").
  - Use "consider", "rule out", "treat as high risk until ruled out" — never make a definitive diagnostic claim.
  - `checklist_text` stays short (one line, ~6-10 words) — it's the row label, not the how-to. NO citation tags inside checklist_text.
  - `why_matters` is the clinical reasoning, NOT the procedure. Don't repeat the instruction here.
  - Most dangerous causes first in rule_outs.
  - The brief.summary should reference what the operator said.
  - Citation tags are exactly `[ID]` (square brackets, no extra punctuation inside). Cite at MOST one chunk per sentence. Prefer the most specific chunk available.
  - When the corpus does not cover a technique, you may still write the step (use general first-aid knowledge), but DO NOT invent a citation id.

Worked example of a good `instruction` (~50 words) with a citation:
  "Kneel beside the patient. Place the heel of one hand on the center of their chest, between the nipples. Place your other hand on top, fingers laced. Press straight down hard and fast — about 2 inches deep, 100 to 120 times per minute [AHA-COMPRESSION-RATE]. Don't stop until help arrives."
"""


def _norm_str_list(items, max_n: int = 5) -> list[str]:
    out: list[str] = []
    if not isinstance(items, list):
        return out
    for x in items:
        if isinstance(x, dict):
            x = x.get("text") or x.get("label") or x.get("name") or ""
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
        if len(out) >= max_n:
            break
    return out


_VALID_ICONS = frozenset({
    "crosshair", "pulse", "breath", "drop", "bolt",
    "shield", "ruler", "pill", "ambulance", "tag",
})


def _normalize_intake(raw: Any) -> dict:
    """Coerce LLM intake output into a safe shape with reasonable defaults."""
    if not isinstance(raw, dict):
        raw = {}
    title = str(raw.get("title") or "Encounter").strip()[:60] or "Encounter"
    patient_label = str(raw.get("patient_label") or "PT-LLM-001").strip()[:24] \
        or "PT-LLM-001"

    steps: list[dict] = []
    raw_steps = raw.get("steps")
    if isinstance(raw_steps, list):
        for i, s in enumerate(raw_steps[:8]):
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id") or f"step_{i+1}").strip() or f"step_{i+1}"
            step_title = str(s.get("title") or "ASSESS").strip().upper()[:32] \
                or "ASSESS"
            icon = str(s.get("icon") or "pulse").strip().lower()
            if icon not in _VALID_ICONS:
                icon = "pulse"
            instruction = str(s.get("instruction") or "").strip()
            checklist_text = (str(s.get("checklist_text") or "").strip()
                              or instruction)
            why_matters = str(s.get("why_matters") or "").strip()
            # V6 — short past-tense first-person line shown on the
            # MARK STEP COMPLETE button when this step is current. If
            # the model omits it, fall back to "I have completed
            # <title in lowercase>." which the frontend also computes
            # client-side as a defensive default.
            affirmation_raw = str(s.get("affirmation") or "").strip()
            if not affirmation_raw:
                affirmation_raw = (
                    f"I have completed {step_title.lower()}."
                )
            steps.append({
                "id": sid,
                "title": step_title,
                "icon": icon,
                "instruction": instruction,
                "checklist_text": checklist_text,
                "why_matters": why_matters,
                "affirmation": affirmation_raw[:120],
                "question": None,
                "jump_to": [],
            })
    if not steps:
        steps = [{
            "id": "assess",
            "title": "ASSESS",
            "icon": "pulse",
            "instruction": "Begin assessment of airway, breathing, and circulation.",
            "checklist_text": "Begin ABC assessment.",
            "why_matters": "",
            "question": None,
            "jump_to": [],
        }]

    raw_brief = raw.get("brief") if isinstance(raw.get("brief"), dict) else {}
    acuity = str(raw_brief.get("acuity") or "yellow").strip().lower()
    if acuity not in {"red", "yellow", "green"}:
        acuity = "yellow"
    brief = {
        "acuity": acuity,
        "top_actions": _norm_str_list(raw_brief.get("top_actions"), 5),
        "rule_outs": _norm_str_list(raw_brief.get("rule_outs"), 5),
        "summary": str(raw_brief.get("summary") or "").strip()[:600],
    }
    return {
        "title": title,
        "patient_label": patient_label,
        "steps": steps,
        "brief": brief,
    }


_CITATION_RE = re.compile(r"\[([A-Z][A-Z0-9_-]{2,})\]")


def _collect_cited_ids(intake: dict) -> set[str]:
    """Walk every text field of the normalized intake and return the set
    of citation ids the model actually emitted in `[BRACKETS]`."""
    cited: set[str] = set()

    def _scan(s):
        if isinstance(s, str):
            cited.update(_CITATION_RE.findall(s))

    for step in intake.get("steps") or []:
        _scan(step.get("instruction"))
        _scan(step.get("why_matters"))
    brief = intake.get("brief") or {}
    _scan(brief.get("summary"))
    for a in brief.get("top_actions") or []:
        _scan(a)
    for r in brief.get("rule_outs") or []:
        _scan(r)
    return cited


async def intake_to_encounter(situation: str) -> tuple[dict, dict]:
    """Ask the LLM to convert a typed situation into an encounter scaffold,
    grounded in the local medical corpus (TCCC / AHA / WHO / ILCOR chunks).

    Returns (intake_data, metadata). intake_data has shape:
        {
          title, patient_label,
          steps[]:  each may carry [CITATION_ID] tags inside instruction/why_matters,
          brief{acuity, top_actions, rule_outs, summary},
          citations[]: chunks the model actually cited, with citation_id +
                       supporting_quote + source + page so the UI can
                       render clickable evidence pills.
        }
    metadata carries latency_ms / token counts from inference.call_llm_json.
    Raises inference.LLMError if the LLM is unreachable.
    """
    situation = (situation or "").strip()

    # RAG: pull the most relevant guideline excerpts so the model has
    # authoritative numbers (compression rate, tourniquet height, ORS
    # volume, etc.) to cite. None as scenario_filter → full corpus.
    try:
        chunks = await retrieval.retrieve(situation, None, k=8)
    except Exception:
        chunks = []

    user_prompt_parts = [f"Situation:\n{situation}"]
    if chunks:
        user_prompt_parts.append("[CORPUS]\n" + inference._format_chunks(chunks))
    user_prompt_parts.append("Return the JSON object now.")
    user_prompt = "\n\n".join(user_prompt_parts)

    # ~50-word instructions × 6 steps + checklist + why_matters + brief
    # comfortably fits under 3072; the previous 2048 occasionally truncated
    # the trailing brief block when the model wrote longer steps.
    parsed, meta = await inference.call_llm_json(
        system_prompt=_INTAKE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=config.LLM_TEMPERATURE_STRUCTURED,
        max_tokens=3072,
    )
    intake = _normalize_intake(parsed)

    # Match the model's [BRACKETS] back to retrieved chunks. Anything
    # the model invented that doesn't match a real chunk is dropped from
    # the citations list (it stays as a tag in the text — the frontend
    # renders it as a pill but it won't open a real source). This keeps
    # us honest: only chunks the corpus actually contains are citable.
    cited_ids = _collect_cited_ids(intake)
    citations = []
    for c in chunks:
        cid = c.get("citation_id")
        if cid in cited_ids:
            citations.append({
                "citation_id": cid,
                "supporting_quote": (c.get("text") or "")[:240],
                "source": c.get("source") or c.get("source_short") or "",
                "page": c.get("page"),
                "section": c.get("section"),
            })
    intake["citations"] = citations

    return intake, meta


# ---------------------------------------------------------------------
# Status snapshot helpers
# ---------------------------------------------------------------------
def status_snapshot() -> dict:
    """Lightweight status for the offline_status block."""
    return {
        "mode": "OFFLINE ACTIVE",
        "cloud_calls": 0,
        "local_llm": {
            "endpoint": config.LLM_ENDPOINT,
            "model": LLM_LAST_MODEL or config.LLM_MODEL,
            "status": LLM_LAST_STATUS,
            "last_latency_ms": LLM_LAST_LATENCY_MS,
        },
    }


def health_check_sync() -> dict:
    """Best-effort sync health probe — for status endpoints that don't
    want to wait on a full inference round-trip."""
    try:
        return asyncio.run(inference.health_check())
    except RuntimeError:
        # already inside an event loop — caller should await directly
        return {"reachable": None, "model_loaded": None}
    except Exception as exc:                              # noqa: BLE001
        return {"reachable": False, "error": str(exc)}
