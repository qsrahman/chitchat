# The docs

One file per phase or change, so the history of a decision sits next to the code it changed. This page says which to read for what. The design as it is now is in [architecture.md](architecture.md); [PLAN.md](../PLAN.md) has the roadmap and status.

## To work on the project
| Read | For |
|---|---|
| [architecture.md](architecture.md) | the backend modules, the front-end modules and how they talk, the wire format |
| [development.md](development.md) | `scripts/check.py`, tests, formatting, keeping dependencies current, the host's network changing mid-run |
| [typescript-check.md](typescript-check.md) | how the UI is type-checked without a build step |
| [accessibility.md](accessibility.md) | the bar (axe over every state), contrast, focus, what to do for a new overlay |
| [vendor.md](vendor.md) | the vendored libraries and how to update them |

## Features
| Read | For |
|---|---|
| [settings-dialog.md](settings-dialog.md) | Settings: General (appearance, defaults for new chats), Personalization, Data controls, Server |
| [ui-mockups.md](ui-mockups.md) | five mock UIs drawn from research on popular chatbots, to choose from (`design/mockups/`, not part of the app) |
| [folio.md](folio.md) | the chosen look applied to the app: paper sheet on a desk, serif replies, ink-blue accent, the Sources panel and citation chips |
| [find-in-chat.md](find-in-chat.md) | Mod+F: find text inside the open chat, painted with the CSS Custom Highlight API |
| [ui-review.md](ui-review.md) | the ⋯ chat menu, "Instructions for this chat", recent chats, the resizable sidebar, and the two review passes behind them |
| [backup.md](backup.md) | export and import, what travels (chats, versions, files, instructions, defaults) and what never overwrites |
| [storage.md](storage.md) | sizes, deleting unused files and old archived chats |
| [token-usage.md](token-usage.md) | the counts on each reply and for a chat |
| [branching.md](branching.md) | versions of a message, `2 / 3`, and where switching lands |
| [tools.md](tools.md) | calculator, search_chats, fetch_url and its safety rules, the date, chat and file tools, and the tools still to build |
| [mcp.md](mcp.md) | whether ChitChat can use MCP servers: two routes, what a spike showed, what it would take (not built) |
| [cli.md](cli.md) | plugging a CLI in: as an HTTP client of the server, or in-process after moving the chat logic out of `routes.py` (noted, not built) |
| [default-prompt.md](default-prompt.md) | the instructions the model always gets, and why |
| [context-window.md](context-window.md) | long chats on a model without compaction |
| [rendering.md](rendering.md) | markdown, math, code, reasoning text, sanitizing, the render time budget |

## The phases, in order
[phase-0](phase-0.md) scaffold, [phase-1](phase-1.md) streaming chat, [phase-2](phase-2.md) persistence and the sidebar, [phase-3](phase-3.md) chat controls, [phase-4](phase-4.md) settings, [phase-5](phase-5.md) reasoning and usage, [phase-6](phase-6.md) attachments, [phase-7](phase-7.md) tools and web search, [phase-8](phase-8.md) long conversations, search and export. These describe what each phase built; where the UI has changed since, the file says so and points to the newer one.

## The rounds after them
Batches of small changes, each change its own commit. They are the record of why something is the way it is.

| Read | What it holds |
|---|---|
| [ui-polish.md](ui-polish.md) | the first look-and-feel pass and the browser tests (between phases 3 and 4) |
| [small-improvements.md](small-improvements.md) | a small model for titles, the model list cache, right-to-left text, security headers |
| [polish-2.md](polish-2.md) | the paged conversation list, the docs-path test, keyboard shortcuts |
| [round-3.md](round-3.md) | older attachments not re-sent, pyright, logging, undo for delete, theme, library updates |
| [round-4.md](round-4.md) | the tools package, the pre-commit hook, the huge-block benchmark |
| [round-5.md](round-5.md) | the flaky-test sweep, the render time budget, branching |
| [round-6.md](round-6.md) | a database copy before an upgrade, try again with another model, attachments in the backup |
| [round-7.md](round-7.md) | switching back to a version, pin and archive, pruning old database copies |
| [round-8.md](round-8.md) | the scale benchmark, splitting the sidebar module, restoring a database copy |
| [round-9.md](round-9.md) | type-checking the UI, defaults for new chats, a better Markdown export |
| [round-10.md](round-10.md) | defaults in the backup, titles follow the default model, reruns for network changes |

Prettier for the UI files, token usage, storage and the UI review each have their own page above instead of a round.
