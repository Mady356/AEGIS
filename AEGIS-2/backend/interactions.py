"""
Drug interaction & allergy engine.

Local database covering the four-scenario formulary plus chronic medications
likely to be in patient histories. Severity tiers: contraindicated / major /
moderate / minor.

Interactions are stored as ordered pairs (lexicographic) so lookup is
order-independent.
"""

from __future__ import annotations
from typing import Iterable


# (drug_a, drug_b) sorted -> (severity, mechanism, recommendation, source)
INTERACTIONS: dict[tuple[str, str], tuple[str, str, str, str]] = {
    ("amiodarone", "epinephrine"): (
        "major",
        "Both prolong QT; epinephrine can precipitate ventricular arrhythmia in setting of amiodarone.",
        "Use lowest effective epinephrine dose; continuous rhythm monitoring required.",
        "Lexicomp, 2024",
    ),
    ("amiodarone", "ondansetron"): (
        "major",
        "Additive QT prolongation — increased risk of torsades de pointes.",
        "Avoid combination if possible; if unavoidable, ECG monitoring before and after each dose.",
        "Lexicomp, 2024",
    ),
    ("fentanyl", "ketamine"): (
        "moderate",
        "Additive respiratory depression and sedation.",
        "Reduce fentanyl dose; have airway equipment immediately available.",
        "Stockley's Drug Interactions, 12th ed.",
    ),
    ("tranexamic_acid", "warfarin"): (
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
    ("midazolam", "fentanyl"): (
        "moderate",
        "Additive CNS and respiratory depression.",
        "Titrate carefully; monitor SpO2 and ETCO2 continuously.",
        "Lexicomp, 2024",
    ),
    ("ssri", "tramadol"): (
        "major",
        "Risk of serotonin syndrome; both increase CNS serotonergic activity.",
        "Avoid combination. Select non-serotonergic analgesic.",
        "Stockley's Drug Interactions, 12th ed.",
    ),
}

# Drug aliases — normalize trade names and abbreviations.
ALIASES = {
    "txa": "tranexamic_acid",
    "tranexamic": "tranexamic_acid",
    "cyklokapron": "tranexamic_acid",
    "epi": "epinephrine",
    "adrenaline": "epinephrine",
    "ibuprofen": "nsaid",
    "naproxen": "nsaid",
    "diclofenac": "nsaid",
    "fluoxetine": "ssri",
    "sertraline": "ssri",
    "paroxetine": "ssri",
    "citalopram": "ssri",
}


def normalize(drug: str) -> str:
    d = drug.lower().strip().replace(" ", "_").replace("-", "_")
    return ALIASES.get(d, d)


def check(drug: str,
          admin_history: Iterable[str],
          allergies: Iterable[str]) -> list[dict]:
    """Return list of flagged interactions and allergy conflicts."""
    drug_n = normalize(drug)
    flags: list[dict] = []

    # Allergy check (substring + alias-aware)
    for a in allergies:
        a_n = normalize(a)
        if a_n == drug_n or a_n in drug_n or drug_n in a_n:
            flags.append({
                "severity": "contraindicated", "kind": "allergy",
                "subject": drug, "interactant": a,
                "mechanism": f"Documented allergy to {a}.",
                "recommendation": "Do not administer. Select alternative.",
                "source": "Patient allergy list (signed event)",
            })

    # Pairwise drug-drug
    for prior in admin_history:
        prior_n = normalize(prior)
        key = tuple(sorted([drug_n, prior_n]))
        if key in INTERACTIONS:
            sev, mech, rec, src = INTERACTIONS[key]
            flags.append({
                "severity": sev, "kind": "drug-drug",
                "subject": drug, "interactant": prior,
                "mechanism": mech, "recommendation": rec, "source": src,
            })
    return flags
