// The drawer: the sidebar opens and closes (a rail of icons on a wide screen, an overlay on a phone).
import { $ } from './core.js'

// The sidebar starts closed. On narrow screens it is an overlay, so choosing something closes it.
export function setNavOpen(open) {
  document.body.classList.toggle('nav-open', open)
  $('scrim').hidden = !open
  const label = open ? 'Hide conversations' : 'Show conversations'
  for (const toggle of /** @type {NodeListOf<HTMLElement>} */ (
    document.querySelectorAll('.nav-toggle')
  )) {
    toggle.setAttribute('aria-expanded', String(open))
    toggle.setAttribute('aria-label', label)
    toggle.title = label
  }
}
export function closeNavIfOverlay() {
  if (matchMedia('(max-width: 760px)').matches) setNavOpen(false)
}
document
  .querySelectorAll('.nav-toggle')
  .forEach((/** @type {HTMLElement} */ b) => {
    b.onclick = () => setNavOpen(!document.body.classList.contains('nav-open'))
  })
$('scrim').onclick = () => setNavOpen(false)

// ---- the width of the sidebar ----
// Dragged by its edge, or with the arrow keys when the edge has the focus (a "window splitter"); kept in this browser.
// Only the wide layout has it: on a phone the sidebar is a drawer, and closed it is the rail.
const MIN_WIDTH = 224
const MAX_WIDTH = 480
const handle = $('sidebar-resize')

/** @param {number} px */
function setWidth(px, save = false) {
  const width = Math.round(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, px)))
  document.documentElement.style.setProperty('--sidebar-w', `${width}px`)
  handle.setAttribute('aria-valuenow', String(width))
  if (!save) return
  try {
    localStorage.setItem('sidebarWidth', String(width))
  } catch {
    /* storage blocked: the width lasts until the page closes */
  }
}
try {
  const saved = Number(localStorage.getItem('sidebarWidth'))
  if (saved) setWidth(saved)
} catch {
  /* storage blocked: the default width */
}

handle.addEventListener('pointerdown', (e) => {
  handle.setPointerCapture(e.pointerId)
  const move = (/** @type {PointerEvent} */ m) => setWidth(m.clientX)
  const stop = () => {
    handle.removeEventListener('pointermove', move)
    handle.removeEventListener('pointerup', stop)
    handle.removeEventListener('pointercancel', stop)
    setWidth(Number(handle.getAttribute('aria-valuenow')), true)
  }
  handle.addEventListener('pointermove', move)
  handle.addEventListener('pointerup', stop)
  handle.addEventListener('pointercancel', stop)
})
handle.addEventListener('keydown', (e) => {
  const now = Number(handle.getAttribute('aria-valuenow'))
  const to = {
    ArrowLeft: now - 16,
    ArrowRight: now + 16,
    Home: MIN_WIDTH,
    End: MAX_WIDTH,
  }[e.key]
  if (to === undefined) return
  e.preventDefault()
  setWidth(to, true)
})
