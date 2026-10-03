# Round 6

Three changes, each its own commit: a copy of the database before it is upgraded, "try again with another model", and attachments in the backup.

## 1. A copy of the database before an upgrade
Branching's migration ran on the real `chitchat.db` the moment the dev server reloaded, with no copy. It worked, but a migration that failed halfway (`executescript` is not a transaction) would have left the only copy of someone's chats half changed.

`db.init` now, when the file has a version above 0 (it holds something) and below the newest, copies it to **`<db_path>.bak-v<version>`** (for example `chitchat.db.bak-v5`, the database as it was before migration 6) and only then upgrades it. The copy is made with SQLite's backup API, not a file copy, because the database runs with a write-ahead log and a plain copy would miss what is still in the log (tested: a row that is only in the log is in the copy). It logs one line saying where. Fresh and up-to-date databases get none, so nothing is written on a normal start.
- **A copy that exists is kept.** It can only be there from an earlier failed try at the same upgrade, and that is the better copy: nothing is overwritten.
- **They are never cleaned up.** A copy is a few hundred kilobytes for a normal database; delete them when you are happy with the upgrade. They are in `.gitignore` (`*.db.bak-*`).
- **To go back:** stop the server, move `chitchat.db` (and `chitchat.db-wal` and `-shm` if present) aside and rename the copy to `chitchat.db`. Older code than the migration is needed to run it: the copy is at the old version, and a newer app would upgrade it again.
- Not covered: attachment files are not in the copy (they are not touched by a migration).
Tests: `tests/test_db_backup.py`.

## 2. Try again with another model
Next to **Regenerate** (and **Retry**, after a failed or stopped reply) there is a small chevron button, **Try again with another model**. It opens a menu of the models the provider lists (the same list as the header's picker, with the same "default" and "reasoning" tags); picking one runs that reply again with it. Because of branching (`docs/branching.md`) the new answer is a new version of the reply, so `‹ 1 / 2 ›` lets you compare the two.
- **For that reply only.** The conversation's own model (header, settings) does not change, and the next message you send uses it. The server takes an optional `model` on `POST .../regenerate` and `POST .../edit` (like `.../chat` already did); an empty, blank or over-long name is a 422 before anything changes.
- **Each reply records which model wrote it.** `meta.model` is saved on every assistant message (also a stopped one), sent with the `done` event, and shown as a small grey name next to the buttons under the reply (visible on hover, always on the last reply). That is what makes comparing versions possible, and it also shows which model answered after a model switch mid-chat. Older messages have none and show nothing. The backup keeps it (it is on the whitelist in `backup._clean_meta`, as text up to 200 characters).
- **Settings still follow the model.** The reasoning effort or temperature sent is the one that fits the model chosen for the reply (`supports_reasoning`), as for any message.
- The menu is a popover like the header's: arrow keys, Home and End, Tab and Escape, the focus back on its button; it opens below the button or above it when there is no room (the buttons are at the bottom of a reply). Code: `retry-menu.js`; the row and key handling are shared with `model-menu.js`.
- Not done: a way to run one reply on several models at once, and choosing a model while editing.
Tests: `tests/test_retry_model.py`, `tests/ui/test_retry_model_ui.py`, `tests/ui/test_a11y_ui.py`.
