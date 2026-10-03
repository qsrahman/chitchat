// Deleting a chat, with ten seconds to change your mind. The chat is hidden at once and deleted on the server when
// the time is up (list.js hides it; this file owns the timer, the toast and the Undo button).
import { $, api, bus, showDialog, state, thread } from './core.js'
import { hideChat, refreshList, renderList } from './list.js'

// A deleted chat is hidden at once but only deleted on the server after UNDO_MS, so "Undo" is just un-hiding it.
// Deleting another chat, or leaving the page, makes a waiting delete final straight away.
const UNDO_MS = 10_000
/** @type {{conv: Conversation, wasOpen: boolean, timer: ReturnType<typeof setTimeout>} | null} */
let pending = null

async function deleteChat(c) {
  $('delete-name').textContent = c.title
  if ((await showDialog($('delete-dialog'))) !== 'delete') return
  await commitDelete()
  pending = {
    conv: c,
    wasOpen: c.id === state.id,
    timer: setTimeout(commitDelete, UNDO_MS),
  }
  $('toast').firstElementChild.textContent = `Deleted "${c.title}"`
  $('toast').hidden = false
  hideChat(c.id, !pending.wasOpen)
  if (pending.wasOpen)
    bus.dispatchEvent(new CustomEvent('open', { detail: null })) // app.js opens a new chat
}

export async function commitDelete() {
  if (!pending) return
  const { conv, timer } = pending
  clearTimeout(timer)
  pending = null
  $('toast').hidden = true
  hideChat(null, false)
  try {
    await api(`/conversations/${conv.id}`, { method: 'DELETE' })
  } catch {
    /* already gone (another tab, or the page was closing): that is what was wanted */
  }
  await refreshList()
}

$('toast').querySelector('button').onclick = () => {
  if (!pending) return
  const { conv, wasOpen, timer } = pending
  clearTimeout(timer)
  pending = null
  $('toast').hidden = true
  // Back on the blank chat the delete left behind: show the chat again. Anywhere else, only the list changes.
  hideChat(null, false)
  if (wasOpen && state.id === null && !thread.children.length)
    bus.dispatchEvent(new CustomEvent('open', { detail: conv.id }))
  else renderList()
}

// keepalive lets the request finish while the page closes
window.addEventListener('pagehide', () => {
  if (!pending) return
  fetch(`/api/conversations/${pending.conv.id}`, {
    method: 'DELETE',
    keepalive: true,
  })
  clearTimeout(pending.timer)
  pending = null // sent: nothing is waiting any more (the page may come back from the back-forward cache)
  hideChat(null, false)
  $('toast').hidden = true
})
bus.addEventListener('delete-chat', (e) =>
  deleteChat(/** @type {CustomEvent} */ (e).detail),
) // from the row's Delete button (list.js)
