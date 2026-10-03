// A turn: streaming a reply into the thread, and the actions on messages (copy, edit, regenerate, retry).
import {
  ICONS,
  actionsOf,
  api,
  bodyOf,
  bus,
  form,
  iconButton,
  input,
  state,
  textEl,
  thread,
} from './core.js'
import {
  addMessage,
  finishReasoning,
  reasoningOf,
  render,
  renderFresh,
  setNote,
  setReasoning,
  setText,
} from './messages.js'
import {
  clearPending,
  focusComposer,
  pending,
  saveDraft,
  scheduleComposer,
  syncSend,
} from './composer.js'
import { refreshList } from './list.js'
import { openRetryMenu } from './retry-menu.js'
import { renderToolCall } from './tools-ui.js'

function actionButton(label, onclick) {
  const b = document.createElement('button')
  b.type = 'button'
  b.textContent = label
  b.onclick = onclick
  return b
}

const clearActions = () => {
  thread.querySelectorAll('.actions').forEach((a) => a.replaceChildren())
  thread
    .querySelectorAll('.has-versions')
    .forEach((m) => m.classList.remove('has-versions'))
}

// Every message that has text gets Copy (copying only that message), and a user message gets Edit; Regenerate on
// the last reply, or Retry when the conversation ends on a user message or an error. A message that has other
// versions (an edit, another reply) shows "2 / 3" with arrows to move between them. Icon buttons, named by aria-label.
export function updateActions() {
  clearActions()
  if (state.busy) return
  const msgs = [...thread.children]
  const last = msgs.at(-1)
  const lastUser = msgs.findLast((m) => m.classList.contains('user'))
  for (const m of msgs.filter(
    (m) =>
      m._text &&
      (m.classList.contains('assistant') || m.classList.contains('user')),
  )) {
    const copy = iconButton('Copy', ICONS.copy, async () => {
      await navigator.clipboard.writeText(m._text)
      confirmed(copy)
    })
    actionsOf(m).append(copy)
    if (m.classList.contains('user'))
      actionsOf(m).append(iconButton('Edit', ICONS.pencil, () => startEdit(m)))
    if (m._siblings?.length > 1) {
      actionsOf(m).prepend(versionSwitcher(m))
      m.classList.add('has-versions')
    }
  }
  for (const m of msgs.filter(
    (m) => m._model && m.classList.contains('assistant'),
  )) {
    // which model wrote it
    actionsOf(m).append(textEl('span', m._model, 'model-tag'))
  }
  if (last?.classList.contains('assistant')) {
    actionsOf(last).append(
      iconButton('Regenerate', ICONS.refresh, () => regenerate()),
      anotherModel((model) => regenerate(model)),
    )
  } else if (last && lastUser) {
    actionsOf(last).append(
      iconButton('Retry', ICONS.refresh, () => retry(lastUser)),
      anotherModel((model) => retry(lastUser, model)),
    )
  }
}

// The button after Regenerate / Retry: a menu of models to run that reply again with.
function anotherModel(run) {
  const b = iconButton('Try again with another model', ICONS.chevronDown, () =>
    openRetryMenu(b, run),
  )
  b.setAttribute('aria-haspopup', 'menu')
  b.setAttribute('aria-expanded', 'false')
  return b
}

// ---- versions of a message ----
// A message's id and the ids of its versions (`_siblings`, oldest first, itself included) come from the server: with
// the conversation when it is opened, and with the "done" event of a turn. A message that stopped or failed has
// neither, so syncIds() asks (when an edit needs the id).
const markVersions = (el, { id, siblings }) => {
  if (!el) return
  el.dataset.id = id
  el._siblings = siblings
}

async function syncIds() {
  const { messages } = await api(`/conversations/${state.id}`)
  const els = [...thread.children].filter(
    (e) => e.classList.contains('user') || e.classList.contains('assistant'),
  )
  messages.forEach((m, i) => els[i] && markVersions(els[i], m))
  return messages
}

