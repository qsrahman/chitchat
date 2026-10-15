// The composer's controls: thinking effort and the tools menu.
import { $, api, bus, state, textEl } from './core.js'
import { showNote } from './composer.js'
import {
  capital,
  currentModel,
  defaultEffortLabel,
  defaults,
  modelInfo,
  saveSettings,
} from './settings.js'

// ---- thinking effort ----
// A select in the composer, shown for models that take a reasoning effort (the others take a temperature, which
// stays in the chat settings). The first choice stores null: "Auto", or the default chosen in Settings, which it is
// named after ("Medium", not "Default (Medium)": the select shows the choice made, and a chat that picks none gets
// that one). The list then has no second "Medium": picking it would mean the same, except that it would stay when
// the default changes, and a chat saved with that explicit choice shows as following it.
const effortSelect = $('effort')

function syncEffort() {
  const efforts = modelInfo.efforts ?? []
  $('effort-wrap').hidden = !modelInfo.models.find(
    (m) => m.id === currentModel(),
  )?.reasoning
  const group = document.createElement('optgroup')
  group.label = 'Thinking effort'
  group.append(
    new Option(defaultEffortLabel('Auto'), ''),
    ...efforts
      .filter((e) => e !== defaults.reasoning_effort)
      .map((e) => new Option(capital(e), e)),
  )
  effortSelect.replaceChildren(group)
  const chosen = state.settings.reasoning_effort
  effortSelect.value =
    chosen === defaults.reasoning_effort ? '' : (chosen ?? '')
  effortSelect.title = `Thinking effort: ${effortSelect.selectedOptions[0].text}${
    effortSelect.value === '' && defaults.reasoning_effort
      ? ' (the default from Settings)'
      : ''
  }`
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

// ---- tools menu ----
// Every tool the server offers, a checkbox each, saved per conversation.
const toolsMenu = $('tools-menu')

function syncToolsMenu() {
  const on = state.tools.filter((t) => state.settings.tools.includes(t.name))
  const button = $('tools-btn')
  button.hidden = !state.tools.length
  button.toggleAttribute('data-active', on.length > 0)
  button.title = on.length
    ? `Tools: ${on.map((t) => t.label).join(', ')}`
    : 'Tools'
  for (const box of $('tools-list').querySelectorAll('input'))
    box.checked = state.settings.tools.includes(box.value)
}

function renderToolsMenu() {
  $('tools-list').replaceChildren(
    ...state.tools.map((t) => {
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

bus.addEventListener('settings', () => {
  syncEffort()
  syncToolsMenu()
})
bus.addEventListener('models', syncEffort)

// The tools the server offers; until they arrive (or if they never do) the button stays hidden.
export function loadTools() {
  return api('/tools')
    .then((tools) => {
      state.tools = tools
      syncToolsMenu()
    })
    .catch(() => {})
}
