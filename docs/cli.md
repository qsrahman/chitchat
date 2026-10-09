# A CLI for ChitChat (noted, not built)

The UI is already separate from the backend: `app/static/` talks to the server only through `/api/*` (JSON and SSE, described in `app/static/types.d.ts`, kept in sync with `llm.py` by `tests/test_event_types.py`). A CLI can plug in two ways.

## A. The CLI as an HTTP client (no refactor; do this first)
A `chitchat` command (about 150–250 lines, `httpx`) that calls a running server.
- Commands: `ask "…"` (also reads a pipe), an interactive REPL, `ls`, `show <id>`, `export`; options `--model`, `--effort`, `--tools`, `--chat <id>` to continue one.
- Reuses everything the server does: tools, history and compaction, titles, branching, attachments, backups. It sees the same chats as the browser.
- Streaming output: the reply text to stdout as it arrives; tool calls, reasoning and errors to stderr, so a pipe stays clean.
- Cost: a server must be running. Fine for a local single-user app (there is no auth yet; if an access password is added, the CLI needs a token option).
- Server URL from `CHITCHAT_URL`, default `http://127.0.0.1:8000`.

## B. The CLI in the same process, no server (one phase of refactoring)
The chat logic is tied to FastAPI: `_history`, `_model_options`, `_make_turn` and `_stream_turn` in `app/routes.py` (about 200 lines: instructions, tools, compaction, saving a stopped reply, tool metadata, titles) take a `Request` only to reach `app.state.{settings, llm, tools}`.
- Move them to a service module (a new `chat` module) that takes a small context (settings, llm, tools, a connection) instead of a `Request`. `routes.py` keeps thin wrappers; behaviour and tests stay the same; the CLI calls the same functions.
- The rest of `routes.py` (export, import, storage, config) already wraps `backup`, `storage` and `store`.
- Worth it only if the CLI must work with the server stopped, or the core should be importable. Two processes writing the one SQLite file (server and CLI) is the risk A avoids by design.

## Choosing
A first; B only when serverless use is wanted. B does not change what A needs, so doing A first loses nothing.
