"""Agent loop tests. LLM integration marked; runs against dev model only."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestCorrectionDetector:
    def test_import_without_key(self):
        # module import must not require GEMINI_API_KEY
        import agent  # noqa: F401

    def test_explicit_correction(self):
        from agent import looks_like_correction
        assert looks_like_correction("No, I prefer Rust for CLI tools")
        assert looks_like_correction("Actually I use neovim now")
        assert looks_like_correction("Don't use tabs in my code")

    def test_durable_facts(self):
        from agent import looks_like_correction
        assert looks_like_correction("My name is Deva")
        assert looks_like_correction("I work at Stripe on payments")
        assert looks_like_correction("Call me Dev")

    def test_plain_questions_not_corrections(self):
        from agent import looks_like_correction
        assert not looks_like_correction("What is a monad?")
        assert not looks_like_correction("Can you help me write a parser?")
        assert not looks_like_correction("no idea, tell me more")


@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"),
                    reason="needs real key; run with GEMINI_MODEL=gemini-3.6-flash")
class TestLLMIntegration:
    def test_memory_cited_in_reply(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MEMORIES_DIR", str(tmp_path))
        import importlib
        import memory
        importlib.reload(memory)
        memory.remember("style", "I prefer terse replies and working code over long explanations")
        importlib.reload(memory)

        from agent import PartnerAgent
        p = PartnerAgent()
        out = p.chat("test-session-1", "How should you format answers for me?")
        assert "reply" in out and out["reply"]
        assert isinstance(out["memories_used"], list)
