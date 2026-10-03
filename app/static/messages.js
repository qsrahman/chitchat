// The thread: building a message (text, reasoning, tool calls, attachments, note), rendering it, and scrolling.
import { renderMarkdown, renderReasoning } from "./markdown.js";
import { $, ICONS, bodyOf, icon, main, messagesEl, noteOf, state, thread } from "./core.js";
import { renderToolCall } from "./tools-ui.js";

// ---- scrolling ----
const nearBottom = () => messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
export function scrollToBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }
messagesEl.addEventListener("scroll", () => {
  state.stick = nearBottom();
  $("jump").hidden = state.stick;
});
$("jump").onclick = () => { state.stick = true; scrollToBottom(); };

// ---- messages ----
// Each .msg = [details.reasoning] + .body (rendered text) + .note (stopped / cut off / compacted) + .actions.
// el._text and el._reasoning are the raw texts.
export function addMessage(role, text = "", meta = {}) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  for (const cls of ["body", "note", "actions"]) el.append(Object.assign(document.createElement("div"), { className: cls }));
  if (role !== "assistant") bodyOf(el).dir = "auto"; // plain text; a reply's blocks get theirs when rendered (markdown.js)
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


export function setNote(el, meta) {
  const note = noteOf(el);
  note.textContent = [
    meta.stopped && "Stopped.",
    meta.incomplete && "Reply cut off: output limit reached.",
    meta.compaction && "Earlier messages were compacted to save context.",
    meta.trimmed && `${meta.trimmed} earlier message${meta.trimmed === 1 ? " was" : "s were"} left out to fit the model's context.`,
  ].filter(Boolean).join(" ");
  note.hidden = !note.textContent;
}

// Re-rendering markdown on every delta is wasteful; coalesce to one render per frame.
function schedule(el) {
  el._frame ??= requestAnimationFrame(() => render(el));
}
export function setText(el, text) {
  el._text = text;
  schedule(el);
}
export function setReasoning(el, text) {
  el._reasoning = text;
  schedule(el);
}

// The reasoning summary sits above the answer in a <details>: open and "Thinking…" while it streams,
// collapsed and "Reasoning" once the answer starts or for a saved message.
export function reasoningOf(el) {
  let details = el.querySelector(".reasoning");
  if (!details) {
    details = document.createElement("details");
    details.className = "reasoning";
    details.innerHTML = '<summary>Reasoning</summary><div class="reasoning-body"></div>';
    el.prepend(details);
  }
  return details;
}

export function finishReasoning(el) {
  const details = el.querySelector(".reasoning");
  if (!details) return;
  details.open = false;
  details.querySelector("summary").textContent = "Reasoning";
}

export function render(el) {
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

// Copy button inside rendered code blocks (event delegation: the HTML is re-rendered while streaming).
thread.addEventListener("click", async (e) => {
  const btn = e.target.closest(".code-copy");
  if (!btn) return;
  await navigator.clipboard.writeText(btn.closest(".code").querySelector("code").innerText);
  btn.textContent = "Copied";
  setTimeout(() => (btn.textContent = "Copy"), 1200);
});
