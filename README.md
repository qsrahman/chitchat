# ChitChat

A ChatGPT-style web chat app built on the [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses). It is built in small phases, and each phase adds code, tests, docs and a commit. See [PLAN.md](PLAN.md) for the roadmap.

## Features
- Streaming replies (SSE) with markdown rendering
- Saved conversations in SQLite, sidebar with new/rename/delete, auto-generated titles, shareable `#<id>` links
- Stop generation (partial reply kept), regenerate, retry, edit the last message, copy any message (yours or a reply) on its own
- Reading-focused UI: ChatGPT's system font stack, highlighted code with copy, typeset math (KaTeX), light/dark theme, centered new-chat composer that reflows as you type, icon rail sidebar, mobile drawer, smart autoscroll, drafts that survive a reload
- Storage in Settings: sizes, deleting unused files and old archived chats (`docs/storage.md`)
- Token counts on each reply and for the chat (`docs/token-usage.md`)
- Model picker in the header, per-conversation system prompt, reasoning effort or temperature, and a Settings dialog (appearance, defaults for new chats, shortcuts, custom instructions, export and import, and what the server is set up with: `docs/settings-dialog.md`)
- Reasoning summaries in a collapsible block
- Attachments: images, PDFs and text files via the + button, drag and drop or paste
- Composer controls: web search on/off (globe) and thinking effort (for reasoning models; "None" turns thinking off)
- Web search (Brave) the model can use while answering, shown with its results; a small tool registry for more
- Tools menu (per chat): a calculator for exact arithmetic, search over your past chats, and a page reader for links (public sites only). See `docs/tools.md`
- Long chats keep working: past a token threshold OpenAI compacts the older turns server-side (`COMPACT_THRESHOLD`); on a local model the oldest turns are left out of the request instead (`CONTEXT_TOKENS`), with a note
- Full-text search across all conversations (sidebar; titles and messages, a result opens at the matching message), and export of a chat as Markdown or JSON (the chat's ⋯ menu); editing a message or regenerating a reply keeps the old one as a version you can switch back to ("2 / 3"); "try again with another model" on a reply; light, dark or system appearance in Settings; deleting a chat can be undone for a few seconds; the chat list loads a page at a time; Cmd/Ctrl+K searches and Cmd/Ctrl+Shift+O starts a new chat (`docs/polish-2.md`)
- Backup: export every chat, every version of your messages and your custom instructions as one JSON file, or as a zip that also holds the attachment files (or a zip of Markdown to read), and import it back without overwriting anything; the database is copied before an upgrade and `scripts/restore_db.py` goes back to a copy (`docs/backup.md`, `docs/round-6.md`, `docs/round-8.md`)

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
| `OPENAI_PDF_INPUT` | `text` | `text` extracts a PDF's text and sends that (any model); `file` sends the PDF itself (OpenAI) |
| `ATTACHMENTS_DIR` | `attachments` | Where uploaded files are stored |
| `TITLE_MODEL` | small OpenAI model, or `OPENAI_MODEL` on a custom endpoint | Model that writes chat titles |
| `DEFAULT_SYSTEM_PROMPT` | built-in (date, display format) | Prompt sent before custom instructions; empty sends none; `{date}` is today. See `docs/default-prompt.md` |
| `COMPACT_THRESHOLD` | `150000` | Tokens after which OpenAI compacts the older turns of a conversation (OpenAI only); `0` turns it off |
| `CONTEXT_TOKENS` | `32000` on a custom endpoint, none on OpenAI | Most history to send without compaction; older messages are left out (not deleted) and a note says so. `0` = no limit. See `docs/context-window.md` |
| `BRAVE_API_KEY` | none | Enables web search (Brave Search API). Without it the globe button in the composer is disabled |
| `LOG_LEVEL` | `INFO` | Server log lines (requests, replies, tool calls, each with a request id; never message text). `WARNING` keeps only problems. `docs/round-3.md` |
| `MAX_TOOL_CALLS` | `8` | Most tool calls in one reply, over all tools (each web search is billed by Brave, about half a cent) |
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
app/attachments.py  upload validation, file storage, PDF text
app/tools/      tools the model can call, one module each (web search, calculator, search_chats, fetch_url)
app/static/     vanilla JS UI, ES modules, vendored libs (no build step)
tests/ui/       Playwright browser tests
tests/          pytest suite
docs/           architecture.md and per-phase notes
```
