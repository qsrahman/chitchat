# More tools: calculator, search_chats, fetch_url

Three tools were added to the registry from phase 7 (`app/tools.py`). They need no API key. Like web search they are off by default and switched on per conversation: web search keeps its globe in the composer, and the others are in the **Tools** menu (wrench icon, left of the text box), a checkbox each with a one-line hint. `GET /api/tools` lists every usable tool as `{name, label, hint}`. The loop, the per-reply call cap (`MAX_TOOL_CALLS`), the guidance added to the instructions while a tool is on, and the UI line per call all work as described in `docs/phase-7.md`.

## calculator
Exact arithmetic: models are unreliable at long multiplication, percentages and compound interest, and the answer shows in the reply as `17 * 23 = 391`.
- The expression is parsed with `ast` and walked by a small evaluator that accepts only numbers, `+ - * / // % **`, parentheses, `pi`, `e`, `tau` and a list of `math` functions (`sqrt`, trig, `log`, `exp`, `gcd`, `factorial`, `comb`, `perm`, `round`, `min`, `max`...). Names, attributes, calls to anything else, strings, comparisons and comprehensions are refused, so nothing reaches the interpreter. (No dependency covers this; `eval` is not an option.)
- Bounded: expressions over 500 characters, integer results over 10,000 bits, `**` that would exceed that (checked before computing, so `9**9**9` is an error and not a hang), `factorial`/`comb`/`perm` over 1,000, complex results and infinities are errors. Division by zero and domain errors are reported to the model, which can correct itself.
- `^` is XOR in Python, so it is refused with a message to write `**`. Floats are shown to 15 significant digits (`0.1 + 0.2` is `0.3`).

## search_chats
The model searches your saved conversations (`store.search_conversations`, the phase 8 FTS5 index) when you refer to something said before ("what did we decide about X?"). It returns the best match from each matching conversation with its title, date, who wrote it and a longer snippet (up to 6). In the UI the matches are links to those chats. Past messages can contain pasted web pages, so the result is labelled as information, not instructions. It searches the user's *other* conversations: the chat it runs in is already in front of the model, so it is left out. A tool that needs to know which chat it runs in declares `per_chat=True` and takes a `conversation_id`; the route binds it for each reply with `tools.bound_to`, so the shared tool object is never changed. Titles are searched too (a title-only match is reported as such).

## fetch_url
Reads one web page or PDF: the readable text, 12,000 characters at a time (about 3,000 tokens). The usual follow-up to a search result.

**Long pages come in parts.** The tool has an `offset` argument (null for the start). A page longer than one part ends with "[The page continues: call fetch_url again with offset=N to read on (M more characters).]", and the model passes that N to get the next part. Each part says which characters it is ("characters 12,000 to 24,000 of 128,038"); concatenating the parts gives the whole text exactly, with nothing lost or repeated (tested). The page is fetched again for each part (the tool keeps no state), and the UI shows "12,000 characters read from character 12,000 of 128,038; there is more".

**PDFs** (`application/pdf`) are read as text with the same `pypdf` code the attachments use (`attachments.pdf_to_text`), the first 100 pages, in a worker thread. A PDF may be up to 10 MB (a PDF is much bigger than the text in it) and is refused, not read half, above that; a pages limit, a scan with no text, a password-protected or malformed file each give a clear error. The title shown is the file name. pypdf parses untrusted files here, bounded by the size, page and time limits, which is the same exposure an uploaded PDF already is.

It is the one tool that makes this server connect to an address a model chose, so it is built defensively (all in `tools._fetch`):
- **Public sites only.** Scheme must be `http`/`https`, no `user:pass@`, ports 80 and 443 only. The host is resolved, and **every** address it resolves to must be public (`ipaddress.is_global`, not multicast; IPv4-mapped IPv6 is unwrapped). That refuses loopback, private ranges, link-local (including cloud metadata at `169.254.169.254`), CGNAT, reserved and unspecified addresses, in IPv4 and IPv6. One private answer among public ones is a refusal.
- **The check is the connection.** The request goes to the checked IP with the real name as `Host` and TLS SNI (`extensions={"sni_hostname": ...}`), so DNS can't answer differently between the check and the connect (DNS rebinding), and certificates still verify against the real name (confirmed live against `example.com`).
- **Redirects are followed by hand** (at most 3), each hop going through the same checks, so a public page can't bounce the server to `127.0.0.1`.
- **No ambient authority:** a fresh client per call, no cookies, no `Authorization`, `trust_env=False` (so proxy variables can't route around the pinning), fixed `User-Agent`.
- **Bounded:** 1 MB of body (read as a stream and stopped, also for compressed responses), 15 seconds in all, text types only (`text/*`, JSON, XML, XHTML); images, PDFs and downloads are refused.
- **Untrusted output:** the text is labelled as untrusted internet content that must not be obeyed, and the guidance tells the model to cite the URL. The UI shows the title as text and links the URL only if it is `http(s)`.
- HTML is reduced to text with the stdlib `html.parser`: scripts, styles, navigation, footers, asides and forms are dropped, headings and paragraphs keep their breaks.

Not covered: pages that need JavaScript to show their content (you get what the server sent), logins and paywalls, scanned PDFs (no OCR), and a page over 1 MB of HTML (cut there, and it says so).

## Tests
`tests/test_tools_local.py` (about 130 cases: the calculator's accepted and refused expressions and limits; chat search; fetch_url's address checks for 20+ non-public addresses, redirects into private places, ports, schemes, content types, size and time limits, pinning, malformed HTML), `tests/test_tool_calls.py` (listing, per-conversation switching, guidance), `tests/ui/test_tools_ui.py` (the menu and how each call reads). Live (`-m live`): the real model using the calculator, and a real fetch of `example.com` through the pinned connection.

## Future tools (noted, not built)
Roughly in order of value. Each is a function in `tools.py` plus a `TOOL_UI` entry in `static/tools-ui.js`, except where it says otherwise.
- **`get_time`**: current date and time in any timezone (`zoneinfo`). The default prompt already gives the date, so this adds timezones and the time of day.
- **`lookup_wikipedia` / `search_arxiv`**: short citable reference lookups from free APIs without keys.
- **`weather`**: a forecast for a place (Open-Meteo needs no key); a good template for a small read-only API tool.
- **`run_python`**: running code for data work. Needs a real sandbox; the practical choice is OpenAI's hosted `code_interpreter` (per-session cost, runs on their side). Model-written code must not run unisolated on this machine.
- **Image generation**: needs same-origin image serving (the sanitizer strips `<img>`), a new event type, storage and a cost note.
- **Local notes or files search**: a read-only, allowlisted folder indexed with FTS5, like `search_chats`.
- **MCP servers**: OpenAI's hosted MCP tool needs a publicly reachable server; a local MCP client inside ChitChat is a larger design.
- **Memory** ("remember that I prefer X"): writes to custom instructions, so it needs a visible approval step.
- Anything with side effects (shell, file writes, email, calendar) needs a confirmation UI that does not exist yet, and should wait for it.
