# Development workflow

## One command
```
uv run python scripts/check.py
```
Runs, and stops at the first failure: `ruff` (Python lint), `pyright` (types, `app/` only, config in `pyproject.toml`), `prettier --check` (the JavaScript format, below), `eslint` (the JavaScript in `app/static`, when Node is installed), `tsc` (the same files, type-checked from their JSDoc; `docs/typescript-check.md`), and the whole test suite. About 30 seconds. The JavaScript lint is there because a missing import in the UI only shows when that line runs, and nothing else would find it (config: `eslint.config.mjs`; `tests/test_static_modules.py` checks import names without Node).

To run it before every commit, once per clone:
```
git config core.hooksPath .githooks
```
Skip it for one commit with `git commit --no-verify`. The hook is enabled in the maintainer's clone (since `docs/round-4.md`); a new clone has to run the command above. It checks the working tree, not just what is staged, so a half-finished file you are not committing can still fail it.

## Formatting the JavaScript
`prettier` formats `app/static/*.js` (not `vendor/`) with the settings in `.prettierrc.json`: no semicolons, single quotes, trailing commas, 2 spaces, 80 columns, LF. `check.py` only checks; to fix a file:
```
npx prettier@3 --write "app/static/*.js" "app/static/early/*.js"
```
Like eslint and tsc it runs through `npx` with a pinned major version, because the project has no Node manifest. Comments are not re-wrapped by it, and the types in `app/static/types.d.ts` and the HTML and CSS are not formatted.

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
