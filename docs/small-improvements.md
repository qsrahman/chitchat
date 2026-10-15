# Small improvements

A batch of four, each its own commit.

## 1. A small model for chat titles
Titles were written by the default model (`gpt-5.5`, a reasoning model) for six words. `TITLE_MODEL` now picks the model; empty means `gpt-5.4-mini` on OpenAI (it was `gpt-5.4-nano` at first; both took about a second for a title), or the default model when `OPENAI_BASE_URL` is set (the one chosen in Settings, else `OPENAI_MODEL`: `docs/round-10.md`), because a custom endpoint (Ollama) doesn't have OpenAI's model names and every title call would fail (`Settings.title_model_for`). Measured on one title: `gpt-5.5` 3.0 s, `gpt-5.4-nano` 1.1 s, `gpt-5.4-mini` 1.0 s. A title model that can't be reached still falls back to the first words of the message, as before. Tests: `tests/test_settings.py`.

## 2. The model list is cached for five minutes
`GET /api/models` listed models from the provider on every call: on page load, whenever the picker opens, and in the background when the settings dialog opens. That is a remote call each time. `OpenAILLM.list_models` now remembers a successful answer for `MODELS_TTL` (300 s). A failed listing is never remembered, and once the time is up a failing endpoint gives `[]` again (so the picker reports the problem) instead of an old list passing as current. The cache lives in the `OpenAILLM` object, so a restart or a changed `OPENAI_BASE_URL` starts fresh. Tests: `tests/test_llm.py`.

## 3. Right-to-left text
Urdu, Arabic and Hebrew now align and flow correctly, per block, without a setting:
- The message box, search box, title, rename field and the settings textareas have `dir="auto"`, so their direction follows the first strong character typed. Your sent messages, error lines, sidebar titles, search results and tool-call lines do too.
- Rendered replies get `dir="auto"` on the **outermost** text block (paragraph, heading, list, quote, table) in the sanitizer hook in `markdown.js`. An Arabic paragraph runs right to left while an English paragraph in the same reply stays left to right. Only outermost blocks, because the browser skips descendants that carry their own `dir` when it looks for the first strong character, so a list whose items each had `dir` found no text and stayed left to right (a bug caught by the tests).
- Code blocks are always `dir="ltr"`.
- Layout uses logical properties where text is concerned (`padding-inline-start`, `border-inline-start`, `text-align: start`), so list markers and the quote bar move to the right side of right-to-left text. A right-to-left block is placed at the right edge of the column with `:dir(rtl)`, because a narrow block is positioned by its container's direction, not its own.
- The chrome (sidebar, composer controls, the streaming edge) stays left to right: the interface language is English.
Not done: a right-to-left interface layout and KaTeX in right-to-left text beyond what the browser does. Tests: `tests/ui/test_rtl_ui.py`.

## 4. Security headers
Every response now carries (`SecurityHeaders` in `app/main.py`, a plain ASGI middleware, not `BaseHTTPMiddleware`, whose wrapping of streams can interfere with a dropped connection cancelling a reply, which is how Stop works):
- **`Content-Security-Policy`:** `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`. It is defence in depth for the case that model output or an uploaded file ever gets past the sanitizer: injected inline scripts, inline event handlers and scripts from other origins don't run, requests can only go to this origin, and the page can't be framed. `'unsafe-inline'` is allowed for styles only, because KaTeX writes `style` attributes; `data:` is for the favicon and `blob:` for attachment previews.
- `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` (for browsers that predate `frame-ancestors`), and a `Permissions-Policy` that turns off camera, microphone and location.
- A route's own value wins: the attachment route keeps its stricter `Content-Security-Policy: sandbox`.
- Not set: HSTS (the app is plain HTTP on localhost; add it with TLS when deploying, phase 9).

**What this means for changes:** the page has no inline scripts and none may be added; libraries stay vendored (no CDN, which `CLAUDE.md` already said, and now the browser enforces it); no `eval`/`new Function`; an inline `style="..."` in markup is allowed, an inline `<script>` or `onclick="..."` is not. A CSP violation shows up as a console error, which fails the UI tests, so a change that breaks the policy is caught (the whole UI suite, math, code, previews and dialogs included, runs under it). Tests: `tests/test_security_headers.py`, `tests/ui/test_csp_ui.py` (injected script, foreign script, inline handler and foreign request are all blocked and reported).
