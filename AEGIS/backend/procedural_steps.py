"""
V5 — Procedural step graphs for the cockpit's CURRENT STEP card.

Each scenario has an ordered list of steps. Each step has:
  - id              : stable identifier (string)
  - title           : the procedural title shown in the CURRENT STEP card
                      (UPPERCASE, 1-3 words)
  - icon            : monoline icon name (rendered client-side as SVG)
  - instruction     : 1-3 sentence operator instruction (Fraunces body text)
  - checklist_text  : the corresponding CHECKLIST row text (right column)
  - why_matters     : 2-3 sentence clinical context (WHY THIS MATTERS panel)
  - question        : optional binary decision (YES/NO) at end of step
                      {"text": "...", "yes_routes_to": <step_id|"complete">,
                                       "no_routes_to":  <step_id|"complete">}
  - jump_to         : list of alternative step IDs the operator can jump to.
                      Each jump card shows {step.title, step.icon,
                                             step.instruction[:70]}.

The operator advances through steps via:
  POST /api/encounter/{id}/advance-step  body: {step_id, decision?}
where `decision` is "yes" | "no" | None. If None, advance to the next
step in the ordered list. If `decision` is set, route via question rules.

These are reference fixtures sufficient for the demo. Real protocol
content remains the responsibility of the corpus + LLM citation flow.
"""

from __future__ import annotations
from typing import Optional


# ---- Step graphs -----------------------------------------------------

_BATTLEFIELD = [
    {
        "id": "control_bleeding",
        "title": "CONTROL BLEEDING",
        "icon": "crosshair",
        "instruction": "Apply CAT tourniquet 5–7 cm above the wound. Tighten until bleeding stops.",
        "checklist_text": "Apply CAT tourniquet 5–7 cm proximal to wound, high and tight.",
        "why_matters": "Uncontrolled bleeding is the most immediate threat. Controlling it improves survival chances. The femoral arterial bleed exsanguinates in minutes if not occluded.",
        "question": {
            "text": "Is bleeding still visible?",
            "yes_routes_to": "second_tourniquet",
            "no_routes_to": "verify_cessation",
        },
        "jump_to": ["check_circulation", "evac_prep"],
    },
    {
        "id": "second_tourniquet",
        "title": "SECOND TOURNIQUET",
        "icon": "crosshair",
        "instruction": "Place a second tourniquet directly proximal to the first. Tighten until bleeding stops.",
        "checklist_text": "Place a second CAT tourniquet directly proximal to the first.",
        "why_matters": "If the first tourniquet has not occluded arterial flow, a second device side-by-side is the protocol-correct response before considering junctional devices.",
        "question": None,
        "jump_to": ["verify_cessation", "evac_prep"],
    },
    {
        "id": "verify_cessation",
        "title": "VERIFY CESSATION",
        "icon": "pulse",
        "instruction": "Confirm distal pulse is absent and visible bleeding has stopped. Note the time.",
        "checklist_text": "Verify hemorrhage cessation — confirm absence of distal pulse and bleeding.",
        "why_matters": "A correctly applied tourniquet stops both venous and arterial flow. Persistent distal pulse means the device is not tight enough.",
        "question": None,
        "jump_to": ["mark_tourniquet", "check_circulation"],
    },
    {
        "id": "mark_tourniquet",
        "title": "MARK TOURNIQUET",
        "icon": "tag",
        "instruction": "Write the tourniquet application time on the casualty card. Mark TQ and the time on the casualty's forehead.",
        "checklist_text": "Annotate tourniquet time on casualty card and write TQ on forehead.",
        "why_matters": "Downstream providers need the application time to make limb-salvage decisions. Visible marking on the forehead is doctrine when the casualty card may be lost.",
        "question": None,
        "jump_to": ["check_circulation", "evac_prep"],
    },
    {
        "id": "check_circulation",
        "title": "CHECK CIRCULATION",
        "icon": "pulse",
        "instruction": "Assess radial pulse and capillary refill. If absent, treat for shock and elevate lower extremities if no spinal concern.",
        "checklist_text": "Reassess circulation — radial pulse, capillary refill, skin color.",
        "why_matters": "Class III/IV hemorrhagic shock follows arterial loss even after the bleed is stopped. Early recognition drives fluid and TXA decisions.",
        "question": None,
        "jump_to": ["evac_prep"],
    },
    {
        "id": "evac_prep",
        "title": "PREPARE EVACUATION",
        "icon": "ambulance",
        "instruction": "Establish IV access (18g antecubital). Prepare TXA per protocol. Stage casualty for litter movement.",
        "checklist_text": "Initiate IV access, 18g antecubital, prepare TXA per protocol.",
        "why_matters": "Definitive surgical care is the disposition. TXA within the first hour reduces mortality. Vascular access prepared now means no delay at the casualty collection point.",
        "question": {
            "text": "Has evacuation been requested?",
            "yes_routes_to": "complete",
            "no_routes_to": "evac_prep",
        },
        "jump_to": [],
    },
]


