"""Collaborative Partner agent loop v2.

Flow per turn:
0. regex fast path captures obvious corrections (zero LLM cost)
1. recall() facts -> context block; first turn of a session gets a briefing
2. Gemini generates; may call tools (remember/recall/forget/update_fact/search_code)
3. tool results fed back; loop bounded at MAX_TOOL_CALLS
4. reply is chip-validated server-side: [STRONG]/[WEAK] chips are stripped
   unless an equally-strong fact was actually injected this turn
5. if nothing was captured by regex AND no tool wrote a fact, one cheap
   structured-output extractor pass decides whether the utterance was durable

The Collaborative Partner track is won on statefulness + honesty: corrections
persist across restarts, and verdict chips can never be faked by the model.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, str(os.path.dirname(os.path.abspath(__file__))))
import memory  # noqa: E402
from model_config import MODEL  # noqa: E402

MAX_TOOL_CALLS = 8


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)

SYSTEM_BASE = """You are Partner, a collaborative AI that gets better the longer it knows someone.

Rules:
1. When known facts are provided, USE them. Cite inline as [STRONG] or
   [WEAK] exactly matching the label given (bare token, no colons). Never
   invent a memory. Only cite a chip for facts present in your context this turn.
2. If a fact is [WEAK], confirm before acting on it ("still prefer X?").
3. If a fact is [CONFLICTED], show both versions and ask which is true.
4. If a fact is [STALE], mention it might be outdated.
5. Use the `remember` tool whenever the user shares something durable about
   themselves (preferences, identity, people, projects, skills, constraints) —
   even if it doesn't look like a correction to you.
