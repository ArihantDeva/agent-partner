"""Server tests via TestClient — no real LLM (PartnerAgent patched out)."""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORIES_DIR", str(tmp_path / "mem"))
    monkeypatch.setattr(memory := __import__("memory"), "MEMORIES_DIR", tmp_path / "mem")
    monkeypatch.setattr(memory, "FACTS_FILE", tmp_path / "mem" / "facts.jsonl")
    # stub agent so tests never call Gemini
    class FakeAgent:
        def __init__(self): self.sessions = {}
        def chat(self, sid, msg):
            if not sid:
                raise ValueError("bad session")
            return {"reply": f"echo:{msg}", "memories_used": ["STRONG"], "remembered": []}
    import server
    monkeypatch.setattr(server, "get_agent", lambda: FakeAgent())
    from fastapi.testclient import TestClient
    return TestClient(server.app)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_chat_roundtrip(client):
    r = client.post("/chat", json={"session_id": "s1", "message": "hello"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "echo:hello"
    assert body["memories_used"] == ["STRONG"]


def test_chat_validates_empty_message(client):
    assert client.post("/chat", json={"session_id": "s", "message": "  "}).status_code == 422


def test_chat_validates_length(client):
    r = client.post("/chat", json={"session_id": "s", "message": "x" * 8001})
    assert r.status_code == 422


def test_reset(client):
    client.post("/chat", json={"session_id": "sx", "message": "hi"})
    r = client.post("/sessions/sx/reset")
    assert r.json() == {"reset": True}


def test_memories_endpoint_empty(client):
    assert client.get("/memories").json() == []
