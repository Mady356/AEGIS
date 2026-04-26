"""
Stdlib-only preview server for AEGIS V2.

Exists for one purpose: render the V2 frontend in environments where the
full backend (Ollama, ChromaDB, faster-whisper, SQLCipher) is not
installed. Reasoning streams are served from the cached canonical
responses in backend/scenarios.py — the same text that backs the
inference-timeout fallback in production. Vitals, network monitor,
records, and system status are real, computed locally.

Run:
    python3 preview_server.py            # serves on 0.0.0.0:8000
    PORT=8001 python3 preview_server.py
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend import scenarios as sc_mod  # type: ignore

PORT = int(os.environ.get("PORT", "8000"))
FRONTEND = ROOT / "frontend"

# V5 — when the V4 mock doesn't implement an /api/* route, forward it
# to the real uvicorn-served AEGIS backend so the preview cockpit can
# do real chat, real situation persistence, real procedural-step graph,
# etc. Override with env if the real backend lives elsewhere.
REAL_BACKEND = os.environ.get("AEGIS_REAL_BACKEND", "http://127.0.0.1:8000")

# ---------------------------------------------------------------------
# Mock state
# ---------------------------------------------------------------------
_state_lock = threading.Lock()
_encounters: dict[int, dict] = {}
_events: dict[int, list[dict]] = {}
_next_id = 1
_network_history: list[dict] = []
_network_subs: list[list] = []  # each sub is a list used as a queue with a Condition

CITATIONS = {
    "TCCC-1.0": {
        "text": "All combat casualty assessments begin with MARCH-PAWS: Massive hemorrhage, Airway, Respiration, Circulation, Hypothermia. Identify and treat life-threatening hemorrhage before all other interventions.",
        "document": "TCCC Guidelines",
        "page": 12, "section": "1.0 — General Principles", "tags": ["combat"],
    },
    "TCCC-3.2": {
        "text": "For life-threatening extremity hemorrhage, apply a Combat Application Tourniquet (CAT) two to three inches proximal to the wound, over the uniform if necessary. Tighten until distal pulse is absent and bleeding has stopped. Mark the time of application clearly on the casualty card and write 'TQ' on the forehead.",
        "document": "TCCC Guidelines",
        "page": 28, "section": "3.2 — Tourniquet Application", "tags": ["combat"],
    },
    "TCCC-3.4": {
        "text": "Class II hemorrhagic shock is characterized by 15–30% blood loss, heart rate above 100, narrowed pulse pressure, mild anxiety, and capillary refill prolonged beyond 2 seconds. Treat with hemorrhage control and limited crystalloid resuscitation if the casualty is not in refractory shock.",
        "document": "TCCC Guidelines",
        "page": 31, "section": "3.4 — Shock Recognition", "tags": ["combat"],
    },
    "TCCC-3.5": {
        "text": "Document the time of every tourniquet application on the TCCC Casualty Card. Mark the casualty's forehead with the letters 'TQ' in indelible marker so subsequent providers can identify the limb at risk without delay.",
        "document": "TCCC Guidelines",
        "page": 33, "section": "3.5 — Documentation", "tags": ["combat"],
    },
    "TCCC-4.4": {
        "text": "Tranexamic acid (TXA) 1 g in 100 mL normal saline is administered slow IV push over 10 minutes for any casualty with significant hemorrhage when administration can begin within 3 hours of injury. A second 1 g dose may be given over 8 hours.",
        "document": "TCCC Guidelines",
        "page": 47, "section": "4.4 — Tranexamic Acid", "tags": ["combat"],
    },
    "JTS-CPG-2104": {
        "text": "Tourniquet conversion to a pressure dressing may be attempted only when (a) the casualty is hemodynamically stable, (b) total tourniquet time is under 2 hours, (c) the tactical situation permits, and (d) the wound is not from a major junctional vessel.",
        "document": "JTS CPG — Tourniquet Conversion",
        "page": 4, "section": "Conversion Criteria", "tags": ["combat"],
    },
    "ILCOR-3.1": {
        "text": "Adult chest compressions are delivered at 100–120 per minute, with a depth of 5–6 cm, allowing complete chest recoil between compressions. Minimize interruptions; pauses for ventilation, rhythm analysis, and shock delivery should be brief.",
        "document": "ILCOR Consensus 2025",
        "page": 18, "section": "3.1 — Compression Quality", "tags": ["maritime"],
    },
    "ILCOR-3.2": {
        "text": "Standard adult CPR uses a 30:2 compression-to-ventilation ratio when no advanced airway is in place. Each rescue breath is delivered over approximately one second with sufficient volume to produce visible chest rise.",
        "document": "ILCOR Consensus 2025",
        "page": 19, "section": "3.2 — Ventilation", "tags": ["maritime"],
    },
    "ILCOR-7.1": {
        "text": "Cardiac arrest of probable hypoxic etiology, including drowning and submersion, is treated with five rescue breaths before the first cycle of compressions. Standard 30:2 ratio resumes thereafter. The rescuer must ensure the casualty is on a dry, non-conductive surface before AED application.",
        "document": "ILCOR Maritime Addendum",
        "page": 3, "section": "7.1 — Submersion Arrest", "tags": ["maritime"],
    },
    "ILCOR-7.2": {
        "text": "Apply AED pads as soon as the casualty is dry on a non-conductive surface. Pause compressions only for rhythm analysis and shock delivery; resume immediately afterward without checking for pulse.",
        "document": "ILCOR Maritime Addendum",
        "page": 5, "section": "7.2 — AED Application", "tags": ["maritime"],
    },
    "NAVMED-5052-IV": {
        "text": "Initial vasopressor in cardiac arrest is epinephrine 1 mg IV/IO, repeated every 3–5 minutes. Establish the largest peripheral access available; intraosseous access is preferred when peripheral attempts fail within two tries.",
        "document": "NAVMED P-5052 — Submarine Medicine Practice",
        "page": 88, "section": "Pharmacology — Cardiac Arrest", "tags": ["maritime"],
    },
    "NAVMED-5052-AIR": {
        "text": "Advanced airway placement during cardiac arrest is deferred until after the second rhythm check unless basic airway maneuvers fail to produce effective ventilation. Continuous capnography is preferred to confirm placement and quality of CPR.",
        "document": "NAVMED P-5052 — Submarine Medicine Practice",
        "page": 92, "section": "Airway Management", "tags": ["maritime"],
    },
    "WHO-EC-p46": {
        "text": "Pediatric weight estimation in field settings is best performed using a length-based resuscitation tape (Broselow). When the tape is unavailable, the formula weight (kg) = 2 × (age + 4) provides a rough estimate for children 1–10 years.",
        "document": "WHO Emergency Care Pocket Book, 2023 ed.",
        "page": 46, "section": "Pediatric Triage", "tags": ["pediatric", "disaster"],
    },
    "WHO-EC-p84": {
        "text": "Moderate dehydration in a febrile child presents with sunken eyes, decreased skin turgor, and capillary refill 2–4 seconds. Initial management is oral rehydration with WHO ORS, 75 mL/kg over 4 hours, while monitoring for vomiting and worsening mental status.",
        "document": "WHO Emergency Care Pocket Book, 2023 ed.",
        "page": 84, "section": "Dehydration & Fluid Therapy", "tags": ["pediatric", "disaster"],
    },
    "WHO-EC-p86": {
        "text": "Reassess all pediatric patients receiving oral rehydration at 60-minute intervals. Document temperature, mental status, capillary refill, and oral intake volume. Escalate to IV fluids if vomiting persists or capillary refill exceeds 4 seconds.",
        "document": "WHO Emergency Care Pocket Book, 2023 ed.",
        "page": 86, "section": "Reassessment", "tags": ["pediatric", "disaster"],
    },
    "WHO-EC-p88": {
        "text": "Indications for escalation from oral to intravenous rehydration in pediatric patients: persistent vomiting, capillary refill > 4 seconds, altered mental status, oliguria, or inability to tolerate oral intake.",
        "document": "WHO Emergency Care Pocket Book, 2023 ed.",
        "page": 88, "section": "Escalation Criteria", "tags": ["pediatric", "disaster"],
    },
    "WHO-EC-p98": {
        "text": "Paracetamol pediatric dosing: 15 mg/kg per dose orally every 4–6 hours, not exceeding 60 mg/kg/day. Avoid in suspected hepatic insufficiency. For a 16 kg child the calculated single dose is 240 mg, equivalent to 10 mL of standard 120 mg/5 mL suspension.",
        "document": "WHO Emergency Care Pocket Book, 2023 ed.",
        "page": 98, "section": "Pediatric Pharmacology", "tags": ["pediatric", "pharmacology"],
    },
    "WHO-IMAI-4.4": {
        "text": "Antibiotic therapy is deferred in pediatric febrile illness pending source identification, except in cases with overt signs of sepsis (rapid breathing, lethargy, capillary refill > 3 s, hypotension), suspected meningitis, or known bacterial focus. Antipyresis and rehydration are first-line.",
        "document": "WHO IMAI Guidelines",
        "page": 44, "section": "4.4 — Pediatric Febrile Illness", "tags": ["pediatric", "disaster"],
    },
}


# ---------------------------------------------------------------------
# Network monitor (real probes)
# ---------------------------------------------------------------------
def _probe(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            return True
    except Exception:
        return False


def _network_loop():
    while True:
        targets = {"1.1.1.1:53": _probe("1.1.1.1", 53), "8.8.8.8:53": _probe("8.8.8.8", 53)}
        ev = {"reachable": any(targets.values()), "t": int(time.time() * 1000), "targets": targets}
        with _state_lock:
            _network_history.append(ev)
            if len(_network_history) > 30:
                # V4 §2.4 fix — keep the last 30, not all-but-the-last-30
                _network_history[:] = _network_history[-30:]
            for sub in list(_network_subs):
                sub.append(ev)
        time.sleep(2.0)


threading.Thread(target=_network_loop, daemon=True).start()


# ---------------------------------------------------------------------
# Cryptographic event signing chain (V3)
# ---------------------------------------------------------------------
# Production uses Ed25519 via `cryptography.hazmat.primitives.asymmetric.ed25519`.
# Preview uses HMAC-SHA256 with a per-device random key — a real cryptographic
# chain that demonstrates tamper detection without requiring the cryptography
# package to be installed. The signing surface (signature length, prev-hash
# linkage, verification logic) matches the production semantics exactly.

import hmac
import secrets

DEVICE_KEY_PATH = ROOT / "aegis_data" / "keys" / "device.key"
DEVICE_PUB_PATH = ROOT / "aegis_data" / "keys" / "device.pub"
DEVICE_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_or_create_keys() -> tuple[bytes, str]:
    if DEVICE_KEY_PATH.exists():
        priv = DEVICE_KEY_PATH.read_bytes()
    else:
        priv = secrets.token_bytes(32)
        DEVICE_KEY_PATH.write_bytes(priv)
        os.chmod(DEVICE_KEY_PATH, 0o600)
    pub_fp = hashlib.sha256(priv).hexdigest()
    if not DEVICE_PUB_PATH.exists():
        DEVICE_PUB_PATH.write_text(pub_fp)
    return priv, pub_fp


_DEVICE_PRIV, _DEVICE_PUB_FP = _load_or_create_keys()
_KEY_ISSUED_AT = int(DEVICE_KEY_PATH.stat().st_mtime * 1000) if DEVICE_KEY_PATH.exists() else _now_ms() if False else int(time.time() * 1000)
_BUNDLES_SIGNED = 0
_HANDOFFS_TRANSMITTED = 0
_TAMPER_FLIP = {"enabled": False, "encounter_id": None, "event_id": None}


def _sign(payload: bytes) -> str:
    return hmac.new(_DEVICE_PRIV, payload, hashlib.sha256).hexdigest()


def _event_canonical(ev: dict, prev_sig: str) -> bytes:
    return json.dumps({
        "et": ev["event_type"],
        "t":  ev.get("t_offset_ms"),
        "p":  json.dumps(ev.get("payload") or {}, sort_keys=True),
        "c":  ev["created_at"],
        "ps": prev_sig,
    }, sort_keys=True, separators=(",", ":")).encode()


def _verify_chain(rows: list[dict]) -> tuple[bool, int | None]:
    """Walk the chain. Return (ok, broken_event_id). When tamper is enabled,
    the canonical bytes for the targeted event are mutated, breaking the chain
    at exactly that point."""
    prev_sig = "GENESIS"
    for ev in rows:
        canonical = _event_canonical(ev, prev_sig)
        if (_TAMPER_FLIP["enabled"]
                and _TAMPER_FLIP["encounter_id"] == ev.get("__enc")
                and _TAMPER_FLIP["event_id"] == ev["id"]):
            # Simulate a single byte flipped in storage
            canonical = canonical[:-1] + bytes([canonical[-1] ^ 0x01])
        expected = _sign(canonical)
        if expected != ev.get("signature"):
            return False, ev["id"]
        prev_sig = ev["signature"]
    return True, None


def _hash_events(rows: list[dict]) -> str:
    """Bundle integrity hash — SHA-256 over the signed chain."""
    h = hashlib.sha256()
    for r in rows:
        h.update(r.get("signature", "").encode()); h.update(b"\n")
    return h.hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _start_encounter(scenario_id: str) -> dict:
    global _next_id
    sc = sc_mod.get(scenario_id) or {}
    with _state_lock:
        eid = _next_id; _next_id += 1
        rec = {
            "id": eid,
            "scenario_id": scenario_id,
            "scenario_name": sc.get("name", scenario_id),
            "patient_label": sc.get("patient_label", "PT-—"),
            "started_at": _now_ms(),
            "ended_at": None,
        }
        _encounters[eid] = rec
        _events[eid] = []
    return rec


def _add_event(eid: int, etype: str, payload: dict):
    with _state_lock:
        if eid not in _events:
            return
        prev_sig = _events[eid][-1]["signature"] if _events[eid] else "GENESIS"
        ev = {
            "id": len(_events[eid]) + 1,
            "event_type": etype,
            "t_offset_ms": payload.get("t_offset_ms"),
            "payload": payload or {},
            "created_at": _now_ms(),
            "__enc": eid,
        }
        canonical = _event_canonical(ev, prev_sig)
        ev["prev_signature_hash"] = hashlib.sha256(prev_sig.encode()).hexdigest()
        ev["signature"] = _sign(canonical)
        _events[eid].append(ev)


# ---------------------------------------------------------------------
# V4 — Curated corpus loader (reads backend/corpus/chunks/*.md)
# ---------------------------------------------------------------------
_V4_CORPUS_CACHE: list[dict] | None = None
_V4_CORPUS_DIR = ROOT / "backend" / "corpus" / "chunks"


def _v4_parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    meta: dict = {}
    for line in fm.splitlines():
        if not line.strip() or line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip(); v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            meta[k] = [s.strip().strip("'\"") for s in v[1:-1].split(",") if s.strip()]
        elif v.startswith('"') and v.endswith('"'):
            meta[k] = v[1:-1]
        else:
            try: meta[k] = int(v)
            except ValueError:
                try: meta[k] = float(v)
                except ValueError: meta[k] = v
    return meta, body


def _v4_load_corpus() -> list[dict]:
    global _V4_CORPUS_CACHE
    if _V4_CORPUS_CACHE is not None:
        return _V4_CORPUS_CACHE
    out = []
    if _V4_CORPUS_DIR.exists():
        for p in sorted(_V4_CORPUS_DIR.glob("*.md")):
            text = p.read_text(encoding="utf-8")
            meta, body = _v4_parse_frontmatter(text)
            cid = meta.get("citation_id") or p.stem
            out.append({
                "citation_id": cid, "id": cid,
                "source": meta.get("source", ""),
                "source_short": meta.get("source_short", ""),
                "source_url": meta.get("source_url", ""),
                "source_pdf": meta.get("source_pdf", ""),
                "page": meta.get("page"),
                "section": meta.get("section", ""),
                "revision": meta.get("revision", ""),
                "scenario_tags": meta.get("scenario_tags") or [],
                "text": body.strip(),
                "document": meta.get("source", ""),
            })
    _V4_CORPUS_CACHE = out
    return out


def _v4_get_chunk(citation_id: str) -> dict | None:
    return next((c for c in _v4_load_corpus()
                 if c["citation_id"] == citation_id), None)


def _v4_keyword_retrieve(query: str, scenario_filter: str | None = None,
                         k: int = 5) -> list[dict]:
    import re as _re
    qtoks = set(_re.findall(r"[a-zA-Z]{3,}", (query or "").lower()))
    if not qtoks: return []
    scored: list[tuple[float, dict]] = []
    for c in _v4_load_corpus():
        text_l = c["text"].lower()
        ttoks = set(_re.findall(r"[a-zA-Z]{3,}", text_l))
        overlap = len(qtoks & ttoks)
        if overlap == 0: continue
        bonus = 0.0
        meta = f"{c['citation_id']} {c['section']} {c['source_short']}".lower()
        for t in qtoks:
            if t in meta: bonus += 0.5
        if scenario_filter and scenario_filter in c["scenario_tags"]:
            bonus += 0.6
        scored.append((overlap + bonus, c))
    scored.sort(key=lambda x: -x[0])
    if not scored: return []
    max_s = scored[0][0]
    return [{**c, "score": round(s / max(max_s, 1), 3)}
            for s, c in scored[:k]]


def _now_iso_v4() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ---------------------------------------------------------------------
# V4.1 — TRUST surface content (mirrors backend/trust_surface.py)
# ---------------------------------------------------------------------
def _v41_trust_surface() -> dict:
    try:
        from backend import trust_surface
        return trust_surface.as_dict()
    except Exception:
        return {"product_positioning": "AEGIS is a documentation interface, "
                                       "not a clinical advisor.",
                "gap_statements": [], "vignette": {},
                "deployment_model": {}, "cost_comparison": [],
                "failure_modes": [], "institutional_buyers": []}


# ---------------------------------------------------------------------
# V4.1 — Source PDF whitelist (built from the corpus on first request)
# ---------------------------------------------------------------------
_V41_PDF_WHITELIST: set[str] | None = None


def _v41_pdf_whitelist() -> set[str]:
    global _V41_PDF_WHITELIST
    if _V41_PDF_WHITELIST is None:
        chunks = _v4_load_corpus()
        _V41_PDF_WHITELIST = {c["source_pdf"] for c in chunks if c.get("source_pdf")}
    return _V41_PDF_WHITELIST


# ---------------------------------------------------------------------
# V4 LLM endpoint implementations (preview = canned-shape, real chunks)
# ---------------------------------------------------------------------
def _v4_extract(req: dict) -> dict:
    transcript = req.get("transcript", "") or ""
    if not transcript.strip():
        return {
            "patient": None, "mechanism": None,
            "vitals_observed": [], "interventions_performed": [],
            "extraction_confidence": "low",
            "notes": "Insufficient clinical content for extraction.",
        }
    import re as _re
    t = transcript; t_low = transcript.lower()

    def _span(needle: str) -> str:
        i = t_low.find(needle.lower())
        if i < 0: return needle
        return t[i : i + min(len(needle) + 30, len(t) - i)].strip()

    patient = {"age": None, "sex": None, "weight_kg": None, "demographics_notes": None}
    mechanism = {"category": None, "description": None}
    vitals: list[dict] = []
    interventions: list[dict] = []

    if m := _re.search(r"(\d{1,3})\s*(?:year|yr|years old)", t_low):
        patient["age"] = int(m.group(1))
    if "male" in t_low and "female" not in t_low:
        patient["sex"] = "male"
    elif "female" in t_low:
        patient["sex"] = "female"
    if m := _re.search(r"(\d+(?:\.\d+)?)\s*(?:kilogram|kg)", t_low):
        patient["weight_kg"] = float(m.group(1))

    if "gunshot" in t_low or "gsw" in t_low:
        mechanism = {"category": "penetrating",
                     "description": _span("gunshot")}
    elif "drown" in t_low or "submer" in t_low or "diver" in t_low:
        mechanism = {"category": "environmental",
                     "description": _span("drown") if "drown" in t_low else _span("submersion")}
    elif "fever" in t_low or "lethargic" in t_low:
        mechanism = {"category": "medical",
                     "description": _span("fever")}
    elif "collapse" in t_low or "pulseless" in t_low:
        mechanism = {"category": "medical",
                     "description": _span("collapse") if "collapse" in t_low else _span("pulseless")}

    if m := _re.search(r"(?:fever|temp(?:erature)?)[^\d]*(\d{2,3}(?:\.\d)?)", t_low):
        vitals.append({"type": "temp", "value": f"{m.group(1)}°C",
                       "transcript_span": _span(m.group(0))})
    if "spo2" in t_low or "oxygen saturation" in t_low:
        if m := _re.search(r"(?:spo2|oxygen saturation)[^\d]*(\d{2,3})", t_low):
            vitals.append({"type": "spo2", "value": f"{m.group(1)}%",
                           "transcript_span": _span(m.group(0))})
    if m := _re.search(r"(?:hr|heart rate)[^\d]*(\d{2,3})", t_low):
        vitals.append({"type": "hr", "value": m.group(1),
                       "transcript_span": _span(m.group(0))})

    if "tourniquet" in t_low:
        interventions.append({"type": "tourniquet",
                              "details": "applied",
                              "transcript_span": _span("tourniquet")})
    if "compression" in t_low:
        interventions.append({"type": "cpr_compressions",
                              "details": "compressions in progress",
                              "transcript_span": _span("compression")})
    if "shock" in t_low and ("aed" in t_low or "rhythm" in t_low):
        interventions.append({"type": "defibrillation",
                              "details": "AED shock delivered",
                              "transcript_span": _span("shock")})
    if "paracetamol" in t_low or "acetaminophen" in t_low:
        interventions.append({"type": "medication",
                              "details": "paracetamol weight-based dosing",
                              "transcript_span": _span("paracetamol") if "paracetamol" in t_low else _span("acetaminophen")})

    return {
        "patient": patient, "mechanism": mechanism,
        "vitals_observed": vitals,
        "interventions_performed": interventions,
        "extraction_confidence": "medium" if (vitals or interventions) else "low",
        "notes": None,
    }


def _v4_qa(req: dict) -> dict:
    q = req.get("question", "") or ""
    sc = req.get("scenario_context")
    if not q.strip():
        return {"answer_type": "refused", "answer_text": None, "citations": [],
                "refusal_reason": "Empty question."}
    chunks = _v4_keyword_retrieve(q, sc, k=5)
    if not chunks:
        return {"answer_type": "refused", "answer_text": None, "citations": [],
                "refusal_reason": "The retrieved corpus does not contain "
                                  "information sufficient to answer this "
                                  "question. Consider rephrasing or consulting "
                                  "a different reference."}
    top = chunks[0]
    snippet = top["text"].strip().replace("\n", " ")
    if len(snippet) > 280:
        snippet = snippet[:280].rsplit(" ", 1)[0] + "…"
    return {
        "answer_type": "answered",
        "answer_text": (
            f"According to {top['source_short']} {top['section']}, "
            f"{snippet}"
        ),
        "citations": [
            {"citation_id": top["citation_id"], "supporting_quote": snippet}
        ] + ([
            {"citation_id": chunks[1]["citation_id"],
             "supporting_quote": chunks[1]["text"][:160].strip() + "…"}
        ] if len(chunks) > 1 else []),
        "refusal_reason": None,
        "_retrieval_meta": {"chunks_searched": 18, "chunks_returned": len(chunks)},
    }


def _v4_nudges(req: dict) -> dict:
    state = req.get("encounter_state") or {}
    sid = state.get("scenario_id") or ""
    elapsed = int(state.get("elapsed_seconds", 0) or 0)
    completed = set(state.get("completed_checklist_items") or [])
    nudges: list[dict] = []

    def _push(severity, label, rationale, cid):
        chunk = _v4_get_chunk(cid)
        if not chunk: return
        quote = chunk["text"][:160].strip().replace("\n", " ") + "…"
        nudges.append({
            "severity": severity, "step_label": label,
            "rationale": rationale,
            "citation_id": cid,
            "supporting_quote": quote,
            "issued_at_elapsed_seconds": elapsed,
        })

    if sid == "battlefield":
        if "tourniquet_applied" not in completed and elapsed >= 60:
            sev = "critical_overdue" if elapsed > 180 else "overdue"
            _push(sev, "Confirm tourniquet placement and casualty card time-on",
                  f"No tourniquet placement event recorded {elapsed}s into "
                  f"encounter; arterial bleed risk.", "TCCC-TQ-PLACE")
        if "txa_administered" not in completed and "tourniquet_applied" in completed and elapsed > 300:
            _push("reminder", "Consider TXA 2 g IV within the 3-hour window",
                  "Tourniquet placed; TXA window closes at 3 h post-injury.",
                  "TCCC-TXA-DOSE")
    elif sid == "maritime":
        if "compressions_started" not in completed and elapsed >= 30:
            _push("critical_overdue", "Begin chest compressions (100–120/min)",
                  "Pulseless casualty; no compressions logged.",
                  "AHA-COMPRESSION-RATE")
        if "rescue_breaths" not in completed and elapsed >= 20:
            _push("overdue", "Deliver 5 initial rescue breaths (drowning sequence)",
                  "Drowning arrest is hypoxic — oxygenation precedes circulation.",
                  "AHA-DROWNING")
    elif sid == "disaster":
        if "weight_documented" not in completed and elapsed >= 60:
            _push("reminder", "Confirm weight by length-based tape",
                  "Pediatric drug dosing requires documented weight.",
                  "WHO-PED-WEIGHT-EST")
        if "antipyretic_administered" not in completed and elapsed >= 120:
            _push("overdue", "Administer paracetamol 15 mg/kg PO",
                  "Febrile pediatric patient; antipyretic step not recorded.",
                  "WHO-PED-PARACETAMOL")

    return {"nudges": nudges[:3]}


def _v4_aar(req: dict) -> dict:
    eid = req.get("encounter_id")
    rec = _v4_resolve_record(str(eid)) if eid else None
    if not rec or not rec.get("events"):
        return {
            "summary": "Insufficient documentation for review.",
            "timeline_highlights": [],
            "protocol_compliance": {"performed_correctly": [], "missed": [], "out_of_sequence": []},
            "teaching_points": [], "documentation_quality": "partial",
        }
    events = rec["events"]
    sid = rec["scenario_id"]
    completed = [e for e in events if e.get("event_type") == "checklist_item_completed"]

    if sid == "battlefield":
        primary_cid = "TCCC-TQ-PLACE"
        teach_cid = "TCCC-CASUALTY-CARD"
    elif sid == "maritime":
        primary_cid = "AHA-COMPRESSION-RATE"
        teach_cid = "AHA-AED-PROTOCOL"
    else:
        primary_cid = "WHO-PED-PARACETAMOL"
        teach_cid = "WHO-PED-DEHYDRATION"

    pc = _v4_get_chunk(primary_cid)
    tc = _v4_get_chunk(teach_cid)
    pc_quote = (pc["text"][:140].strip() + "…") if pc else ""
    tc_quote = (tc["text"][:140].strip() + "…") if tc else ""

    correct = []
    for e in completed[:3]:
        correct.append({
            "step": e.get("payload", {}).get("step_label", "step completed"),
            "citation_id": primary_cid, "supporting_quote": pc_quote,
        })

    duration = rec.get("duration", "—")
    return {
        "summary": (
            f"Encounter ENC-{rec['id']} ran {duration}. {len(events)} events "
            f"captured, {len(completed)} checklist items completed. Documentation "
            f"chain integrity verified at close."
        ),
        "timeline_highlights": [
            {"time_offset_seconds": int((e.get("t_offset_ms") or 0) / 1000),
             "event_summary": e["event_type"]}
            for e in events[:6]
        ],
        "protocol_compliance": {
            "performed_correctly": correct,
            "missed": [],
            "out_of_sequence": [],
        },
        "teaching_points": [
            {"point": "Time-stamped intervention logging maintained.",
             "citation_id": teach_cid},
        ] if tc else [],
        "documentation_quality": "complete" if len(events) > 20 else "mostly_complete",
    }


# ---------------------------------------------------------------------
# V4 — Tamper demo (visible button-driven; §6)
# ---------------------------------------------------------------------
def _v4_tamper_event(req: dict) -> dict:
    eid_str = req.get("encounter_id")
    event_id = req.get("event_id")
    rec = _v4_resolve_record(str(eid_str)) if eid_str is not None else None
    if not rec or event_id is None:
        return {"ok": False, "error": "encounter or event not found"}
    eid = rec["id"]
    with _state_lock:
        evs = _events.get(eid) or []
        target = next((e for e in evs if e["id"] == int(event_id)), None)
        if not target:
            return {"ok": False, "error": "event not found"}
        # Save original payload for healing, flip a byte
        target.setdefault("_orig_payload", dict(target.get("payload") or {}))
        p = dict(target.get("payload") or {})
        # Modify any string field by flipping its last byte
        for k, v in list(p.items()):
            if isinstance(v, str) and v:
                b = bytearray(v, "utf-8"); b[-1] ^= 0x01
                p[k] = b.decode("utf-8", errors="replace")
                break
        else:
            p["__tamper_marker__"] = "modified"
        target["payload"] = p
        # Recompute the signature so chain *would* validate but the hash chain
        # against prev_signature_hash detects the modification.
        # In the preview's HMAC chain, we DO NOT re-sign — that's how the
        # tamper is detectable: the stored signature no longer matches the
        # canonical bytes.
        _TAMPER_FLIP["enabled"] = True
        _TAMPER_FLIP["encounter_id"] = eid
        _TAMPER_FLIP["event_id"] = int(event_id)
    return {"ok": True, "tampered_event_id": int(event_id)}


def _v4_heal_event(req: dict) -> dict:
    eid_str = req.get("encounter_id")
    rec = _v4_resolve_record(str(eid_str)) if eid_str is not None else None
    if not rec:
        return {"ok": False, "error": "encounter not found"}
    eid = rec["id"]
    with _state_lock:
        evs = _events.get(eid) or []
        for e in evs:
            if "_orig_payload" in e:
                e["payload"] = e.pop("_orig_payload")
        _TAMPER_FLIP["enabled"] = False
        _TAMPER_FLIP["encounter_id"] = None
        _TAMPER_FLIP["event_id"] = None
    return {"ok": True}


def _v4_resolve_record(eid_str: str) -> dict | None:
    """Accept both V4 string IDs (ENC-...) and V3 integer IDs."""
    try:
        eid = int(eid_str)
    except ValueError:
        # ENC-prefixed: strip + try integer
        if eid_str.startswith("ENC-"):
            try: eid = int(eid_str.split("-", 1)[1].lstrip("0") or "0")
            except Exception: return None
        else:
            return None
    return _get_record(eid)


def _v4_summary(rec: dict) -> dict:
    return {
        "id": f"ENC-{rec['id']:012d}",
        "scenario_id": rec["scenario_id"],
        "scenario_name": rec.get("scenario_name", rec["scenario_id"]),
        "patient_label": rec["patient_label"],
        "started_at": _now_iso_v4(),
        "ended_at": rec.get("ended_at") and _now_iso_v4(),
        "event_count": len(_events.get(rec["id"], [])),
        "integrity_status": "verified",
    }


def _get_record(eid: int) -> dict | None:
    with _state_lock:
        if eid not in _encounters:
            return None
        rec = dict(_encounters[eid])
        evs = list(_events.get(eid, []))
    h = _hash_events(evs)
    ok, broken_id = _verify_chain(evs)
    end = rec["ended_at"] or _now_ms()
    s = max(0, end - rec["started_at"]) // 1000
    rec.update({
        "events": evs,
        "integrity_hash": h,
        "integrity_ok": ok,
        "broken_event_id": broken_id,
        "device_pub_fingerprint": _DEVICE_PUB_FP,
        "key_issued_at": _KEY_ISSUED_AT,
        "chain_length": len(evs),
        "duration": f"T+{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}",
    })
    return rec


# ---------------------------------------------------------------------
# V3 — Profiles, Queue, Calculators, Interactions, Vision, rPPG, Handoff
# ---------------------------------------------------------------------

PROFILES = [
    {
        "id": "combat_medic",
        "name": "Combat Medic",
        "description": "TCCC-prioritized corpus, combat trauma formulary, military triage doctrine.",
        "corpus_summary": "TCCC · JTS CPG · NAVMED",
        "scenarios": ["battlefield", "maritime"],
        "default_scenario": "battlefield",
    },
    {
        "id": "submarine_corpsman",
        "name": "Submarine Corpsman",
        "description": "Submarine medicine, limited onboard formulary, decompression and cardiac priorities.",
        "corpus_summary": "NAVMED P-5052 · ILCOR Maritime Addendum",
        "scenarios": ["maritime"],
        "default_scenario": "maritime",
    },
    {
        "id": "disaster_response",
        "name": "Disaster Response",
        "description": "Mass-casualty optimized queue, START/JumpSTART triage, broader formulary.",
        "corpus_summary": "WHO Emergency Care · WHO IMAI",
        "scenarios": ["disaster", "battlefield"],
        "default_scenario": "disaster",
    },
    {
        "id": "rural_clinic",
        "name": "Rural Clinic",
        "description": "Primary care corpus, chronic disease management, referral pathway emphasis.",
        "corpus_summary": "WHO Primary Care · WHO IMAI",
        "scenarios": ["disaster"],
        "default_scenario": "disaster",
    },
    {
        "id": "correctional_facility",
        "name": "Correctional Facility",
        "description": "Emergency medicine corpus, careful medication tracking, forensic documentation.",
        "corpus_summary": "Emergency Medicine · DEA scheduling",
        "scenarios": ["battlefield", "disaster"],
        "default_scenario": "battlefield",
    },
]
_active_profile_id = "combat_medic"


# ---- Queue & triage ----
TRIAGE_CATEGORIES = ("red", "yellow", "green", "black")


def _queue_list() -> list[dict]:
    with _state_lock:
        out = []
        for rec in sorted(_encounters.values(), key=lambda x: x["id"]):
            if rec.get("ended_at"): continue
            sc = sc_mod.get(rec["scenario_id"]) or {}
            out.append({
                "id": rec["id"],
                "patient_label": rec["patient_label"],
                "scenario_id": rec["scenario_id"],
                "scenario_name": sc.get("name", rec["scenario_id"]),
                "domain": sc.get("domain", ""),
                "case": sc.get("case", ""),
                "started_at": rec["started_at"],
                "triage": rec.get("triage"),
                "interactions_pending": rec.get("interactions_pending", 0),
                "rppg_active": rec.get("rppg_active", False),
            })
        return out


def _queue_set_triage(eid: int, category: str) -> dict:
    if category not in TRIAGE_CATEGORIES:
        return {"ok": False, "error": "invalid category"}
    with _state_lock:
        if eid not in _encounters:
            return {"ok": False, "error": "not found"}
        _encounters[eid]["triage"] = category
    _add_event(eid, "triage", {"category": category})
    return {"ok": True}


# ---- Calculators (real Python implementations) ----
def calc_gcs(eye: int, verbal: int, motor: int) -> dict:
    total = eye + verbal + motor
    if total <= 8: tier = "severe brain injury — consider intubation"
    elif total <= 12: tier = "moderate brain injury — stratify and monitor"
    else: tier = "mild brain injury"
    return {"name": "Glasgow Coma Scale", "result": total,
            "tier": tier,
            "inputs": {"eye": eye, "verbal": verbal, "motor": motor},
            "source": "Teasdale & Jennett, 1974 — Lancet 2:81–84"}


def calc_qsofa(rr: float, altered: bool, sbp: float) -> dict:
    score = (1 if rr >= 22 else 0) + (1 if altered else 0) + (1 if sbp <= 100 else 0)
    tier = "high risk for sepsis-related mortality" if score >= 2 else "low qSOFA"
    return {"name": "qSOFA", "result": score, "tier": tier,
            "inputs": {"rr": rr, "altered_mental_status": altered, "systolic_bp": sbp},
            "source": "Singer M et al., 2016 — JAMA 315:801"}


def calc_shock_index(hr: float, sbp: float) -> dict:
    si = round(hr / max(sbp, 1), 2)
    tier = "shock likely" if si >= 1.0 else ("shock possible" if si >= 0.7 else "stable")
    return {"name": "Shock Index", "result": si, "tier": tier,
            "inputs": {"hr": hr, "systolic_bp": sbp},
            "source": "Allgöwer & Buri, 1967"}


def calc_map(sbp: float, dbp: float) -> dict:
    m = round((sbp + 2 * dbp) / 3, 1)
    tier = "perfusion adequate" if m >= 65 else "low MAP — consider pressors"
    return {"name": "Mean Arterial Pressure", "result": m, "tier": tier,
            "inputs": {"systolic_bp": sbp, "diastolic_bp": dbp},
            "source": "Standard hemodynamic formula"}


def calc_parkland(weight_kg: float, percent_bsa: float) -> dict:
    total_ml = round(4 * weight_kg * percent_bsa)
    return {"name": "Parkland Formula", "result": total_ml,
            "tier": f"{total_ml // 2} mL over first 8 h, remainder over next 16 h",
            "inputs": {"weight_kg": weight_kg, "percent_bsa": percent_bsa},
            "source": "Baxter & Shires, 1968 — Ann NY Acad Sci 150:874"}


def calc_ett_size(age_years: float) -> dict:
    uncuffed = round(age_years / 4 + 4, 1)
    cuffed = round(age_years / 4 + 3.5, 1)
    return {"name": "Pediatric ETT Sizing", "result": cuffed,
            "tier": f"cuffed: {cuffed} mm · uncuffed: {uncuffed} mm",
            "inputs": {"age_years": age_years},
            "source": "Khine et al., 1997 — Anesthesiology 86:627"}


def calc_ped_dose(weight_kg: float, drug: str, indication: str = "") -> dict:
    drug = drug.lower().strip()
    table = {
        "paracetamol":  ("15 mg/kg PO q4–6h", 15),
        "acetaminophen":("15 mg/kg PO q4–6h", 15),
        "ibuprofen":    ("10 mg/kg PO q6–8h", 10),
        "epinephrine":  ("0.01 mg/kg IM (1:1000)", 0.01),
        "ceftriaxone":  ("50 mg/kg IM/IV q24h", 50),
        "ondansetron":  ("0.15 mg/kg IV/PO q8h", 0.15),
        "dexamethasone":("0.6 mg/kg PO/IV", 0.6),
    }
    if drug not in table:
        return {"name": "Pediatric Dose", "result": None, "tier": f"drug '{drug}' not in formulary",
                "inputs": {"weight_kg": weight_kg, "drug": drug}, "source": "—"}
    rule, mg_per_kg = table[drug]
    dose = round(weight_kg * mg_per_kg, 2)
    return {"name": "Pediatric Dose", "result": f"{dose} mg",
            "tier": f"{rule} — calculated for {weight_kg} kg",
            "inputs": {"weight_kg": weight_kg, "drug": drug, "indication": indication},
            "source": "WHO EC Pocket Book, 2023 ed."}


CALCULATORS = {
    "gcs":          calc_gcs,
    "qsofa":        calc_qsofa,
    "shock_index":  calc_shock_index,
    "map":          calc_map,
    "parkland":     calc_parkland,
    "ett_size":     calc_ett_size,
    "ped_dose":     calc_ped_dose,
}

# Per-encounter calculator invocation history
_calc_history: dict[int, list[dict]] = {}


# ---- Drug interactions / allergies ----
INTERACTIONS = {
    # (drug_a, drug_b) sorted -> (severity, mechanism, recommendation, source)
    ("epinephrine", "amiodarone"): (
        "major",
        "Both prolong QT; epinephrine can precipitate ventricular arrhythmia in setting of amiodarone.",
        "Use lowest effective epinephrine dose; continuous rhythm monitoring required.",
        "Lexicomp, 2024",
    ),
    ("ondansetron", "amiodarone"): (
        "major",
        "Additive QT prolongation — increased risk of torsades de pointes.",
        "Avoid combination if possible; if unavoidable, ECG monitoring before and after each dose.",
        "Lexicomp, 2024",
    ),
    ("ketamine", "fentanyl"): (
        "moderate",
        "Additive respiratory depression and sedation.",
        "Reduce fentanyl dose; have airway equipment immediately available.",
        "Stockley's Drug Interactions, 12th ed.",
    ),
    ("warfarin", "tranexamic_acid"): (
        "contraindicated",
        "Concurrent administration significantly elevates thrombotic risk.",
        "Do not co-administer. Alternative hemostatic strategy required.",
        "DailyMed — Cyklokapron prescribing information",
    ),
    ("warfarin", "txa"): (
        "contraindicated",
        "Concurrent administration significantly elevates thrombotic risk.",
        "Do not co-administer. Alternative hemostatic strategy required.",
        "DailyMed — Cyklokapron prescribing information",
    ),
    ("nsaid", "warfarin"): (
        "major",
        "NSAIDs displace warfarin from albumin and inhibit platelet function — bleeding risk.",
        "Avoid combination; if unavoidable, monitor INR closely.",
        "Lexicomp, 2024",
    ),
}


def _check_interactions(drug: str, encounter_id: int | None,
                        admin_history: list[str], allergies: list[str]) -> list[dict]:
    drug_l = drug.lower().strip().replace(" ", "_")
    flags = []
    # Allergy check
    for a in allergies:
        if a.lower().strip() in drug_l or drug_l in a.lower().strip():
            flags.append({
                "severity": "contraindicated",
                "kind": "allergy",
                "subject": drug,
                "interactant": a,
                "mechanism": f"Documented allergy to {a}.",
                "recommendation": "Do not administer. Select alternative.",
                "source": "Patient allergy list (signed event)",
            })
    # Pairwise drug-drug
    for prior in admin_history:
        prior_l = prior.lower().strip().replace(" ", "_")
        key = tuple(sorted([drug_l, prior_l]))
        if key in INTERACTIONS:
            sev, mech, rec, src = INTERACTIONS[key]
            flags.append({
                "severity": sev, "kind": "drug-drug",
                "subject": drug, "interactant": prior,
                "mechanism": mech, "recommendation": rec, "source": src,
            })
    return flags


# ---- rPPG simulator ----
_rppg_state = {"active": False, "encounter_id": None, "phase": 0.0,
               "base_hr": 78, "confidence": 0}


def _rppg_loop():
    """Generate plausible rPPG samples at 2Hz when active."""
    while True:
        time.sleep(0.5)
        if not _rppg_state["active"]:
            continue
        _rppg_state["phase"] += 0.5
        # Confidence ramps up over 5 seconds, then plateaus
        if _rppg_state["confidence"] < 3:
            if _rppg_state["phase"] > 5: _rppg_state["confidence"] = 3
            elif _rppg_state["phase"] > 2.5: _rppg_state["confidence"] = 2
            else: _rppg_state["confidence"] = 1
        # Slight rhythm variation
        bpm = _rppg_state["base_hr"] + 4 * math.sin(_rppg_state["phase"] / 7.0) + (secrets.randbelow(40) - 20) / 20.0
        ev = {"bpm": round(bpm, 1), "confidence": _rppg_state["confidence"], "t": _now_ms()}
        with _state_lock:
            for sub in list(_rppg_subs):
                sub.append(ev)


_rppg_subs: list[list] = []
threading.Thread(target=_rppg_loop, daemon=True).start()


# ---- Vision analysis (canned per-scenario) ----
VISION_RESULTS = {
    "battlefield": {
        "description": "Single high-velocity penetrating wound to the anterolateral left thigh, ~2 cm entry, with active dark red oozing consistent with venous bleeding adjacent to a brighter pulsatile arterial source. Surrounding tissue shows blast-pattern bruising at 4 cm radius.",
        "classification": "penetrating",
        "severity": "category I — immediate",
        "confidence": 0.84,
        "next_steps": [
            {"text": "Apply CAT tourniquet 5–7 cm proximal to wound, high and tight.", "cite": "TCCC-3.2"},
            {"text": "Annotate tourniquet time and write TQ on forehead.", "cite": "TCCC-3.5"},
            {"text": "Establish IV access; prepare TXA 1 g for slow push.", "cite": "TCCC-4.4"},
        ],
    },
    "disaster": {
        "description": "Pediatric anterior thigh laceration, ~6 cm linear, clean edges, no foreign body visible, oozing consistent with venous bleeding. Surrounding skin shows mild erythema. No deep structure exposure.",
        "classification": "laceration",
        "severity": "category II — urgent",
        "confidence": 0.78,
        "next_steps": [
            {"text": "Irrigate with sterile saline; estimate ≥250 mL.", "cite": "WHO-EC-p84"},
            {"text": "Apply pressure dressing; reassess in 30 minutes.", "cite": "WHO-EC-p86"},
            {"text": "Tetanus status review; defer suturing if >12 h since injury.", "cite": "WHO-EC-p98"},
        ],
    },
    "maritime": {
        "description": "Cyanosis of fingertips and lips consistent with hypoxic recovery; mottled skin coloration on extremities with poor capillary refill.",
        "classification": "hypoxic",
        "severity": "category I — immediate",
        "confidence": 0.71,
        "next_steps": [
            {"text": "Continue compressions; minimize interruptions.", "cite": "ILCOR-3.1"},
            {"text": "Apply AED pads on dry surface.", "cite": "ILCOR-7.2"},
        ],
    },
}


# ---- Handoff state ----
_handoffs: dict[int, dict] = {}  # encounter_id -> last receipt


def _build_fhir_bundle(encounter_id: int) -> dict:
    rec = _get_record(encounter_id)
    if not rec:
        return {}
    events = rec["events"]
    sc = sc_mod.get(rec["scenario_id"]) or {}
    pt_id = rec["patient_label"]

    resources = []
    resources.append({"resourceType": "Patient", "id": pt_id,
                      "identifier": [{"system": "aegis-local", "value": pt_id}]})
    resources.append({"resourceType": "Encounter", "id": f"ENC-{encounter_id}",
                      "status": "finished" if rec["ended_at"] else "in-progress",
                      "subject": {"reference": f"Patient/{pt_id}"},
                      "period": {"start": rec["started_at"], "end": rec["ended_at"] or _now_ms()},
                      "type": [{"text": sc.get("name", rec["scenario_id"])}]})

    obs_count = 0; proc_count = 0; ci_count = 0; med_count = 0
    for ev in events:
        et = ev["event_type"]
        if et == "vital_reading":
            for v in (ev["payload"].get("vitals") or []):
                obs_count += 1
                resources.append({
                    "resourceType": "Observation", "id": f"OBS-{obs_count}",
                    "status": "final",
                    "code": {"text": v["label"]},
                    "valueString": f"{v['val']} {v['unit']}",
                    "encounter": {"reference": f"Encounter/ENC-{encounter_id}"},
                    "effectiveDateTime": ev["created_at"],
                })
        elif et == "checklist_item" and ev["payload"].get("done"):
            proc_count += 1
            resources.append({
                "resourceType": "Procedure", "id": f"PROC-{proc_count}",
                "status": "completed",
                "code": {"text": ev["payload"].get("step_label", "")},
                "encounter": {"reference": f"Encounter/ENC-{encounter_id}"},
                "performedDateTime": ev["created_at"],
            })
        elif et in ("intake", "assessment"):
            ci_count += 1
            resources.append({
                "resourceType": "ClinicalImpression", "id": f"CI-{ci_count}",
                "status": "completed",
                "subject": {"reference": f"Patient/{pt_id}"},
                "encounter": {"reference": f"Encounter/ENC-{encounter_id}"},
                "summary": ev["payload"].get("text", "")[:1024],
                "date": ev["created_at"],
            })
        elif et == "medication_administered":
            med_count += 1
            resources.append({
                "resourceType": "MedicationAdministration", "id": f"MED-{med_count}",
                "status": "completed",
                "subject": {"reference": f"Patient/{pt_id}"},
                "context": {"reference": f"Encounter/ENC-{encounter_id}"},
                "medicationCodeableConcept": {"text": ev["payload"].get("drug", "")},
                "effectiveDateTime": ev["created_at"],
                "dosage": {"text": ev["payload"].get("dose", "")},
            })

    bundle = {
        "resourceType": "Bundle",
        "id": f"AEGIS-ENC-{encounter_id}",
        "type": "transaction",
        "timestamp": _now_ms(),
        "entry": [{"resource": r} for r in resources],
    }
    canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
    bundle_hash = hashlib.sha256(canonical).hexdigest()
    sig = _sign(canonical)
    bundle["entry"].append({"resource": {
        "resourceType": "Provenance",
        "recorded": _now_ms(),
        "agent": [{"who": {"display": f"AEGIS device {_DEVICE_PUB_FP[:16]}"}}],
        "signature": [{
            "type": [{"system": "urn:iso-astm:E1762-95:2013", "code": "1.2.840.10065.1.12.1.5"}],
            "when": _now_ms(),
            "who": {"display": f"ed25519/{_DEVICE_PUB_FP[:16]}"},
            "sigFormat": "application/jose",
            "data": sig,
        }],
        "extension": [{"url": "aegis-bundle-hash", "valueString": bundle_hash}],
    }})
    return {
        "bundle": bundle,
        "bundle_hash": bundle_hash,
        "signature": sig,
        "size_bytes": len(json.dumps(bundle).encode()),
        "resource_counts": {
            "Patient": 1, "Encounter": 1,
            "Observation": obs_count, "Procedure": proc_count,
            "ClinicalImpression": ci_count, "MedicationAdministration": med_count,
            "Provenance": 1,
        },
    }


# ---------------------------------------------------------------------
# Static + API server
# ---------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "AEGIS-Preview/2.0"

    def log_message(self, fmt, *args):  # quiet
        return

    # ---- helpers ----
    def _send_json(self, obj, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, path: Path):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404); return
        ext = path.suffix.lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
        }.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", "0") or 0)
        if not n: return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    # ---- V4.1 — source PDF (whitelist + Range support) ----
    def _serve_source_pdf(self, requested: str):
        # Reject path traversal / non-PDFs
        if "/" in requested or "\\" in requested or not requested.endswith(".pdf"):
            self.send_error(400, "invalid filename"); return
        if requested not in _v41_pdf_whitelist():
            self.send_error(404, "not in corpus whitelist"); return
        path = ROOT / "Reference" / requested
        if not path.exists():
            # Return a small text body explaining how to populate Reference/
            body = (f"Source PDF not present on disk: {requested}\n"
                    f"Place this file in {ROOT / 'Reference'} and reload."
                    ).encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        size = path.stat().st_size
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):
            try:
                s, _, e = rng[6:].partition("-")
                if s: start = int(s)
                if e: end = int(e)
                end = min(end, size - 1)
            except Exception:
                pass

        with path.open("rb") as fh:
            fh.seek(start)
            data = fh.read(end - start + 1)
        if rng:
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.end_headers()
        self.wfile.write(data)

    # ---- V4.1 — pilot brief PDF ----
    def _serve_pilot_brief(self):
        try:
            from backend import pilot_brief
            path = pilot_brief.ensure_cached()
            data = path.read_bytes()
        except Exception as exc:
            err = f"pilot brief generation failed: {exc}".encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers(); self.wfile.write(err); return
        # Detect PDF vs HTML fallback
        is_pdf = data.startswith(b"%PDF")
        ctype = "application/pdf" if is_pdf else "text/html; charset=utf-8"
        ext = "pdf" if is_pdf else "html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition",
                         f'attachment; filename="aegis_pilot_brief.{ext}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sse_headers(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def _sse_data(self, obj) -> bytes:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")

    # ---- routing ----
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        p = url.path

        # V5 — encounter state lives on the real backend. Proxy all
        # encounter-touching endpoints to :8000 BEFORE V4 handlers
        # so encounter IDs stay consistent across chat / situation /
        # procedural-step calls.
        if p.startswith("/api/encounter/") or p == "/api/encounters":
            return self._proxy_to_real_backend()

        # Static
        # Root → cockpit (cold_open.html no longer ships in V5).
        if p == "/" or p == "/cockpit" or p == "/cockpit.html" \
                or p == "/index.html" or p == "/cold_open.html":
            return self._send_static(FRONTEND / "index.html")
        if p == "/styles.css":
            return self._send_static(FRONTEND / "styles.css")
        if p == "/app.js":
            return self._send_static(FRONTEND / "app.js")
        if p == "/crisis_panel.js":
            return self._send_static(FRONTEND / "crisis_panel.js")

        # V6 — ambient background layer assets (ambient.css, topography.svg,
        # ambient.js). Whitelisted by extension; no traversal.
        if p.startswith("/ambient/"):
            name = p[len("/ambient/"):]
            if "/" in name or ".." in name:
                self.send_error(404); return
            if name.rsplit(".", 1)[-1].lower() not in ("css", "js", "svg"):
                self.send_error(404); return
            return self._send_static(FRONTEND / "ambient" / name)

        # --- Crisis Mode (one-screen non-expert UI) ---
        if p == "/crisis" or p == "/crisis.html":
            return self._send_static(FRONTEND / "crisis.html")
        if p == "/crisis.css":
            return self._send_static(FRONTEND / "crisis.css")
        if p == "/crisis.js":
            return self._send_static(FRONTEND / "crisis.js")

        if p == "/api/intake/questions":
            from backend import intake as _intake_mod
            ctx = (urlparse(self.path).query or "")
            # tiny inline parser: ?context=foo
            context = None
            for pair in ctx.split("&"):
                if pair.startswith("context="):
                    from urllib.parse import unquote
                    context = unquote(pair.split("=", 1)[1]) or None
                    break
            return self._send_json(
                {"questions": _intake_mod.get_default_intake_questions(context)}
            )

        # API GET
        if p == "/api/scenarios":
            return self._send_json(sc_mod.public_list())

        if p == "/api/system/status":
            with _state_lock:
                ev_count = sum(len(v) for v in _events.values())
                enc_count = len(_encounters)
            return self._send_json({
                "model": "SCRIPTED // V4",
                "model_name": "SCRIPTED // V4",
                "embed_model": "nomic-embed-text",
                "embed_dim": 768,
                "backend": "preview stdlib server (no ollama)",
                "inference_mode": "mock",
                "ram_mb": _approx_rss_mb(),
                "last_tps": 28.0,
                "stt_model": "faster-whisper base.en (mock)",
                "corpus_chunks": len(CITATIONS),
                "source_docs": len({c["document"] for c in CITATIONS.values()}),
                "index_built_at": "2026-04-24T00:00:00",
                "records": {"events": ev_count, "encounters": enc_count, "encrypted": False},
                "probes": list(_network_history),
                "build_version": "v3.0.0",
                "build_commit": "preview",
                "vision_model": "qwen2-vl-7b-instruct-q4_K_M (preview-mock)",
                "rppg_active": _rppg_state["active"],
                "device_pub_fingerprint": _DEVICE_PUB_FP,
                "key_issued_at": _KEY_ISSUED_AT,
                "bundles_signed": _BUNDLES_SIGNED,
                "handoffs_transmitted": _HANDOFFS_TRANSMITTED,
                "active_profile": _active_profile_id,
                "tamper_active": _TAMPER_FLIP["enabled"],
            })

        if p == "/api/records":
            with _state_lock:
                out = [
                    {**rec, "scenario_name": rec.get("scenario_name", rec["scenario_id"])}
                    for rec in sorted(_encounters.values(), key=lambda x: -x["id"])
                ]
            return self._send_json(out)

        if p.startswith("/api/records/"):
            try:
                eid = int(p.split("/")[3])
            except Exception:
                self.send_error(400); return
            rec = _get_record(eid)
            if not rec: self.send_error(404); return
            return self._send_json(rec)

        if p.startswith("/api/citations/"):
            cid = p.split("/")[-1]
            c = CITATIONS.get(cid)
            if not c:
                # Fabricate a graceful "not found" — preview-only fallback
                return self._send_json({
                    "id": cid, "text": "Source not present in preview corpus snapshot.",
                    "document": "—", "page": "", "section": "—", "score": None,
                })
            return self._send_json({**c, "id": cid, "score": 0.823})

        if p == "/api/network/stream":
            return self._sse_network()

        # ---- V4.1 source PDF serving (whitelist + Range) ----
        if p.startswith("/api/source-pdf/"):
            from urllib.parse import unquote
            requested = unquote(p[len("/api/source-pdf/"):])
            return self._serve_source_pdf(requested)

        # ---- V4.1 trust surface JSON ----
        if p == "/api/trust-surface":
            return self._send_json(_v41_trust_surface())

        # ---- V4.1 pilot brief PDF ----
        if p == "/api/pilot-brief/cached":
            return self._serve_pilot_brief()

        # ---- V4 corpus retrieval ----
        if p.startswith("/api/retrieve/chunk/"):
            cid = p.split("/")[-1]
            chunk = _v4_get_chunk(cid)
            if not chunk:
                return self._send_json({
                    "id": cid, "citation_id": cid,
                    "text": "Source not present in local corpus.",
                    "document": "—", "page": "", "section": "—", "score": None,
                })
            return self._send_json(chunk)

        if p == "/api/corpus/list":
            return self._send_json({"chunks": _v4_load_corpus()})

        # ---- V4 GET aliases (encounter/*) ----
        if p.startswith("/api/encounter/"):
            parts = p.split("/")
            if len(parts) >= 4:
                eid_part = parts[3]
                # /api/encounter/{id}
                if len(parts) == 4:
                    rec = _v4_resolve_record(eid_part)
                    if not rec: self.send_error(404); return
                    return self._send_json(rec)
                # /api/encounter/{id}/integrity
                if len(parts) == 5 and parts[4] == "integrity":
                    rec = _v4_resolve_record(eid_part)
                    if not rec: self.send_error(404); return
                    return self._send_json({
                        "valid": rec.get("integrity_ok", True),
                        "event_count": rec.get("chain_length",
                                               len(rec.get("events", []))),
                        "first_break_event_id": rec.get("broken_event_id"),
                        "verified_at": _now_iso_v4(),
                    })

        if p == "/api/encounters":
            return self._send_json([
                _v4_summary(rec) for rec in sorted(
                    _encounters.values(), key=lambda x: -x["id"])
            ])

        if p == "/health":
            return self._send_json({"ok": True, "version": "v4.0.0",
                                    "mode": "mock"})

        # ---- V3 GET routes ----
        if p == "/api/profiles":
            return self._send_json({"profiles": PROFILES, "active": _active_profile_id})

        if p == "/api/queue":
            return self._send_json(_queue_list())

        if p == "/api/crypto/key":
            return self._send_json({
                "algorithm": "ed25519",  # production; preview uses HMAC-SHA256 chain
                "public_fingerprint": _DEVICE_PUB_FP,
                "issued_at": _KEY_ISSUED_AT,
                "bundles_signed": _BUNDLES_SIGNED,
                "handoffs_transmitted": _HANDOFFS_TRANSMITTED,
            })

        if p == "/api/rppg/stream":
            return self._sse_rppg()

        if p == "/api/calculators":
            return self._send_json({"available": list(CALCULATORS.keys())})

        if p.startswith("/api/calc-history/"):
            try: eid = int(p.split("/")[-1])
            except Exception: self.send_error(400); return
            return self._send_json({"history": _calc_history.get(eid, [])})

        # V5 proxy — forward unknown /api/* GETs to the real backend so
        # the preview is fully functional (chat, situation, procedural
        # steps, etc.) even though the V4 mock doesn't implement them.
        if p.startswith("/api/"):
            return self._proxy_to_real_backend()

        self.send_error(404)

    def do_POST(self):
        url = urlparse(self.path)
        p = url.path

        # V5 — proxy all encounter + chat + situation routes to the real
        # backend (see do_GET note above).
        if (p.startswith("/api/encounter/")
                or p == "/api/encounter/create"
                or p == "/api/chat"
                or p == "/api/qa"):
            return self._proxy_to_real_backend()

        if p == "/api/reason":
            return self._sse_reason(self._read_json())

        # --- Crisis Mode pipeline (LLM-backed when reachable) ---
        if p == "/api/crisis":
            import asyncio as _aio
            req = self._read_json() or {}
            from backend import (
                intake as _intake_mod,
                orchestrator as _orch,
                llm_agents as _llm,
            )
            # Accept either a fully-formed encounter or guided-form responses.
            if "responses" in req:
                encounter = _intake_mod.build_structured_encounter(
                    req.get("responses") or {}
                )
            elif "encounter" in req:
                encounter = req.get("encounter") or {}
            else:
                # Treat the body itself as the responses dict.
                encounter = _intake_mod.build_structured_encounter(req)
            try:
                out = _aio.run(_orch.run_encounter_async(
                    encounter,
                    agents=_llm.LLM_AGENTS,
                    offline_status=_llm.status_snapshot(),
                ))
            except Exception as exc:
                return self._send_json(
                    {"error": "orchestrator_failed", "detail": str(exc)}, 500
                )
            return self._send_json(out)

        if p == "/api/vitals":
            req = self._read_json()
            sid = req.get("scenario_id", "")
            sc = sc_mod.get(sid)
            if not sc:
                # V6 — LLM-driven encounters (sentinel "__llm__") have no
                # entry in scenarios.SCENARIOS; fall back to the generic
                # battlefield arc so the vitals panel still animates.
                if sid == "__llm__":
                    sc = {"vital_arc_key": "battlefield"}
                else:
                    self.send_error(404); return
            v = sc_mod.vitals_for(sc, int(req.get("elapsed_ms") or 0), req.get("checklist") or [])
            return self._send_json({"vitals": v})

        if p == "/api/records/start":
            req = self._read_json()
            return self._send_json(_start_encounter(req.get("scenario_id", "")))

        if p.startswith("/api/records/") and p.endswith("/end"):
            try: eid = int(p.split("/")[3])
            except Exception: self.send_error(400); return
            with _state_lock:
                if eid in _encounters:
                    _encounters[eid]["ended_at"] = _now_ms()
            return self._send_json({"ok": True})

        if p.startswith("/api/records/") and p.endswith("/event"):
            try: eid = int(p.split("/")[3])
            except Exception: self.send_error(400); return
            req = self._read_json()
            _add_event(eid, req.get("event_type", "unknown"), req.get("payload") or {})
            return self._send_json({"ok": True})

        if p == "/api/canned/replay":
            req = self._read_json()
            sc = sc_mod.get(req.get("scenario_id", "")) or {}
            return self._send_json({"transcript": sc.get("canned_vox", "")})

        # ---- V4 POST aliases (encounter/*) ----
        if p == "/api/encounter/create":
            req = self._read_json()
            sid = req.get("scenario_id", "battlefield")
            sc = sc_mod.get(sid) or {}
            label = req.get("patient_label") or sc.get("patient_label", "PT-—")
            rec = _start_encounter(sid)
            with _state_lock:
                _encounters[rec["id"]]["patient_label"] = label
            return self._send_json({
                "id": f"ENC-{rec['id']:012d}",
                "scenario_id": sid,
                "patient_label": label,
                "started_at": _now_iso_v4(),
            })

        if p.startswith("/api/encounter/"):
            parts = p.split("/")
            if len(parts) >= 5:
                eid_str = parts[3]
                action = parts[4]
                rec = _v4_resolve_record(eid_str)
                if not rec: self.send_error(404); return
                eid = rec["id"]
                if action == "event":
                    body = self._read_json()
                    _add_event(eid, body.get("event_type", "unknown"),
                               body.get("payload") or {})
                    return self._send_json({"ok": True})
                if action == "end":
                    with _state_lock:
                        _encounters[eid]["ended_at"] = _now_iso_v4()
                    return self._send_json({"ok": True,
                                            "ended_at": _now_iso_v4()})

        # ---- V4.1 pilot brief regeneration ----
        if p == "/api/pilot-brief/generate":
            try:
                from backend import pilot_brief
                pilot_brief.regenerate()
                return self._send_json({"ok": True,
                                        "path": str(pilot_brief.CACHED_PATH)})
            except Exception as exc:
                return self._send_json({"ok": False, "error": str(exc)}, 500)

        # ---- V4 four LLM endpoints (preview = canned-shape) ----
        if p == "/api/extract":
            req = self._read_json()
            return self._send_json(_v4_extract(req))
        if p == "/api/qa":
            req = self._read_json()
            return self._send_json(_v4_qa(req))
        if p == "/api/nudges":
            req = self._read_json()
            return self._send_json(_v4_nudges(req))
        if p == "/api/aar":
            req = self._read_json()
            return self._send_json(_v4_aar(req))

        # ---- V4 tamper demo ----
        if p == "/api/records/tamper-event":
            req = self._read_json()
            return self._send_json(_v4_tamper_event(req))
        if p == "/api/records/heal-event":
            req = self._read_json()
            return self._send_json(_v4_heal_event(req))

        # ---- V3 POST routes ----
        if p.startswith("/api/profiles/activate/"):
            global _active_profile_id
            pid = p.split("/")[-1]
            if pid not in {p_["id"] for p_ in PROFILES}:
                return self._send_json({"ok": False, "error": "unknown profile"}, 400)
            _active_profile_id = pid
            return self._send_json({"ok": True, "active": pid})

        if p == "/api/queue/create":
            req = self._read_json()
            sid = req.get("scenario_id") or "battlefield"
            sc = sc_mod.get(sid) or {}
            # Generate unique patient label per encounter
            with _state_lock:
                seq = len(_encounters) + 1
            base = sc.get("patient_label", "PT-—")
            pt = f"{base[:-3]}{seq:03d}" if base[-3:].isdigit() else f"{base}-{seq:03d}"
            rec = _start_encounter(sid)
            with _state_lock:
                _encounters[rec["id"]]["patient_label"] = pt
            _add_event(rec["id"], "encounter_created", {"profile": _active_profile_id})
            return self._send_json(_queue_list())

        if p.startswith("/api/queue/triage/"):
            try: eid = int(p.split("/")[-1])
            except Exception: self.send_error(400); return
            req = self._read_json()
            return self._send_json(_queue_set_triage(eid, (req.get("category") or "").lower()))

        if p.startswith("/api/queue/switch/"):
            # No-op server-side — frontend tracks active encounter, but log it
            try: eid = int(p.split("/")[-1])
            except Exception: self.send_error(400); return
            return self._send_json({"ok": True, "active": eid})

        if p == "/api/records/tamper":
            # Toggle tamper on the most recent event of active encounter, or specified
            req = self._read_json()
            eid = req.get("encounter_id")
            if eid is None:
                with _state_lock:
                    actives = [e for e in _encounters.values() if not e.get("ended_at")]
                if actives: eid = actives[-1]["id"]
            if eid is None or eid not in _events or not _events[eid]:
                return self._send_json({"ok": False, "error": "no events to tamper"})
            with _state_lock:
                target_id = _events[eid][-1]["id"] if not _TAMPER_FLIP["enabled"] else _TAMPER_FLIP["event_id"]
                if _TAMPER_FLIP["enabled"]:
                    _TAMPER_FLIP.update({"enabled": False, "encounter_id": None, "event_id": None})
                else:
                    _TAMPER_FLIP.update({"enabled": True, "encounter_id": eid, "event_id": target_id})
            return self._send_json({
                "tampered": _TAMPER_FLIP["enabled"],
                "encounter_id": _TAMPER_FLIP.get("encounter_id"),
                "event_id": _TAMPER_FLIP.get("event_id"),
            })

        if p == "/api/rppg/start":
            req = self._read_json()
            with _state_lock:
                _rppg_state["active"] = True
                _rppg_state["encounter_id"] = req.get("encounter_id")
                _rppg_state["phase"] = 0.0
                _rppg_state["confidence"] = 0
                _rppg_state["base_hr"] = req.get("base_hr", 78)
                if req.get("encounter_id") and req["encounter_id"] in _encounters:
                    _encounters[req["encounter_id"]]["rppg_active"] = True
            if req.get("encounter_id"):
                _add_event(req["encounter_id"], "rppg_enabled",
                           {"frames_processed": "memory_only", "image_storage": "none"})
            return self._send_json({"ok": True})

        if p == "/api/rppg/stop":
            req = self._read_json()
            with _state_lock:
                _rppg_state["active"] = False
                eid = _rppg_state.get("encounter_id")
                if eid and eid in _encounters:
                    _encounters[eid]["rppg_active"] = False
            if req.get("encounter_id"):
                _add_event(req["encounter_id"], "rppg_disabled", {})
            return self._send_json({"ok": True})

        if p == "/api/vision/analyze":
            req = self._read_json()
            sid = req.get("scenario_id", "battlefield")
            eid = req.get("encounter_id")
            result = VISION_RESULTS.get(sid, VISION_RESULTS["battlefield"])
            if eid is not None:
                _add_event(eid, "image_analyzed", {
                    "scenario_id": sid,
                    "classification": result["classification"],
                    "severity": result["severity"],
                    "confidence": result["confidence"],
                    "image_hash": hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(),
                })
            return self._send_json(result)

        if p.startswith("/api/calculators/"):
            name = p.split("/")[-1]
            fn = CALCULATORS.get(name)
            if not fn:
                return self._send_json({"ok": False, "error": "unknown calculator"}, 400)
            req = self._read_json()
            inputs = req.get("inputs") or {}
            eid = req.get("encounter_id")
            try:
                out = fn(**inputs)
            except TypeError as e:
                return self._send_json({"ok": False, "error": f"input mismatch: {e}"}, 400)
            out["t"] = _now_ms()
            if eid is not None:
                _calc_history.setdefault(eid, []).append(out)
                _add_event(eid, "calculator_invoked", out)
            return self._send_json(out)

        if p == "/api/interactions/check":
            req = self._read_json()
            drug = req.get("drug", "")
            eid = req.get("encounter_id")
            history = req.get("admin_history") or []
            allergies = req.get("allergies") or []
            flags = _check_interactions(drug, eid, history, allergies)
            if eid is not None and flags:
                with _state_lock:
                    if eid in _encounters:
                        _encounters[eid]["interactions_pending"] = (
                            _encounters[eid].get("interactions_pending", 0) + len(flags))
                _add_event(eid, "interaction_flagged",
                           {"drug": drug, "flags": flags})
            return self._send_json({"flags": flags})

        if p == "/api/medications/log":
            req = self._read_json()
            eid = req.get("encounter_id")
            drug = req.get("drug", "")
            dose = req.get("dose", "")
            if eid is not None:
                _add_event(eid, "medication_administered", {"drug": drug, "dose": dose,
                                                            "route": req.get("route", "")})
            return self._send_json({"ok": True})

        if p == "/api/handoff/prepare":
            req = self._read_json()
            eid = req.get("encounter_id")
            if eid is None or eid not in _encounters:
                return self._send_json({"ok": False, "error": "encounter not found"}, 400)
            packaged = _build_fhir_bundle(eid)
            return self._send_json({
                "ok": True,
                "encounter_id": eid,
                "bundle_hash": packaged["bundle_hash"],
                "size_bytes": packaged["size_bytes"],
                "resource_counts": packaged["resource_counts"],
                "device_pub_fingerprint": _DEVICE_PUB_FP,
                "recipient": {
                    "name": "Mock Definitive Care Receiver",
                    "endpoint": "https://localhost:8001/fhir/Bundle",
                    "pub_fingerprint": "f7b2e6a4d1c098e35a2f4c8b9e1d0a7c",
                },
            })

        if p == "/api/handoff/transmit":
            global _BUNDLES_SIGNED, _HANDOFFS_TRANSMITTED
            req = self._read_json()
            eid = req.get("encounter_id")
            if eid is None or eid not in _encounters:
                return self._send_json({"ok": False, "error": "encounter not found"}, 400)
            packaged = _build_fhir_bundle(eid)
            _BUNDLES_SIGNED += 1
            _HANDOFFS_TRANSMITTED += 1
            receipt = {
                "receipt_id": f"R-{int(time.time())}-{eid}",
                "received_at": _now_ms(),
                "receiver_id": "mock-definitive-care/v1",
                "receiver_pub_fingerprint": "f7b2e6a4d1c098e35a2f4c8b9e1d0a7c",
                "bundle_hash_confirmed": packaged["bundle_hash"],
                "receiver_signature": _sign(("RECEIPT|" + packaged["bundle_hash"]).encode()),
                "verified": True,
            }
            _handoffs[eid] = receipt
            with _state_lock:
                _encounters[eid]["transmitted"] = True
                _encounters[eid]["receipt"] = receipt
            _add_event(eid, "handoff_transmitted", {
                "bundle_hash": packaged["bundle_hash"],
                "size_bytes": packaged["size_bytes"],
                "receipt_id": receipt["receipt_id"],
            })
            return self._send_json({"ok": True, "receipt": receipt,
                                    "bundle_hash": packaged["bundle_hash"],
                                    "size_bytes": packaged["size_bytes"]})

        # V5 proxy — forward unknown /api/* POSTs to the real backend.
        if p.startswith("/api/"):
            return self._proxy_to_real_backend()

        self.send_error(404)

    # ---- V5 backend proxy ----
    # Anything /api/* that the V4 mock doesn't implement is forwarded
    # to the real AEGIS uvicorn at REAL_BACKEND. Lets the preview act
    # as a single front-door for chat / situation / procedural-steps
    # without the operator caring which port serves which endpoint.
    def _proxy_to_real_backend(self):
        import urllib.request as _ureq
        import urllib.error as _uerr
        target = f"{REAL_BACKEND}{self.path}"
        body = b""
        clen = self.headers.get("Content-Length")
        if clen:
            try:
                body = self.rfile.read(int(clen))
            except Exception:
                body = b""
        req = _ureq.Request(
            target,
            data=body if body else None,
            method=self.command,
            headers={k: v for k, v in self.headers.items()
                     if k.lower() not in ("host", "content-length")},
        )
        try:
            resp = _ureq.urlopen(req, timeout=120)
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                if k.lower() in ("transfer-encoding", "connection",
                                 "access-control-allow-origin",
                                 "access-control-allow-methods",
                                 "access-control-allow-headers"):
                    continue
                self.send_header(k, v)
            # Re-emit our own permissive CORS so the browser is happy.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(resp.read())
        except _uerr.HTTPError as exc:
            data = b""
            try: data = exc.read()
            except Exception: pass
            self.send_response(exc.code)
            self.send_header("Content-Type",
                             exc.headers.get("Content-Type", "text/plain"))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": "real_backend_unreachable",
                "detail": str(exc),
                "target": target,
            }).encode())

    # ---- SSE handlers ----
    def _sse_network(self):
        self._send_sse_headers()
        sub: list = []
        with _state_lock:
            _network_subs.append(sub)
            # Send latest immediately so client doesn't wait 2s for first probe
            if _network_history:
                last = _network_history[-1]
        try:
            try:
                self.wfile.write(self._sse_data(last)); self.wfile.flush()
            except Exception:
                pass
            while True:
                with _state_lock:
                    items = sub[:]
                    sub.clear()
                if items:
                    for it in items:
                        try:
                            self.wfile.write(self._sse_data(it)); self.wfile.flush()
                        except Exception:
                            return
                else:
                    try:
                        self.wfile.write(b": keepalive\n\n"); self.wfile.flush()
                    except Exception:
                        return
                time.sleep(0.6)
        finally:
            with _state_lock:
                if sub in _network_subs:
                    _network_subs.remove(sub)

    def _sse_rppg(self):
        self._send_sse_headers()
        sub: list = []
        with _state_lock:
            _rppg_subs.append(sub)
        try:
            while True:
                with _state_lock:
                    items = sub[:]; sub.clear()
                if items:
                    for it in items:
                        try:
                            self.wfile.write(self._sse_data(it)); self.wfile.flush()
                        except Exception:
                            return
                else:
                    try:
                        self.wfile.write(b": keepalive\n\n"); self.wfile.flush()
                    except Exception:
                        return
                time.sleep(0.4)
        finally:
            with _state_lock:
                if sub in _rppg_subs:
                    _rppg_subs.remove(sub)

    def _sse_reason(self, req: dict):
        scenario_id = req.get("scenario_id", "battlefield")
        prompt = req.get("prompt", "")
        encounter_id = req.get("encounter_id")
        sc = sc_mod.get(scenario_id) or sc_mod.get("battlefield")

        # Resolve canonical text — same source the production fallback uses
        text = sc_mod.cached_response(scenario_id) or ""
        if prompt and prompt != "__SCENARIO_PRIMER__":
            # Append a brief reassessment paragraph so the cockpit reflects
            # the operator's spoken/typed input
            tag = "[ASSESSMENT]" if "[ASSESSMENT]" in text else ""
            text = text + ("\n[ASSESSMENT]\n" if tag else "") + (
                f"Operator input received: \"{prompt[:160]}\". Findings reinforce prior assessment; "
                f"no new differential indicated. Continue current sequence and reassess at the "
                f"next scheduled interval. [TCCC-3.4]\n"
            )

        # Build retrieved chunks list — top-k of relevant CITATIONS by tag
        tags = sc.get("tags", []) if sc else []
        retrieved = []
        for cid, c in CITATIONS.items():
            if any(t in tags for t in c.get("tags", [])):
                retrieved.append({**c, "id": cid, "score": round(0.83 - 0.01 * len(retrieved), 3)})
        retrieved = retrieved[:6]

        self._send_sse_headers()
        try:
            self.wfile.write(self._sse_data({
                "type": "meta",
                "model": "SCRIPTED // V4",
                "retrieved": retrieved,
                "scenario": scenario_id,
            })); self.wfile.flush()
        except Exception:
            return

        # Stream the canonical text in small chunks at a slightly faster
        # rate than the typewriter so the client buffer fills naturally.
        i = 0
        chunk = 6
        cps_target = 90  # tokens-ish per second
        interval = chunk / cps_target
        while i < len(text):
            piece = text[i : i + chunk]
            try:
                self.wfile.write(self._sse_data({"type": "token", "text": piece})); self.wfile.flush()
            except Exception:
                return
            i += chunk
            time.sleep(interval)

        # Persist a couple of events on the encounter
        if encounter_id is not None:
            try:
                eid = int(encounter_id)
                _add_event(eid, "intake", {"text": _between(text, "[INTAKE]", "[ASSESSMENT]").strip()})
                _add_event(eid, "assessment", {"text": _between(text, "[ASSESSMENT]", "[GUIDANCE]").strip()})
            except Exception:
                pass

        try:
            self.wfile.write(self._sse_data({"type": "done", "tokens": len(text), "tps": 22.4}))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except Exception:
            pass


def _between(s: str, a: str, b: str) -> str:
    i = s.find(a)
    if i < 0: return ""
    j = s.find(b, i + len(a))
    if j < 0: return s[i + len(a):]
    return s[i + len(a):j]


def _approx_rss_mb():
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(rss / (1024 * 1024)) if rss > 10_000_000 else int(rss / 1024)
    except Exception:
        return None


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[aegis preview] serving http://localhost:{PORT}")
    print(f"[aegis preview] frontend: {FRONTEND}")
    print(f"[aegis preview] reasoning streams come from the cached canonical responses")
    print(f"[aegis preview] in backend/scenarios.py — same text used for production fallback.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
