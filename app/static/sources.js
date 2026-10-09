// Sources: the pages this chat's search and page-reading calls found, as a panel beside the conversation, and the
// links in a reply that point at one of them as numbered chips (click one to see its card). Nothing is stored for
// this: the list is read from the tool calls the messages already carry (tools-ui.js records each finished one).
import { $, bus, textEl, thread } from './core.js'
import { hostOf, isWebUrl } from './tools-ui.js'

const panel = $('sources')
const button = $('sources-btn')
const list = $('sources-list')

/** @typedef {{url: string, title: string, description: string}} Source */

/** @param {ToolCall} call @returns {Source[]} */
function foundBy(call) {
  const shown = /** @type {any} */ (call.display) // each tool's own shape (app/tools/)
  if (call.name === 'web_search')
    return (shown?.results ?? []).filter((r) => isWebUrl(r.url))
  if (call.name === 'fetch_url' && isWebUrl(shown?.url))
    return [{ url: shown.url, title: shown.title || '', description: '' }]
  return []
}

// One page is one source however often it was found: the same address without its #fragment and trailing slash.
const key = (url) => new URL(url).href.replace(/#.*/, '').replace(/\/$/, '')

/** @returns {Source[]} in the order they were found */
export function allSources() {
  const found = new Map()
  for (const el of /** @type {NodeListOf<MessageEl>} */ (
    thread.querySelectorAll('.msg.assistant')
  ))
    for (const call of el._calls?.values() ?? [])
      for (const r of foundBy(call))
        if (!found.has(key(r.url))) found.set(key(r.url), r)
  return [...found.values()]
}

// A colour for a site's letter, the same every time (no favicons: that would be a request to every site found).
const hue = (host) =>
  [...host].reduce((n, c) => n + c.charCodeAt(0) * 7, 0) % 360
const dot = (host) =>
  Object.assign(textEl('i', host[0]?.toUpperCase() ?? '?'), {
    style: `background: hsl(${hue(host)} 45% 32%)`,
  })

/** Turn the links of a rendered reply that point at a source into chips: [1], [2]... */
export function chipLinks(body) {
  const sources = allSources()
  if (!sources.length) return
  const numbers = new Map(sources.map((s, i) => [key(s.url), i + 1]))
  for (const a of body.querySelectorAll('a[href]')) {
    const n = numbers.get(key(a.href))
    if (!n) continue
    const title = sources[n - 1].title || hostOf(a.href)
    a.classList.add('cite')
    a.textContent = String(n)
    a.setAttribute('aria-label', `Source ${n}: ${title}`)
    a.title = title
  }
}

function show(open) {
  const any = list.children.length > 0
  document.body.classList.toggle('sources-open', open && any)
  panel.hidden = !(open && any)
  button.setAttribute('aria-expanded', String(open && any))
}

let queued = false
function refresh() {
  if (queued) return
  queued = true
  Promise.resolve().then(() => {
    queued = false
    const sources = allSources()
    list.replaceChildren(
      ...sources.map((s, i) => {
        const host = hostOf(s.url)
        const card = Object.assign(document.createElement('a'), {
          className: 'source-card',
          href: s.url,
          target: '_blank',
          rel: 'noopener noreferrer',
          id: `source-${i + 1}`,
        })
        card.dir = 'auto'
        const site = textEl('span', '')
        site.className = 'source-host'
        site.append(dot(host), `${i + 1} · ${host}`)
        card.append(site, textEl('strong', s.title || host))
        if (s.description) card.append(textEl('p', s.description))
        return card
      }),
    )
    button.hidden = !sources.length
    button.querySelector('.count').textContent =
      `${sources.length} source${sources.length === 1 ? '' : 's'}`
    button
      .querySelector('.site-dots')
      .replaceChildren(
        ...[...new Set(sources.map((s) => hostOf(s.url)))].slice(0, 3).map(dot),
      )
    show(document.body.classList.contains('sources-open'))
  })
}

bus.addEventListener('sources', refresh)
bus.addEventListener('thread-reset', refresh)
button.addEventListener('click', () => show(panel.hidden))
$('sources-close').addEventListener('click', () => {
  show(false)
  button.focus()
})
panel.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    show(false)
    button.focus()
  }
})
thread.addEventListener('click', (e) => {
  const chip = /** @type {HTMLElement} */ (e.target).closest?.('a.cite')
  if (!chip || e.metaKey || e.ctrlKey || e.shiftKey) return
  e.preventDefault()
  show(true)
  const card = /** @type {HTMLElement | null} */ (
    panel.querySelector(`#source-${chip.textContent}`)
  )
  list.querySelectorAll('.is-hit').forEach((c) => c.classList.remove('is-hit'))
  if (!card) return
  card.classList.add('is-hit')
  card.scrollIntoView({ block: 'nearest' })
  card.focus()
})
