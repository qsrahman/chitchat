# Round 9

Three changes, each its own commit: type-checking the UI, defaults for new chats, and a better Markdown export.

## 1. Type-checking the UI
`tsc` checks the JavaScript from JSDoc, as a step of `scripts/check.py`: no `.ts` files and no build step. What it covers and what it does not: `docs/typescript-check.md`.

## 2. Defaults for new chats
Settings, General, has a *New chats* card: the model and thinking effort used by chats that pick none, and a switch for starting new chats with web search. A chat's own setting wins, then this default, then `.env`. They are app-wide settings in the database, and Settings opens on the tab it was last left on. What is stored and what is not covered: `docs/settings-dialog.md`.

## 3. The Markdown export, and a button for it
Exporting one chat as Markdown already existed, but only as a small link inside the chat settings dialog, and the file was thin: who spoke and the text. (My suggestion for this round overlapped it: I had not looked at what the export did.) What changed:

- **A Download button in the header**, next to the chat settings button, once the chat exists: a plain link to `GET /api/conversations/{id}/export?format=md`, so it is one click and works without script. The two links in the chat settings dialog stay.
- **The model that answered** is in the heading when it is known: `## Assistant (gpt-5-mini)`. With "try again with another model" a chat can have replies from several, and the transcript did not say which.
- **What the tools found.** An answer from a web search lost its sources. Now a reply that used tools starts with a line for each one that finished: `*Searched the web for* “query”` and a list of the results as links, `*Read* [title](url)`, `*Searched your chats for* “query”`, and `*Calculated* \`2*3 = 6\``. A call that failed or was stopped adds nothing.
- The text of those lines came from the web or the model, so it cannot become other Markdown: it is put on one line (a title with a newline and a `- ` cannot start a list item or a heading), brackets in a title cannot end the link, a link is made only for an `http` or `https` address without spaces or brackets (otherwise just the title), and a sum goes in code so its `*` stays a `*`. Saved calls from an older version or an imported file whose details are not what is expected give no line instead of an error.
- The zip of Markdown files (Settings, Data controls) uses the same function, so it reads the same.

Not in it: the reasoning summaries (they are progress notes, not part of the answer) and attachment files (listed by name, as before).

Tests: the exact text of a chat with all the tools, hostile titles and queries, a failed call and malformed details (`tests/test_phase8.py`); the button appearing, downloading and following the open chat (`tests/ui/test_history_ui.py`).
