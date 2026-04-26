#!/usr/bin/env bash
# AEGIS V4 — fresh-laptop bring-up script.
#
# Run from the project root. Takes a clean machine from "OS installed" to
# "AEGIS running" in under 5 minutes assuming a working internet connection.
#
# Idempotent: re-running picks up where it left off.

set -euo pipefail
cd "$(dirname "$0")"

color() { printf "\033[%sm%s\033[0m\n" "$1" "$2"; }
info()  { color "1;33" "[AEGIS] $*"; }
ok()    { color "1;32" "[AEGIS] $*"; }
warn()  { color "1;31" "[AEGIS] $*"; }

PYTHON_BIN="${PYTHON_BIN:-python3}"
SKIP_OLLAMA="${SKIP_OLLAMA:-0}"
SKIP_INGEST="${SKIP_INGEST:-0}"

# ---------------------------------------------------------------------
info "step 1/7  installing Ollama (if missing)"
if ! command -v ollama >/dev/null 2>&1 && [ "$SKIP_OLLAMA" != "1" ]; then
  if [[ "$(uname)" == "Darwin" ]]; then
    if command -v brew >/dev/null; then
      brew install ollama
    else
      warn "Homebrew not installed; install Ollama from https://ollama.com/download"
    fi
  else
    curl -fsSL https://ollama.com/install.sh | sh
  fi
fi
ok "Ollama present (or skipped via SKIP_OLLAMA=1)"

# ---------------------------------------------------------------------
info "step 2/7  starting Ollama in the background"
if [ "$SKIP_OLLAMA" != "1" ]; then
  if ! pgrep -f "ollama serve" >/dev/null 2>&1; then
    (ollama serve >/tmp/aegis-ollama.log 2>&1 &)
    sleep 3
  fi
fi
ok "Ollama serving"

# ---------------------------------------------------------------------
info "step 3/7  pulling models (gemma2:9b-instruct-q4_K_M, nomic-embed-text)"
if [ "$SKIP_OLLAMA" != "1" ]; then
  ollama pull gemma2:9b-instruct-q4_K_M || warn "gemma pull failed; demo will use canned"
  ollama pull nomic-embed-text || warn "embed model pull failed; ingest will fall back"
fi
ok "models pulled"

# ---------------------------------------------------------------------
info "step 4/7  Python venv + deps"
if [ ! -d venv ]; then
  $PYTHON_BIN -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt
ok "deps installed"

# ---------------------------------------------------------------------
info "step 5/7  generating device keys"
$PYTHON_BIN -m backend.crypto_ed25519 init
ok "device keys ready"

# ---------------------------------------------------------------------
info "step 6/7  ingesting corpus"
if [ "$SKIP_INGEST" != "1" ]; then
  $PYTHON_BIN -m backend.ingest
fi
ok "corpus ingested"

# ---------------------------------------------------------------------
info "step 7/7  running evals"
if [ -f tests/run_evals.py ]; then
  $PYTHON_BIN tests/run_evals.py || warn "evals not all passing — review tests/eval_*.json"
fi
ok "evals complete"

# ---------------------------------------------------------------------
info "starting backend on http://127.0.0.1:8000"
exec uvicorn backend.main:app --host 127.0.0.1 --port 8000
