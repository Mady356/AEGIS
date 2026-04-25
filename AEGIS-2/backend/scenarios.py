"""
Scenario definitions: system prompts, retrieval filters, vital trajectories,
canned voice prompts, and cached fallback responses.
"""

from __future__ import annotations
import math


SCENARIOS = {
    "battlefield": {
        "id": "battlefield",
        "domain": "Battlefield",
        "case": "GSW Femoral",
        "name": "Combat Casualty // GSW",
        "patient_label": "PT-2026-0424-001",
        "tags": ["combat"],
        "system_prompt": "You are AEGIS — combat casualty decision support.",
        "primer_prompt": (
            "Casualty, male, approximate age 24, gunshot wound left thigh, suspected "
            "femoral arterial bleed, conscious and responsive, skin pale and "
            "diaphoretic. Talk me through it."
        ),
        "canned_vox": "Patient took a round to the left thigh, bleed is pumping, I have him conscious — talk me through it.",
        "steps": [
            "Apply CAT tourniquet 5–7 cm proximal to wound, high and tight.",
            "Verify hemorrhage cessation — confirm absence of distal pulse and bleeding.",
            "Annotate tourniquet time on casualty card and write TQ on forehead.",
            "Establish patent airway; place casualty in recovery position if unconscious.",
            "Initiate IV access, 18g antecubital, prepare TXA per protocol.",
            "Reassess at five-minute interval; escalate to junctional device if bleed reemerges.",
        ],
        "vital_arc_key": "battlefield",
    },
    "maritime": {
        "id": "maritime",
        "domain": "Maritime",
        "case": "Submerged Cardiac Event",
        "name": "Maritime // Cardiac Arrest",
        "patient_label": "PT-2026-0424-002",
        "tags": ["maritime"],
        "system_prompt": "You are AEGIS — submarine corpsman support.",
        "primer_prompt": (
            "Recovered diver, male, approximate age 41, surface time under three "
            "minutes, unresponsive on extraction, no spontaneous respiration, no "
            "carotid pulse. What's my sequence."
        ),
        "canned_vox": "Pulled a diver, no pulse, no breath — what's my sequence here.",
        "steps": [
            "Confirm scene safety; move casualty to dry, non-conductive surface.",
            "Initiate compressions at 100–120/min, depth 5–6 cm, full recoil.",
            "Deliver two rescue breaths after every 30 compressions; observe chest rise.",
            "Apply AED pads; pause only for rhythm analysis and shock delivery.",
            "Establish IV/IO access; prepare epinephrine 1 mg every 3–5 minutes.",
            "Continue cycles; consider advanced airway after second rhythm check.",
        ],
        "vital_arc_key": "maritime",
    },
    "disaster": {
        "id": "disaster",
        "domain": "Disaster",
        "case": "Pediatric Pyrexia",
        "name": "Disaster // Pediatric Pyrexia",
        "patient_label": "PT-2026-0424-003",
        "tags": ["pediatric", "disaster", "pharmacology"],
        "system_prompt": "You are AEGIS — disaster pediatric triage.",
        "primer_prompt": (
            "Pediatric casualty, female, approximate age 4 years, weight ~16 kg, "
            "fever 39.6 °C, lethargy, reduced oral intake over 36 hours, capillary "
            "refill 3 seconds, no rash. What do you give her."
        ),
        "canned_vox": "Four-year-old, fever's been climbing for a day and a half, she's listless — what do I give her.",
        "steps": [
            "Confirm weight by length-based tape; document on triage tag.",
            "Administer paracetamol 15 mg/kg PO — calculated dose 240 mg.",
            "Initiate ORS at 75 ml/kg over 4 hours — total 1.2 L planned.",
            "Reassess hydration, mental status, and temperature at 60-minute interval.",
            "Escalate to IV fluids if vomiting persists or capillary refill exceeds 4 seconds.",
            "Document and queue for physician review at next rotation.",
        ],
        "vital_arc_key": "disaster",
    },
}


def public_list() -> list[dict]:
    out = []
    for s in SCENARIOS.values():
        out.append({
            "id": s["id"], "domain": s["domain"], "case": s["case"],
            "name": s["name"], "patient_label": s["patient_label"],
            "steps": s["steps"],
        })
    return out


def get(scenario_id: str) -> dict | None:
    return SCENARIOS.get(scenario_id)


def cached_response(scenario_id: str) -> str:
    return _CACHED.get(scenario_id, "")


def vitals_for(scenario: dict, elapsed_ms: int, checklist: list) -> list[dict]:
    key = scenario.get("vital_arc_key", "battlefield")
    t = elapsed_ms / 1000.0
    H = 14
    samples_t = [t - (H - 1 - i) * 1.5 for i in range(H)]
    if key == "battlefield": return _vitals_battlefield(samples_t, checklist)
    if key == "maritime":    return _vitals_maritime(samples_t, checklist)
    return _vitals_disaster(samples_t, checklist)


