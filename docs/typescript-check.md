# Type-checking the UI

The UI stays plain JavaScript with no build step (so what the browser loads is the file in the repository). `tsc` checks it anyway: `jsconfig.json` turns on `checkJs`, and `scripts/check.py` runs it after eslint (`npx -p typescript@7 tsc -p jsconfig.json`, about 1 second).

## What is checked
- **What the server sends.** `app/static/types.d.ts` describes a conversation, a message and its `meta`, the stream events of a turn (`StreamEvent`), the model and tool lists and `GET /api/config`. `readSSE` yields `StreamEvent`, so in `runTurn` a field that does not exist on that event (`ev.mdoel`, `ev.cnt`) is an error. Nothing loads the file; it is for the compiler.
- **The shared state** (`state`, `DEFAULT_SETTINGS`, `modelInfo`), and the message element with the raw text, model, versions and attachments kept on it (`MessageEl`).
- **`null`** (`strictNullChecks`): `querySelector` can return nothing, a pending delete may not exist, a response may have no body.

## What is not
- `$("id")` returns `any`. The ids are in `index.html` and an input, a button and a dialog need different types, so it can't be typed without a map of every id; a wrong id still shows only when that line runs.
- `noImplicitAny` is off: it reports 191 places (every `(m) =>` callback), nearly all of them noise next to the 21 real `null` findings.
- `api()` returns `any`, so a response read through it is as typed as the line that annotates it.
- The vendored libraries (`marked`, `hljs`, `katex`, `DOMPurify`) are declared as `any`.

## Adding to it
A new field in a response or event: add it to `types.d.ts` in the same change. A new element property on a message: add it to `MessageEl`. The checker's own version is pinned to 7 in `scripts/check.py`, like eslint.

First run: the code needed no behavior change. The fixes were annotations and casts (`/** @type {NodeListOf<HTMLElement>} */`), a typed `pending` in `delete.js` and the retry menu's `anchor` and `onPick`, a guard for a response with no body in `readSSE`, and `getTime()` for the date difference in `list.js`.
