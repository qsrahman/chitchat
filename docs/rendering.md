# Rendering model output

`app/static/markdown.js` turns reply text into sanitized HTML. Libraries (marked, DOMPurify, highlight.js, KaTeX) are vendored in `app/static/vendor/`.

- **Code:** fenced blocks get a header (language, Copy) and highlighting. highlight.js's plaintext mode doubles as the HTML escaper.
- **Math (KaTeX 0.19):** `\( inline \)`, `$inline$`, `\[ block \]` and `$$ either $$`. We use our own small `marked` extension because `marked` reads `\(` as an escaped paren and drops the backslash, and `marked-katex-extension` has no `\( \)`. Single `$` follows Pandoc's rule so prices stay text: the opening `$` needs a non-space after it, and the closing `$` a non-space before it and no digit after it. `$x$` and `$1 / \ln(x)$` are math; `$5 and $10`, `$20,000 and $30,000` and `$10-$20` are not. `\$` is a literal dollar sign. Known false positive: `5$ and 5$`-style text ("price is 5$ today" is fine, a pair of `N$` is not). An unfinished formula stays literal until its closing delimiter streams in. Code spans and fences are never math. KaTeX runs with `trust` off (no `\href` / `\url`), `throwOnError: false` (bad TeX shows as red text) and `maxSize: 20`. Only the woff2 fonts are shipped.
- **Reasoning:** `renderReasoning` uses a second `marked` instance without single-delimiter emphasis, see `docs/phase-5.md`.
- **Sanitizing:** DOMPurify after marked, with `<img>` forbidden (remote image URLs would leak requests) and `semantics` / `annotation` allowed, because KaTeX's accessible MathML wraps each formula in them and the TeX would otherwise show up as stray text. Links open in a new tab with `noopener`.
- **Not supported:** images in replies.

Tests: `tests/ui/test_math_ui.py`, `tests/ui/test_chat_ui.py` (sanitizing, code blocks), `tests/ui/test_reasoning_ui.py`.

## Streaming long replies: only the last block is re-rendered
**The problem, measured.** A reply that is streaming used to be rendered again in full for every frame. Streaming realistic markdown (paragraphs, lists, code blocks, math) at a steady pace through the real page, with the main thread watched for long tasks:

| Reply size | Main thread blocked, before | after | Longest freeze, before | after |
|---|---|---|---|---|
| 5,000 characters | 0 s | 0 s | none | none |
| 20,000 | 0.1 s | 0.1 s | 53 ms | 114 ms (the final render) |
| 50,000 | 5.9 s of 10 s | 0.3 s | 142 ms | 256 ms (the final render) |
| 100,000 | 15.3 s of 19.4 s | 0.5 s | 280 ms, 119 times | 505 ms, once (the final render) |

Where the time went (one render of 100,000 characters): sanitizing 137 ms, replacing the DOM and laying it out 72 ms, lexing and parsing together only 21 ms (including highlighting and math). So the cost was in sanitizing and inserting blocks that had not changed, and the page was unresponsive (scroll, Stop) during a long answer.

**The fix** (`renderBlocks` in `markdown.js`, used by `messages.render`). The text is lexed (cheap) into top-level blocks, and the DOM of the blocks whose text is unchanged since the last frame is kept; from the first block that differs, the rest is removed and made again. While a reply streams only its last block changes, so a frame costs the size of that block, not of the whole reply. A side effect: text you select, or a code block you hover, in a finished part of a streaming reply is no longer thrown away every frame.

**It has to give the same HTML as rendering everything**, so `tests/ui/test_incremental_render_ui.py` streams 15 tricky documents (a setext heading that only appears when its underline arrives, a paragraph that turns into a table, lists continued across blank lines, reference links defined at the very end, unterminated code, partial and display math, hostile HTML, right-to-left text, Windows line endings) in steps of 1 to 61 characters and compares with a full render **after every step** (over 2,000 comparisons), for replies and for reasoning text, plus text that jumps around (edit, regenerate). One known case is handled on purpose: a reference link definition arriving later changes how earlier paragraphs read without changing their text, so any change in the set of definitions starts afresh. Other tests check that a long stream sanitizes about one block per update (not hundreds) and that the first block is still the same element after hundreds of updates.

**One full render at the end.** When a stream finishes, the reply is rendered once in full with nothing reused (`renderFresh`), so what is saved is exactly what a reload shows (tested). That is the single remaining freeze in the table above: 114 ms at 20,000 characters, about half a second at 100,000, once.

**Not done / limits:** a very long single block (a 20,000-line code block, one enormous list item) is still re-rendered whole each frame, because it is one block; a reply of that shape would need highlighting that continues instead of restarting. This was not measured: the benchmark's blocks are ordinary sized, so how bad a single huge block is remains unknown.
