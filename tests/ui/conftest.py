"""Browser tests: the real app served by uvicorn on a free port, with a scripted LLM (no network)."""
import asyncio
import socket
import threading
import time

import pytest
import uvicorn

from app.config import Settings
from app.main import create_app

CODE_REPLY = "Here is a loop:\n\n```python\nfor i in range(3):\n    print(i)\n```\n\nThat's it, with `inline` code.\n"
MATH_REPLY = (
    "Inline \\(17\\cdot20 = 340\\) and display $$E=mc^2$$ inline.\n\n"
    "\\[\nx^2 + y^2 = z^2\n\\]\n\n"
    "It costs $5 and $10, code `\\(x\\)` stays literal, and so does:\n\n"
    "```\n\\(y\\)\n```\n\n"
    "Unsafe: \\(\\href{javascript:window.__xss=1}{click me}\\)."
)
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

    async def stream_reply(self, model, messages, instructions=None, reasoning_effort=None, temperature=None):
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
        elif "long" in text:
            for i in range(80):
                await asyncio.sleep(0.04)
                yield {"type": "delta", "text": f"Paragraph {i} of a long answer.\n\n"}
        elif "mathstream" in text:  # a formula split across deltas, with a pause inside it
            yield {"type": "delta", "text": "Here: \\(a^2"}
            await asyncio.sleep(0.8)
            yield {"type": "delta", "text": " + b^2\\) is the sum."}
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
            used = {"model": model if model != self.default_model else None, "instructions": instructions,
                    "effort": reasoning_effort, "temperature": temperature}
            echo = "".join(f" [{k}={v}]" for k, v in used.items() if v is not None)
            yield {"type": "delta", "text": f"Reply #{self.n} to **{text}**{echo}"}
        yield {"type": "done"}

    async def generate_title(self, model, user_text, reply_text):
        return user_text[:30]

    async def list_models(self):
        return ["alpha-model", "gpt-5-mini"]


@pytest.fixture
def app_url(tmp_path):
    app = create_app(Settings(
        _env_file=None, db_path=str(tmp_path / "ui.db"), openai_api_key="test", openai_model=ScriptedLLM.default_model
    ))
    app.state.llm = ScriptedLLM()
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


@pytest.fixture
def page(page, expected_console_errors):
    """pytest-playwright's page, plus: any JS error or unexpected console error fails the test."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    yield page
    unexpected = [e for e in errors if not any(w in e for w in expected_console_errors)]
    assert not unexpected, unexpected
