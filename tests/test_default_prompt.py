from datetime import date

import httpx
import pytest

from app.config import DEFAULT_SYSTEM_PROMPT, Settings
from app.main import create_app
from tests.conftest import FakeLLM
from tests.helpers import new_conv


@pytest.fixture
async def client_with_default(tmp_path):
    """An app that keeps the built-in default system prompt (the shared fixtures turn it off)."""
    app = create_app(Settings(
        _env_file=None, db_path=str(tmp_path / "d.db"), attachments_dir=str(tmp_path / "f"),
        openai_api_key="test", openai_model="m",
    ))
    app.state.llm = FakeLLM()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, app


async def instructions(client, app, **conv):
    cid = (await client.post("/api/conversations", json={"settings": conv})).json()["id"]
    await client.post(f"/api/conversations/{cid}/chat", json={"content": "hi"})
    return app.state.llm.calls[-1]["options"]["instructions"]


async def test_the_default_prompt_is_sent_with_todays_date(client_with_default):
    client, app = client_with_default
    sent = await instructions(client, app)
    assert sent == DEFAULT_SYSTEM_PROMPT.replace("{date}", date.today().isoformat())
    assert date.today().isoformat() in sent and "{date}" not in sent


async def test_it_comes_first_then_custom_instructions_then_the_conversation_prompt(client_with_default):
    client, app = client_with_default
    await client.put("/api/custom-instructions", json={"text": "I am Que."})
    sent = await instructions(client, app, system_prompt="Be brief.")
    assert sent.endswith("\n\nI am Que.\n\nBe brief.")
    assert sent.startswith("You are an expert AI assistant")


async def test_an_empty_default_sends_no_instructions_at_all(client, llm):
    await client.put("/api/defaults", json={"tools": []})  # a tool adds its own guidance, so none are on here
    cid = await new_conv(client)
    await client.post(f"/api/conversations/{cid}/chat", json={"content": "hi"})
    assert llm.calls[-1]["options"]["instructions"] is None


async def test_a_custom_default_replaces_the_built_in_one(tmp_path):
    app = create_app(Settings(
        _env_file=None, db_path=str(tmp_path / "d.db"), attachments_dir=str(tmp_path / "f"),
        openai_api_key="t", openai_model="m", default_system_prompt="Reply in French. Date: {date}.",
    ))
    app.state.llm = FakeLLM()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert await instructions(c, app) == f"Reply in French. Date: {date.today().isoformat()}."


def test_the_default_mentions_what_the_ui_can_render():
    assert "\\(" in DEFAULT_SYSTEM_PROMPT and "fenced" in DEFAULT_SYSTEM_PROMPT and "{date}" in DEFAULT_SYSTEM_PROMPT
