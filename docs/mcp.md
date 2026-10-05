# MCP: can ChitChat use MCP servers?

An exploration, not a feature. Looked into on 2026-10-05 against the OpenAI docs and the official MCP Python SDK (`mcp` 2.3.0, checked through Context7), with a throwaway spike (a real server and client on Python 3.14, outside the repository). Nothing in the app changed.

**Short answer: yes, and the local-client route fits ChitChat. It is a phase of its own (about the size of phase 7), and it should wait for two things the app does not have yet: sign-in, and a way to confirm a tool call.** A first slice that needs neither is possible; it is described at the end.

## Two ways in

### A. OpenAI's hosted MCP tool
The Responses API takes `{"type": "mcp", "server_label", "server_url", "allowed_tools", "require_approval", "authorization", "headers"}` and OpenAI's side connects to the server, lists its tools and calls them. Little code on our side. But:
- **OpenAI's servers make the connection**, so `server_url` must be reachable from the internet. A server on this machine (the usual case for MCP: a stdio process, or `localhost`) cannot be used. (The reference also lists a `tunnel_id` for a "Secure MCP Tunnel"; I did not find out what it needs.)
- **Only on OpenAI.** A custom `OPENAI_BASE_URL` (Ollama and the like) has no such tool, and this app is meant to work there.
- **Approvals are the model's loop, not ours.** With `require_approval` other than `"never"` the API returns `mcp_approval_request` items and waits for an `mcp_approval_response`: that is a new normalized event, a confirmation UI, and a second request per approval. With `"never"` the model calls the server unattended.
- **Statelessness:** the API returns an `mcp_list_tools` item that the docs say to keep in the input of later turns, or the tools are listed again. We send history as plain messages (`store=False`), so those items would have to be saved with the reply (a new `meta` field, a backup whitelist entry, and the compaction rules around it).
- Your data and the tool results go to OpenAI and to the server's owner. The connectors (Gmail, Calendar...) need OAuth tokens, which this app has no place to keep.

It is the right tool for a deployed ChitChat that wants a SaaS connector. It is the wrong one for local tools.

### B. A local MCP client inside ChitChat
ChitChat itself connects to the servers (stdio subprocesses or streamable HTTP), turns their tools into the `Tool` objects it already has (`app/tools/base.py`), and runs them in the tool loop it already has (`llm.stream_reply`). Works with any model that does function calling, including a local one, and nothing leaves the machine unless the server sends it.

**What the spike showed** (`mcp` 2.3.0, Python 3.14, a 3-tool `MCPServer` over stdio and over streamable HTTP):
- It works as the docs describe: `Client(StdioServerParameters(...))` or `Client("http://.../mcp")` as an async context manager, `list_tools()` (name, description, `input_schema`), `call_tool(name, args)` returning `content` blocks and `is_error`. Connecting to a stdio server took 0.28 s.
- **The mapping to our `Tool` is small:** `name` becomes `<server>__<tool>`, `input_schema` becomes `parameters`, and `run` is a function that calls `call_tool`, joins the text blocks, cuts them at a limit, raises `ToolError` for `is_error`, and wraps everything else (a dead server, a timeout) in a `ToolError` so a reply never fails because of a tool (the loop already does this for any exception).
- **Real schemas are not strict-mode schemas.** The server's own schema for a tool with an optional argument has `"required": ["name"]` and no `additionalProperties: false`, but `llm._tool_spec` sends every tool with `"strict": True`, which OpenAI rejects for such schemas. MCP tools need `strict: False`: a `strict` field on `Tool` (default true) that `_tool_spec` reads. The model may then send arguments that don't fit; the server validates them (the spike got a clear validation error back as a result) and the error goes to the model like any tool error.
- **A server that dies stays dead.** After killing the stdio process the next call failed at once (good) and kept failing: there is no reconnect, and closing the client at shutdown raised an `ExceptionGroup`. A real integration needs a supervisor: reconnect with backoff, and a shutdown that catches the group.
- **The cost of the dependency:** `mcp` brings 11 packages we do not have (`attrs`, `cffi`, `cryptography`, `jsonschema`, `jsonschema-specifications`, `mcp-types`, `pycparser`, `pyjwt`, `referencing`, `rpds-py`, `sse-starlette`); `cryptography`, `cffi` and `rpds-py` are compiled wheels. It installs on 3.14. The SDK's API changed between 1.x (`ClientSession`, `inputSchema`) and 2.x (`Client`, `input_schema`), so pin it and read the docs for the version.

