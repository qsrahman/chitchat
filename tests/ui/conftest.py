"""Browser tests: the real app served by uvicorn on a free port, with a scripted LLM (no network)."""
import asyncio
import socket
import threading
import time

import pytest
import uvicorn

from app import tools
from app.config import Settings
from app.main import create_app
from app.tools import Tool
from tests import network_changed

CODE_REPLY = "Here is a loop:\n\n```python\nfor i in range(3):\n    print(i)\n```\n\nThat's it, with `inline` code.\n"
MATH_REPLY = (
    "Inline \\(17\\cdot20 = 340\\) and display $$E=mc^2$$ inline.\n\n"
    "\\[\nx^2 + y^2 = z^2\n\\]\n\n"
    "It costs $5 and $10, code `\\(x\\)` stays literal, and so does:\n\n"
    "```\n\\(y\\)\n```\n\n"
    "Unsafe: \\(\\href{javascript:window.__xss=1}{click me}\\)."
)
# Adapted from a real reply (gemma4) to "What is the distribution of prime numbers?": $...$ math, a $$ block, math
# inside emphasis, an escaped dollar sign, and prices that must stay text.
PRIMES_REPLY = (
    "The number of primes up to a number $x$ is approximately:\n\n"
    "$$\\pi(x) \\approx \\frac{x}{\\ln(x)}$$\n\n"
    "*(Where $\\pi(x)$ is the prime-counting function and $\\ln(x)$ is the natural logarithm of $x$.)*\n\n"
    "The chance that a number near $x$ is prime is roughly $1 / \\ln(x)$.\n\n"
    "For any number $n$, you can find $n$ consecutive composite numbers.\n\n"
    "The Clay Institute will pay \\$1 million to whoever proves it. "
    "Tickets cost $5 and $10; budgets are $20,000 and $30,000."
)
SEARCH_RESULTS = [
    {"title": "Python Releases", "url": "https://www.python.org/downloads/", "description": "The latest release."},
    {"title": "What's new", "url": "https://docs.python.org/3/whatsnew/", "description": ""},
    {"title": "Not a web page", "url": "javascript:window.__xss=1", "description": "must not become a link"},
]
XSS_REPLY = (
    'Hi <img src=x onerror="window.__xss=1"> ![pixel](https://example.invalid/leak.png) '
    "<script>window.__xss=1</script> "
    "[docs](https://example.com) <a href=\"javascript:window.__xss=1\">bad</a>"
)


