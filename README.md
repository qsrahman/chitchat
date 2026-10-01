# ChitChat

A ChatGPT-style web chat app built on the [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses). It is built in small phases, and each phase adds code, tests, docs and a commit. See [PLAN.md](PLAN.md) for the roadmap.

## Features
- Streaming replies (SSE) with markdown rendering
- Saved conversations in SQLite, sidebar with new/rename/delete, auto-generated titles, shareable `#<id>` links
- Planned: stop/regenerate/edit, model and system-prompt settings, reasoning summaries, attachments, web search and tools, search and export

## Requirements
Python 3.14+, [uv](https://docs.astral.sh/uv/), and an OpenAI API key.

## Run
```bash
cp .env.example .env   # set OPENAI_API_KEY
uv run uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000.

## Configuration
Environment variables or `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | | OpenAI credentials |
| `DEFAULT_MODEL` | `gpt-5.5` | Model used when a request doesn't name one |
| `DB_PATH` | `chitchat.db` | SQLite file |

## Test
```bash
uv run pytest            # no network, uses a fake LLM
uv run pytest -m live    # hits the real API, needs OPENAI_API_KEY
```

## Layout
```
app/llm.py      the only module that talks to OpenAI; emits normalized events
app/routes.py   HTTP + SSE endpoints
app/db.py       SQLite connection + migrations
app/store.py    conversation/message CRUD
app/static/     vanilla JS UI (no build step)
tests/          pytest suite
docs/           architecture.md and per-phase notes
```
