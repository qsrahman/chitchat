// The Settings dialog (the sidebar's gear): appearance and shortcuts, custom instructions, export and import, and what
// the server is set up with. Settings that belong to one chat (model, system prompt, temperature) are in
// settings.js; the import itself is in backup.js. The design and what is where: docs/settings-dialog.md.
import { $, WEB_SEARCH, api, bus, state } from './core.js'
import { closeNavIfOverlay } from './nav.js'
import { loadStorage } from './storage.js'
import {
  defaults,
  modelInfo,
  newChatSettings,
  saveDefaults,
  setSettings,
} from './settings.js'

const dialog = $('prefs-dialog')
const tabs = [...dialog.querySelectorAll('[role="tab"]')]

// ---- tabs ----
function lastTab() {
  try {
    return (
      tabs.find((t) => t.id === localStorage.getItem('prefsTab'))?.id ??
      'tab-general'
    )
  } catch {
    return 'tab-general'
  }
}
// A vertical tab list with the keyboard contract of the pattern: arrows move between tabs (and show them), Home and
// End jump, only the selected tab is in the tab order, and the panel is in the tab order after it.
function showTab(tab, focus = false) {
  for (const t of tabs) {
    const on = t === tab
    t.setAttribute('aria-selected', String(on))
    t.tabIndex = on ? 0 : -1
    $(t.getAttribute('aria-controls')).hidden = !on
  }
  if (focus) tab.focus()
  tab.scrollIntoView({ block: 'nearest', inline: 'nearest' }) // in the phone's row of tabs it may be off to the side
  if (tab.id === 'tab-server') loadServer()
  if (tab.id === 'tab-data') loadStorage()
  try {
    localStorage.setItem('prefsTab', tab.id)
  } catch {
    /* storage blocked: it opens on General next time */
  }
}
tabs.forEach((t) => (t.onclick = () => showTab(t)))
dialog.querySelector('[role="tablist"]').addEventListener('keydown', (e) => {
  const at = tabs.indexOf(document.activeElement)
  const to = {
    ArrowDown: at + 1,
    ArrowRight: at + 1,
    ArrowUp: at - 1,
    ArrowLeft: at - 1,
    Home: 0,
    End: tabs.length - 1,
  }[e.key]
  if (to === undefined || at < 0) return
  e.preventDefault()
  showTab(tabs[(to + tabs.length) % tabs.length], true)
})

// Opens on the tab it was last left on (kept in this browser), General the first time.
export function openPreferences(tabId = lastTab()) {
  $('backup-status').hidden = true // what the last import said is not news
  loadInstructions()
  fillDefaults()
  showTab($(tabId))
  closeNavIfOverlay() // on a phone the drawer was open to reach the gear; it is in the way behind the dialog
  dialog.showModal()
}
$('prefs-btn').onclick = () => openPreferences()

// ---- General: appearance ----
// System follows the operating system; Light and Dark are remembered in this browser. early/theme.js applies the
// saved one before the first paint; the colors are in style.css.
const theme = $('pref-theme')
theme.value = document.documentElement.dataset.theme ?? 'system'
theme.onchange = () => {
  if (theme.value === 'system') delete document.documentElement.dataset.theme
  else document.documentElement.dataset.theme = theme.value
  try {
    if (theme.value === 'system') localStorage.removeItem('theme')
    else localStorage.setItem('theme', theme.value)
  } catch {
    /* storage blocked: the choice lasts until the page closes */
  }
}

// ---- General: new chats ----
// The model and thinking effort a chat uses when it picks none, and whether new chats start with web search. They are
// saved as they change (no Save button), and the chat's own settings (settings.js) still win.
const defaultModel = $('pref-model')
const defaultEffort = $('pref-effort')
const defaultSearch = $('pref-search')

