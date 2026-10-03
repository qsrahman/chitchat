// The theme button in the sidebar: System (follows the operating system), Light or Dark, remembered in this browser.
// The saved choice is applied before first paint by early/theme.js; the colors are in style.css.
import { $ } from "./core.js";

const MODES = ["system", "light", "dark"];
const LABELS = { system: "System", light: "Light", dark: "Dark" };
const ICONS = { // one 20x20 outline each: half-filled circle, sun, moon
  system: "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM10 3v14",
  light: "M10 6.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM10 2v2M10 16v2M2 10h2M16 10h2M4.3 4.3l1.4 1.4M14.3 14.3l1.4 1.4M4.3 15.7l1.4-1.4M14.3 5.7l1.4-1.4",
  dark: "M16 11.5A6.5 6.5 0 0 1 8.5 4a6.5 6.5 0 1 0 7.5 7.5z",
};

const button = $("theme-btn");
let mode = document.documentElement.dataset.theme ?? "system";

function show() {
  if (mode === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = mode;
  const text = `Theme: ${LABELS[mode]}`;
  button.querySelector(".label").textContent = text;
  button.setAttribute("aria-label", text);
  button.title = "Change theme";
  button.querySelector("path").setAttribute("d", ICONS[mode]);
}

button.onclick = () => {
  mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
  try {
    if (mode === "system") localStorage.removeItem("theme");
    else localStorage.setItem("theme", mode);
  } catch { /* storage blocked: the choice lasts until the page closes */ }
  show();
};

show();
