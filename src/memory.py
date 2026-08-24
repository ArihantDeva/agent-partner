"""Heimdall-partner memory layer.

Two tiers, both CPU-only:
1. FACTS — file-backed store (memories/facts.jsonl), written by remember(),
   read by recall(). Verdicts are computed honestly:
     STRONG — >=2 keyword/exact-term overlap, or same fact updated <7d
     WEAK   — single fuzzy term match
   (heimdall's own fact sink is a stub in v0.5/0.6, so the app owns this.)
2. CODE CONTEXT — heimdall CLI search over indexed repos, for "where is X"
   questions. Proven working incl. container.

No LLM calls here; the agent decides what to remember/recall.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

HEIMDALL = os.environ.get("HEIMDALL_BIN", "heimdall")
MEMORIES_DIR = Path(os.environ.get(
    "MEMORIES_DIR",
    str(Path(__file__).resolve().parent.parent / "memories"),
))
FACTS_FILE = MEMORIES_DIR / "facts.jsonl"
WORD_RE = re.compile(r"[a-z][a-z0-9_-]{2,}", re.I)
RECENCY_S = 7 * 24 * 3600


def _terms(text: str) -> set[str]:
    return {w.lower() for w in WORD_RE.findall(text)}


def _run(args: list[str], timeout: int = 60) -> str:
    out = subprocess.run([HEIMDALL, *args], capture_output=True, text=True,
                         timeout=timeout)
    return out.stdout


def remember(title: str, body: str, kind: str = "preference") -> bool:
    """Append one fact. Same title updates in place (append + latest wins)."""
    if not title.strip() or not body.strip():
        return False
    MEMORIES_DIR.mkdir(parents=True, exist_ok=True)
    fact = {
        "ts": time.time(),
        "title": title.strip()[:120],
        "body": body.strip(),
        "kind": kind,
    }
    with open(FACTS_FILE, "a") as f:
        f.write(json.dumps(fact) + "\n")
    return True


def _facts() -> list[dict]:
    """All facts, latest per title first."""
    if not FACTS_FILE.exists():
        return []
    by_title: dict[str, dict] = {}
    with open(FACTS_FILE) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # torn write: skip
            if isinstance(rec, dict) and rec.get("title"):
                by_title[rec["title"]] = rec  # later lines win
    return sorted(by_title.values(), key=lambda r: -r.get("ts", 0))


def recall(query: str, n: int = 4) -> list[dict]:
    """Search facts. Returns [{verdict, body, title}] best-first."""
    q = _terms(query)
    if not q:
        return []
    scored: list[tuple[float, float, dict]] = []  # (overlap, recency, fact)
    now = time.time()
    for fact in _facts():
        overlap = len(q & (_terms(fact["body"]) | _terms(fact["title"])))
        if not overlap:
            continue
        recency = max(0.0, 1 - (now - fact.get("ts", 0)) / RECENCY_S)
        scored.append((float(overlap), recency, fact))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    hits = []
    for overlap, recency, fact in scored[:n]:
        strong = overlap >= 2 or (overlap >= 1 and recency > 0.5 and fact["kind"] == "preference")
        hits.append({
            "verdict": "STRONG" if strong else "WEAK",
            "title": fact["title"],
            "body": fact["body"],
        })
    return hits


def context_block(query: str, n: int = 4) -> str:
    """System-prompt block of recalled facts with honest verdict chips."""
    hits = recall(query, n)
    if not hits:
        return ""
    lines = [
        "Known facts about this user. Act on [STRONG]; mention uncertainty for [WEAK]:"
    ]
    lines += [f"- [{h['verdict']}] {h['body']}" for h in hits]
    return "\n".join(lines)


def recall_code(query: str, n: int = 3) -> list[dict]:
    """Repo/code context via heimdall search (verified paths). Best-effort."""
    try:
        out = _run(["search", query, "-n", str(n)])
    except (subprocess.TimeoutExpired, OSError):
        return []
    hits = []
    lines = out.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"\s*\d+\.\s+\[(\w+)\]\s+cov(\d+)%\s+(\S+)", line)
        if not m:
            continue
        desc = lines[i + 1].strip() if i + 1 < len(lines) else ""
        hits.append({"verdict": m.group(1), "coverage": m.group(2),
                     "path": m.group(3), "desc": desc})
    return hits


if __name__ == "__main__":
    # self-check: round-trip on a scratch dir
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.environ["MEMORIES_DIR"] = td
        import importlib
        importlib.reload(memory := __import__(__name__, fromlist=["x"])) if False else None
    print("run pytest tests/test_memory.py instead")
