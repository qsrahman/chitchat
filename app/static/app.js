import { renderMarkdown } from "./markdown.js";

const $ = (id) => document.getElementById(id);
const main = document.querySelector("main");
const messagesEl = $("messages");
const thread = $("thread");
const input = $("input");
const sendBtn = $("send");
const form = $("form");

// id: current conversation (null = new chat, created lazily on first send).
// stick: keep the view pinned to the bottom unless the reader scrolled up.
const state = { id: null, busy: false, abort: null, stick: true, convs: [] };

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.status === 204 ? null : res.json();
}

// ---- scrolling ----
const nearBottom = () => messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
function scrollToBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }
messagesEl.addEventListener("scroll", () => {
  state.stick = nearBottom();
  $("jump").hidden = state.stick;
});
$("jump").onclick = () => { state.stick = true; scrollToBottom(); };

// ---- messages ----
// Each .msg = .body (rendered text) + .note (stopped / cut off) + .actions. el._text is the raw text.
function addMessage(role, text = "", meta = {}) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  for (const cls of ["body", "note", "actions"]) el.append(Object.assign(document.createElement("div"), { className: cls }));
  thread.append(el);
  main.classList.add("is-started");
  setNote(el, meta);
  setText(el, text);
  return el;
}

const bodyOf = (el) => el.querySelector(".body");
const noteOf = (el) => el.querySelector(".note");
const actionsOf = (el) => el.querySelector(".actions");

function setNote(el, meta) {
  const note = noteOf(el);
  note.textContent = meta.stopped ? "Stopped." : meta.incomplete ? "Reply cut off: output limit reached." : "";
  note.hidden = !note.textContent;
}

// Re-rendering markdown on every delta is wasteful; coalesce to one render per frame.
function setText(el, text) {
  el._text = text;
  el._frame ??= requestAnimationFrame(() => render(el));
}

function render(el) {
  cancelAnimationFrame(el._frame);
  el._frame = null;
  const body = bodyOf(el);
  if (el.classList.contains("assistant")) {
    if (el._text) body.innerHTML = renderMarkdown(el._text);
    else body.innerHTML = '<span class="dots" role="status" aria-label="Thinking"><i></i><i></i><i></i></span>';
  } else body.textContent = el._text;
  if (state.stick) scrollToBottom();
}

function actionButton(label, onclick) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  b.onclick = onclick;
  return b;
}

const clearActions = () => thread.querySelectorAll(".actions").forEach((a) => a.replaceChildren());

// Copy on every reply; Edit on the last user message; Regenerate on the last reply, or
// Retry when the conversation ends on a user message or an error.
function updateActions() {
  clearActions();
  if (state.busy) return;
  const msgs = [...thread.children];
  const last = msgs.at(-1);
  const lastUser = msgs.findLast((m) => m.classList.contains("user"));
  for (const m of msgs.filter((m) => m.classList.contains("assistant"))) {
    actionsOf(m).append(actionButton("Copy", async (e) => {
      await navigator.clipboard.writeText(m._text);
      e.target.textContent = "Copied";
      setTimeout(() => (e.target.textContent = "Copy"), 1200);
    }));
  }
  if (lastUser) actionsOf(lastUser).append(actionButton("Edit", () => startEdit(lastUser)));
  if (last?.classList.contains("assistant")) actionsOf(last).append(actionButton("Regenerate", regenerate));
  else if (last && lastUser) actionsOf(last).append(actionButton("Retry", () => retry(lastUser)));
}

function startEdit(m) {
  clearActions();
  const ta = document.createElement("textarea");
  ta.className = "edit";
  ta.setAttribute("aria-label", "Edit your message");
  ta.value = m._text;
  bodyOf(m).replaceChildren(ta);
  actionsOf(m).append(
    actionButton("Save", () => {
      const text = ta.value.trim();
      if (!text) return;
      while (m.nextElementSibling) m.nextElementSibling.remove();
      setText(m, text);
      runTurn("edit", { content: text });
    }),
    actionButton("Cancel", () => { render(m); updateActions(); }),
  );
  ta.focus();
}

