# AEGIS V4

> The network is optional. Care is not.

V4 locks the substance with the LLM still mocked. Every operator interaction
produces a real, hashed, persisted event. Real audio capture, real local
transcription, real corpus retrieval, real cryptographic chain, real
network monitoring, real system telemetry. The only mocked component is
the source of the streaming reasoning text — and even that streams over
real SSE infrastructure at the V1 typewriter cadence, sourced from
hardcoded fixtures pre-written to look exactly like real model output.

A judge cannot tell the model is mocked. The developer can — `INFERENCE_MODE`
is `"mock"` in V4, becomes `"live"` in V5 with a single env-var change.

## What's running

| Component        | V4 software                              | V5 swap                  |
|------------------|------------------------------------------|--------------------------|
| LLM              | scripted fixtures (`inference_mock.py`)  | Ollama serving Gemma     |
| Embeddings       | Ollama `nomic-embed-text` (for ingest)   | unchanged                |
| Vector store     | ChromaDB persistent (local)              | unchanged                |
| Speech-to-text   | `faster-whisper` base.en, in-memory      | unchanged                |
| Records          | SQLite + SQLCipher, SHA-256 chain        | + Ed25519 signature col. |
| Backend API      | FastAPI / uvicorn                        | unchanged                |
| Network monitor  | TCP probes 1.1.1.1:53 + 8.8.8.8:53       | unchanged                |

## Run

### Production stack (FastAPI + ChromaDB + Whisper)

```bash
# 1. Optional Ollama — only needed for ingest (embeddings) in V4
brew install ollama
ollama serve &
ollama pull nomic-embed-text

# 2. Python deps
cd aegis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Drop corpus PDFs into backend/corpus/, then:
python -m backend.ingest

# 4. Run V4 backend
uvicorn backend.main:app --host 127.0.0.1 --port 8000
# Then open http://127.0.0.1:8000
```

### Preview server (stdlib, no FastAPI/Chroma/Whisper required)

For dev environments without the full stack:

```bash
python preview_server.py
```

The preview server implements the same routes as `backend/main.py` and
serves the V4 frontend. Reasoning streams come from the same
`inference_mock` fixtures.

## V4-to-V5 hand-off

The single line that flips:

```bash
INFERENCE_MODE=live OLLAMA_HOST=http://localhost:11434 \
  uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

V5 fills in `stream_live_response` in `backend/inference.py`. The router
already dispatches on `INFERENCE_MODE`. No frontend change. No schema
change. No persistence migration.

## Demo flow

| t       | Action                                        | What's real                        |
|---------|-----------------------------------------------|------------------------------------|
| 0:00    | Boot — encounter created in encrypted store   | DB write, SHA-256 chain seeded     |
| 0:10    | Vitals begin evolving                         | Vital trajectory computed live     |
| 0:30    | Press mic, describe casualty                  | `getUserMedia` + Whisper transcription |
| 0:50    | Reasoning streams in via SSE                  | Real SSE; tokens from fixture      |
| 1:10    | Click any citation                            | Real corpus lookup, real score     |
| 1:30    | Network state flip (toggle Wi-Fi)             | Real TCP probes, 2s update         |
| 2:00    | Open RECORD                                   | Full event timeline, integrity ✓   |
| 2:30    | Open SYS                                      | Live psutil RAM, CPU, disk, probes |
| 2:50    | `Ctrl+Shift+T` (V3 hold-over) → tamper demo   | Chain breaks at exact event        |

## Demo failure-mode shortcuts

| Shortcut             | Effect                                                  |
|----------------------|---------------------------------------------------------|
| `Ctrl+Shift+1/2/3`   | Replay canned voice for scenario 1/2/3                  |
| `Ctrl+Shift+T`       | Toggle tamper on most recent event                      |
| `Ctrl+Shift+I`       | Trigger image capture flow (V3 carry-over)              |

## V4 modules

```
backend/
  config.py            paths, env, INFERENCE_MODE switch
  models.py            Pydantic schemas
  db.py                SQLCipher connection mgmt + migrations
  records.py           encounters + events + SHA-256 chain
  crypto.py            hash utilities
  crypto_ed25519.py    V5 stub (Ed25519 signing)
  monitor.py           network probe coroutine + SSE
  scenarios.py         scenario defs + vital evolution
  retrieval.py         ChromaDB wrapper (existing)
  transcription.py     faster-whisper WS handler (existing)
  inference_mock.py    V4 fixture-driven streaming source
  inference.py         router (mock | live)
  system_status.py     psutil-driven telemetry
  main.py              FastAPI app
  ingest.py            corpus ingestion CLI
  fixtures/
    gsw_response.txt
    cardiac_response.txt
    pediatric_response.txt
  corpus/              source PDFs (gitignored)

frontend/
  index.html / styles.css / app.js     V1+V2.1+V3+V4 cockpit

tests/
  test_records.py      SHA-256 chain integrity round-trip
  query_corpus.py      retrieval CLI

aegis_data/            runtime data (gitignored)
  records.db
  chroma/
  ingest.log
  keys/
```

## Out of scope for V4

- Real LLM inference (V5)
- Ed25519 signing upgrade (V5; stub at `crypto_ed25519.py`)
- The V3 features (rPPG, calculators, interactions, queue, profiles,
  handoff) remain present where they were already built. V4 does not
  add to them; V4's job was to lock the substance beneath them.
