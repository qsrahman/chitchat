// The Settings dialog (the sidebar's gear): appearance and shortcuts, custom instructions, export and import, and what
// the server is set up with. Settings that belong to one chat (model, system prompt, temperature) are in
// settings.js; the import itself is in backup.js. The design and what is where: docs/settings-dialog.md.
import { $, api } from "./core.js";
import { closeNavIfOverlay } from "./nav.js";

const dialog = $("prefs-dialog");
const tabs = [...dialog.querySelectorAll('[role="tab"]')];

// ---- tabs ----
// A vertical tab list with the keyboard contract of the pattern: arrows move between tabs (and show them), Home and
// End jump, only the selected tab is in the tab order, and the panel is in the tab order after it.
function showTab(tab, focus = false) {
  for (const t of tabs) {
    const on = t === tab;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
    $(t.getAttribute("aria-controls")).hidden = !on;
  }
  if (focus) tab.focus();
  tab.scrollIntoView({ block: "nearest", inline: "nearest" }); // in the phone's row of tabs it may be off to the side
  if (tab.id === "tab-server") loadServer();
}
tabs.forEach((t) => (t.onclick = () => showTab(t)));
dialog.querySelector('[role="tablist"]').addEventListener("keydown", (e) => {
  const at = tabs.indexOf(document.activeElement);
  const to = { ArrowDown: at + 1, ArrowRight: at + 1, ArrowUp: at - 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[e.key];
  if (to === undefined || at < 0) return;
  e.preventDefault();
  showTab(tabs[(to + tabs.length) % tabs.length], true);
});

export function openPreferences(tabId = "tab-general") {
  $("backup-status").hidden = true; // what the last import said is not news
  loadInstructions();
  showTab($(tabId));
  closeNavIfOverlay(); // on a phone the drawer was open to reach the gear; it is in the way behind the dialog
  dialog.showModal();
}
$("prefs-btn").onclick = () => openPreferences();

// ---- General: appearance ----
// System follows the operating system; Light and Dark are remembered in this browser. early/theme.js applies the
// saved one before the first paint; the colors are in style.css.
const theme = $("pref-theme");
theme.value = document.documentElement.dataset.theme ?? "system";
theme.onchange = () => {
  if (theme.value === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme.value;
  try {
    if (theme.value === "system") localStorage.removeItem("theme");
    else localStorage.setItem("theme", theme.value);
  } catch { /* storage blocked: the choice lasts until the page closes */ }
};

// ---- General: shortcuts ----
const mod = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl+";
/** @type {[string, string[]][]} */
const SHORTCUTS = [
  ["Search chats", [`${mod}K`]],
  ["New chat", [`${mod}Shift+O`]],
  ["Send the message", ["Enter"]],
  ["New line in the message", ["Shift+Enter"]],
  ["Stop a reply", ["Esc"]],
];
$("shortcut-list").replaceChildren(...SHORTCUTS.map(([label, keys]) => {
  const row = Object.assign(document.createElement("div"), { className: "pref-row" });
  const text = Object.assign(document.createElement("span"), { className: "pref-label", textContent: label });
  const kbd = Object.assign(document.createElement("kbd"), { textContent: keys.join(" ") });
  row.append(text, kbd);
  return row;
}));

// ---- Personalization: custom instructions ----
const instructions = $("set-instructions");
const status = $("instructions-status");
let typed = false; // the box has been edited since it was filled: what arrives later must not replace it
async function loadInstructions() {
  status.textContent = "";
  typed = false;
  try {
    const { text } = await api("/custom-instructions");
    if (!typed) instructions.value = text;
  } catch {
    status.textContent = "Couldn't load them. Check your connection.";
  }
  try {
    const { default_instructions: text } = await api("/config");
    $("default-instructions-text").textContent = text || "Nothing: DEFAULT_SYSTEM_PROMPT is empty.";
  } catch { /* the details stay empty; the Server tab says what is wrong */ }
}
$("instructions-save").onclick = async (e) => {
  const button = e.currentTarget;
  button.disabled = true;
  status.classList.remove("is-error");
  try {
    await api("/custom-instructions", { method: "PUT", body: JSON.stringify({ text: instructions.value }) });
    status.textContent = "Saved.";
  } catch {
    status.textContent = "Couldn't save. Check your connection and try again.";
    status.classList.add("is-error");
  }
  button.disabled = false;
};
instructions.addEventListener("input", () => {
  typed = true;
  status.textContent = "";
});

// ---- Server: what it is set up with (read only) ----
const tokens = (n) => `${n.toLocaleString()} tokens`;
/** @param {ServerConfig} config */
function rows(config) {
  const context = config.compaction
    ? `OpenAI compacts the conversation once it passes ${tokens(config.compact_threshold)}`
    : config.history_tokens
      ? `The oldest messages are left out beyond ${tokens(config.history_tokens)}`
      : "All of the conversation is sent every time";
  return [
    ["Connection", [
      ["Endpoint", config.endpoint, "OPENAI_BASE_URL"],
      ["Default model", config.model, "OPENAI_MODEL"],
      ["Chat titles are written by", config.title_model, "TITLE_MODEL"],
    ]],
    ["Conversations", [
      ["Long conversations", context, config.compaction ? "COMPACT_THRESHOLD" : "CONTEXT_TOKENS"],
      ["Longest reply", config.max_output_tokens ? tokens(config.max_output_tokens) : "The model's own limit", "OPENAI_MAX_OUTPUT_TOKENS"],
      ["PDFs", config.pdf_input === "file" ? "Sent to the model as a file" : "Their text is sent", "OPENAI_PDF_INPUT"],
      ["Thinking summaries", config.reasoning_summaries ? "Asked for" : "Not asked for", "OPENAI_REASONING_SUMMARIES"],
    ]],
    ["Tools", [
      ["Web search", config.web_search ? "On" : "Off: add a Brave Search key to turn it on", "BRAVE_API_KEY"],
      ["Tools you can switch on", config.tools.join(", ") || "None", null],
      ["Tool calls in one reply", String(config.max_tool_calls), "MAX_TOOL_CALLS"],
    ]],
    ["Storage", [
      ["Database", config.database, "DB_PATH"],
      ["Attachments", config.attachments, "ATTACHMENTS_DIR"],
      ["Log level", config.log_level, "LOG_LEVEL"],
    ]],
  ];
}

async function loadServer() {
  const error = $("server-error");
  error.hidden = true;
  let config;
  try {
    config = await api("/config");
  } catch {
    error.textContent = "Couldn't reach the server.";
    error.hidden = false;
    return;
  }
  $("server-config").replaceChildren(...rows(config).flatMap(([title, items]) => {
    const heading = Object.assign(document.createElement("h3"), { textContent: title });
    const list = Object.assign(document.createElement("dl"), { className: "pref-card" });
    for (const [label, value, env] of items) {
      const row = Object.assign(document.createElement("div"), { className: "pref-row" });
      const term = Object.assign(document.createElement("dt"), { className: "pref-text" });
      term.append(Object.assign(document.createElement("span"), { className: "pref-label", textContent: label }));
      if (env) term.append(Object.assign(document.createElement("code"), { textContent: env }));
      row.append(term, Object.assign(document.createElement("dd"), { className: "pref-value", textContent: value }));
      list.append(row);
    }
    return [heading, list];
  }));
}
