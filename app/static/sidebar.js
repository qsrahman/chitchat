// The sidebar: the conversation list, search, rename and delete, and the drawer that shows or hides it.
import { $, ICONS, api, bus, iconButton, showDialog, state } from "./core.js";

// ---- sidebar ----
const DAY = 864e5;
function groupOf(iso) {
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const days = Math.round((startOfDay(new Date()) - startOfDay(new Date(iso))) / DAY);
  return days <= 0 ? "Today" : days === 1 ? "Yesterday" : days <= 7 ? "Previous 7 days" : "Older";
}

export async function refreshList() {
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
    a.dir = "auto";
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

async function deleteConv(c) {
  $("delete-name").textContent = c.title;
  if ((await showDialog($("delete-dialog"))) !== "delete") return;
  await api(`/conversations/${c.id}`, { method: "DELETE" });
  if (c.id === state.id) bus.dispatchEvent(new CustomEvent("open", { detail: null })); // app.js opens a new chat
  else refreshList();
}

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
