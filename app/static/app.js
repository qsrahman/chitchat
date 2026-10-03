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
const DEFAULT_SETTINGS = { model: null, system_prompt: "", reasoning_effort: null, temperature: null, tools: [] };
const state = { id: null, busy: false, abort: null, stick: true, convs: [], settings: { ...DEFAULT_SETTINGS }, tools: [] };

// 20x20 stroke icons (see iconButton).
const ICONS = {
  copy: "M7 7h9v9H7zM13 7V4H4v9h3",
  check: "M4 10l4 4 8-8",
  refresh: "M16 10a6 6 0 1 1-1.8-4.3M16 4v3.5h-3.5",
  pencil: "M4 16l1-4 8-8 3 3-8 8-4 1zM11 6l3 3",
  trash: "M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10",
  file: "M6 3h6l4 4v10H6zM12 3v4h4",
  close: "M5 5l10 10M15 5L5 15",
};
const icon = (path) => `<svg viewBox="0 0 20 20" aria-hidden="true"><path d="${path}"/></svg>`;

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
// Each .msg = [details.reasoning] + .body (rendered text) + .note (stopped / cut off / compacted) + .actions.
// el._text and el._reasoning are the raw texts.
function addMessage(role, text = "", meta = {}) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  for (const cls of ["body", "note", "actions"]) el.append(Object.assign(document.createElement("div"), { className: cls }));
  thread.append(el);
  main.classList.add("is-started");
  for (const call of meta.tools ?? []) renderToolCall(el, call);
  if (meta.attachments?.length) {
    el._attachments = meta.attachments;
    el.prepend(attachmentTiles(meta.attachments));
  }
  setNote(el, meta);
  if (meta.reasoning) setReasoning(el, meta.reasoning);
  setText(el, text);
  return el;
}

// Sent attachments: images as thumbnails that open full size, everything else as a download link. Names are
// untrusted, so they only ever go in as text.
function attachmentTiles(files) {
  const tiles = document.createElement("div");
  tiles.className = "attachments";
  for (const f of files) {
    const link = document.createElement("a");
    link.href = `/api/attachments/${f.id}`;
    if (f.kind === "image") {
      link.className = "tile-image";
      link.target = "_blank";
      link.rel = "noopener";
      link.title = f.name;
      const img = Object.assign(document.createElement("img"), { src: link.href, alt: f.name });
      link.append(img);
    } else {
      link.className = "tile-file";
      link.title = `Download ${f.name}`;
      link.innerHTML = icon(ICONS.file);
      link.append(Object.assign(document.createElement("span"), { className: "chip-name", textContent: f.name }));
    }
    tiles.append(link);
  }
  return tiles;
}

const bodyOf = (el) => el.querySelector(".body");
const noteOf = (el) => el.querySelector(".note");
const actionsOf = (el) => el.querySelector(".actions");

