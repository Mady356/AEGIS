"""
Pydantic schemas for everything that crosses the API boundary.

Strict types. No `Any` in production paths. No string IDs that could be
more usefully typed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# =====================================================================
# Scenarios
# =====================================================================

class VitalsBaseline(BaseModel):
    hr: int
    bp_systolic: int
    bp_diastolic: int
    spo2: int
    rr: int
    temp: Optional[float] = None


class ScenarioDef(BaseModel):
    id: str
    name: str
    domain: str
    case: str
    patient_label: str
    environment: str
    default_vitals: VitalsBaseline
    system_prompt: str
    retrieval_tags: list[str]
    primer_prompt: str
    canned_vox: str
    steps: list[str]


# =====================================================================
# Encounters & Events
# =====================================================================

EVENT_TYPES = Literal[
    "encounter_started",
    "scenario_switched",
    "vital_reading",
    "checklist_item_completed",
    "voice_input_started",
    "voice_input_finalized",
    "intake",
    "assessment",
    "guidance",
    "citation_viewed",
    "record_viewed",
    "system_panel_viewed",
    "encounter_ended",
    # V3-era event types preserved for backward compatibility
    "rppg_enabled", "rppg_disabled",
    "image_analyzed", "calculator_invoked",
    "interaction_flagged", "medication_administered",
    "triage", "encounter_created",
    "handoff_transmitted", "reference_view",
]


class EncounterCreate(BaseModel):
    scenario_id: str
    patient_label: Optional[str] = None


class EncounterSummary(BaseModel):
    id: str
    scenario_id: str
    scenario_name: str
    patient_label: str
    started_at: str
    ended_at: Optional[str]
    event_count: int
    integrity_status: Literal["verified", "unverified", "broken"]


class Event(BaseModel):
    id: int
    encounter_id: str
    event_type: str
    t_offset_ms: int
    payload: dict
    hash: str
    prev_hash: Optional[str]
    created_at: str


class EventCreate(BaseModel):
    event_type: str
    payload: dict = Field(default_factory=dict)
    t_offset_ms: int = 0


class IntegrityResult(BaseModel):
    valid: bool
    event_count: int
    first_break_event_id: Optional[int]
    verified_at: str
    chain_root: Optional[str] = None


# =====================================================================
# Retrieval
# =====================================================================

class RetrievalQuery(BaseModel):
    query: str
    scenario_id: Optional[str] = None
    top_k: int = 6


class Chunk(BaseModel):
    citation_id: str
    text: str
    source_doc: str
    page: Optional[int]
    section_heading: Optional[str]
    scenario_tags: list[str]
    score: Optional[float] = None


class RetrievalResult(BaseModel):
    chunks: list[Chunk]


# =====================================================================
# Reasoning (SSE)
# =====================================================================

class ReasonRequest(BaseModel):
    encounter_id: str
    transcript: str
    scenario_id: Optional[str] = None  # falls back to encounter's scenario


# =====================================================================
# System status
# =====================================================================

class SystemStatus(BaseModel):
    # Inference
    model_name: str
    embed_model: str
    backend: str
    inference_mode: Literal["mock", "live"]
    last_inference_latency_ms: Optional[int] = None

    # Speech
    stt_model: str
    stt_backend: str
    last_transcription_ms: Optional[int] = None

    # Corpus
    corpus_chunk_count: int
    embedding_dimensions: int
    source_document_count: int
    last_index_build: Optional[str]
    index_storage_mb: Optional[float]

    # Persistence
    record_store_engine: str
    storage_path_mb: Optional[float]
    encounter_count: int
    event_count: int

    # Telemetry
    ram_resident_mb: Optional[int]
    disk_free_mb: Optional[int]
    cpu_usage_percent: Optional[float]
    uptime_seconds: int

    # Network
    network_reachable: Optional[bool]
    last_state_change: Optional[str]
    probe_history: list[dict]

    # Build
    version: str
    build_hash: str
    built_at: str
    platform: str


# =====================================================================
# Network monitor
# =====================================================================

class HostResult(BaseModel):
    host: str
    ok: bool
    latency_ms: Optional[int]


class NetworkState(BaseModel):
    reachable: bool
    last_probe_at: str
    host_results: list[HostResult]


# =====================================================================
# Decision support (structured, non-chatbot)
# =====================================================================

class DecisionSupportRequest(BaseModel):
    encounter: dict = Field(default_factory=dict)
    scenario_id: Optional[str] = None