function regenerate() {
  while (thread.lastElementChild && !thread.lastElementChild.classList.contains("user")) thread.lastElementChild.remove();
  runTurn("regenerate");
}

// Retry differs from Regenerate: a turn whose POST never landed leaves the user message in
// the DOM only, and regenerating that would 409 forever. Ask the server what it actually has.
async function retry(user) {
  const last = state.id && (await api(`/conversations/${state.id}`)).messages.at(-1);
  if (last?.role === "user" && last.content === user._text) return regenerate();
  while (thread.lastElementChild !== user) thread.lastElementChild.remove();
  runTurn("chat", { content: user._text });
}

// Copy button inside rendered code blocks (event delegation: the HTML is re-rendered while streaming).
thread.addEventListener("click", async (e) => {
  const btn = e.target.closest(".code-copy");
  if (!btn) return;
  await navigator.clipboard.writeText(btn.closest(".code").querySelector("code").innerText);
  btn.textContent = "Copied";
  setTimeout(() => (btn.textContent = "Copy"), 1200);
});

// ---- sse ----
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

// ---- sending ----
// Streams a reply from POST /api/conversations/{id}/{path} into a new assistant message.
async function runTurn(path, payload = {}) {
  const ctrl = (state.abort = new AbortController());
  state.busy = true;
  state.stick = true;
  thread.setAttribute("aria-busy", "true");
  syncSend();
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
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    for await (const ev of readSSE(res)) {
      if (ev.type === "delta") { reply += ev.text; setText(el, reply); }
      else if (ev.type === "done") setNote(el, ev);
      else if (ev.type === "error") throw new Error(ev.message);
    }
  } catch (err) {
    if (err.name === "AbortError") setNote(el, { stopped: true });
    else {
      el.className = "msg error";
      setText(el, `Couldn't get a reply. ${err.message}`);
    }
  } finally {
    render(el);
    if (el.classList.contains("assistant") && !el._text) el.remove();
    if (state.abort === ctrl) { // a newer turn may already own the UI (e.g. after switching chats)
      state.busy = false;
      state.abort = null;
      thread.removeAttribute("aria-busy");
      syncSend();
      updateActions();
      input.focus();
    }
  }
  refreshList(); // picks up the new title and recency order
}

function syncSend() {
  sendBtn.classList.toggle("is-stop", state.busy);
  sendBtn.setAttribute("aria-label", state.busy ? "Stop generating" : "Send message");
  sendBtn.disabled = !state.busy && !input.value.trim();
}

function submit(text) {
  input.value = "";
  fit();
  syncSend();
  addMessage("user", text);
  runTurn("chat", { content: text });
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  if (state.busy) return state.abort?.abort(); // the button is "Stop" while streaming
  const text = input.value.trim();
  if (text) submit(text);
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    if (!state.busy) form.requestSubmit();
  }
});

// Browsers without `field-sizing: content` get a manual auto-grow.
const fit = CSS.supports("field-sizing", "content") ? () => {} : () => {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
};
input.addEventListener("input", () => { fit(); syncSend(); });

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && state.busy && !document.querySelector("dialog[open]")) state.abort?.abort();
});

const STARTERS = [
  "Explain how database indexes work, with a short example",
  "Write a Python script that renames files by their modified date",
  "Compare SQLite and Postgres for a side project",
  "Draft a polite email asking to move a meeting to next week",
];
$("starters").append(...STARTERS.map((text) => {
  const li = document.createElement("li");
  li.append(actionButton(text, () => !state.busy && submit(text)));
  return li;
}));

// ---- sidebar ----
const DAY = 864e5;
function groupOf(iso) {
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const days = Math.round((startOfDay(new Date()) - startOfDay(new Date(iso))) / DAY);
  return days <= 0 ? "Today" : days === 1 ? "Yesterday" : days <= 7 ? "Previous 7 days" : "Older";
}

async function refreshList() {
  state.convs = await api("/conversations");
  renderList();
  setTitle(state.convs.find((c) => c.id === state.id)?.title);
}

function setTitle(title) {
  $("title").textContent = title || "New chat";
  document.title = title ? `${title} · ChitChat` : "ChitChat";
}

