# Phase 5: reasoning summaries and token usage

## Reasoning
- `llm.py` turns `response.reasoning_summary_text.delta` into `{"type": "reasoning_delta", "text"}`. Consecutive summary parts (different `summary_index`) are separated by a blank line.
- Reasoning models (`supports_reasoning`) are asked for `reasoning.summary = "auto"`. OpenAI refuses summaries for organizations that aren't verified, so `OPENAI_REASONING_SUMMARIES=false` turns the request off. Non-reasoning models never get the `reasoning` parameter. (`gpt-oss` on Ollama streams summaries whether or not you ask.)
- UI: a `<details class="reasoning">` above the answer. It opens as "Thinking…" while the summary streams, and collapses to "Reasoning" when the answer starts. It stands in for the three-dot indicator while there is no answer text yet. A failed reply drops the block.
- The summary is rendered as sanitized markdown (OpenAI summaries use bold headings) by its own `marked` instance (`renderReasoning`). That instance refuses single-delimiter emphasis (`*x*`, `_x_`): models like `gpt-oss` stream their raw thinking as the "summary", where `17*23 ... 17*20` is arithmetic. `**bold**`, lists, code and math still render; a real `*italic*` shows literally.

## Usage
- `done` carries `usage: {input_tokens, output_tokens, reasoning_tokens}` from the response (`reasoning_tokens` is 0 when the endpoint doesn't report it, as Ollama doesn't). Endpoints that report no usage send none.
- The UI does not show usage as a note under the reply (an earlier version did, and it was removed as clutter); it is saved in the message's `meta`, and `docs/token-usage.md` shows it in the line of actions instead.
- No cost estimate: prices depend on the model and the provider, and the endpoint can be a local server. Token counts are shown instead.

## Storage
Both are kept in the assistant message's `meta` (`reasoning`, `usage`), next to `incomplete` / `stopped`, so no schema change was needed. A stopped reply keeps the reasoning it had streamed; reasoning with no answer text is not saved.

## Tests
`tests/test_llm.py` (event mapping, request fields, usage, summaries switch, via the SDK over `httpx.MockTransport`), `tests/test_turns.py` (what is saved), `tests/ui/test_reasoning_ui.py` (the block's live and saved behavior, usage line).
