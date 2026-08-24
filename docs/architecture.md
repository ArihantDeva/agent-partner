# Architecture — Partner

```
                        ┌────────────────────────────────────────────┐
                        │              Cloud Run (container)         │
                        │                                            │
  curl / browser ──────▶│  FastAPI (src/server.py)                   │
                        │    ├─ GET  /healthz                        │
                        │    ├─ POST /chat ─────────┐                │
                        │    ├─ POST /sessions/:id/reset     │        │
                        │    └─ GET  /memories      │                │
                        │                           ▼                │
                        │  PartnerAgent (src/agent.py)               │
                        │    ├─ correction detector (regex, $0)      │
                        │    │    └─ remember() ──▶ facts.jsonl      │
                        │    ├─ recall() ─▶ context_block()          │
                        │    │    (verdict chips [STRONG]/[WEAK])    │
                        │    └─ google-genai SDK ────────────┐       │
                        └───────────────────────────────────│───────┘
                                                            ▼
                                              Gemini 3.5 Flash API
                                              (system prompt = persona
                                               + fact block; cites chips)

  Persistence: memories/facts.jsonl on volume /data/memories
  (survives container restarts — the demo beat)

  Optional code-context tier: heimdall search → verified [STRONG/WEAK]
  repo hits (npm @arihantdeva/heimdall in same container)
```

## Data flow of one correction

1. `POST /chat {"message":"No, I prefer bullet lists"}`
2. `looks_like_correction()` regex hit → `memory.remember()` appends JSONL fact
3. `memory.recall(message)` pulls matching facts → system-prompt block with chips
4. Gemini replies citing `[STRONG]`; reply + usage stored in session history
5. Container dies → volume persists → next session recalls the fact as STRONG

## Verdict honesty rule

The model never invents a chip: it can only echo verdicts present in the
injected context block. Chips are computed by overlap-count + recency in
`memory.py`, auditable at `GET /memories`.
