# Development workflow

## One command
```
uv run python scripts/check.py
```
Runs, and stops at the first failure: `ruff` (Python lint), `pyright` (types, `app/` only, config in `pyproject.toml`), `eslint` (the JavaScript in `app/static`, when Node is installed), and the whole test suite. About 20 seconds. The JavaScript lint is there because a missing import in the UI only shows when that line runs, and nothing else would find it (config: `eslint.config.mjs`; `tests/test_static_modules.py` checks import names without Node).

To run it before every commit, once per clone:
```
git config core.hooksPath .githooks
```
Skip it for one commit with `git commit --no-verify`.

## Tests
`uv run pytest` runs in parallel (`pytest-xdist`, `-n auto` in `pyproject.toml`): 653 tests in about 20 seconds on 14 cores, against about 150 serially (checked repeatedly for flaky tests; each test has its own database, files and server port). For one test or for debugging use `-n 0`:
```
uv run pytest -n 0 tests/ui/test_chat_ui.py -k retry
```
`-m live` runs the tests that use real services (OpenAI or your local model, Brave, a real web page); they cost a little and are never part of the default run. Playwright needs `uv run playwright install chromium` once.

## Keeping things current
| What | Command | Notes |
|---|---|---|
| Vendored JS/CSS libraries | `uv run python scripts/vendor.py check` | `docs/vendor.md` |
| Known vulnerabilities in Python packages | `uv audit` (or `uvx pip-audit -r <(uv export --no-hashes)`) | Both reported none, in 52 packages |
| Outdated Python packages | `uv pip list --outdated`; update with `uv lock --upgrade-package NAME && uv sync` | Run the tests after: the OpenAI SDK moves fast |
| Real-service tests | `uv run pytest -m live` | needs the keys in `.env` |

State when last checked (2026-10-03): no known vulnerabilities in 56 packages; everything is current except `pydantic-core` (held by `pydantic`) and two transitive packages of Playwright (`pyee`, `python-slugify`).
