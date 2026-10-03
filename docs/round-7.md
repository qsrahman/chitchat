# Round 7

Three changes, each its own commit: switching back to a version lands where you left it, pinned and archived chats, and old database copies are pruned. One migration (v7) holds the columns for the first two.

## 1. Switching back to a version lands where you left it
Choosing an earlier version of a message used to continue along the **newest** reply at every step, whatever you had been reading. Now each message remembers which message came after it the last time the path showing went through it (`messages.chosen_id`), and `store.select_branch` follows those, with the newest reply as the fallback where nothing is remembered. The path is noted whenever it is left (`_remember_path`): in `select_branch`, in `set_leaf` (regenerate) and in `add_message` when a message is added beside another instead of after the end (edit). Cost: one small update per message of the path, at those moments only (not on every message sent).

Example, in the page: send "hello", regenerate (reply 2 of 2), go back to reply 1, edit the message (a new version with its own reply), then go back to the original message: you see reply 1, which is what you were reading, not reply 2. A unit test (`test_store.py`) and a browser test (`tests/ui/test_pin_archive_ui.py`) cover it; with the memory switched off the browser test shows reply 2 and fails. Imported chats start without memory (the backup does not carry it: it is where you were, not what was said). Details: `docs/branching.md`.

## 2. Pin and archive
- **Pin:** a pin button on each row of the sidebar. Pinned chats form a **Pinned** group at the top (in the order of their last activity) and show their pin in the accent colour even when the mouse is elsewhere, so you can see what is pinned without hovering. The button reads *Pin "title"* or *Unpin "title"*.
- **Archive:** an archive button on each row takes the chat out of the list. The **Archived chats** button in the sidebar footer switches the list to the archive (`aria-pressed` says which list is showing); there each row has *Unarchive*, Rename and Delete. An archived chat can be opened and talked in; talking in it does not bring it back to the list, and search still finds it (a result opens it as usual).
- **API:** `PATCH /api/conversations/{id}` also takes `pinned` and `archived` (booleans, any combination, with or without a title or settings; nothing at all is a 422). `GET /api/conversations` lists the chats that are not archived, pinned first, then newest first, or with `archived=true` the archived ones; paging works on that order. Pinning and archiving do not count as activity (`updated_at` does not move).
- **Backup:** `pinned` and `archived` are in the JSON and the zip and come back on import (also from the one-chat export, where they are 0 and 1).
- **Schema:** `conversations.pinned` and `conversations.archived` (migration v7, default 0).
- Not done: archiving with an Undo toast (an archived chat is one click away in the archive), pinning in search results, a limit on how many chats can be pinned.
Tests: `tests/test_pin_archive.py`, `tests/test_store.py`, `tests/ui/test_pin_archive_ui.py`, `tests/ui/test_a11y_ui.py`.

## 3. Old database copies are pruned
Each upgrade leaves a copy (`docs/round-6.md`) and nothing removed them. After making a copy, `db._prune` now keeps the copies of the **two most recent versions** (`KEEP_BACKUPS`) and deletes older ones, so the folder holds at most two `<db>.bak-v<N>` files however many upgrades there are. Only files named exactly `<db>.bak-v<number>` are touched: a file you put there yourself (`chitchat.db.bak-v2.keep`, `other.db.bak-v1`) is never deleted. Nothing is pruned on a start that upgrades nothing. This upgrade (v6 to v7) is the first to prune: your folder will hold `chitchat.db.bak-v6` and, if you have it, `.bak-v5`. Tests: `tests/test_db_backup.py`.
