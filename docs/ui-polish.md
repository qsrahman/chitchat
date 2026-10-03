# UI/UX polish + Playwright tests

Done between phases 3 and 4.

## Design
Reading-first. Replies have no bubbles, so long answers read like a document (they were first set in a serif face; see "Font" below). The whole UI uses one system sans stack, and code uses the system monospace. One blue accent, light and dark themes through `light-dark()` (follows the system setting).

## What changed
- **Layout:** sidebar with conversations grouped by recency (Today, Yesterday, Previous 7 days, Older), a slim top bar with the conversation title, a centered reading column, and a composer with a send/stop button. The sidebar is closed by default (toggle button in the top bar). On wide screens it pushes the content aside and stays open while you switch chats; under 760px it is an overlay drawer that closes when you pick a chat.
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

## Second pass: findings from chatgpt.com
Looked at the logged-out chatgpt.com (desktop and mobile, light and dark, the menus, a composer being typed in, and one short conversation) and applied what fits.

| Seen on chatgpt.com | Here |
|---|---|
| The home screen is a hero: heading, composer and suggestions as one centered group; the composer drops to the bottom only once a chat starts | Same. `main:not(.is-started)` centers the group; `is-started` restores the pinned composer |
| Composer is a ~52px pill (28px radius) with a layered soft shadow, and the send button is dim until there is text | Raised pill (`--raised`), same shadow recipe, send disabled-style when empty |
| The composer reflows as it grows: one row for one line; with more, the text takes the full width and the buttons drop to a row below | `is-multiline`, set in `syncComposer()`. It also reflows for wrapped text, and stays reflowed until the box is empty so it can't flip-flop |
| Suggestions are quiet icon rows under the composer, without dividers | Same |
| The closed sidebar is a narrow icon rail, not nothing | Closed = 3.5rem rail (toggle, new chat, custom instructions); open = full list. Still closed by default. Mobile keeps the overlay drawer |
| Message actions are icon-only buttons with tooltips | Copy, Edit and Regenerate are icon buttons (`aria-label` + `title`); Copy shows a check and "Copied" briefly. Retry keeps its text label because it appears on an error |
| The scroll-to-bottom control is a round icon button above the composer | Round button anchored to the top of the form, so it never overlaps a tall composer |
| Unsent text survives a reload | Drafts kept in `localStorage` per conversation (and for the new-chat screen), cleared on send |

Not applied: the model-selector popover in the header (a larger change; settings stay in the dialog), the `+` attach and tools menu (phases 6 and 7), dictation, login upsells, and ChatGPT's all-sans typography (the serif reading face stays on purpose).

Tests: `tests/ui/test_layout_ui.py`.

## Header model picker
The header shows the model the conversation uses ("gemma4:cloud ⌄") and opens a menu to switch it, as ChatGPT's header does.

- **Behavior:** choosing a model saves it to the conversation's settings and applies from the next message. On the new-chat screen it is held until the first message creates the chat. Choosing the default row stores `null`, so the chat keeps following the default. Each conversation keeps its own model; a new chat starts on the default.
- **Menu:** the configured default first (tagged "default"), then what the endpoint lists (reasoning models tagged "reasoning"), then "Chat settings…". A saved model that is no longer listed is still shown, checked and tagged "not listed". The list is fetched when the page loads and again each time the menu opens.
- **Failures:** a failed save shows "Couldn't switch model…" in the menu and keeps the old model. If `/api/models` can't be reached the button reads "Model" until the menu is opened and the list loads.
- **Implementation:** the Popover API (`popover` + `popovertarget`, light dismiss, Escape, focus returns to the button) and a real `role="menu"` with the keyboard contract (arrows, Home, End, Tab leaves). The menu is placed under the button from `app.js`, because CSS anchor positioning is not widely available yet. It is kept inside the viewport on phones.
- **Header:** the conversation title now sits after the model button in a quieter weight, and is hidden on the new-chat screen. A long model name is truncated so the settings button stays on screen.
- The settings button's dot now means "something other than the model is customized", since the model has its own button. The settings dialog and the picker share one model list and stay in sync.

