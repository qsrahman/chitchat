import { renderMarkdown, renderReasoning } from "./markdown.js";

const $ = (id) => document.getElementById(id);
const main = document.querySelector("main");
const messagesEl = $("messages");
const thread = $("thread");
const input = $("input");
const sendBtn = $("send");
const form = $("form");
const composer = document.querySelector(".composer");

// id: current conversation (null = new chat, created lazily on first send).
// stick: keep the view pinned to the bottom unless the reader scrolled up.
// settings: the current conversation's settings (kept client-side until a new chat's first send creates it).
const DEFAULT_SETTINGS = { model: null, system_prompt: "", reasoning_effort: null, temperature: null };
const state = { id: null, busy: false, abort: null, stick: true, convs: [], settings: { ...DEFAULT_SETTINGS } };

// 20x20 stroke icons (see iconButton).
const ICONS = {
  copy: "M7 7h9v9H7zM13 7V4H4v9h3",
  check: "M4 10l4 4 8-8",
  refresh: "M16 10a6 6 0 1 1-1.8-4.3M16 4v3.5h-3.5",
  pencil: "M4 16l1-4 8-8 3 3-8 8-4 1zM11 6l3 3",
  trash: "M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10",
  code: "M7 6l-4 4 4 4M13 6l4 4-4 4",
  chat: "M4 5h12v8H9l-4 3v-3H4z",
  scale: "M10 4v12M5 16h10M4 7h12M4 7l-2 5h4zM16 7l-2 5h4z",
};

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
// Each .msg = [details.reasoning] + .body (rendered text) + .note (stopped / cut off / usage) + .actions.
// el._text and el._reasoning are the raw texts.
function addMessage(role, text = "", meta = {}) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  for (const cls of ["body", "note", "actions"]) el.append(Object.assign(document.createElement("div"), { className: cls }));
  thread.append(el);
  main.classList.add("is-started");
  setNote(el, meta);
  if (meta.reasoning) setReasoning(el, meta.reasoning);
  setText(el, text);
  return el;
}

const bodyOf = (el) => el.querySelector(".body");
const noteOf = (el) => el.querySelector(".note");
const actionsOf = (el) => el.querySelector(".actions");

const tokens = new Intl.NumberFormat();
const usageText = (u) => `${tokens.format(u.input_tokens)} in, ${tokens.format(u.output_tokens)} out` +
  (u.reasoning_tokens ? ` (${tokens.format(u.reasoning_tokens)} reasoning)` : "");

function setNote(el, meta) {
  const note = noteOf(el);
  note.textContent = [
    meta.stopped && "Stopped.",
    meta.incomplete && "Reply cut off: output limit reached.",
    meta.usage && usageText(meta.usage),
  ].filter(Boolean).join(" ");
  note.hidden = !note.textContent;
}

// Re-rendering markdown on every delta is wasteful; coalesce to one render per frame.
function schedule(el) {
  el._frame ??= requestAnimationFrame(() => render(el));
}
function setText(el, text) {
  el._text = text;
  schedule(el);
}
function setReasoning(el, text) {
  el._reasoning = text;
  schedule(el);
}

// The reasoning summary sits above the answer in a <details>: open and "Thinking…" while it streams,
// collapsed and "Reasoning" once the answer starts or for a saved message.
function reasoningOf(el) {
  let details = el.querySelector(".reasoning");
  if (!details) {
    details = document.createElement("details");
    details.className = "reasoning";
    details.innerHTML = '<summary>Reasoning</summary><div class="reasoning-body"></div>';
    el.prepend(details);
  }
  return details;
}

function finishReasoning(el) {
  const details = el.querySelector(".reasoning");
  if (!details) return;
  details.open = false;
  details.querySelector("summary").textContent = "Reasoning";
}

