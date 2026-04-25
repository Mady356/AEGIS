"""
V4 retrieval — semantic search over the hand-curated corpus.

Reads chunks from backend/corpus/chunks/*.md and embeds them via Ollama's
nomic-embed-text into a local ChromaDB collection. Falls back to a pure
in-memory keyword retriever if Ollama or chromadb is unavailable so the
preview still works without dependencies.

The fallback is honest about itself — system_status reports
`embed_backend = "keyword-fallback"` instead of "ollama" when active.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import config

CORPUS_DIR = config.BASE_DIR / "backend" / "corpus" / "chunks"
COLLECTION = "aegis_corpus_v4"

_chroma = None
_collection = None
_keyword_index: list[dict] = []          # fallback corpus
_built_at: Optional[str] = None
_embed_backend: str = "uninitialized"


# ---------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------
def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Tiny frontmatter parser — no PyYAML dependency. Supports scalars and
    flow-style lists for `scenario_tags: [combat, trauma]`."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    meta: dict = {}
    for line in fm_block.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip(); v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            meta[k] = [s.strip().strip("'\"") for s in v[1:-1].split(",") if s.strip()]
        elif v.startswith('"') and v.endswith('"'):
            meta[k] = v[1:-1]
        elif v.startswith("'") and v.endswith("'"):
            meta[k] = v[1:-1]
        else:
            try:
                meta[k] = int(v)
            except ValueError:
                try:
                    meta[k] = float(v)
                except ValueError:
                    meta[k] = v
    return meta, body


def load_corpus() -> list[dict]:
    """Load every chunk from disk. Returns [{citation_id, source, page,
    section, scenario_tags, text}]."""
    chunks: list[dict] = []
    if not CORPUS_DIR.exists():
        return chunks
    for path in sorted(CORPUS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        cid = meta.get("citation_id") or path.stem
        chunks.append({
            "citation_id": cid,
            "id": cid,           # alias for older frontend code
            "source": meta.get("source", ""),
            "source_short": meta.get("source_short", ""),
            "source_url": meta.get("source_url", ""),
            "source_pdf": meta.get("source_pdf", ""),
            "page": meta.get("page"),
            "section": meta.get("section", ""),
            "revision": meta.get("revision", ""),
            "scenario_tags": meta.get("scenario_tags") or [],
            "text": body.strip(),
            "document": meta.get("source", ""),
        })
    return chunks


# ---------------------------------------------------------------------
# Warmup — try Chroma+Ollama, fall back to keyword
# ---------------------------------------------------------------------
async def warmup() -> None:
    """Load chunks from disk, embed them locally with sentence-transformers,
    push to ChromaDB. Falls back to a pure keyword retriever if either
    chromadb or sentence-transformers is unavailable."""
    global _chroma, _collection, _keyword_index, _built_at, _embed_backend
    chunks = load_corpus()
    _keyword_index = chunks
    _built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        import chromadb            # type: ignore
    except ImportError:
        _embed_backend = "keyword-fallback (chromadb missing)"
        return

    # V5 — embeddings via sentence-transformers (in-process, no HTTP).
    try:
        from . import embeddings as embed_mod
    except Exception as exc:
        print(f"[retrieval] embeddings module unavailable: {exc}")
        _embed_backend = "keyword-fallback (embeddings unavailable)"
        return

    try:
        client = chromadb.PersistentClient(path=str(config.CHROMA_PATH))
        try:
            client.delete_collection(COLLECTION)
        except Exception:
            pass
        coll = client.get_or_create_collection(
            name=COLLECTION, metadata={"hnsw:space": "cosine"},
        )
        if chunks:
            texts = [c["text"] for c in chunks]
            # Run the synchronous batch embed off-loop so we don't block.
            import asyncio as _asyncio
            embs = await _asyncio.get_event_loop().run_in_executor(
                None, embed_mod.embed_batch, texts,
            )
            ids = [c["citation_id"] for c in chunks]
            docs = texts
            metas = [{
                "source": c["source"], "source_short": c["source_short"],
                "page": c["page"] if c["page"] is not None else -1,
                "section": c["section"], "revision": c["revision"],
                "scenario_tags": ",".join(c["scenario_tags"]),
            } for c in chunks]
            coll.add(ids=ids, documents=docs, metadatas=metas, embeddings=embs)
        _chroma = client
        _collection = coll
        _embed_backend = (
            f"sentence-transformers ({embed_mod.active_device()}) + chroma"
        )
    except Exception as exc:
        print(f"[retrieval] chroma+embeddings warmup failed: {exc}")
        _chroma = None; _collection = None
        _embed_backend = "keyword-fallback"


# ---------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------
async def retrieve(query: str,
                   scenario_filter: str | list[str] | None = None,
                   k: int = 5) -> list[dict]:
    if not _keyword_index and not _collection:
        await warmup()
    tags: list[str] = []
    if isinstance(scenario_filter, str):
        tags = [scenario_filter]
    elif isinstance(scenario_filter, list):
        tags = scenario_filter

    if _collection is not None:
        try:
            from . import embeddings as embed_mod
            import asyncio as _asyncio
            emb = await _asyncio.get_event_loop().run_in_executor(
                None, embed_mod.embed_text, query,
            )
            if emb is None:
                raise RuntimeError("embed failed")
            try:
                res = _collection.query(query_embeddings=[emb], n_results=k)
            except Exception as exc:
                # ChromaDB raises on dimension mismatch when the index was
                # built with a different embedding model. Surface it clearly.
                msg = str(exc)
                if "dimension" in msg.lower():
                    raise RuntimeError(
                        "Corpus embeddings outdated. "
                        "Run `python -m backend.ingest` to rebuild."
                    ) from exc
                raise
            ids = (res.get("ids") or [[]])[0]
            docs = (res.get("documents") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            out: list[dict] = []
            for i, cid in enumerate(ids):
                full = next((c for c in _keyword_index if c["citation_id"] == cid), None)
                if not full: continue
                score = round(1 - float(dists[i]), 3) if dists[i] is not None else None
                out.append({**full, "score": score})
            return out
        except Exception:
            pass

    # Keyword fallback — case-insensitive token overlap with scenario boost.
    return _keyword_retrieve(query, tags, k)


def _keyword_retrieve(query: str, tags: list[str], k: int) -> list[dict]:
    qtoks = set(re.findall(r"[a-zA-Z]{3,}", query.lower()))
    if not qtoks:
        return []
    scored: list[tuple[float, dict]] = []
    for c in _keyword_index:
        text_l = c["text"].lower()
        ttoks = set(re.findall(r"[a-zA-Z]{3,}", text_l))
        overlap = len(qtoks & ttoks)
        if overlap == 0:
            continue
        # title / section / citation-id match counts double
        bonus = 0.0
        meta_blob = f"{c['citation_id']} {c['section']} {c['source_short']}".lower()
        for t in qtoks:
            if t in meta_blob:
                bonus += 0.5
        # Scenario tag boost
        if tags and any(t in c["scenario_tags"] for t in tags):
            bonus += 0.6
        score = overlap + bonus
        scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    out = []
    max_s = scored[0][0] if scored else 1
    for s, c in scored[:k]:
        out.append({**c, "score": round(s / max(max_s, 1), 3)})
    return out


async def by_id(citation_id: str) -> dict | None:
    if not _keyword_index:
        await warmup()
    return next((c for c in _keyword_index if c["citation_id"] == citation_id), None)


async def stats() -> dict:
    if not _keyword_index:
        await warmup()
    return {
        "count": len(_keyword_index),
        "dim": config.EMBED_DIM if _embed_backend.startswith("ollama") else 0,
        "source_docs": len({c["source_short"] for c in _keyword_index if c["source_short"]}),
        "built_at": _built_at,
        "embed_backend": _embed_backend,
    }
