"""
V6 — Handoff document generation.

Produces a single comprehensive PDF (no zip wrapper) suitable for
handing the receiving clinician at patient transfer. The document
walks the encounter event chain and surfaces every clinically
relevant fact: the situation as the operator described it, the
LLM-driven initial brief, the procedural steps performed (with
completion times and citations), the latest vitals, the source
citations with supporting quotes, and a tamper-evident footer.

The signature/verifier scaffolding from V4 (encounter.json,
encounter.json.sig, device.pub, verify_handoff.py) has been
collapsed: the SHA-256 of the canonical encounter JSON plus the
Ed25519 signature are printed in the PDF footer for chain-of-custody
without requiring the receiver to run a separate script.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import json
from pathlib import Path
from typing import Optional

from . import config, crypto_ed25519, records, scenarios

ROOT = config.BASE_DIR


# ---------------------------------------------------------------------
# Encounter walk — pull every clinically relevant fact out of the event
# chain so the PDF is comprehensive even for LLM-driven encounters that
# don't have an `extraction` or `after_action_review` payload.
# ---------------------------------------------------------------------
LLM_SCENARIO_ID = "__llm__"


def _fmt_offset(ms: int) -> str:
    s = max(0, int((ms or 0) // 1000))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _walk_encounter(encounter_id: str) -> dict:
    """Extract a clinically structured view of the encounter from its
    persisted events. Works for both LLM-driven and legacy scenarios."""
    rec = records.get_encounter(encounter_id) or {}
    events = rec.get("events") or []
    sid = rec.get("scenario_id", "")
    sc = scenarios.get(sid) if sid and sid != LLM_SCENARIO_ID else None

    situation = ""
    title = sc.get("name", "") if sc else ""
    steps: list[dict] = []
    citations: list[dict] = []
    brief_text = ""
    chat_turns: list[dict] = []
    completions: dict[str, dict] = {}
    operator_phrases: list[dict] = []

    for ev in events:
        et = ev.get("event_type")
        payload = ev.get("payload") or {}
        t_off = int(ev.get("t_offset_ms") or 0)

        if et == "operator_situation_set":
            txt = (payload.get("text") or "").strip()
            if txt:
                situation = txt
        elif et == "encounter_steps_set":
            if payload.get("title"):
                title = payload["title"]
            if isinstance(payload.get("steps"), list):
                steps = payload["steps"]
            if isinstance(payload.get("citations"), list):
                citations = payload["citations"]
        elif et == "chat_turn":
            q = (payload.get("question") or "").strip()
            r = (payload.get("reply") or "").strip()
            chat_turns.append({"q": q, "r": r,
                                "t": _fmt_offset(t_off)})
            if not brief_text and "(initial brief from situation intake)" in q:
                brief_text = r
        elif et == "step_completed":
            sid_done = payload.get("step_id") or ""
            completions[sid_done] = {
                "t": _fmt_offset(t_off),
                "decision": payload.get("decision"),
                "complete": bool(payload.get("complete")),
                "title": payload.get("title", ""),
            }
        elif et == "operator_phrase":
            txt = (payload.get("text") or "").strip()
            if txt:
                operator_phrases.append({"t": _fmt_offset(t_off), "text": txt})

    # Legacy scenarios store steps in the static graph rather than on
    # the encounter — fall back to that so the PDF still has content.
    if not steps and sc:
        from . import procedural_steps as _ps
        steps = _ps.graph_for(sid) or []
        if not title:
            title = sc.get("name", "")

    started = rec.get("started_at")
    ended = rec.get("ended_at")
    if started:
        try:
            t0 = datetime.datetime.fromisoformat(started)
            now = datetime.datetime.now(t0.tzinfo or datetime.timezone.utc)
            elapsed = int((now - t0).total_seconds() * 1000)
        except Exception:
            elapsed = 0
    else:
        elapsed = 0

    return {
        "encounter_id": rec.get("id", encounter_id),
        "scenario_id": sid,
        "title": title or "Encounter",
        "patient_label": rec.get("patient_label", "") or "PT-—",
        "started_at": started,
        "ended_at": ended,
        "elapsed_ms": elapsed,
        "situation": situation,
        "brief_text": brief_text,
        "steps": steps,
        "citations": citations,
        "chat_turns": chat_turns,
        "completions": completions,
        "operator_phrases": operator_phrases,
        "events": events,
    }


def _canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------
# Comprehensive transfer PDF
# ---------------------------------------------------------------------
def _render_transfer_pdf(walk: dict, integrity_hash: str,
                         signature_hex: str, pub_fp: str) -> bytes:
    """Render the patient-transfer PDF. Pulls every clinically relevant
    fact from the walked encounter view. Single self-contained document
    — the receiving clinician needs only this file."""
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        KeepTogether, PageBreak,
    )
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        title=f"AEGIS Patient Transfer — {walk['encounter_id']}",
        author="AEGIS",
    )

    base = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=base["Heading1"], fontName="Helvetica-Bold",
                        fontSize=18, leading=22, spaceAfter=2,
                        textColor=colors.HexColor("#1a1a1a"))
    metaStyle = ParagraphStyle("meta", parent=base["BodyText"],
                               fontName="Courier", fontSize=8.5, leading=12,
                               textColor=colors.HexColor("#555"), spaceAfter=14)
    h2 = ParagraphStyle("h2", parent=base["Heading2"],
                        fontName="Helvetica-Bold", fontSize=11.5, leading=14,
                        textColor=colors.HexColor("#a04500"),
                        spaceBefore=14, spaceAfter=6,
                        borderPadding=0)
    bodyStyle = ParagraphStyle("body", parent=base["BodyText"],
                               fontName="Helvetica", fontSize=10, leading=14,
                               alignment=TA_LEFT)
    bodyEm = ParagraphStyle("body-em", parent=bodyStyle,
                            fontName="Helvetica-Oblique",
                            textColor=colors.HexColor("#444"))
    bodySmall = ParagraphStyle("body-sm", parent=bodyStyle,
                               fontSize=9, leading=12)
    mono = ParagraphStyle("mono", parent=bodyStyle, fontName="Courier",
                          fontSize=8.5, leading=12)
    citationQuote = ParagraphStyle(
        "cite-q", parent=bodyStyle, fontName="Helvetica-Oblique",
        fontSize=9, leading=12.5, leftIndent=12,
        textColor=colors.HexColor("#444"),
    )
    sigFooter = ParagraphStyle(
        "sig", parent=bodyStyle, fontName="Courier", fontSize=7.5,
        leading=10.5, textColor=colors.HexColor("#666"), spaceBefore=20,
    )

    def _esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story: list = []

    # ---- HEADER -------------------------------------------------------
    story.append(Paragraph("AEGIS PATIENT TRANSFER", h1))
    gen_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC")
    elapsed_str = _fmt_offset(walk["elapsed_ms"])
    story.append(Paragraph(
        f"{_esc(walk['encounter_id'])} &nbsp;·&nbsp; generated {gen_at} "
        f"&nbsp;·&nbsp; mission elapsed T+{elapsed_str}",
        metaStyle,
    ))

    # ---- IDENTITY TABLE ----------------------------------------------
    ident_rows = [
        ["Encounter Title",   walk["title"] or "—"],
        ["Patient Label",     walk["patient_label"] or "—"],
        ["Encounter Started", (walk["started_at"] or "—").replace("T", " ")[:19]],
        ["Steps Performed",
         f"{sum(1 for c in walk['completions'].values() if not c.get('complete'))} "
         f"of {len(walk['steps'])}"
         if walk["steps"] else "—"],
    ]
    ident = Table(ident_rows, colWidths=[1.6 * inch, 5.4 * inch], hAlign="LEFT")
    ident.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#ddd")),
    ]))
    story.append(ident)

    # ---- SITUATION ----------------------------------------------------
    story.append(Paragraph("Situation as Reported", h2))
    if walk["situation"]:
        story.append(Paragraph(_esc(walk["situation"]), bodyEm))
    else:
        story.append(Paragraph("No situation captured.", bodySmall))

    # ---- INITIAL BRIEF ------------------------------------------------
    if walk["brief_text"]:
        story.append(Paragraph("Initial Assessment (Brief)", h2))
        for line in walk["brief_text"].splitlines():
            line = line.strip()
            if not line:
                continue
            # Strip [CITATION_ID] markers in the readable body — they
            # appear cleanly in the Citations section below.
            import re as _re
            line_clean = _re.sub(r"\[[A-Z][A-Z0-9_-]{2,}\]", "", line)
            line_clean = _re.sub(r"\s+", " ", line_clean).strip()
            story.append(Paragraph(_esc(line_clean), bodyStyle))

    # ---- PROCEDURAL STEPS --------------------------------------------
    if walk["steps"]:
        story.append(Paragraph("Procedural Steps Performed", h2))

        rows = [[
            Paragraph("<b>#</b>", bodySmall),
            Paragraph("<b>Step</b>", bodySmall),
            Paragraph("<b>Status</b>", bodySmall),
            Paragraph("<b>Time</b>", bodySmall),
        ]]
        for i, s in enumerate(walk["steps"], 1):
            sid_local = s.get("id", "")
            comp = walk["completions"].get(sid_local)
            status = "✓ Complete" if comp else "Not reached"
            t_str = comp.get("t", "—") if comp else "—"
            title = s.get("title", "—")
            rows.append([
                Paragraph(str(i), bodySmall),
                Paragraph(_esc(title), bodySmall),
                Paragraph(status, bodySmall),
                Paragraph(t_str, mono),
            ])

        steps_table = Table(rows, colWidths=[
            0.35 * inch, 3.3 * inch, 1.0 * inch, 0.95 * inch,
        ], hAlign="LEFT")
        steps_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3eee5")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#a04500")),
            ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#ececec")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(steps_table)

        # Detail blocks for completed steps
        for i, s in enumerate(walk["steps"], 1):
            sid_local = s.get("id", "")
            comp = walk["completions"].get(sid_local)
            if not comp:
                continue
            instr = (s.get("instruction") or "").strip()
            why = (s.get("why_matters") or "").strip()
            block = []
            block.append(Paragraph(
                f"<b>{i}. {_esc(s.get('title','—'))}</b> "
                f"<font color='#888' size='8'>· at T+{comp.get('t','—')}</font>",
                bodyStyle,
            ))
            if instr:
                # Strip [CITATION_ID] markers from the readable instruction.
                import re as _re
                instr_clean = _re.sub(r"\s*\[[A-Z][A-Z0-9_-]{2,}\]\s*",
                                      " ", instr).strip()
                block.append(Paragraph(_esc(instr_clean), bodySmall))
            if why:
                import re as _re
                why_clean = _re.sub(r"\s*\[[A-Z][A-Z0-9_-]{2,}\]\s*",
                                    " ", why).strip()
                block.append(Paragraph(
                    f"<i>Clinical context:</i> {_esc(why_clean)}",
                    citationQuote,
                ))
            block.append(Spacer(1, 6))
            story.append(KeepTogether(block))

    # ---- LATEST VITALS / OPERATOR PHRASES (free-form context) -------
    if walk["operator_phrases"]:
        story.append(Paragraph("Operator Notes", h2))
        for ph in walk["operator_phrases"][-8:]:
            story.append(Paragraph(
                f"<font face='Courier' size='8' color='#888'>"
                f"T+{ph['t']}</font> &nbsp; {_esc(ph['text'])}",
                bodySmall,
            ))

    # ---- CITATIONS ----------------------------------------------------
    if walk["citations"]:
        story.append(Paragraph("Source Citations", h2))
        for c in walk["citations"]:
            cid = c.get("citation_id") or "—"
            src = c.get("source") or ""
            page = c.get("page")
            section = c.get("section") or ""
            quote = (c.get("supporting_quote") or "").strip()

            head = f"<b>{_esc(cid)}</b>"
            tail_bits = [b for b in [src, f"page {page}" if page else "",
                                       section] if b]
            if tail_bits:
                head += f" &nbsp; <font color='#666' size='9'>" \
                        f"{_esc(' · '.join(map(str, tail_bits)))}</font>"
            story.append(Paragraph(head, bodyStyle))
            if quote:
                story.append(Paragraph(f"&ldquo;{_esc(quote)}&rdquo;",
                                        citationQuote))
            story.append(Spacer(1, 4))

    # ---- INTEGRITY FOOTER --------------------------------------------
    story.append(Spacer(1, 0.15 * inch))
    short_hash = (integrity_hash or "")
    short_sig = (signature_hex or "")
    story.append(Paragraph(
        f"Integrity (SHA-256): {short_hash}<br/>"
        f"Ed25519 signature: {short_sig}<br/>"
        f"Device key fingerprint: {pub_fp}<br/>"
        f"This document was generated locally and never transmitted to "
        f"a remote service. Encounter ID and integrity hash uniquely "
        f"identify this transfer.",
        sigFooter,
    ))

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------
def build_transfer_pdf(encounter_id: str) -> tuple[bytes, dict]:
    """V6 — Build the single-PDF patient transfer document.

    Returns (pdf_bytes, manifest). The manifest carries the same chain-
    of-custody metadata the previous .zip flow exposed (filename,
    integrity_hash, signature_hex, device_pub_fingerprint, size_bytes)
    so existing callers can keep recording it on the encounter record.
    """
    walk = _walk_encounter(encounter_id)

    # Sign a canonical projection of the walk for chain-of-custody.
    canonical = _canonical_bytes({
        "schema": "aegis-v6-transfer",
        "encounter_id": walk["encounter_id"],
        "scenario_id": walk["scenario_id"],
        "title": walk["title"],
        "patient_label": walk["patient_label"],
        "started_at": walk["started_at"],
        "ended_at": walk["ended_at"],
        "situation": walk["situation"],
        "steps": walk["steps"],
        "citations": walk["citations"],
        "events": walk["events"],
    })
    integrity_hash = hashlib.sha256(canonical).hexdigest()

    crypto_ed25519.init()
    signature = crypto_ed25519.sign_bundle(canonical)
    sig_hex = signature.hex()
    pub_fp = crypto_ed25519.public_fingerprint()

    pdf_bytes = _render_transfer_pdf(walk, integrity_hash, sig_hex, pub_fp)

    manifest = {
        "filename": f"aegis-transfer-{encounter_id}.pdf",
        "size_bytes": len(pdf_bytes),
        "integrity_hash": integrity_hash,
        "signature_hex": sig_hex,
        "device_pub_fingerprint": pub_fp,
        "events": len(walk.get("events", [])),
    }
    return pdf_bytes, manifest


# Backwards-compatible alias so any existing callers (tests, other
# routes) keep working. Returns the same shape as before but the bytes
# are now a PDF rather than a zip.
def build_packet(encounter_id: str,
                 extraction: Optional[dict] = None,
                 aar: Optional[dict] = None) -> tuple[bytes, dict]:
    """V6 — Returns (pdf_bytes, manifest). The extraction / aar
    parameters are accepted for API compatibility but no longer used:
    the PDF is built directly from the encounter event chain."""
    return build_transfer_pdf(encounter_id)
