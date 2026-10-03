# Architecture

Flat backend: `config` (settings), `db`/`store` (SQLite, plain functions), `llm` (the only module that imports `openai`; emits our own normalized events), `routes` (HTTP + SSE), `static/` (vanilla JS UI).
`main` exposes only a `create_app()` factory, so importing it has no side effects; serve it with `uvicorn app.main:create_app --factory`.
Conversation state lives in our SQLite DB; every OpenAI call is stateless (`store=False`).
See the phase notes (`phase-N.md`) for what each phase added.

Request flow for a chat turn: `POST /api/conversations/{id}/chat` saves the user message, streams `llm.stream_reply` events as SSE, saves the assistant message on `done`, then emits a `title` event if the conversation is new.

Streaming uses FastAPI's own SSE support (`fastapi.sse.EventSourceResponse`): each chat endpoint is an async generator, FastAPI frames the yielded dicts as `data: {json}`, sends keepalive pings during long silences and sets `Cache-Control` / `X-Accel-Buffering` so proxies don't buffer. The request is validated and the turn is prepared in a dependency (`chat_turn`, `regenerate_turn`, `edit_turn` -> `Turn`), so errors there are normal HTTP errors. The browser side keeps a small frame splitter (`readSSE` in `static/chat.js`) because `EventSource` can't POST.

## Front end modules
`static/app.js` was one 1,100-line file; it is now an entry point plus one ES module per part of the page (loaded without a build step, so each import is a file the browser fetches; CSP allows only same-origin scripts). Libraries (marked, DOMPurify, highlight.js, KaTeX) are classic scripts that define globals, loaded before the module graph.

| Module | Owns |
|---|---|
| `app.js` | entry: loads the others, `openConversation`, the new-chat button, the hash route, boot |
| `core.js` | DOM handles, the one `state` object, `DEFAULT_SETTINGS`, `api()`, icons and small builders, dialogs helper, the `bus` |
| `messages.js` | the thread: building and rendering a message, the note, reasoning, scrolling, code-block copy |
| `tools-ui.js` | `TOOL_UI` (how each tool's call reads) and `renderToolCall` |
| `chat.js` | a turn: SSE reading, `runTurn`, message actions (copy, edit, regenerate, retry), submit and Escape |
| `composer.js` | the input box: send button state, auto-grow, drafts, attachments, the composer note |
| `controls.js` | thinking effort select, web search toggle, tools menu |
| `settings.js` | settings of the open chat (`setSettings`, `saveSettings`), the model list, the settings and instructions dialogs |
| `model-menu.js`, `retry-menu.js` | the header model picker, and the "try again with another model" menu |
| `list.js` | the sidebar's conversation list: paging, search, rename, pin and archive |
| `delete.js` | deleting a chat with ten seconds to undo it |
| `nav.js`, `shortcuts.js` | the drawer; the keyboard shortcuts |
| `backup.js` | the backup dialog and what an import says it did |
| `preferences.js` | the Settings dialog: tabs, appearance, shortcuts, custom instructions, the Server tab (`docs/settings-dialog.md`) |
| `markdown.js` | markdown to sanitized HTML (unchanged) |

**Rules that keep it from tangling again:**
- The import graph has no cycles: `core` is the base, `app.js` the top. Modules that would otherwise need each other talk through `bus` (an `EventTarget`): `settings` (the open chat's settings changed: the model button, effort select, search toggle, tools menu and settings dot all update from it), `models` (the model list was refreshed), and `open` (open a chat, used by delete so it doesn't import `app.js`), and `delete-chat` (a row's Delete button in `list.js` asks `delete.js`, which imports `list.js`, to start a delete).
- A module wires up its own part of the page when it loads (its listeners are at the top level). `app.js` only imports them, then starts.
- `tests/test_static_modules.py` checks, with no browser: every imported name is exported by its module, every import is used, no cycles, every module is reachable from `app.js`.
- To add UI: put it in the module that owns that part of the page; a new tool's display goes in `tools-ui.js`; a new setting's control goes in `controls.js` or `settings.js`.
