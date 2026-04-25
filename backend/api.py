from __future__ import annotations

from fastapi import FastAPI, HTTPException

from backend.orchestrator import run_aegis_pipeline


app = FastAPI(title="AEGIS Backend", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "mode": "offline"}


@app.post("/aegis/run")
def run_pipeline(encounter: dict) -> dict:
    try:
        result = run_aegis_pipeline(encounter)
        return {
            "ok": True,
            "data": {
                "crisis_view": result.get("crisis_view", {}),
                "triage": result.get("triage", {}),
                "differential": result.get("differential", {}),
                "protocol": result.get("protocol", {}),
                "missed_signals": result.get("missed_signals", {}),
                "questions": result.get("questions", {}),
                "safety": result.get("safety", {}),
                "reasoning_trace": result.get("reasoning_trace", []),
                "audit": result.get("audit", {}),
                "handoff": result.get("handoff", {}),
                "integrations": result.get("integrations", {}),
            },
            "meta": {
                "offline_status": result.get("offline_status", {"mode": "OFFLINE ACTIVE", "cloud_calls": 0}),
                "encounter_id": result.get("encounter", {}).get("encounter_id"),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"pipeline_failed: {exc}") from exc
