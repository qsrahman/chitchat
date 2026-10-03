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

## 2. The pre-commit hook is on
`git config core.hooksPath .githooks` is set in this clone, so every commit runs `scripts/check.py` (ruff, pyright, eslint, the whole suite; about 30 seconds) and is refused if it fails. Checked by trying to commit a file with an unused import: the commit was refused with the ruff output. This setting lives in `.git/config`, not in the repository, so a fresh clone has to run the command again (`docs/development.md`). The hook tests the working tree, not the staged files, so unrelated unstaged changes count; `--no-verify` skips it.

## 3. Measuring one huge block
The open question in `docs/rendering.md` was how the page behaves when a reply is one enormous block, which the block-reuse trick cannot help. `scripts/bench_render.py` now holds the benchmark (it only existed in a scratch folder before) and takes a shape: `mixed` (the original), `code`, `list` or `para`. The numbers are in `docs/rendering.md`. Short version: fine to about 1,000 lines in one block; a code block of 20,000 lines blocks the page for 28 of 32 seconds but in half-second pieces; one 20,000-line list item freezes it for 35 s at once. No fix: that needs roughly 100,000 output tokens in one block. The fix to reach for, if it is ever needed, is described there.

## Also: five tests that raced
The first commit attempt with the hook on was refused by `test_disconnect_before_any_text_saves_no_reply`, which failed once under load (it passed six times in a row afterwards). Five tests cancelled a request after `asyncio.sleep(0.1)`, hoping the fake model had reached its "hang" by then. `FakeLLM` now sets `hanging` when it gets there and the tests wait for that, so they no longer depend on the machine's speed. (Found because the hook runs the suite while other things are running.)
