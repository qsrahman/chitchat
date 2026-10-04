# CLAUDE.md

ChitChat: a ChatGPT-style web chat app on the OpenAI Responses API. Built in phases; the roadmap and status are in `PLAN.md`, the design in `docs/architecture.md`.

## Commands
```
uv run uvicorn app.main:create_app --factory --reload   # dev server on :8000
uv run python scripts/check.py        # ruff + pyright + prettier + eslint + tsc + all tests, ~20s: run before committing (docs/development.md)
uv run pytest                          # API + Playwright UI tests, no network, in parallel (-n 0 for one process)
uv run pytest tests/ui                 # UI tests only (needs: uv run playwright install chromium)
uv run pytest -m live                  # real OpenAI API, needs OPENAI_API_KEY
```

## Layout
- `app/llm.py`: the only module that imports `openai`. It yields our normalized events (`delta`, `done`, `error`, ...).
- `app/routes.py`: HTTP and SSE endpoints. `app/main.py` is the `create_app()` factory.
- `app/attachments.py`: upload classification (from bytes), files on disk, PDF text, and `for_model()`, which turns a stored attachment into what `llm.py` sends. `llm.py` builds the API input parts.
- `app/tools/`: tools the model can call, one module each (`brave`, `calc`, `chats`, `fetch`: the function plus a `make(settings)` that builds its schema; `base` has `Tool`, `ToolResult`, `ToolError`). Functions return `ToolResult(output, display)`. `llm.stream_reply` runs the tool loop; a new tool is a module like those, listed in `build()` and `NAMES` in `__init__.py`. See `docs/phase-7.md` and `docs/tools.md` (calculator, search_chats, fetch_url and its SSRF rules: any change to `_fetch` in `tools/fetch.py` must keep its tests passing).
- Context management is OpenAI's server-side compaction, not our own summarizing: `llm.py` asks for it, `routes._history` starts from the latest saved compaction item. See `docs/phase-8.md`.
- Instructions sent to the model = `DEFAULT_SYSTEM_PROMPT` (config.py) + custom instructions + the conversation's system prompt + tool guidance, built in `routes._model_options`. See `docs/default-prompt.md`. Test `Settings` use `default_system_prompt=""`.
- Context: OpenAI compacts (`docs/phase-8.md`); on a custom `OPENAI_BASE_URL` the oldest turns are left out of the request past `CONTEXT_TOKENS` (`app/context.py`, `docs/context-window.md`). Compaction items are only ever sent to OpenAI.
- `app/backup.py`: export all (JSON, or a zip with the attachment files) / import (validated, all-or-nothing, never overwrites; files from a zip are re-checked from their bytes; `docs/backup.md`). A change to what a message's `meta` holds must update its whitelist there.
- `app/storage.py`: what is kept on disk, and the two deletes on request (files nothing uses, archived chats untouched for N days; `docs/storage.md`).
- `app/db.py`: SQLite connection and migrations (append to `MIGRATIONS`). `app/store.py`: plain CRUD functions. Messages are a tree (`parent_id`, `conversations.leaf_id`): `store.list_messages` is the path to the leaf, editing or regenerating adds a sibling, and nothing deletes single messages (`docs/branching.md`).
- `app/static/`: vanilla JS UI as ES modules, no build step: `app.js` (entry) plus one module per part of the page, listed in `docs/architecture.md`. `tests/test_static_modules.py` checks that every import resolves, is used, and that there are no cycles. Libraries are vendored in `static/vendor/` (including the Open Props design tokens used by `style.css`: radii, shadows, type, easing); libraries are listed and checked in `scripts/vendor.toml` / `docs/vendor.md` (add one there, update with `scripts/vendor.py`); don't add CDN links, inline `<script>` or `onclick=` (a Content-Security-Policy in `main.py` blocks them; `docs/small-improvements.md`). Rendering rules (math, reasoning text, sanitizing) are in `docs/rendering.md`.
- The UI is type-checked with `tsc` from JSDoc (`jsconfig.json`, `app/static/types.d.ts`, `docs/typescript-check.md`): a change to a response or SSE event is changed in `types.d.ts` too. There are no `.ts` files and no build step.
- The UI files (JS, CSS, HTML, `types.d.ts`; not `vendor/`) are formatted by prettier (`.prettierrc.json`: no semicolons, single quotes, 80 columns); `check.py` fails on an unformatted file. Fix with `npx prettier@3 --write app/static` (`docs/development.md`).
- Accessibility: `tests/ui/test_a11y_ui.py` runs axe over every state and must stay at zero violations. New overlays/menus go inside `<main>`, anything that scrolls needs `tabindex="0"`, colors need 4.5:1 (`docs/accessibility.md`).
- `tests/ui/`: Playwright tests against the real app with a `ScriptedLLM` (`tests/ui/conftest.py`).

## Conventions
- Work one phase at a time, as in `PLAN.md`. A phase is code + tests + `docs/phase-N.md` + one commit titled `phase N: <summary>`. Update the `PLAN.md` status table and the README feature list in the same commit.
- Keep it flat. No ORM, no repository classes, no new abstraction until a phase needs it. Before writing a helper, check what already exists and use it, even if a hand-rolled version would be a line shorter: stdlib and JS builtins, FastAPI (e.g. `fastapi.sse`), pydantic, the openai SDK (types such as `ReasoningEffort`, and `httpx.MockTransport` for testing it), Playwright (`wait_for_function`, not polling loops), highlight.js / marked / DOMPurify / KaTeX. Keep a hand-written piece only when nothing covers it, and say why in a comment.
- Per-conversation settings live in `conversations.settings` (JSON, defaults in `store.DEFAULT_SETTINGS`); app-wide ones in `app_settings`. Add a setting by extending `ConversationSettings` (routes.py) and `DEFAULT_SETTINGS`, then pass it through `_model_options` and `llm.stream_reply`.
- Every OpenAI call is stateless: `store=False`, with history sent as `input`. Don't use `previous_response_id` or the Conversations API.
- Don't leak raw OpenAI events past `llm.py`. For a new feature, add a normalized event type there and handle it in `routes.py` and `static/chat.js`.
- Wire format is SSE over `POST`, produced by FastAPI: chat endpoints are generators with `response_class=EventSourceResponse`, each yielded dict becomes `data: {json}`. Checks that must be real HTTP errors (404, 409, 422) go in dependencies (`chat_turn` etc.), because once a generator endpoint starts streaming it is too late to change the status.
- Every UI behavior change comes with a Playwright test in `tests/ui/`. Console errors fail those tests.
- Build `Settings` in tests with `_env_file=None` so the developer's real `.env` can't leak in.
- Tests must not touch the network. Inject `FakeLLM` through `app.state.llm` (see `tests/conftest.py`). Mark real-API tests `@pytest.mark.live`.
- Anything the model or a user supplies is untrusted. Render assistant markdown through `DOMPurify`, and set user text with `textContent`.
- Config comes from `Settings` (env / `.env`). Never commit `.env` or `*.db`.
- Check current OpenAI SDK and API details in the docs (Context7) instead of relying on memory. The SDK moves fast.
