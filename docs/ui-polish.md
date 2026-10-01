# UI/UX polish + Playwright tests

Done between phases 3 and 4.

## Design
Reading-first. Replies are set in a serif face (Charter / Iowan Old Style / Georgia) with no bubbles, so long answers read like a document. Your messages and the interface use the system sans, and code uses the system monospace. One blue accent, light and dark themes through `light-dark()` (follows the system setting).

## What changed
- **Layout:** sidebar with conversations grouped by recency (Today, Yesterday, Previous 7 days, Older), a slim top bar with the conversation title, a centered reading column, and a composer with a send/stop button. Under 760px the sidebar becomes a drawer.
- **Empty state:** "What are you working on?" with four starter prompts.
- **Rename / delete:** native `<dialog>` (focus trap, Esc, light dismiss where supported) replaces `prompt()` and `confirm()`. Delete defaults focus to "Keep it".
- **Replies:** thinking indicator before the first token, markdown re-rendered once per frame, syntax-highlighted code blocks with a language label and Copy button, links open in a new tab with `noopener`.
- **Scrolling:** the view follows the stream only while you are at the bottom. If you scroll up, it stays put and a "Jump to latest" button appears.
- **Security:** model output is sanitized with DOMPurify and `<img>` is removed entirely: a remote image URL in a reply would make the browser send requests, and whatever the URL encodes, to a third party. Revisit when image output becomes a feature.
- **Notes:** "Stopped." and "Reply cut off: output limit reached." show under the reply and persist (from `messages.meta`).
- **Keys:** Enter sends, Shift+Enter adds a line, Esc stops a reply.
- **Accessibility:** `role="log"`, `aria-busy` while streaming (no per-token announcements), labelled icon buttons, visible focus, reduced-motion respected.
- **Offline:** `marked`, `DOMPurify` and `highlight.js` are vendored in `app/static/vendor/` (no CDN). Source versions: marked 16.4.2, DOMPurify 3.4.16, highlight.js 11.11.1.
- **Code layout:** `static/markdown.js` (render + sanitize + code blocks) and `static/app.js` (everything else), loaded as ES modules without a build step.

## Tests
`tests/ui/` drives the real app in Chromium with Playwright (`pytest-playwright`). `tests/ui/conftest.py` serves the app with uvicorn on a free port and a `ScriptedLLM` whose reply depends on a keyword in the prompt (`slow`, `long`, `code`, `xss`, `fail`, `cutoff`). Any JS or console error fails the test.

One-time setup: `uv run playwright install chromium`. Run only the UI tests with `uv run pytest tests/ui`.
