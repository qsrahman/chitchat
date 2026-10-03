// The box you type in: the send button, auto-grow, drafts, and attachments (chips, uploads, paste, drag and drop).
import { $, ICONS, api, composer, form, icon, iconButton, input, sendBtn, state } from "./core.js";

// ---- the input box and the send button ----
export function syncSend() {
  sendBtn.classList.toggle("is-stop", state.busy);
  sendBtn.setAttribute("aria-label", state.busy ? "Stop generating" : "Send message");
  const ready = pending.filter((p) => p.status === "done").length;
  const uploading = pending.some((p) => p.status === "uploading");
  sendBtn.disabled = !state.busy && (uploading || !(input.value.trim() || ready));
}

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
export function scheduleComposer() {
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
export function saveDraft() {
  try {
    if (input.value) localStorage.setItem(draftKey(), input.value);
    else localStorage.removeItem(draftKey());
  } catch { /* storage blocked: drafts just aren't kept */ }
}
export function loadDraft() {
  try { input.value = localStorage.getItem(draftKey()) ?? ""; } catch { input.value = ""; }
  scheduleComposer();
}

// ---- attachments ----
// Files upload as soon as they are chosen and show as chips in the composer; sending refers to them by id.
// pending: [{ name, size, status: "uploading" | "done" | "error", file (the server's record), error, preview, ctrl, chip }]
export const pending = [];
let maxFiles = 5; // replaced by the server's limit, see loadAttachmentLimits

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

export function clearPending() {
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

let noteTimer;
export function showNote(text) {
  const note = $("composer-note");
  note.textContent = text;
  note.hidden = false;
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => { note.hidden = true; }, 5000);
}

export function loadAttachmentLimits() {
  return api("/attachments/limits").then((limits) => { maxFiles = limits.max_files; }).catch(() => {});
}
