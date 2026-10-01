# Architecture

Flat backend: `config` (settings), `db`/`store` (SQLite, plain functions), `llm` (the only module that imports `openai`; emits our own normalized events), `routes` (HTTP + SSE), `static/` (vanilla JS UI).
`main` exposes only a `create_app()` factory, so importing it has no side effects; serve it with `uvicorn app.main:create_app --factory`.
Conversation state lives in our SQLite DB; every OpenAI call is stateless (`store=False`).
See the phase notes (`phase-N.md`) for what each phase added.

Request flow for a chat turn: `POST /api/conversations/{id}/chat` saves the user message, streams `llm.stream_reply` events as SSE, saves the assistant message on `done`, then emits a `title` event if the conversation is new.

Streaming uses FastAPI's own SSE support (`fastapi.sse.EventSourceResponse`): each chat endpoint is an async generator, FastAPI frames the yielded dicts as `data: {json}`, sends keepalive pings during long silences and sets `Cache-Control` / `X-Accel-Buffering` so proxies don't buffer. The request is validated and the turn is prepared in a dependency (`chat_turn`, `regenerate_turn`, `edit_turn` -> `Turn`), so errors there are normal HTTP errors. The browser side keeps a small frame splitter (`readSSE` in `app.js`) because `EventSource` can't POST.
