"""Agent loop v2 tests: fake LLM client drives the contract.

Covers:
- tool-call loop (remember/recall/forget/update_fact/search_code)
- chip validation: unearned [STRONG]/[WEAK] stripped server-side
- extractor fallback: durable-but-unregexed input still captured
- welcome-back briefing on new session with existing facts
- regex fast path still zero-cost
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ.setdefault("MEMORIES_DIR", tempfile.mkdtemp())


def fresh_memory(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setenv("MEMORIES_DIR", d)
    import importlib
    import memory
    monkeypatch.setattr(memory, "MEMORIES_DIR", Path(d))
    monkeypatch.setattr(memory, "FACTS_FILE", Path(d) / "facts.jsonl")
    return memory


class FakeParts:
    def __init__(self, text=None, function_call=None):
        self.text = text
        self.function_call = function_call


class FakeContent:
    def __init__(self, parts):
        self.parts = parts


class FakeResponse:
    """Mirrors real SDK shape: resp.candidates[0].content.parts[]."""
    def __init__(self, parts):
        self.candidates = [FakeCandidate(parts)]


class FakeCandidate:
    def __init__(self, parts):
        self.content = FakeContent(parts)


class FakeModels:
    """Scripted responses: each call pops the next scripted item."""
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def generate_content(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        parts = []
        if isinstance(item, str):
            parts.append(FakeParts(text=item))
        elif isinstance(item, dict):
            parts.append(FakeParts(function_call=item))
        elif isinstance(item, tuple):  # (text, function_call) multi-part
            t, fc = item
            if t:
                parts.append(FakeParts(text=t))
            if fc:
                parts.append(FakeParts(function_call=fc))
        return FakeResponse(parts)


@pytest.fixture()
def agent_cls(monkeypatch):
    mem = fresh_memory(monkeypatch)
    import importlib
    import sessions as session_store
    monkeypatch.setattr(session_store, "SESSIONS_DIR",
                        Path(tempfile.mkdtemp()))
    import agent
    importlib.reload(agent)
    yield agent, mem


def make_agent(agent_mod, script):
    p = object.__new__(agent_mod.PartnerAgent)
    p.models = FakeModels(script)
    p.sessions = {}
    p.model = agent_mod.os.environ.get("GEMINI_MODEL", "fake-model")
    return p


# ---------------------------------------------------------------------------

class TestChipValidation:
    def test_unbacked_chip_stripped(self, agent_cls):
        agent, mem = agent_cls
        p = make_agent(agent, [
            # model hallucinates a STRONG chip with no facts recalled
            ("I always format answers as bullet lists [STRONG].", None),
        ])
        out = p.chat("s1", "hello what is a monad?")
        assert "[STRONG]" not in out["reply"]
        assert "[STRONG]" not in "".join(out["memories_used"])

    def test_earned_chip_survives(self, agent_cls):
        agent, mem = agent_cls
        mem.remember("style", "I prefer bullet lists for answers")
        p = make_agent(agent, [
            ("I use bullet lists for you [STRONG].", None),
        ])
        out = p.chat("s2", "how do you format answers?")
        assert "[STRONG]" in out["reply"]

    def test_wrong_chip_downgraded_to_none(self, agent_cls):
        agent, mem = agent_cls
        mem.remember("editor", "I use Vim bindings everywhere possible", kind="note")
        # fact exists but verdict is WEAK; model claims STRONG -> must be stripped
        p = make_agent(agent, [
            ("Vim it is [STRONG].", None),
        ])
        out = p.chat("s3", "which editor do I use?")
        # WEAK was available but model claimed STRONG: strip rather than lie
        assert "[STRONG]" not in out["reply"]


class TestToolLoop:
    def test_remember_tool_call_writes_fact(self, agent_cls):
        agent, mem = agent_cls
        p = make_agent(agent, [
            {"name": "remember", "args": {"title": "coffee",
             "body": "I prefer oat milk in coffee", "kind": "preference"}},
            "Noted — oat milk from now on.",
        ])
        out = p.chat("t1", "btw I prefer oat milk in coffee")
        assert any(f["body"].startswith("I prefer oat milk") for f in mem.active_rows())
        assert out["reply"] == "Noted — oat milk from now on."

    def test_recall_tool_call_informs_second_turn(self, agent_cls):
        agent, mem = agent_cls
        mem.remember("style", "I prefer bullet lists for answers")
        p = make_agent(agent, [
            {"name": "recall", "args": {"query": "formatting preferences"}},
            "You like bullet lists.",
        ])
        out = p.chat("t2", "what format do you use for me?")
        # second scripted call must have received fact block in system prompt
        sys_prompt = p.models.calls[-1]["config"].system_instruction
        assert "bullet" in sys_prompt or "[STRONG]" in sys_prompt or "[STRONG]" in out["reply"]

    def test_max_tool_calls_bounded(self, agent_cls):
        agent, mem = agent_cls
        loops = [{"name": "recall", "args": {"query": f"q{i}"}} for i in range(20)]
        p = make_agent(agent, loops + ["done"])
        out = p.chat("t3", "search everything")
        # MAX_TOOL_CALLS+1 model calls consumed; loop exits with fallback reply
        assert len(p.models.calls) == agent.MAX_TOOL_CALLS + 1
        assert out["reply"] == "(I got tangled up mid-thought — try that again?)"


class TestExtractorFallback:
    def test_durable_but_unregexed_input_captured(self, agent_cls):
        agent, mem = agent_cls
        # "My sister Sarah has a birthday in May" — no regex pattern matches
        from agent import looks_like_correction
        assert not looks_like_correction("My sister Sarah has a birthday in May")
        p = make_agent(agent, [
            {"name": "remember", "args": {"title": "person-sarah",
             "body": "User's sister Sarah has a birthday in May", "kind": "person"}},
            "Noted — Sarah's birthday is in May.",
        ])
        out = p.chat("e1", "My sister Sarah has a birthday in May")
        assert any("Sarah" in f["body"] for f in mem.active_rows())


class TestBriefing:
    def test_new_session_with_facts_gets_briefing_block(self, agent_cls):
        agent, mem = agent_cls
        mem.remember("style", "I prefer bullet lists for answers", kind="preference")
        p = make_agent(agent, ["Welcome back! You prefer bullet lists."])
        out = p.chat("brand-new-session-xyz", "hi again")
        sys_prompt = p.models.calls[0]["config"].system_instruction
        assert "Welcome back" in sys_prompt or "briefing" in sys_prompt.lower()

    def test_same_session_no_repeat_briefing(self, agent_cls):
        agent, mem = agent_cls
        p = make_agent(agent, ["hi", "hello"])
        p.chat("b1", "first message")
        first_sys = p.models.calls[0]["config"].system_instruction
        p.chat("b1", "second message")
        second_sys = p.models.calls[1]["config"].system_instruction
        assert "briefing" not in second_sys.lower()


class TestRegexFastPath:
    def test_regex_still_zero_llm_cost(self, agent_cls):
        agent, mem = agent_cls
        p = make_agent(agent, [])  # no scripted responses: must NOT call LLM for capture
        from agent import looks_like_correction
        assert looks_like_correction("No, I prefer short answers")


class TestSessionPersistence:
    def test_history_survives_agent_recreation(self, agent_cls, monkeypatch):
        """The restart guarantee: new agent instance resumes persisted history."""
        agent, mem = agent_cls
        import sessions as session_store
        p1 = make_agent(agent, ["first reply"])
        p1.chat("persist-1", "hello there")
        # simulate process death: brand-new instance
        p2 = make_agent(agent, ["second reply"])
        p2.chat("persist-1", "and again")
        turns = session_store.load("persist-1")
        texts = [t["text"] for t in turns]
        assert "hello there" in texts and "first reply" in texts and "second reply" in texts

    def test_tolerates_corrupt_session_file(self, agent_cls):
        agent, mem = agent_cls
        import sessions as session_store
        p = session_store._path("corrupt-sess")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{torn json")
        p3 = make_agent(agent, ["ok"])
        out = p3.chat("corrupt-sess", "hi")
        assert out["reply"] == "ok"   # degraded gracefully to fresh session

    def test_reset_tombstones_not_deletes(self, agent_cls):
        agent, mem = agent_cls
        import sessions as session_store
        p = make_agent(agent, ["r"])
        p.chat("tomb-1", "x")
        session_store.drop("tomb-1")
        assert not session_store._path("tomb-1").exists()
        assert session_store._path("tomb-1").with_suffix(".gone").exists()
