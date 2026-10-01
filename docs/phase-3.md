# Phase 3: chat controls

- **Stop:** the send button turns into "Stop" while streaming and aborts the `fetch`. The server sees the disconnect, and `_stream_turn` (`routes.py`) saves the partial text with `meta {"stopped": true}`. A stop before any text saves nothing. Switching conversation mid-stream also counts as Stop.
- **Regenerate / Retry:** `POST /api/conversations/{id}/regenerate` deletes everything after the last user message and streams a new reply. The same endpoint is "Retry" after an error or an empty stop, when the conversation ends on a user message.
- **Edit:** `POST /api/conversations/{id}/edit {content}` rewrites the last user message, drops everything after it and streams a new reply. Only the last user message is editable. There is no branching: the old reply is gone.
- **Copy:** copies a reply's raw markdown.
- `chat`, `regenerate` and `edit` share `_stream_turn`, which owns the save-on-done, save-partial-on-stop and title logic. A reply that ends in an error is still not saved.
- UI: each message is `.body` + `.actions`, and `updateActions()` decides which buttons show (Copy on replies, Edit on the last user message, Regenerate or Retry on the last message).
- Known gap: a conversation whose first reply was stopped keeps the default title until the next completed turn.
- Tests: `tests/test_turns.py`. The disconnect tests cancel the client task, and `FakeLLM` has a `hang` event to simulate a slow stream.
