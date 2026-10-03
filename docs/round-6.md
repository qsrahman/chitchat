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
