# The Settings dialog

The options had spread over four places: a *Custom instructions* button, a *Backup & import* button and a *Theme* button in the sidebar footer, and a per-chat dialog in the header, while what the server was set up with (the endpoint, whether web search was on, how long conversations are handled) was not visible anywhere. There is now one **Settings** dialog, opened from the gear at the bottom of the sidebar (it stays in the icon rail; on a phone it is in the drawer, which closes when Settings opens). The sidebar footer is down to two buttons: *Archived chats* (it switches the list, so it is not a setting) and *Settings*.

## What ChatGPT does (looked at on 2026-10-04)
Read from chatgpt.com in the built-in browser, logged out (the logged-in dialog is behind a sign-in I did not use; its sections are from OpenAI's help pages):
- **Sections, then rows.** A logged-out visitor already gets *Settings* with *General* (Appearance: System, Language: Auto-detect) and *Data controls* (three switches with a sentence each). Signed in there are more sections: General, Personalization (personality, custom instructions, memory), Data controls (export, delete), Security, Account and so on.
- **A section is a card.** A heading (16 px, weight 500, 16 px below it), then one rounded card (16 px radius, a 1 px border at 10% white, a surface a step above the page) with rows 72 to 89 px tall, 16 px padding, **the label and its one-sentence description on the left and the control on the right**: a dropdown, or a switch (a real `input` with `role="switch"`, 32 x 20 px).
- **Changes save as you make them** (there is an inline "Something went wrong while saving your preferences" line, hidden until needed); there is no Save button for switches and dropdowns.
- Same system font stack as the rest of the page, 24 px page title.

## What ChitChat took from it, and what it did not
Taken: sections as titled cards; rows with the label and a muted sentence on the left and the control on the right; dropdowns and buttons that act at once; a left list of sections that is the dialog's navigation (ChatGPT's signed-in dialog has the same); inline errors, no alert boxes.
Not taken: language (the interface is English), a Security or Account section (there is no sign-in until phase 9).
Added, because ChitChat has what ChatGPT keeps server side: a **Server** tab that shows the effective configuration, read only.

## The four sections
| Section | Holds |
|---|---|
| **General** | *Appearance* (System, Light, Dark: it applies at once and is remembered in this browser; the old Theme button is gone); *New chats* (the defaults, below); *Keyboard shortcuts* (a list for this platform: search, new chat, send, new line, stop); a note that one chat can differ (the sliders button in its header sets that chat's own model, system prompt and temperature) |
| **Personalization** | *Custom instructions*: the text sent with every chat, with a Save button and a "Saved." line (a failed save says so and keeps the text; typed text is not replaced by a late load, and survives switching tabs); *Built-in instructions*: a disclosure showing the text of `DEFAULT_SYSTEM_PROMPT` that is always sent first, read only |
| **Data controls** | *Export*: with attachments (zip), all chats (JSON), Markdown (zip); *Import*: the file picker and what the import did (`docs/backup.md`); *Storage*: what is kept, delete unused files, delete old archived chats (`docs/storage.md`) |
| **Server** | Read only, from `GET /api/config`: endpoint (scheme and host only), default model, title model, how long conversations are handled (compaction or trimming and at what size), longest reply, PDF mode, thinking summaries, web search on or off and which tools exist, tool calls per reply, database path, attachments folder, log level. Under each label, the environment variable that sets it. It says to edit `.env` and restart to change them |

`GET /api/config` never returns a secret: a key is only "on" or "off", and the endpoint has no credentials, path or query (tested with a URL that has all three).

## The design in the page
- **Layout:** a dialog 48 rem wide and at most 36 rem tall, a header with the title and a close button, a list of the four sections on the left (12 rem) and the panel on the right, which is the part that scrolls. On a phone (up to 640 px) the list is a row of tabs above the panel, the dialog fills the screen, rows wrap, and long values drop under their label.
- **Look:** the app's own tokens (the warm surfaces, the teal accent as the selected tab's edge, the radius scale), not ChatGPT's colours; headings and card proportions follow what was measured above.
- **Keyboard and screen readers:** the sections are a real tab list (`role="tablist"`, vertical): arrows (and Home and End) move between tabs and show them, only the selected tab is in the tab order, the panel itself is focusable so it can be scrolled with the keyboard, and the dialog is a native `<dialog>` (focus trapped, Escape closes, the focus returns to the gear). Every control has a visible label and its description is linked with `aria-describedby`. axe passes on all four tabs, light and dark, and on a phone.
- **Files:** `preferences.js` (the dialog), `backup.js` (the import, unchanged apart from where it is), the markup in `index.html`, the `.pref-*` rules in `style.css`.

## Defaults for new chats (added later)
The first version left these out: the model came from `.env` only, and I did not want two places that can disagree. They are now app-wide settings in the database (`app_settings`, key `defaults`; `GET`/`PUT /api/defaults`; `store.Defaults`), and the way the two places agree is that **a chat's own setting wins, then this default, then the server's `.env`**:

| Row | Control | Effect |
|---|---|---|
| Model | dropdown: *Server default (<OPENAI_MODEL>)* or any listed model | Used by every chat that picks none (a chat's model of `null` means "follow the default"), so existing chats follow it too. The header button and the chat settings' "Default (...)" show it (`/api/models` leads with it; `server_default` is the `.env` one) |
| Thinking effort | dropdown: Auto or an effort | Used for a thinking model when the chat sets none |
| Web search | switch (`role="switch"`, 32 x 20 px) | New chats start with it on. Disabled, with the reason, when the server has no search key |

They save as they change, one at a time and each built from the last (two quick changes would otherwise undo each other: the save replaces all three), and a failed save says so inline and puts the control back. A new chat's tools are applied by the page (its settings are held until the first message; the new-chat screen follows a change at once), and by the server for a chat created with no settings. They are in the backup file (`docs/backup.md`), and the title model follows the default on a custom endpoint (`docs/round-10.md`). Not done: only web search is a switch (the other tools stay as the API set them, and are switched per chat from the tools menu, which now holds web search as well).

Settings now also opens on the tab it was last left on (kept in this browser's `localStorage`).

## Not done
- Language (the interface is English).
- Editing the server settings from the page (it would need to write `.env` and restart).

Tests: `tests/ui/test_prefs_ui.py` (the tabs and their keyboard, each section, closing, the shortcuts, saving and failing to save, the Server tab and its failure, the phone and short-window layouts), `tests/ui/test_theme_ui.py`, `tests/ui/test_backup_ui.py`, `tests/ui/test_a11y_ui.py`, `tests/test_config_api.py`.

## Also found while testing it
Two older UI tests were flaky and are fixed: the Server-tab test measured the panel before the server's answer had filled it, and an Arabic-text test sent a second message while the first reply was still streaming (Enter then *stops* the reply, by design). A load run of 12 passed after the fixes.
