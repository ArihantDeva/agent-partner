"""Collaborative Partner agent loop.

Flow per turn:
1. recall() facts for the user's message -> context_block()
2. system prompt = persona + fact block + session summary
3. Gemini generates reply (cites [STRONG]/[WEAK] chips when using memory)
4. correction detector scans the USER message; on correction, remember()

The Collaborative Partner track is won on statefulness: corrections persist,
next session recalls them with honest verdicts.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

from google import genai
from google.genai import types

sys.path.insert(0, str(os.path.dirname(os.path.abspath(__file__))))
import memory  # noqa: E402
from model_config import MODEL  # noqa: E402

SYSTEM_BASE = """You are Partner, a collaborative AI that gets better the longer it knows someone.

Rules:
1. When known facts are provided, USE them. Cite inline as [STRONG] or [WEAK]
   matching the label given. Never invent a memory.
2. If a fact is [WEAK], confirm before acting on it ("still prefer X?").
3. When the user states a preference, corrects you, or shares something durable
   about themselves, acknowledge briefly ("Noted.") — the system records it.
4. Ask clarifying questions before big assumptions. Adapt explanations to
   their level once you know it.
5. Be concise. No filler, no "As an AI" talk."""

CORRECTION_PATTERNS = [
    re.compile(r"\b(?:no|nope|actually|instead|rather)\b[,.!]?\s+(?:i|my|we)?\s*(?:prefer|use|want|like|am|do)\b", re.I),
    re.compile(r"\bdon'?t\s+use\b", re.I),
    re.compile(r"\balways\s+(?:use|prefer|want)\b", re.I),
    re.compile(r"\bi\s+(?:prefer|hate|love|always|never|usually)\b", re.I),
    re.compile(r"\bstop\s+(?:doing|using|suggesting)\b", re.I),
    re.compile(r"\bcall me\b", re.I),
    re.compile(r"\bmy name is\b", re.I),
    re.compile(r"\bi\s+work\s+(?:at|for|on)\b", re.I),
]


def looks_like_correction(text: str) -> bool:
    """Cheap regex gate (no LLM call): does this utterance carry durable info?"""
    return any(p.search(text) for p in CORRECTION_PATTERNS)


@dataclass
class Turn:
    role: str  # "user" | "model"
    text: str


@dataclass
class Session:
    session_id: str
    history: list[Turn] = field(default_factory=list)
    memories_used: list[str] = field(default_factory=list)

    def to_contents(self) -> list[types.Content]:
        out = []
        for t in self.history[-20:]:  # window keeps tokens bounded
            role = "user" if t.role == "user" else "model"
            out.append(types.Content(role=role, parts=[types.Part(text=t.text)]))
        return out


class PartnerAgent:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
        self.model = model or MODEL
        self.sessions: dict[str, Session] = {}

    def _system_prompt(self, query: str) -> str:
        block = memory.context_block(query, n=5)
        parts = [SYSTEM_BASE]
        if block:
            parts.append(block)
        return "\n\n".join(parts)

    def chat(self, session_id: str, message: str) -> dict:
        """One turn. Returns {reply, memories_used, remembered}."""
        sess = self.sessions.setdefault(session_id, Session(session_id=session_id))

        # 0. correction capture happens BEFORE reply so this turn's context
        # already includes the corrected preference
        remembered: list[str] = []
        if looks_like_correction(message):
            title = f"user-fact-{len(sess.history)}"
            if memory.remember(title, message.strip(), kind="preference"):
                remembered.append(message.strip())

        # 1-2. recall + compose
        system = self._system_prompt(message)
        contents = sess.to_contents()
        contents.append(types.Content(role="user", parts=[types.Part(text=message)]))

        # 3. generate
        resp = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.3,
            ),
        )
        reply = resp.text or ""

        used = re.findall(r"\[(STRONG|WEAK)\]", reply)
        sess.history.append(Turn("user", message))
        sess.history.append(Turn("model", reply))
        sess.memories_used = used

        return {"reply": reply, "memories_used": used, "remembered": remembered}

    def new_session_fresh(self) -> bool:
        """Demo helper: simulate process restart by dropping in-memory history.
        Facts persist via the file store — this is the money shot."""
        self.sessions.clear()
        return True
