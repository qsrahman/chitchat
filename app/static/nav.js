// The drawer: the sidebar opens and closes (a rail of icons on a wide screen, an overlay on a phone).
import { $ } from "./core.js";

// The sidebar starts closed. On narrow screens it is an overlay, so choosing something closes it.
export function setNavOpen(open) {
  document.body.classList.toggle("nav-open", open);
  $("scrim").hidden = !open;
  const label = open ? "Hide conversations" : "Show conversations";
  for (const toggle of /** @type {NodeListOf<HTMLElement>} */ (document.querySelectorAll(".nav-toggle"))) {
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", label);
    toggle.title = label;
  }
}
export function closeNavIfOverlay() {
  if (matchMedia("(max-width: 760px)").matches) setNavOpen(false);
}
document.querySelectorAll(".nav-toggle").forEach((/** @type {HTMLElement} */ b) => {
  b.onclick = () => setNavOpen(!document.body.classList.contains("nav-open"));
});
$("scrim").onclick = () => setNavOpen(false);