function setNote(el, meta) {
  const note = noteOf(el);
  note.textContent = [
    meta.stopped && "Stopped.",
    meta.incomplete && "Reply cut off: output limit reached.",
    meta.compaction && "Earlier messages were compacted to save context.",
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

// ---- tool calls ----
// A tool the model called shows as a line above the answer: "Searching the web for ..." while it runs, then
// "Searched the web for ..." that opens to the results. How each tool reads is in TOOL_UI; others get a plain line.
const hostOf = (url) => new URL(url).hostname.replace(/^www\./, "");
const isWebUrl = (url) => { try { return ["http:", "https:"].includes(new URL(url).protocol); } catch { return false; } };

const TOOL_UI = {
  web_search: {
    running: (args) => `Searching the web for “${args.query ?? ""}”…`,
    done: (args, shown) => {
      const n = shown.results.length;
      return `Searched the web for “${shown.query}” · ${n ? `${n} result${n === 1 ? "" : "s"}` : "no results"}`;
    },
    failed: (error) => `Web search failed: ${error}`,
    stopped: "Web search stopped",
    detail: (shown) => {
      const list = document.createElement("ol");
      for (const r of shown.results.filter((r) => isWebUrl(r.url))) { // URLs from the web are untrusted: web links only
        const item = document.createElement("li");
        const link = Object.assign(document.createElement("a"), { href: r.url, target: "_blank", rel: "noopener noreferrer", textContent: r.title });
        item.append(link, Object.assign(document.createElement("span"), { className: "domain", textContent: hostOf(r.url) }));
        if (r.description) item.append(Object.assign(document.createElement("p"), { textContent: r.description }));
        list.append(item);
      }
      return list;
    },
  },
};

function renderToolCall(el, call) {
  let box = el.querySelector(".tool-calls");
  if (!box) {
    box = Object.assign(document.createElement("div"), { className: "tool-calls" });
    bodyOf(el).before(box);
  }
  let row = [...box.children].find((d) => d.dataset.id === call.id);
  if (!row) {
    row = document.createElement("details");
    row.className = "tool-call";
    row.dataset.id = call.id;
    row.dataset.name = call.name;
    row.innerHTML = '<summary></summary><div class="tool-body"></div>';
    box.append(row);
  }
  const ui = TOOL_UI[call.name];
  row.dataset.status = call.status;
  row.setAttribute("aria-busy", String(call.status === "running"));
  row.querySelector("summary").textContent = {
    running: () => ui?.running(call.arguments ?? {}) ?? `Using ${call.name}…`,
    done: () => ui?.done(call.arguments ?? {}, call.display) ?? `Used ${call.name}`,
    error: () => ui?.failed(call.error) ?? `${call.name} failed: ${call.error}`,
    stopped: () => ui?.stopped ?? `${call.name} stopped`,
  }[call.status]();
  row.querySelector(".tool-body").replaceChildren(...(call.status === "done" && ui ? [ui.detail(call.display)] : []));
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
    else if (el._reasoning || el.querySelector(".tool-call")) body.replaceChildren(); // those are the progress indicator
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
  else if (last && lastUser) actionsOf(last).append(iconButton("Retry", ICONS.refresh, () => retry(lastUser)));
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
    runTurn("chat", { content: user._text, attachments: (user._attachments ?? []).map((a) => a.id) });
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
  let compaction = false;
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
      } else if (ev.type === "tool_call") {
        renderToolCall(el, ev);
        render(el);
      } else if (ev.type === "compaction") compaction = true;
      else if (ev.type === "done") { finished = true; setNote(el, { ...ev, compaction }); }
      else if (ev.type === "error") throw new Error(ev.message);
    }
    if (!finished) throw new Error("The connection closed before the reply finished.");
  } catch (err) {
    if (err.name === "AbortError") setNote(el, { stopped: true });
    else {
      el.className = "msg error";
      el.querySelector(".reasoning")?.remove();
      el.querySelector(".tool-calls")?.remove();
      el._reasoning = null;
      setText(el, `Couldn't get a reply. ${err.message}`);
    }
  } finally {
    for (const row of el.querySelectorAll('.tool-call[data-status="running"]')) { // a stopped search stays "running" otherwise
      renderToolCall(el, { id: row.dataset.id, name: row.dataset.name, status: "stopped" });
    }
    finishReasoning(el);
    render(el);
    if (el.classList.contains("assistant") && !el._text && !el._reasoning && !el.querySelector(".tool-call")) el.remove();
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
  const ready = pending.filter((p) => p.status === "done").length;
  const uploading = pending.some((p) => p.status === "uploading");
  sendBtn.disabled = !state.busy && (uploading || !(input.value.trim() || ready));
}

function submit(text) {
  const files = pending.filter((p) => p.status === "done").map((p) => p.file);
  input.value = "";
  saveDraft();
  scheduleComposer();
  clearPending();
  addMessage("user", text, { attachments: files });
  runTurn("chat", { content: text, attachments: files.map((f) => f.id) });
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  if (state.busy) return state.abort?.abort(); // the button is "Stop" while streaming
  const text = input.value.trim();
  const ready = pending.some((p) => p.status === "done");
  if (pending.some((p) => p.status === "uploading")) return;
  if (text || ready) submit(text);
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
// fit() and syncComposer() both read the field's layout, so they run once per frame rather than once per
// keystroke. saveDraft() stays synchronous: a debounced write would lose the draft if the page is reloaded
// straight after typing.
let composerFrame;
function scheduleComposer() {
  composerFrame ??= requestAnimationFrame(() => {
    composerFrame = null;
    fit();
    syncComposer();
    syncSend();
  });
}
input.addEventListener("input", () => { scheduleComposer(); saveDraft(); });

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
  scheduleComposer();
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && state.busy && !document.querySelector("dialog[open]")) state.abort?.abort();
});

