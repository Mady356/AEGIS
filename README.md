AEGIS
The network is optional. Care is not.

Autonomous Emergency Guidance & Intelligence System. A fully offline, fully working clinical decision-support cockpit for non-expert first responders in austere environments — refugee triage, submarines, combat, disaster zones, remote rescue. Real local LLM inference, real corpus-grounded reasoning, real encrypted records, no cloud round-trips.

Status: working end-to-end
LLM: Gemma 4 26B-A4B (Mixture-of-Experts; 4B active per token) running on an NVIDIA GB10 (DGX Spark / GX10), served by Ollama over its OpenAI-compatible endpoint at http://192.168.100.2:11434/v1.
Embeddings: nomic-embed-text (Q5_K_M, 768-dim) on the same GX10.
Mac ↔ GX10 link: direct Cat6 10GbE, static 192.168.100.1 ↔ .2.
Chat: multi-turn, situation-aware, RAG-grounded against the medical corpus, citation chips clickable. Sub-second to 2 s per turn warm.
Encounter intake: operator types the situation, the LLM generates the procedural step graph + a structured brief (acuity / top actions / rule-outs) on the spot, grounded in TCCC, AHA, ILCOR, WHO sources.
Records: SQLite + SHA-256 chained events; every operator action, every chat turn, every step transition is hashed and audit-trailed.
STT: faster-whisper base.en on the Mac, real-time microphone capture.
Network monitor: live TCP probes to 1.1.1.1:53 and 8.8.8.8:53 so the cockpit can prove it stays useful when those probes time out.
Component	What's running
LLM	Gemma 4 26B-A4B on GB10 via Ollama (/v1/chat/completions)
Embeddings	nomic-embed-text on GB10 via Ollama (/api/embed)
Vector store	ChromaDB persistent, on the Mac
Speech-to-text	faster-whisper base.en, in-process on the Mac
Records	SQLite + SHA-256 chain (SQLCipher when pysqlcipher3 is up)
Backend API	FastAPI / uvicorn on 127.0.0.1:8000
Frontend	static HTML/CSS/JS served by uvicorn
Network monitor	TCP probes 1.1.1.1:53 + 8.8.8.8:53
Reasoning effort	reasoning_effort: "none" on the OpenAI-compat layer →
Gemma emits content directly; sub-second chat
Reasoning pipeline (offline-first, fail-soft)
Every reasoning pass funnels through one orchestrator that wraps the agent stages with two safety layers:

intake (typed/voice) ──► failsafe.check_insufficient_data
                              │
                              ├── halts and asks the 3 essential questions
                              │   if conscious / breathing / bleeding are
                              │   missing in a high-risk situation
                              │
                              ▼
                    orchestrator.run_encounter[_async]
                              │
              ┌── rules ──┬── triage ──┬── differential ──┬── risk
              │           │            │                  │
              └── protocol ┴── missed_signals ┴── questions
                              │
                              ▼
                  crisis.build_crisis_view  ◄── one-screen JSON view,
                              │                 capped at 3 items per list
                              ▼
                  learning.generate_learning_point
                              │
                              ▼
                  tone.add_human_guidance   ◄── short calm message
                              │                 keyed off acuity
                              ▼
                       PipelineResponse
Properties this gives you:

Fail-soft stages. Each stage is a pluggable callable. If a stage raises, the orchestrator captures the trace, marks that stage error in reasoning_trace, and continues with the rest of the pipeline. Partial reasoning is better than a crashed reasoner.
Single LLM round-trip per encounter. When LLM_AGENTS are wired in, the first stage to run primes a shared bundle and the rest slice their section out — seven stage outputs from one inference call.
Always-on failsafe. If the encounter is too sparse to reason safely, the orchestrator skips the agents and returns a crisis view whose only content is the three-question survival screen.
No diagnostic claims. Prompts and post-processing enforce rule-out / check-next / escalate phrasing. The LLM is asked for short imperative items, not paragraphs.
Run
Mac side (cockpit + records + STT + ChromaDB)
# 1. Python deps
cd AEGIS
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Point at the GX10 (already the default in .env)
#    LLM_ENDPOINT=http://192.168.100.2:11434/v1
#    LLM_MODEL=gemma-4-26b-a4b
#    LLM_REASONING_EFFORT_DEFAULT=none

