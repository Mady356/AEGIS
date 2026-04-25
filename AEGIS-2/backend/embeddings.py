"""
V5 — Local embeddings via sentence-transformers.

Runs in-process on Apple Silicon's MPS backend (or CPU fallback).
Used by both corpus ingestion (embed_batch) and runtime retrieval
(embed_text). No HTTP dependency; no Ollama required at runtime.

The model is loaded lazily on first call so module import remains cheap
for environments that never query the corpus.
"""

from __future__ import annotations

import logging
from typing import Optional

from . import config

LOG = logging.getLogger("aegis.embeddings")

_model = None  # type: ignore[assignment]
_active_device: Optional[str] = None


def _load_model():
    """Load the sentence-transformers model. Tries the configured device
    (default 'mps' for Apple Silicon) and falls back to 'cpu' on failure."""
    global _model, _active_device
    if _model is not None:
        return _model

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers not installed. "
            "pip install -r requirements.txt"
        ) from exc

    LOG.info("Loading embedding model: %s on %s",
             config.EMBED_MODEL, config.EMBED_DEVICE)
    try:
        _model = SentenceTransformer(
            config.EMBED_MODEL,
            trust_remote_code=True,
            device=config.EMBED_DEVICE,
        )
        _active_device = config.EMBED_DEVICE
    except Exception as exc:
        LOG.warning(
            "Failed to load on %s, falling back to cpu: %s",
            config.EMBED_DEVICE, exc,
        )
        _model = SentenceTransformer(
            config.EMBED_MODEL,
            trust_remote_code=True,
            device="cpu",
        )
        _active_device = "cpu"
    return _model


def active_device() -> str:
    """Returns 'mps' / 'cuda' / 'cpu' once the model has been loaded,
    or 'unloaded' if the model has not been touched yet."""
    return _active_device or "unloaded"


def embed_text(text: str) -> list[float]:
    """Embed a single string. Returns a normalized float vector.

    Synchronous — runs in-process. For request-handler usage, this
    completes in tens of milliseconds on M-series Macs.
    """
    model = _load_model()
    vec = model.encode(text, convert_to_tensor=False, normalize_embeddings=True)
    return vec.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of strings in one model call. Used during corpus
    ingestion where amortizing the model overhead matters."""
    model = _load_model()
    vecs = model.encode(
        texts, convert_to_tensor=False, normalize_embeddings=True,
        batch_size=16, show_progress_bar=False,
    )
    return [v.tolist() for v in vecs]


def embedding_dimensions() -> int:
    """Return the dimension count of the embedding model. Used at index
    init time and by the SYS overlay's diagnostic readout."""
    try:
        return _load_model().get_sentence_embedding_dimension()
    except Exception:
        return config.EMBED_DIM


def is_loaded() -> bool:
    return _model is not None
