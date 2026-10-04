# UI review: simplify and polish

A look at the running app (dark and light, desktop and phone-sized window, the empty state, a reply with code, math and reasoning, the sidebar with a hover, the model menu and the chat dialog) found a calm, readable, ChatGPT-like layout whose weak spots were structural: the same thing reachable from several places, and per-chat controls scattered. Eleven changes followed, in three commits. This file records what each did.

## 1 to 4: one menu for a chat, one dialog language
- **The ⋯ chat menu** (`chat-menu.js`, `#chat-menu`) replaces the header's Download button and sliders button, and the four icons that appeared on every sidebar row (pin, rename, archive, delete). It has the same items wherever it is opened, in groups: *Instructions for this chat…* (only for the open chat), *Pin* or *Unpin* and *Rename…*, *Download as Markdown* and *Download as JSON*, *Archive* or *Unarchive* and *Delete…* (red). A new chat, which does not exist yet, has only the instructions; an archived chat has no *Pin*, as before. It is a popover placed from script (CSS anchor positioning is not widely available), right-aligned under its button, flipped above when there is no room, with the arrow, Home, End and Escape keys of the model menu and focus returned to the button; the button says `aria-expanded`. The header's menu asks the server for the chat when it opens, so it is right even when the chat is not in the list yet or on its page.
- **The dot** that says "this chat has instructions or a temperature of its own" moved to the ⋯ button.
- **The row's title has the room back**: one ⋯ instead of four icons (it shows on hover or focus, always on a touch screen).
- **"Chat settings" is "Instructions for this chat"**, in the menu, the model menu's last item and the dialog title, so it is not confused with *Settings* (the gear). The dialog is in the card-and-row language of Settings (a card for the system prompt, a card for temperature and reasoning effort, each row with its own description), has no model select (the model is chosen in the header, which was the same choice twice) and no export links (they are in the menu, where they were also duplicated). Which of temperature and effort it shows follows the chat's model, as before; it still has Save and Cancel, since its fields are text.
- **The gear in the rail is a gear** (it was spokes around a circle and read as a sun, which was the old Theme button's icon).

Tests: `tests/ui/test_chat_menu_ui.py` (one button per row, the groups, the open chat's extras, the keyboard, aria-expanded, choosing closes it, archived, delete asks first, on a phone) and `test_each_dialog` / `test_the_chat_menus` in the accessibility test. The tests that used the old buttons use `chat_menu`, `open_chat_settings` and `row_action` (`tests/ui/test_chat_ui.py`).

### A finding on the way: stale modules
After an update the browser reused some of the page's JavaScript modules from its cache and mixed old and new ones, which fails at load ("does not provide an export named ..."): static files had no `Cache-Control`, so browsers guessed a lifetime from `Last-Modified`. The page's own files (everything outside `/api/`) now carry `Cache-Control: no-cache`: the browser keeps them but asks first, and the `ETag` answers 304 when nothing changed (`tests/test_security_headers.py`).

## 5 to 8: how a conversation reads
- **The line under a reply** puts the buttons together first (copy, regenerate, another model) and the model name and token counts after them as one quiet group, `reply-meta`, instead of in the middle of the buttons. Older replies still show the line only on hover.
- **One disclosure marker.** The reasoning block and the tool-call lines used the browser's own ▶ triangle while everything else on the page uses chevrons. Both now draw the same chevron, which turns down when open and points the other way in right-to-left text. A tool call with nothing to open has none.
- **Spacing.** Your message and the reply to it are one exchange, so they sit closer (your message's action row is 24px instead of 28 and its margin 0.5rem instead of 1.25) than a reply and your next message: about 34px against 52px.
- **Web search says so in words.** When the globe is on, "Search" appears beside it, in addition to the accent color. **No background**: a highlighted button was taken out earlier on purpose, and the tests that kept it out stay (the old rule "on is color alone, no label" became "on is color and a word, no background"). The word is in the text color, not the accent, because on the hover background the accent is 4.15:1, below the 4.5:1 the accessibility test asks for. The button's name is "Web search" on or off.

Tests: `tests/ui/test_polish_ui.py` (the order and contents of the line, the chevron turning, the spacing) and `tests/ui/test_search_ui.py` (the label and the missing background).

## 9 to 11: identity, the new-chat screen, the sidebar
- **Recent chats under the composer** of a new chat: the latest three (not archived), one click to pick up where you left off, `nav#recent` filled by `list.js` from the list it already has, hidden once a conversation is open and in the archive view. The new-chat screen was otherwise a greeting and a box.
- **The accent is used on purpose.** The model name in the header is the accent (it turns to the ink on hover: on the hover background the accent is 4.15:1, under the 4.5:1 text needs), next to the accent that marks the open chat, the focus rings and the Search label's globe. Everything else stays quiet: that restraint is what makes the page look as good as it does.
- **The composer's shadow** in the light theme was Open Props' `shadow-2`, which read as a second outline next to the border; it is now a faint two-layer shadow (checked by eye in both themes; the dark one is as it was in effect).
- **The sidebar's width** is yours: drag its edge, or focus it (it is a `role="separator"` with a value, the "window splitter" pattern) and use the left and right arrows (16px), Home and End. 224 to 480px, kept in this browser (`nav.js`, `--sidebar-w`). Only the open, wide sidebar has the edge; on a phone the sidebar is a drawer and closed it is a rail.

Tests: `tests/ui/test_polish_ui.py` (the recent chats, the resizing by keyboard and by dragging, the limits, where the edge exists, the model name's colour). The tests that clicked a sidebar link by its name on the new-chat screen now say `#conversations`, because the same title is also a recent chat there.

## What was left alone
The Settings dialog (cards, tabs, switches), the model menu, the code blocks and math, and the phone layout (nothing overflows).
