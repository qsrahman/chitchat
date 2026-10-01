# Architecture

Flat backend: `config` (settings), `db`/`store` (SQLite, plain functions), `llm` (the only module that imports `openai`; emits our own normalized events), `routes` (HTTP + SSE), `static/` (vanilla JS UI).
`main` exposes only a `create_app()` factory, so importing it has no side effects; serve it with `uvicorn app.main:create_app --factory`.
Conversation state lives in our SQLite DB; every OpenAI call is stateless (`store=False`).
See the phase notes (`phase-N.md`) for what each phase added.

Request flow for a chat turn: `POST /api/conversations/{id}/chat` saves the user message, streams `llm.stream_reply` events as SSE, saves the assistant message on `done`, then emits a `title` event if the conversation is new.
