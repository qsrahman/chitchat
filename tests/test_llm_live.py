import os

import pytest

from app.config import Settings
from app.llm import OpenAILLM


@pytest.mark.live
async def test_live_stream_normalization():
    s = Settings()
    assert s.openai_api_key or os.environ.get("OPENAI_API_KEY"), "needs OPENAI_API_KEY"
    events = [e async for e in OpenAILLM(s.openai_api_key).stream_reply(
        s.default_model, [{"role": "user", "content": "Say hi in one word."}])]
    assert any(e["type"] == "delta" for e in events)
    assert events[-1] == {"type": "done"}