_MARITIME = [
    {
        "id": "scene_safety",
        "title": "SCENE SAFETY",
        "icon": "shield",
        "instruction": "Confirm scene is safe. Move casualty to a dry, non-conductive surface clear of standing water.",
        "checklist_text": "Confirm scene safety; move casualty to dry, non-conductive surface.",
        "why_matters": "AED delivery on a wet conductive surface risks shocking the rescuer. Dry transfer is the prerequisite to every downstream action.",
        "question": None,
        "jump_to": ["start_compressions"],
    },
    {
        "id": "start_compressions",
        "title": "START COMPRESSIONS",
        "icon": "pulse",
        "instruction": "Begin compressions at 100–120/min, depth 5–6 cm. Allow full chest recoil between compressions.",
        "checklist_text": "Initiate compressions at 100–120/min, depth 5–6 cm, full recoil.",
        "why_matters": "High-quality compressions are the single intervention with the strongest mortality benefit in cardiac arrest. Rate, depth, and recoil all matter.",
        "question": None,
        "jump_to": ["rescue_breaths", "apply_aed"],
    },
    {
        "id": "rescue_breaths",
        "title": "RESCUE BREATHS",
        "icon": "breath",
        "instruction": "After every 30 compressions deliver two rescue breaths. Watch for chest rise. Resume compressions immediately.",
        "checklist_text": "Deliver two rescue breaths after every 30 compressions; observe chest rise.",
        "why_matters": "Submersion arrest is hypoxic in origin. Ventilation is more important here than in primary cardiac arrest — visible chest rise confirms airway patency.",
        "question": None,
        "jump_to": ["apply_aed"],
    },
    {
        "id": "apply_aed",
        "title": "APPLY AED",
        "icon": "bolt",
        "instruction": "Place AED pads. Pause compressions only for rhythm analysis and shock delivery.",
        "checklist_text": "Apply AED pads; pause only for rhythm analysis and shock delivery.",
        "why_matters": "Defibrillation is time-critical. Each minute of delay reduces survival by ~10%. The AED is the only intervention that converts shockable rhythms.",
        "question": {
            "text": "Did the AED advise a shock?",
            "yes_routes_to": "iv_access",
            "no_routes_to": "iv_access",
        },
        "jump_to": ["iv_access"],
    },
    {
        "id": "iv_access",
        "title": "IV ACCESS",
        "icon": "drop",
        "instruction": "Establish IV or IO access. Prepare epinephrine 1 mg every 3–5 minutes per ACLS.",
        "checklist_text": "Establish IV/IO access; prepare epinephrine 1 mg every 3–5 minutes.",
        "why_matters": "IO is acceptable when IV access fails or is delayed. Epinephrine timing is measured from the first dose, not from arrest onset.",
        "question": None,
        "jump_to": ["advanced_airway"],
    },
    {
        "id": "advanced_airway",
        "title": "ADVANCED AIRWAY",
        "icon": "breath",
        "instruction": "After the second rhythm check, place an advanced airway. Switch to continuous compressions with asynchronous ventilation at 10/min.",
        "checklist_text": "Continue cycles; consider advanced airway after second rhythm check.",
        "why_matters": "An advanced airway eliminates the compression pause for ventilation, improving compression fraction. The 30:2 → continuous transition is the doctrine signal.",
        "question": {
            "text": "Has ROSC been achieved?",
            "yes_routes_to": "complete",
            "no_routes_to": "advanced_airway",
        },
        "jump_to": [],
    },
]


