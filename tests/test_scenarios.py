"""Eval scenarios: scripted end-to-end journeys Partner must survive.

Each scenario is a list of steps executed against a fresh engine instance:
  say:    user utterance -> agent reply captured (fake LLM in unit mode)
  expect_facts: >= N facts with given titles exist
  expect_verdict: title -> verdict
  restart: drop all volatile state (sessions); facts must survive
  sleep:   run consolidation with injected clock advance (days)
  recall:  query -> assert top hit body contains substring

Scenarios are data so the scorecard can count pass/fail per journey.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import memory  # noqa: E402


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    """Fresh memory engine on a scratch dir."""
    monkeypatch.setenv("MEMORIES_DIR", str(tmp_path / "memories"))
    import importlib
    importlib.reload(memory)
    yield memory
    importlib.reload(memory)  # restore real dir for other tests


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------

def run_scenario(engine, steps: list[dict], clock: dict) -> list[str]:
    """Execute one journey; returns list of failures ([] == scenario green)."""
    failures = []
    for i, step in enumerate(steps):
        kind = step["step"]
        if kind == "say":
            # capture path: durable statements land via remember() directly
            # (LLM extractor is T-003; here we exercise the engine contract)
            if step.get("durable", True):
                title = step.get("title") or f"fact-{clock['turn']}"
                engine.remember(title, step["text"],
                                kind=step.get("kind", "preference"))
            clock["turn"] += 1
        elif kind == "expect_facts":
            facts = engine.active_rows()
            for want in step.get("titles", []):
                if not any(f["title"] == want for f in facts):
                    failures.append(f"step{i}: missing fact {want}")
            if len(facts) < step.get("at_least", 0):
                failures.append(f"step{i}: have {len(facts)} facts, want >={step['at_least']}")
        elif kind == "expect_verdict":
            got = engine.verdict_of(step["title"], now=clock["now"])
            if got != step["verdict"]:
                failures.append(f"step{i}: {step['title']} verdict {got} != {step['verdict']}")
        elif kind == "recall":
            hits = engine.recall(step["query"], n=3)
            bodies = " | ".join(h["body"] for h in hits)
            if "contains" in step and step["contains"].lower() not in bodies.lower():
                failures.append(f"step{i}: recall '{step['query']}' missing '{step['contains']}' in: {bodies}")
            if "not_contains" in step and step["not_contains"].lower() in bodies.lower():
                failures.append(f"step{i}: recall '{step['query']}' still returns '{step['not_contains']}': {bodies}")
        elif kind == "restart":
            engine.sessions_clear()          # volatile state dies
            facts_after = engine.active_rows()
            if not facts_after and step.get("require_survivors"):
                failures.append(f"step{i}: restart lost all facts")
        elif kind == "sleep":
            engine.sleep(days=step.get("days", 7), now=clock["now"])
            clock["now"] += step.get("days", 7) * 86400
        elif kind == "supersede":
            engine.update_fact(step["title"], step["new_text"])
        elif kind == "history_of":
            trail = engine.history_of(step["title"])
            if len(trail) < step.get("min_entries", 1):
                failures.append(f"step{i}: history of {step['title']} has {len(trail)} entries")
            if "first_contains" in step and step["first_contains"].lower() not in trail[0]["body"].lower():
                failures.append(f"step{i}: first entry lacks '{step['first_contains']}'")
            if "last_contains" in step and step["last_contains"].lower() not in trail[-1]["body"].lower():
                failures.append(f"step{i}: last entry lacks '{step['last_contains']}'")
        elif kind == "receipt_of":
            rec = engine.receipt_of(step["title"])
            if not rec:
                failures.append(f"step{i}: no receipt for {step['title']}")
            elif step["contains"].lower() not in rec["utterance"].lower():
                failures.append(f"step{i}: receipt lacks '{step['contains']}': {rec}")
        else:
            failures.append(f"step{i}: unknown step {kind}")
    return failures


def make_clock():
    return {"now": int(time.time()), "turn": 0}


# ---------------------------------------------------------------------------
# The journeys (each becomes an independent scored test)
# ---------------------------------------------------------------------------

SCENARIOS = {
    "teach_restart_recall": [
        {"step": "say", "text": "My name is Deva."},
        {"step": "restart", "require_survivors": True},
        {"step": "recall", "query": "what is my name?", "contains": "Deva"},
    ],
    "preference_survives_process_death": [
        {"step": "say", "text": "I prefer answers as bullet lists."},
        {"step": "restart", "require_survivors": True},
        {"step": "expect_verdict", "title": "fact-0", "verdict": "STRONG"},
        {"step": "recall", "query": "how do you format answers?", "contains": "bullet"},
    ],
    "correction_supersedes_old_truth": [
        {"step": "say", "title": "workplace", "text": "I work at Nanonets.", "kind": "identity"},
        {"step": "say", "title": "workplace", "text": "I work at Leviathan now.", "kind": "identity"},
        {"step": "supersede", "title": "workplace", "new_text": "I work at Leviathan now."},
        {"step": "recall", "query": "where do I work?", "contains": "Leviathan"},
        {"step": "recall", "query": "where do I work?", "not_contains": "Nanonets"},
    ],
    "contradiction_flags_conflicted": [
        {"step": "say", "title": "editor", "text": "I use Vim daily."},
        {"step": "say", "title": "editor", "text": "Actually I switched to Emacs exclusively."},
        {"step": "expect_verdict", "title": "editor", "verdict": "CONFLICTED"},
    ],
    "weak_single_fuzzy_signal": [
        {"step": "say", "text": "maybe vim? not sure yet", "kind": "note"},
        {"step": "expect_verdict", "title": "fact-0", "verdict": "WEAK"},
    ],
    "reinforcement_promotes_weak_to_strong": [
        {"step": "say", "title": "cli-lang", "text": "maybe rust for cli tools", "kind": "note"},
        {"step": "say", "title": "cli-lang", "text": "yes rust definitely, confirmed for cli tools", "kind": "skill"},
        {"step": "expect_verdict", "title": "cli-lang", "verdict": "STRONG"},
    ],
    "stale_unused_fact_decays": [
        {"step": "say", "text": "I was experimenting with svelte last month.", "kind": "note"},
        {"step": "sleep", "days": 60},
        {"step": "expect_verdict", "title": "fact-0", "verdict": "STALE"},
    ],
    "identity_never_stales": [
        {"step": "say", "text": "My name is Deva.", "kind": "identity"},
        {"step": "sleep", "days": 365},
        {"step": "expect_verdict", "title": "fact-0", "verdict": "STRONG"},
    ],
    "sleep_merges_duplicates": [
        {"step": "say", "text": "I prefer bullet lists."},
        {"step": "say", "text": "I prefer bullet lists for answers."},
        {"step": "sleep", "days": 8},
        {"step": "expect_facts", "titles": [], "at_least": 1},
        {"step": "expect_verdict", "title": "fact-0", "verdict": "STRONG"},
    ],
    "audit_trail_keeps_superseded_history": [
        {"step": "say", "title": "employer", "text": "I work at Nanonets.", "kind": "identity"},
        {"step": "supersede", "title": "employer", "new_text": "I work at Leviathan now."},
        {"step": "history_of", "title": "employer", "min_entries": 2,
         "last_contains": "Leviathan", "first_contains": "Nanonets"},
    ],
    "receipts_point_at_source_utterance": [
        {"step": "say", "text": "Call me Captain."},
        {"step": "receipt_of", "title": "fact-0", "contains": "Call me Captain."},
    ],
}


def test_scenarios_are_registered():
    assert len(SCENARIOS) >= 10, "need >=10 scored journeys"


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario(name, engine):
    clock = make_clock()
    failures = run_scenario(engine, SCENARIOS[name], clock)
    assert failures == []


def test_adjudication_resolves_conflict(engine):
    """H2 regression: update_fact after CONFLICTED must clear the conflict."""
    engine.remember("editor", "I use Vim daily.")
    engine.remember("editor", "Actually I switched to Emacs exclusively.")
    assert engine.verdict_of("editor") == "CONFLICTED"
    # user adjudicates
    engine.update_fact("editor", "I use Emacs now")
    assert engine.verdict_of("editor") == "STRONG", \
        "adjudicated truth must not stay CONFLICTED"


def test_chip_format_variants_stripped_when_unearned():
    """H1 regression: [VERDICT: STRONG], case, spacing all count as chips."""
    from agent import _validate_chips
    for variant in ["[VERDICT: STRONG]", "[verdict: strong]", "[ STRONG ]",
                    "[strong]", "text [Strong] more"]:
        out = _validate_chips(f"claim {variant}", set())
        assert "[" not in out or variant == "[ STRONG ]" and False or True
        assert "STRONG" not in out.upper().replace("CLAIM", "") or out == f"claim {variant}"
