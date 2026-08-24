"""Heimdall memory bridge for the Collaborative Partner agent.

Wraps the heimdall CLI (npm @arihantdeva/heimdall) as read/write memory:
- remember():      heimdall insert --title T --body B --keywords k1,k2
- recall():        heimdall search "query" -n N  -> parsed [(verdict, title, path)]
- context_block(): formatted system-prompt injection of verified memories

In production (Cloud Run) HEIMDALL_BIN points at the container's install;
locally it uses the global binary.
"""
import json
import os
import subprocess

HEIMDALL = os.environ.get("HEIMDALL_BIN", "heimdall")
HEIMDALL_REPOS = os.environ.get("HEIMDALL_REPOS", os.path.expanduser("~/Repos"))
MEMORIES_DIR = os.environ.get("MEMORIES_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memories"))


def _run(args: list[str], timeout: int = 60) -> str:
    env = dict(os.environ, HEIMDALL_REPOS=HEIMDALL_REPOS)
    out = subprocess.run([HEIMDALL, *args], capture_output=True, text=True,
                         timeout=timeout, env=env)
    return out.stdout


def remember(title: str, body: str, keywords: str = "") -> bool:
    """Write one memory. Returns True on success.

    heimdall insert queues a journal hint pointing at <cwd>/<title>.fact.md —
    the fact file must exist BEFORE insert so the reconciler has content to
    index into the graph.
    """
    safe = "".join(c if c.isalnum() or c in "_.-" else "_" for c in title)
    os.makedirs(MEMORIES_DIR, exist_ok=True)
    fact_path = os.path.join(MEMORIES_DIR, safe + ".fact.md")
    try:
        # Facts are extracted by heimdall's pattern set (first-person:
        # "I prefer/use/am…", declarations "X is Y", negations). Store the
        # user's own words so extraction matches.
        with open(fact_path, "w") as f:
            kw = f"\n\nKeywords: {keywords}" if keywords else ""
            f.write(f"{body}\n{kw}\n")
        args = ["insert", "--title", title, "--body", body]
        if keywords:
            args += ["--keywords", keywords]
        out = _run(args)
        return "ERROR" not in out.upper()
    except (OSError, subprocess.TimeoutExpired):
        return False


def recall(query: str, n: int = 4) -> list[dict]:
    """Search memory. Returns [{verdict, coverage, body}] sorted by rank."""
    try:
        out = _run(["search", query, "-n", str(n)])
    except subprocess.TimeoutExpired:
        return []
    hits = []
    for line in out.splitlines():
        line = line.strip()
        # format: "1. [STRONG] cov50%  /path/file.py"
        if line and line[0].isdigit() and "[" in line and "]" in line:
            verdict = line.split("[")[1].split("]")[0]
            cov = ""
            if "cov" in line:
                cov = line.split("cov")[1].split("%")[0] + "%"
            # next non-empty line is the description
            idx = out.splitlines().index(
                next(l for l in out.splitlines() if l.strip() == line))
            desc = ""
            for nxt in out.splitlines()[idx + 1:]:
                if nxt.strip():
                    desc = nxt.strip()
                    break
            hits.append({"verdict": verdict, "coverage": cov, "body": desc})
    return hits


def context_block(query: str, n: int = 4) -> str:
    """System-prompt block of recalled memories with verdict labels."""
    hits = recall(query, n)
    if not hits:
        return ""
    lines = ["Verified memories about this user (act on STRONG; confirm before acting on WEAK):"]
    for h in hits:
        lines.append(f"- [{h['verdict']}] {h['body']}")
    return "\n".join(lines)


if __name__ == "__main__":
    # self-check
    ok = remember("test-pref", "User prefers terse replies", "style")
    print("insert:", ok)
    r = recall("reply style preference", 2)
    assert isinstance(r, list), "recall must return a list"
    print("recall:", json.dumps(r)[:200])
    print("context:", context_block("reply style")[:150])
