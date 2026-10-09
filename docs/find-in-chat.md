# Find in chat

Sidebar search finds chats; this finds text inside the open one.

- **Open:** Mod+F while a chat is open (on the new-chat screen, or with a dialog open, the browser's own find is left alone), or "Find in chat" in the ⋯ menu.
- **Bar:** a search box, "3 of 12", previous and next, close. Enter and Shift+Enter step (and wrap); Escape or the close button closes it and puts the cursor back in the message box. Opening another chat closes it.
- **What is searched:** the text of every message on screen, yours and the replies, case-insensitively, and also the reasoning and the lines and results of tool calls. Stepping to a match inside a closed section (reasoning, a tool line) opens it, as the browser's own find does. Not the buttons, or the TeX a formula is read from. A match may run over bold, italic, code or a link inside a paragraph; it may not run from one paragraph, list item or table cell into the next (`BLOCK` in `find.js`).
- **How it shows** (`static/find.js`): matches are `Range`s painted with the CSS Custom Highlight API (`::highlight(find)`, and `find-current` for the one you are on). The text is not touched, so nothing needs undoing and a re-render does not break it.
- **While a reply streams:** a `MutationObserver` on the thread searches again 300 ms after the last change and stays on the same match number; the view is not moved. (Ranges are not live, so this is what keeps them true.)
- **Limit:** 500 matches ("1 of 500+"): a one-letter search of a long chat can step through the first 500 without slowing the page.
- **Tests:** `tests/ui/test_find_ui.py`, and the bar is in the axe checks.
