# Round 8

Three changes, each its own commit: measuring the app with a lot of data (and the two things that measuring found), splitting the sidebar module, and a restore command for the database copies.

## 1. The app with a lot of data
`scripts/bench_scale.py` builds a database in a temporary folder and times what a person would do (it touches nothing of yours): `chats 5000 20` (the import limit: 5,000 chats, 100,000 messages), `long 5000` (one chat of 5,000 messages), `versions 2000` (every tenth message with three versions) and `page 3000` (opening a long chat in a real Chromium). Same machine as the earlier benchmarks (14-core Mac), median of five runs.

| What | 5,000 chats x 20 messages | one chat of 5,000 | 2,000 with versions |
|---|---|---|---|
| chat list, first page | 6 ms | 10 ms | 5 ms |
| chat list, page 50 of 100 | 8 ms | 8 ms | 5 ms |
| search, a common word | 46 ms | 17 ms | 8 ms |
| search, two words and a prefix | 39 ms | 11 ms | 10 ms |
| open a chat (the whole path) | 4 ms | 66 ms | 30 ms |
| send a message (fake model) | 8 ms | 31 ms | 32 ms |
| switch to another version | n/a | n/a | 12 ms |
| export everything | 368 ms (42 MB) | 21 ms | 19 ms |

So the server is fine at the largest size the app imports: the paging, the full-text search and the tree queries (the path to the leaf, the versions of each message) all stay in milliseconds, and the version switch costs 12 ms at 2,000 messages. Two things were not fine, and are fixed:

- **Importing took 49 s for 100,000 messages**, and ran on the event loop, so the whole server stood still meanwhile. Nearly all of it was the full-text index being updated by a trigger for every message (0.2 ms each, against 0.02 ms for the insert itself). A big import (200 messages or more) now drops that trigger inside the import's transaction, inserts everything, indexes the new messages with one `INSERT ... SELECT` and puts the trigger back, **3.4 s** for the same file. It is in the same transaction as everything else, so a failed import rolls the trigger back too (tested: a failure leaves the trigger and an empty index; a re-import adds nothing; messages that were there before are not indexed twice; messages sent afterwards are found). The import now also runs off the event loop (as the zip import already did).
- **Opening a long chat was quadratic in the page.** `render()` scrolls to the end, which reads the scroll height, which makes the browser lay the whole page out again, once per message. Opening 3,000 messages blocked the page for **2.2 s**; 1,000 for 0.35 s. The loop now renders with the scroll off and scrolls once: **0.42 s** and **0.14 s**. A browser test counts the scroll-height reads while 400 messages open (402 before, a handful now).

Not done: the page still renders every message of a chat at once. At 3,000 messages that is 0.4 s and at 10,000 it would be over a second; `content-visibility: auto` on messages, or drawing only what is near the view, would fix it but changes how scrolling and search-jumps behave, so I left it until a chat that long exists. The numbers use a fake model, so "send a message" is the app's own cost, not the model's. The 5,000-message chat's history is sent whole to OpenAI, where compaction handles it, or trimmed on a custom endpoint (`docs/context-window.md`).

## 2. The sidebar module is five
One file of 296 lines held the chat list, search, delete with undo, pin and archive, the drawer, the keyboard shortcuts and backup. It is now:

| File | Lines | Holds |
|---|---|---|
| `list.js` | 174 | the list: paging, search, rename, pin, archive, the Archived chats toggle, `setTitle` |
| `delete.js` | 56 | delete with ten seconds to undo: the timer, the toast, the Undo button, the page-close handler |
| `nav.js` | 21 | the drawer (`setNavOpen`, `closeNavIfOverlay`) |
| `shortcuts.js` | 27 | Cmd/Ctrl+K and Cmd/Ctrl+Shift+O |
| `backup.js` | 42 | the backup dialog and the import status |

No behavior changed; the moved code is the same text. (The old file is gone.) Two seams needed a decision, because `delete.js` needs the list and the list's rows have a Delete button: the row button dispatches a `delete-chat` event on the shared `bus` (as `open` already works) and `delete.js` listens, so `list.js` never imports it; and the list hides the chat being deleted through `hideChat(id)`, which `delete.js` calls, instead of reading the delete's private `pending` state. The module-graph test (no cycles, every import used, everything reachable from `app.js`) and ESLint pass, and so does the whole browser suite; the docs-path test caught the stale names of the old file in `docs/architecture.md` and `docs/polish-2.md`, which are updated.

## 3. A command to restore a database copy
The recovery steps for the copies made before an upgrade (`docs/round-6.md`) were a paragraph of "stop the server, move three files, rename one". `scripts/restore_db.py` does it:
```
uv run python scripts/restore_db.py                      # lists the copies next to the database, with what is in each
uv run python scripts/restore_db.py chitchat.db.bak-v6   # restores that one, after asking
```
It reads `DB_PATH` from `.env` (or `--db`), and shows for the database and the copy the schema version, the number of chats and messages and the size, read without changing anything. Stop the server first (it does not try to detect one). Restoring:
- **never deletes**: the database as it is now, with its `-wal` and `-shm` files, is moved to `<db>.before-restore-<date-time>`;
- **checks the copy first** (`PRAGMA integrity_check`, and that it has the tables): a file that is not a database, an empty file, a damaged one, or the database itself is refused with nothing changed;
- copies the backup into place with SQLite's backup, so the result is one clean file;
- leaves the copy where it was. The restored database is at its old schema version, and the app upgrades it again on the next start (making a fresh copy first).
`--yes` skips the question. Tried against your real database folder in listing mode only (it showed `chitchat.db` at version 7 and `chitchat.db.bak-v6` at version 6, with the same 2 chats and 22 messages): I did not restore anything of yours. Tests (`tests/test_restore_db.py`) cover the listing, restoring and keeping the old database (including what only its write-ahead log held), the app upgrading the restored copy again, refusing bad, empty, damaged and self copies, and the prompt.
