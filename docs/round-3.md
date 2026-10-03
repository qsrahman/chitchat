# Round 3

Six changes made together, each its own commit.

## 1. Older attachments are not re-sent
Every call is stateless, so an image or PDF was sent again, in full, with every follow-up. Now `routes._history` sends the files of the **newest message that has attachments** and replaces those of older messages with a one-line note ("Attached earlier and not sent again. Ask the user to attach it again if you need it."), under the original file name. A follow-up about the picture you just attached works as before; attaching a new file makes the model forget the old one's contents (it still has its own earlier answers, which are in the text). The chat still shows every file. Tests: `tests/test_attachments.py`.
Trade-off: you can't ask the model to compare an old image with a new one without attaching the old one again. I picked this over "last N messages" because it needs no setting and the saving is the same in the common case.

## 2. Type checking with pyright
`uv run pyright` checks `app/` (basic mode; the tests are not checked) and is a step in `scripts/check.py` after ruff. The first run found 17 errors. Most were missing `None` checks or loose annotations, fixed with narrowing or an annotation. Two things were real:
- **Image parts lacked `detail`.** The SDK's type for an image input requires it; `llm._content` sent `{"type": "input_image", "image_url": ...}` without. The API treats a missing value as `"auto"`, so nothing was failing, and the code now says `"detail": "auto"`.
- **The calculator's `type(value) in (int, float)` guard** (which keeps `True` out) is now a class pattern plus `type(value) is not bool`, which pyright can follow.
Two `assert`s in `store.py` say that a row just inserted is there. Not done: the tests and the front end are not type-checked.

## 3. Logging
The only trace of a failure used to be what the UI showed. `app/logs.py` now gives the `app.*` loggers one stream handler (stderr, so it shows next to uvicorn's own lines) with a request id on every line:
```
2026-10-03 14:02:11,402 INFO [3f9a1c7e] app.llm: tool fetch_url: done (412 ms)
2026-10-03 14:02:13,951 INFO [3f9a1c7e] app.routes: reply done: conversation 9c1e..., model gpt-5.5, 1 tool calls, 5210 tokens in, 388 out, 3.4 s
2026-10-03 14:02:13,953 INFO [3f9a1c7e] app.logs: POST /api/conversations/9c1e.../chat -> 200 in 3552 ms
```
- **Request id:** a middleware (`RequestId`) makes an 8-character id per HTTP request, puts it on every log line written while handling it (a context variable) and in the `X-Request-ID` response header. Browser dev tools show the header, so a failure can be matched to its lines.
- **What is logged:** one line per API request (not for static files or `/healthz`), one per reply (`done`, `error` or `stopped`, the model, how many tool calls, tokens, seconds), one per tool call (name, `done` or `error`, milliseconds), and warnings when a model call or the title call fails (error class and HTTP status). A tool that crashes still logs its traceback.
- **What is never logged:** message text, replies, tool arguments or results, file names, and the provider's or a tool's error message (these can quote a key or a URL with a token; the user still sees them in the UI). Tests check this.
- **Setting:** `LOG_LEVEL` (default `INFO`; `WARNING` keeps only problems).
Not done: a file or JSON log format, log rotation, and logging of the SSE events themselves. `uv run uvicorn` shows it all in the terminal.

## 4. Undo for delete
Deleting a chat used to be final after one confirmation. Now, after the confirmation, the chat disappears from the sidebar (and from search results) and a toast says `Deleted "<title>"` with an **Undo** button, for 10 seconds. The server is only asked to delete when that time is up, so Undo is just un-hiding the chat: nothing is restored from anywhere and nothing is half-deleted.
- Undo on the chat you were in, while you are still on the blank chat the delete opened, reopens it. Otherwise only the sidebar changes.
- Deleting a second chat makes the first delete final at once (one toast at a time). Leaving or closing the page makes a waiting delete final too (`pagehide`, a `keepalive` request), so closing the tab does what you asked.
- The confirmation dialog stays (its text now says the delete can be undone for a few seconds); the API is unchanged: `DELETE /api/conversations/{id}` still deletes at once and its attachment files go with it.
- Limits: the server sees nothing until the 10 seconds are up, so a second tab or an export in that time still shows the chat; if the browser crashes or the network is down during the wait, the chat is simply still there afterwards (the safe direction). The toast is a status message for screen readers, with the Undo button reachable by keyboard.
Tests: `tests/ui/test_history_ui.py` (undo for the open chat and for another chat, the delete becoming final after the wait with a faked clock, a second delete finalizing the first, search), `tests/ui/test_a11y_ui.py`.

## 5. Light/dark toggle
The theme used to follow the operating system with no way to change it. The sidebar footer now has a **Theme** button that cycles **System → Light → Dark**, showing the current one (`Theme: Dark`), remembered in this browser (`localStorage`, key `theme`; System removes it).
- **How:** the colors were already `light-dark(...)` pairs under `color-scheme: light dark`. The button sets `data-theme="light"` or `"dark"` on `<html>`, and `style.css` turns that into `color-scheme: light|dark` (and the shadow hue, which was keyed to a media query). System sets no attribute, so nothing changed for anyone who doesn't use the button. There is no second set of colors.
- **No flash:** a tiny classic script, `early/theme.js`, in the `<head>` applies the saved choice before the first paint (the module code in `appearance.js` runs too late for that). It lives in a subfolder so the module-graph test doesn't take it for an unused module.
- **Tests:** `tests/ui/test_theme_ui.py` (cycling against both system themes, a choice outliving a system change and a reload, System forgetting it, the attribute being set before the page's own script) and axe in each forced theme on each system theme (`tests/ui/test_a11y_ui.py`).
Not done: the highlight.js and KaTeX colors follow `color-scheme` like everything else, but I only checked code blocks and math through axe, not by eye in a forced theme against the opposite system theme.

## 6. Library updates
- **highlight.js 11.11.1 to 11.12.0** and **marked 16.4.2 to 18.0.14**, both with `scripts/vendor.py update` (verified byte for byte against npm afterwards: `vendor.py check` reports everything current). DOMPurify, KaTeX and Open Props were already current.
- **marked** skipped two majors. 17 changed how list items, loose lists and task-list checkboxes are tokenized; 18 trims trailing blank lines from block tokens. `markdown.js` uses the extension API (math tokenizers, the code renderer, the reasoning tokenizer wrapper) and the incremental renderer compares block tokens' `raw`, so I expected trouble. The whole suite, including the math, reasoning, sanitizer and incremental-render tests (which compare streaming output with a full render at every step), passed with no code change. As a second check I rendered seven documents (lists nested, loose and task, tables, setext headings, reference links, raw HTML, indented and fenced code, extra blank lines, unclosed syntax) with 16 and 18 side by side: the HTML is identical except that one blank line between a raw `<div>` block and a following list is gone (`</div><ol>` instead of `</div>\n\n<ol>`), which renders the same.
- **Python packages:** see the commit message and `docs/development.md`.
