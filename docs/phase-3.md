# Phase 3: chat controls

- **Stop:** the send button turns into "Stop" while streaming and aborts the `fetch`. The server sees the disconnect, and `_stream_turn` (`routes.py`) saves the partial text with `meta {"stopped": true}`. A stop before any text saves nothing. Switching conversation mid-stream also counts as Stop.
- **Regenerate / Retry:** `POST /api/conversations/{id}/regenerate` streams a new reply to the last user message (it deleted the old reply until branching, `docs/branching.md`: now the old one stays as another version). The same endpoint is "Retry" after an error or an empty stop, when the conversation ends on a user message.
- **Edit:** `POST /api/conversations/{id}/edit {content}` rewrote the last user message and dropped everything after it. Since branching (`docs/branching.md`) it adds the rewritten message as a new version, can edit any user message (`message_id`), and keeps what followed the old one.
- **Copy:** copies a reply's raw markdown.
- `chat`, `regenerate` and `edit` share `_stream_turn`, which owns the save-on-done, save-partial-on-stop and title logic. A reply that ends in an error is still not saved.
- UI: each message is `.body` + `.actions`, and `updateActions()` decides which buttons show (Copy on replies, Edit on a user message, Regenerate or Retry on the last message).
- Known gap: a conversation whose first reply was stopped keeps the default title until the next completed turn.
- Tests: `tests/test_turns.py`. The disconnect tests cancel the client task, and `FakeLLM` has a `hang` event to simulate a slow stream.
- **Retry rule (UI):** after a failed turn the page and the server can disagree, so Retry compares user-message counts with what the server stored. Not saved: resend with `/chat`. Saved: `/regenerate`, which replaces any partial reply. Saved text differs (an edit that never landed): `/edit`. A stream that closes without `done` is shown as an error, since the server keeps its partial text as a stopped reply.
