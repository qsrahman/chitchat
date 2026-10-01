const messagesEl = document.getElementById("messages");
const listEl = document.getElementById("conversations");
const form = document.getElementById("form");
const input = document.getElementById("input");
const sendBtn = form.querySelector("button");

// id: current conversation (null = new chat, created lazily on first send).
const state = { id: null, busy: false, abort: null };

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.status === 204 ? null : res.json();
}

// ---- messages ----
// Each .msg = .body (rendered text) + .actions (buttons). el._text keeps the raw text for copy/edit.
function addMessage(role, text = "") {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  for (const cls of ["body", "actions"]) el.append(Object.assign(document.createElement("div"), { className: cls }));
  messagesEl.append(el);
  setText(el, text);
  return el;
}

function setText(el, text) {
  el._text = text;
  const body = el.firstElementChild;
  if (el.classList.contains("assistant")) body.innerHTML = DOMPurify.sanitize(marked.parse(text));
  else body.textContent = text;
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function actionButton(label, onclick) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  b.onclick = onclick;
  return b;
}

const clearActions = () => messagesEl.querySelectorAll(".actions").forEach((a) => a.replaceChildren());

// Copy on every reply; Edit on the last user message; Regenerate on the last reply, or
// Retry when the conversation ends on a user message or an error.
function updateActions() {
  clearActions();
  if (state.busy) return;
  const msgs = [...messagesEl.children];
  const last = msgs.at(-1);
  const lastUser = msgs.findLast((m) => m.classList.contains("user"));
  const actionsOf = (m) => m.lastElementChild;
  for (const m of msgs.filter((m) => m.classList.contains("assistant"))) {
    actionsOf(m).append(actionButton("Copy", async (e) => {
      await navigator.clipboard.writeText(m._text);
      e.target.textContent = "Copied";
      setTimeout(() => (e.target.textContent = "Copy"), 1200);
    }));
  }
  lastUser?.lastElementChild.append(actionButton("Edit", () => startEdit(lastUser)));
  if (last?.classList.contains("assistant")) actionsOf(last).append(actionButton("Regenerate", regenerate));
  else if (last) actionsOf(last).append(actionButton("Retry", regenerate));
}

function startEdit(m) {
  clearActions();
  const ta = document.createElement("textarea");
  ta.className = "edit";
  ta.value = m._text;
  m.firstElementChild.replaceChildren(ta);
  m.lastElementChild.append(
    actionButton("Save", () => {
      const text = ta.value.trim();
      if (!text) return;
      while (m.nextElementSibling) m.nextElementSibling.remove();
      setText(m, text);
      runTurn("edit", { content: text });
    }),
    actionButton("Cancel", () => { setText(m, m._text); updateActions(); }),
  );
  ta.focus();
}

function regenerate() {
  const msgs = messagesEl.children;
  while (msgs.length && !msgs[msgs.length - 1].classList.contains("user")) msgs[msgs.length - 1].remove();
  runTurn("regenerate");
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
  state.abort?.abort(); // a reply still streaming is saved as stopped
  state.id = id;
  messagesEl.replaceChildren();
  document.body.classList.remove("nav-open");
  if (location.hash.slice(1) !== (id ?? "")) history.replaceState(null, "", id ? `#${id}` : location.pathname);
  if (id) {
    try {
      const conv = await api(`/conversations/${id}`);
      conv.messages.forEach((m) => addMessage(m.role, m.content));
      updateActions();
    } catch {
      return openConversation(null); // stale link
    }
  }
  refreshList();
  input.focus();
}

// ---- sending ----
// Streams a reply from POST /api/conversations/{id}/{path} into a new assistant message.
async function runTurn(path, payload = {}) {
  state.busy = true;
  sendBtn.textContent = "Stop";
  state.abort = new AbortController();
  updateActions();
  const el = addMessage("assistant");
  let reply = "";
  try {
    if (!state.id) {
      state.id = (await api("/conversations", { method: "POST" })).id;
      history.replaceState(null, "", `#${state.id}`);
    }
    const res = await fetch(`/api/conversations/${state.id}/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: state.abort.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    for await (const ev of readSSE(res)) {
      if (ev.type === "delta") { reply += ev.text; setText(el, reply); }
      else if (ev.type === "error") throw new Error(ev.message);
    }
  } catch (err) {
    if (err.name !== "AbortError") { // Stop keeps the partial reply on screen
      el.className = "msg error";
      setText(el, `Error: ${err.message}`);
    }
  } finally {
    state.busy = false;
    state.abort = null;
    sendBtn.textContent = "Send";
    if (el.classList.contains("assistant") && !el._text) el.remove();
    updateActions();
    input.focus();
  }
  refreshList(); // picks up the new title and recency order
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  if (state.busy) return state.abort?.abort(); // the button reads "Stop" while streaming
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  addMessage("user", text);
  runTurn("chat", { content: text });
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    if (!state.busy) form.requestSubmit();
  }
});

document.getElementById("new-chat").onclick = () => openConversation(null);
document.getElementById("toggle-nav").onclick = () => document.body.classList.toggle("nav-open");
window.addEventListener("hashchange", () => {
  const id = location.hash.slice(1) || null;
  if (id !== state.id) openConversation(id);
});

openConversation(location.hash.slice(1) || null);
