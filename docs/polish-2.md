# Polish, round 2

Three small changes made together, each its own commit.

## 1. The conversation list is paged
`GET /api/conversations` took no arguments and returned every chat, and the sidebar built a row for each. Import allows 5,000 chats, so that list could get slow to fetch and build. It now takes `limit` (1 to 500, default 50) and `offset`, newest first. The sidebar loads 50 and shows a "Show more" button while the last request came back full (so there is no button after the last page, and none for a short list). A refresh after a rename, delete or new message reloads as many chats as are showing, so nothing you scrolled to disappears. `store.list_conversations` has no limit by default, which `backup.py` relies on to export everything.

Because the open chat may be further down than what is loaded, the page takes its title from the chat itself when it opens it (`setTitle` in `sidebar.js`), not from the list. Search is unaffected: it asks the server, not the loaded list. Tests: `tests/test_api.py`, `tests/ui/test_history_ui.py`. Not measured: how slow the old unpaged list actually was at thousands of chats; this was done for the worst case, not from a measurement.

## 2. A test for file names in the docs
`tests/test_docs_paths.py` reads `README.md`, `CLAUDE.md`, `PLAN.md` and `docs/*.md`, takes every backticked token that looks like a file (known extension, no wildcards or placeholders), and fails if it exists in none of the repo's usual places. A renamed or deleted file now breaks the build instead of leaving a stale name. It found nothing stale on its first run (the failures were placeholders such as `phase-N.md` and paths inside npm packages, which are listed in `NOT_FILES`). It checks **file names only**: a function or constant that was renamed (`TOOL_UI`, say) is not caught, because telling a symbol from a word needs more than a regex.

## 3. Keyboard shortcuts
- **Cmd/Ctrl+K** opens the sidebar and focuses the search box (selecting what is in it).
- **Cmd/Ctrl+Shift+O** starts a new chat.
Both are in `sidebar.js`. They do nothing while a dialog is open, and with Alt held down they are left alone. Plain letters are untouched, so typing in the message box is unaffected. The two controls show the shortcut in their tooltip (Cmd on a Mac, Ctrl elsewhere, chosen from `navigator.platform`) and carry `aria-keyshortcuts`. Esc (stop a reply) and Enter/Shift+Enter (send, new line) were already there. Caveat: a browser may keep a shortcut for itself (Ctrl+Shift+O opens the bookmark manager in some Chromium builds); the page calls `preventDefault`, which works in the browsers I know of but I only tested it in Chromium under Playwright, where the browser's own shortcuts don't exist. Tests: `tests/ui/test_history_ui.py`.
