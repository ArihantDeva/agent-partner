# Devpost submission field drafts

## Project title
Partner — the collaborative agent that never forgets you

## Short pitch (≤200 chars)
A chat agent with persistent, auditable memory. Correct it once and it adapts
forever — every recalled fact carries a computed [STRONG]/[WEAK] verdict the
model cannot fake.

## Full description
Every AI agent restarts from zero. Partner fixes that with memory as
infrastructure: durable facts live in crash-safe files (full revision
history, nothing deleted) outside the chat
window, survive a real process kill (killed live, from the web page, during
the demo), and are injected into every conversation with **computed verdict
labels enforced server-side**.

**How it works**
- Capture is three-tiered: a zero-cost regex fast path for obvious corrections;
  native Gemini function calling (`remember`, `recall`, `update_fact`,
  `forget`, `search_code`) so the model decides what's durable; and a
  structured-output extractor fallback that catches durable statements no
  pattern matches ("my sister Sarah's birthday is in May").
- Facts are typed (identity/preference/person/project/constraint/skill/note)
  with source receipts — the exact utterance and timestamp.
- On each turn, matching facts are recalled (hybrid lexical + recency +
  reinforcement scoring) and injected into Gemini 3.5 Flash's system prompt.
- Verdicts are COMPUTED, not claimed: STRONG = multi-signal or confident fresh
  preference; WEAK = single fuzzy/hedged signal → the agent confirms before
  acting. The server strips any verdict chip the model emits without a
  matching injected fact — hallucinated confidence is structurally impossible.
- Contradictions don't silently overwrite: both sides stay on record as
  CONFLICTED until you adjudicate. Corrections supersede with full audit trail.
- Sleep cycles: one endpoint runs consolidation — merges near-duplicate facts,
  decays unused ones toward STALE, promotes reinforced WEAK→STRONG.
  Identity facts never decay below STRONG.
- Sessions persist too: chat history survives the kill, so even mid-conversation
  context returns when the process does.

**Why verdicts matter**: most RAG agents hallucinate confidence. Partner's UX
makes uncertainty a first-class UI element — color-coded chips pop into the
live-brain sidebar as facts are learned; WEAK facts trigger confirmation
questions; CONFLICTED facts surface both sides.

**The demo**: click "⚡ Kill the process" in the page. The container dies on
camera (connection dot goes red), the platform restarts it, the page
reconnects — and Partner still knows your name, your formatting preference,
and where you work. Not a demo trick: memory is files + honest verdicts.

**Tech (all required items)**
- Gemini via Google GenAI SDK ✔ (function calling + SSE streaming;
  deployed on Vertex endpoint as gemini-2.5-flash because this GCP org
  restricts Developer-API keys — same SDK, same Gemini family)
- @arihantdeva/heimdall — my open-source MIT library — for verified code-context
  retrieval via the `search_code` tool; its trust-verdict model inspired the chip UX

## Features & functionality
- Persistent cross-session memory (survives real process death — killed from the UI)
- Honest computed verdicts: STRONG / WEAK / CONFLICTED / STALE
- Server-side chip validation — unearned verdict chips stripped before display
- Three-tier durable capture: regex fast path, function-calling writes, LLM extractor fallback
- Live-brain sidebar: chips pop as learned; click through to source receipts
- Sleep-cycle consolidation: dupe merge, decay, reinforcement promotion
- Memory inspector with audit trail per fact (`GET /memories/{title}/history`)
- Welcome-back briefing: returning users get told what Partner remembers
- SSE token streaming chat, dark UI, mobile-safe

## Technologies used
Python, FastAPI, Google GenAI SDK (function calling + streaming), Gemini 3.5
Flash, Cloud Run, Docker, SSE, vanilla JS/CSS (Radix Colors, Bunny Fonts),
pytest, GitHub Actions

## Data sources used
None external — all memory is user-supplied during conversation.

## Findings & learnings
- "Memory" claims are cheap; *auditable* memory is rare. Receipts (source
  utterance + timestamp per fact) turned trust into a clickable feature.
- Regex gates beat LLM classifiers for the obvious 80% of corrections: free,
  instant, testable. But they miss relational facts ("my sister…") — hence the
  three-tier capture design.
- Making the demo destructive was the best decision: claims about persistence
  must be destroyed and re-shown to be believed. Killing the process from
  inside the page makes judges believe instantly.
- Enforcing honesty server-side (chip stripping) beats asking the model nicely.
  Prompt-level rules are suggestions; response validation is a guarantee.

## Submission checklist
- [x] Public repo URL (this repo)
- [x] Spin-up instructions (README)
- [x] Architecture diagram (docs/architecture.md + image render)
- [ ] ~4-min video (docs/demo-script.md) — USER ACTION: record per script
- [x] GCP proof artifacts (docs/gcp-proof/: deployment-proof.md, service-url.txt, revisions.txt)
- [x] Disclosure of pre-existing code (heimdall library)
