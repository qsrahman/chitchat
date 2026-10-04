// The open conversation's settings (and the model list): saving them, and the chat settings dialog.
import { $, DEFAULT_SETTINGS, api, bus, state, thread } from './core.js'

export function setSettings(settings) {
  state.settings = settings
  // The dot on the chat menu button means "something besides the model and the tools is customized": those have
  // their own controls in the header and the composer.
  const own = ['model', 'tools', 'reasoning_effort']
  const customized = Object.keys(DEFAULT_SETTINGS).some(
    (k) => !own.includes(k) && settings[k] !== DEFAULT_SETTINGS[k],
  )
  $('chat-menu-btn').toggleAttribute('data-active', customized)
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

// The fields of the dialog that depend on the model: a thinking model takes a reasoning effort, the others a
// temperature (an unlisted model shows both: the server sends the one that applies).
function syncSettingsFields() {
  const reasoning = modelInfo.models.find(
    (m) => m.id === currentModel(),
  )?.reasoning
  $('effort-field').hidden = reasoning === false
  $('temp-field').hidden = reasoning === true
}

// What this chat has used so far, from the token counts on the replies on the page (so: the version being read, not
// others), for endpoints that report them.
function showUsageTotal() {
  const sum = { input_tokens: 0, output_tokens: 0 }
  for (const el of /** @type {MessageEl[]} */ ([...thread.children])) {
    sum.input_tokens += el._usage?.input_tokens ?? 0
    sum.output_tokens += el._usage?.output_tokens ?? 0
  }
  const total = $('usage-total')
  total.hidden = !(sum.input_tokens || sum.output_tokens)
  total.textContent = `Tokens in the replies shown: ${sum.input_tokens.toLocaleString()} in, ${sum.output_tokens.toLocaleString()} out.`
}

// The chat's own settings (the chat menu, and the model menu's last item): what to tell the model and how it samples.
// The model itself is chosen in the header, so this dialog only needs the model list to know which fields apply.
export function openSettings() {
  const s = state.settings
  const dialog = $('settings-dialog')
  $('set-effort').replaceChildren(
    new Option('Default', ''),
    ...(modelInfo.efforts ?? []).map((e) => new Option(e, e)),
  )
  $('set-effort').value = s.reasoning_effort ?? ''
  $('set-system').value = s.system_prompt
  $('set-temp').value = s.temperature ?? ''
  syncSettingsFields()
  showUsageTotal()
  dialog.querySelector('.field-error').hidden = true
  dialog.showModal()
}

bindSave($('settings-dialog'), async () => {
  await saveSettings({
    ...state.settings, // keeps what the dialog doesn't show: the model and the tools
    system_prompt: $('set-system').value.trim(),
    reasoning_effort: $('set-effort').value || null,
    temperature:
      $('set-temp').value === '' ? null : Number($('set-temp').value),
  })
})
