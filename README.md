# Partner — a Collaborative Partner that never forgets

**Track:** Collaborative Partner (All Things Agentic Hackathon)
**Stack:** Gemini 3.5 Flash · Google GenAI SDK · Cloud Run · Heimdall memory layer

Partner is a chat agent that **adapts to you across sessions**. Correct it once
and it remembers — with receipts. Every recalled fact carries an honest verdict:

- `[STRONG]` — multiple matching signals, or a fresh preference: act on it.
- `[WEAK]` — single fuzzy match: the agent confirms before acting.

Kill the process, come back tomorrow, and it still knows you — because memory
lives in a persistent store, not in the chat window.

## The demo beat (why this wins)

```
You:  No, I prefer answers as bullet lists.
AI:   Noted. *(fact written)*

# ... container killed, new session ...

You:  What format do you use for answers to me?
AI:   • I format my responses using bullet lists [STRONG] based on your preference.
```

No re-teaching. No hallucinated memory. Verdicts you can audit at `GET /memories`.

## Architecture

```
Browser/curl ──▶ FastAPI on Cloud Run ──▶ Gemini 3.5 Flash (GenAI SDK)
                        │                        ▲
                 correction detector            │ system prompt w/ fact block
                        │ writes                │ cites [STRONG]/[WEAK]
                        ▼                        │
              memories/facts.jsonl ──recall──────┘
              (volume-mounted, survives restarts)

              heimdall search ──▶ verified code-context hits [STRONG/WEAK]
                                  for repo questions (optional tier)
```

- **Correction detector**: regex gate catches "no, I prefer…", "call me…",
  "I work at…" — zero LLM cost to decide what's durable.
- **Verdicts are computed, not claimed**: ≥2 term overlap or fresh preference →
  STRONG; single fuzzy term → WEAK. The agent can only cite what the store gave it.
- **Heimdall** (`@arihantdeva/heimdall`) provides verified repo-context search;
  its trust-verdict model inspired the fact-chip UX.

## Run locally

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

export GEMINI_API_KEY=...        # from aistudio.google.com/apikey
export GEMINI_MODEL=gemini-3.5-flash   # required by hackathon rules; dev tip: gemini-3.6-flash has a bigger free tier

python src/server.py             # serves on :8080
```

Chat:

```bash
curl -s localhost:8080/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"me","message":"No, I prefer short answers."}'
# → {"reply":"Noted...","memories_used":[],"remembered":["No, I prefer short answers."]}

curl -s localhost:8080/memories | jq     # inspect everything it knows about you
```

## Deploy (Cloud Run)

```bash
gcloud run deploy partner \
  --source . --region us-central1 --allow-unauthenticated --max-instances 2
```

Scale-to-zero; memory volume persists per instance via `/data/memories`.
See `docs/demo-script.md` for the exact video beats incl. GCP-console proof.

## Disclosure

Memory layer: [@arihantdeva/heimdall](https://github.com/ArihantDeva/heimdall) —
my open-source library (MIT), used here for verified code-context retrieval and
as the inspiration for the verdict-chip interaction. Everything else in this
repo was built during the hackathon window.

## Tests

```bash
python -m pytest tests -q       # 25 tests: memory verdict honesty, agent loop, HTTP contract
```
