from __future__ import annotations


LOCAL_PROTOCOLS = {
    "hemorrhage": [
        "TCCC-3.2::Control life-threatening extremity hemorrhage with tourniquet high and tight.",
        "TCCC-3.5::Document tourniquet time and reassess bleeding control frequently.",
    ],
    "chest_pain": [
        "ATLS-Cardio-1::Prioritize ABCs, continuous monitoring, and early ECG when available.",
        "WHO-EM-4::Reassess perfusion and oxygenation trends while preparing transfer.",
    ],
    "dyspnea": [
        "WHO-Airway-2::Assess airway and oxygenation first; escalate support if saturation remains low.",
    ],
}


def retrieve_protocol_chunks(encounter: dict, triage: dict, differential: dict) -> list[str]:
    text = (
        str(encounter.get("chief_complaint", "")) + " " +
        " ".join(encounter.get("symptoms") or [])
    ).lower()

    keys = []
    if "bleed" in text or "hemorrhage" in text:
        keys.append("hemorrhage")
    if "chest pain" in text:
        keys.append("chest_pain")
    if "shortness of breath" in text or "dyspnea" in text:
        keys.append("dyspnea")

    chunks: list[str] = []
    for key in keys:
        chunks.extend(LOCAL_PROTOCOLS.get(key, []))
    return chunks