_DISASTER = [
    {
        "id": "confirm_weight",
        "title": "CONFIRM WEIGHT",
        "icon": "ruler",
        "instruction": "Confirm patient weight by length-based tape (Broselow). Document on the triage tag.",
        "checklist_text": "Confirm weight by length-based tape; document on triage tag.",
        "why_matters": "Pediatric dosing is weight-based. A length-based tape is more accurate than parental estimate or visual approximation under field conditions.",
        "question": None,
        "jump_to": ["administer_paracetamol"],
    },
    {
        "id": "administer_paracetamol",
        "title": "ADMINISTER PARACETAMOL",
        "icon": "pill",
        "instruction": "Give paracetamol 15 mg/kg orally. Calculated dose for 16 kg is 240 mg. Verify dose with the operator before administration.",
        "checklist_text": "Administer paracetamol 15 mg/kg PO — calculated dose 240 mg.",
        "why_matters": "Paracetamol reduces fever-driven metabolic demand and improves the child's tolerance of oral rehydration. Dose ceiling is 4 g/24h or 75 mg/kg/24h.",
        "question": None,
        "jump_to": ["start_ors"],
    },
    {
        "id": "start_ors",
        "title": "START ORS",
        "icon": "drop",
        "instruction": "Begin oral rehydration salts at 75 ml/kg over 4 hours. Total volume planned is 1.2 L.",
        "checklist_text": "Initiate ORS at 75 ml/kg over 4 hours — total 1.2 L planned.",
        "why_matters": "Mild-to-moderate dehydration is treated orally first. ORS rehydrates with less risk of fluid overload than IV in pediatric patients with intact gag reflex.",
        "question": {
            "text": "Is the child tolerating oral fluids?",
            "yes_routes_to": "reassess",
            "no_routes_to": "iv_fluids",
        },
        "jump_to": ["iv_fluids", "reassess"],
    },
    {
        "id": "iv_fluids",
        "title": "ESCALATE TO IV",
        "icon": "drop",
        "instruction": "Establish IV access. Begin isotonic bolus 20 ml/kg over 15–30 minutes. Reassess after each bolus.",
        "checklist_text": "Escalate to IV fluids — 20 ml/kg isotonic bolus, reassess.",
        "why_matters": "Persistent vomiting or capillary refill > 4 seconds indicates ORS is insufficient. IV fluids restore intravascular volume rapidly.",
        "question": None,
        "jump_to": ["reassess"],
    },
    {
        "id": "reassess",
        "title": "REASSESS",
        "icon": "pulse",
        "instruction": "At 60 minutes, reassess hydration status, mental status, and temperature. Document in the encounter record.",
        "checklist_text": "Reassess hydration, mental status, and temperature at 60-minute interval.",
        "why_matters": "Sixty minutes is the minimum window to see paracetamol fever response and ORS hydration response. Earlier reassessment is unreliable.",
        "question": None,
        "jump_to": ["physician_review"],
    },
    {
        "id": "physician_review",
        "title": "QUEUE FOR REVIEW",
        "icon": "tag",
        "instruction": "Document the encounter and queue the patient for physician review at the next rotation.",
        "checklist_text": "Document and queue for physician review at next rotation.",
        "why_matters": "Pediatric pyrexia in disaster settings has a wide differential. Physician review is the disposition gate before discharge or escalation.",
        "question": {
            "text": "Has the patient been queued for review?",
            "yes_routes_to": "complete",
            "no_routes_to": "physician_review",
        },
        "jump_to": [],
    },
]


_GRAPHS: dict[str, list[dict]] = {
    "battlefield": _BATTLEFIELD,
    "maritime": _MARITIME,
    "disaster": _DISASTER,
}


# ---- Public API ------------------------------------------------------

def graph_for(scenario_id: str) -> Optional[list[dict]]:
    return _GRAPHS.get(scenario_id)


def step_for(scenario_id: str, step_id: str) -> Optional[dict]:
    g = _GRAPHS.get(scenario_id) or []
    for s in g:
        if s["id"] == step_id:
            return s
    return None


def jump_cards(scenario_id: str, step: dict) -> list[dict]:
    """Resolve the JUMP TO STEP card list for a step into renderable cards."""
    out = []
    for sid in step.get("jump_to") or []:
        s = step_for(scenario_id, sid)
        if s:
            out.append({
                "id": s["id"],
                "title": s["title"],
                "icon": s["icon"],
                "description": s["instruction"][:80],
            })
    return out


def render_step(scenario_id: str, step: dict, total: int, idx: int) -> dict:
    return {
        "id": step["id"],
        "title": step["title"],
        "icon": step["icon"],
        "instruction": step["instruction"],
        "checklist_text": step["checklist_text"],
        "why_matters": step["why_matters"],
        "question": step.get("question"),
        "jump_to": jump_cards(scenario_id, step),
        "step_index": idx,
        "step_count": total,
    }


def initial_step(scenario_id: str) -> Optional[dict]:
    g = _GRAPHS.get(scenario_id)
    if not g:
        return None
    return render_step(scenario_id, g[0], len(g), 1)


