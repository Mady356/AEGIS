from __future__ import annotations

from backend.protocol_indexer import load_protocol_chunks, build_query_terms, score_chunk

def retrieve_protocol_chunks(encounter: dict, triage: dict, differential: dict) -> list[str]:
    candidates = load_protocol_chunks()
    if not candidates:
        return []

    query_terms = build_query_terms(encounter)
    acuity = str(triage.get("acuity", "yellow"))
    expected_population = "pediatric" if (encounter.get("age") is not None and encounter.get("age", 999) < 16) else "adult"

    scored = []
    for chunk in candidates:
        score = score_chunk(chunk, query_terms, acuity, expected_population)
        if score >= 0.08:
            scored.append((score, chunk))

    scored.sort(key=lambda s: s[0], reverse=True)
    top = scored[:8]
    return [f"{chunk['citation']}::{chunk['guidance']}" for _, chunk in top]
