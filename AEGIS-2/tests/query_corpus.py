"""
V4 corpus retrieval CLI — print top-5 chunks for a given query.

The four canonical V4 queries that should each return the listed chunk
in the top 2 results:

    python -m tests.query_corpus "tourniquet placement femoral artery"
        → TCCC-TQ-PLACE in top 2

    python -m tests.query_corpus "pediatric paracetamol weight"
        → WHO-PED-PARACETAMOL in top 2

    python -m tests.query_corpus "epinephrine dose cardiac arrest"
        → AHA-EPI-DOSE in top 2

    python -m tests.query_corpus "drowning child not breathing"
        → AHA-DROWNING in top 2

Run with no args to execute all four canonical queries and print pass/fail.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


CANONICAL = [
    ("tourniquet placement femoral artery", "TCCC-TQ-PLACE"),
    ("pediatric paracetamol weight",        "WHO-PED-PARACETAMOL"),
    ("epinephrine dose cardiac arrest",     "AHA-EPI-DOSE"),
    ("drowning child not breathing",        "AHA-DROWNING"),
]


async def _query(q: str, expected: str | None = None) -> bool:
    from backend import retrieval
    chunks = await retrieval.retrieve(q, scenario_filter=None, k=5)
    print(f"\nQUERY: {q}")
    print("=" * 72)
    if not chunks:
        print("  (no chunks returned — has the corpus been ingested?)")
        return False
    for i, c in enumerate(chunks):
        cid = c.get("citation_id") or c.get("id")
        score = c.get("score", "—")
        print(f"  [{i+1}] {cid:<24} score={score}")
        snippet = (c.get("text") or "").replace("\n", " ")[:160] + "…"
        print(f"      {snippet}")
    if expected is None:
        return True
    top2 = {(c.get("citation_id") or c.get("id")) for c in chunks[:2]}
    ok = expected in top2
    print(f"\n  expected {expected} in top 2: {'PASS' if ok else 'FAIL'}")
    return ok


async def main() -> int:
    if len(sys.argv) > 1:
        await _query(" ".join(sys.argv[1:]), None)
        return 0
    passed = 0
    for q, exp in CANONICAL:
        if await _query(q, exp):
            passed += 1
    print()
    print(f"{passed}/{len(CANONICAL)} canonical queries pass.")
    return 0 if passed == len(CANONICAL) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
