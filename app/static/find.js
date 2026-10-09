// Find in the open chat: Mod+F (while a chat is open) or "Find in chat" in the ⋯ menu. The matches are highlighted
// with the CSS Custom Highlight API, so the text is not touched: no wrapping, no re-render to undo. A match may run
// over bold or a link inside a paragraph, not from one paragraph or table cell into the next.
/* global NodeFilter, Range, Highlight, MutationObserver */
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

// The blocks of text a match may not cross: a match runs over bold or a link inside a paragraph, not from one
// paragraph, list item or table cell into the next.
const BLOCK =
  'p, li, td, th, h1, h2, h3, h4, h5, h6, pre, blockquote, summary, .tool-body, .reasoning-body, .body'
// What is read: the words of the messages, the reasoning and the tool lines, not the buttons around them or the
// TeX a formula is read from.
const READ = '.body, .reasoning-body, .tool-call'

function matches(query) {
  const needle = query.toLowerCase()
  /** @type {Map<Element, Text[]>} */
  const blocks = new Map()
  const walker = document.createTreeWalker(thread, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) =>
      n.parentElement?.closest(READ) && !n.parentElement.closest('.katex')
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_REJECT,
  })
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const block = /** @type {Text} */ (n).parentElement?.closest(BLOCK)
    if (block)
      blocks.set(block, [...(blocks.get(block) ?? []), /** @type {Text} */ (n)])
  }
  const ranges = []
  for (const nodes of blocks.values()) {
    const text = nodes
      .map((n) => n.data)
      .join('')
      .toLowerCase()
    // where each node starts in the block's text, to turn a position in the text back into a node and an offset
    const starts = nodes.map((_, i) =>
      nodes.slice(0, i).reduce((sum, n) => sum + n.data.length, 0),
    )
    const place = (pos, atEnd) => {
      let i = starts.findLastIndex((start) => start <= pos)
      if (atEnd && i > 0 && starts[i] === pos) i-- // an end belongs to the node it ends in
      return { node: nodes[i], offset: pos - starts[i] }
    }
    for (
      let i = text.indexOf(needle);
      i >= 0 && ranges.length < MAX;
      i = text.indexOf(needle, i + needle.length)
    ) {
      const range = new Range()
      const from = place(i, false)
      const to = place(i + needle.length, true)
      range.setStart(from.node, from.offset)
      range.setEnd(to.node, to.offset)
      ranges.push(range)
    }
    if (ranges.length >= MAX) break
  }
  return ranges
}

/** @param {boolean} [scroll] go to the current match (not while a reply is streaming in) */
function paint(scroll = true) {
  CSS.highlights.set('find', new Highlight(...found))
  if (found[at]) CSS.highlights.set('find-current', new Highlight(found[at]))
  else CSS.highlights.delete('find-current')
  count.textContent = !box.value
    ? ''
    : found.length
      ? `${at + 1} of ${found.length >= MAX ? `${MAX}+` : found.length}`
      : 'No matches'
  const range = found[at]
  if (!range || !scroll) return
  // a match in reasoning or a tool call is inside a closed <details>: open what it is in, as the browser's find does
  for (
    let d = range.startContainer.parentElement?.closest('details');
    d;
    d = d.parentElement?.closest('details')
  )
    d.open = true
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

// The thread changes while the bar is open (a reply streams in): look again, a moment after the last change, and
// stay on the same match. The view is not moved, the reader is somewhere.
/** @type {ReturnType<typeof setTimeout> | undefined} */
let again
new MutationObserver(() => {
  if (bar.hidden || !box.value) return
  clearTimeout(again)
  again = setTimeout(() => {
    found = matches(box.value)
    at = Math.min(at, found.length - 1)
    paint(false)
  }, 300)
}).observe(thread, { childList: true, subtree: true, characterData: true })

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
