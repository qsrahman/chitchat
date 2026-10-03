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
        self.models = []
        self.hanging = asyncio.Event()  # set once the stream reaches a "hang" event: a test cancels after that

    async def stream_reply(self, model, messages, **options):
        self.calls.append({"model": model, "messages": messages, "options": options})
        for e in self.events:
            if e["type"] == "hang":  # simulates a slow stream so a test can disconnect mid-reply
                self.hanging.set()
                await asyncio.Event().wait()
            yield e

    async def generate_title(self, model, user_text, reply_text):
        return self.title

    async def list_models(self):
        return self.models


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def app(tmp_path, llm):
    app = create_app(
        Settings(
            _env_file=None, db_path=str(tmp_path / "test.db"), attachments_dir=str(tmp_path / "files"),
            openai_api_key="test", openai_model="test-model", default_system_prompt="",
        )
    )
    app.state.llm = llm
    return app


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c



@pytest.fixture
async def second(tmp_path):
    """A second, empty app: where an export is imported to."""
    app = create_app(Settings(_env_file=None, db_path=str(tmp_path / "second.db"),
                              attachments_dir=str(tmp_path / "second-files"), openai_api_key="t", openai_model="m",
                              default_system_prompt=""))
    app.state.llm = FakeLLM()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://second") as c:
        c.app = app  # so a test can look at that app's files and fake model
        yield c
