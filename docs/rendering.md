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

**Limits: one huge block.** The saving above comes from reusing finished blocks, so a reply that is mostly one block gets none of it. Measured (`scripts/bench_render.py`, the same method; 14-core Mac, Chromium, the stream alone takes about as long as "ideal"):

| One block of | Characters | Main thread blocked while streaming | Longest freeze |
|---|---|---|---|
| code, 1,000 lines | 65,000 | 0 s | none |
| code, 5,000 lines | 337,000 | 4.5 s of 7.8 s | 115 ms |
| code, 20,000 lines | 1,390,000 | 28.5 s of 32.3 s | 482 ms |
| one paragraph, 5,000 lines | 330,000 | 7.5 s of 10.6 s | 262 ms |
| one paragraph, 20,000 lines | 1,300,000 | 41.4 s of 44.8 s | 2.8 s |
| one list item, 1,000 lines | 65,000 | 0.8 s | 104 ms |
| one list item, 5,000 lines | 340,000 | 12.4 s of 13.7 s | 2.1 s |
| one list item, 20,000 lines | 1,400,000 | 80.4 s of 81.8 s | **35 s** |

So: up to about 1,000 lines (65,000 characters, roughly 20,000 tokens, which is a very long answer) a single block is fine. A code block stays tolerable for a long way (the page is sluggish, not frozen: the longest task at 20,000 lines is half a second). A single enormous **list item** is the bad case, 35 s in one freeze at 20,000 lines, and gets worse faster than linearly, which I did not investigate (likely the browser's layout of one very tall item, not our code). The cost of one render of a code block is linear in its size: at 5,000 lines it is 83 ms, of which sanitizing is 64, highlighting 21 (the lexing is nothing), so each frame costs that much again as the block grows.

**The render time budget (round 5) halves most of that.** A render over 16 ms now makes the next one wait twice as long as it took (`schedule` in `messages.js`), so rendering uses at most about a third of the main thread however big the block is; renders under 16 ms (ordinary replies, every row of the first table) never wait. Same benchmark, main thread blocked while streaming, before to after:

| One block of | Blocked, before | after | Longest freeze, before | after |
|---|---|---|---|---|
| code, 5,000 lines | 4.5 s | 1.8 s | 115 ms | 120 ms |
| code, 20,000 lines | 28.5 s | 11.5 s | 482 ms | 468 ms |
| one paragraph, 5,000 lines | 7.5 s | 3.0 s | 262 ms | 272 ms |
| one paragraph, 20,000 lines | 41.4 s | 19.2 s | 2.8 s | 3.0 s |
| one list item, 5,000 lines | 12.4 s | 6.6 s | 2.1 s | 2.3 s |
| mixed, 100,000 characters | 0.5 s | 0.6 s | 505 ms | 563 ms |

The longest single freeze does not change: it is one render of the whole block, which a wait cannot shorten (only not rendering a block that big while it streams would). The stream takes a little longer to appear in full (7.8 s to 9.0 s for 5,000 lines of code) because the last pieces wait for their turn; the end of the stream always renders at once. The one-list-item case at 20,000 lines was not measured again (it took 80 s before).

**What it means:** replies of that size need about 100,000 output tokens, which few models produce, and none of the models this app is aimed at do by default (`OPENAI_MAX_OUTPUT_TOKENS` is unset, so the model's own limit applies). I judged it not worth fixing now. The general fix, capping the share of the main thread rendering may take, is done (below); what is left is the single longest freeze, which only stopping the work on a block that big while it streams (plain text until the end) would shorten.
