// Shared by the mock UIs (not part of the app): icons, the view and theme from the address, and a few toggles.
//   ?view=chat|new   which screen to show (the body gets data-view)
//   ?theme=light|dark    the colors (the root gets data-theme; without it the system's)
//   ?open=tools|model|menu|palette|settings   a menu that starts open (the body gets data-open)
// Clicking [data-toggle="x"] flips the class "x-open" on the body; clicking [data-open="x"] opens that menu (or closes
// it); clicking anywhere else closes it. [data-i="name"] becomes an icon.
const ICONS = {
  copy: 'M7 7h9v9H7zM13 7V4H4v9h3',
  check: 'M4 10l4 4 8-8',
  refresh: 'M16 10a6 6 0 1 1-1.8-4.3M16 4v3.5h-3.5',
  pencil: 'M4 16l1-4 8-8 3 3-8 8-4 1zM11 6l3 3',
  trash: 'M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10',
  file: 'M6 3h6l4 4v10H6zM12 3v4h4',
  close: 'M5 5l10 10M15 5L5 15',
  pin: 'M7 3h6l-.8 5.2L15 11H5l2.8-2.8zM10 11v6',
  archive: 'M3 5h14v3H3zM4 8v8h12V8M8 11.5h4',
  down: 'M6 8l4 4 4-4',
  up: 'M6 12l4-4 4 4',
  left: 'M12 5l-5 5 5 5',
  right: 'M8 5l5 5-5 5',
  more: 'M5 10m-1 0a1 1 0 1 0 2 0a1 1 0 1 0-2 0M10 10m-1 0a1 1 0 1 0 2 0a1 1 0 1 0-2 0M15 10m-1 0a1 1 0 1 0 2 0a1 1 0 1 0-2 0',
  sliders:
    'M3 6h8M15 6h2M3 14h2M9 14h8M11 6a2 2 0 1 0 4 0a2 2 0 1 0-4 0M5 14a2 2 0 1 0 4 0a2 2 0 1 0-4 0',
  download: 'M10 3v9M6 8.5l4 4 4-4M4 16h12',
  plus: 'M10 4v12M4 10h12',
  send: 'M10 16V4M5 9l5-5 5 5',
  stop: 'M6 6h8v8H6z',
  mic: 'M10 3a2.5 2.5 0 0 1 2.5 2.5v4a2.5 2.5 0 0 1-5 0v-4A2.5 2.5 0 0 1 10 3zM5 9.5a5 5 0 0 0 10 0M10 14.5V17',
  globe: 'M10 3a7 7 0 1 0 0 14a7 7 0 1 0 0-14M3 10h14M10 3c2.2 2 2.2 12 0 14M10 3c-2.2 2-2.2 12 0 14',
  search: 'M9 3a6 6 0 1 0 0 12a6 6 0 1 0 0-12M13.5 13.5L17 17',
  sidebar: 'M3 4h14v12H3zM8 4v12',
  gear: 'M10 7a3 3 0 1 0 0 6a3 3 0 1 0 0-6M10 2v2M10 16v2M2 10h2M16 10h2M4.3 4.3l1.4 1.4M14.3 14.3l1.4 1.4M4.3 15.7l1.4-1.4M14.3 5.7l1.4-1.4',
  wrench: 'M13 3a4 4 0 0 0-3.6 5.5L3.5 14.4a1.5 1.5 0 0 0 2.1 2.1l5.9-5.9A4 4 0 0 0 17 7l-2.3 2.3-2-.5-.5-2z',
  spark: 'M10 3l1.6 4.4L16 9l-4.4 1.6L10 15l-1.6-4.4L4 9l4.4-1.6z',
  clock: 'M10 3a7 7 0 1 0 0 14a7 7 0 1 0 0-14M10 6v4l3 2',
  calc: 'M5 3h10v14H5zM7.5 6h5M8 10h.01M10 10h.01M12 10h.01M8 13h.01M10 13h.01M12 13h.01',
  chat: 'M4 4h12v9H9l-4 3v-3H4z',
  book: 'M4 4h5a2 2 0 0 1 2 2v10a2 2 0 0 0-2-2H4zM16 4h-5a2 2 0 0 0-2 2v10a2 2 0 0 1 2-2h5z',
  link: 'M8 12l4-4M7 9.5L5.5 11a2.5 2.5 0 0 0 3.5 3.5L10.5 13M13 10.5L14.5 9A2.5 2.5 0 0 0 11 5.5L9.5 7',
  thumbup: 'M7 9v7H4V9zM7 9l3-6c1.5 0 2 1 1.7 2.5L11 8h4.3a1.5 1.5 0 0 1 1.5 1.8l-1 5A1.5 1.5 0 0 1 14.3 16H7',
  thumbdown: 'M7 11V4H4v7zM7 11l3 6c1.5 0 2-1 1.7-2.5L11 12h4.3a1.5 1.5 0 0 0 1.5-1.8l-1-5A1.5 1.5 0 0 0 14.3 4H7',
  share: 'M10 12V3M6.5 6.5L10 3l3.5 3.5M4 10v6h12v-6',
  folder: 'M3 5h5l1.5 2H17v9H3z',
  command: 'M7 7h6v6H7zM7 7V5.5A1.5 1.5 0 1 0 5.5 7zM13 7V5.5A1.5 1.5 0 1 1 14.5 7zM7 13v1.5A1.5 1.5 0 1 1 5.5 13zM13 13v1.5a1.5 1.5 0 1 0 1.5-1.5z',
  image: 'M3 4h14v12H3zM3 14l4-4 3 3 3-3 4 4M12.5 7.5h.01',
  brain: 'M8 4a2.5 2.5 0 0 0-2.5 2.5A2.5 2.5 0 0 0 4 9a2.5 2.5 0 0 0 1.5 2.3A2.5 2.5 0 0 0 8 16h4a2.5 2.5 0 0 0 2.5-4.7A2.5 2.5 0 0 0 16 9a2.5 2.5 0 0 0-1.5-2.5A2.5 2.5 0 0 0 12 4zM10 4v12',
  eye: 'M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10zM10 8a2 2 0 1 0 0 4a2 2 0 1 0 0-4',
  sun: 'M10 7a3 3 0 1 0 0 6a3 3 0 1 0 0-6M10 2v2M10 16v2M2 10h2M16 10h2M4.3 4.3l1.4 1.4M14.3 14.3l1.4 1.4M4.3 15.7l1.4-1.4M14.3 5.7l1.4-1.4',
  moon: 'M16 11.5A6.5 6.5 0 0 1 8.5 4a6.5 6.5 0 1 0 7.5 7.5z',
}
const svg = (path) =>
  `<svg viewBox="0 0 20 20" aria-hidden="true"><path d="${path}"/></svg>`
