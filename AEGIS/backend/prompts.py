"""
V5 — Prompt contract loader.

Reads prompts/*.md and returns {system, user_template, schema?} dicts.

File format — three delimited sections:

    ---SYSTEM---
    <system prompt body>

    ---USER_TEMPLATE---
    <user prompt template, with {placeholders}>

    ---SCHEMA---     (optional)
    <JSON schema description, can be referenced by the template>

The loader is cached so repeated calls during a request are free.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from . import config

DELIM_PREFIX = "---"
DELIM_SUFFIX = "---"


@lru_cache(maxsize=8)
def load_prompt(name: str) -> dict[str, str]:
    """Load prompts/<name>.md and return its sections as a dict.

    The dict keys are lowercase section names (e.g. 'system', 'user_template').
    Section bodies are stripped of surrounding whitespace.
    """
    path: Path = config.PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {path}. "
            f"V5 expects prompts/{name}.md to exist."
        )

    raw = path.read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    buffer: list[str] = []

    for line in raw.splitlines():
        stripped = line.strip()
        if (stripped.startswith(DELIM_PREFIX)
                and stripped.endswith(DELIM_SUFFIX)
                and len(stripped) >= 6):
            if current is not None:
                sections[current] = buffer
            # "---SYSTEM---" → "system"
            current = stripped.strip("- ").strip().lower()
            buffer = []
        else:
            buffer.append(line)
    if current is not None:
        sections[current] = buffer

    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def render_user_prompt(name: str, **kwargs) -> tuple[str, str]:
    """Convenience: load prompt and substitute placeholders.

    Returns (system_prompt, rendered_user_prompt).
    """
    sections = load_prompt(name)
    system = sections.get("system", "")
    template = sections.get("user_template", "")
    return system, template.format(**kwargs)
