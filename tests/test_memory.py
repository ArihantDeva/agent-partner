"""Memory layer tests — file-backed facts + verdict honesty."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import memory  # noqa: E402


@pytest.fixture()
def mem_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORIES_DIR", str(tmp_path / "memories"))
    monkeypatch.setattr(memory, "MEMORIES_DIR", tmp_path / "memories")
    monkeypatch.setattr(memory, "FACTS_FILE", tmp_path / "memories" / "facts.jsonl")
    return tmp_path / "memories"


class TestRemember:
    def test_append_valid_jsonl(self, mem_dir):
        assert memory.remember("style", "I prefer terse replies") is True
        lines = (mem_dir / "facts.jsonl").read_text().strip().split("\n")
        rec = json.loads(lines[0])
        assert rec["title"] == "style"
        assert "terse" in rec["body"]

    def test_rejects_empty(self, mem_dir):
        assert memory.remember("", "body") is False
        assert memory.remember("t", "  ") is False

    def test_latest_wins_same_title(self, mem_dir):
        memory.remember("lang", "I use Python daily")
        memory.remember("lang", "I now use Rust daily")
        hits = memory.recall("Rust", 5)
        assert any("Rust" in h["body"] for h in hits)
        assert not any("Python" in h["body"] for h in hits)


class TestRecallVerdicts:
    def test_strong_multi_term(self, mem_dir):
        memory.remember("style", "I prefer terse replies and working code over long explanations")
        hits = memory.recall("does the user want terse replies?", 3)
        assert hits and hits[0]["verdict"] == "STRONG"

    def test_weak_single_fuzzy(self, mem_dir):
        memory.remember("editor", "I use Vim bindings everywhere possible", kind="assertion")
        hits = memory.recall("editor setup", 3)  # single overlap term: editor
        assert hits and hits[0]["verdict"] == "WEAK"

    def test_miss_returns_empty(self, mem_dir):
        memory.remember("style", "I prefer terse replies")
        assert memory.recall("quantum chromodynamics homework", 3) == []

    def test_recency_boost_preference(self, mem_dir):
        memory.remember("coffee", "I prefer oat milk in coffee")
        hits = memory.recall("oat milk", 3)
        assert hits[0]["verdict"] == "STRONG"  # fresh preference


class TestContextBlock:
    def test_chips_rendered(self, mem_dir):
        memory.remember("style", "I prefer terse replies and short code samples")
        block = memory.context_block("reply style", 3)
        assert "[STRONG]" in block or "[WEAK]" in block
        assert "terse" in block

    def test_empty_when_no_match(self, mem_dir):
        assert memory.context_block("unrelated gibberish query", 3) == ""


class TestCodeRecall:
    def test_returns_list_never_raises(self, mem_dir, monkeypatch):
        monkeypatch.setattr(memory, "_run", lambda a, timeout=60: "")
        assert memory.recall_code("anything") == []

    def test_parses_heimdall_output(self, mem_dir, monkeypatch):
        sample = "== retrieve: x\n 1. [STRONG] cov50%  /repo/f.py\n      f · function\n"
        monkeypatch.setattr(memory, "_run", lambda a, timeout=60: sample)
        hits = memory.recall_code("x")
        assert hits[0]["verdict"] == "STRONG"
        assert hits[0]["path"] == "/repo/f.py"


class TestRobustness:
    def test_torn_write_skipped(self, mem_dir):
        FACTS = mem_dir / "facts.jsonl"
        mem_dir.mkdir(parents=True, exist_ok=True)
        good = json.dumps({"ts": time.time(), "title": "t", "body": "I prefer tea", "kind": "preference"})
        FACTS.write_text(good + "\n{torn json\n")
        hits = memory.recall("tea", 3)
        assert len(hits) == 1

    def test_missing_file(self, mem_dir):
        assert memory._facts() == []


class TestConcurrencyAndBypasses:
    def test_concurrent_remembers_all_persist(self, mem_dir):
        """10 threads writing distinct titles -> all 10 readable after."""
        import threading
        threads = [
            threading.Thread(target=memory.remember,
                             args=(f"t{i}", f"fact number {i} about topic {i}"))
            for i in range(10)
        ]
        [t.start() for t in threads]
        [t.join() for t in threads]
        rows = memory.active_rows()
        titles = {r["title"] for r in rows}
        assert {f"t{i}" for i in range(10)} <= titles

    def test_concurrent_same_title_last_write_readable(self, mem_dir):
        """Racing writers on one title leave a readable, non-corrupt store."""
        import threading
        def w(n):
            memory.remember("race", f"writer {n} says the thing {n}")
        threads = [threading.Thread(target=w, args=(i,)) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        # every row parses; at least one active 'race' fact survives
        rows = [r for r in memory._load() if r.get("title") == "race"]
        assert rows and any(r["status"] == "active" for r in rows)
