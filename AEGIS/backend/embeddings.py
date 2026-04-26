"""
V5.1 — Embeddings via the GX10's Ollama HTTP service.

The /api/embed endpoint at config.LLM_ENDPOINT (host stripped of /v1)
runs nomic-embed-text on the GB10 GPU. The Mac is just a client.

Public surface unchanged from V5: embed_text, embed_batch,
embedding_dimensions, active_device, is_loaded — so retrieval.py
and ingest.py do not need to change.

When AEGIS is run without the GX10 reachable, the first embed call
will raise a clear RuntimeError. There is no local fallback in this
configuration; that is the explicit hackathon requirement.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional
from urllib import error, request

from . import config

LOG = logging.getLogger("aegis.embeddings")

_dim_cache: Optional[int] = None
_first_call_succeeded: bool = False
_OLLAMA_REQUEST_TIMEOUT = float(os.environ.get("OLLAMA_EMBED_TIMEOUT", "30"))


def _ollama_base() -> str:
    """Strip the /v1 suffix from LLM_ENDPOINT to reach the native /api endpoints."""
    base = config.LLM_ENDPOINT.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base


def _embed_model_name() -> str:
    """Ollama tag for the embedding model on the GX10. Default matches
    the tag we registered during install (`nomic-embed-text`)."""
    return os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")


def _post_embed(inputs: list[str]) -> list[list[float]]:
    """POST to Ollama's /api/embed. Synchronous urllib — no aiohttp dep.
    Callers in retrieval.py wrap this in run_in_executor."""
    global _dim_cache, _first_call_succeeded
    url = _ollama_base() + "/api/embed"
    payload = json.dumps({
        "model": _embed_model_name(),
        "input": inputs,
    }).encode()
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=_OLLAMA_REQUEST_TIMEOUT) as resp:
            body = json.loads(resp.read())
    except error.URLError as exc:
        raise RuntimeError(
            f"Embedding request to {url} failed: {exc}. "
            f"Verify GX10 Ollama is reachable and "
            f"'{_embed_model_name()}' is loaded."
        ) from exc

    embs = body.get("embeddings") or []
    if not embs or not embs[0]:
        raise RuntimeError(f"Ollama returned no embeddings: {body}")
    if _dim_cache is None:
        _dim_cache = len(embs[0])
    if not _first_call_succeeded:
        LOG.info(
            "embeddings: first call to %s/%s succeeded — dim=%d",
            _ollama_base(), _embed_model_name(), _dim_cache,
        )
        _first_call_succeeded = True
    return embs


def embed_text(text: str) -> list[float]:
    """Embed a single string. One HTTP round-trip to the GX10."""
    return _post_embed([text])[0]


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch. Ollama processes the list in a single GPU pass."""
    if not texts:
        return []
    return _post_embed(texts)


def active_device() -> str:
    """For the SYS overlay — where embeddings actually compute."""
    if _first_call_succeeded:
        return f"gx10-ollama"
    return "remote-unloaded"


def embedding_dimensions() -> int:
    """Dimension count. Cached after first successful call.
    Falls back to config.EMBED_DIM if the GX10 is unreachable."""
    if _dim_cache is not None:
        return _dim_cache
    try:
        _post_embed(["dim probe"])
    except Exception as exc:
        LOG.warning("embedding_dimensions probe failed: %s", exc)
        return config.EMBED_DIM
    return _dim_cache or config.EMBED_DIM


def is_loaded() -> bool:
    """Whether the remote embedding service has answered at least once."""
    return _first_call_succeeded
