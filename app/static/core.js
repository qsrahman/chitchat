// Shared basics for the UI modules: DOM handles, the one shared state object, the API helper, icons, a few small
// builders, and a bus for "something changed" notices. Nothing here depends on another module of the app.

export const $ = (id) => document.getElementById(id);
export const main = document.querySelector("main");
export const messagesEl = $("messages");
export const thread = $("thread");
export const input = $("input");
export const sendBtn = $("send");
export const form = $("form");
export const composer = document.querySelector(".composer");

// Notices between modules that shouldn't import each other: "settings" (the open conversation's settings changed),
// "models" (the model list was refreshed) and "open" (open the conversation in event.detail, null for a new chat).
export const bus = new EventTarget();

// id: current conversation (null = new chat, created lazily on first send).
// stick: keep the view pinned to the bottom unless the reader scrolled up.
// jumpTo: id of a message to scroll to when the next conversation opens (set by a search result).
// settings: the current conversation's settings (kept client-side until a new chat's first send creates it).
export const DEFAULT_SETTINGS = { model: null, system_prompt: "", reasoning_effort: null, temperature: null, tools: [] };
export const state = { id: null, jumpTo: null, busy: false, abort: null, stick: true, convs: [], settings: { ...DEFAULT_SETTINGS }, tools: [] };

// 20x20 stroke icons (see iconButton).
export const ICONS = {
  copy: "M7 7h9v9H7zM13 7V4H4v9h3",
  check: "M4 10l4 4 8-8",
  refresh: "M16 10a6 6 0 1 1-1.8-4.3M16 4v3.5h-3.5",
  pencil: "M4 16l1-4 8-8 3 3-8 8-4 1zM11 6l3 3",
  trash: "M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10",
  file: "M6 3h6l4 4v10H6zM12 3v4h4",
  close: "M5 5l10 10M15 5L5 15",
  previous: "M12 5l-5 5 5 5",
  next: "M8 5l5 5-5 5",
};
export const icon = (path) => `<svg viewBox="0 0 20 20" aria-hidden="true"><path d="${path}"/></svg>`;

export async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.status === 204 ? null : res.json();
}

export const bodyOf = (el) => el.querySelector(".body");
export const noteOf = (el) => el.querySelector(".note");
export const actionsOf = (el) => el.querySelector(".actions");

export const textEl = (tag, text, className = "") => Object.assign(document.createElement(tag), { textContent: text, className, dir: "auto" });

export function iconButton(label, path, onclick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "icon-btn";
  b.setAttribute("aria-label", label);
  b.title = label;
  b.innerHTML = `<svg viewBox="0 0 20 20" aria-hidden="true"><path d="${path}"/></svg>`;
  b.onclick = onclick;
  return b;
}

// ---- dialogs ----
export function showDialog(dlg) {
  dlg.returnValue = "";
  return new Promise((resolve) => {
    dlg.addEventListener("close", () => resolve(dlg.returnValue), { once: true });
    dlg.showModal();
  });
}
document.querySelectorAll("dialog [data-cancel]").forEach((b) => (b.onclick = () => b.closest("dialog").close("cancel")));
