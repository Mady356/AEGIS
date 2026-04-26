"""
V4.1 — Pilot brief PDF generator.

Single-page document formatted as a real pilot proposal. Generated at
runtime via the /api/pilot-brief/generate endpoint and auto-cached at
aegis_data/pilot_brief.pdf on server startup so the file always exists
on disk for attachment to Devpost or USB.

Falls back to a printable HTML if reportlab isn't installed.
"""

from __future__ import annotations

import datetime
import io
from pathlib import Path

from . import config


CACHED_PATH = config.DATA_DIR / "pilot_brief.pdf"


def _build_with_reportlab() -> bytes:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )
    from reportlab.lib import colors

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Heading1"],
                            fontName="Courier-Bold", fontSize=15,
                            leading=18, spaceAfter=2)
    scope = ParagraphStyle("scope", parent=styles["BodyText"],
                            fontName="Courier", fontSize=7,
                            textColor=colors.grey, spaceAfter=12)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=10,
                        spaceBefore=10, spaceAfter=3, textColor=colors.black)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=8.5,
                          leading=12, spaceAfter=2)
    foot = ParagraphStyle("foot", parent=styles["BodyText"],
                          fontName="Courier", fontSize=6.5,
                          textColor=colors.grey, leading=9, spaceBefore=10)

    story = []
    today = datetime.date.today().isoformat()
    story.append(Paragraph("AEGIS PILOT BRIEF — RURAL EMS DEPLOYMENT", title))
    story.append(Paragraph(
        f"Version 4.1 &nbsp;·&nbsp; {today} &nbsp;·&nbsp; "
        f"DOCUMENTATION INTERFACE · NOT A CLINICAL ADVISOR", scope,
    ))

    story.append(Paragraph("Target population", h2))
    story.append(Paragraph(
        "Rural EMS units in counties with population density under 50 per "
        "square mile. United States baseline: approximately 6,000 EMS "
        "agencies meeting this threshold, serving roughly 60 million people.",
        body,
    ))

    story.append(Paragraph("Deployment model", h2))
    story.append(Paragraph(
        "One AEGIS unit per ambulance, pre-loaded with a regionally relevant "
        "protocol corpus (TCCC for trauma-focused units, AHA/ILCOR for "
        "cardiac, WHO Pediatric for pediatric-equipped units). Operator "
        "devices (existing tablets or ruggedized handhelds) connect to the "
        "AEGIS unit over the ambulance's local Wi-Fi.", body,
    ))

    story.append(Paragraph("Success metrics", h2))
    metrics = [
        "Time from voice intake to first cited reference (target: under 5 seconds)",
        "Documentation completeness (extraction receipts capturing >90% of stated interventions)",
        "Integrity verification rate (target: 100% of generated handoff packets verify successfully)",
        "Post-call AAR completion rate (target: >80% of encounters produce a structured AAR within 5 minutes of close)",
        "Operator satisfaction (qualitative interviews at 3 and 6 months)",
    ]
    for m in metrics:
        story.append(Paragraph(f"• {m}", body))

    story.append(Paragraph("Pilot scope", h2))
    story.append(Paragraph(
        "12 ambulance units across 3 rural EMS agencies, 6-month duration. "
        "Month 1: baseline measurement of current documentation and reference "
        "practices. Months 2–6: AEGIS deployment with biweekly check-ins.",
        body,
    ))

    story.append(Paragraph("Estimated cost", h2))
    cost_rows = [
        ["Hardware (12 units @ $3,500)", "$42,000"],
        ["Corpus curation and customization", "$25,000"],
        ["Training and onboarding", "$15,000"],
        ["Pilot evaluation and reporting", "$20,000"],
        ["TOTAL ESTIMATED PILOT COST", "$102,000"],
    ]
    t = Table(cost_rows, colWidths=[3.6 * inch, 1.2 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Courier", 8.5),
        ("LINEBELOW", (0, -2), (-1, -2), 0.5, colors.black),
        ("FONT", (0, -1), (-1, -1), "Courier-Bold", 8.5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    story.append(t)

    story.append(Paragraph("Risk mitigations", h2))
    risks = [
        "<b>Hardware failure:</b> redundant unit per agency for hot-swap.",
        "<b>Software failure:</b> graceful degradation, fall back to existing reference materials.",
        "<b>Operator non-adoption:</b> phased rollout, operator-led champion model, weekly office hours.",
        "<b>Regulatory inquiry:</b> pre-engagement with state EMS authority and FDA Pre-Submission program.",
    ]
    for r in risks:
        story.append(Paragraph(f"• {r}", body))

    story.append(Paragraph("Privacy and regulatory posture", h2))
    posture = [
        "Aligns with HIPAA Security Rule (encryption at rest, no transmission of PHI).",
        "Compatible with FDA Class II medical device pathway (with predicate devices identified).",
        "State EMS regulatory variations addressed through per-state deployment configuration.",
        "Patient consent for documentation handled through existing EMS consent forms.",
    ]
    for p in posture:
        story.append(Paragraph(f"• {p}", body))

    story.append(Paragraph("What AEGIS does not do", h2))
    story.append(Paragraph(
        "AEGIS is a documentation interface, not a clinical advisor. The "
        "LLM does not prescribe. Clinical decisions remain entirely with "
        "the operator. This limitation is a feature, not a bug — it keeps "
        "AEGIS within a defensible regulatory category.", body,
    ))

    story.append(Paragraph(
        "Prepared by the AEGIS team for LA Hacks 2026 &nbsp;·&nbsp; "
        f"Generated from the live AEGIS system at "
        f"{datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}",
        foot,
    ))

    doc.build(story)
    return buf.getvalue()


def _build_html_fallback() -> bytes:
    today = datetime.date.today().isoformat()
    html = f"""<!doctype html>
<meta charset="utf-8">
<title>AEGIS Pilot Brief — Rural EMS Deployment</title>
<style>
body {{ font-family: Georgia, serif; max-width: 720px; margin: 36px auto;
       color: #111; padding: 0 24px; }}
h1   {{ font-family: 'Courier New', monospace; font-size: 18px; margin-bottom: 0; }}
.scope {{ font-family: 'Courier New', monospace; font-size: 10px;
          color: #666; letter-spacing: 0.05em; margin-bottom: 18px; }}
h2   {{ font-size: 13px; margin-top: 16px; margin-bottom: 4px; }}
p, li {{ font-size: 11px; line-height: 1.5; margin: 4px 0; }}
table {{ border-collapse: collapse; font-family: 'Courier New', monospace;
         font-size: 11px; margin: 6px 0; }}
td   {{ padding: 1px 12px 1px 0; }}
.foot {{ font-family: 'Courier New', monospace; font-size: 8px; color: #888;
         margin-top: 24px; }}
</style>
<h1>AEGIS PILOT BRIEF — RURAL EMS DEPLOYMENT</h1>
<div class="scope">Version 4.1 · {today} · DOCUMENTATION INTERFACE · NOT A CLINICAL ADVISOR</div>
<h2>Target population</h2>
<p>Rural EMS units in counties with population density under 50 per square mile.
United States baseline: approximately 6,000 EMS agencies meeting this threshold,
serving roughly 60 million people.</p>
<h2>Deployment model</h2>
<p>One AEGIS unit per ambulance, pre-loaded with a regionally relevant protocol
corpus. Operator devices connect over the ambulance's local Wi-Fi.</p>
<h2>Estimated cost</h2>
<table>
  <tr><td>Hardware (12 units @ $3,500)</td><td>$42,000</td></tr>
  <tr><td>Corpus curation and customization</td><td>$25,000</td></tr>
  <tr><td>Training and onboarding</td><td>$15,000</td></tr>
  <tr><td>Pilot evaluation and reporting</td><td>$20,000</td></tr>
  <tr><td><b>TOTAL ESTIMATED PILOT COST</b></td><td><b>$102,000</b></td></tr>
</table>
<h2>What AEGIS does not do</h2>
<p>AEGIS is a documentation interface, not a clinical advisor. The LLM does
not prescribe. Clinical decisions remain entirely with the operator.</p>
<div class="foot">Prepared by the AEGIS team for LA Hacks 2026.</div>
"""
    return html.encode("utf-8")


def build_pilot_brief() -> bytes:
    try:
        return _build_with_reportlab()
    except Exception:
        return _build_html_fallback()


def ensure_cached() -> Path:
    """Build (if missing) and return the cached pilot brief path."""
    if not CACHED_PATH.exists():
        CACHED_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHED_PATH.write_bytes(build_pilot_brief())
    return CACHED_PATH


def regenerate() -> Path:
    """Force regeneration of the cached pilot brief."""
    CACHED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHED_PATH.write_bytes(build_pilot_brief())
    return CACHED_PATH
