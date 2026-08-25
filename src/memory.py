"""Partner memory engine v2.

Design:
- Facts are typed (identity/preference/person/project/skill/constraint/note),
  append-only JSONL = audit trail. Latest entry per title is current truth;
  prior entries are history (receipts).
- Verdicts are COMPUTED, never claimed: STRONG / WEAK / CONFLICTED / STALE.
- Supersession: a correction with the same title supersedes; if it contradicts
  (different content, no explicit supersede) both stay and verdict flips to
  CONFLICTED for user adjudication.
- recall(): hybrid scoring — term overlap + recency + reinforcement — pure
  python, no LLM, deterministic. Vector tier hooks in T-005+ if needed.
- sleep(): consolidation pass. Merges near-dupes, decays unused facts toward
  STALE, promotes reinforced WEAK→STRONG. Idempotent under frozen clock.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

_WRITE_LOCK = threading.Lock()   # serializes read-modify-write cycles

HEIMDALL = os.environ.get("HEIMDALL_BIN", "heimdall")
MEMORIES_DIR = Path(os.environ.get(
    "MEMORIES_DIR",
    str(Path(__file__).resolve().parent.parent / "memories"),
))
FACTS_FILE = MEMORIES_DIR / "facts.jsonl"
WORD_RE = re.compile(r"[a-z][a-z0-9_-]{2,}", re.I)
RECENCY_S = 7 * 24 * 3600

# verdict rules
STRONG_MIN_SIGNALS = 2      # ≥2 signals (reinforcements) OR confident fresh fact
FRESH_S = 60                # a just-written confident fact is STRONG until contradicted

# hedge words -> a hedged statement is WEAK even when fresh
_HEDGE_RE = re.compile(
    r"\b(?:maybe|perhaps|might|not sure|kinda|sorta|i think|possibly|sometimes|guess)\b", re.I)

# decay policy (sleep cycles)
STALE_AFTER_DAYS = 45       # unused + non-identity -> STALE
IDENTITY_KINDS = {"identity"}   # never decay below STRONG


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _terms(text: str) -> set[str]:
    return {_stem(w.lower()) for w in WORD_RE.findall(text)}

def _stem(w: str) -> str:
    # ponytail: naive stemmer (ies->y, plural-s); swap snowball if recall quality demands
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _now() -> int:
    return int(time.time())


def _run(args: list[str], timeout: int = 60) -> str:
    out = subprocess.run([HEIMDALL, *args], capture_output=True, text=True,
                         timeout=timeout)
    return out.stdout


def _load() -> list[dict]:
    """All rows, tolerating torn tails. Rows missing v2 fields get defaults
    (v1 hand-written test fixtures must behave like real records)."""
    if not FACTS_FILE.exists():
        return []
    rows = []
    now = _now()
    for line in FACTS_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:      # torn tail from a killed writer
            continue
        r.setdefault("kind", "preference")
        r.setdefault("reinforcements", 0)
        r.setdefault("last_used", r.get("ts", now))
        r.setdefault("superseded_by", None)
        r.setdefault("status", "active")
        r.setdefault("ts", now)   # L4 fix: hand-edited rows must not 500 reads
        rows.append(r)
    return rows


def _save(rows: list[dict]) -> None:
    """Atomic full rewrite: tmp file + rename."""
    MEMORIES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FACTS_FILE.with_suffix(".tmp")
    payload = "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else "")
    tmp.write_text(payload)
    os.replace(tmp, FACTS_FILE)


# ---------------------------------------------------------------------------
# core operations
# ---------------------------------------------------------------------------

def remember(title: str, body: str, kind: str = "preference") -> bool:
    """Append one fact. Same title = correction event:
    - explicit supersede goes through update_fact()
    - otherwise contradiction check decides CONFLICTED vs reinforce.
    """
    title = (title or "").strip()
    body = (body or "").strip()
    if not title or not body:
        return False
    with _WRITE_LOCK:
        return _remember_locked(title, body, kind)

def _remember_locked(title: str, body: str, kind: str) -> bool:
    """remember() body; caller holds _WRITE_LOCK."""
    rows = _load()
    prior = [r for r in rows if r.get("title") == title]
    now = _now()
    rec = {
        "title": title,
        "body": body,
        "kind": kind if kind in KINDS else "note",
        "ts": now,
        "reinforcements": 0,
        "last_used": now,
        "superseded_by": None,
        "status": "active",
    }

    if prior:
        cur = max(prior, key=lambda r: r["ts"])
        if _same_claim(cur["body"], body):
            # reinforcement of same claim
            cur["reinforcements"] += 1
            cur["ts"] = now
            cur["kind"] = kind if kind in KINDS else cur["kind"]
            _save(rows)
            return True
        if _contradicts(cur["body"], body):
            # keep old active, add new as conflicting sibling
            rec["conflict_with"] = cur["title"]
            rows.append(rec)
            _save(rows)
            return True
        # different but non-contradicting update under same title -> supersede
        rec["supersedes"] = cur["title"]
        cur["superseded_by"] = f"{title}@{now}"

    rows.append(rec)
    _save(rows)
    return True


KINDS = {"identity", "preference", "person", "project", "constraint", "skill", "note"}


def update_fact(title: str, new_body: str, kind: str | None = None) -> bool:
    """Explicit correction: mark chain superseded, write new truth."""
    with _WRITE_LOCK:
        return _update_fact_locked(title, new_body, kind)


def _update_fact_locked(title: str, new_body: str, kind: str | None) -> bool:
    rows = _load()
    prior = [r for r in rows if r.get("title") == title and r["status"] == "active"]
    now = _now()
    if not prior:
        return False
    for r in prior:
        r["status"] = "superseded"
        r["superseded_by"] = f"{title}@{now}"
    # H2 fix: adjudication resolves the whole conflict chain — conflicting
    # siblings are closed out too, so the new truth isn't born CONFLICTED
    resolved = {r["title"] for r in prior}
    for r in rows:
        if r.get("conflict_with") in resolved and r["status"] == "active":
            r["status"] = "resolved-conflict"
            r["resolved_by"] = f"{title}@{now}"
    rec = {
        "title": title, "body": new_body.strip(),
        "kind": kind if kind in KINDS else prior[0]["kind"],
        "ts": now, "reinforcements": prior[0]["reinforcements"],
        "last_used": now, "superseded_by": None, "status": "active",
        "supersedes": title,
    }
    rows.append(rec)
    _save(rows)
    return True


def forget(title: str) -> bool:
    """Soft-delete whole chain (audit preserved)."""
    with _WRITE_LOCK:
        return _forget_locked(title)


def _forget_locked(title: str) -> bool:
    rows = _load()
    changed = False
    for r in rows:
        if r.get("title") == title and r["status"] == "active":
            r["status"] = "forgotten"
            r["forgotten_at"] = _now()
            changed = True
    if changed:
        _save(rows)
    return changed


def _same_claim(a: str, b: str) -> bool:
    ta, tb = _terms(a), _terms(b)
    if not ta or not tb:
        return a.strip() == b.strip()
    overlap = len(ta & tb) / min(len(ta), len(tb))
    return overlap >= 0.8


_CONTRADICT_VERBS = re.compile(
    r"\b(?:actually|instead|no[,.!]|not anymore|moved|switched|changed to|now use|exclusively)\b", re.I)
_NEGATION_RE = re.compile(r"\b(?:not|never|don'?t|stopped|quit|no longer)\b", re.I)


def _contradicts(old: str, new: str) -> bool:
    """Heuristic for genuine corrections vs topic shifts.

    Conflict requires a correction marker AND one of:
    - shared subject matter (0.15 <= jaccard < 0.45), or
    - an explicit negation flip ("I don't drink coffee" vs "I drink coffee")
    M4 fix: generic titles across unrelated topics no longer fuse into fake
    conflicts; negation flips still caught even at zero lexical overlap.
    """
    ta, tb = _terms(old), _terms(new)
    if not ta or not tb:
        return False
    if not _CONTRADICT_VERBS.search(new) and not _NEGATION_RE.search(new):
        return False
    jaccard = len(ta & tb) / len(ta | tb)
    if 0.15 <= jaccard < 0.45:
        return True
    # zero-overlap but same predicate frame (use X daily → switched to Y
    # exclusively): both sides name an editor/tool/thing after use/prefer verb
    _PRED = re.compile(r"\b(?:use|using|prefer|switched to|moved to|drink|write)\b", re.I)
    return bool(_PRED.search(old) and _PRED.search(new))


# ---------------------------------------------------------------------------
# recall + verdicts (pure functions of stored state)
# ---------------------------------------------------------------------------

def _facts() -> list[dict]:
    """Back-compat: latest record per title (any status), newest first.
    Later row wins timestamp ties (append order = truth order)."""
    by_title: dict[str, dict] = {}
    for r in _load():
        cur = by_title.get(r.get("title", ""))
        if cur is None or r["ts"] >= cur["ts"]:
            by_title[r.get("title", "")] = r
    return sorted(by_title.values(), key=lambda r: -r.get("ts", 0))


def active_rows() -> list[dict]:
    """Latest ACTIVE record per title. Last row wins timestamp ties."""
    by_title: dict[str, dict] = {}
    for r in _load():
        if r["status"] != "active":
            continue
        cur = by_title.get(r["title"])
        if cur is None or r["ts"] >= cur["ts"]:
            by_title[r["title"]] = r
    return sorted(by_title.values(), key=lambda r: -r["ts"])


# kinds whose fresh confident statement is trustworthy on its own
FRESH_STRONG_KINDS = {"preference", "identity"}


def _base_strength(cur: dict, now: int) -> str:
    """Intrinsic strength of one active record: STRONG or WEAK."""
    hedged = bool(_HEDGE_RE.search(cur["body"]))
    signals = 1 + min(cur.get("reinforcements", 0), 2)
    fresh_confident = (now - cur["ts"]) < FRESH_S and not hedged \
        and cur["kind"] in FRESH_STRONG_KINDS
    return "STRONG" if (signals >= STRONG_MIN_SIGNALS or fresh_confident) else "WEAK"


def verdict_of(title: str, now: int | None = None) -> str:
    """Computed verdict for a fact chain. One of STRONG/WEAK/CONFLICTED/STALE."""
    rows = [r for r in _load() if r.get("title") == title]
    if not rows:
        return "UNKNOWN"
    now = now or _now()
    active = [r for r in rows if r["status"] == "active"]
    if not active:
        return "SUPERSEDED"
    cur = max(active, key=lambda r: r["ts"])

    # any ACTIVE row pointing at this chain conflicts (resolved siblings are
    # status='resolved-conflict' and no longer count — H2 fix)
    all_rows = _load()
    if any(r.get("conflict_with") == title for r in all_rows
           if r.get("status") == "active"):
        return "CONFLICTED"

    if cur["kind"] not in IDENTITY_KINDS:
        age_days = (now - cur["last_used"]) / 86400
        if age_days > STALE_AFTER_DAYS:
            return "STALE"

    return _base_strength(cur, now)


def recall(query: str, n: int = 4, now: int | None = None) -> list[dict]:
    """Hybrid recall over active facts. Deterministic, LLM-free.

    score = term_overlap + freshness + reinforcement bonus; STALE demoted.
    Returns [{verdict, body, title, score}] best-first.
    """
    q = _terms(query)
    if not q:
        return []
    now = now or _now()
    scored = []
    for r in active_rows():
        v = verdict_of(r["title"], now=now)
        # searchable text = title + body (titles carry intent: "editor", "style")
        r_terms = _terms(r["title"]) | _terms(r["body"])
        overlap = len(q & r_terms) / max(1, min(len(q), len(r_terms)))
        if overlap <= 0:
            continue          # recall is relevance search, not a dump
        fresh = 1.0 if (now - r["ts"]) < RECENCY_S else 0.3
        rein = min(r.get("reinforcements", 0), 3) * 0.25
        penalty = {"STALE": -0.6, "WEAK": -0.4, "CONFLICTED": -0.5}.get(v, 0.0)
        score = overlap * 2 + fresh * 0.5 + rein + penalty
        scored.append({
            "verdict": v,
            "body": r["body"],
            "title": r["title"],
            "score": round(score, 3),
            "kind": r["kind"],
            "receipt": {"utterance": r["body"], "ts": r["ts"]},
        })
    scored.sort(key=lambda h: -h["score"])
    return [h for h in scored if h["score"] > 0][:n]


def context_block(query: str, n: int = 4) -> str:
    """System-prompt block of recalled facts with honest verdict chips."""
    hits = recall(query, n=n)
    if not hits:
        return ""
    lines = ["Known facts about this user (cite chips exactly as given):"]
    for h in hits:
        lines.append(f"- [{h['verdict']}] ({h['kind']}) {h['body']}")
    lines.append("Rules: act on [STRONG]; confirm before acting on [WEAK]; "
                 "surface both sides of [CONFLICTED] and ask which is true; "
                 "[STALE] facts may be outdated — mention staleness.")
    return "\n".join(lines)


def sessions_clear() -> None:
    """Volatile-state wipe used by restart scenarios and /reset."""
    SESSIONS.clear()


SESSIONS: dict = {}


def history_of(title: str) -> list[dict]:
    """Full audit trail for one title, oldest first."""
    rows = [r for r in _load() if r.get("title") == title]
    return sorted(rows, key=lambda r: r["ts"])


def receipt_of(title: str) -> dict | None:
    cur = max((r for r in _load() if r.get("title") == title),
              key=lambda r: r["ts"], default=None)
    if not cur:
        return None
    return {"utterance": cur["body"], "ts": cur["ts"],
            "title": title, "kind": cur["kind"]}


# ---------------------------------------------------------------------------
# sleep cycles: consolidation pass over the fact store
# ---------------------------------------------------------------------------

def _tokens(a: str, b: str) -> float:
    ta, tb = _terms(a), _terms(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def sleep(days: float = 7, now: int | None = None) -> dict:
    """One consolidation cycle. Deterministic under injected clock.

    - merge near-duplicate chains (Jaccard >= 0.6): older becomes a
      reinforcement on the newer chain and goes status='merged'
    - decay: active non-identity facts unused for > STALE_AFTER_DAYS days
      become STALE (status stays 'active', verdict computed from last_used)
    - promote: WEAK chains reinforced since last sleep -> recompute naturally
    Idempotent: running twice with the same clock changes nothing.
    """
    now = now or _now()
    with _WRITE_LOCK:
        return _sleep_locked(days, now)


def _sleep_locked(days: float, now: int) -> dict:
    """sleep() body; caller holds _WRITE_LOCK."""
    rows = _load()
    report = {"merged": 0, "decayed": 0, "promoted": 0}

    active = [r for r in rows if r["status"] == "active"]
    by_title: dict[str, dict] = {}
    for r in active:
        cur = by_title.get(r["title"])
        if cur is None or r["ts"] >= cur["ts"]:
            by_title[r["title"]] = r

    titles = list(by_title.values())
    merged_titles: set[str] = set()
    for i, a in enumerate(titles):
        if a["title"] in merged_titles or a["kind"] == "identity":
            continue
        for b in titles[i + 1:]:
            if b["title"] in merged_titles or b["title"] == a["title"] \
                    or b["kind"] == "identity":
                continue
            if _tokens(a["body"], b["body"]) >= 0.6:
                keep, drop = (a, b) if a["ts"] >= b["ts"] else (b, a)
                keep["reinforcements"] = keep.get("reinforcements", 0) + 1
                keep["last_used"] = max(keep["last_used"], drop["last_used"])
                for r in rows:
                    if r["title"] == drop["title"] and r["status"] == "active":
                        r["status"] = "merged"
                        r["merged_into"] = keep["title"]
                merged_titles.add(drop["title"])
                report["merged"] += 1

    for t, cur in by_title.items():
        if t in merged_titles or cur["kind"] in IDENTITY_KINDS:
            continue
        was_stale = verdict_of(t, now=now) == "STALE"
        age_days = (now - cur["last_used"]) / 86400
        if age_days > STALE_AFTER_DAYS:
            if not was_stale:
                report["decayed"] += 1
            # stamp so /memories shows the transition moment
            cur.setdefault("stale_since", now)
        elif "stale_since" in cur and age_days <= STALE_AFTER_DAYS:
            del cur["stale_since"]   # used again -> un-stales
            report["promoted"] += 1

    # sleep counts as a use cycle: reinforcement signal strengthens (identity
    # facts get a floor boost so a name taught once still answers STRONG weeks later)
    for t, cur in by_title.items():
        if cur["kind"] in IDENTITY_KINDS and cur.get("reinforcements", 0) == 0:
            cur["reinforcements"] = 1
            report["promoted"] += 1

    _save(rows)
    report["at"] = now
    return report


_HEIMDALL_HIT_RE = re.compile(r"\[\s*(STRONG|WEAK)\s*\]\s*\S*\s+(\S*/\S*)")


def recall_code(query: str, n: int = 3) -> list[dict]:
    """Repo/code context via heimdall search (text format). Best-effort."""
    try:
        out = _run(["search", query, "--n", str(n)])
        if not out.strip():
            return []
        hits = []
        for line in out.splitlines():
            m = _HEIMDALL_HIT_RE.search(line)
            if m and "/" in m.group(2):
                hits.append({
                    "verdict": m.group(1),
                    "path": m.group(2),
                    "title": m.group(2).rsplit("/", 1)[-1],
                    "body": m.group(2),
                })
        return hits[:n]
    except Exception:
        return []


if __name__ == "__main__":
    print("self-check moved to pytest: python -m pytest tests/ -q")
