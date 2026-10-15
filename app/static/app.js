// The entry point: loads the modules (each wires up its own part of the page when it loads), opens a conversation
// and starts the page. See docs/architecture.md for what is where.
import { $, DEFAULT_SETTINGS, api, bus, main, state, thread } from './core.js'
import { addMessage, jumpTo, render, scrollToBottom } from './messages.js'
import {
  clearPending,
  focusComposer,
  loadAttachmentLimits,
  loadDraft,
  syncSend,
} from './composer.js'
import { updateActions } from './chat.js'
import { refreshList, setTitle } from './list.js'
import { closeNavIfOverlay } from './nav.js'
import {
  loadDefaults,
  newChatSettings,
  refreshModels,
  setSettings,
} from './settings.js'
import { loadTools } from './controls.js'
import './backup.js'
import './chat-menu.js'
import './delete.js'
import './model-menu.js'
import './retry-menu.js'
import './find.js'
import './sources.js'
import './preferences.js'
import './shortcuts.js'

async function openConversation(id) {
  const target = state.jumpTo // a search result asked to open at this message
  state.jumpTo = null
  state.abort?.abort() // a reply still streaming is saved as stopped
  state.id = id
  state.stick = true
  $('jump').hidden = true // the new thread starts at its end: no scroll event comes to hide it
  thread.replaceChildren()
  bus.dispatchEvent(new Event('thread-reset')) // sources and find start over
  clearPending()
  main.classList.remove('is-started')
  closeNavIfOverlay()
  if (location.hash.slice(1) !== (id ?? ''))
    history.replaceState(null, '', id ? `#${id}` : location.pathname)
  setSettings(id ? { ...DEFAULT_SETTINGS } : newChatSettings())
  setTitle(null)
  if (id) {
    try {
      let conv = await api(`/conversations/${id}`)
      if (target && !conv.messages.some((m) => m.id === target)) {
        // a search result in a version that is not shown
        const body = JSON.stringify({ message_id: target })
        conv = await api(`/conversations/${id}/branch`, {
          method: 'POST',
          body,
        }).catch(() => conv)
      }
      setSettings(conv.settings)
      setTitle(conv.title)
      conv.messages.forEach((m) => {
        const el = addMessage(m.role, m.content, m.meta)
        el.dataset.id = m.id
        el._siblings = m.siblings
      })
      state.stick = false // render() scrolls to the end when this is on, and reading the scroll height forces the
      thread.querySelectorAll('.msg').forEach(render) // page to lay out again: once per message is quadratic
      state.stick = true
    } catch {
      return openConversation(null) // stale link
    }
  }
  updateActions()
  if (!jumpTo(target)) scrollToBottom()
  loadDraft()
  await refreshList()
  focusComposer()
}

bus.addEventListener('open', (e) =>
  openConversation(/** @type {CustomEvent} */ (e).detail),
)
$('new-chat').onclick = () => openConversation(null)
// The menus are placed once, when they open (next to their button, kept inside the window): a resized window or a
// turned phone would leave an open one where it no longer fits, so it closes and opens again in the right place.
window.addEventListener('resize', () => {
  for (const menu of document.querySelectorAll('[popover]:popover-open'))
    /** @type {HTMLElement} */ (menu).hidePopover()
})
window.addEventListener('hashchange', () => {
  const id = location.hash.slice(1) || null
  if (id !== state.id) openConversation(id)
})

syncSend()
refreshModels()
loadAttachmentLimits()
loadTools()
await loadDefaults() // a new chat starts with the tools chosen there
// The first conversation is open and the message box has the focus (that comes last): the UI tests wait for this
// before they type or click, or the focus would move from under them.
openConversation(location.hash.slice(1) || null).then(() => {
  document.body.dataset.ready = ''
})