# 3. Build the corpus index (embeddings come from the GX10)
python -m backend.ingest

# 4. Start the backend
uvicorn backend.main:app --host 127.0.0.1 --port 8000
# Open http://127.0.0.1:8000
GX10 side (LLM + embeddings, one-time)
gemma-4-26b-a4b and nomic-embed-text are sideloaded into Ollama on the GX10 (no internet required after install):

# On the GX10, with both GGUFs scp'd from the Mac:
sudo bash /tmp/install_ollama.sh
# Listens on 0.0.0.0:11434, persists across reboots via systemd.
The cable is configured manually on both ends:

# Mac
sudo networksetup -setmanual Ethernet 192.168.100.1 255.255.255.0 ""
# GX10
sudo nmcli connection add type ethernet ifname enP7s7 con-name gx10-direct \
  ipv4.method manual ipv4.addresses 192.168.100.2/24 ipv6.method ignore
sudo nmcli connection up gx10-direct
AEGIS_FORCE_IPV4=1 (default in backend/config.py) keeps Mac → GX10 HTTP traffic on the direct IPv4 path even on NAT64 Wi-Fi networks that would otherwise wrap literal IPv4 addresses into 2607:7700::/96 and route them via Wi-Fi.

How a session works
Boot → encounter intake overlay appears. Operator types the situation: "Adult male, GSW left thigh, arterial bleed, tourniquet placed 90 s ago, conscious, pulse 120."
Begin Encounter → POST /api/encounter/begin sends the situation to the LLM. Gemma generates the encounter scaffold: title, patient label, ordered procedural steps with icons, and a structured brief (acuity, top actions, rule-outs) with corpus citations.
Cockpit populates — CURRENT STEP card, JUMP TO STEP cards, PROCEDURAL CHECKLIST, and the right-column ASK AEGIS chat shows the brief as the first assistant turn.
Operator works the encounter — voice intake (Whisper) extracts structured facts that auto-tick checklist items. Chat handles freeform clinical questions in 1–2 s per turn, every reply RAG-grounded with citation chips that open the source chunk.
Step transitions persist to the encrypted record store. Every chat turn is hashed and chained. Tamper attempts break the chain at the exact event.
End of encounter → handoff packet builds with the full audit trail.
Key endpoints (V6)
Method	Path	Purpose
POST	/api/encounter/begin	Situation → LLM-generated scaffold + brief
POST	/api/chat	Multi-turn RAG-grounded chat
GET	/api/encounter/{id}/situation	Restore prefill on reload
POST	/api/encounter/{id}/situation	Persist operator-set situation
GET	/api/encounter/{id}/procedural-steps	Step graph + current step
POST	/api/encounter/{id}/advance-step	Advance with optional yes/no
GET	/api/encounter/{id}/context-log	Chronological extracted phrases
GET	/api/encounter/{id}/integrity	SHA-256 chain verification report
WS	/api/transcribe	Whisper streaming STT
GET	/api/system/status	Live LLM + embed + corpus telemetry
Demo failure-mode shortcuts
Shortcut	Effect
Ctrl+Shift+1/2/3	Replay canned voice for scenario 1 / 2 / 3
Ctrl+Shift+T	Toggle tamper on most recent event
Ctrl+Shift+I	Trigger image capture flow
Project layout
backend/
  main.py              FastAPI app + V6 routes + lifespan hooks
  config.py            paths, env, AEGIS_FORCE_IPV4 socket override
  models.py            Pydantic request/response schemas
  inference.py         OpenAI-compat client; chat_completion + reasoning_effort
  embeddings.py        urllib client → GX10 /api/embed
  retrieval.py         ChromaDB wrapper, async embed_text
  ingest.py            corpus ingestion CLI (embeds via GX10)
  prompts.py           prompt template renderer

  intake.py            structured intake question bank → encounter dict
  llm_agents.py        single-bundle LLM agents + intake_to_encounter
  procedural_steps.py  step graph helpers (scenario-default + LLM-generated)
  orchestrator.py      pipeline runner; sync + async; fault-tolerant
  failsafe.py          insufficient-data check; halts before agents run
  crisis.py            one-screen crisis_view assembly (capped at 3/list)
  learning.py          one-sentence learning takeaway
  tone.py              human-tone wrapper (calm message keyed off acuity)

  records.py           encounters + events + SHA-256 chain
  db.py                SQLite migration + SQLCipher fallthrough
  crypto.py            symmetric helpers
  crypto_ed25519.py    signing chain stub (V5 upgrade path)
  handoff.py           signed handoff packet (.zip + manifest)
  pilot_brief.py       brief generation helpers
  trust_surface.py     trust badges + status hints for the cockpit
  monitor.py           network probe coroutine + SSE
  scenarios.py         scenario defs + vital evolution
  transcription.py     faster-whisper WS handler
  system_status.py     psutil-driven telemetry
  corpus/chunks/       chunked .md sources (TCCC, AHA, ILCOR, WHO-PED)

