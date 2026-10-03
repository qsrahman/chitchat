// The model picker in the header: a menu to switch the conversation's model.
import { $, ICONS, bus, state } from "./core.js";
import { currentModel, modelInfo, openSettings, refreshModels, saveSettings } from "./settings.js";

// ---- model picker ----
// The header button shows the model this conversation uses and opens a menu to switch it. null in the
// settings means "the default", so choosing the default row stores null and keeps following it.
const modelBtn = $("model-btn");
const modelMenu = $("model-menu");

function syncModelButton() {
  const name = currentModel();
  $("model-name").textContent = name ?? "Model";
  modelBtn.setAttribute("aria-label", name ? `Model: ${name}` : "Model");
  modelBtn.title = name ? `Model: ${name}` : "Model";
}

// One row of a model list: the name and its tags. The picker's rows are radios, one checked; the "try again" menu's
// are plain items (checked: null).
export function modelRow(id, tags, checked = id === currentModel()) {
  const row = document.createElement("button");
  row.type = "button";
  row.setAttribute("role", checked === null ? "menuitem" : "menuitemradio");
  if (checked !== null) row.setAttribute("aria-checked", String(checked));
  row.className = "menu-item";
  row.innerHTML = `<svg class="check" viewBox="0 0 20 20" aria-hidden="true"><path d="${ICONS.check}"/></svg>` +
    '<span class="menu-name"></span>' + tags.map(() => '<span class="menu-tag"></span>').join("");
  row.querySelector(".menu-name").textContent = id;
  row.querySelectorAll(".menu-tag").forEach((el, i) => (el.textContent = tags[i]));
  row.onclick = () => chooseModel(id);
  return row;
}

// The tags of a model in the lists: the default one, and those that think.
export const modelTags = (m) => [m.id === modelInfo.default && "default", m.reasoning && "reasoning"].filter(Boolean);

function renderModelMenu() {
  const saved = state.settings.model;
  const rows = modelInfo.models.map((m) => modelRow(m.id, modelTags(m)));
  if (saved && !modelInfo.models.some((m) => m.id === saved)) rows.push(modelRow(saved, ["not listed"]));
  $("model-list").replaceChildren(...rows);
}

async function chooseModel(id) {
  const error = modelMenu.querySelector(".field-error");
  error.hidden = true;
  const next = { ...state.settings, model: id === modelInfo.default ? null : id };
  try {
    await saveSettings(next);
    modelMenu.hidePopover(); // the browser returns focus to the button
  } catch {
    error.textContent = "Couldn't switch model. Check your connection and try again.";
    error.hidden = false;
  }
}

modelMenu.addEventListener("beforetoggle", (e) => {
  if (e.newState !== "open") return;
  modelMenu.querySelector(".field-error").hidden = true;
  renderModelMenu();
});
modelMenu.addEventListener("toggle", async (e) => {
  if (e.newState !== "open") return;
  const r = modelBtn.getBoundingClientRect(); // under the button, kept inside the viewport
  modelMenu.style.top = `${r.bottom + 6}px`;
  modelMenu.style.left = `${Math.max(8, Math.min(r.left, innerWidth - modelMenu.offsetWidth - 8))}px`;
  (modelMenu.querySelector('[aria-checked="true"]') ?? modelMenu.querySelector("button"))?.focus();
  await refreshModels(); // the list may have changed since the page loaded
  if (modelMenu.matches(":popover-open")) {
    const focused = document.activeElement?.textContent;
    renderModelMenu();
    [...modelMenu.querySelectorAll("button")].find((b) => b.textContent === focused)?.focus();
  }
});
// A menu's keyboard contract: arrows, Home and End move between items; Tab leaves; Escape is the popover's own.
export function menuKeys(menu) {
  menu.addEventListener("keydown", (e) => {
    const items = [...menu.querySelectorAll('[role^="menuitem"]')];
    const i = items.indexOf(document.activeElement);
    const target = { ArrowDown: (i + 1) % items.length, ArrowUp: (i - 1 + items.length) % items.length, Home: 0, End: items.length - 1 }[e.key];
    if (target !== undefined) {
      e.preventDefault();
      items[target].focus();
    } else if (e.key === "Tab") menu.hidePopover();
  });
}
menuKeys(modelMenu);
$("more-settings").onclick = () => { modelMenu.hidePopover(); openSettings(); };

bus.addEventListener("settings", syncModelButton);
bus.addEventListener("models", syncModelButton);