document.querySelectorAll('[data-i]').forEach((el) => {
  el.innerHTML = svg(ICONS[el.dataset.i] ?? '')
  el.classList.add('ic')
})

const q = new URLSearchParams(location.search)
if (q.get('theme')) document.documentElement.dataset.theme = q.get('theme')
document.body.dataset.view = q.get('view') || 'chat'
if (q.get('open')) document.body.dataset.open = q.get('open')

document.addEventListener('click', (e) => {
  const toggle = e.target.closest('[data-toggle]')
  if (toggle) document.body.classList.toggle(`${toggle.dataset.toggle}-open`)
  const open = e.target.closest('[data-open]')
  const name = open?.dataset.open
  if (open) {
    e.stopPropagation()
    if (document.body.dataset.open === name) delete document.body.dataset.open
    else document.body.dataset.open = name
  } else if (!e.target.closest('[data-keep-open]')) {
    delete document.body.dataset.open
  }
  const view = e.target.closest('[data-view-to]')
  if (view) document.body.dataset.view = view.dataset.viewTo
  const theme = e.target.closest('[data-theme-toggle]')
  if (theme) {
    const root = document.documentElement
    const dark =
      (root.dataset.theme ??
        (matchMedia('(prefers-color-scheme: dark)').matches
          ? 'dark'
          : 'light')) === 'dark'
    root.dataset.theme = dark ? 'light' : 'dark'
  }
})
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    document.body.dataset.open =
      document.body.dataset.open === 'palette' ? '' : 'palette'
  }
  if (e.key === 'Escape') delete document.body.dataset.open
})