class ScriptedLLM:
    """Reply depends on keywords in the last user message, so each test picks its scenario."""

    default_model = "scripted-default"

    def __init__(self):
        self.n = 0
        self.failed = set()
        self.dropped = set()

    async def stream_reply(
        self, model, messages, instructions=None, reasoning_effort=None, temperature=None, tools=None, max_tool_calls=4
    ):
        text = messages[-1]["content"]
        self.n += 1
        if "fail" in text and text not in self.failed:
            self.failed.add(text)
            yield {"type": "error", "message": "simulated failure"}
            return
        if "drop" in text and text not in self.dropped:  # the stream ends without a "done" event
            self.dropped.add(text)
            yield {"type": "delta", "text": "Half an ans"}
            return
        if "slow" in text:  # a thinking pause, then a stream long enough to stop mid-way
            await asyncio.sleep(0.5)
            for i in range(60):
                await asyncio.sleep(0.1)
                yield {"type": "delta", "text": f"word{i} "}
        elif "bigblock" in text:  # one code block that grows for 1.5 s, in 150 pieces
            yield {"type": "delta", "text": "```python\n"}
            for i in range(150):
                await asyncio.sleep(0.01)
                yield {"type": "delta", "text": "".join(f"value_{i}_{j} = compute({j})\n" for j in range(20))}
            yield {"type": "delta", "text": "```\n"}
        elif "long" in text:
            for i in range(80):
                await asyncio.sleep(0.04)
                yield {"type": "delta", "text": f"Paragraph {i} of a long answer.\n\n"}
        elif "mathstream" in text:  # a formula split across deltas, with a pause inside it
            yield {"type": "delta", "text": "Here: \\(a^2"}
            await asyncio.sleep(0.8)
            yield {"type": "delta", "text": " + b^2\\) is the sum."}
        elif "findweb" in text:  # a web search, then the answer; "broken" makes the search fail, "hang" never returns
            query = {"arguments": {"query": "python version", "freshness": None}}
            call = {"type": "tool_call", "id": "call_1", "name": "web_search"}
            if "hang" in text:
                yield {"type": "delta", "text": "Let me look. "}
            yield {**call, "status": "running", **query}
            if "hang" in text:
                await asyncio.sleep(60)
            await asyncio.sleep(0.4)
            if "broken" in text:
                yield {**call, "status": "error", **query, "error": "Search rate limit reached."}
                yield {"type": "delta", "text": "Sorry, I couldn't search."}
            else:
                shown = {"query": "python version", "results": SEARCH_RESULTS}
                yield {**call, "status": "done", **query, "display": shown}
                yield {"type": "delta", "text": "It is **3.14**, per [python.org](https://www.python.org/)."}
            yield {"type": "done"}
            return
        elif "richreply" in text:  # one of everything the markdown renderer produces
            yield {"type": "delta", "text": (
                "# A heading\n\nA paragraph with **bold**, *italic*, `inline code` and a [link](https://example.com).\n\n"
                "## Second level\n\n- first item\n- second item\n\n1. one\n2. two\n\n"
                "> A quote that is muted\n\n| Name | Value |\n|---|---|\n| alpha | 1 |\n| beta | 2 |\n\n"
                "```python\n# every kind of token\ndef greet(name: str, times=3):\n    for i in range(times):\n"
                "        print(\"hello \" + name, 42, i)\n    return None\n```\n\n"
                "Math: \\(x^2 + y^2 = z^2\\)\n\n"
                "$$\n\\int_0^1 x\\,dx = \\tfrac12\n$$")}
        elif "widereply" in text:  # long reasoning, and code, a table and a formula wider than the column
            for i in range(30):
                yield {"type": "reasoning_delta", "text": f"Thinking step {i} of a long chain of thought.\n\n"}
            columns = " | ".join(f"col{c}" for c in range(40))  # cells wrap anywhere, so only many columns overflow
            cells = " | ".join(f"v{c}" for c in range(40))
            yield {"type": "delta", "text": (
                "```python\n" + "result = " + " + ".join(f"value_{i}" for i in range(40)) + "\n```\n\n"
                f"| {columns} |\n|{'---|' * 40}\n| {cells} |\n\n"
                "$$" + " + ".join(f"x_{{{i}}}^{{2}}" for i in range(40)) + "$$")}
        elif "urdu" in text:  # an Arabic-script paragraph, an English one, a list and code, in one reply
            yield {"type": "delta", "text": "السلام عليكم، هذه فقرة عربية.\n\nThis paragraph is English.\n\n"
                   "- بند أول\n- بند ثان\n\n```python\nprint('hi')\n```\n\n> اقتباس"}
        elif text in ("calcsum", "calcbad"):  # the calculator: "calcbad" fails
            call = {"type": "tool_call", "id": "call_c", "name": "calculator"}
            args = {"arguments": {"expression": "17 * 23" if text == "calcsum" else "1 / 0"}}
            yield {**call, "status": "running", **args}
            await asyncio.sleep(0.3)
            if text == "calcbad":
                yield {**call, "status": "error", **args, "error": "Division by zero."}
                yield {"type": "delta", "text": "That can't be calculated."}
            else:
                yield {**call, "status": "done", **args, "display": {"expression": "17 * 23", "result": "391"}}
                yield {"type": "delta", "text": "It is **391**."}
        elif text == "findchats":  # search_chats, with markup in the snippet that must stay text
            call = {"type": "tool_call", "id": "call_s", "name": "search_chats", "arguments": {"query": "mutex"}}
            yield {**call, "status": "running"}
            await asyncio.sleep(0.3)
            found = [{"id": "abc123", "title": "Threads <i>and</i> locks", "snippet": "use a mutex <b>around</b> it"}]
            yield {**call, "status": "done", "display": {"query": "mutex", "results": found}}
            yield {"type": "delta", "text": "You discussed it in Threads."}
        elif text in ("checktime", "readchatx", "readfilex", "listfilesx"):  # the date, chat and file tools
            name, args, shown, answer = {
                "checktime": ("get_datetime", {"timezone": None, "until": "2026-12-25"}, {
                    "now": "Monday 5 October 2026, 14:03", "timezone": "PKT, UTC+05:00",
                    "also": ["Friday 25 December 2026, 00:00 (UTC+05:00) is in 80 days <b>9</b> hours"]},
                    "It is Monday afternoon."),
                "readchatx": ("read_chat", {"chat_id": "abc123"}, {
                    "id": "abc123", "title": "Plans <i>for</i> May", "from": 4, "to": 9, "total": 20}, "I read it."),
                "readfilex": ("read_attachment", {"name": "notes.txt"}, {
                    "name": "<img src=x onerror=window.__xss=1>.txt", "kind": "text", "characters": 12_000,
                    "offset": 12_000, "total": 30_000}, "The file says hello."),
                "listfilesx": ("read_attachment", {"name": None}, {"files": ["a <b>b</b>.txt", "c.pdf"]},
                               "Two files."),
            }[text]
            call = {"type": "tool_call", "id": "call_r", "name": name, "arguments": args}
            yield {**call, "status": "running"}
            await asyncio.sleep(0.3)
            yield {**call, "status": "done", "display": shown}
            yield {"type": "delta", "text": answer}
        elif text in ("readpage", "readevil"):  # fetch_url; "readevil" returns a URL and a title that must stay inert
            url = "https://example.com/post" if text == "readpage" else "javascript:window.__xss=1"
            call = {"type": "tool_call", "id": "call_f", "name": "fetch_url", "arguments": {"url": url}}
            yield {**call, "status": "running"}
            await asyncio.sleep(0.3)
            title = "Example post" if text == "readpage" else "<img src=x onerror=window.__xss=1>"
            shown = {"url": url, "title": title, "characters": 1234, "offset": 0, "total": 5000,
                     "truncated": text == "readpage"}
            yield {**call, "status": "done", "display": shown}
            yield {"type": "delta", "text": "The page says hello."}
        elif "compactme" in text:  # the context was compacted during this reply
            yield {"type": "delta", "text": "Done, and compacted."}
            yield {"type": "compaction", "item": {"type": "compaction", "encrypted_content": "x"}, "after_reply": True}
        elif "dollarstream" in text:  # a $...$ formula split across deltas
            yield {"type": "delta", "text": "Here: $a^2"}
            await asyncio.sleep(0.8)
            yield {"type": "delta", "text": " + b^2$ is the sum."}
        elif "primes" in text:
            yield {"type": "delta", "text": PRIMES_REPLY}
        elif "math" in text:
            yield {"type": "delta", "text": MATH_REPLY}
        elif "ponder" in text:  # reasoning summary first, then the answer and its token usage
            if "stars" in text:  # raw-thinking style: arithmetic with asterisks, and a formula
                yield {"type": "reasoning_delta", "text": "**Plan**\n\nSo 17*23 = 391 and 17*20 + 17*3 = 391, "}
                yield {"type": "reasoning_delta", "text": "i.e. \\(17\\cdot23\\) with _snake_case_."}
            else:
                yield {"type": "reasoning_delta", "text": "**Weighing options.**"}
                await asyncio.sleep(0.4)
                yield {"type": "reasoning_delta", "text": "\n\nChecking the sums."}
            if "broken" in text:
                yield {"type": "error", "message": "model fell over"}
                return
            await asyncio.sleep(0.4)
            yield {"type": "delta", "text": "The answer is 42."}
            usage = {"input_tokens": 1234, "output_tokens": 567, "reasoning_tokens": 300}
            yield {"type": "done", "usage": usage}
            return
        elif "literal" in text:
            yield {"type": "delta", "text": "```weird\n<b>not bold</b> & 'q' <script>window.__xss=1</script>\n```"}
        elif "code" in text:
            yield {"type": "delta", "text": CODE_REPLY}
        elif "xss" in text:
            yield {"type": "delta", "text": XSS_REPLY}
        elif "cutoff" in text:
            yield {"type": "delta", "text": "Partial answer"}
            yield {"type": "done", "incomplete": "max_output_tokens"}
            return
        else:
            await asyncio.sleep(0.05)
            # Echo the settings that reached the model, so tests can see them in the reply.
            files = ",".join(a["name"] for a in messages[-1].get("attachments", []))
            used = {"model": model if model != self.default_model else None, "instructions": instructions,
                    "effort": reasoning_effort, "temperature": temperature, "files": files or None,
                    "tools": ",".join(tools) if tools else None}
            echo = "".join(f" [{k}={v}]" for k, v in used.items() if v is not None)
            yield {"type": "delta", "text": f"Reply #{self.n} to **{text}**{echo}"}
        yield {"type": "done"}

    async def generate_title(self, model, user_text, reply_text):
        return user_text[:30]

    async def list_models(self):
        return ["alpha-model", "gpt-5-mini"]


