# Demo video script — ~4 minutes

Rule: every claim shown live, never narrated over a slide. GCP proof beat is
mandatory (judges require deployment evidence).

## Beat 1 — The problem (0:00–0:40)
- Terminal, fresh session. Ask the agent a personalization question:
  "How do you format answers for me?" → generic reply, no idea.
- Line: "Every AI agent starts from zero. Every. Single. Time."

## Beat 2 — Teach it once (0:40–1:20)
- "No, I prefer answers as bullet lists." → reply shows *Noted.*
- `curl /memories` → JSON shows the fact stored with timestamp.
- Second correction: "My name is Deva." → Noted.

## Beat 3 — Kill it (1:20–2:00)
- `docker rm -f partner && docker run ...` (or gcloud replace on Cloud Run).
- Show the process actually dying (container gone).

## Beat 4 — The money shot (2:00–2:50)
- New session: "What format do you use for answers to me?"
- Reply cites bullet lists **[STRONG]** unprompted.
- "What's my name?" → "Deva [STRONG]".
- Line: "Not a demo trick — memory is a volume mount + honest verdicts."

## Beat 5 — Auditability (2:50–3:30)
- `curl /memories` → full fact store visible.
- Introduce a WEAK case: single fuzzy mention → agent asks to confirm instead
  of assuming ("Still prefer Vim?"). Contrast with STRONG behavior.
- One line on how verdicts are computed (overlap count + recency) — honesty,
  not vibes.

## Beat 6 — GCP proof + close (3:30–4:00)
- Cloud Console → Cloud Run → service page with live URL.
- curl the .run.app URL /healthz and /chat live.
- Close: "Partner adapts across sessions because memory is infrastructure,
  not chat history. Built on Gemini 3.5 Flash, GenAI SDK, Cloud Run."

## Shot list
- [ ] Screen recording 2560×1440, dark terminal, font ≥16pt
- [ ] Pre-stage: two terminals (one for curl, one for docker/gcloud)
- [ ] Do NOT show API keys; env vars pre-loaded
- [ ] Captions for each beat title
