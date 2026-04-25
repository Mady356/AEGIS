from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PROTOCOLS_DIR = ROOT / "protocols"

TOKEN_RE = re.compile(r"[a-z0-9_]+")
STOPWORDS = {
    "and", "or", "the", "a", "an", "to", "of", "for", "with", "on", "in",
    "at", "by", "is", "are", "was", "were", "be", "as", "from", "that", "this",
}
SYNONYMS = {
    "sob": {"shortness", "breath", "dyspnea"},
    "dyspnea": {"shortness", "breath", "sob"},
    "breathless": {"shortness", "breath", "dyspnea"},
    "cp": {"chest", "pain"},
    "hemorrhage": {"bleeding", "bleed"},
    "bleeding": {"hemorrhage", "bleed"},
    "hypoxia": {"low", "oxygen", "spo2"},
    "tachycardia": {"high", "heart", "rate"},
}
SOURCE_WEIGHTS = {
    "TCCC": 1.0,
    "ATLS": 0.95,
    "WHO": 0.9,
}


def _tokenize(text: str) -> set[str]:
    tokens = {t for t in TOKEN_RE.findall(text.lower()) if t and t not in STOPWORDS}
    expanded = set(tokens)
    for token in list(tokens):
        expanded.update(SYNONYMS.get(token, set()))
    return expanded


def _source_from_citation(citation: str) -> str:
    return citation.split("-", 1)[0].upper().strip()


@lru_cache(maxsize=1)
def load_protocol_chunks() -> list[dict]:
    chunks: list[dict] = []
    if not PROTOCOLS_DIR.exists():
        return chunks

    for file_path in sorted(PROTOCOLS_DIR.glob("*.json")):
        try:
            data = json.loads(file_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            citation = str(item.get("citation", "")).strip()
            guidance = str(item.get("guidance", "")).strip()
            keywords = [str(k).strip().lower() for k in (item.get("keywords") or []) if str(k).strip()]
            section = str(item.get("section", "")).strip()
            population = str(item.get("population", "all")).strip().lower()
            if not citation or not guidance:
                continue
            token_source = " ".join(keywords) + " " + guidance + " " + section
            chunks.append(
                {
                    "citation": citation,
                    "guidance": guidance,
                    "keywords": keywords,
                    "section": section,
                    "population": population,
                    "source": _source_from_citation(citation),
                    "tokens": _tokenize(token_source),
                }
            )
    return chunks


def build_query_terms(encounter: dict) -> set[str]:
    vitals = encounter.get("vitals") or {}
    text = " ".join(
        [
            str(encounter.get("chief_complaint", "")),
            " ".join(encounter.get("symptoms") or []),
            str(encounter.get("notes", "")),
            str(encounter.get("context", "")),
        ]
    )
    terms = _tokenize(text)
    if vitals.get("oxygen_saturation") is not None and float(vitals["oxygen_saturation"]) < 92:
        terms.update({"hypoxia", "low", "oxygen", "spo2"})
    if vitals.get("systolic_bp") is not None and float(vitals["systolic_bp"]) < 90:
        terms.update({"hypotension", "shock", "perfusion"})
    if vitals.get("heart_rate") is not None and float(vitals["heart_rate"]) > 120:
        terms.update({"tachycardia", "heart", "rate"})
    return terms


def score_chunk(chunk: dict, query_terms: set[str], acuity: str, expected_population: str = "all") -> float:
    overlap = query_terms.intersection(chunk["tokens"])
    if not overlap:
        return 0.0
    lexical = min(len(overlap) / max(len(query_terms), 1), 1.0)
    concept = min(len(overlap) / max(len(chunk["tokens"]), 1) * 4.0, 1.0)
    acuity_match = 1.0 if acuity == "red" and any(k in chunk["tokens"] for k in {"shock", "hemorrhage", "airway"}) else 0.5
    source_weight = SOURCE_WEIGHTS.get(chunk["source"], 0.8)
    pop_match = 1.0 if chunk.get("population", "all") in {"all", expected_population} else 0.2
    return (0.35 * lexical) + (0.35 * concept) + (0.2 * acuity_match) + (0.05 * source_weight) + (0.05 * pop_match)