def advance(scenario_id: str, current_id: str,
            decision: Optional[str] = None) -> Optional[dict]:
    """Compute the next step rendering. Returns:
       - the next step (render_step shape) if a next step exists
       - {"complete": True, "step_index": N, "step_count": N} when finished
       - None if scenario or current step are unknown
    """
    g = _GRAPHS.get(scenario_id) or []
    if not g:
        return None

    cur = step_for(scenario_id, current_id)
    if cur is None:
        return None

    # Question-driven routing first
    q = cur.get("question")
    if q and decision in ("yes", "no"):
        target = q["yes_routes_to"] if decision == "yes" else q["no_routes_to"]
        if target == "complete":
            return {"complete": True,
                    "step_index": len(g), "step_count": len(g)}
        nxt = step_for(scenario_id, target)
        if nxt:
            idx = next((i for i, s in enumerate(g) if s["id"] == nxt["id"]), 0)
            return render_step(scenario_id, nxt, len(g), idx + 1)

    # Otherwise advance linearly
    idx = next((i for i, s in enumerate(g) if s["id"] == current_id), -1)
    if idx < 0:
        return None
    if idx + 1 >= len(g):
        return {"complete": True,
                "step_index": len(g), "step_count": len(g)}
    nxt = g[idx + 1]
    return render_step(scenario_id, nxt, len(g), idx + 2)


# ---- V6 — Step helpers operating on an arbitrary step list ----------
# Used by LLM-driven encounters where steps are stored on the encounter
# record rather than in the hardcoded _GRAPHS dict. Mirror the public
# shape of step_for / render_step / initial_step / advance.

def step_in(steps: list[dict], step_id: str) -> Optional[dict]:
    for s in steps or []:
        if s.get("id") == step_id:
            return s
    return None


def _jump_cards_in(steps: list[dict], step: dict) -> list[dict]:
    out = []
    for sid in step.get("jump_to") or []:
        s = step_in(steps, sid)
        if s:
            out.append({
                "id": s["id"],
                "title": s["title"],
                "icon": s.get("icon", "pulse"),
                "description": (s.get("instruction") or "")[:80],
            })
    return out


def render_step_in(steps: list[dict], step: dict, idx: int) -> dict:
    return {
        "id": step["id"],
        "title": step["title"],
        "icon": step.get("icon", "pulse"),
        "instruction": step.get("instruction", ""),
        "checklist_text": step.get("checklist_text", step.get("title", "")),
        "why_matters": step.get("why_matters", ""),
        # V6 — pass the per-step affirmation through so MARK STEP COMPLETE
        # shows the LLM-supplied "I have done X" line instead of falling
        # back to the legacy hardcoded substring lookup in the frontend.
        "affirmation": step.get("affirmation", ""),
        "question": step.get("question"),
        "jump_to": _jump_cards_in(steps, step),
        "step_index": idx,
        "step_count": len(steps),
    }


def initial_step_in(steps: list[dict]) -> Optional[dict]:
    if not steps:
        return None
    return render_step_in(steps, steps[0], 1)


def advance_in(steps: list[dict], current_id: str,
               decision: Optional[str] = None) -> Optional[dict]:
    if not steps:
        return None
    cur = step_in(steps, current_id)
    if cur is None:
        return None
    q = cur.get("question")
    if q and decision in ("yes", "no"):
        target = q.get("yes_routes_to") if decision == "yes" \
            else q.get("no_routes_to")
        if target == "complete":
            return {"complete": True,
                    "step_index": len(steps), "step_count": len(steps)}
        nxt = step_in(steps, target)
        if nxt:
            idx = next((i for i, s in enumerate(steps)
                        if s["id"] == nxt["id"]), 0)
            return render_step_in(steps, nxt, idx + 1)
    idx = next((i for i, s in enumerate(steps)
                if s["id"] == current_id), -1)
    if idx < 0:
        return None
    if idx + 1 >= len(steps):
        return {"complete": True,
                "step_index": len(steps), "step_count": len(steps)}
    return render_step_in(steps, steps[idx + 1], idx + 2)


def context_log_seed(scenario_id: str) -> list[dict]:
    """Seed entries the cockpit shows before any voice extraction has run.
    These are short verbatim phrases scaled to the operator's likely first
    minutes. Real entries flow from the extraction pipeline."""
    if scenario_id == "battlefield":
        return [
            {"t": "00:00:08", "text": "Patient took a round to the left thigh."},
            {"t": "00:00:14", "text": "Bleed is pumping — arterial."},
            {"t": "00:00:21", "text": "Patient is conscious and responsive."},
        ]
    if scenario_id == "maritime":
        return [
            {"t": "00:00:06", "text": "Pulled a diver. No pulse, no breath."},
            {"t": "00:00:12", "text": "Surface time under three minutes."},
        ]
    if scenario_id == "disaster":
        return [
            {"t": "00:00:09", "text": "Four-year-old, fever climbing for a day and a half."},
            {"t": "00:00:15", "text": "She's listless, not eating."},
        ]
    return []
