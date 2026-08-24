# Devpost submission field drafts

## Project title
Partner — the collaborative agent that never forgets you

## Short pitch (≤200 chars)
A chat agent with persistent, auditable memory. Correct it once and it adapts
forever — every recalled fact carries an honest [STRONG]/[WEAK] verdict.

## Full description
Every AI agent restarts from zero. Partner fixes that with memory as
infrastructure: durable facts live in a persistent store outside the chat
window, survive container restarts (shown live in our demo), and are injected
into every conversation with **honest verdict labels**.

**How it works**
- A regex correction detector (zero LLM cost) catches durable statements —
  preferences, corrections, identity — and writes them to a fact store.
- On each turn, matching facts are recalled and injected into Gemini 3.5 Flash's
  system prompt. The model may only echo verdict chips it was given:
  [STRONG] = multi-signal or fresh preference; [WEAK] = single fuzzy match,
  so the agent confirms instead of assuming.
- Memory is a volume mount: kill the container, return tomorrow, it still knows
  your name and formatting preference — verified on camera.
- Judges can audit everything at GET /memories: full transparency into what the
  agent believes about you.

**Why verdicts matter**: most RAG agents hallucinate confidence. Partner's UX
makes uncertainty a feature — WEAK facts trigger confirmation questions,
STRONG facts drive behavior.

**Tech (all required items)**
- Gemini 3.5 Flash via Google GenAI SDK ✔
- Cloud Run deployment (scale-to-zero, live URL in demo) ✔
- @arihantdeva/heimdall — my open-source MIT library — for verified
  code-context retrieval; its trust-verdict model inspired the chip UX

## Features & functionality
- Persistent cross-session memory (survives process death — shown live)
- Honest [STRONG]/[WEAK] recall verdicts, auditable via API
- Zero-cost regex correction detection
- Session reset endpoint simulating "come back tomorrow"
- /memories transparency endpoint for judges
- Verified code-context search tier via heimdall

## Technologies used
Python, FastAPI, Google GenAI SDK, Gemini 3.5 Flash, Cloud Run, Docker,
@arihantdeva/heimdall (MIT), pytest

## Data sources used
None external — all memory is user-supplied during conversation.

## Findings & learnings
- "Memory" claims are cheap; *auditable* memory is rare. We made verdicts a
  first-class UI element and the model structurally unable to fake them.
- Regex gates beat LLM classifiers for capture: free, instant, testable (25 tests).
- Container restart as demo beat: persistence claims must be destroyed and
  re-shown to be believed.
- Heimdall's fact pipeline taught us where the hard problems are (projection
  from journal → searchable index); we built the app tier to be honest within
  those constraints.

## Submission checklist
- [x] Public repo URL (this repo)
- [x] Spin-up instructions (README)
- [x] Architecture diagram (docs/architecture.md + image render)
- [ ] ~4-min video (docs/demo-script.md) — USER ACTION: record per script
- [ ] GCP proof artifacts — after deploy (T-006)
- [x] Disclosure of pre-existing code (heimdall library)
