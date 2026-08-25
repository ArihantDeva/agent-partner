/* Partner UI logic — vanilla JS, no framework.
   Wires: chat, live brain sidebar, kill-the-process demo, memory inspector. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = {
  sessionId: "ui-" + Math.random().toString(36).slice(2, 10),
  facts: new Map(),   // title -> {verdict, body, kind}
};

/* ---------- verdict chips ---------- */
function chipEl(verdict, earned) {
  const s = document.createElement("span");
  s.className = "chip chip-" + verdict.toLowerCase() + (earned ? " chip-earned" : "");
  s.textContent = verdict;
  return s;
}

function renderVerdictsIn(text, earnedSet) {
  // split on [STRONG]/[WEAK] chips and render each as a colored badge
  const frag = document.createDocumentFragment();
  text.split(/(\[(?:STRONG|WEAK|CONFLICTED|STALE)\])/).forEach((part) => {
    const m = part.match(/^\[(STRONG|WEAK|CONFLICTED|STALE)\]$/);
    if (m) {
      frag.appendChild(chipEl(m[1], earnedSet && earnedSet.has(m[1])));
    } else if (part) {
      frag.appendChild(document.createTextNode(part));
    }
  });
  return frag;
}

/* ---------- chat ---------- */
function addMsg(role, text, metas) {
  const div = document.createElement("div");
  div.className = "msg msg-" + role;
  const earned = new Set((metas && metas.memories_used) || []);
  div.appendChild(renderVerdictsIn(text, role === "bot" ? earned : null));
  if (role === "bot" && metas) {
    if (metas.remembered && metas.remembered.length) {
      const note = document.createElement("div");
      note.className = "msg-meta";
      note.textContent = "🧠 remembered: " + metas.remembered.join(" | ");
      div.appendChild(note);
    }
  }
  $("#chat-log").appendChild(div);
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  return div;
}

async function send(text) {
  addMsg("user", text);
  const div = addMsg("bot", "");
  const earned = new Set();
  try {
    const r = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, message: text }),
    });
    if (!r.ok || !r.body) throw new Error("stream unavailable (" + r.status + ")");

    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "", full = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, idx); buf = buf.slice(idx + 2);
        if (!raw.startsWith("data: ")) continue;
        const evt = JSON.parse(raw.slice(6));
        if (evt.event === "delta") {
          full += evt.text;
          div.innerHTML = "";
          div.appendChild(renderVerdictsIn(full, null));
          $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
        } else if (evt.event === "done") {
          evt.memories_used.forEach((v) => earned.add(v));
          div.innerHTML = "";
          div.appendChild(renderVerdictsIn(evt.reply, earned));
          (evt.remembered || []).forEach(() => refreshBrain());
          refreshBrain();
        } else if (evt.event === "error") {
          div.appendChild(document.createTextNode("⚠️ " + evt.text));
        }
      }
    }
  } catch (e) {
    div.innerHTML = "";
    addMsg("bot", "⚠️ " + e.message);
  }
}

/* ---------- brain sidebar ---------- */
const VERDICT_ORDER = { STRONG: 0, WEAK: 1, CONFLICTED: 2, STALE: 3, SUPERSEDED: 4, UNKNOWN: 5 };

async function refreshBrain() {
  try {
    const rows = await (await fetch("/memories")).json();
    const list = $("#fact-list");
    list.innerHTML = "";
    rows.slice(0, 24).forEach((f) => {
      const tpl = $("#tpl-fact").content.cloneNode(true);
      const v = f.verdict || deriveVerdict(f);
      tpl.querySelector(".chip").className = "chip chip-" + v.toLowerCase();
      tpl.querySelector(".chip").textContent = v;
      tpl.querySelector(".fact-kind").textContent = f.kind || "note";
      tpl.querySelector(".fact-body").textContent = f.body;
      tpl.querySelector(".receipt blockquote").textContent = `“${f.body}” — ${new Date(f.ts * 1000).toLocaleString()}`;
      list.appendChild(tpl);
    });
    const n = rows.length;
    $("#stat-facts").textContent = n + " fact" + (n === 1 ? "" : "s");
    const counts = {};
    rows.forEach((f) => { const v = deriveVerdict(f); counts[v] = (counts[v] || 0) + 1; });
    $("#stat-verdicts").textContent = Object.entries(counts)
      .sort((a, b) => VERDICT_ORDER[a[0]] - VERDICT_ORDER[b[0]])
      .map(([v, c]) => `${c} ${v}`).join(" · ") || "—";
  } catch (_) { /* server down mid-kill: leave as-is */ }
}