// ---- attachments ----
// Files upload as soon as they are chosen and show as chips in the composer; sending refers to them by id.
// pending: [{ name, size, status: "uploading" | "done" | "error", file (the server's record), error, preview, ctrl, chip }]
const pending = [];
let maxFiles = 5; // replaced by the server's limit

const bytes = (n) => {
  const [unit, size] = n < 1024 ? ["byte", n] : n < 1024 ** 2 ? ["kilobyte", n / 1024] : ["megabyte", n / 1024 ** 2];
  return new Intl.NumberFormat(undefined, { style: "unit", unit, unitDisplay: "narrow", maximumFractionDigits: 1 }).format(size);
};

// A chip's shape is fixed by its name and preview, so it is built once and then patched in place: rebuilding
// them all on every status change would drop keyboard focus and re-create the preview images. They are only
// ever appended and removed, so the DOM order already matches `pending`.
function buildChip(p) {
  const chip = Object.assign(document.createElement("div"), { className: "chip" });
  if (p.preview) {
    chip.classList.add("chip-image");
    chip.append(Object.assign(document.createElement("img"), { src: p.preview, alt: p.name }));
  } else {
    chip.classList.add("chip-file");
    chip.innerHTML = icon(ICONS.file);
    chip._note = Object.assign(document.createElement("span"), { className: "chip-size" });
    chip.append(
      Object.assign(document.createElement("span"), { className: "chip-name", textContent: p.name }),
      chip._note,
    );
  }
  const remove = iconButton(`Remove ${p.name}`, ICONS.close, () => removePending(p));
  remove.className = "chip-remove";
  chip.append(remove);
  return chip;
}

function patchChip(p) {
  const failed = p.status === "error";
  p.chip.setAttribute("aria-busy", String(p.status === "uploading"));
  p.chip.classList.toggle("is-error", failed);
  if (p.chip._note) {
    p.chip._note.className = failed ? "chip-error-text" : "chip-size";
    p.chip._note.textContent = failed ? p.error : bytes(p.size);
  }
}

function renderChips() {
  const chips = $("chips");
  chips.hidden = !pending.length;
  for (const p of pending) {
    if (!p.chip) {
      p.chip = buildChip(p);
      chips.append(p.chip);
    }
    patchChip(p);
  }
  for (const chip of [...chips.children]) {
    if (!pending.some((p) => p.chip === chip)) chip.remove();
  }
  syncSend();
}

function removePending(p) {
  p.ctrl?.abort();
  if (p.preview) URL.revokeObjectURL(p.preview);
  pending.splice(pending.indexOf(p), 1);
  renderChips();
}

function clearPending() {
  for (const p of pending) { p.ctrl?.abort(); if (p.preview) URL.revokeObjectURL(p.preview); }
  pending.length = 0;
  renderChips();
}

async function upload(p, file) {
  const body = new FormData();
  body.append("file", file);
  try {
    const res = await fetch("/api/attachments", { method: "POST", body, signal: p.ctrl.signal });
    if (!res.ok) {
      const { detail } = await res.json().catch(() => ({}));
      throw new Error(typeof detail === "string" ? detail : `Upload failed (${res.status}).`);
    }
    p.file = await res.json();
    p.status = "done";
  } catch (err) {
    if (err.name === "AbortError") return; // removed while uploading
    p.status = "error";
    p.error = err instanceof TypeError ? "Couldn't reach the server." : err.message;
  }
  renderChips();
}

function addFiles(files) {
  for (const file of files) {
    const p = { name: file.name || "pasted file", size: file.size, status: "uploading", ctrl: new AbortController() };
    if (pending.length >= maxFiles) {
      Object.assign(p, { status: "error", error: `You can attach up to ${maxFiles} files.` });
    } else {
      if (file.type.startsWith("image/")) p.preview = URL.createObjectURL(file); // a quick local preview
      upload(p, file);
    }
    pending.push(p);
  }
  renderChips();
}

$("attach").onclick = () => $("file-input").click();
$("file-input").onchange = (e) => { addFiles([...e.target.files]); e.target.value = ""; };
input.addEventListener("paste", (e) => { // pasted screenshots and copied files; plain text pastes as usual
  if (!e.clipboardData.files.length) return;
  e.preventDefault();
  addFiles([...e.clipboardData.files]);
});

