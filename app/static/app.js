const messagesEl = document.getElementById("messages");
const listEl = document.getElementById("conversations");
const form = document.getElementById("form");
const input = document.getElementById("input");
const sendBtn = form.querySelector("button");

// id: current conversation (null = new chat, created lazily on first send).
const state = { id: null, busy: false };

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.status === 204 ? null : res.json();
}

// ---- messages ----
function addMessage(role, text = "") {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  messagesEl.append(el);
  setText(el, role, text);
  return el;
}

function setText(el, role, text) {
  if (role === "assistant") el.innerHTML = DOMPurify.sanitize(marked.parse(text));
  else el.textContent = text;
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// POST + ReadableStream: yields parsed `data: {json}` SSE events.
async function* readSSE(response) {
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += value;
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, i);
      buf = buf.slice(i + 2);
      if (frame.startsWith("data: ")) yield JSON.parse(frame.slice(6));
    }
  }
}

// ---- sidebar ----
async function refreshList() {
  const convs = await api("/conversations");
  listEl.replaceChildren(...convs.map(renderConv));
}

function renderConv(c) {
  const row = document.createElement("div");
  row.className = "conv" + (c.id === state.id ? " active" : "");
  const link = document.createElement("a");
  link.href = `#${c.id}`;
  link.textContent = c.title;
  const rename = document.createElement("button");
  rename.textContent = "✎";
  rename.title = "Rename";
  rename.onclick = async () => {
    const title = prompt("Rename conversation", c.title)?.trim();
    if (title) { await api(`/conversations/${c.id}`, { method: "PATCH", body: JSON.stringify({ title }) }); refreshList(); }
  };
  const del = document.createElement("button");
  del.textContent = "✕";
  del.title = "Delete";
  del.onclick = async () => {
    if (!confirm(`Delete "${c.title}"?`)) return;
    await api(`/conversations/${c.id}`, { method: "DELETE" });
    if (c.id === state.id) openConversation(null);
    refreshList();
  };
  row.append(link, rename, del);
  return row;
}

async function openConversation(id) {
  state.id = id;
  messagesEl.replaceChildren();
  document.body.classList.remove("nav-open");
  if (location.hash.slice(1) !== (id ?? "")) history.replaceState(null, "", id ? `#${id}` : location.pathname);
  if (id) {
    try {
      const conv = await api(`/conversations/${id}`);
      conv.messages.forEach((m) => addMessage(m.role, m.content));
    } catch {
      return openConversation(null); // stale link
    }
  }
  refreshList();
  input.focus();
}

// ---- sending ----
async function send(text) {
  if (!state.id) {
    state.id = (await api("/conversations", { method: "POST" })).id;
    history.replaceState(null, "", `#${state.id}`);
  }
  addMessage("user", text);
  const el = addMessage("assistant");
  let reply = "";
  try {
    const res = await fetch(`/api/conversations/${state.id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: text }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    for await (const ev of readSSE(res)) {
      if (ev.type === "delta") { reply += ev.text; setText(el, "assistant", reply); }
      else if (ev.type === "error") throw new Error(ev.message);
    }
  } catch (err) {
    el.className = "msg error";
    el.textContent = `Error: ${err.message}`;
  }
  refreshList(); // picks up the new title and recency order
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || state.busy) return;
  input.value = "";
  state.busy = sendBtn.disabled = true;
  try { await send(text); }
  finally { state.busy = sendBtn.disabled = false; input.focus(); }
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
});

document.getElementById("new-chat").onclick = () => openConversation(null);
document.getElementById("toggle-nav").onclick = () => document.body.classList.toggle("nav-open");
window.addEventListener("hashchange", () => {
  const id = location.hash.slice(1) || null;
  if (id !== state.id) openConversation(id);
});

openConversation(location.hash.slice(1) || null);
