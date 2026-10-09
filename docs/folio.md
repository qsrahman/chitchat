# Folio: the look of the app

Chosen from the five mocks in `docs/ui-mockups.md` (the mock is `design/mockups/folio.html`). The conversation is a sheet of paper on a slightly darker desk. The model's words and the chat title are set in a serif; everything you operate is a quiet sans. One ink-blue accent.

## What changed (`app/static/style.css` only, plus the favicon colour)
- Tokens: `--bg` is the desk (and the sidebar), `--surface` the sheet, `--accent` ink blue (`#2d4f87` light, `#93b2ee` dark), `--accent-soft`, `--serif` (Iowan Old Style, Charter, Palatino, Georgia: OS fonts, no download), `--sans` starts with Avenir Next.
- `main` is the sheet: rounded, ringed, 10px off the desk. On a phone it fills the screen.
- Replies, the chat title, the new-chat greeting and the sidebar brand are serif. Code stays mono.
- The open chat in the sidebar is a small raised sheet, not an accent bar.
- `main` has a bounded grid column, so a very long title ellipsizes instead of widening the sheet.
- `--muted` (light) and the code number colour were darkened to keep 4.5:1 on the new surfaces.

## Checked by eye (light mode and a 375px phone)
- The new-chat screen's "Pick up where you left off" list is serif with the age on the right ("4 hours ago", "yesterday"; the date past a week). Found on the way: a long title stretched the grid column and pushed the ages out of view (the list's column is now `minmax(0, 1fr)`).
- On a phone the header was too tight with the Sources button: the chat title shrank to one letter. The model name now stops at 6rem, the button shows only the site letters (two of them) and the title keeps about 75px with sources, 135px without.
- Left out of the mock on purpose: the time-of-day greeting (it needs the user's name, which the app doesn't have, and the heading is what every test and screen reader finds), a Search chip in the composer (web search is already one switch in the Tools menu and in Settings; a second place to flip it would need to stay in step with both), and the "can be wrong" footnote under the composer.

## Sources panel and numbered chips (`app/static/sources.js`)
- No backend change: web search and page reading already save what they found in the message's tool metadata (`display.results` of `web_search`, `display.url`/`title` of `fetch_url`), and backups keep it. `tools-ui.js` records each finished call on its message element (`_calls`) and sends a `sources` notice; `sources.js` reads the list from those, so it is always what the messages on screen carry (a different version of a reply shows its own).
- One page is one source however often it was found (address without `#fragment` and trailing slash). Numbers follow the order found in the chat.
- A link in a reply that points at a source becomes a chip showing its number (accessible name "Source 2: title"); other links stay links. The model already cites as markdown links (`app/tools/brave.py` guidance), so there is no new instruction. Click a chip to open the panel at its card; ctrl/cmd/shift-click still opens the link.
- The header shows "N sources" with up to three site letters when the chat has any; it toggles the panel, a third grid column (a drawer over the page on a phone). Escape or the close button closes it.
- Only web links are listed (`isWebUrl`), cards open in a new tab with `rel="noopener noreferrer"`, and there are no favicons: that would be a request to every site found. Each site gets a letter in a colour from its name.
- Tests: `tests/ui/test_sources_ui.py`, and the panel is in the axe checks.

## Not done
The mock's "Searched the web" notes are the existing tool lines. Citations from OpenAI's own web search are not captured (the app uses Brave).
