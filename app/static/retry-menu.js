// "Try again with another model": a menu of the models, opened from the button next to Regenerate (or Retry). Picking
// one runs that reply again with it, for that reply only; the conversation keeps its own model.
import { $ } from "./core.js";
import { modelRow, modelTags, menuKeys } from "./model-menu.js";
import { modelInfo, refreshModels } from "./settings.js";

const menu = $("retry-menu");
/** @type {HTMLElement | null} */
let anchor = null;
/** @type {((model: string) => void) | null} */
let onPick = null;

function render() {
  $("retry-list").replaceChildren(...modelInfo.models.map((m) => {
    const row = modelRow(m.id, modelTags(m), null);
    row.onclick = () => {
      menu.hidePopover(); // the browser returns the focus to the button
      onPick?.(m.id);
    };
    return row;
  }));
  if (!modelInfo.models.length) {
    $("retry-list").replaceChildren(Object.assign(document.createElement("p"), {
      className: "menu-note", textContent: "No models are listed by your provider right now.",
    }));
  }
}

// Under the button, or above it when there is no room below (the buttons are at the bottom of a reply).
function place() {
  if (!anchor) return;
  const r = anchor.getBoundingClientRect();
  const below = innerHeight - r.bottom;
  menu.style.top = `${below >= menu.offsetHeight + 12 ? r.bottom + 6 : Math.max(8, r.top - menu.offsetHeight - 6)}px`;
  menu.style.left = `${Math.max(8, Math.min(r.left, innerWidth - menu.offsetWidth - 8))}px`;
}

export function openRetryMenu(button, pick) {
  anchor = button;
  onPick = pick;
  render();
  menu.showPopover();
}

menu.addEventListener("toggle", async (e) => {
  anchor?.setAttribute("aria-expanded", String(e.newState === "open"));
  if (e.newState !== "open") return;
  place();
  menu.querySelector("button")?.focus();
  await refreshModels(); // the list may have changed since the page loaded
  if (menu.matches(":popover-open")) {
    const focused = document.activeElement?.textContent;
    render();
    place();
    [...menu.querySelectorAll("button")].find((b) => b.textContent === focused)?.focus();
  }
});
menuKeys(menu);