function render(el) {
  cancelAnimationFrame(el._frame);
  el._frame = null;
  const body = bodyOf(el);
  if (el._reasoning) reasoningOf(el).querySelector(".reasoning-body").innerHTML = renderReasoning(el._reasoning);
  if (el.classList.contains("assistant")) {
    if (el._text) body.innerHTML = renderMarkdown(el._text);
    else if (el._reasoning) body.replaceChildren(); // the reasoning block is the progress indicator
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
// Retry when the conversation ends on a user message or an error. Icon buttons, named by aria-label.
function updateActions() {
  clearActions();
  if (state.busy) return;
  const msgs = [...thread.children];
  const last = msgs.at(-1);
  const lastUser = msgs.findLast((m) => m.classList.contains("user"));
  for (const m of msgs.filter((m) => m.classList.contains("assistant"))) {
    const copy = iconButton("Copy", ICONS.copy, async () => {
      await navigator.clipboard.writeText(m._text);
      confirmed(copy);
    });
    actionsOf(m).append(copy);
  }
  if (lastUser) actionsOf(lastUser).append(iconButton("Edit", ICONS.pencil, () => startEdit(lastUser)));
  if (last?.classList.contains("assistant")) actionsOf(last).append(iconButton("Regenerate", ICONS.refresh, regenerate));
  else if (last && lastUser) actionsOf(last).append(actionButton("Retry", () => retry(lastUser)));
}

// Briefly show a check mark and "Copied" on an icon button.
function confirmed(btn) {
  const path = btn.querySelector("path");
  const [d, label] = [path.getAttribute("d"), btn.getAttribute("aria-label")];
  path.setAttribute("d", ICONS.check);
  btn.setAttribute("aria-label", "Copied");
  btn.title = "Copied";
  setTimeout(() => { path.setAttribute("d", d); btn.setAttribute("aria-label", label); btn.title = label; }, 1200);
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

// Retry differs from Regenerate: after a failed send or edit the server may not have what the page
// shows, so regenerating would 409 (message never saved) or reply to stale text (edit never saved).
// Compare the page with what the server stored, and redo the turn the way that makes them agree.
async function retry(user) {
  const dropAfterUser = () => { while (thread.lastElementChild !== user) thread.lastElementChild.remove(); };
  let saved;
  try {
    saved = state.id ? (await api(`/conversations/${state.id}`)).messages.filter((m) => m.role === "user") : [];
  } catch {
    dropAfterUser();
    addMessage("error", "Couldn't reach the server. Check your connection and retry.");
    return updateActions();
  }
  if (saved.length < thread.querySelectorAll(".msg.user").length) { // this message never landed
    dropAfterUser();
    runTurn("chat", { content: user._text });
  } else if (saved.at(-1).content === user._text) { // it landed; any reply (or partial one) is replaced
    regenerate();
  } else { // an edit that never landed
    dropAfterUser();
    runTurn("edit", { content: user._text });
  }
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
// Yields parsed `data: {json}` SSE events. Hand-written because EventSource is GET-only, and these turns
// are POSTs; TextDecoderStream does the decoding. Comment frames (keepalive pings) are skipped.
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
  let finished = false;
  try {
    if (!state.id) {
      state.id = (await api("/conversations", { method: "POST", body: JSON.stringify({ settings: state.settings }) })).id;
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
      if (ev.type === "delta") {
        if (!reply) finishReasoning(el);
        reply += ev.text;
        setText(el, reply);
      } else if (ev.type === "reasoning_delta") {
        if (!el._reasoning) { // first of the stream: show it live
          const details = reasoningOf(el);
          details.open = true;
          details.querySelector("summary").textContent = "Thinking…";
        }
        setReasoning(el, (el._reasoning ?? "") + ev.text);
      } else if (ev.type === "done") { finished = true; setNote(el, ev); }
      else if (ev.type === "error") throw new Error(ev.message);
    }
    if (!finished) throw new Error("The connection closed before the reply finished.");
  } catch (err) {
    if (err.name === "AbortError") setNote(el, { stopped: true });
    else {
      el.className = "msg error";
      el.querySelector(".reasoning")?.remove();
      el._reasoning = null;
      setText(el, `Couldn't get a reply. ${err.message}`);
    }
  } finally {
    finishReasoning(el);
    render(el);
    if (el.classList.contains("assistant") && !el._text && !el._reasoning) el.remove();
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
  saveDraft();
  fit();
  syncComposer();
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
input.addEventListener("input", () => { fit(); syncComposer(); syncSend(); saveDraft(); });

// One line sits in a single row with the send button. Once the text takes more than a line the input gets
// the full width and send drops below; it stays that way until the box is empty, so wrapping can't flip-flop.
function syncComposer() {
  const style = getComputedStyle(input);
  const padding = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
  const lines = Math.round((input.scrollHeight - padding) / parseFloat(style.lineHeight));
  const multiline = input.value !== "" &&
    (composer.classList.contains("is-multiline") || input.value.includes("\n") || lines > 1);
  composer.classList.toggle("is-multiline", multiline);
}

// Unsent text is kept per conversation (and for the new-chat screen), so a reload or a switch loses nothing.
const draftKey = () => `chitchat:draft:${state.id ?? "new"}`;
function saveDraft() {
  try {
    if (input.value) localStorage.setItem(draftKey(), input.value);
    else localStorage.removeItem(draftKey());
  } catch { /* storage blocked: drafts just aren't kept */ }
}
function loadDraft() {
  try { input.value = localStorage.getItem(draftKey()) ?? ""; } catch { input.value = ""; }
  fit();
  syncComposer();
  syncSend();
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && state.busy && !document.querySelector("dialog[open]")) state.abort?.abort();
});

const STARTERS = [
  [ICONS.chat, "Explain how database indexes work, with a short example"],
  [ICONS.code, "Write a Python script that renames files by their modified date"],
  [ICONS.scale, "Compare SQLite and Postgres for a side project"],
  [ICONS.pencil, "Draft a polite email asking to move a meeting to next week"],
];
$("starters").append(...STARTERS.map(([icon, text]) => {
  const li = document.createElement("li");
  const button = actionButton(text, () => !state.busy && submit(text));
  button.prepend(Object.assign(document.createElement("span"), { innerHTML: `<svg viewBox="0 0 20 20" aria-hidden="true"><path d="${icon}"/></svg>` }));
  li.append(button);
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
  b.title = label;
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
    iconButton(`Rename "${c.title}"`, ICONS.pencil, () => renameConv(c)),
    iconButton(`Delete "${c.title}"`, ICONS.trash, () => deleteConv(c)),
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

// ---- settings ----
function setSettings(settings) {
  state.settings = settings;
  $("settings-btn").toggleAttribute("data-active", Object.keys(DEFAULT_SETTINGS).some((k) => settings[k] !== DEFAULT_SETTINGS[k]));
}

// Dialogs that save to the server stay open until the save succeeds.
function bindSave(dlg, save) {
  const error = dlg.querySelector(".field-error");
  dlg.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    error.hidden = true;
    try {
      await save();
      dlg.close("save");
    } catch {
      error.textContent = "Couldn't save. Check your connection and try again.";
      error.hidden = false;
    }
  });
}

let reasoningModels = new Map(); // model id -> takes reasoning effort (otherwise temperature)
function syncSettingsFields() {
  const reasoning = reasoningModels.get($("set-model").value); // "" = the default model
  $("effort-field").hidden = reasoning === false;
  $("temp-field").hidden = reasoning === true; // unknown model: show both, the server sends the one that applies
}
$("set-model").addEventListener("change", syncSettingsFields);

async function openSettings() {
  const { default: fallback, efforts, models } = await api("/models");
  const s = state.settings;
  reasoningModels = new Map([["", models[0].reasoning], ...models.map((m) => [m.id, m.reasoning])]);
  const options = models.slice(1).map((m) => new Option(m.id, m.id));
  if (s.model && !reasoningModels.has(s.model)) options.push(new Option(s.model, s.model)); // no longer listed
  $("set-model").replaceChildren(new Option(`Default (${fallback})`, ""), ...options);
  $("set-effort").replaceChildren(new Option("Default", ""), ...efforts.map((e) => new Option(e, e)));
  $("set-model").value = s.model ?? "";
  $("set-system").value = s.system_prompt;
  $("set-effort").value = s.reasoning_effort ?? "";
  $("set-temp").value = s.temperature ?? "";
  syncSettingsFields();
  $("settings-dialog").querySelector(".field-error").hidden = true;
  $("settings-dialog").showModal();
}
$("settings-btn").onclick = openSettings;

bindSave($("settings-dialog"), async () => {
  const next = {
    model: $("set-model").value || null,
    system_prompt: $("set-system").value.trim(),
    reasoning_effort: $("set-effort").value || null,
    temperature: $("set-temp").value === "" ? null : Number($("set-temp").value),
  };
  if (state.id) setSettings((await api(`/conversations/${state.id}`, { method: "PATCH", body: JSON.stringify({ settings: next }) })).settings);
  else setSettings(next);
});

$("instructions-btn").onclick = async () => {
  const dlg = $("instructions-dialog");
  $("set-instructions").value = (await api("/custom-instructions")).text;
  dlg.querySelector(".field-error").hidden = true;
  dlg.showModal();
};
bindSave($("instructions-dialog"), () =>
  api("/custom-instructions", { method: "PUT", body: JSON.stringify({ text: $("set-instructions").value }) }));

// ---- navigation ----
// The sidebar starts closed. On narrow screens it is an overlay, so choosing something closes it.
function setNavOpen(open) {
  document.body.classList.toggle("nav-open", open);
  $("scrim").hidden = !open;
  const label = open ? "Hide conversations" : "Show conversations";
  for (const toggle of document.querySelectorAll(".nav-toggle")) {
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", label);
    toggle.title = label;
  }
}
function closeNavIfOverlay() {
  if (matchMedia("(max-width: 760px)").matches) setNavOpen(false);
}
document.querySelectorAll(".nav-toggle").forEach((b) => {
  b.onclick = () => setNavOpen(!document.body.classList.contains("nav-open"));
});
$("scrim").onclick = () => setNavOpen(false);

async function openConversation(id) {
  state.abort?.abort(); // a reply still streaming is saved as stopped
  state.id = id;
  state.stick = true;
  thread.replaceChildren();
  main.classList.remove("is-started");
  closeNavIfOverlay();
  if (location.hash.slice(1) !== (id ?? "")) history.replaceState(null, "", id ? `#${id}` : location.pathname);
  setSettings({ ...DEFAULT_SETTINGS });
  if (id) {
    try {
      const conv = await api(`/conversations/${id}`);
      setSettings(conv.settings);
      conv.messages.forEach((m) => addMessage(m.role, m.content, m.meta));
      thread.querySelectorAll(".msg").forEach(render);
    } catch {
      return openConversation(null); // stale link
    }
  }
  updateActions();
  scrollToBottom();
  loadDraft();
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