def _smooth(x: float) -> float:
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    return x * x * (3 - 2 * x)


def _checked_at(chk: list, idx: int):
    if idx < len(chk) and chk[idx]:
        return 0.0
    return None


def _vital(label, val, unit, series, cls):
    spark = [max(1, int(round(abs(s)))) for s in series]
    return {"label": label, "val": val, "unit": unit, "spark": spark, "cls": cls}


def _cls_hr(hr, ped=False):
    if ped:
        return "warn" if hr > 130 else ("crit" if hr < 70 else "")
    return "crit" if hr > 140 or hr < 40 else ("warn" if hr > 110 or hr < 50 else "")


def _cls_spo2(s):
    return "crit" if s < 88 else ("warn" if s < 94 else "")


def _vitals_battlefield(samples_t, chk):
    tq_done_at = _checked_at(chk, 0)
    hrs, sbps, dbps, sps, rrs = [], [], [], [], []
    for ts in samples_t:
        ts = max(ts, 0.0)
        if tq_done_at is None or ts < tq_done_at:
            hr = 92 + 28 * _smooth(ts / 30)
            sbp = 118 - 30 * _smooth(ts / 30)
            dbp = 78 - 22 * _smooth(ts / 30)
        else:
            since = ts - tq_done_at
            hr = 124 - 18 * _smooth(since / 60)
            sbp = 88 + 14 * _smooth(since / 60)
            dbp = 56 + 10 * _smooth(since / 60)
        hrs.append(hr); sbps.append(sbp); dbps.append(dbp)
        sps.append(94 + 2 * _smooth(ts / 50))
        rrs.append(22 + 2 * math.sin(ts / 4))
    chr_, cs, cd = hrs[-1], sbps[-1], dbps[-1]
    return [
        _vital("HR", round(chr_), "bpm", hrs, _cls_hr(chr_)),
        _vital("BP", f"{round(cs)}/{round(cd)}", "mmHg", sbps, "warn" if cs < 95 else ""),
        _vital("SpO₂", round(sps[-1]), "%", sps, _cls_spo2(sps[-1])),
        _vital("RR", round(rrs[-1]), "/min", rrs, ""),
    ]


def _vitals_maritime(samples_t, chk):
    aed = _checked_at(chk, 3); epi = _checked_at(chk, 4)
    hrs, sbps, dbps, sps, rrs = [], [], [], [], []
    for ts in samples_t:
        ts = max(ts, 0.0)
        rosc = aed is not None and epi is not None
        if rosc:
            since = ts - max(aed, epi)
            hr = 30 + 70 * _smooth(since / 90)
            sbp = 60 + 50 * _smooth(since / 90)
            dbp = 38 + 32 * _smooth(since / 90)
            spo = 70 + 25 * _smooth(since / 90)
            rr = 4 + 14 * _smooth(since / 90)
        else:
            hr = 0; sbp = 0; dbp = 0; rr = 0
            spo = max(40, 62 - 0.2 * ts)
        hrs.append(hr); sbps.append(sbp); dbps.append(dbp); sps.append(spo); rrs.append(rr)
    chr_ = hrs[-1]; cs = sbps[-1]; cd = dbps[-1]
    return [
        _vital("HR", round(chr_) if chr_ > 0 else "0", "bpm", hrs,
               "crit" if chr_ < 30 else ("warn" if chr_ < 60 else "")),
        _vital("BP", f"{round(cs)}/{round(cd)}" if cs > 0 else "—", "mmHg", sbps,
               "crit" if cs < 60 else ("warn" if cs < 90 else "")),
        _vital("SpO₂", round(sps[-1]), "%", sps, _cls_spo2(sps[-1])),
        _vital("RR", round(rrs[-1]) if rrs[-1] > 0 else "0", "/min", rrs,
               "crit" if rrs[-1] < 6 else ""),
    ]


def _vitals_disaster(samples_t, chk):
    apap = _checked_at(chk, 1); ors_ = _checked_at(chk, 2)
    hrs, sbps, dbps, sps, ts_ = [], [], [], [], []
    for ts in samples_t:
        ts = max(ts, 0.0)
        if apap is not None and ts >= apap:
            since = ts - apap
            temp = 40.1 - 1.6 * _smooth(since / 60)
        else:
            temp = 40.1 + 0.3 * math.sin(ts / 8)
        if ors_ is not None and ts >= ors_:
            since = ts - ors_
            hr = 148 - 20 * _smooth(since / 90)
            sbp = 98 + 6 * _smooth(since / 90)
        else:
            hr = 148 + 4 * math.sin(ts / 5)
            sbp = 98 - 2 * _smooth(ts / 60)
        dbp = sbp - 36
        hrs.append(hr); sbps.append(sbp); dbps.append(dbp)
        sps.append(97 + math.sin(ts / 3))
        ts_.append(temp)
    chr_ = hrs[-1]; ct = ts_[-1]; cs = sbps[-1]; cd = dbps[-1]
    return [
        _vital("HR", round(chr_), "bpm", hrs, _cls_hr(chr_, ped=True)),
        _vital("BP", f"{round(cs)}/{round(cd)}", "mmHg", sbps, ""),
        _vital("SpO₂", round(sps[-1]), "%", sps, _cls_spo2(sps[-1])),
        _vital("Temp", f"{ct:.1f}", "°C", ts_, "warn" if ct >= 38.5 else ""),
    ]