function fillDefaults() {
  const { models, efforts = [], server_default: server } = modelInfo
  const saved = defaults.model
  const ids = models.map((m) => m.id)
  if (saved && !ids.includes(saved)) ids.push(saved) // no longer listed by the provider: keep showing the choice
  defaultModel.replaceChildren(
    new Option(`Server default (${server ?? modelInfo.default ?? '…'})`, ''),
    ...ids.map((id) => new Option(id, id)),
  )
  defaultModel.value = saved ?? ''
  defaultEffort.replaceChildren(
    new Option('Auto', ''),
    ...efforts.map((e) => new Option(e[0].toUpperCase() + e.slice(1), e)),
  )
  defaultEffort.value = defaults.reasoning_effort ?? ''
  const tool = state.tools.find((t) => t.name === WEB_SEARCH)
  defaultSearch.disabled = !tool
  defaultSearch.checked = !!tool && defaults.tools.includes(WEB_SEARCH)
  $('pref-search-note').textContent = tool
    ? 'Start new chats with web search on.'
    : 'Unavailable: set BRAVE_API_KEY on the server.'
}
bus.addEventListener('models', fillDefaults)

// One save at a time, each built from what the one before saved (the tools list is made from the saved list, so two
// quick changes of web search would otherwise each start from the old one and the later would undo the earlier).
let saving = Promise.resolve()
/** @param {Partial<Defaults>} change */
const saveDefault = (change) =>
  (saving = saving.then(() => storeDefault(change)))

/** @param {Partial<Defaults>} change */
async function storeDefault(change) {
  $('defaults-error').hidden = true
  try {
    await saveDefaults(change)
    if (!state.id)
      setSettings({ ...state.settings, tools: newChatSettings().tools }) // the chat on screen is a new one
  } catch {
    $('defaults-error').hidden = false
    fillDefaults() // back to what is saved
  }
}
defaultModel.onchange = () => saveDefault({ model: defaultModel.value || null })
defaultEffort.onchange = () =>
  saveDefault({ reasoning_effort: defaultEffort.value || null })
defaultSearch.onchange = () =>
  saveDefault({
    tools: defaultSearch.checked
      ? [...new Set([...defaults.tools, WEB_SEARCH])]
      : defaults.tools.filter((t) => t !== WEB_SEARCH),
  })

// ---- General: shortcuts ----
const mod = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl+'
/** @type {[string, string[]][]} */
const SHORTCUTS = [
  ['Search chats', [`${mod}K`]],
  ['New chat', [`${mod}Shift+O`]],
  ['Send the message', ['Enter']],
  ['New line in the message', ['Shift+Enter']],
  ['Stop a reply', ['Esc']],
]
$('shortcut-list').replaceChildren(
  ...SHORTCUTS.map(([label, keys]) => {
    const row = Object.assign(document.createElement('div'), {
      className: 'pref-row',
    })
    const text = Object.assign(document.createElement('span'), {
      className: 'pref-label',
      textContent: label,
    })
    const kbd = Object.assign(document.createElement('kbd'), {
      textContent: keys.join(' '),
    })
    row.append(text, kbd)
    return row
  }),
)

// ---- Personalization: custom instructions ----
const instructions = $('set-instructions')
const status = $('instructions-status')
let typed = false // the box has been edited since it was filled: what arrives later must not replace it
async function loadInstructions() {
  status.textContent = ''
  typed = false
  try {
    const { text } = await api('/custom-instructions')
    if (!typed) instructions.value = text
  } catch {
    status.textContent = "Couldn't load them. Check your connection."
  }
  try {
    const { default_instructions: text } = await api('/config')
    $('default-instructions-text').textContent =
      text || 'Nothing: DEFAULT_SYSTEM_PROMPT is empty.'
  } catch {
    /* the details stay empty; the Server tab says what is wrong */
  }
}
$('instructions-save').onclick = async (e) => {
  const button = e.currentTarget
  button.disabled = true
  status.classList.remove('is-error')
  try {
    await api('/custom-instructions', {
      method: 'PUT',
      body: JSON.stringify({ text: instructions.value }),
    })
    status.textContent = 'Saved.'
  } catch {
    status.textContent = "Couldn't save. Check your connection and try again."
    status.classList.add('is-error')
  }
  button.disabled = false
}
instructions.addEventListener('input', () => {
  typed = true
  status.textContent = ''
})

