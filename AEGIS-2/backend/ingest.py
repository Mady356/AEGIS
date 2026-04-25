"""
V4 corpus ingestion — reads backend/corpus/chunks/*.md and writes them to
ChromaDB with embeddings produced by Ollama's nomic-embed-text.

Idempotent: re-running deletes the collection and rebuilds. Logs every
chunk to aegis_data/ingest.log.

Run:
    cd aegis
    python -m backend.ingest
"""

from __future__ import annotations

import asyncio
import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, retrieval  # noqa: E402


async def main() -> int:
    config.INGEST_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = config.INGEST_LOG.open("w", encoding="utf-8")

    def emit(line: str) -> None:
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        msg = f"[{ts}] {line}"
        print(msg)
        log.write(msg + "\n")

    chunks = retrieval.load_corpus()
    if not chunks:
        emit("no chunks found in backend/corpus/chunks/. Nothing to ingest.")
        log.close()
        return 1

    # V4.1 — validate that every referenced source PDF exists in Reference/.
    reference_dir = config.BASE_DIR / "Reference"
    referenced = sorted({c["source_pdf"] for c in chunks if c.get("source_pdf")})
    missing = [name for name in referenced
               if not (reference_dir / name).exists()]
    if missing:
        # Strict halt is the demo-day default — every citation must resolve to
        # a real file on disk. Set AEGIS_INGEST_ALLOW_MISSING_PDFS=1 to bypass
        # for dev work; QA / extraction / nudges / AAR all still function (the
        # only feature affected is the citation overlay's VIEW SOURCE PDF link).
        if os.environ.get("AEGIS_INGEST_ALLOW_MISSING_PDFS") == "1":
            emit("WARNING: missing source PDFs (bypassed via env var):")
            for name in missing: emit(f"  - {name}")
            emit("citation overlay's VIEW SOURCE PDF will return a 404 hint "
                 "for these chunks. retrieval + QA continue to work normally.")
        else:
            emit("MISSING source PDFs in Reference/ — ingestion halted:")
            for name in missing: emit(f"  - {name}")
            emit("Place these files in Reference/ and re-run, or set "
                 "AEGIS_INGEST_ALLOW_MISSING_PDFS=1 to bypass for dev work.")
            log.close()
            return 2
    available = {p.name for p in reference_dir.glob("*.pdf")} if reference_dir.exists() else set()
    unreferenced = sorted(available - set(referenced))
    if unreferenced:
        emit(f"WARNING: {len(unreferenced)} PDFs in Reference/ are not "
             f"referenced by any corpus chunk:")
        for name in unreferenced: emit(f"  ? {name}")

    emit(f"loaded {len(chunks)} chunks; {len(referenced)} referenced PDFs verified")
    for c in chunks:
        emit(f"  {c['citation_id']:<24} src={c['source_short']:<8} "
             f"page={c['page']!s:<4} tags={','.join(c['scenario_tags'])}")

    # V5 — pre-warm the local embedding model so the count + dim are
    # surfaced before chunks are written, and so the user sees the model
    # load before any "ChromaDB push" log line.
    try:
        from backend import embeddings as embed_mod
        emit(f"loading embedding model: {config.EMBED_MODEL} on {config.EMBED_DEVICE}")
        # Trigger lazy load
        embed_mod.embed_text("warmup")
        emit(f"embedding model loaded — device={embed_mod.active_device()} "
             f"dim={embed_mod.embedding_dimensions()}")
    except Exception as exc:
        emit(f"embedding model load failed: {exc}")
        emit("falling back to keyword retrieval (semantic search disabled)")

    emit("rebuilding ChromaDB index (one batch embedding pass)...")
    await retrieval.warmup()
    stats = await retrieval.stats()
    emit(f"retrieval ready — backend={stats['embed_backend']} "
         f"count={stats['count']} dim={stats['dim']} "
         f"docs={stats['source_docs']}")

    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
