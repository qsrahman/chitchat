# CLAUDE.md

ChitChat: a ChatGPT-style web chat app on the OpenAI Responses API. Built in phases; the roadmap and status are in `PLAN.md`, the design in `docs/architecture.md`.

## Commands
```
uv run uvicorn app.main:app --reload   # dev server on :8000
uv run pytest                          # default suite, no network
uv run pytest -m live                  # real OpenAI API, needs OPENAI_API_KEY
```

## Layout
- `app/llm.py`: the only module that imports `openai`. It yields our normalized events (`delta`, `done`, `error`, ...).
- `app/routes.py`: HTTP and SSE endpoints. `app/main.py` is the `create_app()` factory.
- `app/db.py` and `app/store.py` (from phase 2): SQLite schema and plain CRUD functions.
- `app/static/`: vanilla JS UI, no build step.

## Conventions
- Work one phase at a time, as in `PLAN.md`. A phase is code + tests + `docs/phase-N.md` + one commit titled `phase N: <summary>`. Update the `PLAN.md` status table and the README feature list in the same commit.
- Keep it flat. No ORM, no repository classes, no new abstraction until a phase needs it. Don't hand-roll what the stdlib, FastAPI, pydantic or the openai SDK already provide.
- Every OpenAI call is stateless: `store=False`, with history sent as `input`. Don't use `previous_response_id` or the Conversations API.
- Don't leak raw OpenAI events past `llm.py`. For a new feature, add a normalized event type there and handle it in `routes.py` and `app.js`.
- Wire format is SSE over `POST`: `data: {json}\n\n`.
- Tests must not touch the network. Inject `FakeLLM` through `app.state.llm` (see `tests/conftest.py`). Mark real-API tests `@pytest.mark.live`.
- Anything the model or a user supplies is untrusted. Render assistant markdown through `DOMPurify`, and set user text with `textContent`.
- Config comes from `Settings` (env / `.env`). Never commit `.env` or `*.db`.
- Check current OpenAI SDK and API details in the docs (Context7) instead of relying on memory. The SDK moves fast.
