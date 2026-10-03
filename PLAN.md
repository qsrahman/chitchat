# PLAN

A ChatGPT-style web chat app on the OpenAI Responses API, built in small phases.
Every phase lands as **code + tests + `docs/phase-N.md` + one commit** (`phase N: <summary>`), and leaves the app working.

## Decisions
- **Stack:** Python 3.14, FastAPI, official `openai` SDK (`AsyncOpenAI`), SQLite via stdlib `sqlite3`, vanilla HTML/CSS/JS (no build step), pytest, `uv`.
- **State:** we own history in SQLite. Every OpenAI call is stateless (`store=False`, history sent as `input`), so edit, regenerate, branch, search and export stay under our control.
- **Modularity:** flat and small. Add a module only when a phase needs it.

## Architecture
```
app/
  main.py      create_app(): routes + static + lifespan
  config.py    Settings (env / .env; OPENAI_* names)
  db.py        sqlite connection + schema (PRAGMA user_version)
  store.py     plain functions: conversations + messages CRUD
  attachments.py  upload checks, files on disk, what the model gets per file
  tools/       tools the model can call, one module each (web_search via Brave, calculator, search_chats, fetch_url)
  llm.py       the ONLY module importing openai; emits normalized events
  routes.py    /api/* + SSE
  static/      index.html, app.js + one JS module per part of the page (see docs/architecture.md), markdown.js, style.css, vendor/
tests/         pytest + httpx ASGI client + FakeLLM
docs/          architecture.md, phase-N.md
```
Seams that keep features additive:
1. `llm.py` normalizes SDK events into ours (`delta`, `reasoning_delta`, `tool_call`, `done` with usage, `error`). Routes and the UI never see raw OpenAI events.
2. The LLM is injected (`app.state.llm`); tests swap in `FakeLLM`.
3. SSE over `POST` + `fetch` stream, one frame format: `data: {json}\n\n`.
4. `messages(id, conversation_id, role, content, meta JSON, created_at)`. `meta` carries attachments, tool calls and usage, so features don't force schema changes.
5. `store.py` is functions over a connection, with no ORM or repository classes.

## Phases
| # | Status | Deliverable |
|---|---|---|
| 0 | done | Scaffold: uv project, app factory, settings, `/healthz`, pytest harness |
| 1 | done | Streaming chat over SSE, markdown rendering, history in browser memory |
| 2 | done | SQLite persistence, conversation sidebar (create/list/rename/delete), auto-title, URL per conversation |
| 3 | done | Stop generation (partial message saved), regenerate, edit last user message, copy, retry |
| 3b | done | UI/UX polish (`docs/ui-polish.md`) and Playwright browser tests |
| 4 | done | Model picker, per-conversation system prompt, global custom instructions, temperature/reasoning effort |
| 5 | done | Reasoning summaries (collapsible), token usage recorded (not displayed) |
| 6 | done | Attachments: images (`input_image`), files/PDF (`input_file`) |
| 7 | done | Tools: built-in web search with citations, then a function-calling loop with a small registry (`app/tools/`) |
| 8 | done | Context management (OpenAI server-side compaction), FTS5 search, export (Markdown/JSON) |
| 9 | | Optional: auth, multi-user, rate limits, Dockerfile |

Phases 0 to 3 give a usable ChatGPT-lite. Phases 4 onward can be reordered.

## Testing
- Default suite makes no network calls: pytest + `httpx.ASGITransport` + temp SQLite + `FakeLLM`.
- One opt-in live test (`uv run pytest -m live`, needs `OPENAI_API_KEY`) checks event normalization against the real API.
- Frontend: Playwright (`pytest-playwright`, Chromium) in `tests/ui/`, against the real app on a free port with a `ScriptedLLM`. Any new UI behavior gets a test there. One-time setup: `uv run playwright install chromium`.

## Per-phase checklist
1. Write tests first where practical (API tests, plus a Playwright test for any UI change), then code.
2. `uv run pytest` green (includes the browser tests).
3. Run `uv run uvicorn app.main:create_app --factory --reload` and try the feature against the real API.
4. Add `docs/phase-N.md`, update the table above and the README feature list.
5. Commit.

## Future tools
Noted in `docs/tools.md` (get_time, Wikipedia/arXiv, weather, run_python, image generation, notes search, MCP, memory).

## Open items
- Single local user until phase 9, so there is no auth before then.