// Dropping files anywhere on the page attaches them; the overlay shows while files are dragged over.
let dragDepth = 0;
const hasFiles = (e) => e.dataTransfer?.types.includes("Files");
document.addEventListener("dragenter", (e) => { if (hasFiles(e)) { dragDepth++; $("drop").hidden = false; } });
document.addEventListener("dragleave", (e) => { if (hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; $("drop").hidden = true; } });
document.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
document.addEventListener("drop", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $("drop").hidden = true;
  addFiles([...e.dataTransfer.files]);
});

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

// Search replaces the list while the box has text: results are conversations with the matched message's snippet.
// The server marks matches with STX/ETX characters; the snippet is built as DOM, never as HTML.
const searchBox = $("search");
let searchTimer;
searchBox.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, 200);
});

async function runSearch() {
  const q = searchBox.value.trim();
  if (!q) return renderList();
  const results = await api(`/search?q=${encodeURIComponent(q)}`);
  if (q !== searchBox.value.trim()) return; // typed on meanwhile
  const nav = $("conversations");
  if (!results.length) {
    nav.replaceChildren(Object.assign(document.createElement("p"), { className: "no-convs", textContent: "No chats match." }));
    return;
  }
  const ul = document.createElement("ul");
  ul.append(...results.map((r) => {
    const li = document.createElement("li");
    li.className = "conv";
    const a = document.createElement("a");
    a.className = "result";
    a.href = `#${r.id}`;
    a.onclick = closeNavIfOverlay;
    const snippet = document.createElement("span");
    // split() puts the captured (matched) parts at the odd indexes
    snippet.append(...r.snippet.split(/\x02(.*?)\x03/s).map((t, i) =>
      i % 2 ? Object.assign(document.createElement("mark"), { textContent: t }) : t));
    a.append(Object.assign(document.createElement("strong"), { textContent: r.title }), snippet);
    li.append(a);
    return li;
  }));
  nav.replaceChildren(ul);
}

function renderList() {
  if (searchBox.value.trim()) return; // results are showing; they stay until the box is cleared
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
  // The dot on the settings button means "something besides the model and the tools is customized": those have
  // their own controls in the header and the composer.
  const own = ["model", "tools", "reasoning_effort"];
  const customized = Object.keys(DEFAULT_SETTINGS).some((k) => !own.includes(k) && settings[k] !== DEFAULT_SETTINGS[k]);
  $("settings-btn").toggleAttribute("data-active", customized);
  syncModelButton();
  syncSearchToggle();
  syncEffort();
}

