# Phase 7: tools and web search

The model can call tools during a reply. The first tool is `web_search`, backed by the [Brave Search API](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started). It is a function tool run by this app, not OpenAI's hosted web search, so it works with any model that supports function calling: OpenAI, and the local models tried here (`gemma4:cloud`, `gpt-oss:20b`, `qwen3.5:9b`).

## Setup
Put a Brave key in `.env`: `BRAVE_API_KEY=...`. Without it the tool isn't offered and the globe button is shown disabled, with a tooltip saying why. Brave bills per request (one request per search); at the time of writing an account gets $5 of free credit a month, about 1,000 searches. `MAX_TOOL_CALLS` (default 4) caps the searches in one reply.

## Using it
The globe button in the composer switches web search on or off for the conversation (off by default, saved with the conversation like the model). While it's on, the model decides when to search. A search shows above the answer as "Searching the web for “...”…", then "Searched the web for “...” · 6 results", which opens to titles, domains and snippets. The model is told to cite what it uses as inline markdown links, so the answer carries its own sources, and those links stay in the history for later turns.

## How it works
- **`tools.py`:** a registry. A `Tool` is a name, a JSON schema (written for OpenAI's strict mode), an async function and optional `guidance` for the instructions. The function returns `ToolResult(output, display)`: `output` is what the model reads, `display` is what the UI shows. `ToolError` is for failures worth telling the model and the user (a bad key, a rate limit, no connection); its message must not hold secrets. `build(settings)` returns the tools that are configured, and `NAMES` lists every tool the app can have. To add a tool: write the function, register it in `build()`, add a `TOOL_UI` entry in `app.js` (unknown tools still get a plain line), and add its name to `NAMES`.
- **The loop (`llm.stream_reply`):** with tools, each round streams a response; if the model made function calls they run in order and their results go back with the model's own output items (reasoning items included, and `reasoning.encrypted_content` is requested for reasoning models, since calls are stateless), then the next round starts. It ends when the model answers. Bounded by `MAX_TOOL_CALLS` per reply (calls past it get an error result so the model answers with what it has) and by a round limit. Usage is summed over the rounds. Text from before a tool call is separated from the answer by a paragraph break. A tool that raises never fails the reply: the model gets "Error: ..." and the UI shows the failure.
- **Events:** `{"type": "tool_call", id, name, arguments, status: running | done | error, display | error}`. The route keeps the last event per id and saves them in the message's `meta.tools`; a call still running when the reply is stopped is saved as `stopped`.
- **Settings:** `settings.tools` is a list of tool names (validated against `tools.NAMES`, de-duplicated). A tool that is saved but not configured right now is ignored, not an error, so removing the key never blocks saving other settings. `GET /api/tools` lists what is usable.

## Safety and cost
- Search results are untrusted web content: the text given to the model says so, and the guidance tells it never to follow instructions found in results.
- Result URLs only become links if they are `http` or `https` (checked by the tool and again by the UI); titles and snippets are only ever set as text; links open in a new tab with `noopener`. HTML markup and entities in Brave's snippets are stripped.
- The API key is sent only to Brave, and never appears in error messages.
- Each search adds tokens to the context (results go back to the model), which the usage line shows.

## Not included
- OpenAI's hosted `web_search` tool (it only works on OpenAI models and bills per call).
- Fetching a result's full page: results are Brave's snippets. A fetch tool would need SSRF protection.
- Numbered citation chips: the model's inline links are used as they are.
- Brave's separate "LLM Context" endpoint: its documentation page wasn't reachable when this was built, so the documented Web Search endpoint is used.

## Tests
`tests/test_tools.py` (Brave against a mocked API), `tests/test_llm.py` (the loop against mocked streams), `tests/test_tool_calls.py` (settings, what the model receives, what is saved), `tests/ui/test_search_ui.py`. Live (`-m live`): the loop against the real API with a stand-in search tool, and a real Brave search (skipped without a key).
