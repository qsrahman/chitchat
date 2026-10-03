# Backup: export everything, import it back

**Where:** the sidebar's "Backup & import" button (a download icon in the closed rail) opens a dialog with the two exports and an import file picker.

## Export
- `GET /api/export` (or "Export all chats"): **one JSON file** with every conversation, which can be imported again:
  ```json
  {"format": "chitchat-backup", "version": 1, "exported_at": "...",
   "conversations": [{"id", "title", "settings", "created_at", "updated_at",
                      "messages": [{"id", "role", "content", "meta", "created_at"}]}]}
  ```
  Oldest chat first. Message `meta` carries what the page shows (reasoning, usage, tool calls, notes).
- `GET /api/export?format=md` ("Export as Markdown"): a **zip with a Markdown file per conversation**, named `date-title-idprefix.md` (the id prefix is why two chats with the same title don't collide). Meant for reading, not for importing.
- The export one chat (settings dialog) is unchanged, and its JSON can be imported too.
- Never in an export: OpenAI's encrypted compaction items (opaque, tied to a model, only for the model), and attachment **files**: they are listed by name in the Markdown and in `meta.attachments`, but their bytes are not included.

## Import
`POST /api/import` (multipart `file`), or "Import chats from a file". It takes the backup above, a single chat's export, or a bare list of chats.
- **Nothing is overwritten.** A conversation whose `id` is already here is skipped, so importing the same file twice does nothing ("Nothing new: 1 chat already here"), and importing an old backup next to newer chats never touches them. A chat without a usable id (a file written by hand or by another tool) gets a new one, so it is added again each time. Ids that aren't 32 hex digits are replaced, never used.
- **All or nothing.** The whole file is checked first (shape, roles, sizes), and the inserts are one transaction: a file with one bad conversation adds none of them, and an error halfway rolls everything back. Refusals say why in plain words ("conversations.1.messages.0.role: Input should be 'user' or 'assistant'"), as a 422; a file over 50 MB is a 413.
- **Limits:** 5,000 conversations, 20,000 messages in one, 1,000,000 characters in a message.
- **What is kept and what isn't.** Titles (trimmed, 200 characters, "Imported chat" if blank), messages in order, timestamps (any ISO form, normalized to UTC; missing ones default to the chat's), settings (validated; tools this version doesn't have are dropped, and settings that are still invalid give the defaults rather than a refusal). From `meta`, only a whitelist is kept: reasoning, usage counts, tool calls (with a known status and object-shaped details), `stopped`, `incomplete`, `trimmed`. **Attachments are dropped**, and the message gets a note ("[Attached when this was sent, not included in the import: cat.png]") so it isn't a silent loss; compaction is dropped.
- **Why the whitelist:** the page renders `meta`. A crafted file must not be able to make a conversation unopenable or run script. Beyond cleaning the data, the page now draws a tool call whose details it can't use as a plain line ("Used web_search") instead of failing the whole conversation, which also protects against older saved shapes. Titles are set as text and replies go through the sanitizer, as always; the tests import a file full of markup, `javascript:` links and malformed tool details and check nothing runs.
- Imported chats are searchable at once (by title and by message) and can be continued like any other.

## Not covered
- Attachment files (a backup of the `attachments/` folder next to the database is the way for now).
- Custom instructions (they are one text; app-wide, not per chat).
- Merging two versions of the same chat: a chat that exists is skipped whole.
- Importing the Markdown zip or another app's format (ChatGPT's export would need a converter).

Tests: `tests/test_backup.py` (52: both exports, round trip into a fresh database, idempotency, never overwriting, hostile and malformed files, atomicity, limits, metadata cleaning), `tests/ui/test_backup_ui.py`.