function versionSwitcher(m) {
  const ids = m._siblings
  const at = ids.indexOf(Number(m.dataset.id))
  const box = document.createElement('span')
  box.className = 'versions'
  box.setAttribute('role', 'group')
  box.setAttribute('aria-label', 'Versions of this message')
  const previous = iconButton('Previous version', ICONS.previous, () =>
    showVersion(ids[at - 1]),
  )
  const next = iconButton('Next version', ICONS.next, () =>
    showVersion(ids[at + 1]),
  )
  previous.disabled = at <= 0
  next.disabled = at >= ids.length - 1
  box.append(
    previous,
    textEl('span', `${at + 1} / ${ids.length}`, 'versions-count'),
    next,
  )
  return box
}

// The server switches the path; the conversation is then opened again, at that message (app.js).
async function showVersion(id) {
  await api(`/conversations/${state.id}/branch`, {
    method: 'POST',
    body: JSON.stringify({ message_id: id }),
  })
  state.jumpTo = id
  bus.dispatchEvent(new CustomEvent('open', { detail: state.id }))
}

// Briefly show a check mark and "Copied" on an icon button.
function confirmed(btn) {
  const path = btn.querySelector('path')
  const [d, label] = [path.getAttribute('d'), btn.getAttribute('aria-label')]
  path.setAttribute('d', ICONS.check)
  btn.setAttribute('aria-label', 'Copied')
  btn.title = 'Copied'
  setTimeout(() => {
    path.setAttribute('d', d)
    btn.setAttribute('aria-label', label)
    btn.title = label
  }, 1200)
}

async function startEdit(m) {
  clearActions()
  if (!m.dataset.id) await syncIds().catch(() => {}) // a message that has no id yet: the server will take the last one
  const ta = document.createElement('textarea')
  ta.className = 'edit'
  ta.dir = 'auto'
  ta.setAttribute('aria-label', 'Edit your message')
  ta.value = m._text
  bodyOf(m).replaceChildren(ta)
  actionsOf(m).append(
    actionButton('Save', () => {
      const text = ta.value.trim()
      if (!text) return
      while (m.nextElementSibling) m.nextElementSibling.remove()
      setText(m, text)
      runTurn('edit', {
        content: text,
        ...(m.dataset.id && { message_id: Number(m.dataset.id) }),
      })
    }),
    actionButton('Cancel', () => {
      render(m)
      updateActions()
    }),
  )
  ta.focus()
}

function regenerate(model) {
  while (
    thread.lastElementChild &&
    !thread.lastElementChild.classList.contains('user')
  )
    thread.lastElementChild.remove()
  runTurn('regenerate', model ? { model } : {})
}

// Retry differs from Regenerate: after a failed send or edit the server may not have what the page
// shows, so regenerating would 409 (message never saved) or reply to stale text (edit never saved).
// Compare the page with what the server stored, and redo the turn the way that makes them agree.
async function retry(user, model) {
  const dropAfterUser = () => {
    while (thread.lastElementChild !== user) thread.lastElementChild.remove()
  }
  let saved
  try {
    saved = state.id ? (await syncIds()).filter((m) => m.role === 'user') : []
  } catch {
    dropAfterUser()
    addMessage(
      'error',
      "Couldn't reach the server. Check your connection and retry.",
    )
    return updateActions()
  }
  if (saved.length < thread.querySelectorAll('.msg.user').length) {
    // this message never landed
    dropAfterUser()
    runTurn('chat', {
      content: user._text,
      attachments: (user._attachments ?? []).map((a) => a.id),
      ...(model && { model }),
    })
  } else if (saved.at(-1).content === user._text) {
    // it landed; any reply (or partial one) is replaced
    regenerate(model)
  } else {
    // an edit that never landed
    dropAfterUser()
    runTurn('edit', {
      content: user._text,
      ...(user.dataset.id && { message_id: Number(user.dataset.id) }),
      ...(model && { model }),
    })
  }
}

// ---- sse ----
// Yields parsed `data: {json}` SSE events. Hand-written because EventSource is GET-only, and these turns
// are POSTs; TextDecoderStream does the decoding. Comment frames (keepalive pings) are skipped.
/** @param {Response} response @returns {AsyncGenerator<StreamEvent>} */
async function* readSSE(response) {
  if (!response.body) return // runTurn then reports that the connection closed early
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buf += value
    let i
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i)
      buf = buf.slice(i + 2)
      if (frame.startsWith('data: ')) yield JSON.parse(frame.slice(6))
    }
  }
}

