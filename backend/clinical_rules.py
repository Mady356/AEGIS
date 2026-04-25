from typing import Any


def deterministic_triage(encounter: dict[str, Any]) -> dict[str, Any]:
    vitals = encounter.get("vitals") or {}

    hr = vitals.get("heart_rate")
    rr = vitals.get("respiratory_rate")
    spo2 = vitals.get("oxygen_saturation")
    systolic = vitals.get("systolic_bp")
    mental = (vitals.get("mental_status") or "").lower()

    red_flags: list[str] = []
    forced_acuity = None

    if systolic is not None and systolic < 90:
        red_flags.append("Hypotension: systolic blood pressure below 90")
        forced_acuity = "red"

    if hr is not None and hr > 120:
        red_flags.append("Severe tachycardia: heart rate above 120")
        forced_acuity = "red"

    if spo2 is not None and spo2 < 92:
        red_flags.append("Low oxygen saturation below 92%")
        forced_acuity = "red"

    if rr is not None and rr > 30:
        red_flags.append("Severe tachypnea: respiratory rate above 30")
        forced_acuity = "red"

    if any(term in mental for term in ["confused", "unresponsive", "altered", "lethargic"]):
        red_flags.append("Altered mental status")
        forced_acuity = "red"

    symptoms_text = " ".join(encounter.get("symptoms", [])).lower()
    complaint = (encounter.get("chief_complaint") or "").lower()
    text = f"{complaint} {symptoms_text}"

    if "chest pain" in text and ("shortness of breath" in text or "sweating" in text):
        red_flags.append("Chest pain with concerning associated symptoms")

    if "severe bleeding" in text or "uncontrolled bleeding" in text:
        red_flags.append("Possible uncontrolled hemorrhage")
        forced_acuity = "red"

    return {
        "forced_acuity": forced_acuity,
        "detected_red_flags": red_flags,
        "rule_source": "deterministic_vitals_and_red_flag_screen",
    }