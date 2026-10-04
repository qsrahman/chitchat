// The composer's controls: thinking effort, the web search toggle and the tools menu.
import { $, WEB_SEARCH, api, bus, state, textEl } from './core.js'
import { showNote } from './composer.js'
import { currentModel, modelInfo, saveSettings } from './settings.js'

// ---- thinking effort ----
// A select in the composer, shown for models that take a reasoning effort (the others take a temperature, which
// stays in the chat settings). "Auto" stores null: the model's own default.
const effortSelect = $('effort')

function syncEffort() {
  const efforts = modelInfo.efforts ?? []
  $('effort-wrap').hidden = !modelInfo.models.find(
    (m) => m.id === currentModel(),
  )?.reasoning
  if (effortSelect.options.length !== efforts.length + 1) {
    const group = document.createElement('optgroup')
    group.label = 'Thinking effort'
    group.append(
      new Option('Auto', ''),
      ...efforts.map((e) => new Option(e[0].toUpperCase() + e.slice(1), e)),
    )
    effortSelect.replaceChildren(group)
  }
  effortSelect.value = state.settings.reasoning_effort ?? ''
  effortSelect.title = `Thinking effort: ${effortSelect.selectedOptions[0].text}`
  $('effort-wrap').title = effortSelect.title
  $('effort-wrap').toggleAttribute('data-active', effortSelect.value !== '')
}

effortSelect.onchange = async () => {
  try {
    await saveSettings({
      ...state.settings,
      reasoning_effort: effortSelect.value || null,
    })
  } catch {
    syncEffort()
    showNote(
      "Couldn't change the thinking effort. Check your connection and try again.",
    )
  }
}

// ---- web search toggle ----
// Always shown; it is disabled while the server has no search tool configured (a Brave key). On or off is a
// per-conversation setting.
const searchOn = () => state.settings.tools.includes(WEB_SEARCH)

function syncSearchToggle() {
  const toggle = $('search-toggle')
  const tool = state.tools.find((t) => t.name === WEB_SEARCH)
  // The tool names itself; the page's own wording stands in until the list arrives (or if it never does).
  const label = tool?.label ?? toggle.getAttribute('aria-label')
  toggle.disabled = !tool
  toggle.setAttribute('aria-pressed', String(!!tool && searchOn()))
  toggle.setAttribute('aria-label', label)
  toggle.title = !tool
    ? `${label} is unavailable: set BRAVE_API_KEY on the server`
    : `${label}: ${searchOn() ? 'on' : 'off'}`
}

// ---- tools menu ----
// The tools besides web search (which has the globe): a checkbox each, saved per conversation like the search toggle.
const toolsMenu = $('tools-menu')
const otherTools = () => state.tools.filter((t) => t.name !== WEB_SEARCH)

function syncToolsMenu() {
  const on = otherTools().filter((t) => state.settings.tools.includes(t.name))
  const button = $('tools-btn')
  button.hidden = !otherTools().length
  button.toggleAttribute('data-active', on.length > 0)
  button.title = on.length
    ? `Tools: ${on.map((t) => t.label).join(', ')}`
    : 'Tools'
  for (const box of $('tools-list').querySelectorAll('input'))
    box.checked = state.settings.tools.includes(box.value)
}

function renderToolsMenu() {
  $('tools-list').replaceChildren(
    ...otherTools().map((t) => {
      const row = document.createElement('label')
      row.className = 'tool-row'
      const box = Object.assign(document.createElement('input'), {
        type: 'checkbox',
        value: t.name,
      })
      const text = document.createElement('span')
      text.className = 'tool-text'
      text.append(
        textEl('span', t.label, 'menu-name'),
        textEl('span', t.hint, 'tool-hint'),
      )
      box.onchange = async () => {
        const tools = box.checked
          ? [...state.settings.tools, t.name]
          : state.settings.tools.filter((n) => n !== t.name)
        try {
          await saveSettings({ ...state.settings, tools })
        } catch {
          box.checked = !box.checked
          showNote(
            `Couldn't change ${t.label}. Check your connection and try again.`,
          )
        }
      }
      row.append(box, text)
      return row
    }),
  )
  syncToolsMenu()
}

toolsMenu.addEventListener('beforetoggle', (e) => {
  if (e.newState === 'open') renderToolsMenu()
})
toolsMenu.addEventListener('toggle', (e) => {
  if (e.newState !== 'open') return
  const r = $('tools-btn').getBoundingClientRect() // above the button, as the composer is at the bottom of the page
  const top = r.top - toolsMenu.offsetHeight - 8
  toolsMenu.style.top = `${top >= 8 ? top : r.bottom + 8}px`
  toolsMenu.style.left = `${Math.max(8, Math.min(r.left, innerWidth - toolsMenu.offsetWidth - 8))}px`
  toolsMenu.querySelector('input')?.focus()
})

$('search-toggle').onclick = async () => {
  const tools = searchOn()
    ? state.settings.tools.filter((t) => t !== WEB_SEARCH)
    : [...state.settings.tools, WEB_SEARCH]
  try {
    await saveSettings({ ...state.settings, tools })
  } catch {
    showNote("Couldn't change web search. Check your connection and try again.")
  }
}

bus.addEventListener('settings', () => {
  syncEffort()
  syncSearchToggle()
  syncToolsMenu()
})
bus.addEventListener('models', syncEffort)

// The tools the server offers; until they arrive (or if they never do) the toggles stay disabled or hidden.
export function loadTools() {
  return api('/tools')
    .then((tools) => {
      state.tools = tools
      syncSearchToggle()
      syncToolsMenu()
    })
    .catch(() => {})
}
