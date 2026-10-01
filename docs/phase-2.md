# Phase 2: persistence + conversation sidebar

- `db.py`: `connect()` (row factory, foreign keys on) and `init()`, which applies `MIGRATIONS` in order and records progress in `PRAGMA user_version`. Add a schema change by appending a script to `MIGRATIONS`.
- `store.py`: plain functions for conversations and messages. `add_message` bumps `conversations.updated_at`, and the sidebar sorts by it. `messages.meta` is a JSON column reserved for attachments, tool calls and usage in later phases.
- API (`routes.py`):
  - `GET/POST /api/conversations`, `GET/PATCH/DELETE /api/conversations/{id}`
  - `POST /api/conversations/{id}/chat` with `{content, model?}`. It saves the user message, streams the reply, and saves the assistant message on `done`. This replaces phase 1's `POST /api/chat`.
- Titles: after the first exchange the server calls `llm.generate_title` (non-streaming, best-effort) and sends `{"type": "title", ...}` after `done`. On failure the title falls back to the first 40 characters of the user message.
- UI: sidebar with new, rename and delete. The URL hash (`#<id>`) is the conversation link. "New chat" creates the conversation lazily on first send, so no empty conversations pile up.
- Behavior to know: a failed or interrupted reply is not saved, but the user message is. Phase 3 handles stop and retry properly.
- Fixed: the static mount path is now relative to `app/main.py`, so the server no longer needs to start from the project root.
