# Architecture — Partner v2

```
                     ┌──────────────────────────────────────────────────┐
                     │              Cloud Run (container, min-inst=1)   │
 browser ───────────▶│  static/ (vanilla JS UI)                         │
   │  SSE stream     │    chat · live-brain sidebar · Kill button       │
   │  kill click     │    memory inspector · sleep button               │
   ▼                 │                                                  │
 FastAPI (src/server.py)                                                 │
   ├─ GET  /healthz           liveness                                   │
   ├─ POST /chat              one-shot turn                              │
   ├─ POST /chat/stream       SSE: delta* → done (chip-validated)        │
   ├─ GET  /memories          raw fact store (judge audit)               │
   ├─ GET  /memories/:t/history  per-fact audit trail                    │
   ├─ POST /sessions/:id/reset  drop history (facts stay)                │
   ├─ POST /sleep             consolidation cycle                        │
   ├─ GET  /stats             verdict/kind/session counts                │
   └─ POST /demo/kill         os._exit(0) → platform restarts us        │
                     │                                                  │
 PartnerAgent (src/agent.py)                                            │
   ├─ regex fast path ($0) ──────────────▶ remember()                      │
   ├─ recall() → context block w/ chips                               │
   ├─ Gemini fn-calling loop (≤8 calls): remember / recall /          │
   │     update_fact / forget / search_code (heimdall tier)           │
   ├─ extractor fallback (1 structured call when nothing captured)    │
   ├─ welcome-back briefing (recent facts, unprompted)                │
   └─ chip validation: strip [STRONG]/[WEAK] not backed by injected   │
         facts this turn  ← the honesty guarantee lives HERE          │
                     │                                                  │
 Memory engine (src/memory.py)                                          │
   ├─ typed facts w/ receipts (utterance + ts)                        │
   ├─ facts.jsonl = revision-history audit trail; supersession chains │
   ├─ computed verdicts: STRONG/WEAK/CONFLICTED/STALE                 │
   ├─ hybrid recall: stemmed overlap + recency + reinforcement        │
   ├─ _WRITE_LOCK around all read-modify-write cycles                 │
   └─ sleep(): dupe merge · decay→STALE · promote reinforced          │
                     │                                                  │
 Session store (src/sessions.py): sessions/*.json, atomic writes,       │
   torn-read tolerant; chat history survives restarts too               │
                     └──── volumes: /data/memories · /data/sessions ────┘
```

## Data flow of one correction

1. `POST /chat/stream {"message":"No, I prefer bullet lists"}`
2. Regex fast path hits → `memory.remember()` appends a fact (locked RMW)
3. `recall(message)` pulls matching facts → system-prompt block with computed chips
4. Gemini streams tokens; may also call `remember` itself for durable content
5. Stream ends with `done`: full reply is chip-validated server-side — any
   `[STRONG]`/`[WEAK]` without a matching injected fact is stripped
6. Turn saved to session store; UI pops the new fact chip into the sidebar

## The honesty guarantee

Verdicts are computed in `memory.verdict_of()` (signal strength + recency +
reinforcement). The model only sees chips we injected and its reply passes
through `_validate_chips()`, which removes any verdict token it wasn't given.
Prompt rules ask nicely; the server enforces.

## Persistence model

- `facts.jsonl` — every write keeps history (nothing deleted); latest active
  row per title is current truth
- `sessions/*.json` — per-session chat history, atomic tmp+rename writes,
  tombstoned on reset (never deleted)
- Both live on Cloud Run volumes (`/data/memories`, `/data/sessions`);
  deploy with min-instances=1 so state stays coherent across requests
