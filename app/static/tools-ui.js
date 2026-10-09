// How a tool call the model made reads in a reply: one line while it runs and when it is done, with details to open.
import { bodyOf, bus, textEl } from './core.js'

// ---- tool calls ----
// A tool the model called shows as a line above the answer: "Searching the web for ..." while it runs, then
// "Searched the web for ..." that opens to the results. How each tool reads is in TOOL_UI; others get a plain line.
export const hostOf = (url) => new URL(url).hostname.replace(/^www\./, '')
export const isWebUrl = (url) => {
  try {
    return ['http:', 'https:'].includes(new URL(url).protocol)
  } catch {
    return false
  }
}

const safeHost = (url) => {
  try {
    return hostOf(url)
  } catch {
    return ''
  }
}
const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`

const TOOL_UI = {
  calculator: {
    running: (args) => `Calculating ${args.expression ?? ''}…`,
    done: (args, shown) => `${shown.expression} = ${shown.result}`,
    failed: (error) => `Calculator: ${error}`,
    stopped: 'Calculation stopped',
  },
  search_chats: {
    running: (args) => `Searching your chats for “${args.query ?? ''}”…`,
    done: (args, shown) =>
      `Searched your chats for “${shown.query}” · ${shown.results.length ? plural(shown.results.length, 'chat') : 'no matches'}`,
    failed: (error) => `Chat search failed: ${error}`,
    stopped: 'Chat search stopped',
    detail: (shown) => {
      const list = document.createElement('ol')
      for (const r of shown.results) {
        const item = document.createElement('li')
        const link = Object.assign(textEl('a', r.title), {
          href: `#${encodeURIComponent(r.id)}`,
        }) // a chat in this app
        item.append(link, textEl('p', r.snippet))
        list.append(item)
      }
      return list
    },
  },
  fetch_url: {
    running: (args) => `Reading ${safeHost(args.url) || 'the page'}…`,
    done: (args, shown) =>
      `Read ${shown.title || safeHost(shown.url) || 'a page'}`,
    failed: (error) => `Couldn't read the page: ${error}`,
    stopped: 'Reading the page stopped',
    detail: (shown) => {
      const box = document.createElement('div')
      if (isWebUrl(shown.url)) {
        // the URL came from the model: web links only
        box.append(
          Object.assign(textEl('a', shown.url), {
            href: shown.url,
            target: '_blank',
            rel: 'noopener noreferrer',
          }),
        )
      }
      // saved from before pages came in parts have no offset or total
      const from = shown.offset
        ? ` from character ${shown.offset.toLocaleString()}`
        : ''
      const total = shown.total ? ` of ${shown.total.toLocaleString()}` : ''
      const more = shown.truncated ? '; there is more' : ''
      box.append(
        textEl(
          'p',
          `${plural(shown.characters, 'character')} read${from}${total}${more}`,
        ),
      )
      return box
    },
  },
  web_search: {
    running: (args) => `Searching the web for “${args.query ?? ''}”…`,
    done: (args, shown) => {
      const n = shown.results.length
      return `Searched the web for “${shown.query}” · ${n ? `${n} result${n === 1 ? '' : 's'}` : 'no results'}`
    },
    failed: (error) => `Web search failed: ${error}`,
    stopped: 'Web search stopped',
    detail: (shown) => {
      const list = document.createElement('ol')
      for (const r of shown.results.filter((r) => isWebUrl(r.url))) {
        // URLs from the web are untrusted: web links only
        const item = document.createElement('li')
        const link = Object.assign(document.createElement('a'), {
          href: r.url,
          target: '_blank',
          rel: 'noopener noreferrer',
          textContent: r.title,
        })
        item.append(
          link,
          Object.assign(document.createElement('span'), {
            className: 'domain',
            textContent: hostOf(r.url),
          }),
        )
        if (r.description)
          item.append(
            Object.assign(document.createElement('p'), {
              textContent: r.description,
            }),
          )
        list.append(item)
      }
      return list
    },
  },
  get_datetime: {
    running: () => 'Checking the time…',
    done: (args, shown) => `${shown.now} · ${shown.timezone}`,
    failed: (error) => `Date and time: ${error}`,
    stopped: 'Checking the time stopped',
    detail: (shown) => {
      if (!shown.also?.length) return null
      const list = document.createElement('ul')
      list.append(...shown.also.map((line) => textEl('li', line)))
      return list
    },
  },
  read_chat: {
    running: () => 'Reading a past chat…',
    done: (args, shown) =>
      `Read “${shown.title}” · messages ${shown.from} to ${shown.to} of ${shown.total}`,
    failed: (error) => `Couldn't read the chat: ${error}`,
    stopped: 'Reading the chat stopped',
    detail: (shown) => {
      // a chat in this app, so it opens in this tab
      const link = Object.assign(textEl('a', shown.title), {
        href: `#${encodeURIComponent(shown.id)}`,
      })
      const box = document.createElement('div')
      box.append(link)
      return box
    },
  },
  read_attachment: {
    running: (args) =>
      args.name ? `Reading ${args.name}…` : 'Looking at the attached files…',
    done: (args, shown) =>
      shown.files
        ? `Listed the attached files · ${plural(shown.files.length, 'file')}`
        : `Read ${shown.name}${shown.offset ? ` from character ${shown.offset.toLocaleString()}` : ''}`,
    failed: (error) => `Couldn't read the file: ${error}`,
    stopped: 'Reading the file stopped',
    detail: (shown) => {
      if (shown.files) {
        const list = document.createElement('ul')
        list.append(...shown.files.map((name) => textEl('li', name)))
        return list
      }
      const total = shown.total
        ? ` of ${shown.total.toLocaleString()}${shown.offset + shown.characters < shown.total ? '; there is more' : ''}`
        : ''
      return textEl(
        'p',
        `${plural(shown.characters, 'character')} read${shown.offset ? ` from character ${shown.offset.toLocaleString()}` : ''}${total}`,
      )
    },
  },
}

