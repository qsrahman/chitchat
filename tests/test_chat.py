import json

import pytest


def parse_sse(text):
    return [json.loads(f[6:]) for f in text.split("\n\n") if f.startswith("data: ")]


async def test_chat_streams_events(client, llm):
    r = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert parse_sse(r.text) == llm.events
    assert llm.calls == [{"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}]


async def test_chat_model_override(client, llm):
    await client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "model": "other"})
    assert llm.calls[0]["model"] == "other"


async def test_chat_passes_error_event(client, llm):
    llm.events = [{"type": "error", "message": "boom"}]
    r = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert parse_sse(r.text) == [{"type": "error", "message": "boom"}]


@pytest.mark.parametrize("body", [
    {"messages": []},
    {"messages": [{"role": "system", "content": "x"}]},
    {},
])
async def test_chat_validation(client, body):
    assert (await client.post("/api/chat", json=body)).status_code == 422
