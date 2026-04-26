"""
SQLCipher-encrypted SQLite connection management + migrations.

Tries pysqlcipher3 first (encrypted at rest); falls back to plain
sqlite3 with a console warning. The schema is identical either way —
encryption is transparent at the driver level.
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from typing import Iterator

from . import config

_USING_CIPHER = False


def _new_conn():
    global _USING_CIPHER
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher  # type: ignore
        conn = sqlcipher.connect(str(config.DB_PATH))
        conn.execute(f"PRAGMA key = '{config.DB_PASSPHRASE}'")
        _USING_CIPHER = True
    except Exception:
        conn = sqlite3.connect(str(config.DB_PATH))
        if not _USING_CIPHER:
            print(
                "[db] pysqlcipher3 unavailable — using plain sqlite3. "
                "Records are NOT encrypted at rest in this run.",
                file=sys.stderr,
            )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = _new_conn()
    try:
        yield conn
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS encounters (
    id              TEXT PRIMARY KEY,
    scenario_id     TEXT NOT NULL,
    patient_label   TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    integrity_hash  TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id    TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    t_offset_ms     INTEGER NOT NULL,
    payload_json    TEXT NOT NULL,
    hash            TEXT NOT NULL,
    prev_hash       TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (encounter_id) REFERENCES encounters(id)
);

CREATE INDEX IF NOT EXISTS idx_events_encounter ON events(encounter_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id    TEXT,
    action          TEXT NOT NULL,
    actor           TEXT,
    timestamp       TEXT NOT NULL
);
"""


def migrate() -> None:
    with connection() as conn:
        for stmt in SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(s)
        conn.commit()


def is_encrypted() -> bool:
    return _USING_CIPHER


def storage_size_mb() -> float | None:
    try:
        return round(config.DB_PATH.stat().st_size / (1024 * 1024), 2)
    except Exception:
        return None
