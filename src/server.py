"""HTTP wrapper for Cloud Run. Endpoints:
- GET  /healthz          liveness (touches neither memory nor LLM)
- POST /chat             {session_id, message} -> {reply, memories_used, remembered}
- POST /sessions/{id}/reset   drop in-memory history (facts persist)
- GET  /memories         current fact list (debug/transparency for judges)
"""
from __future__ import annotations

import os
import sys
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, str(os.path.dirname(os.path.abspath(__file__))))
import memory  # noqa: E402
from agent import PartnerAgent  # noqa: E402

app = FastAPI(title="Partner — Collaborative Memory Agent")
_agent: PartnerAgent | None = None


def get_agent() -> PartnerAgent:
    global _agent
    if _agent is None:
        _agent = PartnerAgent()
    return _agent


class ChatIn(BaseModel):
    session_id: str
    message: str


class ChatOut(BaseModel):
    reply: str
    memories_used: list[str]
    remembered: list[str]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatOut)
def chat(body: ChatIn) -> dict[str, Any]:
    if not body.message.strip():
        raise HTTPException(422, "message must not be empty")
    if len(body.message) > 8000:
        raise HTTPException(422, "message too long (max 8000 chars)")
    try:
        return get_agent().chat(body.session_id, body.message)
    except Exception as e:  # surface provider errors cleanly
        raise HTTPException(502, f"upstream error: {e}") from e


@app.post("/sessions/{session_id}/reset")
def reset(session_id: str) -> dict[str, bool]:
    """Drop live session AND its persisted history (facts stay).
    Idempotent: resetting an unknown session also reports success."""
    agent = get_agent()
    agent.sessions.pop(session_id, None)
    import sessions as session_store
    session_store.drop(session_id)
    return {"reset": True}


@app.post("/sleep")
def run_sleep() -> dict:
    """Consolidation cycle: merge dupes, decay unused, promote reinforced."""
    return memory.sleep()


@app.get("/stats")
def stats() -> dict:
    rows = memory._load()
    active = [r for r in memory.active_rows()]
    verdicts: dict[str, int] = {}
    for r in active:
        v = memory.verdict_of(r["title"])
        verdicts[v] = verdicts.get(v, 0) + 1
    return {
        "total_records": len(rows),
        "active_facts": len(active),
        "verdicts": verdicts,
        "kinds": sorted({r["kind"] for r in active}),
        "sessions_live": len(get_agent().sessions),
    }


@app.get("/memories/{title}/history")
def fact_history(title: str) -> list[dict]:
    trail = memory.history_of(title)
    if not trail:
        raise HTTPException(404, f"no such fact: {title}")
    return trail


@app.get("/memories")
def memories() -> list[dict]:
    return memory._facts()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
