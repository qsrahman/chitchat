# Rendering model output

`app/static/markdown.js` turns reply text into sanitized HTML. Libraries (marked, DOMPurify, highlight.js, KaTeX) are vendored in `app/static/vendor/`.

- **Code:** fenced blocks get a header (language, Copy) and highlighting. highlight.js's plaintext mode doubles as the HTML escaper.
- **Math (KaTeX 0.19):** `\( inline \)`, `$inline$`, `\[ block \]` and `$$ either $$`. We use our own small `marked` extension because `marked` reads `\(` as an escaped paren and drops the backslash, and `marked-katex-extension` has no `\( \)`. Single `$` follows Pandoc's rule so prices stay text: the opening `$` needs a non-space after it, and the closing `$` a non-space before it and no digit after it. `$x$` and `$1 / \ln(x)$` are math; `$5 and $10`, `$20,000 and $30,000` and `$10-$20` are not. `\$` is a literal dollar sign. Known false positive: `5$ and 5$`-style text ("price is 5$ today" is fine, a pair of `N$` is not). An unfinished formula stays literal until its closing delimiter streams in. Code spans and fences are never math. KaTeX runs with `trust` off (no `\href` / `\url`), `throwOnError: false` (bad TeX shows as red text) and `maxSize: 20`. Only the woff2 fonts are shipped.
- **Reasoning:** `renderReasoning` uses a second `marked` instance without single-delimiter emphasis, see `docs/phase-5.md`.
- **Sanitizing:** DOMPurify after marked, with `<img>` forbidden (remote image URLs would leak requests) and `semantics` / `annotation` allowed, because KaTeX's accessible MathML wraps each formula in them and the TeX would otherwise show up as stray text. Links open in a new tab with `noopener`.
- **Not supported:** images in replies.

Tests: `tests/ui/test_math_ui.py`, `tests/ui/test_chat_ui.py` (sanitizing, code blocks), `tests/ui/test_reasoning_ui.py`.
