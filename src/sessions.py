"""Durable session store: chat history survives process death, like facts.

Same philosophy as memory.py — files under SESSIONS_DIR, atomic writes,
tolerant reads. Sessions are small; whole-store rewrite per save is fine.
Note: saves keep the most recent 40 turns (older turns drop from the file;
facts store carries the durable part).
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
    """Collision-free filename: readable prefix + short content hash.
    'a b' and 'a/b' map to DIFFERENT files (no cross-session bleed)."""
    import hashlib
    safe = "".join(c for c in session_id if c.isalnum() and c.isascii() or c in "-_")[:40]
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    name = f"{safe or 's'}-{digest}.json"
    return SESSIONS_DIR / name


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
    """Atomic write: unique tmp + os.replace (M5: per-call tmp, no clobber)."""
    import uuid
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(session_id).with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
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
