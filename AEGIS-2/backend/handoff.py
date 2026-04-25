"""
V4 — Handoff packet generation.

Produces a signed .zip containing:
  - encounter.json          (canonical encounter record)
  - encounter.json.sig      (Ed25519 signature, hex)
  - summary.pdf             (one-page printable summary, reportlab)
  - device.pub              (raw 32-byte Ed25519 public key)
  - verify_handoff.py       (standalone verification script)

The verify_handoff.py script is shipped at the repo root and copied into
each packet, so the receiving party can run it on any machine with
`pip install cryptography`.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Optional

from . import config, crypto_ed25519, records, scenarios

ROOT = config.BASE_DIR
VERIFY_SCRIPT = ROOT / "verify_handoff.py"


# ---------------------------------------------------------------------
# Canonical encounter JSON
# ---------------------------------------------------------------------
def _canonical_encounter(encounter_id: str,
                         extraction: Optional[dict] = None,
                         aar: Optional[dict] = None) -> dict:
    rec = records.get_encounter(encounter_id) or {}
    sc = scenarios.get(rec.get("scenario_id", "")) or {}
    return {
        "schema": "aegis-v4-handoff",
        "encounter_id": rec.get("id", encounter_id),
        "scenario_id": rec.get("scenario_id", ""),
        "scenario_name": sc.get("name", ""),
        "patient_label": rec.get("patient_label", ""),
        "started_at": rec.get("started_at"),
        "ended_at": rec.get("ended_at"),
        "events": rec.get("events", []),
        "extraction": extraction,
        "after_action_review": aar,
        "device": {
            "pub_fingerprint": "ed25519/" + crypto_ed25519.public_fingerprint(),
        },
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }


def _canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------
# Summary PDF — reportlab if available, fallback to a printable HTML
# ---------------------------------------------------------------------
def _render_summary_pdf(encounter: dict) -> bytes:
    try:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.units import inch
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.pdfgen import canvas as _canvas
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        )
        from reportlab.lib import colors
    except ImportError:
        return _summary_html_as_pdf_placeholder(encounter)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Courier-Bold",
                        fontSize=20, leading=24, spaceAfter=4)
    meta = ParagraphStyle("meta", parent=styles["BodyText"], fontName="Courier",
                          fontSize=8, textColor=colors.grey, spaceAfter=18)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontSize=11,
                        spaceBefore=12, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10,
                          leading=14)
    sig = ParagraphStyle("sig", parent=styles["BodyText"], fontName="Courier",
                         fontSize=7.5, leading=11, textColor=colors.grey,
                         spaceBefore=24)

    story = []
    story.append(Paragraph("AEGIS ENCOUNTER HANDOFF PACKET", h1))
    story.append(Paragraph(
        f"{encounter.get('encounter_id', '')} &nbsp;·&nbsp; "
        f"{encounter.get('generated_at', '')}", meta,
    ))

    aar = encounter.get("after_action_review") or {}
    story.append(Paragraph("Summary", h3))
    story.append(Paragraph(aar.get("summary", "—"), body))

    extr = encounter.get("extraction") or {}
    if extr.get("patient"):
        story.append(Paragraph("Patient", h3))
        p = extr["patient"]
        story.append(Paragraph(
            f"Age: {p.get('age', '—')} &nbsp; Sex: {p.get('sex', '—')} &nbsp; "
            f"Weight: {p.get('weight_kg', '—')} kg", body,
        ))

    if extr.get("interventions_performed"):
        story.append(Paragraph("Interventions", h3))
        rows = [["Type", "Details"]]
        for i in extr["interventions_performed"]:
            rows.append([i.get("type", "—"), i.get("details", "—")])
        t = Table(rows, colWidths=[1.7 * inch, 4.3 * inch])
        t.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
        ]))
        story.append(t)

    nudges = aar.get("teaching_points") or []
    if nudges:
        story.append(Paragraph("Teaching Points", h3))
        for n in nudges[:5]:
            story.append(Paragraph(
                f"• {n.get('point', '')} &nbsp; <font color='grey'>"
                f"[{n.get('citation_id', '')}]</font>", body,
            ))

    story.append(Spacer(1, 0.2 * inch))
    fp = encounter.get("device", {}).get("pub_fingerprint", "—")
    story.append(Paragraph(
        f"Integrity hash (SHA-256) and Ed25519 device signature ship inside "
        f"the .zip alongside this PDF.<br/>"
        f"Device key: {fp}<br/>"
        f"Verify on any computer:<br/>"
        f"<font face='Courier'>python verify_handoff.py encounter.json</font>",
        sig,
    ))

    doc.build(story)
    return buf.getvalue()


def _summary_html_as_pdf_placeholder(encounter: dict) -> bytes:
    """If reportlab isn't installed, ship a minimal HTML file as the summary
    inside the zip. The verify script doesn't depend on this file."""
    aar = encounter.get("after_action_review") or {}
    return (
        f"<!doctype html><meta charset='utf-8'><title>AEGIS Handoff</title>\n"
        f"<h1>AEGIS Encounter Handoff</h1>\n"
        f"<p>{encounter.get('encounter_id', '')}</p>\n"
        f"<h3>Summary</h3><p>{aar.get('summary', '')}</p>\n"
    ).encode("utf-8")


# ---------------------------------------------------------------------
# Build packet
# ---------------------------------------------------------------------
def build_packet(encounter_id: str,
                 extraction: Optional[dict] = None,
                 aar: Optional[dict] = None) -> tuple[bytes, dict]:
    """Returns (zip_bytes, manifest)."""
    encounter = _canonical_encounter(encounter_id, extraction, aar)
    canonical = _canonical_bytes(encounter)
    integrity_hash = hashlib.sha256(canonical).hexdigest()

    crypto_ed25519.init()
    signature = crypto_ed25519.sign_bundle(canonical)
    sig_hex = signature.hex()
    pub_bytes = crypto_ed25519.public_key_bytes()

    pdf_bytes = _render_summary_pdf(encounter)
    verify_script = (VERIFY_SCRIPT.read_bytes() if VERIFY_SCRIPT.exists()
                     else b"# verify_handoff.py missing from repo root\n")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("encounter.json", canonical)
        zf.writestr("encounter.json.sig", sig_hex)
        zf.writestr("summary.pdf", pdf_bytes)
        zf.writestr("device.pub", pub_bytes)
        zf.writestr("verify_handoff.py", verify_script)

    manifest = {
        "filename": f"encounter-{encounter_id}.zip",
        "size_bytes": buf.tell(),
        "integrity_hash": integrity_hash,
        "signature_hex": sig_hex,
        "device_pub_fingerprint": crypto_ed25519.public_fingerprint(),
        "events": len(encounter.get("events", [])),
        "extraction_facts": (
            len((extraction or {}).get("vitals_observed") or [])
            + len((extraction or {}).get("interventions_performed") or [])
        ),
    }
    return buf.getvalue(), manifest
