# Five mock UIs to choose from

ChitChat's UI is a hand-built take on ChatGPT's. To see what else is possible, popular chatbots were looked at (2026-10-09) and five different looks were drawn from them, as static pages in `design/mockups/`. They are mocks: nothing talks to a model, and nothing in `app/` uses them. Open the chooser:

```
open design/mockups/index.html
```
(or, from that folder, `python3 -m http.server 8140` and `http://localhost:8140/`). It shows the five side by side, with a switch for the screen (a chat, a new chat), the colors (system, light, dark) and an open menu (tools, the chat's ⋯ menu); each preview opens full size, and **Choose** marks a pick (kept in that browser) and offers "go with Folio" to paste into the chat.

## What was looked at
Signed out, in a browser, with the computed sizes read from the page; plus teardowns and docs for what is behind a sign-in.

| Product | Worth taking | Seen |
|---|---|---|
| ChatGPT | The reference ChitChat started from: thread list, pill composer, canvas as a second pane. | Measured earlier |
| Claude | A serif for what is written and a quiet sans for controls; a side panel for artifacts; Projects. The sign-in page sets a 56px serif at weight 300 on near-black (#151515). | Login page; the app from public descriptions |
| Gemini | A light greeting (36px, weight 320), a tall pill composer with the model chip and the microphone inside it, tonal surfaces, an icon-only rail, "Show thinking" and sources as chips. | Measured: #0f0f0f, Google Sans Flex |
| Perplexity | Answer first: the question as the heading, a "completed steps" row, source cards before the answer, domain chips with +N on claims, a sources tab or panel, follow-up questions, "wrong sources" as its own feedback; scope chips beside the composer. | Measured: #161616 / #1d1d1d, 16px radius, 640px wide; teardowns |
| T3 Chat | Speed as design: a tinted dark (#21141e), one inset rounded panel, category pills over starter prompts, a model chip with capability icons, ⌘K. | Measured |
| Grok | Almost no chrome: one heading, "/" for slash commands, one mode selector, a round send button. | Measured |
| Open WebUI, LibreChat | A controls panel with the system prompt, temperature and effort; presets; changing model mid-chat; branching. | Docs and reviews |
| Copilot, Le Chat | Not seen past a sign-in page and a bot check (which was left alone). | — |

Sources: [Perplexity's citations, aiuxplayground](https://aiuxplayground.com/teardowns/perplexity/citations), [conversational AI UIs, intuitionlabs](https://intuitionlabs.ai/articles/conversational-ai-ui-comparison-2025), [Open WebUI and LibreChat](https://docs.openwebui.com/alternatives/librechat.md).

## The five
Every mock shows the same conversation (a web search, reasoning, a code block, sources, token counts, versions "2 / 3", a reply still streaming) and the features ChitChat has today: the tools menu with its six default tools and web search off, the model picker, the chat's ⋯ menu with "Instructions for this chat", pinned and recent chats, Settings and Archived. Fonts are system fonts, so nothing is downloaded.

| Mock | Looks like | Takes | The catch | To build |
|---|---|---|---|---|
| **Folio** (`design/mockups/folio.html`) | An editorial reading room: paper on a darker desk | Serif for the model's text, numbered citation chips, a Sources panel that opens beside the answer | Calm but not dense; leans on system serifs | Medium: CSS, and a panel from the web search results already saved with a reply |
| **Canvas** (`design/mockups/canvas.html`) | Soft and tonal: no borders, huge radii, a gradient greeting | A pill composer with everything inside, "Show thinking" and "Searched the web" chips, recent chats as tiles | Roomy, so fewer messages per screen | Medium: CSS, an avatar, the tiles |
| **Cite** (`design/mockups/cite.html`) | An answer engine: each question a titled section | Steps, source cards, domain chips on claims, tabs for Answer / Sources / Steps, "Ask next", tools as scope chips | The biggest change to how a message is built; small talk looks odd; "Ask next" needs a model call or is left out | Large: restructure messages into sections, a tabs view |
| **Bench** (`design/mockups/bench.html`) | A workbench: history, conversation and controls panes, dense | Every message labelled with who and when, a tool trace, a context meter, temperature / effort / system prompt always visible, versions as tabs | Built for wide screens; less welcoming | Large: a controls panel, a message gutter, a context estimate from the server |
| **Swift** (`design/mockups/swift.html`) | Keyboard first, almost no chrome, a plum-tinted dark | ⌘K palette for chats and actions, slash commands (`/calc`, `/read`, `/web`) instead of a tools menu, starter prompts by category, shortcuts on every control | A new palette and slash parsing need an accessibility pass; the tint is a strong look | Medium: a palette module, slash parsing, CSS |

None of them changes what the app does. Whichever is chosen would be built the way the earlier UI changes were: the existing modules and tests kept, the look swapped, the layout moved only where the design needs it, and the accessibility test (`tests/ui/test_a11y_ui.py`) held at zero violations. The mocks use `?view=chat|new`, `?theme=light|dark` and `?open=tools|model|menu|palette` in their address so any state can be linked to.

## Choosing
Look at the chooser, then say which one (or which parts of which: "Cite's source cards in Folio's layout" is fine), and it gets built as a series of small commits. If none is right, say what is missing and the mocks can be redrawn.
