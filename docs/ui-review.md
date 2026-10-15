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
- **Web search says so in words.** When the globe is on, "Search" appears beside it, in addition to the accent color. **No background**: a highlighted button was taken out earlier on purpose, and the tests that kept it out stay (the old rule "on is color alone, no label" became "on is color and a word, no background"). The word is in the text color, not the accent, because on the hover background the accent is 4.15:1, below the 4.5:1 the accessibility test asks for. The button's name was "Web search" on or off. *Later reversed twice: the word went out again, and then the globe went too (next section).*

Tests: `tests/ui/test_polish_ui.py` (the order and contents of the line, the chevron turning, the spacing) and `tests/ui/test_search_ui.py` (the label and the missing background).

## 9 to 11: identity, the new-chat screen, the sidebar
- **Recent chats under the composer** of a new chat: the latest three (not archived), one click to pick up where you left off, `nav#recent` filled by `list.js` from the list it already has, hidden once a conversation is open and in the archive view. The new-chat screen was otherwise a greeting and a box.
- **The accent is used on purpose.** The model name in the header is the accent (it turns to the ink on hover: on the hover background the accent is 4.15:1, under the 4.5:1 text needs), next to the accent that marks the open chat, the focus rings and the Tools wrench when a tool is on. Everything else stays quiet: that restraint is what makes the page look as good as it does.
- **The composer's shadow** in the light theme was Open Props' `shadow-2`, which read as a second outline next to the border; it is now a faint two-layer shadow (checked by eye in both themes; the dark one is as it was in effect).
- **The sidebar's width** is yours: drag its edge, or focus it (it is a `role="separator"` with a value, the "window splitter" pattern) and use the left and right arrows (16px), Home and End. 224 to 480px, kept in this browser (`nav.js`, `--sidebar-w`). Only the open, wide sidebar has the edge; on a phone the sidebar is a drawer and closed it is a rail.

Tests: `tests/ui/test_polish_ui.py` (the recent chats, the resizing by keyboard and by dragging, the limits, where the edge exists, the model name's colour). The tests that clicked a sidebar link by its name on the new-chat screen now say `#conversations`, because the same title is also a recent chat there.

## What was left alone
The Settings dialog (cards, tabs, switches), the model menu, the code blocks and math, and the phone layout (nothing overflows).

## A second pass: the moments, not the resting page
The first review looked at the page at rest. This one drove the states that matter most with scripted replies: a web search and its sources, a reply streaming (and its Stop button), a failed reply, attachments in the message box and in a sent message, the drop overlay, a message box of several lines, the undo toast, and a phone-sized window. Nearly everything held: the streaming edge, the Stop button, the sources list, the chips (stacked on a phone) and the drop overlay read well. Three things did not:

- **The end of the conversation was covered when the message box grew.** Adding an attachment or typing several lines made the box taller and the pane shorter, and the last reply's buttons (or the failed reply's Retry) slid under the box. A reader at the bottom now stays at the bottom: a `ResizeObserver` on the pane keeps it pinned while `state.stick` says they were there, and leaves a reader who scrolled up where they are.
- **After a failed reply the way forward was an unlabeled icon.** Retry now has its word beside the icon (the accessible name was already "Retry"). A normal reply's Regenerate stays the bare icon.
- **Touch targets in the menus.** On a touch screen the rows of the chat menu, the model lists and the tools menu were 43px; they are 44px, as the rest of the page's controls (the sidebar rows were already).

A thing that looked wrong and was not: after deleting a chat the new-chat screen still listed a chat of the same title. It was another chat; the one waiting to be deleted is hidden from the recent list, which a test now pins (`test_a_chat_waiting_to_be_deleted_is_not_a_recent_chat_and_undo_opens_it_again`). And "3 results" over a list of two links is the count the model got: a result that is not a web address is not made a link, by design.

Tests: `tests/ui/test_polish_ui.py` (staying at the end, not following a reader who scrolled up, Retry's word) and `tests/ui/test_chat_menu_ui.py` (44px rows).

## A third pass: one tools control
Web search had a globe of its own in the composer, beside the **Tools** menu, and both said the same thing in the same way: a tool that is on is the accent on the icon. Once the word "Search" came off the globe, neither icon said what it was, so the two were one control with extra steps.

- **Web search is a row in the Tools menu**, first, with the label and hint the server sends (`GET /api/tools`), like every other tool. The globe is gone; the composer holds attach and Tools. The wrench is the accent while any tool is on and its tooltip names them ("Tools: Web search, Read web pages"), so the state is still readable without opening anything.
- **The Tools button appears when there is any tool**, web search included. With none there is nothing to offer and no button; Settings still says how to get web search ("Unavailable: set BRAVE_API_KEY on the server"), which is where the globe's tooltip went.
- **What it costs:** switching web search is two clicks instead of one. Settings, General, still starts new chats with web search on, which would have been the annoying case.

Tests: `tests/ui/test_search_ui.py` (the choice is made in the menu, the label comes from the server, nothing in the composer when there are no tools, the menu fits on a phone) and `tests/ui/test_tools_ui.py` (every tool listed, the button shown or hidden with the list, the accent and the size).

## Menus and a resized window
The menus (chat, retry, tools, model) are popovers placed once, when they open, next to their button and kept inside the window. A window resized or a phone turned while one was open left it where it no longer fitted. `app.js` now closes every open popover on `resize`; opening it again places it for the new size. (A Playwright `set_viewport_size` is a resize, so the tests use it; `tests/ui/test_chat_menu_ui.py`.)

## Copying
Every copy button (a message's, a code block's) goes through `copyText` in `core.js`: the clipboard API first, then, if that throws, selecting the text in a hidden field and `document.execCommand('copy')`. The API is missing on a page that is not secure (`http://192.168...` or a host name, as opposed to `https` or `localhost`) and the browser can refuse it by permission (the built-in browser pane of the desktop app does: "Write permission denied"); before, the button then did nothing, with an unhandled error in the console. The older call is deprecated but is the only one that works in those cases, and the focus is put back where it was. If both fail the buttons say so: a code block's button reads "Couldn't copy" for a moment, a message's shows the note over the message box. `tests/ui/test_copy_ui.py` makes the API refuse, then absent, then everything fail.