// ---- Server: what it is set up with (read only) ----
const tokens = (n) => `${n.toLocaleString()} tokens`
/** @param {ServerConfig} config */
function rows(config) {
  const context = config.compaction
    ? `OpenAI compacts the conversation once it passes ${tokens(config.compact_threshold)}`
    : config.history_tokens
      ? `The oldest messages are left out beyond ${tokens(config.history_tokens)}`
      : 'All of the conversation is sent every time'
  return [
    [
      'Connection',
      [
        ['Endpoint', config.endpoint, 'OPENAI_BASE_URL'],
        [
          'Default model',
          // what Settings chose (General, New chats) is what chats use; the server's is the fallback
          config.chosen_model
            ? `${config.chosen_model} (chosen in Settings; the server's is ${config.model})`
            : config.model,
          'OPENAI_MODEL',
        ],
        ['Chat titles are written by', config.title_model, 'TITLE_MODEL'],
      ],
    ],
    [
      'Conversations',
      [
        [
          'Long conversations',
          context,
          config.compaction ? 'COMPACT_THRESHOLD' : 'CONTEXT_TOKENS',
        ],
        [
          'Longest reply',
          config.max_output_tokens
            ? tokens(config.max_output_tokens)
            : "The model's own limit",
          'OPENAI_MAX_OUTPUT_TOKENS',
        ],
        [
          'PDFs',
          config.pdf_input === 'file'
            ? 'Sent to the model as a file'
            : 'Their text is sent',
          'OPENAI_PDF_INPUT',
        ],
        [
          'Thinking summaries',
          config.reasoning_summaries ? 'Asked for' : 'Not asked for',
          'OPENAI_REASONING_SUMMARIES',
        ],
      ],
    ],
    [
      'Tools',
      [
        [
          'Web search',
          config.web_search
            ? 'On'
            : 'Off: add a Brave Search key to turn it on',
          'BRAVE_API_KEY',
        ],
        ['Tools you can switch on', config.tools.join(', ') || 'None', null],
        [
          'Switched on in new chats',
          // the defaults for new chats (General): every tool but web search until the user chooses otherwise
          state.tools
            .filter((t) => defaults.tools.includes(t.name))
            .map((t) => t.label)
            .join(', ') || 'None',
          null,
        ],
        [
          'Tool calls in one reply',
          String(config.max_tool_calls),
          'MAX_TOOL_CALLS',
        ],
      ],
    ],
    [
      'Storage',
      [
        ['Database', config.database, 'DB_PATH'],
        ['Attachments', config.attachments, 'ATTACHMENTS_DIR'],
        ['Log level', config.log_level, 'LOG_LEVEL'],
      ],
    ],
  ]
}

async function loadServer() {
  const error = $('server-error')
  error.hidden = true
  let config
  try {
    config = await api('/config')
  } catch {
    error.textContent = "Couldn't reach the server."
    error.hidden = false
    return
  }
  $('server-config').replaceChildren(
    ...rows(config).flatMap(([title, items]) => {
      const heading = Object.assign(document.createElement('h3'), {
        textContent: title,
      })
      const list = Object.assign(document.createElement('dl'), {
        className: 'pref-card',
      })
      for (const [label, value, env] of items) {
        const row = Object.assign(document.createElement('div'), {
          className: 'pref-row',
        })
        const term = Object.assign(document.createElement('dt'), {
          className: 'pref-text',
        })
        term.append(
          Object.assign(document.createElement('span'), {
            className: 'pref-label',
            textContent: label,
          }),
        )
        if (env)
          term.append(
            Object.assign(document.createElement('code'), { textContent: env }),
          )
        row.append(
          term,
          Object.assign(document.createElement('dd'), {
            className: 'pref-value',
            textContent: value,
          }),
        )
        list.append(row)
      }
      return [heading, list]
    }),
  )
}
