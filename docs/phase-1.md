# Phase 1: streaming chat

- `llm.py`: `OpenAILLM.stream_reply(model, messages)` calls `responses.create(stream=True, store=False)` and yields normalized events (`delta` / `done` / `error`). Nothing else imports `openai`.
- `routes.py`: `POST /api/chat` takes the full message list and streams the events as SSE (`data: {json}\n\n`).
- UI (`static/`): history is held in browser memory (phase 2 moves it to SQLite). Replies are rendered as markdown (`marked` + `DOMPurify` from a CDN).
- Tests use `FakeLLM` (see `tests/conftest.py`); `uv run pytest -m live` runs one check against the real API.