_CACHED = {
    "battlefield": (
        "[INTAKE]\n"
        "Adult male combatant, age approximately 24, presenting with a single gunshot wound to the left "
        "thigh. Bleeding is described as pulsatile, consistent with arterial involvement, most likely the "
        "femoral artery. The casualty is conscious and verbally responsive at intake. [TCCC-1.0]\n\n"
        "[ASSESSMENT]\n"
        "Findings are consistent with life-threatening extremity hemorrhage. [TCCC-3.2] Tachycardia and "
        "diaphoresis indicate early Class II hemorrhagic shock. [TCCC-3.4] Tourniquet placement takes "
        "precedence over airway management in this MARCH sequence given the active arterial bleed. "
        "[TCCC-3.2]\n\n"
        "[GUIDANCE]\n"
        "1. Apply a CAT tourniquet 5–7 cm proximal to the wound, high and tight on the extremity. [TCCC-3.2]\n"
        "2. Tighten until distal pulse is absent and bleeding has stopped. [TCCC-3.2]\n"
        "3. Mark TQ time on the casualty card and write TQ on the forehead. [TCCC-3.5]\n"
        "4. Establish IV access antecubital 18g and prepare TXA 1 g for slow push. [TCCC-4.4]\n"
        "5. Reassess at five-minute intervals. Convert to pressure dressing only if conditions of "
        "Joint Trauma System CPG are met. [JTS-CPG-2104]\n"
    ),
    "maritime": (
        "[INTAKE]\n"
        "Adult male diver recovered from submersion under three minutes. Unresponsive on extraction, no "
        "spontaneous respiration, no palpable carotid pulse, cyanotic. [ILCOR-7.1]\n\n"
        "[ASSESSMENT]\n"
        "Cardiac arrest of probable hypoxic origin. [ILCOR-7.1] Compressions take precedence; rescue "
        "breaths integrated due to hypoxic primary mechanism. AED is indicated as soon as casualty is "
        "dry on a non-conductive surface. [ILCOR-7.2]\n\n"
        "[GUIDANCE]\n"
        "1. Confirm scene safety; move casualty to a dry, non-conductive surface. [ILCOR-7.1]\n"
        "2. Initiate compressions at 100–120/min, depth 5–6 cm, full recoil. [ILCOR-3.1]\n"
        "3. Deliver two rescue breaths after every 30 compressions. [ILCOR-3.2]\n"
        "4. Apply AED pads; pause only for rhythm analysis and shock delivery. [ILCOR-7.2]\n"
        "5. Establish IV/IO; prepare epinephrine 1 mg every 3–5 minutes. [NAVMED-5052-IV]\n"
        "6. Reassess and consider advanced airway after second rhythm check. [NAVMED-5052-AIR]\n"
    ),
    "disaster": (
        "[INTAKE]\n"
        "Pediatric female, approximately 4 years old, ~16 kg, fever 39.6 °C, lethargy, decreased oral "
        "intake for 36 hours, capillary refill 3 seconds, no rash. [WHO-EC-p84]\n\n"
        "[ASSESSMENT]\n"
        "Moderate dehydration secondary to a febrile illness of undetermined etiology. [WHO-EC-p84] "
        "Antipyresis, oral rehydration, and observational reassessment are indicated. Antibiotic "
        "therapy is deferred pending source identification. [WHO-IMAI-4.4]\n\n"
        "[GUIDANCE]\n"
        "1. Confirm weight by length-based tape and document on triage tag. [WHO-EC-p46]\n"
        "2. Administer paracetamol 15 mg/kg PO — calculated dose 240 mg. [WHO-EC-p98]\n"
        "3. Initiate ORS at 75 ml/kg over 4 hours — total 1.2 L. [WHO-IMAI-4.4]\n"
        "4. Reassess hydration, mental status, and temperature at 60-minute interval. [WHO-EC-p86]\n"
        "5. Escalate to IV fluids if vomiting persists or CRT exceeds 4 seconds. [WHO-EC-p88]\n"
        "6. Document and queue for physician review at next rotation. [UNSOURCED]\n"
    ),
}