// Save settings for the open conversation; on the new-chat screen they are held until the first message.
// PATCH replaces the whole object, so callers pass the full next settings.
async function saveSettings(next) {
  if (state.id) setSettings((await api(`/conversations/${state.id}`, { method: "PATCH", body: JSON.stringify({ settings: next }) })).settings);
  else setSettings(next);
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

// ---- model picker ----
// The header button shows the model this conversation uses and opens a menu to switch it. null in the
// settings means "the default", so choosing the default row stores null and keeps following it.
const modelBtn = $("model-btn");
const modelMenu = $("model-menu");
let modelInfo = { default: null, models: [] }; // from GET /api/models

const currentModel = () => state.settings.model ?? modelInfo.default;

function syncModelButton() {
  const name = currentModel();
  $("model-name").textContent = name ?? "Model";
  modelBtn.setAttribute("aria-label", name ? `Model: ${name}` : "Model");
  modelBtn.title = name ? `Model: ${name}` : "Model";
}

async function refreshModels() {
  try { modelInfo = await api("/models"); } catch { /* keep what we have; the settings dialog reports real problems */ }
  syncModelButton();
  syncEffort();
}

function modelRow(id, tags) {
  const row = document.createElement("button");
  row.type = "button";
  row.setAttribute("role", "menuitemradio");
  row.setAttribute("aria-checked", String(id === currentModel()));
  row.className = "menu-item";
  row.innerHTML = `<svg class="check" viewBox="0 0 20 20" aria-hidden="true"><path d="${ICONS.check}"/></svg>` +
    '<span class="menu-name"></span>' + tags.map(() => '<span class="menu-tag"></span>').join("");
  row.querySelector(".menu-name").textContent = id;
  row.querySelectorAll(".menu-tag").forEach((el, i) => (el.textContent = tags[i]));
  row.onclick = () => chooseModel(id);
  return row;
}

function renderModelMenu() {
  const saved = state.settings.model;
  const rows = modelInfo.models.map((m) =>
    modelRow(m.id, [m.id === modelInfo.default && "default", m.reasoning && "reasoning"].filter(Boolean)));
  if (saved && !modelInfo.models.some((m) => m.id === saved)) rows.push(modelRow(saved, ["not listed"]));
  $("model-list").replaceChildren(...rows);
}

async function chooseModel(id) {
  const error = modelMenu.querySelector(".field-error");
  error.hidden = true;
  const next = { ...state.settings, model: id === modelInfo.default ? null : id };
  try {
    await saveSettings(next);
    modelMenu.hidePopover(); // the browser returns focus to the button
  } catch {
    error.textContent = "Couldn't switch model. Check your connection and try again.";
    error.hidden = false;
  }
}

modelMenu.addEventListener("beforetoggle", (e) => {
  if (e.newState !== "open") return;
  modelMenu.querySelector(".field-error").hidden = true;
  renderModelMenu();
});
modelMenu.addEventListener("toggle", async (e) => {
  if (e.newState !== "open") return;
  const r = modelBtn.getBoundingClientRect(); // under the button, kept inside the viewport
  modelMenu.style.top = `${r.bottom + 6}px`;
  modelMenu.style.left = `${Math.max(8, Math.min(r.left, innerWidth - modelMenu.offsetWidth - 8))}px`;
  (modelMenu.querySelector('[aria-checked="true"]') ?? modelMenu.querySelector("button"))?.focus();
  await refreshModels(); // the list may have changed since the page loaded
  if (modelMenu.matches(":popover-open")) {
    const focused = document.activeElement?.textContent;
    renderModelMenu();
    [...modelMenu.querySelectorAll("button")].find((b) => b.textContent === focused)?.focus();
  }
});
// A menu's keyboard contract: arrows, Home and End move between items; Tab leaves; Escape is the popover's own.
modelMenu.addEventListener("keydown", (e) => {
  const items = [...modelMenu.querySelectorAll('[role^="menuitem"]')];
  const i = items.indexOf(document.activeElement);
  const target = { ArrowDown: (i + 1) % items.length, ArrowUp: (i - 1 + items.length) % items.length, Home: 0, End: items.length - 1 }[e.key];
  if (target !== undefined) {
    e.preventDefault();
    items[target].focus();
  } else if (e.key === "Tab") modelMenu.hidePopover();
});
$("more-settings").onclick = () => { modelMenu.hidePopover(); openSettings(); };

let reasoningModels = new Map(); // model id -> takes reasoning effort (otherwise temperature)
function syncSettingsFields() {
  const reasoning = reasoningModels.get($("set-model").value); // "" = the default model
  $("effort-field").hidden = reasoning === false;
  $("temp-field").hidden = reasoning === true; // unknown model: show both, the server sends the one that applies
}
$("set-model").addEventListener("change", syncSettingsFields);

// The model and effort choices come from the list the page already has, so the dialog opens at once; the list is
// refreshed in the background and the choices rebuilt, keeping what has been picked meanwhile.
function fillModelChoices(model, effort) {
  const { default: fallback, efforts = [], models } = modelInfo;
  // "" is what the Default option carries, so it needs the default model's own reasoning flag. Both lines
  // below ask for the default by id rather than trusting the order /api/models happens to use.
  reasoningModels = new Map([
    ["", models.find((m) => m.id === fallback)?.reasoning],
    ...models.map((m) => [m.id, m.reasoning]),
  ]);
  const options = models.filter((m) => m.id !== fallback).map((m) => new Option(m.id, m.id));
  if (model && !reasoningModels.has(model)) options.push(new Option(model, model)); // no longer listed
  $("set-model").replaceChildren(new Option(`Default (${fallback ?? "…"})`, ""), ...options);
  $("set-effort").replaceChildren(new Option("Default", ""), ...efforts.map((e) => new Option(e, e)));
  $("set-model").value = model ?? "";
  $("set-effort").value = effort ?? "";
  syncSettingsFields();
}

function openSettings() {
  const s = state.settings;
  const dialog = $("settings-dialog");
  fillModelChoices(s.model, s.reasoning_effort);
  $("set-system").value = s.system_prompt;
  $("set-temp").value = s.temperature ?? "";
  $("export-row").hidden = !state.id;
  if (state.id) { // no hrefs before there is a conversation, so nothing can ask for /conversations/null
    $("export-md").href = `/api/conversations/${state.id}/export?format=md`;
    $("export-json").href = `/api/conversations/${state.id}/export?format=json`;
  }
  dialog.querySelector(".field-error").hidden = true;
  dialog.showModal();
  refreshModels().then(() => {
    if (dialog.open) fillModelChoices($("set-model").value || null, $("set-effort").value || null);
  });
}
$("settings-btn").onclick = openSettings;

bindSave($("settings-dialog"), async () => {
  await saveSettings({
    ...state.settings, // keeps what the dialog doesn't show, such as the tools
    model: $("set-model").value || null,
    system_prompt: $("set-system").value.trim(),
    reasoning_effort: $("set-effort").value || null,
    temperature: $("set-temp").value === "" ? null : Number($("set-temp").value),
  });
});

$("instructions-btn").onclick = async () => {
  const dlg = $("instructions-dialog");
  $("set-instructions").value = (await api("/custom-instructions")).text;
  dlg.querySelector(".field-error").hidden = true;
  dlg.showModal();
};
bindSave($("instructions-dialog"), () =>
  api("/custom-instructions", { method: "PUT", body: JSON.stringify({ text: $("set-instructions").value }) }));

// ---- thinking effort ----
// A select in the composer, shown for models that take a reasoning effort (the others take a temperature, which
// stays in the chat settings). "Auto" stores null: the model's own default.
const effortSelect = $("effort");

function syncEffort() {
  const efforts = modelInfo.efforts ?? [];
  $("effort-wrap").hidden = !modelInfo.models.find((m) => m.id === currentModel())?.reasoning;
  if (effortSelect.options.length !== efforts.length + 1) {
    const group = document.createElement("optgroup");
    group.label = "Thinking effort";
    group.append(new Option("Auto", ""), ...efforts.map((e) => new Option(e[0].toUpperCase() + e.slice(1), e)));
    effortSelect.replaceChildren(group);
  }
  effortSelect.value = state.settings.reasoning_effort ?? "";
  effortSelect.title = `Thinking effort: ${effortSelect.selectedOptions[0].text}`;
  $("effort-wrap").title = effortSelect.title;
  $("effort-wrap").toggleAttribute("data-active", effortSelect.value !== "");
}

effortSelect.onchange = async () => {
  try {
    await saveSettings({ ...state.settings, reasoning_effort: effortSelect.value || null });
  } catch {
    syncEffort();
    showNote("Couldn't change the thinking effort. Check your connection and try again.");
  }
};

// ---- web search toggle ----
// Always shown; it is disabled while the server has no search tool configured (a Brave key). On or off is a
// per-conversation setting.
const SEARCH = "web_search";
const searchOn = () => state.settings.tools.includes(SEARCH);

function syncSearchToggle() {
  const toggle = $("search-toggle");
  const tool = state.tools.find((t) => t.name === SEARCH);
  // The tool names itself; the page's own wording stands in until the list arrives (or if it never does).
  const label = tool?.label ?? toggle.getAttribute("aria-label");
  toggle.disabled = !tool;
  toggle.setAttribute("aria-pressed", String(!!tool && searchOn()));
  toggle.setAttribute("aria-label", label);
  toggle.title = !tool ? `${label} is unavailable: set BRAVE_API_KEY on the server`
    : `${label}: ${searchOn() ? "on" : "off"}`;
}

let noteTimer;
function showNote(text) {
  const note = $("composer-note");
  note.textContent = text;
  note.hidden = false;
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => { note.hidden = true; }, 5000);
}

$("search-toggle").onclick = async () => {
  const tools = searchOn() ? state.settings.tools.filter((t) => t !== SEARCH) : [...state.settings.tools, SEARCH];
  try {
    await saveSettings({ ...state.settings, tools });
  } catch {
    showNote("Couldn't change web search. Check your connection and try again.");
  }
};

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
  clearPending();
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
refreshModels();
api("/attachments/limits").then((limits) => { maxFiles = limits.max_files; }).catch(() => {});
api("/tools").then((tools) => { state.tools = tools; syncSearchToggle(); }).catch(() => {});
openConversation(location.hash.slice(1) || null);
