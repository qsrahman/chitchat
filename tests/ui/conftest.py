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
XSS_REPLY = (
    'Hi <img src=x onerror="window.__xss=1"> ![pixel](https://example.invalid/leak.png) '
    "<script>window.__xss=1</script> "
    "[docs](https://example.com) <a href=\"javascript:window.__xss=1\">bad</a>"
)


class ScriptedLLM:
    """Reply depends on keywords in the last user message, so each test picks its scenario."""

    def __init__(self):
        self.n = 0
        self.failed = set()
        self.dropped = set()

    async def stream_reply(self, model, messages):
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
            yield {"type": "delta", "text": f"Reply #{self.n} to **{text}**"}
        yield {"type": "done"}

    async def generate_title(self, model, user_text, reply_text):
        return user_text[:30]


@pytest.fixture
def app_url(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "ui.db"), openai_api_key="test"))
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
