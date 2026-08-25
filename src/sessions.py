"""Durable session store: chat history survives process death, like facts.

Same philosophy as memory.py — files under SESSIONS_DIR, atomic writes,
tolerant reads. Sessions are small; whole-store rewrite per save is fine.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

SESSIONS_DIR = Path(os.environ.get(
    "SESSIONS_DIR",
    str(Path(__file__).resolve().parent.parent / "sessions"),
))


def _path(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")[:80]
    return SESSIONS_DIR / f"{safe or 'default'}.json"


def load(session_id: str) -> list[dict] | None:
    p = _path(session_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return data.get("turns", [])
    except json.JSONDecodeError:
        return None


def save(session_id: str, turns: list[dict]) -> None:
    """Atomic write: tmp + os.replace."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(session_id).with_suffix(".tmp")
    payload = json.dumps({"session_id": session_id, "saved_at": int(time.time()),
                          "turns": turns[-40:]})
    tmp.write_text(payload)
    os.replace(tmp, _path(session_id))


def drop(session_id: str) -> bool:
    p = _path(session_id)
    if p.exists():
        os.replace(p, p.with_suffix(".gone"))  # tombstone, not delete: audit
        return True
    return False