@pytest.fixture
def app_url(tmp_path):
    settings = Settings(
        _env_file=None, db_path=str(tmp_path / "ui.db"), attachments_dir=str(tmp_path / "files"),
        openai_api_key="test", openai_model=ScriptedLLM.default_model, default_system_prompt=""
    )
    app = create_app(settings)
    app.state.llm = ScriptedLLM()

    async def no_network(args):
        raise AssertionError("the scripted LLM never runs tools")

    # The real keyless tools (the scripted model never runs them) and a stand-in for web search, which needs a key.
    app.state.tools = {
        "web_search": Tool("web_search", "Web search", "Search.", {"type": "object"}, no_network),
        **tools.build(settings),
    }
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 1100, "height": 760},
            "permissions": ["clipboard-read", "clipboard-write"]}


@pytest.fixture
def expected_console_errors():
    """A test that deliberately breaks the network appends the errors it expects here."""
    return []


def wait_until_ready(page):
    """The page's HTML is visible before its module scripts have run (they are deferred), and under load the gap is
    long enough for a fill or an Enter to land on a page that cannot react yet; and the app moves the focus to the
    message box when it has loaded, which would take it from a field a test had just filled. app.js marks the body
    when it has loaded the first conversation and done that."""
    page.locator("body[data-ready]").wait_for(state="attached")


@pytest.fixture
def page(page, expected_console_errors, request):
    """pytest-playwright's page, plus: navigations wait for the app to be ready, and any JS error or unexpected
    console error fails the test."""
    goto, reload = page.goto, page.reload

    def goto_ready(*args, **kwargs):
        response = goto(*args, **kwargs)
        wait_until_ready(page)
        return response

    def reload_ready(*args, **kwargs):
        response = reload(*args, **kwargs)
        wait_until_ready(page)
        return response

    page.goto, page.reload = goto_ready, reload_ready
    errors = []

    def note(text):
        errors.append(text)
        if network_changed.seen([text]):  # see tests/network_changed.py
            request.node.network_changed = True

    page.on("pageerror", lambda e: note(str(e)))
    page.on("console", lambda m: m.type == "error" and note(m.text))
    yield page
    unexpected = [e for e in errors if not any(w in e for w in expected_console_errors)]
    if unexpected and all(network_changed.seen([e]) for e in unexpected):
        raise network_changed.NetworkChanged(f"the page's requests failed: {len(unexpected)} x {unexpected[0]}")
    assert not unexpected, unexpected