export function renderToolCall(el, call) {
  let box = el.querySelector('.tool-calls')
  if (!box) {
    box = Object.assign(document.createElement('div'), {
      className: 'tool-calls',
    })
    bodyOf(el).before(box)
  }
  let row = [...box.children].find((d) => d.dataset.id === call.id)
  if (!row) {
    row = document.createElement('details')
    row.className = 'tool-call'
    row.dataset.id = call.id
    row.dataset.name = call.name
    row.innerHTML = '<summary></summary><div class="tool-body"></div>'
    box.append(row)
  }
  const ui = TOOL_UI[call.name]
  row.querySelector('summary').dir = 'auto'
  row.dataset.status = call.status
  row.setAttribute('aria-busy', String(call.status === 'running'))
  let summary,
    detail = null
  try {
    summary = {
      running: () => ui?.running(call.arguments ?? {}) ?? `Using ${call.name}…`,
      done: () =>
        ui?.done(call.arguments ?? {}, call.display) ?? `Used ${call.name}`,
      error: () =>
        ui?.failed(call.error) ?? `${call.name} failed: ${call.error}`,
      stopped: () => ui?.stopped ?? `${call.name} stopped`,
    }[call.status]()
    detail = call.status === 'done' ? ui?.detail?.(call.display) : null
  } catch {
    // Saved details this page doesn't expect (from an older version, or an imported file) must not break the
    // whole conversation: it falls back to a plain line.
    summary = `Used ${call.name}`
  }
  row.querySelector('summary').textContent = summary
  row.querySelector('.tool-body').replaceChildren(...(detail ? [detail] : []))
  if (call.status === 'done') {
    // the Sources panel lists the pages the calls of every reply found (sources.js)
    ;(el._calls ??= new Map()).set(call.id, call)
    bus.dispatchEvent(new Event('sources'))
  }
}
