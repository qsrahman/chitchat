// The sidebar: the conversation list, search, rename and delete, and the drawer that shows or hides it.
import { $, ICONS, api, bus, iconButton, showDialog, state, thread } from "./core.js";
import { jumpTo } from "./messages.js";

// ---- sidebar ----
const DAY = 864e5;
function groupOf(iso) {
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const days = Math.round((startOfDay(new Date()) - startOfDay(new Date(iso))) / DAY);
  return days <= 0 ? "Today" : days === 1 ? "Yesterday" : days <= 7 ? "Previous 7 days" : "Older";
}

// The list loads a page at a time ("Show more" asks for the next). A refresh reloads as many as are showing.
const PAGE = 50;
let more = false; // the last request came back full, so there may be older chats

export async function refreshList() {
  const limit = Math.min(500, Math.max(PAGE, state.convs.length));
  state.convs = await api(`/conversations?limit=${limit}`);
  more = state.convs.length === limit;
  renderList();
  const current = state.convs.find((c) => c.id === state.id);
  if (current) setTitle(current.title);
}

async function showMore() {
  const next = await api(`/conversations?limit=${PAGE}&offset=${state.convs.length}`);
  state.convs.push(...next);
  more = next.length === PAGE;
  renderList();
}

// The open chat may be further down than the list has loaded, so the page sets its title when it opens it.
export function setTitle(title) {
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

// A string with matches between STX and ETX, as text with <mark> around them (never as HTML).
const withMarks = (text) => text.split(/\x02(.*?)\x03/s).map((t, i) => // the captured (matched) parts are the odd ones
  i % 2 ? Object.assign(document.createElement("mark"), { textContent: t }) : t);

async function runSearch() {
  const q = searchBox.value.trim();
  if (!q) return renderList();
  const results = (await api(`/search?q=${encodeURIComponent(q)}`)).filter((r) => r.id !== pending?.conv.id);
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
    a.dir = "auto";
    a.href = `#${r.id}`;
    a.onclick = (e) => {
      closeNavIfOverlay();
      if (r.id !== state.id) {
        state.jumpTo = r.message_id; // the hash change opens the chat there (null: a title match, opened as usual)
        return;
      }
      e.preventDefault(); // already open: the hash won't change
      // A message streamed in this session has no id on the page yet; opening the chat again gives them all one.
      if (r.message_id && !jumpTo(r.message_id)) {
        state.jumpTo = r.message_id;
        bus.dispatchEvent(new CustomEvent("open", { detail: r.id }));
      }
    };
    const title = document.createElement("strong");
    title.append(...withMarks(r.title_marked));
    a.append(title);
    if (r.snippet) {
      const snippet = document.createElement("span");
      snippet.append(...withMarks(r.snippet));
      a.append(snippet);
    }
    li.append(a);
    return li;
  }));
  nav.replaceChildren(ul);
}

function renderList() {
  if (searchBox.value.trim()) return; // results are showing; they stay until the box is cleared
  const nav = $("conversations");
  const shown = state.convs.filter((c) => c.id !== pending?.conv.id); // a chat waiting to be deleted is hidden
  if (!shown.length) {
    nav.replaceChildren(Object.assign(document.createElement("p"), { className: "no-convs", textContent: "Your conversations will show up here." }));
    return;
  }
  const groups = Map.groupBy(shown, (c) => groupOf(c.updated_at)); // list is already newest-first
  nav.replaceChildren(...[...groups].flatMap(([name, convs]) => {
    const h = Object.assign(document.createElement("h2"), { textContent: name });
    const ul = document.createElement("ul");
    ul.append(...convs.map(renderConv));
    return [h, ul];
  }));
  if (more) {
    const button = Object.assign(document.createElement("button"), { type: "button", className: "btn show-more", textContent: "Show more" });
    button.onclick = showMore;
    nav.append(button);
  }
}


