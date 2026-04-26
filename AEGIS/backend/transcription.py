"""
V4 — faster-whisper transcription, in-memory only.

WebSocket protocol:
  client → {type: "start", encounter_id, format}
  client → binary audio chunks (1 s each)
  client → {action: "finalize"}
  server → {type: "partial"|"final", text}

Audio is decoded via ffmpeg subprocess to 16 kHz mono float PCM, then
passed to faster-whisper. Nothing is written to disk.

Pre-recorded clips (Ctrl+Shift+1/2/3) bypass the WebSocket: the
frontend uploads the file via /api/transcribe/file, the server runs
the same Whisper pipeline against it, the transcript is returned.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

LOG = logging.getLogger("aegis.transcription")
MODEL_NAME = os.environ.get("AEGIS_STT_MODEL", "base.en")
LAST_TRANSCRIPTION_MS: Optional[int] = None

_model = None
_load_lock = asyncio.Lock()


async def warmup() -> None:
    asyncio.create_task(_load())


async def _load():
    global _model
    if _model is not None:
        return _model
    async with _load_lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel  # type: ignore
            loop = asyncio.get_event_loop()
            _model = await loop.run_in_executor(
                None, lambda: WhisperModel(MODEL_NAME, device="cpu", compute_type="int8"),
            )
            LOG.info("loaded faster-whisper model=%s", MODEL_NAME)
        except Exception as exc:
            LOG.warning("faster-whisper unavailable: %s", exc)
            _model = None
    return _model


async def handle(ws):
    """WebSocket handler — accumulates audio, transcribes on finalize."""
    chunks: list[bytes] = []
    fmt = "audio/webm"
    started = False
    while True:
        msg = await ws.receive()
        if msg.get("type") == "websocket.disconnect":
            return
        if msg.get("text"):
            try:
                import json
                payload = json.loads(msg["text"])
            except Exception:
                continue
            if payload.get("type") == "start":
                fmt = payload.get("format") or "audio/webm"
                started = True
                continue
            if payload.get("action") == "finalize" or payload.get("type") == "stop":
                break
        elif msg.get("bytes"):
            if started:
                chunks.append(msg["bytes"])

    text = await transcribe_bytes(b"".join(chunks), fmt)
    await ws.send_json({"type": "final", "text": text})
    await ws.close()


async def transcribe_bytes(audio_bytes: bytes, mime: str = "audio/webm") -> str:
    if not audio_bytes:
        return ""
    pcm = await _decode_to_pcm(audio_bytes)
    if pcm is None:
        return ""
    model = await _load()
    if model is None:
        return ""
    t0 = time.monotonic()
    loop = asyncio.get_event_loop()

    def _run():
        segments, _info = model.transcribe(
            pcm, language="en", vad_filter=True, beam_size=1,
        )
        return " ".join(s.text.strip() for s in segments).strip()

    try:
        text = await loop.run_in_executor(None, _run)
    except Exception as exc:
        LOG.warning("whisper transcription failed: %s", exc)
        return ""
    global LAST_TRANSCRIPTION_MS
    LAST_TRANSCRIPTION_MS = int((time.monotonic() - t0) * 1000)
    return text


async def transcribe_file(path: Path) -> str:
    """Transcribe a clip from disk — used for pre-recorded fallbacks."""
    return await transcribe_bytes(path.read_bytes(), "audio/wav")


async def _decode_to_pcm(audio_bytes: bytes):
    try:
        import numpy as np  # type: ignore
    except ImportError:
        LOG.warning("numpy unavailable; skipping decode")
        return None
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg  # type: ignore
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            LOG.warning("ffmpeg unavailable; cannot decode audio")
            return None
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-f", "f32le", "-acodec", "pcm_f32le",
        "-ac", "1", "-ar", "16000", "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(input=audio_bytes)
    if proc.returncode != 0:
        LOG.warning("ffmpeg decode failed: %s", err.decode(errors="replace")[:200])
        return None
    return np.frombuffer(out, dtype=np.float32)
