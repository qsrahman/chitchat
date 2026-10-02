# ChitChat

A ChatGPT-style web chat app built on the [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses). It is built in small phases, and each phase adds code, tests, docs and a commit. See [PLAN.md](PLAN.md) for the roadmap.

## Features
- Streaming replies (SSE) with markdown rendering
- Saved conversations in SQLite, sidebar with new/rename/delete, auto-generated titles, shareable `#<id>` links
- Stop generation (partial reply kept), regenerate, retry, edit the last message, copy
- Reading-focused UI: serif replies, highlighted code with copy, typeset math (KaTeX), light/dark theme, mobile drawer, smart autoscroll
- Model picker, per-conversation system prompt, reasoning effort or temperature, and global custom instructions
- Reasoning summaries in a collapsible block, and token usage under each reply
- Planned: attachments, web search and tools, search and export

## Requirements
Python 3.14+, [uv](https://docs.astral.sh/uv/), and an OpenAI API key. For the browser tests, run `uv run playwright install chromium` once.

## Run
```bash
cp .env.example .env   # set OPENAI_API_KEY
uv run uvicorn app.main:create_app --factory --reload
```
Open http://127.0.0.1:8000.

## Configuration
Environment variables or `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | | OpenAI credentials |
| `OPENAI_MODEL` | `gpt-5.5` | Model for chat replies and titles |
| `OPENAI_BASE_URL` | SDK default | Point at a proxy or compatible endpoint |
| `OPENAI_MAX_RETRIES` | `2` | SDK retries on transient errors |
| `OPENAI_MAX_OUTPUT_TOKENS` | none | Cap on tokens per reply; a reply that hits it is kept and flagged |
| `OPENAI_REASONING_SUMMARIES` | `true` | Ask reasoning models for a summary of their thinking; set `false` if your OpenAI organization isn't verified for it |
| `DB_PATH` | `chitchat.db` | SQLite file |

## Test
```bash
uv run pytest            # API + browser (Playwright) tests, no network, fake LLM
uv run pytest tests/ui   # browser tests only
uv run pytest -m live    # hits the real API, needs OPENAI_API_KEY
```

## Layout
```
app/llm.py      the only module that talks to OpenAI; emits normalized events
app/routes.py   HTTP + SSE endpoints
app/db.py       SQLite connection + migrations
app/store.py    conversation/message CRUD
app/static/     vanilla JS UI, ES modules, vendored libs (no build step)
tests/ui/       Playwright browser tests
tests/          pytest suite
docs/           architecture.md and per-phase notes
```
