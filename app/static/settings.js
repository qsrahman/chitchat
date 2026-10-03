// The open conversation's settings (and the model list): saving them, and the chat settings dialog.
import { $, DEFAULT_SETTINGS, api, bus, state } from './core.js'

export function setSettings(settings) {
  state.settings = settings
  // The dot on the settings button means "something besides the model and the tools is customized": those have
  // their own controls in the header and the composer.
  const own = ['model', 'tools', 'reasoning_effort']
  const customized = Object.keys(DEFAULT_SETTINGS).some(
    (k) => !own.includes(k) && settings[k] !== DEFAULT_SETTINGS[k],
  )
  $('settings-btn').toggleAttribute('data-active', customized)
  bus.dispatchEvent(new Event('settings'))
}

// Save settings for the open conversation; on the new-chat screen they are held until the first message.
// PATCH replaces the whole object, so callers pass the full next settings.
export async function saveSettings(next) {
  if (state.id)
    setSettings(
      (
        await api(`/conversations/${state.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ settings: next }),
        })
      ).settings,
    )
  else setSettings(next)
}

// Dialogs that save to the server stay open until the save succeeds.
function bindSave(dlg, save) {
  const error = dlg.querySelector('.field-error')
  dlg.querySelector('form').addEventListener('submit', async (e) => {
    e.preventDefault()
    error.hidden = true
    try {
      await save()
      dlg.close('save')
    } catch {
      error.textContent = "Couldn't save. Check your connection and try again."
      error.hidden = false
    }
  })
}

// ---- the defaults chosen in Settings ----
// GET /api/defaults: the model and thinking effort for chats that pick none (the server applies them: a chat's null
// means "follow the default"), and the tools a new chat starts with (applied here, as a new chat's settings are held
// until its first message).
/** @type {Defaults} */
export let defaults = { model: null, reasoning_effort: null, tools: [] }

export async function loadDefaults() {
  try {
    defaults = await api('/defaults')
  } catch {
    /* the chat works without them; Settings reports real problems */
  }
}

/** @param {Defaults} next */
export async function saveDefaults(next) {
  defaults = await api('/defaults', {
    method: 'PUT',
    body: JSON.stringify(next),
  })
  refreshModels() // the model that is "Default (...)" may have changed
}

export const newChatSettings = () => ({
  ...DEFAULT_SETTINGS,
  tools: [...defaults.tools],
})

// ---- the model list ----
// From GET /api/models; the picker, the settings dialog and the thinking select all read it.
/** @type {ModelInfo} */
export let modelInfo = { default: null, models: [] }

export const currentModel = () => state.settings.model ?? modelInfo.default

export async function refreshModels() {
  try {
    modelInfo = await api('/models')
  } catch {
    /* keep what we have; the settings dialog reports real problems */
  }
  bus.dispatchEvent(new Event('models'))
}

/** @type {Map<string, boolean | undefined>} */
let reasoningModels = new Map() // model id -> takes reasoning effort (otherwise temperature)
function syncSettingsFields() {
  const reasoning = reasoningModels.get($('set-model').value) // "" = the default model
  $('effort-field').hidden = reasoning === false
  $('temp-field').hidden = reasoning === true // unknown model: show both, the server sends the one that applies
}
$('set-model').addEventListener('change', syncSettingsFields)

// The model and effort choices come from the list the page already has, so the dialog opens at once; the list is
// refreshed in the background and the choices rebuilt, keeping what has been picked meanwhile.
function fillModelChoices(model, effort) {
  const { default: fallback, efforts = [], models } = modelInfo
  // "" is what the Default option carries, so it needs the default model's own reasoning flag. Both lines
  // below ask for the default by id rather than trusting the order /api/models happens to use.
  reasoningModels = new Map([
    ['', models.find((m) => m.id === fallback)?.reasoning],
    ...models.map(
      (m) => /** @type {[string, boolean | undefined]} */ ([m.id, m.reasoning]),
    ),
  ])
  const options = models
    .filter((m) => m.id !== fallback)
    .map((m) => new Option(m.id, m.id))
  if (model && !reasoningModels.has(model))
    options.push(new Option(model, model)) // no longer listed
  $('set-model').replaceChildren(
    new Option(`Default (${fallback ?? '…'})`, ''),
    ...options,
  )
  $('set-effort').replaceChildren(
    new Option('Default', ''),
    ...efforts.map((e) => new Option(e, e)),
  )
  $('set-model').value = model ?? ''
  $('set-effort').value = effort ?? ''
  syncSettingsFields()
}

export function openSettings() {
  const s = state.settings
  const dialog = $('settings-dialog')
  fillModelChoices(s.model, s.reasoning_effort)
  $('set-system').value = s.system_prompt
  $('set-temp').value = s.temperature ?? ''
  $('export-row').hidden = !state.id
  if (state.id) {
    // no hrefs before there is a conversation, so nothing can ask for /conversations/null
    $('export-md').href = `/api/conversations/${state.id}/export?format=md`
    $('export-json').href = `/api/conversations/${state.id}/export?format=json`
  }
  dialog.querySelector('.field-error').hidden = true
  dialog.showModal()
  refreshModels().then(() => {
    if (dialog.open)
      fillModelChoices(
        $('set-model').value || null,
        $('set-effort').value || null,
      )
  })
}
$('settings-btn').onclick = openSettings

bindSave($('settings-dialog'), async () => {
  await saveSettings({
    ...state.settings, // keeps what the dialog doesn't show, such as the tools
    model: $('set-model').value || null,
    system_prompt: $('set-system').value.trim(),
    reasoning_effort: $('set-effort').value || null,
    temperature:
      $('set-temp').value === '' ? null : Number($('set-temp').value),
  })
})
