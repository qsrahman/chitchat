// The sidebar's list of conversations: paging, search, rename, pin and archive. Delete is in delete.js, the drawer in
// nav.js, the shortcuts in shortcuts.js, and backup and import in backup.js.
import { $, ICONS, api, bus, iconButton, showDialog, state } from "./core.js";
import { jumpTo } from "./messages.js";
import { closeNavIfOverlay } from "./nav.js";

const DAY = 864e5;
function groupOf(iso) {
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const days = Math.round((startOfDay(new Date()).getTime() - startOfDay(new Date(iso)).getTime()) / DAY);
  return days <= 0 ? "Today" : days === 1 ? "Yesterday" : days <= 7 ? "Previous 7 days" : "Older";
}

// The list loads a page at a time ("Show more" asks for the next). A refresh reloads as many as are showing.
const PAGE = 50;
let more = false; // the last request came back full, so there may be older chats
let showArchived = false; // the list is the archived chats (the "Archived chats" button in the footer)

// The header's Download button: a link to this chat as Markdown, there once the chat exists.
function syncExport() {
  const link = $("export-btn");
  link.hidden = !state.id;
  if (state.id) link.href = `/api/conversations/${state.id}/export?format=md`;
}

export async function refreshList() {
  syncExport();
  const limit = Math.min(500, Math.max(PAGE, state.convs.length));
  state.convs = await api(`/conversations?limit=${limit}&archived=${showArchived}`);
  more = state.convs.length === limit;
  renderList();
  const current = state.convs.find((c) => c.id === state.id);
  if (current) setTitle(current.title);
}

async function showMore() {
  const next = await api(`/conversations?limit=${PAGE}&offset=${state.convs.length}&archived=${showArchived}`);
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
  const results = (await api(`/search?q=${encodeURIComponent(q)}`)).filter((r) => r.id !== hiddenId);
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

// A chat that is being deleted (delete.js: gone for good in ten seconds unless undone) is hidden from the list.
let hiddenId = null;
export function hideChat(id, render = true) {
  hiddenId = id;
  if (render) renderList();
}

export function renderList() {
  if (searchBox.value.trim()) return; // results are showing; they stay until the box is cleared
  const nav = $("conversations");
  const shown = state.convs.filter((c) => c.id !== hiddenId); // a chat waiting to be deleted is hidden
  if (!shown.length) {
    const empty = showArchived ? "Archived chats will show up here." : "Your conversations will show up here.";
    nav.replaceChildren(Object.assign(document.createElement("p"), { className: "no-convs", textContent: empty }));
    return;
  }
  // Pinned chats first, in a group of their own; the rest by date. The list is already pinned first, newest first.
  const groups = Map.groupBy(shown, (c) => (c.pinned ? "Pinned" : groupOf(c.updated_at)));
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
  const pin = iconButton(`${c.pinned ? "Unpin" : "Pin"} "${c.title}"`, ICONS.pin, () => setFlags(c, { pinned: !c.pinned }));
  pin.classList.toggle("is-on", !!c.pinned); // a pinned chat shows it without the mouse over it
  li.append(
    link,
    ...(showArchived ? [] : [pin]),
    iconButton(`Rename "${c.title}"`, ICONS.pencil, () => renameConv(c)),
    iconButton(`${showArchived ? "Unarchive" : "Archive"} "${c.title}"`, ICONS.archive,
      () => setFlags(c, { archived: !showArchived })),
    iconButton(`Delete "${c.title}"`, ICONS.trash, () => bus.dispatchEvent(new CustomEvent("delete-chat", { detail: c }))),
  );
  return li;
}

async function setFlags(c, flags) {
  await api(`/conversations/${c.id}`, { method: "PATCH", body: JSON.stringify(flags) });
  await refreshList();
}

// The footer button switches the list between the chats and the archive (an archived chat can still be opened).
$("archived-btn").onclick = async () => {
  showArchived = !showArchived;
  $("archived-btn").setAttribute("aria-pressed", String(showArchived));
  state.convs = []; // start from the first page of the other list
  await refreshList();
};

async function renameConv(c) {
  $("rename-input").value = c.title;
  if ((await showDialog($("rename-dialog"))) !== "save") return;
  const title = $("rename-input").value.trim();
  if (!title) return;
  await api(`/conversations/${c.id}`, { method: "PATCH", body: JSON.stringify({ title }) });
  refreshList();
}
