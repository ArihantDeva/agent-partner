# Partner — the collaborative agent that never forgets you

**Track:** Collaborative Partner (All Things Agentic Hackathon)
**Stack:** Gemini (Google GenAI SDK) · Cloud Run · crash-safe memory engine
Deployed model: `gemini-2.5-flash` via Vertex endpoint — this GCP org blocks
Developer-API keys (`API_KEY_SERVICE_BLOCKED`), so production runs on Vertex
with service-identity auth; the SDK call path is identical. Flip
`GEMINI_MODEL`/auth env when a clean key project is available.

Partner is a chat agent that **adapts to you across sessions**. Correct it once
and it remembers — with receipts. Every recalled fact carries a computed,
honest verdict:

- `[STRONG]` — multiple signals or a confident preference: act on it.
- `[WEAK]` — single fuzzy or hedged signal: the agent confirms before acting.
- `[CONFLICTED]` — contradictory facts on record: both sides surfaced, user adjudicates.
- `[STALE]` — unused for 45+ days: mentioned as possibly outdated.

Kill the process, come back tomorrow, and it still knows you — memory lives
in crash-safe files outside the chat window (atomic writes; every fact keeps
its full revision history, nothing is ever deleted).

## The demo beat (why this wins)

```
You:  No, I prefer answers as bullet lists.
AI:   Noted. (fact written, chip pops into the live-brain sidebar)

# ... click "⚡ Kill the process" in the page: container dies, dot goes red ...
# ... platform restarts it; UI reconnects ...

You:  What format do you use for answers to me?
AI:   • I format my responses using bullet lists [STRONG] based on your preference.
```

No re-teaching. No hallucinated confidence. Verdicts are **enforced in the
server**: any `[STRONG]`/`[WEAK]` chip the model emits without a matching fact
injected that turn is stripped before you ever see it.

## Architecture

```
Browser ──SSE──▶ FastAPI on Cloud Run ──▶ Gemini 3.5 Flash (GenAI SDK)
   │                     │    ▲                  │ function calling:
   │      live-brain     │    │ system prompt    │ remember / recall /
   │      sidebar ◀──────┘    │ w/ fact block    │ update_fact / forget /
   │                          │ cites chips      │ search_code
   │                          │                  ▼
   └─ Kill button ──▶ os._exit ── platform restart
                                     │
        memories/facts.jsonl ◀──recall┘  (revision audit trail)
        sessions/*.json       (chat history survives restarts too)
```

- **Two-stage capture** — regex fast path (zero LLM cost) + model-driven
  `remember` tool calls + structured-output extractor fallback for durable
  statements no regex catches ("my sister Sarah's birthday is in May").
- **Typed facts with receipts** — identity/preference/person/project/
  constraint/skill/note; every fact keeps its source utterance + timestamp.
- **Versioned truth** — corrections supersede; nothing is deleted; full audit
  trail at `GET /memories/{title}/history`.
- **Verdicts are computed** — signal strength + recency + reinforcement;
  `sleep()` consolidates: merges near-dupes, decays unused facts toward STALE,
  promotes reinforced WEAK→STRONG. Identity facts never decay below STRONG.
- **Agentic loop** — native Gemini function calling, bounded at 8 tool
  calls/turn; welcome-back briefing summarizes what Partner remembers when you
  return.

## Run locally

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# Local (Developer API):
export GEMINI_API_KEY=...        # from aistudio.google.com/apikey
export GEMINI_MODEL=gemini-2.5-flash

# Or Vertex mode (what our Cloud Run uses):
export USE_VERTEX=1 GOOGLE_CLOUD_PROJECT=<proj> GOOGLE_CLOUD_LOCATION=us-central1

python src/server.py             # serves UI + API on :8080
```

Open http://localhost:8080. Or via curl:

```bash
curl -s localhost:8080/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"me","message":"No, I prefer short answers."}'

curl -s localhost:8080/memories | python3 -m json.tool   # full transparency
curl -s -N localhost:8080/chat/stream -H 'Content-Type: application/json' \  # SSE
  -d '{"session_id":"me","message":"hello"}'
```

Or with mise: `mise run test` · `mise run dev`.

## Deploy (Cloud Run)

```bash
gcloud run deploy partner \
  --source . --region us-central1 --allow-unauthenticated \
  --min-instances=1 --max-instances=1 \
  --set-env-vars USE_VERTEX=1,GOOGLE_CLOUD_PROJECT=<proj>,GOOGLE_CLOUD_LOCATION=us-central1,GEMINI_MODEL=gemini-2.5-flash \
  --add-volume name=mem,type=cloud-storage,bucket=<mem-bucket> \
  --add-volume name=sess,type=cloud-storage,bucket=<sess-bucket> \
  --add-volume-mount volume=mem,mount-path=/data/memories \
  --add-volume-mount volume=sess,mount-path=/data/sessions
```

Memory volume persists per instance via `/data/memories`; sessions likewise.
The kill-button works on Cloud Run too: the process exits, Cloud Run replaces
the instance, the page reconnects, and the fact store survives.

## Tests & evals

```bash
mise run test        # or: python -m pytest -q
```

- Unit tests: verdict honesty, capture paths, persistence, HTTP contract.
- **12 scripted eval journeys** (`tests/test_scenarios.py`): teach→restart→recall,
  correction→supersession, conflict flagging, unbacked-chip stripping,
  sleep consolidation effects (decay/promote/merge), receipts, identity immortality.
- CI (GitHub Actions): hermetic suite + docker build + `/healthz` smoke.

## Disclosure

Memory-layer inspiration and code-context tier: [@arihantdeva/heimdall](https://github.com/ArihantDeva/heimdall) —
my open-source library (MIT), used here for verified repo-context retrieval
(`search_code` tool). Everything else in this repo was built during the
hackathon window.

## Known limits (honesty section)

- Verdict computation is lexical/heuristic (stemmed term overlap, recency,
  reinforcement counts) — not embeddings yet; recall quality degrades on
  paraphrase-heavy fact stores.
- The extractor fallback costs one extra LLM call only when neither regex nor
  the model wrote a fact; latency-conscious users see it as a slightly slower
  first reply.
- Multi-instance Cloud Run would split session files across instances; deploy
  with min-instances=1 (as documented) to keep state coherent.
