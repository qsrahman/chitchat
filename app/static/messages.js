// The thread: building a message (text, reasoning, tool calls, attachments, note), rendering it, and scrolling.
import { renderMarkdownInto, renderReasoningInto } from './markdown.js'
import {
  $,
  ICONS,
  bodyOf,
  icon,
  main,
  messagesEl,
  noteOf,
  state,
  thread,
} from './core.js'
import { renderToolCall } from './tools-ui.js'

// ---- scrolling ----
const nearBottom = () =>
  messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80
export function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight
}
messagesEl.addEventListener('scroll', () => {
  state.stick = nearBottom()
  $('jump').hidden = state.stick
})
$('jump').onclick = () => {
  state.stick = true
  scrollToBottom()
}

// ---- messages ----
// Each .msg = [details.reasoning] + .body (rendered text) + .note (stopped / cut off / compacted) + .actions.
// el._text and el._reasoning are the raw texts.
// Scroll a message (by its id in the database) into the middle of the view and light it up for a moment. False if
// it isn't in the thread.
export function jumpTo(id) {
  const el = id && thread.querySelector(`.msg[data-id="${id}"]`)
  if (!el) return false
  state.stick = false
  el.scrollIntoView({ block: 'center' })
  el.classList.add('is-found')
  setTimeout(() => el.classList.remove('is-found'), 2500)
  return true
}

/** @param {string} role @param {string} [text] @param {MessageMeta} [meta] @returns {MessageEl} */
export function addMessage(role, text = '', meta = {}) {
  const el = /** @type {MessageEl} */ (document.createElement('div'))
  el.className = `msg ${role}`
  for (const cls of ['body', 'note', 'actions'])
    el.append(Object.assign(document.createElement('div'), { className: cls }))
  if (role !== 'assistant') bodyOf(el).dir = 'auto' // plain text; a reply's blocks get theirs when rendered (markdown.js)
  thread.append(el)
  main.classList.add('is-started')
  for (const call of meta.tools ?? []) renderToolCall(el, call)
  if (meta.attachments?.length) {
    el._attachments = meta.attachments
    el.prepend(attachmentTiles(meta.attachments))
  }
  setNote(el, meta)
  el._model = meta.model // which model wrote a reply (chat.js shows it)
  el._usage = meta.usage // and what it cost in tokens
  if (meta.reasoning) setReasoning(el, meta.reasoning)
  setText(el, text)
  return el
}

// Sent attachments: images as thumbnails that open full size, everything else as a download link. Names are
// untrusted, so they only ever go in as text.
function attachmentTiles(files) {
  const tiles = document.createElement('div')
  tiles.className = 'attachments'
  for (const f of files) {
    const link = document.createElement('a')
    link.href = `/api/attachments/${f.id}`
    if (f.kind === 'image') {
      link.className = 'tile-image'
      link.target = '_blank'
      link.rel = 'noopener'
      link.title = f.name
      const img = Object.assign(document.createElement('img'), {
        src: link.href,
        alt: f.name,
      })
      link.append(img)
    } else {
      link.className = 'tile-file'
      link.title = `Download ${f.name}`
      link.innerHTML = icon(ICONS.file)
      link.append(
        Object.assign(document.createElement('span'), {
          className: 'chip-name',
          textContent: f.name,
        }),
      )
    }
    tiles.append(link)
  }
  return tiles
}

export function setNote(el, meta) {
  const note = noteOf(el)
  note.textContent = [
    meta.stopped && 'Stopped.',
    meta.incomplete && 'Reply cut off: output limit reached.',
    meta.compaction && 'Earlier messages were compacted to save context.',
    meta.trimmed &&
      `${meta.trimmed} earlier message${meta.trimmed === 1 ? ' was' : 's were'} left out to fit the model's context.`,
  ]
    .filter(Boolean)
    .join(' ')
  note.hidden = !note.textContent
}

// Re-rendering markdown on every delta is wasteful; coalesce to one render per frame. And a render that takes long
// (one enormous block, which the block reuse in markdown.js cannot help) makes the next ones wait: rendering may
// take about a third of the main thread, so scrolling and Stop stay usable. Renders under SLOW_MS never wait.
const SLOW_MS = 16
const WAIT_FACTOR = 2 // wait this many times as long as the last render took
function schedule(el) {
  if (el._frame || el._timer) return
  const wait = (el._resumeAt ?? 0) - performance.now()
  const frame = () => {
    el._frame = requestAnimationFrame(() => render(el))
  }
  if (wait > 0)
    el._timer = setTimeout(() => {
      el._timer = null
      frame()
    }, wait)
  else frame()
}
export function setText(el, text) {
  el._text = text
  schedule(el)
}
export function setReasoning(el, text) {
  el._reasoning = text
  schedule(el)
}

// The reasoning summary sits above the answer in a <details>: open and "Thinking…" while it streams,
// collapsed and "Reasoning" once the answer starts or for a saved message.
export function reasoningOf(el) {
  let details = el.querySelector('.reasoning')
  if (!details) {
    details = document.createElement('details')
    details.className = 'reasoning'
    details.innerHTML =
      '<summary>Reasoning</summary><div class="reasoning-body" tabindex="0"></div>' // scrolls when long
    el.prepend(details)
  }
  return details
}

export function finishReasoning(el) {
  const details = el.querySelector('.reasoning')
  if (!details) return
  details.open = false
  details.querySelector('summary').textContent = 'Reasoning'
}

export function render(el) {
  cancelAnimationFrame(el._frame)
  clearTimeout(el._timer)
  el._frame = el._timer = null
  const started = performance.now()
  const body = bodyOf(el)
  if (el._reasoning)
    renderReasoningInto(
      reasoningOf(el).querySelector('.reasoning-body'),
      el._reasoning,
    )
  if (el.classList.contains('assistant') && el._text)
    renderMarkdownInto(body, el._text) // reuses what has not changed
  else {
    body._blocks = null // the content is replaced by something else: the next markdown render starts afresh
    if (!el.classList.contains('assistant')) body.textContent = el._text
    else if (el._reasoning || el.querySelector('.tool-call'))
      body.replaceChildren() // those are the progress indicator
    else
      body.innerHTML =
        '<span class="dots" role="status" aria-label="Thinking"><i></i><i></i><i></i></span>'
  }
  if (state.stick) scrollToBottom()
  const took = performance.now() - started
  el._resumeAt = took > SLOW_MS ? performance.now() + WAIT_FACTOR * took : 0
}

// One full render with nothing reused: at the end of a stream, so a saved reply is exactly what a reload shows.
export function renderFresh(el) {
  bodyOf(el)._blocks = null
  const reasoning = el.querySelector('.reasoning-body')
  if (reasoning) reasoning._blocks = null
  render(el)
}

// Copy button inside rendered code blocks (event delegation: the HTML is re-rendered while streaming).
thread.addEventListener('click', async (e) => {
  const btn = e.target.closest('.code-copy')
  if (!btn) return
  await navigator.clipboard.writeText(
    btn.closest('.code').querySelector('code').innerText,
  )
  btn.textContent = 'Copied'
  setTimeout(() => (btn.textContent = 'Copy'), 1200)
})