function renderList() {
  const nav = $("conversations");
  if (!state.convs.length) {
    nav.replaceChildren(Object.assign(document.createElement("p"), { className: "no-convs", textContent: "Your conversations will show up here." }));
    return;
  }
  const groups = Map.groupBy(state.convs, (c) => groupOf(c.updated_at)); // list is already newest-first
  nav.replaceChildren(...[...groups].flatMap(([name, convs]) => {
    const h = Object.assign(document.createElement("h2"), { textContent: name });
    const ul = document.createElement("ul");
    ul.append(...convs.map(renderConv));
    return [h, ul];
  }));
}

function iconButton(label, path, onclick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "icon-btn";
  b.setAttribute("aria-label", label);
  b.innerHTML = `<svg viewBox="0 0 20 20" aria-hidden="true"><path d="${path}"/></svg>`;
  b.onclick = onclick;
  return b;
}

function renderConv(c) {
  const li = document.createElement("li");
  li.className = "conv";
  const link = document.createElement("a");
  link.href = `#${c.id}`;
  link.textContent = c.title;
  link.title = c.title;
  if (c.id === state.id) link.setAttribute("aria-current", "page");
  link.onclick = closeNavIfOverlay;
  li.append(
    link,
    iconButton(`Rename "${c.title}"`, "M4 16l1-4 8-8 3 3-8 8-4 1zM11 6l3 3", () => renameConv(c)),
    iconButton(`Delete "${c.title}"`, "M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10", () => deleteConv(c)),
  );
  return li;
}

// ---- dialogs ----
function showDialog(dlg) {
  dlg.returnValue = "";
  return new Promise((resolve) => {
    dlg.addEventListener("close", () => resolve(dlg.returnValue), { once: true });
    dlg.showModal();
  });
}
document.querySelectorAll("dialog [data-cancel]").forEach((b) => (b.onclick = () => b.closest("dialog").close("cancel")));

async function renameConv(c) {
  $("rename-input").value = c.title;
  if ((await showDialog($("rename-dialog"))) !== "save") return;
  const title = $("rename-input").value.trim();
  if (!title) return;
  await api(`/conversations/${c.id}`, { method: "PATCH", body: JSON.stringify({ title }) });
  refreshList();
}

async function deleteConv(c) {
  $("delete-name").textContent = c.title;
  if ((await showDialog($("delete-dialog"))) !== "delete") return;
  await api(`/conversations/${c.id}`, { method: "DELETE" });
  if (c.id === state.id) await openConversation(null);
  else refreshList();
}

// ---- navigation ----
// The sidebar starts closed. On narrow screens it is an overlay, so choosing something closes it.
function setNavOpen(open) {
  document.body.classList.toggle("nav-open", open);
  $("scrim").hidden = !open;
  const toggle = $("toggle-nav");
  toggle.setAttribute("aria-expanded", String(open));
  toggle.setAttribute("aria-label", open ? "Hide conversations" : "Show conversations");
}
function closeNavIfOverlay() {
  if (matchMedia("(max-width: 760px)").matches) setNavOpen(false);
}
$("toggle-nav").onclick = () => setNavOpen(!document.body.classList.contains("nav-open"));
$("scrim").onclick = () => setNavOpen(false);

async function openConversation(id) {
  state.abort?.abort(); // a reply still streaming is saved as stopped
  state.id = id;
  state.stick = true;
  thread.replaceChildren();
  main.classList.remove("is-started");
  closeNavIfOverlay();
  if (location.hash.slice(1) !== (id ?? "")) history.replaceState(null, "", id ? `#${id}` : location.pathname);
  if (id) {
    try {
      const conv = await api(`/conversations/${id}`);
      conv.messages.forEach((m) => addMessage(m.role, m.content, m.meta));
      thread.querySelectorAll(".msg").forEach(render);
    } catch {
      return openConversation(null); // stale link
    }
  }
  updateActions();
  scrollToBottom();
  await refreshList();
  input.focus();
}

$("new-chat").onclick = () => openConversation(null);
window.addEventListener("hashchange", () => {
  const id = location.hash.slice(1) || null;
  if (id !== state.id) openConversation(id);
});

syncSend();
openConversation(location.hash.slice(1) || null);
