"""
V4 eval runner — exercises the four LLM jobs against their eval sets.

Pass criteria per V4 §4.5:
  - Output is valid JSON matching the schema
  - Required fields are present and non-null where expected
  - Citations point to real chunk IDs that exist in the corpus
  - For adversarial inputs, refusal shape matches exactly

Run:
    python tests/run_evals.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EVAL_DIR = ROOT / "tests"


def _green(s): return f"\033[1;32m{s}\033[0m"
def _red(s):   return f"\033[1;31m{s}\033[0m"
def _gray(s):  return f"\033[2m{s}\033[0m"


def _check(actual, expects: dict, valid_chunk_ids: set[str]) -> tuple[bool, list[str]]:
    failures: list[str] = []

    def _get(path: str):
        cur = actual
        for p in path.split("."):
            if not isinstance(cur, dict): return None
            cur = cur.get(p)
        return cur

    for k, v in expects.items():
        if k.endswith("_min"):
            field = k[:-4]
            arr = _get(field) if "." in field else actual.get(field)
            if not isinstance(arr, list) or len(arr) < int(v):
                failures.append(f"  expected len({field}) >= {v}, got {len(arr) if isinstance(arr, list) else type(arr).__name__}")
        elif k.endswith("_max"):
            field = k[:-4]
            arr = _get(field) if "." in field else actual.get(field)
            if not isinstance(arr, list) or len(arr) > int(v):
                failures.append(f"  expected len({field}) <= {v}, got {len(arr) if isinstance(arr, list) else type(arr).__name__}")
        elif k.endswith("_includes"):
            field = k[:-9]
            arr = actual.get(field) or []
            if isinstance(v, str): v = [v]
            blob = json.dumps(arr).lower()
            for needle in v:
                if needle.lower() not in blob:
                    failures.append(f"  expected {field} to include '{needle}'")
        elif k.endswith("_includes_citation"):
            cits = actual.get("citations") or actual.get("nudges") or []
            blob = json.dumps(cits)
            if v not in blob:
                failures.append(f"  expected citation '{v}' in {k[:-19]}")
        elif k.endswith("_in"):
            field = k[:-3]
            val = _get(field)
            if val not in v:
                failures.append(f"  expected {field} in {v}, got {val}")
        elif k == "answer_type":
            if actual.get("answer_type") != v:
                failures.append(f"  expected answer_type={v}, got {actual.get('answer_type')}")
        elif k == "documentation_quality":
            if actual.get("documentation_quality") != v:
                failures.append(f"  expected documentation_quality={v}")
        elif k == "summary_present":
            s = actual.get("summary")
            if not (isinstance(s, str) and s.strip()):
                failures.append("  expected summary present")
        elif k == "extraction_confidence":
            if actual.get("extraction_confidence") != v:
                failures.append(f"  expected extraction_confidence={v}")
        elif k == "severity_in":
            sevs = [n.get("severity") for n in (actual.get("nudges") or [])]
            if not any(s in v for s in sevs):
                failures.append(f"  expected at least one severity in {v}")
        elif "." in k:
            actual_v = _get(k)
            if actual_v != v:
                # Allow numeric coercion for ages / weights
                try:
                    if float(actual_v) == float(v): continue
                except (TypeError, ValueError): pass
                failures.append(f"  expected {k}={v}, got {actual_v}")
        else:
            if actual.get(k) != v:
                failures.append(f"  expected {k}={v}, got {actual.get(k)}")

    # Validate any citation IDs actually exist in the corpus
    for cite in actual.get("citations") or []:
        cid = cite.get("citation_id")
        if cid and cid not in valid_chunk_ids:
            failures.append(f"  invalid citation_id {cid!r} not in corpus")
    for n in actual.get("nudges") or []:
        cid = n.get("citation_id")
        if cid and cid not in valid_chunk_ids:
            failures.append(f"  invalid nudge citation {cid!r} not in corpus")

    return (not failures), failures


async def run_extraction(valid_ids: set[str]) -> tuple[int, int]:
    from backend import inference
    examples = json.loads((EVAL_DIR / "eval_extraction.json").read_text())["examples"]
    passed = 0
    for ex in examples:
        ip = ex["input"]
        out = await inference.extract_facts(ip["transcript"], ip["encounter_id"],
                                              ip["scenario_name"], ip["elapsed_seconds"])
        ok, fails = _check(out, ex["expect"], valid_ids)
        print(("  " + _green("PASS") if ok else "  " + _red("FAIL")) + f"  {ex['id']}")
        for f in fails: print(_gray(f))
        if ok: passed += 1
    return passed, len(examples)


async def run_qa(valid_ids: set[str]) -> tuple[int, int]:
    from backend import inference
    examples = json.loads((EVAL_DIR / "eval_qa.json").read_text())["examples"]
    passed = 0
    for ex in examples:
        ip = ex["input"]
        out = await inference.answer_question(ip["question"], ip["scenario_context"])
        ok, fails = _check(out, ex["expect"], valid_ids)
        print(("  " + _green("PASS") if ok else "  " + _red("FAIL")) + f"  {ex['id']}")
        for f in fails: print(_gray(f))
        if ok: passed += 1
    return passed, len(examples)


async def run_nudges(valid_ids: set[str]) -> tuple[int, int]:
    from backend import inference
    examples = json.loads((EVAL_DIR / "eval_nudges.json").read_text())["examples"]
    passed = 0
    for ex in examples:
        out = await inference.compute_nudges(ex["input"]["encounter_state"])
        ok, fails = _check(out, ex["expect"], valid_ids)
        print(("  " + _green("PASS") if ok else "  " + _red("FAIL")) + f"  {ex['id']}")
        for f in fails: print(_gray(f))
        if ok: passed += 1
    return passed, len(examples)


async def main() -> int:
    print("AEGIS V4 — eval suite")
    print("=" * 60)

    from backend import retrieval
    chunks = retrieval.load_corpus()
    valid_ids = {c["citation_id"] for c in chunks}
    print(f"corpus: {len(valid_ids)} chunks loaded")
    print()

    total_pass = total = 0
    for name, fn in [("EXTRACTION", run_extraction),
                     ("REFERENCE QA", run_qa),
                     ("NUDGES", run_nudges)]:
        print(f"--- {name} ---")
        p, t = await fn(valid_ids)
        print(f"  {p}/{t} pass")
        print()
        total_pass += p; total += t

    pct = (total_pass * 100 / total) if total else 0
    print("=" * 60)
    print(f"TOTAL: {total_pass}/{total} pass  ({pct:.1f}%)")
    print(f"AAR eval is structural-only; runs at handoff time.")
    return 0 if pct >= 90 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
