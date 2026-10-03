// The entry point: loads the modules (each wires up its own part of the page when it loads), opens a conversation
// and starts the page. See docs/architecture.md for what is where.
import { $, DEFAULT_SETTINGS, api, bus, input, main, state, thread } from "./core.js";
import { addMessage, jumpTo, render, scrollToBottom } from "./messages.js";
import { clearPending, loadAttachmentLimits, loadDraft, syncSend } from "./composer.js";
import { updateActions } from "./chat.js";
import { closeNavIfOverlay, refreshList } from "./sidebar.js";
import { refreshModels, setSettings } from "./settings.js";
import { loadTools } from "./controls.js";
import "./model-menu.js";

async function openConversation(id) {
  const target = state.jumpTo; // a search result asked to open at this message
  state.jumpTo = null;
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
      conv.messages.forEach((m) => { addMessage(m.role, m.content, m.meta).dataset.id = m.id; });
      thread.querySelectorAll(".msg").forEach(render);
    } catch {
      return openConversation(null); // stale link
    }
  }
  updateActions();
  if (!jumpTo(target)) scrollToBottom();
  loadDraft();
  await refreshList();
  input.focus();
}

bus.addEventListener("open", (e) => openConversation(e.detail));
$("new-chat").onclick = () => openConversation(null);
window.addEventListener("hashchange", () => {
  const id = location.hash.slice(1) || null;
  if (id !== state.id) openConversation(id);
});

syncSend();
refreshModels();
loadAttachmentLimits();
loadTools();
openConversation(location.hash.slice(1) || null);
