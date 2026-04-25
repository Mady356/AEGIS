"""
Network monitor — TCP probes to public DNS resolvers as the read-only
"the network is reachable but we don't use it" signal.

The probe sends nothing. It opens a TCP socket and immediately closes.
No payload. No DNS query. Just connectivity confirmation.
"""

from __future__ import annotations

import asyncio
import socket
import time
from datetime import datetime, timezone
from typing import Optional

from . import config

_history: list[dict] = []
_subs: list[asyncio.Queue] = []
_last: Optional[dict] = None
_last_change: Optional[str] = None
_task: Optional[asyncio.Task] = None


async def _probe_one(host: str, port: int) -> tuple[bool, Optional[int]]:
    t0 = time.monotonic()
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(
            fut, timeout=config.MONITOR_TIMEOUT_MS / 1000.0
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        try:
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), timeout=0.1)
        except Exception:
            pass
        return True, latency_ms
    except Exception:
        return False, None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


async def _loop() -> None:
    global _last, _last_change
    while True:
        host_results = []
        any_ok = False
        for host, port in config.MONITOR_PROBE_HOSTS:
            ok, lat = await _probe_one(host, port)
            host_results.append({
                "host": f"{host}:{port}", "ok": ok, "latency_ms": lat,
            })
            if ok:
                any_ok = True
        ts = _now_iso()
        ev = {"reachable": any_ok, "last_probe_at": ts,
              "host_results": host_results}
        if _last is None or _last["reachable"] != any_ok:
            _last_change = ts
        _last = ev
        _history.append(ev)
        # V4 §2.4 fix — was: del _history[0:-30] (off-by-one, truncates wrong end)
        if len(_history) > 30:
            _history[:] = _history[-30:]
        for q in list(_subs):
            try:
                if q.full():
                    try: q.get_nowait()
                    except Exception: pass
                q.put_nowait(ev)
            except Exception:
                pass
        await asyncio.sleep(config.MONITOR_INTERVAL_SECONDS)


async def start() -> None:
    global _task
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="aegis-network-monitor")


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        try: await _task
        except asyncio.CancelledError: pass
        _task = None


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subs.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    try: _subs.remove(q)
    except ValueError: pass


def last() -> Optional[dict]: return _last
def history() -> list[dict]: return list(_history)
def last_state_change() -> Optional[str]: return _last_change
