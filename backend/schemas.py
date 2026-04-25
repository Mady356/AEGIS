from __future__ import annotations

from copy import deepcopy


def _parse_bp(value: object) -> tuple[float | None, float | None]:
    if isinstance(value, str) and "/" in value:
        left, right = value.split("/", 1)
        try:
            return float(left.strip()), float(right.strip())
        except ValueError:
            return None, None
    if isinstance(value, dict):
        sbp = value.get("systolic")
        dbp = value.get("diastolic")
        try:
            return float(sbp), float(dbp)
        except (TypeError, ValueError):
            return None, None
    return None, None


def normalize_encounter(encounter: dict | None) -> dict:
    raw = deepcopy(encounter or {})
    vitals_in = raw.get("vitals") or {}

    hr = vitals_in.get("heart_rate")
    rr = vitals_in.get("respiratory_rate")
    spo2 = vitals_in.get("oxygen_saturation")
    temp = vitals_in.get("temperature")
    sbp, dbp = _parse_bp(vitals_in.get("blood_pressure"))
    if sbp is None:
        sbp = vitals_in.get("systolic_bp")
    if dbp is None:
        dbp = vitals_in.get("diastolic_bp")

    def _as_float(value: object) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    normalized = {
        "encounter_id": raw.get("encounter_id", "encounter-local"),
        "age": raw.get("age"),
        "sex": raw.get("sex", "unknown"),
        "chief_complaint": raw.get("chief_complaint", ""),
        "symptoms": list(raw.get("symptoms") or []),
        "context": raw.get("context", ""),
        "notes": raw.get("notes", ""),
        "vitals": {
            "heart_rate": _as_float(hr),
            "systolic_bp": _as_float(sbp),
            "diastolic_bp": _as_float(dbp),
            "respiratory_rate": _as_float(rr),
            "oxygen_saturation": _as_float(spo2),
            "temperature_c": _as_float(temp),
            "mental_status": vitals_in.get("mental_status", "unknown"),
        },
        "metadata": raw.get("metadata") or {},
    }
    return normalized
