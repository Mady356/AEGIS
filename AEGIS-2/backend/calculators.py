"""
Validated clinical calculators — pure functions with explicit input
validation, source citation, and full provenance.

The LLM never computes these. It invokes them via tool-use; the backend
calls the appropriate function; the result is returned as structured JSON
which the model then quotes verbatim.
"""

from __future__ import annotations
from typing import Any


def _result(name: str, result: Any, tier: str, inputs: dict, source: str) -> dict:
    return {
        "name": name, "result": result, "tier": tier,
        "inputs": inputs, "source": source,
    }


def gcs(eye: int, verbal: int, motor: int) -> dict:
    if not (1 <= eye <= 4 and 1 <= verbal <= 5 and 1 <= motor <= 6):
        raise ValueError("GCS components out of range")
    total = eye + verbal + motor
    tier = ("severe brain injury — consider intubation" if total <= 8 else
            "moderate brain injury — stratify and monitor" if total <= 12 else
            "mild brain injury")
    return _result("Glasgow Coma Scale", total, tier,
                   {"eye": eye, "verbal": verbal, "motor": motor},
                   "Teasdale & Jennett, 1974 — Lancet 2:81–84")


def qsofa(rr: float, altered: bool, sbp: float) -> dict:
    score = (1 if rr >= 22 else 0) + (1 if altered else 0) + (1 if sbp <= 100 else 0)
    tier = "high risk for sepsis-related mortality" if score >= 2 else "low qSOFA"
    return _result("qSOFA", score, tier,
                   {"rr": rr, "altered_mental_status": altered, "systolic_bp": sbp},
                   "Singer M et al., 2016 — JAMA 315:801")


def shock_index(hr: float, sbp: float) -> dict:
    si = round(hr / max(sbp, 1), 2)
    tier = ("shock likely" if si >= 1.0 else
            "shock possible" if si >= 0.7 else "stable")
    return _result("Shock Index", si, tier,
                   {"hr": hr, "systolic_bp": sbp},
                   "Allgöwer & Buri, 1967")


def map(sbp: float, dbp: float) -> dict:
    m = round((sbp + 2 * dbp) / 3, 1)
    tier = "perfusion adequate" if m >= 65 else "low MAP — consider pressors"
    return _result("Mean Arterial Pressure", m, tier,
                   {"systolic_bp": sbp, "diastolic_bp": dbp},
                   "Standard hemodynamic formula")


def parkland(weight_kg: float, percent_bsa: float) -> dict:
    total_ml = round(4 * weight_kg * percent_bsa)
    return _result("Parkland Formula", total_ml,
                   f"{total_ml // 2} mL over first 8 h, remainder over next 16 h",
                   {"weight_kg": weight_kg, "percent_bsa": percent_bsa},
                   "Baxter & Shires, 1968 — Ann NY Acad Sci 150:874")


def ett_size(age_years: float) -> dict:
    uncuffed = round(age_years / 4 + 4, 1)
    cuffed = round(age_years / 4 + 3.5, 1)
    return _result("Pediatric ETT Sizing", cuffed,
                   f"cuffed: {cuffed} mm · uncuffed: {uncuffed} mm",
                   {"age_years": age_years},
                   "Khine et al., 1997 — Anesthesiology 86:627")


PED_DOSE_TABLE = {
    "paracetamol":   ("15 mg/kg PO q4–6h",  15),
    "acetaminophen": ("15 mg/kg PO q4–6h",  15),
    "ibuprofen":     ("10 mg/kg PO q6–8h",  10),
    "epinephrine":   ("0.01 mg/kg IM",      0.01),
    "ceftriaxone":   ("50 mg/kg IM/IV q24h", 50),
    "ondansetron":   ("0.15 mg/kg IV/PO q8h", 0.15),
    "dexamethasone": ("0.6 mg/kg PO/IV",    0.6),
}


def ped_dose(weight_kg: float, drug: str, indication: str = "") -> dict:
    drug = drug.lower().strip()
    if drug not in PED_DOSE_TABLE:
        return _result("Pediatric Dose", None,
                       f"drug '{drug}' not in formulary",
                       {"weight_kg": weight_kg, "drug": drug}, "—")
    rule, mg_per_kg = PED_DOSE_TABLE[drug]
    dose = round(weight_kg * mg_per_kg, 2)
    return _result("Pediatric Dose", f"{dose} mg",
                   f"{rule} — calculated for {weight_kg} kg",
                   {"weight_kg": weight_kg, "drug": drug, "indication": indication},
                   "WHO EC Pocket Book, 2023 ed.")


def wells_pe(clinical_signs: bool, pe_likely: bool, hr_over_100: bool,
             immobilization: bool, prior_pe: bool, hemoptysis: bool,
             malignancy: bool) -> dict:
    score = (3.0 if clinical_signs else 0) + (3.0 if pe_likely else 0) + \
            (1.5 if hr_over_100 else 0) + (1.5 if immobilization else 0) + \
            (1.5 if prior_pe else 0) + (1.0 if hemoptysis else 0) + \
            (1.0 if malignancy else 0)
    tier = ("high probability" if score > 6 else
            "moderate probability" if score >= 2 else "low probability")
    return _result("Wells Score (PE)", score, tier,
                   {"clinical_signs_dvt": clinical_signs,
                    "pe_more_likely_than_alt": pe_likely,
                    "hr_over_100": hr_over_100,
                    "immobilization_or_surgery_4w": immobilization,
                    "prior_pe_or_dvt": prior_pe,
                    "hemoptysis": hemoptysis,
                    "malignancy_active": malignancy},
                   "Wells PS et al., 2000 — Ann Intern Med 135:98")


def apgar(heart_rate: int, respiratory: int, muscle_tone: int,
          reflex: int, color: int) -> dict:
    for v, n in [(heart_rate, "HR"), (respiratory, "RR"), (muscle_tone, "tone"),
                 (reflex, "reflex"), (color, "color")]:
        if not (0 <= v <= 2):
            raise ValueError(f"APGAR component {n} out of range")
    total = heart_rate + respiratory + muscle_tone + reflex + color
    tier = ("severely depressed — resuscitate" if total <= 3 else
            "moderately depressed — assist" if total <= 6 else "reassuring")
    return _result("Apgar Score", total, tier,
                   {"heart_rate": heart_rate, "respiratory": respiratory,
                    "muscle_tone": muscle_tone, "reflex": reflex, "color": color},
                   "Apgar V, 1953 — Curr Res Anesth Analg 32:260")


REGISTRY = {
    "gcs": gcs, "qsofa": qsofa, "shock_index": shock_index, "map": map,
    "parkland": parkland, "ett_size": ett_size, "ped_dose": ped_dose,
    "wells_pe": wells_pe, "apgar": apgar,
}
