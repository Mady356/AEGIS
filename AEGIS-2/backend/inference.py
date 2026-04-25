"""
V5 AEGIS LLM client — OpenAI-compatible.

The same client talks to LM Studio (`http://localhost:1234/v1`) on the
developer's Mac and Ollama (`http://localhost:11434/v1`) on the GX10.
Switching is a single environment variable: LLM_ENDPOINT.

Public surface:

  Low-level
    - call_llm_json(system, user, ...)  → (parsed_json, metadata)
    - stream_llm(system, user, ...)     → async iterator of token chunks
    - health_check()                    → {reachable, model_loaded, ...}

  Four-job wrappers (preserve V4 endpoint signatures)
    - extract_facts(transcript, encounter_id, scenario_name, elapsed_seconds)
    - answer_question(question, scenario_context)
    - compute_nudges(encounter_state)
    - generate_aar(encounter_record, chunks=None)

When the LLM is unreachable, each wrapper falls back to a schema-faithful
canned response sourced from the curated corpus, and logs the fallback at
WARNING level. The endpoint contracts never break.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from typing import AsyncIterator, Optional

from . import config, prompts, retrieval

LOG = logging.getLogger("aegis.inference")

# Last-turn telemetry surfaced via /api/system/status.
LAST_LATENCY_MS: Optional[int] = None
LAST_TPS: Optional[float] = None
LAST_PROMPT_TOKENS: Optional[int] = None
LAST_COMPLETION_TOKENS: Optional[int] = None


# ---------------------------------------------------------------------
# OpenAI-compatible client
# ---------------------------------------------------------------------
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        from openai import AsyncOpenAI  # type: ignore
    except ImportError as exc:
        raise LLMError(
            "openai package not installed. pip install -r requirements.txt"
        ) from exc
    _client = AsyncOpenAI(
        base_url=config.LLM_ENDPOINT,
        api_key=config.LLM_API_KEY,
        timeout=config.LLM_REQUEST_TIMEOUT_SECONDS,
    )
    return _client


class LLMError(Exception):
    """Raised when the LLM call fails or returns invalid output."""


# ---------------------------------------------------------------------
# Low-level: structured JSON
# ---------------------------------------------------------------------
async def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[dict, dict]:
    """Call the LLM expecting a JSON object response.

    Returns (parsed_json, metadata) where metadata contains latency_ms
    and token counts (when the server returns them).

    Raises LLMError on transport or parse failure.
    """
    global LAST_LATENCY_MS, LAST_PROMPT_TOKENS, LAST_COMPLETION_TOKENS

    temperature = (temperature if temperature is not None
                   else config.LLM_TEMPERATURE_STRUCTURED)
    max_tokens = (max_tokens if max_tokens is not None
                  else config.LLM_MAX_TOKENS_STRUCTURED)

    client = _get_client()
    started = time.perf_counter()
    try:
        from openai import APIError, APITimeoutError  # type: ignore
        try:
            # LM Studio's OpenAI-compat layer accepts only "text" or
            # "json_schema" for response_format (not "json_object" like
            # OpenAI proper). Our system prompts enforce JSON output and
            # _parse_json() tolerates fences + leading prose, so plain
            # text mode is the portable choice.
            response = await client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except APITimeoutError as exc:
            LOG.error("LLM request timed out after %.1fs",
                      config.LLM_REQUEST_TIMEOUT_SECONDS)
            raise LLMError(f"LLM timed out: {exc}") from exc
        except APIError as exc:
            LOG.error("LLM API error: %s", exc)
            raise LLMError(f"LLM API error: {exc}") from exc
    except ImportError as exc:
        raise LLMError(str(exc)) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    LAST_LATENCY_MS = latency_ms

    content = response.choices[0].message.content
    if not content:
        raise LLMError("LLM returned empty response")

    parsed = _parse_json(content)
    if parsed is None:
        LOG.error("LLM returned invalid JSON. Raw content (truncated): %r",
                  content[:500])
        raise LLMError("LLM returned invalid JSON")

    usage = getattr(response, "usage", None)
    metadata = {
        "latency_ms": latency_ms,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "model": config.LLM_MODEL,
        "endpoint": config.LLM_ENDPOINT,
    }
    LAST_PROMPT_TOKENS = metadata["prompt_tokens"]
    LAST_COMPLETION_TOKENS = metadata["completion_tokens"]
    LOG.info("LLM JSON call: %dms · %s prompt / %s completion tokens",
             latency_ms, metadata["prompt_tokens"], metadata["completion_tokens"])
    return parsed, metadata


def _parse_json(content: str) -> Optional[dict]:
    """Tolerant JSON parsing — strips markdown fencing and finds the
    first {...} block if the model emits prose around it."""
    if not content:
        return None
    s = content.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]+\}", s)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


# ---------------------------------------------------------------------
# Low-level: streaming text
# ---------------------------------------------------------------------
async def stream_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """Stream tokens from the LLM. Yields text chunks as they arrive."""
    global LAST_LATENCY_MS, LAST_TPS

    temperature = (temperature if temperature is not None
                   else config.LLM_TEMPERATURE_NARRATIVE)
    max_tokens = (max_tokens if max_tokens is not None
                  else config.LLM_MAX_TOKENS_AAR)

    client = _get_client()
    started = time.perf_counter()
    char_count = 0
    first_token_at: Optional[float] = None

    try:
        from openai import APIError, APITimeoutError  # type: ignore
        stream = await client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content
            except Exception:
                delta = None
            if delta:
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                char_count += len(delta)
                yield delta
    except APITimeoutError as exc:
        LOG.error("LLM stream timed out: %s", exc)
        raise LLMError(f"LLM stream timed out: {exc}") from exc
    except APIError as exc:
        LOG.error("LLM stream API error: %s", exc)
        raise LLMError(f"LLM stream error: {exc}") from exc

    elapsed = time.perf_counter() - started
    LAST_LATENCY_MS = int(elapsed * 1000)
    if first_token_at is not None and char_count > 0:
        stream_seconds = max(time.perf_counter() - first_token_at, 1e-3)
        # Rough chars-per-second → tokens-per-second proxy (~4 chars/token)
        LAST_TPS = round((char_count / 4) / stream_seconds, 1)


# ---------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------
async def health_check() -> dict:
    """Probe the LLM endpoint. Used by /api/system/status."""
    try:
        client = _get_client()
        models = await client.models.list()
        available = []
        for m in getattr(models, "data", []) or []:
            mid = getattr(m, "id", None) or getattr(m, "name", None)
            if mid:
                available.append(mid)
        return {
            "reachable": True,
            "endpoint": config.LLM_ENDPOINT,
            "configured_model": config.LLM_MODEL,
            "available_models": available,
            "model_loaded": config.LLM_MODEL in available,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "endpoint": config.LLM_ENDPOINT,
            "configured_model": config.LLM_MODEL,
            "error": str(exc),
        }


# =====================================================================
# Four-job wrappers (preserve V4 endpoint signatures)
# =====================================================================

async def extract_facts(transcript: str,
                         encounter_id: str,
                         scenario_name: str = "",
                         elapsed_seconds: int = 0) -> dict:
    try:
        system, user = prompts.render_user_prompt(
            "extraction",
            transcript=transcript,
            encounter_id=encounter_id,
            scenario_name=scenario_name,
            elapsed_seconds=elapsed_seconds,
        )
        result, _meta = await call_llm_json(system, user)
        return result
    except (LLMError, FileNotFoundError) as exc:
        LOG.warning("extraction LLM unreachable, using canned: %s", exc)
        return _extraction_canned(transcript)


async def answer_question(question: str,
                           scenario_context: Optional[str] = None) -> dict:
    # k=3 keeps the prompt under ~2K tokens which fits LM Studio's
    # default 4K context window with comfortable margin for completion.
    chunks = await retrieval.retrieve(question, scenario_context, k=3)
    if not chunks:
        return {
            "answer_type": "refused", "answer_text": None, "citations": [],
            "refusal_reason": ("No corpus chunks indexed locally. Ingest "
                               "the corpus before issuing reference queries."),
        }

    chunks_block = _format_chunks(chunks)
    try:
        system, user = prompts.render_user_prompt(
            "qa",
            question=question,
            chunks_formatted=chunks_block,
        )
        result, _meta = await call_llm_json(system, user)
        return result
    except (LLMError, FileNotFoundError) as exc:
        LOG.warning("QA LLM unreachable, using canned: %s", exc)
        return _qa_canned(question, chunks)


async def compute_nudges(encounter_state: dict) -> dict:
    scenario = (encounter_state.get("scenario_id")
                or encounter_state.get("scenario") or "")
    chunks = await retrieval.retrieve(
        f"protocol steps {scenario}", scenario, k=3,
    )
    chunks_block = _format_chunks(chunks)
    try:
        system, user = prompts.render_user_prompt(
            "nudges",
            scenario_name=encounter_state.get("scenario_name", scenario),
            elapsed_seconds=int(encounter_state.get("elapsed_seconds", 0)),
            extracted_facts_json=json.dumps(
                encounter_state.get("extracted_facts") or {}
            ),
            completed_items=", ".join(
                encounter_state.get("completed_checklist_items") or []
            ),
            chunks_formatted=chunks_block,
        )
        result, _meta = await call_llm_json(system, user)
        return result
    except (LLMError, FileNotFoundError) as exc:
        LOG.warning("nudges LLM unreachable, using canned: %s", exc)
        return _nudges_canned(encounter_state, chunks)


async def generate_aar(encounter_record: dict,
                        chunks: list[dict] | None = None) -> dict:
    if chunks is None:
        chunks = await retrieval.retrieve(
            "protocol compliance review",
            encounter_record.get("scenario_id"), k=4,
        )
    chunks_block = _format_chunks(chunks)
    record_json = json.dumps(encounter_record, default=str, indent=2)[:8000]
    try:
        system, user = prompts.render_user_prompt(
            "aar",
            encounter_record_json=record_json,
            chunks_formatted=chunks_block,
        )
        result, _meta = await call_llm_json(system, user,
                                             max_tokens=config.LLM_MAX_TOKENS_AAR)
        return result
    except (LLMError, FileNotFoundError) as exc:
        LOG.warning("AAR LLM unreachable, using canned: %s", exc)
        return _aar_canned(encounter_record, chunks)


# =====================================================================
# Helpers
# =====================================================================

def _format_chunks(chunks: list[dict], max_chars_per_chunk: int = 500) -> str:
    """Format retrieved chunks for inclusion in a user prompt.

    Each chunk is truncated to keep the total prompt under tighter
    context budgets (LM Studio's default is often 4K tokens). The full
    chunk text remains accessible to the citation overlay.
    """
    if not chunks:
        return "(no chunks retrieved)"
    parts = []
    for c in chunks:
        cid = c.get("citation_id") or c.get("id") or "?"
        src = c.get("source_short") or c.get("source") or c.get("document") or "?"
        page = c.get("page") if c.get("page") not in (None, "") else "?"
        text = (c.get("text") or "").strip()
        if len(text) > max_chars_per_chunk:
            text = text[:max_chars_per_chunk].rsplit(" ", 1)[0] + " [...]"
        parts.append(f"[{cid}] (source: {src}, page: {page})\n{text}")
    return "\n\n".join(parts)


# =====================================================================
# Canned fallbacks (used when LLM is unreachable so the demo never breaks)
# =====================================================================

def _extraction_canned(transcript: str) -> dict:
    t = (transcript or "").lower()
    if not t.strip():
        return {
            "patient": None, "mechanism": None,
            "vitals_observed": [], "interventions_performed": [],
            "extraction_confidence": "low",
            "notes": "Insufficient clinical content for extraction.",
        }
    patient = {"age": None, "sex": None, "weight_kg": None,
               "demographics_notes": None}
    mechanism = {"category": None, "description": None}
    vitals: list[dict] = []
    interventions: list[dict] = []

    def _span(needle: str) -> str:
        i = t.find(needle.lower())
        if i < 0: return needle
        return transcript[i : i + min(len(needle) + 30, len(transcript) - i)].strip()

    if m := re.search(r"(\d{1,3})\s*(?:year|yr|yo|years old)", t):
        patient["age"] = int(m.group(1))
    if "male" in t and "female" not in t: patient["sex"] = "male"
    elif "female" in t: patient["sex"] = "female"
    if m := re.search(r"(\d+(?:\.\d+)?)\s*(?:kilogram|kg)", t):
        patient["weight_kg"] = float(m.group(1))
    if "gunshot" in t or "gsw" in t:
        mechanism = {"category": "penetrating", "description": "gunshot wound"}
    elif "submer" in t or "drown" in t:
        mechanism = {"category": "environmental",
                     "description": "submersion / drowning"}
    elif "fever" in t or "lethargic" in t:
        mechanism = {"category": "medical", "description": "febrile illness"}

    if m := re.search(r"(?:fever|temp(?:erature)?)\s*(?:of\s*)?(\d{2,3}(?:\.\d)?)", t):
        vitals.append({"type": "temp", "value": f"{m.group(1)}°C",
                       "transcript_span": _span(m.group(0))})
    if "tourniquet" in t:
        interventions.append({"type": "tourniquet", "details": "applied",
                              "transcript_span": _span("tourniquet")})
    if "compression" in t:
        interventions.append({"type": "cpr",
                              "details": "compressions in progress",
                              "transcript_span": _span("compression")})
    if "paracetamol" in t or "acetaminophen" in t:
        interventions.append({"type": "medication",
                              "details": "paracetamol weight-based dosing",
                              "transcript_span": _span("paracetamol")})

    return {
        "patient": patient, "mechanism": mechanism,
        "vitals_observed": vitals,
        "interventions_performed": interventions,
        "extraction_confidence": "medium" if (vitals or interventions) else "low",
        "notes": None,
    }


def _qa_canned(question: str, chunks: list[dict]) -> dict:
    if not chunks:
        return {"answer_type": "refused", "answer_text": None, "citations": [],
                "refusal_reason": "No retrieved chunks support this question."}
    top = chunks[0]
    cid = top.get("citation_id") or top.get("id", "")
    snippet = (top.get("text") or "").strip().replace("\n", " ")
    if len(snippet) > 280:
        snippet = snippet[:280].rsplit(" ", 1)[0] + "…"
    return {
        "answer_type": "answered",
        "answer_text": (
            f"According to {top.get('source_short') or top.get('source')} "
            f"{top.get('section', '')}, {snippet}"
        ),
        "citations": [
            {"citation_id": cid, "supporting_quote": snippet}
        ],
        "refusal_reason": None,
    }


def _nudges_canned(encounter_state: dict, chunks: list[dict]) -> dict:
    if not chunks:
        return {"nudges": []}
    elapsed = int(encounter_state.get("elapsed_seconds", 0))
    completed = set(encounter_state.get("completed_checklist_items") or [])
    nudges: list[dict] = []
    sid = encounter_state.get("scenario_id", "")
    if sid in ("battlefield", "combat") and "tourniquet_applied" not in completed and elapsed > 60:
        c = next((c for c in chunks if "TQ" in (c.get("citation_id") or "")), chunks[0])
        nudges.append({
            "severity": "overdue" if elapsed < 180 else "critical_overdue",
            "step_label": "Confirm tourniquet placement and time-on-card",
            "rationale": f"No tourniquet placement event recorded {elapsed}s into encounter.",
            "citation_id": c.get("citation_id", ""),
            "supporting_quote": (c.get("text", "")[:160] + "…"),
            "issued_at_elapsed_seconds": elapsed,
        })
    return {"nudges": nudges[:3]}


def _aar_canned(rec: dict, chunks: list[dict]) -> dict:
    events = rec.get("events", []) or []
    if not events:
        return {
            "summary": "Insufficient documentation for review.",
            "timeline_highlights": [],
            "protocol_compliance": {"performed_correctly": [], "missed": [],
                                    "out_of_sequence": []},
            "teaching_points": [], "documentation_quality": "partial",
        }
    cite = chunks[0].get("citation_id", "") if chunks else ""
    quote = (chunks[0].get("text", "")[:120] + "…") if chunks else ""
    completed = [e for e in events if e.get("event_type") == "checklist_item_completed"]
    correct = [{"step": e.get("payload", {}).get("step_label", "step"),
                "citation_id": cite, "supporting_quote": quote}
               for e in completed[:3]]
    return {
        "summary": (
            f"Encounter ENC-{rec.get('id', '')} ran for "
            f"{rec.get('duration', '—')}. {len(events)} events captured. "
            f"{len(completed)} checklist items completed."
        ),
        "timeline_highlights": [
            {"time_offset_seconds": int((e.get("t_offset_ms") or 0) / 1000),
             "event_summary": e["event_type"]}
            for e in events[:6]
        ],
        "protocol_compliance": {
            "performed_correctly": correct,
            "missed": [], "out_of_sequence": [],
        },
        "teaching_points": [
            {"point": "Time-stamped intervention logging maintained.",
             "citation_id": cite}
        ] if cite else [],
        "documentation_quality": (
            "complete" if len(events) > 20 else "mostly_complete"
        ),
    }
