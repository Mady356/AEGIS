"""
AEGIS V4 — FastAPI app.

Mounts every V4 route, runs startup tasks (DB migration, monitor
coroutine), serves the frontend statically. Bound to localhost only.

Run:
    uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from . import (
    config, db, inference, monitor, records, retrieval,
    scenarios, system_status, transcription, handoff, decision_support,
)
from fastapi.responses import Response
from .models import (
    EncounterCreate, EventCreate, ReasonRequest, RetrievalQuery, DecisionSupportRequest,
)

# V4 §1 lock-down — CORS to a single origin, no wildcards.
_V4_CORS = ["http://127.0.0.1:8000"]


app = FastAPI(title="AEGIS V4 Backend", version=config.BUILD_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_V4_CORS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    db.migrate()
    await monitor.start()
    try:
        await retrieval.warmup()
    except Exception as e:
        print(f"[startup] retrieval warmup deferred: {e}")
    try:
        await transcription.warmup()
    except Exception as e:
        print(f"[startup] transcription warmup deferred: {e}")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await monitor.stop()


# =====================================================================
# Static
# =====================================================================
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(config.FRONTEND_DIR / "index.html")


@app.get("/styles.css")
async def styles() -> FileResponse:
    return FileResponse(config.FRONTEND_DIR / "styles.css", media_type="text/css")


@app.get("/app.js")
async def app_js() -> FileResponse:
    return FileResponse(config.FRONTEND_DIR / "app.js",
                        media_type="application/javascript")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "version": config.BUILD_VERSION,
            "llm_endpoint": config.LLM_ENDPOINT,
            "llm_model": config.LLM_MODEL,
            "embed_model": config.EMBED_MODEL}


# =====================================================================
# Scenarios
# =====================================================================
@app.get("/api/scenarios")
async def list_scenarios():
    return scenarios.public_list()


# =====================================================================
# Encounters & events
# =====================================================================
@app.post("/api/encounter/create")
async def encounter_create(req: EncounterCreate):
    """Create a new encounter; first event is encounter_started."""
    sc = scenarios.get(req.scenario_id)
    if not sc:
        raise HTTPException(404, f"unknown scenario {req.scenario_id}")
    label = req.patient_label or sc.get("patient_label", "PT-—")
    return records.create_encounter(req.scenario_id, label)


@app.get("/api/encounter/{enc_id}")
async def encounter_get(enc_id: str):
    rec = records.get_encounter(enc_id)
    if not rec:
        raise HTTPException(404, "encounter not found")
    return rec


@app.post("/api/encounter/{enc_id}/event")
async def encounter_event(enc_id: str, body: EventCreate):
    """Append a hashed event."""
    if records.get_encounter(enc_id) is None:
        raise HTTPException(404, "encounter not found")
    eid = records.add_event(enc_id, body.event_type, body.payload, body.t_offset_ms)
    return {"ok": True, "event_id": eid}


@app.post("/api/encounter/{enc_id}/end")
async def encounter_end(enc_id: str):
    if records.get_encounter(enc_id) is None:
        raise HTTPException(404)
    return records.end_encounter(enc_id)


@app.get("/api/encounter/{enc_id}/integrity")
async def encounter_integrity(enc_id: str):
    return records.verify_encounter_integrity(enc_id).model_dump()


@app.get("/api/encounters")
async def encounters_list(active_only: bool = False):
    return records.list_encounters(active_only=active_only)


# =====================================================================
# Retrieval
# =====================================================================
@app.post("/api/retrieve")
async def api_retrieve(q: RetrievalQuery):
    chunks = await retrieval.retrieve(q.query, q.scenario_id, q.top_k)
    return {"chunks": chunks}


@app.post("/api/decision-support")
async def api_decision_support(req: DecisionSupportRequest):
    """Structured decision support pipeline (deterministic + retrieval-backed)."""
    out = await decision_support.run_decision_support(
        req.encounter or {},
        scenario_id=req.scenario_id,
    )
    enc_id = (req.encounter or {}).get("encounter_id")
    if enc_id:
        try:
            records.add_event(enc_id, "decision_support_generated", {
                "acuity": out.get("triage", {}).get("acuity"),
                "top_rule_outs": out.get("crisis_view", {}).get("top_rule_outs", []),
            })
        except Exception:
            pass
    return out


@app.get("/api/retrieve/chunk/{citation_id}")
async def api_chunk(citation_id: str):
    chunk = await retrieval.by_id(citation_id)
    if not chunk:
        raise HTTPException(404, "citation not in local index")
    return chunk


# =====================================================================
# Transcription (WebSocket)
# =====================================================================
@app.websocket("/api/transcribe")
async def ws_transcribe(ws: WebSocket):
    await ws.accept()
    try:
        await transcription.handle(ws)
    except WebSocketDisconnect:
        return


# =====================================================================
# Reasoning (SSE)
# =====================================================================
@app.post("/api/reason")
async def api_reason(req: ReasonRequest):
    rec = records.get_encounter(req.encounter_id)
    if rec is None:
        raise HTTPException(404, "encounter not found")
    scenario_id = req.scenario_id or rec["scenario_id"]

    async def event_gen():
        # Meta with retrieved chunks (frontend uses to populate ref panel)
        try:
            chunks = await retrieval.retrieve(
                req.transcript or scenarios.get(scenario_id)["primer_prompt"],
                scenario_id, 6,
            )
        except Exception:
            chunks = []
        yield _sse({"type": "meta", "model": (
            config.LLM_MODEL if config.INFERENCE_MODE == "live"
            else "SCRIPTED // V4"
        ), "retrieved": chunks})

        async for tok in inference.stream_reasoning(
            scenario_id, req.transcript, encounter_id=req.encounter_id
        ):
            yield _sse({"type": "token", "text": tok})

        yield _sse({"type": "done", "tps": inference.LAST_TPS or 28.0})
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


def _sse(obj) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


# =====================================================================
# Vitals (per-tick evolution)
# =====================================================================
@app.post("/api/vitals")
async def api_vitals(body: dict):
    sid = body.get("scenario_id", "")
    sc = scenarios.get(sid)
    if not sc:
        raise HTTPException(404)
    return {"vitals": scenarios.vitals_for(
        sc, int(body.get("elapsed_ms") or 0), body.get("checklist") or []
    )}


# =====================================================================
# Network monitor (SSE)
# =====================================================================
@app.get("/api/network/stream")
async def network_stream(request: Request):
    async def gen():
        q = monitor.subscribe()
        try:
            last = monitor.last()
            if last:
                yield _sse(last)
            while True:
                if await request.is_disconnected(): break
                try:
                    item = await asyncio.wait_for(q.get(), timeout=10)
                    yield _sse(item)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            monitor.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/system/probes")
async def api_probes():
    return {"probes": monitor.history()}


# =====================================================================
# System status
# =====================================================================
@app.get("/api/system/status")
async def api_system_status():
    # V5 — async variant probes the LLM endpoint at the same time it
    # gathers local telemetry. The cockpit's SYS overlay polls every 4s,
    # which is slow enough to absorb the round-trip cost.
    return await system_status.status_snapshot_with_health()


# =====================================================================
# V4 — The four LLM endpoints (§4)
# =====================================================================
@app.post("/api/extract")
async def api_extract(body: dict):
    """Extract structured facts from a voice transcript."""
    transcript = body.get("transcript", "")
    enc_id = body.get("encounter_id", "")
    scenario = body.get("scenario_name", "")
    elapsed = int(body.get("elapsed_seconds", 0) or 0)
    out = await inference.extract_facts(transcript, enc_id, scenario, elapsed)
    if enc_id:
        try:
            records.add_event(enc_id, "extraction_completed",
                              {"summary": _extract_summary(out)})
        except Exception:
            pass
    return out


def _extract_summary(out: dict) -> dict:
    return {
        "vitals_count": len(out.get("vitals_observed") or []),
        "interventions_count": len(out.get("interventions_performed") or []),
        "confidence": out.get("extraction_confidence"),
    }


@app.post("/api/qa")
async def api_qa(body: dict):
    """Reference QA — operator question against the curated corpus."""
    q = body.get("question", "")
    sc = body.get("scenario_context")
    enc_id = body.get("encounter_id")
    out = await inference.answer_question(q, sc)
    if enc_id:
        try:
            records.add_event(enc_id, "qa_query",
                              {"question": q[:200],
                               "answer_type": out.get("answer_type")})
        except Exception:
            pass
    return out


@app.post("/api/nudges")
async def api_nudges(body: dict):
    """Compute compliance nudges against current encounter state."""
    state = body.get("encounter_state") or {}
    out = await inference.compute_nudges(state)
    enc_id = state.get("encounter_id")
    if enc_id and out.get("nudges"):
        for n in out["nudges"]:
            try:
                records.add_event(enc_id, "nudge_issued", n)
            except Exception:
                pass
    return out


@app.post("/api/handoff/build")
async def api_handoff_build(body: dict):
    """Build the signed .zip packet for an encounter and return it as
    application/zip with a content-disposition for direct download."""
    enc_id = body.get("encounter_id", "")
    extraction = body.get("extraction")
    aar = body.get("aar")
    if records.get_encounter(enc_id) is None:
        raise HTTPException(404, "encounter not found")
    if aar is None:
        # Generate a fresh AAR if not provided
        aar = await inference.generate_aar(records.get_encounter(enc_id))
    zip_bytes, manifest = handoff.build_packet(enc_id, extraction, aar)
    headers = {
        "Content-Disposition": f'attachment; filename="{manifest["filename"]}"',
        "X-AEGIS-Bundle-Hash": manifest["integrity_hash"],
        "X-AEGIS-Signature": manifest["signature_hex"],
        "X-AEGIS-Pub-Fingerprint": manifest["device_pub_fingerprint"],
    }
    records.add_event(enc_id, "handoff_packet_built", {
        "filename": manifest["filename"],
        "size_bytes": manifest["size_bytes"],
        "integrity_hash": manifest["integrity_hash"],
    })
    return Response(content=zip_bytes, media_type="application/zip", headers=headers)


@app.post("/api/aar")
async def api_aar(body: dict):
    """Generate an after-action review for a completed encounter.

    Returns the structured AAR as a single JSON object. Frontend renders
    the `summary` field through a typewriter effect at the established
    28 cps cadence — the typewriter pacing is purely a UI concern, the
    LLM call itself is non-streaming JSON.
    """
    enc_id = body.get("encounter_id", "")
    rec = records.get_encounter(enc_id)
    if not rec:
        raise HTTPException(404, "encounter not found")
    out = await inference.generate_aar(rec)
    try:
        records.add_event(enc_id, "aar_generated", {
            "documentation_quality": out.get("documentation_quality"),
            "summary_present": bool((out.get("summary") or "").strip()),
        })
    except Exception:
        pass
    return out


@app.post("/api/aar/stream")
async def api_aar_stream(body: dict):
    """V5 — true streaming AAR via Server-Sent Events.

    The frontend's existing typewriter consumes `event: token` messages
    at the established 28 cps visual cadence. The LLM may emit faster
    or slower; the consumer paces.

    Note: the AAR is a structured JSON object, not free-form prose.
    This endpoint streams the *raw model response text* (which the
    backend then parses to JSON post-stream and writes as an event).
    The typewriter renders this directly as the AAR's narrative
    `summary` paragraph during the handoff packet generation moment.
    """
    from sse_starlette.sse import EventSourceResponse  # type: ignore

    enc_id = body.get("encounter_id", "")
    rec = records.get_encounter(enc_id)
    if not rec:
        raise HTTPException(404, "encounter not found")

    chunks = await retrieval.retrieve(
        "protocol compliance review", rec.get("scenario_id"), k=4,
    )
    chunks_block = inference._format_chunks(chunks)
    record_json = json.dumps(rec, default=str, indent=2)[:8000]
    system, user = (
        await __import__("asyncio").get_event_loop().run_in_executor(
            None,
            lambda: __import__("backend.prompts", fromlist=["render_user_prompt"])
                    .render_user_prompt(
                        "aar",
                        encounter_record_json=record_json,
                        chunks_formatted=chunks_block,
                    ),
        )
    )

    async def event_gen():
        full = []
        try:
            async for token in inference.stream_llm(system, user):
                full.append(token)
                yield {"event": "token", "data": json.dumps({"token": token})}
        except inference.LLMError as exc:
            yield {"event": "error",
                   "data": json.dumps({"error": str(exc)})}
            return
        yield {"event": "done", "data": json.dumps({})}
        # Persist the full AAR text as an event so the handoff packet can
        # reference it later.
        try:
            records.add_event(enc_id, "aar_streamed", {
                "raw_text": "".join(full)[:4000],
            })
        except Exception:
            pass

    return EventSourceResponse(event_gen())
