import os

import pytest

from app.config import Settings
from app.llm import OpenAILLM


@pytest.mark.live
async def test_live_stream_normalization():
    s = Settings()
    assert s.openai_api_key or os.environ.get("OPENAI_API_KEY"), "needs OPENAI_API_KEY"
    events = [e async for e in OpenAILLM(s).stream_reply(
        s.openai_model, [{"role": "user", "content": "Say hi in one word."}])]
    assert any(e["type"] == "delta" for e in events)
    assert events[-1] == {"type": "done"}


@pytest.mark.live
async def test_live_generate_title():
    s = Settings()
    title = await OpenAILLM(s).generate_title(s.openai_model, "How do I sort a list in Python?", "Use sorted().")
    assert title
