"""
Live system telemetry — psutil-driven.

Powers the SYS overlay. Returns a structured snapshot consolidating
every dimension the operator might inspect: inference, speech, corpus,
persistence, runtime resources, network, build identity.
"""

from __future__ import annotations

import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, db, monitor, records

_PROCESS_STARTED = time.monotonic()


def _safe_psutil():
    try:
        import psutil  # type: ignore
        return psutil
    except ImportError:
        return None


def _ram_resident_mb() -> int | None:
    psu = _safe_psutil()
    if psu is None:
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return int(rss / (1024 * 1024)) if rss > 10_000_000 else int(rss / 1024)
        except Exception:
            return None
    return int(psu.Process().memory_info().rss / (1024 * 1024))


def _disk_free_mb() -> int | None:
    psu = _safe_psutil()
    if psu is None:
        try:
            import shutil
            return int(shutil.disk_usage(str(config.BASE_DIR)).free / (1024 * 1024))
        except Exception:
            return None
    try:
        return int(psu.disk_usage(str(config.BASE_DIR)).free / (1024 * 1024))
    except Exception:
        return None


def _cpu_percent() -> float | None:
    psu = _safe_psutil()
    if psu is None: return None
    try: return float(psu.cpu_percent(interval=None))
    except Exception: return None


def _corpus_stats() -> dict:
    """Return chunk count / dim / source count / last build time. Tries
    ChromaDB if available; falls back to file-system inspection.

    retrieval.stats() is async, but this function is called from a sync
    snapshot path. We synchronously read the in-memory keyword index it
    populates instead.
    """
    try:
        from . import retrieval, embeddings as embed_mod
        chunks = retrieval._keyword_index or retrieval.load_corpus()
        dim = (embed_mod.embedding_dimensions()
               if embed_mod.is_loaded() else config.EMBED_DIM)
        return {
            "count": len(chunks),
            "dim": dim,
            "source_docs": len({c["source_short"] for c in chunks
                                if c.get("source_short")}),
            "built_at": retrieval._built_at,
            "embed_backend": retrieval._embed_backend,
        }
    except Exception:
        pass
    # Fallback: count files
    cnt = 0
    docs = 0
    if config.CORPUS_DIR.exists():
        for p in config.CORPUS_DIR.iterdir():
            if p.suffix in (".pdf", ".md"):
                docs += 1
    return {
        "count": cnt, "dim": config.EMBED_DIM, "source_docs": docs,
        "built_at": None,
    }


def _index_storage_mb() -> float | None:
    if not config.CHROMA_PATH.exists(): return None
    total = 0
    for p in config.CHROMA_PATH.rglob("*"):
        if p.is_file():
            try: total += p.stat().st_size
            except Exception: pass
    return round(total / (1024 * 1024), 2)


def _last_inference_latency_ms() -> int | None:
    # The inference router sets this attribute when it streams a turn.
    try:
        from . import inference
        return getattr(inference, "LAST_LATENCY_MS", None)
    except Exception:
        return None


def _last_transcription_ms() -> int | None:
    try:
        from . import transcription
        return getattr(transcription, "LAST_TRANSCRIPTION_MS", None)
    except Exception:
        return None


def _build_hash() -> str:
    try:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(config.BASE_DIR),
            capture_output=True, text=True, timeout=1,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "no-git"


def status_snapshot() -> dict:
    rec = records.event_counts()
    corpus = _corpus_stats()

    # V5 — LLM + embeddings telemetry
    llm_info = {"reachable": False, "endpoint": config.LLM_ENDPOINT,
                "configured_model": config.LLM_MODEL}
    embed_info = {"model": config.EMBED_MODEL, "device": "unloaded",
                  "dimensions": config.EMBED_DIM,
                  "backend": "sentence-transformers (in-process)"}
    try:
        from . import embeddings as _emb
        if _emb.is_loaded():
            embed_info["device"] = _emb.active_device()
            embed_info["dimensions"] = _emb.embedding_dimensions()
    except Exception:
        pass

    return {
        # Inference
        "model_name": config.LLM_MODEL,
        "embed_model": config.EMBED_MODEL,
        "backend": f"OpenAI-compat @ {config.LLM_ENDPOINT}",
        "inference_mode": "live",
        "last_inference_latency_ms": _last_inference_latency_ms(),

        # Speech
        "stt_model": "faster-whisper base.en",
        "stt_backend": f"CTranslate2 / {platform.machine()}",
        "last_transcription_ms": _last_transcription_ms(),

        # Corpus
        "corpus_chunk_count": int(corpus.get("count") or 0),
        "embedding_dimensions": int(corpus.get("dim") or config.EMBED_DIM),
        "source_document_count": int(corpus.get("source_docs") or 0),
        "last_index_build": corpus.get("built_at"),
        "index_storage_mb": _index_storage_mb(),

        # Persistence
        "record_store_engine": (
            "SQLite + SQLCipher" if db.is_encrypted() else "SQLite (plain)"
        ),
        "storage_path_mb": db.storage_size_mb(),
        "encounter_count": rec["encounters"],
        "event_count": rec["events"],

        # Telemetry
        "ram_resident_mb": _ram_resident_mb(),
        "disk_free_mb": _disk_free_mb(),
        "cpu_usage_percent": _cpu_percent(),
        "uptime_seconds": int(time.monotonic() - _PROCESS_STARTED),

        # Network
        "network_reachable": (monitor.last() or {}).get("reachable"),
        "last_state_change": monitor.last_state_change(),
        "probe_history": monitor.history(),

        # V5 — structured LLM/embeddings sub-objects (frontend can use either flat
        # legacy fields or these structured ones).
        "inference": {
            "endpoint": config.LLM_ENDPOINT,
            "model": config.LLM_MODEL,
            "last_inference_latency_ms": _last_inference_latency_ms(),
        },
        "embeddings": embed_info,

        # Build
        "version": config.BUILD_VERSION,
        "build_hash": _build_hash(),
        "built_at": config.BUILD_DATE,
        "platform": f"{platform.system().lower()}/{platform.machine()}",
    }


async def status_snapshot_with_health() -> dict:
    """status_snapshot() + an actual probe of the LLM endpoint. Used by
    the /api/system/status route — kept separate so synchronous callers
    don't need to await the network round-trip."""
    snap = status_snapshot()
    try:
        from . import inference as _inf
        snap["inference"] = {**snap["inference"], **(await _inf.health_check())}
    except Exception as exc:
        snap["inference"]["reachable"] = False
        snap["inference"]["error"] = str(exc)
    return snap
