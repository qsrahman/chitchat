# Development workflow

## One command
```
uv run python scripts/check.py
```
Runs, and stops at the first failure: `ruff` (Python lint), `pyright` (types, `app/` only, config in `pyproject.toml`), `prettier --check` (the format of the UI files, below), `eslint` (the JavaScript in `app/static`, when Node is installed), `tsc` (the same files, type-checked from their JSDoc; `docs/typescript-check.md`), and the whole test suite. About 30 seconds. The JavaScript lint is there because a missing import in the UI only shows when that line runs, and nothing else would find it (config: `eslint.config.mjs`; `tests/test_static_modules.py` checks import names without Node).

To run it before every commit, once per clone:
```
git config core.hooksPath .githooks
```
Skip it for one commit with `git commit --no-verify`. The hook is enabled in the maintainer's clone (since `docs/round-4.md`); a new clone has to run the command above. It checks the working tree, not just what is staged, so a half-finished file you are not committing can still fail it.

## Formatting the UI files
`prettier` formats everything in `app/static` except `vendor/`: the JavaScript, `style.css`, `index.html` and `types.d.ts`, with the settings in `.prettierrc.json` (no semicolons, single quotes, trailing commas, 2 spaces, 80 columns, LF). `check.py` only checks; to fix files:
```
npx prettier@3 --write app/static
```
Like eslint and tsc it runs through `npx` with a pinned major version, because the project has no Node manifest. It does not re-wrap comments. Formatting the CSS and the HTML (done after the JavaScript) turned the one-line rules of `style.css` into one declaration per line: 1,800 lines instead of 600, and a large diff with no change in behavior (the browser tests, including the accessibility and layout ones, pass unchanged).

## Tests
`uv run pytest` runs in parallel (`pytest-xdist`, `-n auto` in `pyproject.toml`): 653 tests in about 20 seconds on 14 cores, against about 150 serially (checked repeatedly for flaky tests; each test has its own database, files and server port). For one test or for debugging use `-n 0`:
```
uv run pytest -n 0 tests/ui/test_chat_ui.py -k retry
```
**The host's network changing.** If your Mac's network changes while the suite runs (Wi-Fi, a VPN, waking from sleep), Chromium fails requests, even to `127.0.0.1`, with `net::ERR_NETWORK_CHANGED`, and every browser test running at that moment fails with errors that say nothing about the app: console errors, a page that never became ready, timeouts. Those tests are now run again (up to twice, after two seconds), and only those: `tests/network_changed.py` turns a failure into `NetworkChanged` when the page saw that error or the error names it, and `--only-rerun NetworkChanged` (pytest-rerunfailures, in `pyproject.toml`) reruns exactly that. Any other failure is reported at once and never run twice, and a test that keeps failing is reported as `NetworkChanged: the host's network changed during the test ...` with the original failure in the message, so it can't be taken for an app bug. Rerun lines (`R`, "2 rerun") in the output mean it happened. Tested in `tests/test_network_changed.py` with small sub-runs.

`-m live` runs the tests that use real services (OpenAI or your local model, Brave, a real web page); they cost a little and are never part of the default run. Playwright needs `uv run playwright install chromium` once.

## A flaky test that was a bug (the pane at the end)
`test_a_reader_at_the_end_stays_there_when_the_message_box_grows` failed once in a busy full run (a 30 s timeout waiting for the end of the conversation) and passed on its own every time, also under CPU burners (12 of 12). It was not the test's timing but a race in `messages.js`: a reader at the end stays there through the resize observer, but the scroll handler decides "at the end" by the gap to the end, and a scroll event delivered after the message box had grown measured that gap against the smaller pane (100 px, past the 80 px that means "near") and took the reader to have scrolled up, so the observer left the pane where it was. The late event is the last scroll of a reply, which is how a slow machine makes it likely. The handler now ignores a scroll event while the pane's height differs from the one the observer last saw (the observer scrolls, then records it). `test_a_scroll_event_that_arrives_after_the_pane_shrank_...` sends that event in the same task as the growth, so the order is the one that failed, every time. It failed before the fix and passes after. No retry was added.

## Keeping things current
| What | Command | Notes |
|---|---|---|
| Vendored JS/CSS libraries | `uv run python scripts/vendor.py check` | `docs/vendor.md` |
| Known vulnerabilities in Python packages | `uv audit` (or `uvx pip-audit -r <(uv export --no-hashes)`) | Both reported none, in 52 packages |
| Outdated Python packages | `uv pip list --outdated`; update with `uv lock --upgrade-package NAME && uv sync` | Run the tests after: the OpenAI SDK moves fast |
| Real-service tests | `uv run pytest -m live` | needs the keys in `.env` |

State when last checked (2026-10-03): no known vulnerabilities in 56 packages; everything is current except `pydantic-core` (held by `pydantic`) and two transitive packages of Playwright (`pyee`, `python-slugify`).
