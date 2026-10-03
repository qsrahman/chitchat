# Vendored libraries

The third-party code the page runs is copied into `app/static/vendor/`: no CDN (the Content-Security-Policy would block one, see `docs/small-improvements.md`) and no build step. That makes the app work offline and keeps a hostile CDN out of the page, but it also means nothing updates these files except you. `scripts/vendor.toml` records what each was copied from and at which version, and `scripts/vendor.py` checks and updates them.

| Library | Version | Used for | Source file in the npm package |
|---|---|---|---|
| [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.16 | Sanitizes everything rendered from model output. **The one that matters most.** | `dist/purify.min.js` |
| [marked](https://github.com/markedjs/marked) | 18.0.14 | Markdown to HTML | `lib/marked.umd.js` (the npm package has no minified build; it was misnamed `marked.min.js` before) |
| [highlight.js](https://highlightjs.org) | 11.12.0 | Syntax highlighting (the "common languages" build) | `@highlightjs/cdn-assets`: `highlight.min.js` |
| [KaTeX](https://katex.org) | 0.19.0 | Math | `dist/katex.min.js`, `dist/katex.min.css`, `dist/fonts/*.woff2` |
| [Open Props](https://open-props.style) | 1.7.23 | Design tokens (CSS variables) | six files from the package root, see the manifest |
| [axe-core](https://github.com/dequelabs/axe-core) | 4.13.0 | **Tests only**: the accessibility checker (`docs/accessibility.md`), kept in `tests/ui/assets/`, never served | `axe.min.js`, `LICENSE` |

All of these were verified byte for byte against the official npm packages, with **one deliberate edit**: KaTeX's stylesheet lists woff2, woff and ttf for every font, and the woff and ttf fallbacks were removed (and not shipped), since every current browser takes woff2. The edit is a named transform in `vendor.py`, so `check` and `update` reproduce it exactly.

## Checking
```
uv run python scripts/vendor.py check
```
For each library: do the files match the official package at the pinned version (anything changed, missing, or not in the manifest fails with exit code 1), and is there a newer release (information only). It needs the network, so the tests don't run it. As of 2026-10-03 everything is pristine and current. The math support (`markdown.js`) uses marked's extension API, so a major marked update needs the math, reasoning, sanitizer and incremental-render tests to pass again before it ships (they did for 16 to 18, with no code change; see `docs/round-3.md`).

## Updating
```
uv run python scripts/vendor.py update NAME          # to the latest
uv run python scripts/vendor.py update NAME 1.2.3    # to a given version
```
It downloads the package, writes the files, and bumps the version in `vendor.toml` (comments are kept). It deletes nothing: files the new version no longer has are listed for you to remove. Then: read the release notes, run `uv run pytest` (the UI tests cover math, code blocks, XSS and the CSP), and look at the page.

**How often:** DOMPurify is the library to watch. It exists because model output is untrusted, and its releases are mostly security fixes. Run `check` now and then, and whenever a DOMPurify advisory is published; the others can wait for a reason.

## What the tests guard (no network)
`tests/test_vendor.py` checks that the version in the manifest is the version each file declares in its own header, that every manifest file exists and every vendored file is in the manifest, that the page loads only vendored files (no CDN link), that the KaTeX stylesheet names only fonts that are shipped, and that the script itself works against a fake registry (changed, missing and unknown files, scoped package names, the KaTeX transform, `update` writing only inside `vendor/`).
