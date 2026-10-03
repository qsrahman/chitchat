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