6. Use `recall` before answering questions about the user or their past asks.
7. Acknowledge writes briefly ("Noted."). Be concise. No filler, no "As an AI" talk."""

TOOLS_SPEC = [
    {"name": "remember",
     "description": "Store a durable fact about the user with source receipt.",
     "parameters": {"type": "object", "properties": {
         "title": {"type": "string", "description": "short stable slug, e.g. coffee-preference"},
         "body": {"type": "string", "description": "the fact, close to user's words"},
         "kind": {"type": "string",
                  "enum": ["identity", "preference", "person", "project",
                           "constraint", "skill", "note"]}},
         "required": ["title", "body"]}},
    {"name": "recall",
     "description": "Search stored facts about the user.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
    {"name": "update_fact",
     "description": "Explicit correction of an existing fact; keeps audit trail.",
     "parameters": {"type": "object", "properties": {
         "title": {"type": "string"}, "new_body": {"type": "string"}},
         "required": ["title", "new_body"]}},
    {"name": "forget",
     "description": "User asked to forget something.",
     "parameters": {"type": "object", "properties": {
         "title": {"type": "string"}}, "required": ["title"]}},
    {"name": "search_code",
     "description": "Search the user's code/repos via heimdall (verified paths).",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
]

EXTRACTOR_PROMPT = """Extract durable facts about the USER from their message.
Return JSON: {"durable": bool, "facts": [{"title": str, "body": str, "kind":
"identity|preference|person|project|constraint|skill|note"}]}
Durable = still true tomorrow and useful then (preferences, identity, people,
projects, constraints, skills). Not durable = questions, chit-chat, tasks.
Message: {msg}"""

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


def _tool_declarations():
    """SDK-shaped tool declarations; falls back to raw dicts off-SDK (tests)."""
    try:
        from google.genai import types
        return [types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name=t["name"], description=t["description"],
                parameters=t["parameters"])
            for t in TOOLS_SPEC])]
    except Exception:
        return TOOLS_SPEC


_TOOL_DECL = _tool_declarations()


@dataclass
class Turn:
    role: str  # "user" | "model"
    text: str


@dataclass
class Session:
    session_id: str
    history: list[Turn] = field(default_factory=list)
    memories_used: list[str] = field(default_factory=list)
    briefed: bool = False


class ChipValidationError(Exception):
    pass


class PartnerAgent:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        from google import genai
        self.client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
        self.model = model or os.environ.get("GEMINI_MODEL") or MODEL
        self.sessions: dict[str, Session] = {}
        self._gen_config = None
        self.models = self.client.models   # test seam: swap with a fake

    # -- test seam: `models` is a plain attribute; real init wires it to client.models

    def _system_prompt(self, query: str, sess: Session) -> tuple[str, list[dict]]:
        """Compose system prompt. Returns (prompt, injected_facts)."""
        parts = [SYSTEM_BASE]
        injected = []
        block = memory.context_block(query, n=5)
        if block:
            parts.append(block)
            injected = memory.recall(query, n=5)

        if not sess.briefed:
            # welcome-back briefing: most recent memories, not query-matched —
            # a returning user gets told what Partner remembers, unprompted
            recent = memory.active_rows()[:3]
            if recent and not sess.history:
                lines = ["SESSION BRIEFING (user was away — greet them back "
                         "warmly, one line max, weave these in):"]
                for r in recent:
                    v = memory.verdict_of(r["title"])
                    lines.append(f"- [{v}] {r['body']}")
                parts.append("\n".join(lines))
            sess.briefed = True
        return "\n\n".join(parts), injected

    def _run_tools(self, sess: Session, fc, injected: list[dict]) -> dict:
        name = fc["name"] if isinstance(fc, dict) else fc.name
        args = dict(fc.get("args", {}) if isinstance(fc, dict) else (fc.args or {}))
        if name == "remember":
            ok = memory.remember(args.get("title", ""), args.get("body", ""),
                                 kind=args.get("kind", "note"))
            return {"result": "stored" if ok else "rejected (empty)"}
        if name == "recall":
            hits = memory.recall(args.get("query", ""), n=4)
            injected.clear()
            injected.extend(hits)
            return {"facts": [{"verdict": h["verdict"], "body": h["body"]} for h in hits]}
        if name == "update_fact":
            ok = memory.update_fact(args.get("title", ""), args.get("new_body", ""))
            return {"result": "updated" if ok else "not found"}
        if name == "forget":
            ok = memory.forget(args.get("title", ""))
            return {"result": "forgotten" if ok else "no such fact"}
        if name == "search_code":
            hits = memory.recall_code(args.get("query", ""), n=3)
            return {"code_hits": [{"verdict": h["verdict"], "path": h.get("path", h["body"])}
                                  for h in hits]} if hits else {"code_hits": []}
        return {"error": f"unknown tool {name}"}

    def _extractor_pass(self, message: str) -> list[dict]:
        """One cheap structured-output call deciding durability. Best-effort."""
        try:
            resp = self.models.generate_content(
                model=self.model,
                contents=[{"role": "user",
                           "parts": [{"text": EXTRACTOR_PROMPT.format(msg=message)}]}],
                config=self._gen_cfg(response_mime_type="application/json"),
            )
            data = json.loads(resp.text or "{}")
            if not data.get("durable"):
                return []
            out = []
            for f in data.get("facts", [])[:4]:
                title = (f.get("title") or "").strip()
                body = (f.get("body") or "").strip()
                if title and body:
                    memory.remember(title, body, kind=f.get("kind", "note"))
                    out.append(body)
            return out
        except Exception:
            return []

    def _gen_cfg(self, **kw):
        from google.genai import types
        return types.GenerateContentConfig(temperature=0.3, tools=_TOOL_DECL, **kw)

    def _session_live(self, session_id: str) -> bool:
        """H4 fix: a reset mid-stream revokes persistence for that turn."""
        return session_id in self.sessions

    def chat_stream(self, session_id: str, message: str):
        """Streaming variant of chat(): yields {event, text?, ...} dicts.

        events: delta (token chunk), done (final payload incl. chip-validated
        full reply), error. Same capture + validation semantics as chat().
        """
        from google.genai import types
        import sessions as session_store

        sess = self.sessions.get(session_id)
        if sess is None:
            sess = Session(session_id=session_id)
            persisted = session_store.load(session_id)
            if persisted:
                sess.history = [Turn(**t) for t in persisted]
                # M2 fix: resumed sessions get the briefing too
            self.sessions[session_id] = sess

        remembered: list[str] = []
        if looks_like_correction(message):
            title = f"{session_id}-fact-{len(sess.history)}-{_now_ms()}"
            if memory.remember(title, message.strip(), kind="preference"):
                remembered.append(message.strip())

        system, injected = self._system_prompt(message, sess)
        contents = [types.Content(role="user" if t.role == "user" else "model",
                                  parts=[types.Part(text=t.text)])
                    for t in sess.history[-20:]]
        contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
        config = types.GenerateContentConfig(
            system_instruction=system, temperature=0.3, tools=_TOOL_DECL)

        reply_bits: list[str] = []
        try:
            for _ in range(MAX_TOOL_CALLS + 1):
                stream = self.models.generate_content_stream(
                    model=self.model, contents=contents, config=config)
                func_call = None
                for chunk in stream:
                    cand = chunk.candidates[0] if getattr(chunk, "candidates", None) else None
                    parts = cand.content.parts if cand and getattr(cand, "content", None) else []
                    for part in (parts or []):
                        t = getattr(part, "text", None)
                        fc = getattr(part, "function_call", None)
                        if isinstance(t, str) and t and not fc:
                            reply_bits.append(t)
                            yield {"event": "delta", "text": t}
                        if fc:
                            func_call = fc
                if func_call is None:
                    break
                result = self._run_tools(sess, func_call, injected)
                fc_name = (func_call["name"] if isinstance(func_call, dict)
                           else func_call.name)
                contents.append(cand.content if cand else types.Content(role="model", parts=[]))
                contents.append(types.Content(role="user", parts=[types.Part(
                    function_response=types.FunctionResponse(name=fc_name,
                                                             response=result))]))
                # M3 fix: pre-tool text was already streamed to the user — keep
                # it in the final reply instead of silently discarding it

        except Exception as e:
            yield {"event": "error", "text": str(e)}
            return

        full = "".join(reply_bits).strip()
        allowed = {h["verdict"] for h in injected}
        full = _validate_chips(full, allowed)
        used = sorted({m.group(1).upper() for m in _CHIP_RE.finditer(full)})
        sess.history.append(Turn("user", message))
        sess.history.append(Turn("model", full))
        sess.memories_used = used
        if self._session_live(session_id):
            _persist(session_store, session_id, sess)
        yield {"event": "done", "reply": full, "memories_used": used,
               "remembered": remembered}

    def chat(self, session_id: str, message: str) -> dict:
        """One turn. Returns {reply, memories_used, remembered}."""
        from google.genai import types
        import sessions as session_store

        sess = self.sessions.get(session_id)
        if sess is None:
            sess = Session(session_id=session_id)
            persisted = session_store.load(session_id)
            if persisted:
                sess.history = [Turn(**t) for t in persisted]
                # M2 fix: resumed sessions ARE returning users — they get the
                # welcome-back briefing (that's the kill-demo payoff)
            self.sessions[session_id] = sess

        # 0. zero-cost fast path
        remembered: list[str] = []
        if looks_like_correction(message):
            title = f"{session_id}-fact-{len(sess.history)}-{_now_ms()}"
            if memory.remember(title, message.strip(), kind="preference"):
                remembered.append(message.strip())

        # 1-2. recall + compose
        system, injected = self._system_prompt(message, sess)
        contents = [types.Content(role="user" if t.role == "user" else "model",
                                  parts=[types.Part(text=t.text)])
                    for t in sess.history[-20:]]
        contents.append(types.Content(role="user", parts=[types.Part(text=message)]))

        config = types.GenerateContentConfig(
            system_instruction=system, temperature=0.3, tools=_TOOL_DECL)

        tool_writes: list[str] = []
        reply_text = ""
        for _ in range(MAX_TOOL_CALLS + 1):
            resp = self.models.generate_content(
                model=self.model, contents=contents, config=config)
            cand = resp.candidates[0] if getattr(resp, "candidates", None) else None
            text_bits, func_call = [], None
            parts = cand.content.parts if cand and getattr(cand, "content", None) else []
            for part in (parts or []):
                fc_text = getattr(part, "text", None)
                if isinstance(fc_text, str) and fc_text:
                    text_bits.append(fc_text)
                raw_fc = getattr(part, "function_call", None)
                if raw_fc:
                    func_call = raw_fc
            if func_call is None:
                reply_text = "".join(text_bits).strip()
                break
            # execute tool, feed result back (dict-shaped fake or SDK object)
            result = self._run_tools(sess, func_call, injected)
            fc_name = func_call["name"] if isinstance(func_call, dict) else func_call.name
            fc_args = (func_call.get("args", {}) if isinstance(func_call, dict)
                       else dict(func_call.args or {}))
            if fc_name == "remember":
                tool_writes.append(str(fc_args.get("body", "")))
            contents.append(cand.content)
            contents.append(types.Content(
                role="user",
                parts=[types.Part(
                    function_response=types.FunctionResponse(
                        name=fc_name, response=result))]))
        else:
            reply_text = "(I got tangled up mid-thought — try that again?)"

        # extractor fallback: regex missed AND model didn't write anything
        if not remembered and not tool_writes and not looks_like_correction(message):
            extracted = self._extractor_pass(message)
            remembered.extend(extracted)

        # 4. chip validation: only chips backed by same-verdict injected facts pass
        allowed = {h["verdict"] for h in injected}
        reply_text = _validate_chips(reply_text, allowed)
        used = sorted({m.group(1).upper() for m in _CHIP_RE.finditer(reply_text)})

        sess.history.append(Turn("user", message))
        sess.history.append(Turn("model", reply_text))
        sess.memories_used = used
        if self._session_live(session_id):
            _persist(session_store, session_id, sess)

        return {"reply": reply_text, "memories_used": used, "remembered": remembered}


_CHIP_RE = re.compile(
    r"\s*\[\s*(?:VERDICT\s*[:：]?\s*)?(STRONG|WEAK)\s*\]", re.I)


def _persist(store, session_id: str, sess: Session) -> None:
    """Best-effort save; failures logged, never silent."""
    import sys
    try:
        store.save(session_id,
                   [{"role": t.role, "text": t.text} for t in sess.history])
    except Exception as e:
        print(f"[partner] session persist failed for {session_id}: {e}",
              file=sys.stderr)


def _validate_chips(reply: str, allowed_verdicts: set[str]) -> str:
    """Strip any chip whose verdict wasn't earned by an injected fact this turn.

    Case/format-insensitive: [STRONG], [strong], [ VERDICT: STRONG ] all match.
    This is what makes 'the model cannot fake verdicts' literally true:
    enforcement lives in the server, not the prompt.
    """
    def repl(m):
        return m.group(0) if m.group(1).upper() in allowed_verdicts else ""
    return _CHIP_RE.sub(repl, reply)
