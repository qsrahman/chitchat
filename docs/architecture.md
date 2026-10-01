# Architecture

Flat backend: `config` (settings), `db`/`store` (SQLite, plain functions), `llm` (the only module that imports `openai`; emits our own normalized events), `routes` (HTTP + SSE), `static/` (vanilla JS UI).
Conversation state lives in our SQLite DB; every OpenAI call is stateless (`store=False`).
See the phase notes (`phase-N.md`) for what each phase added.
