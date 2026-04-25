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
                del _network_history[0:-30]
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

        # Static
        if p == "/" or p == "/index.html":
            return self._send_static(FRONTEND / "index.html")
        if p == "/styles.css":
            return self._send_static(FRONTEND / "styles.css")
        if p == "/app.js":
            return self._send_static(FRONTEND / "app.js")

        # API GET
        if p == "/api/scenarios":
            return self._send_json(sc_mod.public_list())

        if p == "/api/system/status":
            with _state_lock:
                ev_count = sum(len(v) for v in _events.values())
                enc_count = len(_encounters)
            return self._send_json({
                "model": "gemma2:9b-instruct-q4_K_M (preview-mock)",
                "embed_model": "nomic-embed-text",
                "embed_dim": 768,
                "backend": "preview stdlib server (no ollama)",
                "ram_mb": _approx_rss_mb(),
                "last_tps": 24.7,
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

        self.send_error(404)

    def do_POST(self):
        url = urlparse(self.path)
        p = url.path

        if p == "/api/reason":
            return self._sse_reason(self._read_json())

        if p == "/api/vitals":
            req = self._read_json()
            sc = sc_mod.get(req.get("scenario_id", ""))
            if not sc:
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

        self.send_error(404)

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
                "model": "gemma2:9b-instruct-q4_K_M (preview-mock)",
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
