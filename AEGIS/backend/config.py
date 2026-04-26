"""
AEGIS V4 — central configuration.

The single switch that V5 flips is INFERENCE_MODE: "mock" routes through
inference_mock.py (V4 default), "live" routes through inference.py
real-Ollama path (V5).
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# When running on a NAT64-only Wi-Fi (some Cellular/Carrier networks,
# enterprise Wi-Fi with IPv6-only access), macOS can wrap literal
# IPv4 addresses into NAT64 prefixes and route them via Wi-Fi instead
# of the direct Cat6. This makes Mac → GX10 (192.168.100.2) calls
# time out even though the Cat6 link itself is healthy.
#
# Forcing socket.getaddrinfo to AF_INET stops the NAT64 indirection
# and pins literal IPv4 destinations to their direct route. Affects
# only outbound sockets in this Python process; the OS-level routing
# table is untouched.
if os.environ.get("AEGIS_FORCE_IPV4", "1") not in ("0", "false", "no"):
    import socket as _socket
    _orig_getaddrinfo = _socket.getaddrinfo

    def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, _socket.AF_INET, type, proto, flags)

    _socket.getaddrinfo = _ipv4_only_getaddrinfo


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "aegis_data"
CORPUS_DIR = BASE_DIR / "backend" / "corpus"
FIXTURES_DIR = BASE_DIR / "backend" / "fixtures"
FRONTEND_DIR = BASE_DIR / "frontend"

CHROMA_PATH = DATA_DIR / "chroma"
DB_PATH = DATA_DIR / "records.db"
INGEST_LOG = DATA_DIR / "ingest.log"
KEYS_DIR = DATA_DIR / "keys"

# Passphrase is generated once on first run and stored at ~/.aegis/passphrase
# (file mode 0600, regenerated only by operator action). Hardcoded passphrase
# is gone — V4 §2.4 bug fix.
def _load_or_create_passphrase() -> str:
    env = os.environ.get("AEGIS_DB_PASSPHRASE")
    if env:
        return env
    home = Path(os.environ.get("AEGIS_HOME", str(Path.home() / ".aegis")))
    home.mkdir(parents=True, exist_ok=True)
    pp_path = home / "passphrase"
    if pp_path.exists():
        return pp_path.read_text().strip()
    import secrets
    secret = secrets.token_hex(32)
    pp_path.write_text(secret)
    try:
        os.chmod(pp_path, 0o600)
    except Exception:
        pass
    return secret


DB_PASSPHRASE = _load_or_create_passphrase()
AEGIS_HOME = Path(os.environ.get("AEGIS_HOME", str(Path.home() / ".aegis")))

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# V5 — LLM via OpenAI-compatible endpoint (LM Studio locally, Ollama on GX10).
# LM Studio default: http://localhost:1234/v1
# Ollama default:    http://localhost:11434/v1
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://localhost:1234/v1")
LLM_MODEL    = os.environ.get("LLM_MODEL",    "google/gemma-4-31b")
LLM_API_KEY  = os.environ.get("LLM_API_KEY",  "lm-studio")
LLM_TEMPERATURE_STRUCTURED = float(os.environ.get("LLM_TEMPERATURE_STRUCTURED", "0.2"))
LLM_TEMPERATURE_NARRATIVE  = float(os.environ.get("LLM_TEMPERATURE_NARRATIVE",  "0.3"))
LLM_MAX_TOKENS_STRUCTURED  = int(os.environ.get("LLM_MAX_TOKENS_STRUCTURED",   "512"))
LLM_MAX_TOKENS_AAR         = int(os.environ.get("LLM_MAX_TOKENS_AAR",          "1024"))
LLM_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("LLM_REQUEST_TIMEOUT_SECONDS", "120"))

# Gemma 4 (and other "thinking" models served via Ollama's OpenAI-compat
# layer) emit a chain-of-thought into a separate `reasoning` field that
# consumes tokens BEFORE the visible `content`. For chat-style turns
# we want the model to skip CoT entirely and emit content directly —
# huge latency win (sub-second on warm calls). Verified knob:
#   reasoning_effort="none"   on POST /v1/chat/completions  → 0.5s
# (Ollama's own `think:false` only works on /api/chat, not the compat
#  layer; do not use it through the OpenAI SDK.)
# Allowed values: "none" | "minimal" | "low" | "medium" | "high"
# Set to empty/"default" to use the model's default reasoning behavior.
LLM_REASONING_EFFORT_DEFAULT = os.environ.get("LLM_REASONING_EFFORT_DEFAULT", "none")

# Local embeddings via sentence-transformers (in-process; no LLM dependency).
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5")
EMBED_DEVICE = os.environ.get("EMBED_DEVICE", "mps")  # mps for Apple Silicon
EMBED_DIM = int(os.environ.get("EMBED_DIM", "768"))   # nomic-embed-text-v1.5 = 768

# Prompt contracts (V5 — loaded from prompts/*.md)
PROMPTS_DIR = BASE_DIR / "prompts"

# The V4-to-V5 switch. "mock" or "live".
INFERENCE_MODE = os.environ.get("INFERENCE_MODE", "mock")

# Network monitor
MONITOR_PROBE_HOSTS = [("1.1.1.1", 53), ("8.8.8.8", 53)]
MONITOR_INTERVAL_SECONDS = 2.0
MONITOR_TIMEOUT_MS = 500

# Typewriter cadence — must match V1's visual contract
TYPEWRITER_CHARS_PER_SECOND = 28

# Build identity
BUILD_VERSION = "v4.0.0"
BUILD_DATE = "2026-04-25"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    CHROMA_PATH.mkdir(exist_ok=True)
    KEYS_DIR.mkdir(exist_ok=True)
    FIXTURES_DIR.mkdir(exist_ok=True)


ensure_dirs()
