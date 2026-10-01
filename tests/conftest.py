import asyncio

import httpx
import pytest

from app.config import Settings
from app.main import create_app


class FakeLLM:
    """Yields scripted events; records the calls it received."""

    def __init__(self, events=None):
        self.events = events or [
            {"type": "delta", "text": "Hello"},
            {"type": "delta", "text": " world"},
            {"type": "done"},
        ]
        self.calls = []
        self.title = "Fake title"

    async def stream_reply(self, model, messages):
        self.calls.append({"model": model, "messages": messages})
        for e in self.events:
            if e["type"] == "hang":  # simulates a slow stream so a test can disconnect mid-reply
                await asyncio.Event().wait()
            yield e

    async def generate_title(self, model, user_text, reply_text):
        return self.title


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def app(tmp_path, llm):
    app = create_app(Settings(db_path=str(tmp_path / "test.db"), openai_api_key="test", openai_model="test-model"))
    app.state.llm = llm
    return app


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c

