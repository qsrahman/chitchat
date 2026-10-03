# Phase 8: long conversations, search and export

## Context management: OpenAI's compaction, not our own
Before building anything, the OpenAI docs and SDK (3.22) were checked for what exists:

| Option | What it does | Verdict |
|---|---|---|
| `truncation="auto"` | When the input is too long, the server silently drops items from the start | Lossy and invisible; the model forgets the beginning without saying so |
| **`context_management=[{"type": "compaction", "compact_threshold": N}]`** | Server-side compaction: when a request's context passes N tokens, the model replaces the older turns with an encrypted *compaction item* in the response output | **Used.** Works with `store=False` |
| `client.responses.compact(...)` | The same, as an explicit call you make with the whole window | Not needed: the automatic mode does the same thing during a normal request |
| `previous_response_id` / Conversations API | The server keeps the history | Ruled out by design (stateless) |
| `client.responses.input_tokens.count(...)` | Count tokens before sending | Not needed: compaction counts for us |

So there is no summarizing prompt, token budgeting or truncation code in this app. `llm.stream_reply` sends `context_management` (when `COMPACT_THRESHOLD` is not 0), and the compaction item that comes back is our only new state.

### Verified with a real call
A 1,000-token threshold on a ~2,500-token conversation: the stream contained `output_item.done` events for a `compaction` item, then the `message`, then (since the context was still over the threshold) another `compaction`. Sending only the last compaction item plus a new question, the model still answered a detail from the compacted turns correctly. That is the live test `test_live_compaction_round_trip`.

### How we use the item
- The item is opaque and encrypted: not readable, only meaningful to OpenAI. So it is kept next to the text, never instead of it. Our messages stay in SQLite and in the UI in full.
- `llm.py` tracks the last compaction item of a reply and whether it came before or after the reply's text, and emits `{"type": "compaction", "item", "after_reply"}` just before `done`.
- `routes._stream_turn` saves it in the assistant message's `meta.compaction`. The browser is only told that it happened (`{"type": "compaction", "after_reply"}`) and the message lists and exports leave the item out (`_public`).
- `routes._history` finds the latest message with a compaction and sends `[compaction item, ...the messages after it]`: the item stands for everything before it. If the item came after the reply text (`after_reply`) it already covers that reply, otherwise the reply text is sent after it. Regenerating or editing the reply that holds the compaction deletes it, and the history is rebuilt from the previous compaction, or in full.
- The UI adds "Earlier messages were compacted to save context." to the note under that reply.

### Limits
- OpenAI only. A server that doesn't implement it (Ollama was tried) accepts and ignores the parameter, so nothing is ever compacted there; set `COMPACT_THRESHOLD=0` to be explicit. Past the model's context window, those servers decide what to do.
- The item is only valid with the model family that made it, so changing the model in a long conversation after a compaction is untested here.
- A reply that is stopped or errors doesn't save its compaction; the next turn compacts again if needed.
- Only the newest message's attachments are re-sent each turn (`docs/round-3.md`); the compaction item carries what mattered from the rest.

## Search
Full-text search over message text with SQLite FTS5 (migration v4: an external-content index kept in step with `messages` by triggers, so deleting a conversation or editing a message updates it; existing messages are indexed by the migration).
- `GET /api/search?q=...` returns `[{id, title, snippet}]`, one per conversation (its best-matching message), best first, at most 20. Words are stemmed (porter) and the last word is a prefix, so results follow typing.
- The query is built from the `\w+` words of the input, each quoted, so no input can hit FTS5's own syntax (`AND`, `NEAR`, `col:`, quotes).
- Snippets mark matches with STX/ETX control characters, which cannot appear in the text being searched in practice; the UI splits on them and builds `<mark>` elements, so a snippet is never parsed as HTML.
- UI: a search box in the sidebar replaces the dated list with results while it has text (debounced, hidden in the icon rail).
- Titles are searched too, and a result opens the chat at the matching message: see "Search, later" below.

## Export
`GET /api/conversations/{id}/export?format=md|json` downloads the chat. Markdown has the title, then `## You` / `## Assistant (model)` sections (attachments listed by name; the tools the model used, with the sources it found: `docs/round-9.md`). JSON is the conversation with its messages, metadata included (reasoning, usage, tool calls) minus the encrypted compaction item. Attachment files are not included. The links are in the chat settings dialog, and a Download button in the header gets the Markdown.

## Tests
`tests/test_phase8.py` (compaction bookkeeping and history, search, export, the v4 migration), `tests/test_llm.py` (the request parameter, compaction events, the item sent as-is), `tests/ui/test_history_ui.py`. Live: `test_live_compaction_round_trip`.

## Not included
- Our own summarizing or token budgeting, for models without compaction.
- A manual "compact now" button (`responses.compact` is available if wanted).
- Searching titles, or opening a conversation at the matched message.
- Importing an export.

## Search, later: titles, and jumping to the message
- **Titles are searched** (migration v5: a second FTS5 index over `conversations.title`, kept in step by triggers for insert, rename and delete). A chat comes up if its title or any message matches every word; those matching by title come first. Each result is one row: `id`, `title`, `title_marked` (the title with STX/ETX around matches), and, when a message matches, `message_id`, `role` and `snippet`; a title-only match has `message_id: null` and an empty snippet. The `search_chats` tool reports those as "the title matches".
- **A result opens at its message:** the sidebar sets `state.jumpTo` to the message id before the hash changes; `openConversation` puts each message's database id on its element (`data-id`) and, after rendering, scrolls the match to the middle of the view and lights it (`.is-found`, about 2.5 s, fading). A title match opens the chat at the end as before. If the chat is already open the hash does not change, so the page scrolls there directly, or, when the message was streamed in this session and has no id on the page yet, opens the chat again to get the ids.
- Tests: `tests/test_search_titles.py`, `tests/ui/test_search_jump_ui.py`.
