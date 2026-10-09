// Find in the open chat: Mod+F (while a chat is open) or "Find in chat" in the ⋯ menu. The matches are highlighted
// with the CSS Custom Highlight API, so the text is not touched: no wrapping, no re-render to undo. A match inside
// one element of a message is found; one split across elements (bold half-way through a word) is not.
/* global NodeFilter, Range, Highlight */
import { $, bus, messagesEl, state, thread } from './core.js'

const bar = $('find')
const box = $('find-input')
const count = $('find-count')
const MAX = 500 // a one-letter search of a long chat: enough to step through, not enough to slow the page

/** @type {Range[]} */
let found = []
let at = -1
/** @type {string | null} the chat the bar was opened for */
let openFor = null

function matches(query) {
  const ranges = []
  const needle = query.toLowerCase()
  const walker = document.createTreeWalker(thread, NodeFilter.SHOW_TEXT, {
    // the words of the messages, not the buttons around them or the TeX a formula is read from
    acceptNode: (n) =>
      n.parentElement?.closest('.body') && !n.parentElement.closest('.katex')
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_REJECT,
  })
  for (
    let n = walker.nextNode();
    n && ranges.length < MAX;
    n = walker.nextNode()
  ) {
    const text = (n.textContent ?? '').toLowerCase()
    for (
      let i = text.indexOf(needle);
      i >= 0 && ranges.length < MAX;
      i = text.indexOf(needle, i + needle.length)
    ) {
      const range = new Range()
      range.setStart(n, i)
      range.setEnd(n, i + needle.length)
      ranges.push(range)
    }
  }
  return ranges
}

function paint() {
  CSS.highlights.set('find', new Highlight(...found))
  if (found[at]) CSS.highlights.set('find-current', new Highlight(found[at]))
  else CSS.highlights.delete('find-current')
  count.textContent = !box.value
    ? ''
    : found.length
      ? `${at + 1} of ${found.length >= MAX ? `${MAX}+` : found.length}`
      : 'No matches'
  const range = found[at]
  if (!range) return
  state.stick = false
  const r = range.getBoundingClientRect()
  const view = messagesEl.getBoundingClientRect()
  messagesEl.scrollTop += r.top - view.top - view.height / 2
}

function search() {
  found = box.value ? matches(box.value) : []
  at = found.length ? 0 : -1
  paint()
}

function step(by) {
  if (!found.length) return
  at = (at + by + found.length) % found.length
  paint()
}

export function openFind() {
  if (!state.id) return
  openFor = state.id
  bar.hidden = false
  box.focus()
  box.select()
  if (box.value) search() // the chat may have changed since it was last open
}

function closeFind() {
  bar.hidden = true
  found = []
  at = -1
  CSS.highlights.delete('find')
  CSS.highlights.delete('find-current')
  openFor = null
}

box.addEventListener('input', search)
box.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault()
    step(e.shiftKey ? -1 : 1)
  } else if (e.key === 'Escape') {
    e.stopPropagation()
    closeFind()
    $('input').focus()
  }
})
$('find-prev').addEventListener('click', () => step(-1))
$('find-next').addEventListener('click', () => step(1))
$('find-close').addEventListener('click', () => {
  closeFind()
  $('input').focus()
})
// another chat opens (app.js clears the thread): what was found is gone with the old one
bus.addEventListener('thread-reset', () => {
  if (openFor && state.id !== openFor) closeFind()
})
document.addEventListener('keydown', (e) => {
  if (
    (e.metaKey || e.ctrlKey) &&
    !e.shiftKey &&
    !e.altKey &&
    e.key.toLowerCase() === 'f' &&
    state.id &&
    !document.querySelector('dialog[open]')
  ) {
    e.preventDefault()
    openFind()
  }
})