/* /memories returns raw records; compute display verdict client-side
   mirroring the engine's public rules (server remains source of truth). */
function deriveVerdict(f) {
  if (f.status === "superseded") return "STALE";
  if (f.conflict_with || f.verdict === "CONFLICTED") return "CONFLICTED";
  if (f.stale_since) return "STALE";
  if ((f.reinforcements || 0) >= 1) return "STRONG";
  if (f.kind === "identity" || f.kind === "preference") return "STRONG";
  return "WEAK";
}

/* ---------- kill the process (the money shot) ---------- */
let killing = false;
$("#btn-kill").addEventListener("click", async () => {
  if (killing) return;
  killing = true;
  const btn = $("#btn-kill");
  btn.disabled = true;
  btn.textContent = "💀 killing container…";
  addMsg("bot", "⚡ Killing the serving process NOW. Chat history in RAM dies. Watch the dot go red — then reconnect and ask me what I remember.");

  try {
    await fetch("/demo/kill", { method: "POST" });  // best-effort; local docker path
  } catch (_) { /* request dies with the server — expected */ }

  // poll until back up
  const t0 = Date.now();
  $("#conn-dot").className = "dot dot-dead";
  btn.textContent = "🔴 process dead — waiting for restart…";

  const poll = setInterval(async () => {
    try {
      const r = await fetch("/health", { cache: "no-store" });
      if (r.ok) {
        clearInterval(poll);
        const secs = ((Date.now() - t0) / 1000).toFixed(1);
        $("#conn-dot").className = "dot dot-live";
        btn.disabled = false; killing = false;
        btn.textContent = "⚡ Kill the process";
        addMsg("bot", `✅ Reconnected after ${secs}s. New process, same brain. Ask: “What format do you use for answers to me?”`);
        refreshBrain();
      }
    } catch (_) { /* still down */ }
  }, 700);
});

/* ---------- sleep cycle ---------- */
$("#btn-sleep").addEventListener("click", async () => {
  const btn = $("#btn-sleep");
  btn.textContent = "💤 consolidating…";
  try {
    const report = await (await fetch("/sleep", { method: "POST" })).json();
    addMsg("bot", `🌙 Sleep cycle done — merged ${report.merged}, decayed ${report.decayed}, promoted ${report.promoted}.`);
  } catch (e) {
    addMsg("bot", "⚠️ sleep failed: " + e.message);
  }
  btn.textContent = "🌙 Sleep";
  refreshBrain();
});

/* ---------- inspector ---------- */
async function openInspector() {
  $("#inspector").classList.remove("hidden");
  await renderInspector();
}
function closeInspector() { $("#inspector").classList.add("hidden"); }

async function renderInspector() {
  const filter = $("#filter-verdict").value;
  const rows = await (await fetch("/memories")).json();
  const tbody = $("#inspector-rows");
  tbody.innerHTML = "";
  rows.forEach((f) => {
    const v = deriveVerdict(f);
    if (filter && v !== filter) return;
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td><span class="chip chip-${v.toLowerCase()}">${v}</span></td>` +
      `<td>${f.kind || ""}</td><td><code>${escapeHtml(f.title)}</code></td>` +
      `<td>${escapeHtml(f.body)}</td>` +
      `<td>${new Date(f.ts * 1000).toLocaleString()}</td>` +
      `<td>${f.status !== "active" ? escapeHtml(f.status) : ""}</td>`;
    tbody.appendChild(tr);
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

$("#btn-inspector").addEventListener("click", openInspector);
$("#btn-inspect-close").addEventListener("click", closeInspector);
$("#filter-verdict").addEventListener("change", renderInspector);

/* ---------- composer ---------- */
$("#chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  send(text);
});

/* ---------- boot ---------- */
refreshBrain();