function renderConv(c) {
  const li = document.createElement("li");
  li.className = "conv";
  const link = document.createElement("a");
  link.href = `#${c.id}`;
  link.textContent = c.title;
  link.dir = "auto";
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

async function renameConv(c) {
  $("rename-input").value = c.title;
  if ((await showDialog($("rename-dialog"))) !== "save") return;
  const title = $("rename-input").value.trim();
  if (!title) return;
  await api(`/conversations/${c.id}`, { method: "PATCH", body: JSON.stringify({ title }) });
  refreshList();
}

// A deleted chat is hidden at once but only deleted on the server after UNDO_MS, so "Undo" is just un-hiding it.
// Deleting another chat, or leaving the page, makes a waiting delete final straight away.
const UNDO_MS = 10_000;
let pending = null; // { conv, wasOpen, timer }

async function deleteConv(c) {
  $("delete-name").textContent = c.title;
  if ((await showDialog($("delete-dialog"))) !== "delete") return;
  await commitDelete();
  pending = { conv: c, wasOpen: c.id === state.id, timer: setTimeout(commitDelete, UNDO_MS) };
  $("toast").firstElementChild.textContent = `Deleted "${c.title}"`;
  $("toast").hidden = false;
  if (pending.wasOpen) bus.dispatchEvent(new CustomEvent("open", { detail: null })); // app.js opens a new chat
  else renderList();
}

async function commitDelete() {
  if (!pending) return;
  const { conv, timer } = pending;
  clearTimeout(timer);
  pending = null;
  $("toast").hidden = true;
  try {
    await api(`/conversations/${conv.id}`, { method: "DELETE" });
  } finally {
    await refreshList();
  }
}

$("toast").querySelector("button").onclick = () => {
  const { conv, wasOpen, timer } = pending;
  clearTimeout(timer);
  pending = null;
  $("toast").hidden = true;
  // Back on the blank chat the delete left behind: show the chat again. Anywhere else, only the list changes.
  if (wasOpen && state.id === null && !thread.children.length) bus.dispatchEvent(new CustomEvent("open", { detail: conv.id }));
  else renderList();
};

// keepalive lets the request finish while the page closes
window.addEventListener("pagehide", () => {
  if (pending) fetch(`/api/conversations/${pending.conv.id}`, { method: "DELETE", keepalive: true });
});

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
export function closeNavIfOverlay() {
  if (matchMedia("(max-width: 760px)").matches) setNavOpen(false);
}
document.querySelectorAll(".nav-toggle").forEach((b) => {
  b.onclick = () => setNavOpen(!document.body.classList.contains("nav-open"));
});
$("scrim").onclick = () => setNavOpen(false);

// ---- keyboard shortcuts ----
// Mod+K searches chats, Mod+Shift+O starts a new chat (as on chatgpt.com). Mod is Cmd on a Mac, Ctrl elsewhere.
const mod = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl+";
$("search").title = `Search chats (${mod}K)`;
$("new-chat").title = `New chat (${mod}Shift+O)`;
$("search").setAttribute("aria-keyshortcuts", "Control+K Meta+K");
$("new-chat").setAttribute("aria-keyshortcuts", "Control+Shift+O Meta+Shift+O");

document.addEventListener("keydown", (e) => {
  if (!(e.metaKey || e.ctrlKey) || e.altKey || document.querySelector("dialog[open]")) return;
  const key = e.key.toLowerCase();
  if (key === "k" && !e.shiftKey) {
    e.preventDefault();
    setNavOpen(true);
    searchBox.focus();
    searchBox.select();
  } else if (key === "o" && e.shiftKey) {
    e.preventDefault();
    $("new-chat").click();
  }
});

// ---- backup ----
// Export is two links (the server builds the files). Import sends a chosen JSON file and says what came of it.
const chats = (n) => `${n} chat${n === 1 ? "" : "s"}`;

function setBackupStatus(text, failed = false) {
  const status = $("backup-status");
  status.textContent = text;
  status.hidden = !text;
  status.classList.toggle("is-error", failed);
}

$("backup-btn").onclick = () => {
  setBackupStatus("");
  $("backup-dialog").showModal();
};

$("import-file").onchange = async (e) => {
  const [file] = e.target.files;
  e.target.value = ""; // so choosing the same file again still counts
  if (!file) return;
  setBackupStatus(`Importing ${file.name}…`);
  const body = new FormData();
  body.append("file", file);
  try {
    const res = await fetch("/api/import", { method: "POST", body });
    const result = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof result.detail === "string" ? result.detail : `The import failed (${res.status}).`);
    setBackupStatus(result.imported
      ? `Imported ${chats(result.imported)}${result.skipped ? `; ${result.skipped} already here` : ""}.`
      : `Nothing new: ${chats(result.skipped)} already here.`);
    await refreshList();
  } catch (err) {
    setBackupStatus(err instanceof TypeError ? "Couldn't reach the server." : err.message, true);
  }
};
