// Keyboard shortcuts for the sidebar: search chats, new chat.
import { $ } from './core.js'
import { setNavOpen } from './nav.js'

const search = $('search')

// Mod+K searches chats, Mod+Shift+O starts a new chat (as on chatgpt.com). Mod is Cmd on a Mac, Ctrl elsewhere.
const mod = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl+'
$('search').title = `Search chats (${mod}K)`
$('new-chat').title = `New chat (${mod}Shift+O)`
$('search').setAttribute('aria-keyshortcuts', 'Control+K Meta+K')
$('new-chat').setAttribute('aria-keyshortcuts', 'Control+Shift+O Meta+Shift+O')

document.addEventListener('keydown', (e) => {
  if (
    !(e.metaKey || e.ctrlKey) ||
    e.altKey ||
    document.querySelector('dialog[open]')
  )
    return
  const key = e.key.toLowerCase()
  if (key === 'k' && !e.shiftKey) {
    e.preventDefault()
    setNavOpen(true)
    search.focus()
    search.select()
  } else if (key === 'o' && e.shiftKey) {
    e.preventDefault()
    ;/** @type {HTMLElement | null} */ (document.activeElement)?.blur() // so the new chat gets the cursor even if it was in the search box
    $('new-chat').click()
  }
})
