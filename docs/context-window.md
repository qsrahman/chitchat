# Long chats on a model without compaction

On OpenAI, a long conversation is handled by server-side compaction (`docs/phase-8.md`). A custom endpoint (Ollama, or anything behind `OPENAI_BASE_URL`) has no such thing, and has a context window of its own. Past it, the server silently cuts the start of the conversation or fails. This is the fallback for that case (`app/context.py`).

## What it does
Before each reply, if there is a history budget, the newest messages that fit in it are sent and the older ones are left out of that request.
- **The messages are never deleted:** they stay in the database, in the UI and in exports. Only what is sent to the model changes, and it is recomputed every turn, so raising the limit brings the older messages back.
- **The budget:** `CONTEXT_TOKENS`. Unset: 32,000 on a custom endpoint, no limit on OpenAI (which compacts). `0`: no limit anywhere. A number on OpenAI applies there too. Set it to your model's real window, minus nothing: the instructions (default prompt, custom instructions, the chat's system prompt, tool guidance) and room for the reply (`OPENAI_MAX_OUTPUT_TOKENS`, or 2,000 when that is unset) are taken off it for you.
- **Rules:** the message being answered always stays, however big (if it alone is too big the model's own error comes back). What is sent always starts with one of your messages, never with a reply. Newest first, so the recent conversation is what survives.
- **It says so:** a note under the reply, "N earlier messages were left out to fit the model's context." The browser is told with a `context_trimmed` event before the reply starts, and the count is saved in the reply's `meta.trimmed`, so the note is still there after a reload.

## Sizes are estimates
There is no exact tokenizer for an arbitrary local model, so a message counts as its characters divided by 3, rounded up: English is nearer 4 characters per token and code or non-Latin text nearer 2, so this errs towards counting too much and trimming a little early rather than overflowing. An image attachment counts 1,000 tokens and a PDF sent as a file 2,000; text attachments count their text. If your model's window is large, raise `CONTEXT_TOKENS`.

## Checked against a real local model
With `gemma4:cloud` on Ollama: a first message with a code word, three long filler messages, then "what is my code word?". With a small budget, 8 older messages were left out, the model said it did not know, the note and event appeared and all 10 messages were still stored; with no limit it answered correctly.

## A related fix: compaction is OpenAI-only
`Settings.compaction_enabled` is true only when `OPENAI_BASE_URL` is unset. Before, the compaction request was sent to any endpoint, and, worse, a chat that had started on OpenAI (and held an encrypted compaction item) would send that item to a local model after you switched endpoints, which cannot read it. Now a custom endpoint is never asked to compact, and saved compaction items are ignored there (the full history is sent, then trimmed to the budget). Going back to OpenAI uses them again.

## Not covered
- A real tokenizer (an estimate is enough to avoid overflow, and none exists for every local model).
- Summarizing the left-out messages instead of dropping them (a model call per long turn, and quality varies by model).
- Reading the model's real window from the server (Ollama has an API for it, OpenAI-compatible servers in general do not).

Tests: `tests/test_context.py`, `tests/test_context_api.py`, `tests/ui/test_trimmed_ui.py`, and `tests/test_llm.py` (no compaction request to a custom endpoint).
