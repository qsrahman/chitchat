# Folio: the look of the app

Chosen from the five mocks in `docs/ui-mockups.md` (the mock is `design/mockups/folio.html`). The conversation is a sheet of paper on a slightly darker desk. The model's words and the chat title are set in a serif; everything you operate is a quiet sans. One ink-blue accent.

## What changed (`app/static/style.css` only, plus the favicon colour)
- Tokens: `--bg` is the desk (and the sidebar), `--surface` the sheet, `--accent` ink blue (`#2d4f87` light, `#93b2ee` dark), `--accent-soft`, `--serif` (Iowan Old Style, Charter, Palatino, Georgia: OS fonts, no download), `--sans` starts with Avenir Next.
- `main` is the sheet: rounded, ringed, 10px off the desk. On a phone it fills the screen.
- Replies, the chat title, the new-chat greeting and the sidebar brand are serif. Code stays mono.
- The open chat in the sidebar is a small raised sheet, not an accent bar.
- `main` has a bounded grid column, so a very long title ellipsizes instead of widening the sheet.
- `--muted` (light) and the code number colour were darkened to keep 4.5:1 on the new surfaces.

## Not done yet
The mock also has a Sources panel and numbered citation chips. The app does not capture web-search citations yet (`llm.py` would need a normalized `citation` event, stored in the message `meta` and kept by `backup.py`), so that is a separate step.
