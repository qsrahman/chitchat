// Settings, Data controls, Storage: what is kept, the files nothing uses, and old archived chats. Both deletes are
// buttons, never automatic; the server side is storage.py (docs/storage.md).
import { $, api, bus, bytes, showDialog, state } from './core.js'
import { refreshList } from './list.js'

const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`
const age = $('archived-age')
const days = () => Number(age.value)

function say(text, failed = false) {
  const status = $('storage-status')
  status.textContent = text
  status.hidden = !text
  status.classList.toggle('is-error', failed)
}

async function showArchived() {
  const note = $('archived-note')
  try {
    const { count } = await api(`/storage/archived?days=${days()}`)
    note.textContent = count
      ? `${plural(count, 'archived chat')} not used for ${days()} days or more.`
      : 'No archived chats are that old.'
    $('delete-archived').disabled = !count
    $('delete-archived').dataset.count = String(count)
  } catch {
    note.textContent = ''
    $('delete-archived').disabled = true
  }
}

// The numbers and what the buttons would do. After an action this runs without clearing what the action said.
async function refreshNumbers() {
  try {
    /** @type {StorageOverview} */
    const s = await api('/storage')
    $('storage-summary').textContent =
      `Database ${bytes(s.database_bytes)}. Attachments ${bytes(s.attachment_bytes)} in ${plural(s.attachment_files, 'file')}. ` +
      `${plural(s.chats, 'chat')}, ${s.archived_chats} archived.`
    $('unused-note').textContent = s.unused_files
      ? `${plural(s.unused_files, 'file')}, ${bytes(s.unused_bytes)}: uploads that were never sent, and leftovers nothing points to.`
      : 'None: every file belongs to a chat.'
    $('clear-unused').disabled = !s.unused_files
  } catch {
    $('storage-summary').textContent = ''
    say("Couldn't read the storage. Check your connection.", true)
  }
  await showArchived()
}

// Called when the Data controls tab is shown.
export function loadStorage() {
  say('')
  return refreshNumbers()
}

$('clear-unused').onclick = async () => {
  say('')
  try {
    const { files, bytes: freed } = await api('/storage/clear-unused', {
      method: 'POST',
    })
    say(
      files
        ? `Deleted ${plural(files, 'unused file')}, ${bytes(freed)}.`
        : 'Nothing to delete.',
    )
  } catch {
    say("Couldn't delete them. Check your connection and try again.", true)
  }
  refreshNumbers()
}

age.onchange = showArchived

$('delete-archived').onclick = async () => {
  const count = Number($('delete-archived').dataset.count)
  $('purge-text').textContent =
    `${plural(count, 'archived chat')} not used for ${days()} days or more will be deleted for good, with their messages and attached files. ` +
    'This can’t be undone: export first if you might want them back.'
  if ((await showDialog($('purge-dialog'))) !== 'delete') return
  say('')
  try {
    const { deleted, ids } = await api(`/storage/archived?days=${days()}`, {
      method: 'DELETE',
    })
    say(deleted ? `Deleted ${plural(deleted, 'chat')}.` : 'Nothing to delete.')
    if (ids.includes(state.id))
      bus.dispatchEvent(new CustomEvent('open', { detail: null })) // the chat on screen is gone: app.js opens a new one
    await refreshList()
  } catch {
    say("Couldn't delete them. Check your connection and try again.", true)
  }
  refreshNumbers()
}
