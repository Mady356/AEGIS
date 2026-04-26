"""
V4.1 — TRUST surface content.

Centralized so the frontend renders it via /api/trust-surface and the
pilot-brief PDF builder reads from the same source. Updating an evidence
statement is a one-line change here that propagates everywhere.
"""

from __future__ import annotations


PRODUCT_POSITIONING = (
    "AEGIS is a documentation interface, not a clinical advisor. "
    "The local LLM extracts, retrieves, and summarizes — it does not prescribe."
)


GAP_STATEMENTS = [
    {
        "claim": "Hemorrhage causes 80% of preventable combat deaths, most "
                 "of which are survivable with timely intervention.",
        "source": "Joint Trauma System CPG, Battlefield Trauma Care, 2021",
    },
    {
        "claim": "Rural Americans wait an average of 23 minutes for ambulance "
                 "arrival, nearly twice the urban median.",
        "source": "NHTSA Rural EMS Service Profile, 2023",
    },
    {
        "claim": "Maritime medical evacuations cost an average of $200,000 USD "
                 "and require 4–12 hours before specialist contact is possible.",
        "source": "International Maritime Medical Service Reports, 2022",
    },
    {
        "claim": "In federal correctional facilities, inadequate medical care "
                 "is a documented contributing factor in 1 in 3 inmate deaths.",
        "source": "Bureau of Justice Statistics, Mortality in State and "
                  "Federal Prisons, 2019",
    },
    {
        "claim": "90% of healthcare workers in low-resource settings work "
                 "without specialist consultation when needed.",
        "source": "WHO Global Strategy on Human Resources for Health, 2016",
    },
]


VIGNETTE = {
    "title": "Who AEGIS Is For",
    "body": (
        "Maria Chen is an EMT in rural Colorado, 70 minutes from the nearest "
        "Level III trauma center. Last winter she responded to a snowmobile "
        "crash in a canyon with no cellular coverage. Her patient had a "
        "suspected pelvic fracture and she had thirty minutes of training on "
        "that specific injury, two years earlier. She made the call alone. "
        "She did okay. She still thinks about whether she got it right."
    ),
    "closer": "AEGIS exists for the next time Maria takes that call.",
    "honesty_note": (
        "Composite vignette drawn from documented patterns of rural EMS "
        "practice. Identifying details are illustrative."
    ),
}


DEPLOYMENT_MODEL = {
    "title": "Deployment Model",
    "body": (
        "AEGIS is professional medical equipment, not a consumer product.\n\n"
        "The buyer is the institution that employs trained medical operators: "
        "EMS agencies, military medical units, maritime operators, "
        "correctional healthcare providers, indigenous and rural health "
        "systems, disaster response organizations, humanitarian aid "
        "organizations.\n\n"
        "The user is the trained operator: paramedic, combat medic, ship's "
        "corpsman, correctional nurse, community health worker, field "
        "clinician.\n\n"
        "The hardware sits where the work happens: in the ambulance bay, "
        "the medic's kit, the ship's sick bay, the rural clinic. The operator "
        "interacts through any local display device — tablet, phone, "
        "ruggedized handheld — over a private link with no internet "
        "dependency.\n\n"
        "Reference target: ASUS Ascent GX10 ($3–4K) or equivalent compact AI "
        "workstation. The same architecture runs on M-series Macs, NVIDIA "
        "Jetson boards, and high-end mobile devices. Hardware in this class "
        "follows the trajectory of consumer compute: capability doubles "
        "roughly every 18–24 months, price stays flat or declines."
    ),
    "closer": "Per-encounter cost across a typical service lifespan: cents.",
}


COST_COMPARISON = [
    {"item": "DEFIBRILLATOR",          "cost": "$1,500 – $3,000",  "highlight": False},
    {"item": "PORTABLE ULTRASOUND",    "cost": "$5,000 – $30,000", "highlight": False},
    {"item": "TELEHEALTH CART",        "cost": "$15,000 – $30,000", "highlight": False},
    {"item": "EVAC HELICOPTER FLIGHT", "cost": "$25,000 – $50,000", "highlight": False},
    {"item": "ICU BED-DAY",            "cost": "$4,000 – $10,000",  "highlight": False},
    {"item": "AEGIS UNIT",             "cost": "$3,000 – $4,000",   "highlight": True},
]


FAILURE_MODES = [
    {"failure": "Cloud unavailability",
     "mitigation": "Runs entirely on-device. No external dependency at runtime."},
    {"failure": "Specialist unreachability",
     "mitigation": "Local corpus-grounded reference with cited answers."},
    {"failure": "Documentation loss",
     "mitigation": "Encrypted local record, persisted across sessions."},
    {"failure": "Documentation tampering",
     "mitigation": "SHA-256 integrity chain, verifiable on demand."},
    {"failure": "Voice transcription errors",
     "mitigation": "Extraction receipts let the operator verify each fact "
                   "against the verbatim transcript span that supported it."},
    {"failure": "Model hallucination",
     "mitigation": "Refusal shape when retrieved corpus does not support an "
                   "answer. Every clinical assertion cites a real corpus chunk."},
    {"failure": "Citation fabrication",
     "mitigation": "Every citation resolves to a real source PDF in the "
                   "Reference folder, viewable at the cited page."},
    {"failure": "Handoff integrity",
     "mitigation": "Ed25519-signed packets with a standalone verification "
                   "script. Tampering detected by any third party."},
    {"failure": "Demo equipment failure",
     "mitigation": "Pre-recorded fallback voice clips routed through the "
                   "live transcription pipeline. The demo continues if the "
                   "mic fails."},
    {"failure": "Operator data exposure",
     "mitigation": "No keys ever leave the device. No data ever leaves the "
                   "device without explicit, signed handoff to a defined "
                   "recipient."},
]


INSTITUTIONAL_BUYERS = [
    {"category": "Rural EMS Agencies",
     "description": "Approximately 12,000 US agencies, of which 60% serve "
                    "rural populations. Capital expenditure cycles every "
                    "7–10 years."},
    {"category": "Military Medical Units",
     "description": "Department of Defense procurement, including SBIR/STTR "
                    "programs specifically funding austere-environment "
                    "medical AI."},
    {"category": "Maritime Operators",
     "description": "Commercial shipping, offshore platforms, cruise lines, "
                    "Coast Guard. Existing investment in onboard medical "
                    "equipment is established."},
    {"category": "Correctional Healthcare Contractors",
     "description": "Wellpath, Corizon, and equivalent contractors operate "
                    "under constitutional adequacy requirements with "
                    "air-gapped network constraints."},
    {"category": "Indigenous and Rural Health Systems",
     "description": "Indian Health Service, tribal health authorities, "
                    "federally qualified health centers serving low-resource "
                    "populations."},
    {"category": "Humanitarian Organizations",
     "description": "Médecins Sans Frontières, ICRC, UN agencies. "
                    "Established procurement budgets for field medical "
                    "equipment in environments with limited or hostile "
                    "network access."},
]


def as_dict() -> dict:
    return {
        "product_positioning": PRODUCT_POSITIONING,
        "gap_statements": GAP_STATEMENTS,
        "vignette": VIGNETTE,
        "deployment_model": DEPLOYMENT_MODEL,
        "cost_comparison": COST_COMPARISON,
        "failure_modes": FAILURE_MODES,
        "institutional_buyers": INSTITUTIONAL_BUYERS,
    }
