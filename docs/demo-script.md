# Demo video script — ~4 minutes

Rule: every claim shown live, never narrated over a slide. GCP proof beat is
mandatory (judges require deployment evidence). The kill happens FROM THE PAGE.

## Beat 1 — The problem (0:00–0:35)
- Fresh browser, fresh session. Ask Partner a personalization question:
  "How do you format answers for me?" → generic reply, empty brain sidebar.
- Line: "Every AI agent starts from zero. Every. Single. Time."

## Beat 2 — Teach it twice (0:35–1:15)
- "No, I prefer answers as bullet lists." → reply shows *Noted.*; a green
  [STRONG] chip POPS into the live-brain sidebar on the right.
- Click the chip → source receipt: the exact utterance + timestamp.
- Second fact: "My name is Deva." → second chip pops.

## Beat 3 — Kill it from the page (1:15–2:00)
- Hover the red button: "⚡ Kill the process".
- Click. Connection dot goes RED. Terminal (split view) shows the container
  exiting. Narrate: "That's `os._exit` inside the serving process — no graceful
  shutdown, no in-memory handoff. Chat history would normally be gone."
- Platform restarts the instance; dot goes green; UI reconnects with uptime note.

## Beat 4 — The money shot (2:00–2:45)
- New message: "What format do you use for answers to me?"
- Reply streams token-by-token and cites bullet lists **[STRONG]** unprompted.
- "What's my name?" → "Deva [STRONG]".
- Line: "Not a demo trick — memory is crash-safe files + verdicts computed by
  the engine, enforced by the server."

## Beat 5 — Honesty under adversarial probing (2:45–3:25)
- Ask something unrelated; show the model CANNOT fake memory: any unearned
  chip is stripped server-side (show one raw vs rendered if time).
- Introduce a contradiction: "Actually I use Emacs now" after teaching Vim →
  CONFLICTED chip appears in inspector; both sides shown; user adjudicates.
- Open Memory Inspector drawer: full store, filters, audit trail.
- One line on sleep cycles: click 🌙 Sleep → merge/decay/promote report.

## Beat 6 — Cloud Run + close (3:25–4:00)
- Browser tab 2: the deployed .run.app URL. Repeat teach→ask against Cloud Run.
- Show gcloud console service page briefly.
- Close: "Partner adapts across sessions because memory is infrastructure,
  not chat history. Gemini 3.5 Flash, GenAI SDK function calling, Cloud Run.
  Repo + eval suite in the description."

## Shot list
- [ ] Screen recording 2560×1440, dark UI, font ≥16pt
- [ ] Pre-stage: two tabs (local :8080 + .run.app), terminal split below
- [ ] Do NOT show API keys; env pre-loaded
- [ ] Captions per beat title
- [ ] Practice the kill→revive timing (~8s) before recording