frontend/
  index.html           V5 cockpit: intake overlay, current step, chat, vitals
  app.js               state machine, intake, chat, situation, procedural
  styles.css           amber-on-black documentation aesthetic
  crisis.html          one-screen crisis view
  crisis.js            crisis view bootstrapping
  crisis.css           crisis view styles
  crisis_panel.js      embeddable crisis panel for the cockpit
  ambient/             ambient flow-field background

prompts/
  extraction.md / qa.md / nudges.md / aar.md

tests/
  test_records.py      SHA-256 chain integrity round-trip
  query_corpus.py      retrieval CLI
  run_evals.py         four-prompt eval harness

aegis_data/            runtime data (gitignored)
  records.db
  chroma/
  ingest.log
  keys/
Tests
The records chain test runs entirely offline against a temp DB and is the fastest way to confirm a fresh checkout works:

source venv/bin/activate
python -m tests.test_records
# expected: PASS  (creates encounter, writes 20 events, tampers + heals)
Quick orchestrator smoke check (uses the no-op fallback agents — no LLM needed):

python -c "
from backend.orchestrator import run_encounter
out = run_encounter({
    'chief_complaint': 'Chest pain and shortness of breath',
    'mental_status': 'yes', 'breathing': 'no', 'bleeding': 'none',
    'vitals': {'heart_rate': 128, 'spo2': 90},
})
print('acuity:', out['crisis_view']['acuity'],
      '| stages:', out['audit']['stages_run'],
      '| cloud_calls:', out['offline_status']['cloud_calls'])
"
The four-prompt eval harness (extraction / QA / nudges / AAR) requires the LLM to be reachable:

python tests/run_evals.py
Configuration knobs
Set in .env at the project root:

Variable	Default	Notes
LLM_ENDPOINT	http://192.168.100.2:11434/v1	Ollama OpenAI-compat on the GX10
LLM_MODEL	gemma-4-26b-a4b	Sideloaded GGUF (Q4_K_M, 16 GB)
LLM_API_KEY	ollama	Anything; Ollama doesn't auth
LLM_REASONING_EFFORT_DEFAULT	none	"none" | "minimal" | "default"
LLM_TEMPERATURE_STRUCTURED	0.2	JSON-output endpoints
LLM_TEMPERATURE_NARRATIVE	0.3	Streaming AAR + chat
LLM_REQUEST_TIMEOUT_SECONDS	120	Per HTTP request
EMBED_MODEL	nomic-embed-text	Ollama tag on the GX10
AEGIS_FORCE_IPV4	1	Pin sockets to AF_INET (NAT64 fix)
Out of scope
Cloud APIs of any kind. AEGIS is offline-first by design.
The Ed25519 signing column upgrade (stub at crypto_ed25519.py).
iOS / Android cockpit (Mac-tethered cockpit only).
