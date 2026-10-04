# Storage

Settings, Data controls, **Storage** shows what the app keeps and has two deletes. Both are buttons: nothing is deleted on a timer (the only automatic cleanup is the older one at startup: uploads never sent with a message are purged after 24 hours, `docs/phase-6.md`).

| Row | What it shows | Button |
|---|---|---|
| Space used | The database (with its write-ahead log, where recent changes still are), the attachments of chats (size and number of files), and how many chats there are, how many of them archived. `GET /api/storage` | none |
| Unused files | The number and size of files nothing uses, or "None: every file belongs to a chat" | *Delete unused files* (`POST /api/storage/clear-unused`), disabled when there are none |
| Old archived chats | A choice of 30 days, 90 days (the default), 6 months or a year, and how many archived chats have not been used for that long (`GET /api/storage/archived?days=N`) | *Delete archived chats*, after a confirmation that says how many and that it cannot be undone (`DELETE /api/storage/archived?days=N`) |

## Unused files
Two kinds, both **at least an hour old**: an upload that was never sent with a message (its row has no conversation), and a file in the attachments folder that no row names (left by a crash, or a copied folder). A PDF's extracted text, `<id>.txt`, goes with its file. The hour is because an upload is written to disk before its row exists, and a file is attached to a message a while after it is uploaded: a younger one may be about to be used. A file of a chat is never touched, however old.

## Old archived chats
Age is the time of the chat's last message: archiving does not count as activity (`store.set_flags`), so a chat archived today after a year of silence is old. Only archived chats are considered; pinned or not does not matter. The delete removes the chat, its messages and every version of them (and, through the cascade, the attachment rows and the search index entries), then deletes the attachment files, then runs `VACUUM`, because SQLite keeps freed pages in the file and the size would not go down otherwise (tested: the file is smaller after deleting a chat of 90,000 characters). It can take a moment on a big database. If the chat on screen is one of those deleted, the page opens a new chat, and the list is refreshed.

There is no undo, unlike deleting one chat from the sidebar (which waits ten seconds): the confirmation says so and points to Export.

## Not done
Deleting by size or by chat count, deleting chats that are not archived, a schedule (a setting that deletes by itself), and removing the old `*.bak-v*` database copies (they are already pruned to the two newest, `docs/backup.md`).

Code: `app/storage.py`, the routes in `app/routes.py`, `app/static/storage.js`, and `bytes` in `core.js` (shared with the attachment chips, which now count in thousands, "340kB", not in 1,024s). Tests: `tests/test_storage.py`, `tests/ui/test_storage_ui.py`.