## What it would take

**Config, not UI.** A stdio server is a command this machine runs. So servers are listed by the owner in `.env` (`MCP_SERVERS`, JSON in the shape other MCP clients use: `{"files": {"command": "...", "args": [...], "env": {...}}, "docs": {"url": "https://...", "headers": {...}}}`) and never added from the page: today anyone who can reach the port could do that, and it would be remote code execution. This is the main reason to wait for sign-in.

**Lifecycle.** Connect at startup (in the lifespan, with an `AsyncExitStack` and a timeout each), skip and log a server that fails, show each server and its tools (or its error) on the Server tab, reconnect a dead one, close cleanly. Tool lists are read once at startup (plus a manual "refresh" if wanted).

**In the registry.** `NAMES` is a fixed tuple that `ConversationSettings` validates against; MCP names are known only at runtime, so it becomes a function of the settings. The unit a user switches on per chat should be the **server** (`mcp:files`), one row in the Tools menu, not every tool of it (a server may have dozens, and each costs tokens in every request). Backup import already drops tool names it doesn't know, which is right when a server is gone.

**Exposure rules.** Each server in the config can carry an `allow` list; the default is nothing. A tool's `readOnlyHint` annotation is a hint from the server and not a boundary, so it can help a UI describe a tool but must not decide anything.

**Untrusted everything.** A tool's name, description and result come from someone else's code: descriptions are cut and shown as text, a result is cut (12,000 characters like the other tools) and labelled as data to use and not to obey, as `fetch_url` and `read_chat` already do. Images and embedded resources in a result are skipped with a note (a tool result is text here). The page shows a call generically (server, tool, arguments as text, never as markup), through the fallback `renderToolCall` already has for tools it doesn't know.

**Confirmation.** The tools so far only read. An MCP server can do anything (write files, send mail), so before a server with such tools is switched on there should be a confirmation per call: an `approval_request` event in the stream, a dialog, a POST that answers it, and the tool loop waiting for the answer. It is the largest piece, the one that benefits every future tool with side effects (`docs/tools.md`), and the real reason this is not a quick job.

**Tests.** The SDK can run a server in memory (`Client(server_object)`), so most tests need no process or port; one stdio test against a tiny script covers the subprocess path, and one covers a server that dies. Fixtures for hostile descriptions and results (markup, an instruction, a huge text, a non-text block).

**Size.** About one phase: a new module for the config, the connections, the adapter and the supervisor, changes to `tools/__init__.py`, `llm._tool_spec`, `routes` (the settings), the Tools menu and the Server tab, plus the tests and docs. The confirmation UI would be a second one.

## A first slice that needs neither sign-in nor confirmation
Read-only servers only, listed in `.env` by the owner (so no remote way to add a command), an explicit `allow` list per server, one switch per server in the Tools menu, off by default. That is useful on its own (documentation search, a read-only database, a filesystem server limited to one folder) and keeps the trust boundary where it is today: the owner decides what runs. It is still only safe for servers the owner trusts not to be hostile, because their output reaches the model.

## Decision
Not built. Recommended order: sign-in and the optional password (`PLAN.md` phase 9), then this first slice, then the confirmation UI, then servers with side effects. If a hosted SaaS connector is wanted sooner on OpenAI, route A is a smaller job than B for that one case, with the costs above.
