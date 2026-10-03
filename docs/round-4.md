# Round 4

Three small changes, each its own commit.

## 1. The tools are a package
The single tools file had grown to 503 lines: four tools, the web-address safety code, a calculator parser and an HTML-to-text parser in one file. It is now `app/tools/`:

| File | Holds |
|---|---|
| `base.py` | `Tool`, `ToolResult`, `ToolError`, `bound_to` (the shared types) |
| `brave.py` | `web_search` |
| `calc.py` | `calculator` and its `ast` evaluator |
| `chats.py` | `search_chats` |
| `fetch.py` | `fetch_url`: address checks, pinned connection, redirects, HTML and PDF reading (223 lines, the part worth reviewing on its own) |
| `__init__.py` | `NAMES`, `build()`, and re-exports so `tools.fetch_url`, `tools.ToolError` and the rest still work |

Each tool module has a `make(settings)` that builds its `Tool` (schema, guidance) next to the function it runs, so adding a tool is one new module plus a line in `build()` and `NAMES`. Behavior is unchanged: the moved code is the same text, and the 843 tests passed afterwards. Only the tests that patch a limit changed (`monkeypatch.setattr(tools.fetch, "FETCH_BYTES", ...)`, because a limit is now read in the module that uses it, not in the package). `routes.py` (about 430 lines) was not split: it is one flat list of endpoints and helpers with no part that is reviewed on its own, so a split would only add files.
