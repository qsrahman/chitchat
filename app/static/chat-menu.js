// The menu of everything you can do with a chat besides reading it: its own instructions, rename, pin, download,
// archive and delete. One menu for two buttons, the ⋯ in the header (the open chat) and the ⋯ on a sidebar row (that
// chat). It is a popover placed from here: CSS anchor positioning is not widely available.
import { $, ICONS, api, bus, icon, state } from './core.js'
import { openFind } from './find.js'
import { renameConv, setFlags } from './list.js'
import { menuKeys } from './model-menu.js'
import { openSettings } from './settings.js'

const menu = $('chat-menu')
/** @type {HTMLElement | null} */
let anchor = null

/** @typedef {{label: string, icon: string, run?: () => void, href?: string, danger?: boolean}} Item */

/**
 * The groups of items for a chat (null on the new-chat screen, which has no chat yet to rename or download).
 * @param {Conversation | null} c
 * @param {boolean} open is this the chat on screen (only that one has settings to open)
 * @returns {Item[][]}
 */
function groups(c, open) {
  const download = (format) =>
    `/api/conversations/${c?.id}/export?format=${format}`
  return [
    open
      ? [
          {
            label: 'Instructions for this chat…',
            icon: ICONS.sliders,
            run: openSettings,
          },
          ...(c
            ? [{ label: 'Find in chat', icon: ICONS.search, run: openFind }]
            : []),
        ]
      : [],
    c
      ? [
          ...(c.archived
            ? []
            : [
                {
                  label: c.pinned ? 'Unpin' : 'Pin',
                  icon: ICONS.pin,
                  run: () => setFlags(c, { pinned: !c.pinned }),
                },
              ]),
          { label: 'Rename…', icon: ICONS.pencil, run: () => renameConv(c) },
        ]
      : [],
    c
      ? [
          {
            label: 'Download as Markdown',
            icon: ICONS.download,
            href: download('md'),
          },
          {
            label: 'Download as JSON',
            icon: ICONS.download,
            href: download('json'),
          },
        ]
      : [],
    c
      ? [
          {
            label: c.archived ? 'Unarchive' : 'Archive',
            icon: ICONS.archive,
            run: () => setFlags(c, { archived: !c.archived }),
          },
          {
            label: 'Delete…',
            icon: ICONS.trash,
            danger: true,
            run: () =>
              bus.dispatchEvent(new CustomEvent('delete-chat', { detail: c })),
          },
        ]
      : [],
  ].filter((group) => group.length)
}

/** @param {Item} item */
function itemElement(item) {
  const link = item.href
    ? Object.assign(document.createElement('a'), {
        href: item.href,
        download: '',
      })
    : null
  const el =
    link ?? Object.assign(document.createElement('button'), { type: 'button' })
  el.className = 'menu-item'
  el.tabIndex = -1
  el.setAttribute('role', 'menuitem')
  el.classList.toggle('is-danger', !!item.danger)
  el.innerHTML = icon(item.icon) + '<span class="menu-name"></span>'
  const name = /** @type {HTMLElement} */ (el.querySelector('.menu-name'))
  name.textContent = item.label
  el.onclick = () => {
    menu.hidePopover() // the browser returns the focus to the button
    item.run?.()
  }
  return el
}

/**
 * @param {HTMLElement} button the ⋯ that was pressed
 * @param {Conversation | null} c
 * @param {boolean} open
 */
function show(button, c, open) {
  anchor = button
  menu.replaceChildren(
    ...groups(c, open).flatMap((group, i) => [
      ...(i
        ? [
            Object.assign(document.createElement('hr'), {
              className: 'menu-sep',
            }),
          ]
        : []),
      ...group.map(itemElement),
    ]),
  )
  menu.showPopover()
}

// The ⋯ in the header: the open chat, as the server has it now (it may not be in the list yet, or on its page).
$('chat-menu-btn').onclick = async (e) => {
  const button = /** @type {HTMLElement} */ (e.currentTarget)
  /** @type {Conversation | null} */
  let conv = null
  if (state.id) {
    try {
      conv = await api(`/conversations/${state.id}`)
    } catch {
      conv = state.convs.find((c) => c.id === state.id) ?? null
    }
  }
  show(button, conv, true)
}

// The ⋯ on a row of the list.
bus.addEventListener('chat-menu', (e) => {
  const { button, conv } = /** @type {CustomEvent} */ (e).detail
  show(button, conv, conv.id === state.id)
})

// Under the button, its right edge on the button's, and above it when there is no room below.
menu.addEventListener('toggle', (e) => {
  const open = /** @type {ToggleEvent} */ (e).newState === 'open'
  anchor?.setAttribute('aria-expanded', String(open))
  if (!open || !anchor) return
  const r = anchor.getBoundingClientRect()
  const below = innerHeight - r.bottom
  menu.style.top = `${below >= menu.offsetHeight + 12 ? r.bottom + 4 : Math.max(8, r.top - menu.offsetHeight - 4)}px`
  menu.style.left = `${Math.max(8, Math.min(r.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 8))}px`
  const first = menu.querySelector('[role="menuitem"]')
  if (first instanceof HTMLElement) first.focus()
})
menuKeys(menu)