Tests: `tests/ui/test_model_picker_ui.py`.

## Design tokens and a polish pass (Open Props)
[Open Props](https://open-props.style) is vendored in `static/vendor/open-props/` (MIT; only the files used: `sizes`, `shadows`, `easings`, `fonts`, `zindex`, about 11 KB). It is CSS custom properties only: no classes, no build, no JavaScript. The colors stay ours (`light-dark()` palette in `style.css`); Open Props supplies the scales:
- **Radii:** two steps built from `--size-*`: `--r-sm` (controls, 8px) and `--r-lg` (containers: menus, dialogs, code blocks, bubbles, 16px); pills use `--size-5/6`. Previously there were nine different values (5 to 28px).
- **Elevation:** `--shadow-2` (composer, 3 when focused), `--shadow-3` (jump button), `--shadow-4` (menu), `--shadow-5` (dialogs). The tokens switch to stronger shadows in dark mode themselves, which the hand-written ones didn't, so dark-mode popovers and dialogs now lift off the page.
- **Type:** `--font-size-*`, `--font-weight-*`, `--font-lineheight-*` for headings, the hero and the answer text, plus two local steps (`--text-sm` .875rem for secondary text, `--font-size-0` .75rem for the smallest) replacing five near-identical sizes (.78 to .9rem). Headings use `text-wrap: balance`, answer text `pretty`.
- **Motion:** one shared transition (`--ease-out-3`) for hover and press states, a small scale on `:active`, entrances for the model menu and dialogs and a fade for new messages via `@starting-style` (closing is instant). All of it is off under `prefers-reduced-motion`.
- **Layers:** `--layer-*` for the drawer, scrim and drop overlay.
- **Also:** `--bubble` (a step above the page, for sent messages, inline code and attachment tiles: they were hard to tell apart from the page in dark mode), consistent focus rings on fields, a thin scrollbar, `accent-color`, `::selection`.

Spacing and the remaining pixel paddings were left as they are: they are layout, not a scale problem, and converting them is churn. No markup or JavaScript changed, and no test needed changing.

## Composer controls: search and thinking effort
The globe (web search) is always shown; it is disabled, with a tooltip, when the server has no search key, instead of being hidden. Next to it, models that take a reasoning effort get a "Thinking effort" select (Auto, None, Minimal, Low, ... from the SDK's own list; "None" is the way to turn thinking off, if the model allows it). It is a native `<select>`, so it is accessible and works on mobile with no custom popover; it saves the same per-conversation `reasoning_effort` as the chat settings dialog, and the two stay in sync. Models that take a temperature instead don't show it (temperature stays in the dialog). Whether reasoning *summaries* are requested is still the server switch `OPENAI_REASONING_SUMMARIES`. On narrow screens the composer always uses the stacked layout (text above, controls below) so the controls don't squeeze the input.

## Second look at chatgpt.com and chat.qwen.ai
Logged out, in the built-in browser (the logged-in features, like the composer's plus menu on ChatGPT, are behind a sign-in). What was seen, and what was done with it:

| Finding | Done |
|---|---|
| Qwen puts the thinking mode as a labelled dropdown (Auto / Thinking / Fast) at the right of the composer, next to Send, not among the attach/tool icons | The thinking-effort select moved there. Left side: attach and web search; right side: thinking, then Send. With a long message it sits on the bottom row beside Send |
| Both greetings are plain sans text, about 24px, weight 400 (ChatGPT: 24/28px, 400) | The greeting is sans, `--font-size-4`, weight 400, instead of 2rem serif. The serif stays for replies |
| ChatGPT's controls are 44px targets (rail buttons, Scroll to bottom, sign-in); ours were 30 to 36px | On touch screens (`pointer: coarse`) icon buttons, Send, the effort select and the jump button are at least 44px, and sidebar rows are taller |
| Qwen's model menu has a "Model" heading and roomy rows (and a one-line description per model) | Heading added and rows padded more. No descriptions: the API gives none, and inventing them would be wrong |
| Qwen gathers attachments and tools (web search, deep research...) in one plus menu with a toggle | Not done. We have two tools-like controls, and a menu would hide web search one click deeper and break its visible on/off state; revisit if more tools arrive |
| Qwen frames the whole app as an inset rounded card; ChatGPT shows 3 suggestions, a dimmed disabled Send, a hover pill on the model button | Not done: the frame is decoration, and the rest is already how ours behaves |

Tests: `tests/ui/test_reference_ui.py`.

## Removed: suggestions and the keyboard hint
The four example prompts under the new-chat composer and the "Enter to send, Shift+Enter for a new line. Esc stops a reply." line are gone (earlier sections above that mention suggestions describe the past). The shortcuts themselves still work: Enter sends, Shift+Enter adds a line, Esc stops a reply. The home screen is now the greeting and the composer.

## Send button hover
Hovering (or keyboard-focusing) the enabled send/stop button fades in a moving gradient: the accent, purple, pink and orange, flowing continuously while the pointer stays (`--spark-1..4` in `style.css`, lighter in dark mode so the dark arrow stays readable). It is a `::before` layer under the icon, so the fade is a normal opacity transition; the flow is a looping `background-position` animation that is paused at rest, so nothing runs when the button isn't hovered. A disabled button doesn't react. With `prefers-reduced-motion` the gradient still appears but doesn't move. Tests: `tests/ui/test_send_hover_ui.py`.

## Font
chatgpt.com loads no web font (`document.fonts` is empty). Its computed stack is the OS interface font: `-apple-system-body, ui-sans-serif, -apple-system, system-ui, "Segoe UI", Helvetica, "Apple Color Emoji", Arial, sans-serif, "Segoe UI Emoji", "Segoe UI Symbol"`, which on this Mac renders San Francisco; body 16px, weight 400, `text-rendering: optimizeLegibility`, antialiased. That stack is now `--sans` and is used for everything, **replies included**: the serif reading face is gone (the earlier "ChatGPT's all-sans typography is not applied" decision is reversed). Replies are 16px / 1.75 line height. `-apple-system-body` (Safari's Dynamic Type) was left out: it makes sizes follow the OS text-size setting in Safari only, and ours are fixed. Code keeps the monospace stack. Because it is a system font, the look follows the platform: SF on Apple devices, Segoe UI on Windows, and the platform sans on Linux or Android.

## Identity pass
Brief: ChitChat is a personal workbench for a developer who reads long answers, code and math for hours. Scope chosen: keep the ChatGPT-like layout and system font, give it an identity of its own.
- **Palette:** warm graphite and paper instead of cool grey-blue, and one deep teal accent instead of the stock blue. Light: page and sidebar `#f3f1ee`, conversation sheet `#fcfbfa`, ink `#201e1c`, accent `#0f7b6c`. Dark: warm charcoal `#141312` / `#1b1a19` (never pure black), accent `#5fd0bc`. Shadows take the same warm hue (`--shadow-color`). The send button's hover gradient starts from the accent (teal, blue, pink, amber). Favicon follows.
- **Measure:** answer paragraphs, lists and quotes stop at `62ch` (about 75 characters of text), while code blocks, tables and math use the whole column. Longer lines tire the eye over a long session.
- **The one distinctive element: the edge of the reply being written.** A 2px teal edge in the margin of the streaming reply says "still in progress" and fades when it is done, which is the only place the accent carries meaning. A failed reply gets a red edge in the same place. It lives on the text block, in the margin, so text doesn't shift.
- **Quiet elsewhere:** nothing decorative was added; sidebar, menus and dialogs keep the one radius scale and the elevation tokens. Strong text is weight 600 and links get a thin, offset underline.
Not done, on purpose: a second typeface (the system stack was requested), and tinting math blocks (the code block is already the one tinted surface).
Tests: `tests/ui/test_identity_ui.py`.
