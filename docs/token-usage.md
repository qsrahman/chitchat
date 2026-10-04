# Token usage

The numbers were already there: each reply's `meta.usage` (`input_tokens`, `output_tokens`, `reasoning_tokens`) is saved with it (`docs/phase-5.md`), sent in the `done` event, kept in the backup, and shown nowhere. Now:

- **Under each reply**, in the line of actions beside the model name: `1.2K in · 567 out`. Hover for the exact numbers: `1,234 input tokens, 567 output tokens (300 of them reasoning)`. It follows the actions' rule (shown on hover or focus, and always on the last reply), so it is not a note under the text: that was removed earlier as clutter, and the test that no note appears is kept.
- **For the chat**, in the dialog "Instructions for this chat": `Tokens in the replies shown: 2,468 in, 1,134 out.` It adds up the replies on the page, so it is the version being read, not other versions of an edited or regenerated message, and it is hidden when nothing reports usage.

Things to know when reading the numbers:
- The count for a reply is what the API billed for it: with tools, every round of the loop sends the conversation again, so *in* is the sum of the rounds. *Out* includes the reasoning tokens, which is why the tooltip says "of them".
- A reply that was stopped or failed has none (the count arrives with the end of the response). Endpoints that report no usage, and replies saved before it was recorded, show no tag.
- Only counts. There is no price: it would need a table of model prices that goes stale, and a custom endpoint has none.

Code: `usageLabel` and `usageTitle` in `app/static/core.js`, the tag in `updateActions` (`chat.js`), the total in `settings.js`. Tests: `tests/ui/test_reasoning_ui.py`.
