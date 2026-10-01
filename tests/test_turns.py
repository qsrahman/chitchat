import asyncio

import pytest

from tests.helpers import new_conv, parse_sse


async def messages(client, cid):
    return (await client.get(f"/api/conversations/{cid}")).json()["messages"]


async def chat(client, cid, text):
    return await client.post(f"/api/conversations/{cid}/chat", json={"content": text})


async def test_regenerate_replaces_last_reply(client, llm):
    cid = await new_conv(client)
    await chat(client, cid, "hi")
    llm.events = [{"type": "delta", "text": "second try"}, {"type": "done"}]
    r = await client.post(f"/api/conversations/{cid}/regenerate")
    assert parse_sse(r.text)[:2] == llm.events
    got = [(m["role"], m["content"]) for m in await messages(client, cid)]
    assert got == [("user", "hi"), ("assistant", "second try")]
    assert llm.calls[-1]["messages"] == [{"role": "user", "content": "hi"}]


async def test_regenerate_without_messages_is_409(client):
    cid = await new_conv(client)
    assert (await client.post(f"/api/conversations/{cid}/regenerate")).status_code == 409
    assert (await client.post("/api/conversations/nope/regenerate")).status_code == 404


async def test_retry_after_error_saves_reply_and_titles(client, llm):
    llm.events = [{"type": "error", "message": "boom"}]
    cid = await new_conv(client)
    await chat(client, cid, "hi")
    llm.events = [{"type": "delta", "text": "ok"}, {"type": "done"}]
    r = await client.post(f"/api/conversations/{cid}/regenerate")
    assert parse_sse(r.text)[-1] == {"type": "title", "title": "Fake title"}
    msgs = await messages(client, cid)
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "hi"), ("assistant", "ok")]


async def test_edit_rewrites_last_user_message_and_drops_later_ones(client, llm):
    cid = await new_conv(client)
    await chat(client, cid, "one")
    await chat(client, cid, "two")
    llm.events = [{"type": "delta", "text": "new"}, {"type": "done"}]
    r = await client.post(f"/api/conversations/{cid}/edit", json={"content": "two!"})
    assert r.status_code == 200
    assert [(m["role"], m["content"]) for m in await messages(client, cid)] == [
        ("user", "one"), ("assistant", "Hello world"), ("user", "two!"), ("assistant", "new"),
    ]
    assert llm.calls[-1]["messages"][-1] == {"role": "user", "content": "two!"}


async def test_edit_validation(client):
    cid = await new_conv(client)
    assert (await client.post(f"/api/conversations/{cid}/edit", json={"content": "x"})).status_code == 409
    await chat(client, cid, "one")
    assert (await client.post(f"/api/conversations/{cid}/edit", json={"content": ""})).status_code == 422
    assert (await client.post("/api/conversations/nope/edit", json={"content": "x"})).status_code == 404


async def test_disconnect_saves_partial_reply_as_stopped(client, llm):
    llm.events = [{"type": "delta", "text": "par"}, {"type": "delta", "text": "tial"}, {"type": "hang"}]
    cid = await new_conv(client)
    task = asyncio.create_task(chat(client, cid, "hi"))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    msgs = await messages(client, cid)
    assert [(m["role"], m["content"], m["meta"]) for m in msgs] == [
        ("user", "hi", {}), ("assistant", "partial", {"stopped": True}),
    ]


async def test_disconnect_before_any_text_saves_no_reply(client, llm):
    llm.events = [{"type": "hang"}]
    cid = await new_conv(client)
    task = asyncio.create_task(chat(client, cid, "hi"))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [m["role"] for m in await messages(client, cid)] == ["user"]


async def test_reasoning_and_usage_are_saved_in_meta(client, llm):
    usage = {"input_tokens": 10, "output_tokens": 20, "reasoning_tokens": 5}
    llm.events = [
        {"type": "reasoning_delta", "text": "Think "}, {"type": "reasoning_delta", "text": "hard."},
        {"type": "delta", "text": "Answer"}, {"type": "done", "usage": usage},
    ]
    cid = await new_conv(client)
    r = await chat(client, cid, "hi")
    assert [e["type"] for e in parse_sse(r.text)] == ["reasoning_delta", "reasoning_delta", "delta", "done", "title"]
    assert (await messages(client, cid))[-1]["meta"] == {"reasoning": "Think hard.", "usage": usage}


async def test_plain_reply_has_empty_meta(client, llm):
    cid = await new_conv(client)
    await chat(client, cid, "hi")
    assert (await messages(client, cid))[-1]["meta"] == {}


async def test_stopped_reply_keeps_its_reasoning(client, llm):
    llm.events = [{"type": "reasoning_delta", "text": "Hmm."}, {"type": "delta", "text": "part"}, {"type": "hang"}]
    cid = await new_conv(client)
    task = asyncio.create_task(chat(client, cid, "hi"))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await messages(client, cid))[-1]["meta"] == {"stopped": True, "reasoning": "Hmm."}


async def test_reasoning_without_an_answer_is_not_saved_when_stopped(client, llm):
    llm.events = [{"type": "reasoning_delta", "text": "Hmm."}, {"type": "hang"}]
    cid = await new_conv(client)
    task = asyncio.create_task(chat(client, cid, "hi"))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [m["role"] for m in await messages(client, cid)] == ["user"]