// ---- sending ----
// Streams a reply from POST /api/conversations/{id}/{path} into a new assistant message.
async function runTurn(path, payload = {}) {
  const ctrl = (state.abort = new AbortController())
  state.busy = true
  state.stick = true
  thread.setAttribute('aria-busy', 'true')
  syncSend()
  updateActions()
  const el = addMessage('assistant')
  let reply = ''
  let finished = false
  let compaction = false
  let trimmed = 0
  try {
    if (!state.id) {
      state.id = (
        await api('/conversations', {
          method: 'POST',
          body: JSON.stringify({ settings: state.settings }),
        })
      ).id
      history.replaceState(null, '', `#${state.id}`)
    }
    const res = await fetch(`/api/conversations/${state.id}/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    })
    if (!res.ok) throw new Error(`Server returned ${res.status}`)
    for await (const ev of readSSE(res)) {
      if (ev.type === 'delta') {
        if (!reply) finishReasoning(el)
        reply += ev.text
        setText(el, reply)
      } else if (ev.type === 'reasoning_delta') {
        if (!el._reasoning) {
          // first of the stream: show it live
          const details = reasoningOf(el)
          details.open = true
          details.querySelector('summary').textContent = 'Thinking…'
        }
        setReasoning(el, (el._reasoning ?? '') + ev.text)
      } else if (ev.type === 'tool_call') {
        renderToolCall(el, ev)
        render(el)
      } else if (ev.type === 'compaction') compaction = true
      else if (ev.type === 'context_trimmed') trimmed = ev.count
      else if (ev.type === 'done') {
        finished = true
        el._model = ev.model
        setNote(el, { ...ev, compaction, trimmed })
        if (ev.branch) {
          // the reply answers the user message just before it
          markVersions(el.previousElementSibling, ev.branch.user)
          markVersions(el, ev.branch.assistant)
        }
      } else if (ev.type === 'error') throw new Error(ev.message)
    }
    if (!finished)
      throw new Error('The connection closed before the reply finished.')
  } catch (err) {
    if (err.name === 'AbortError') setNote(el, { stopped: true, trimmed })
    else {
      el.className = 'msg error'
      el.querySelector('.reasoning')?.remove()
      el.querySelector('.tool-calls')?.remove()
      el._reasoning = null
      setText(el, `Couldn't get a reply. ${err.message}`)
    }
  } finally {
    for (const row of /** @type {NodeListOf<HTMLElement>} */ (
      el.querySelectorAll('.tool-call[data-status="running"]')
    )) {
      // a stopped search stays "running" otherwise
      renderToolCall(el, {
        id: row.dataset.id,
        name: row.dataset.name,
        status: 'stopped',
      })
    }
    finishReasoning(el)
    renderFresh(el)
    if (
      el.classList.contains('assistant') &&
      !el._text &&
      !el._reasoning &&
      !el.querySelector('.tool-call')
    )
      el.remove()
    if (state.abort === ctrl) {
      // a newer turn may already own the UI (e.g. after switching chats)
      state.busy = false
      state.abort = null
      thread.removeAttribute('aria-busy')
      syncSend()
      updateActions()
      focusComposer()
    }
  }
  refreshList() // picks up the new title and recency order
}

function submit(text) {
  const files = pending.filter((p) => p.status === 'done').map((p) => p.file)
  input.value = ''
  saveDraft()
  scheduleComposer()
  clearPending()
  addMessage('user', text, { attachments: files })
  runTurn('chat', { content: text, attachments: files.map((f) => f.id) })
}

form.addEventListener('submit', (e) => {
  e.preventDefault()
  if (state.busy) return state.abort?.abort() // the button is "Stop" while streaming
  const text = input.value.trim()
  const ready = pending.some((p) => p.status === 'done')
  if (pending.some((p) => p.status === 'uploading')) return
  if (text || ready) submit(text)
})

document.addEventListener('keydown', (e) => {
  if (
    e.key === 'Escape' &&
    state.busy &&
    !document.querySelector('dialog[open]')
  )
    state.abort?.abort()
})
