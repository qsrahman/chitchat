from tests.helpers import new_conv, parse_sse


async def test_conversation_lifecycle(client):
    r = await client.post("/api/conversations")
    assert r.status_code == 201
    cid = r.json()["id"]
    assert [c["id"] for c in (await client.get("/api/conversations")).json()] == [cid]
    assert (await client.patch(f"/api/conversations/{cid}", json={"title": "T"})).json()["title"] == "T"
    got = (await client.get(f"/api/conversations/{cid}")).json()
    assert got["title"] == "T" and got["messages"] == []
    assert (await client.delete(f"/api/conversations/{cid}")).status_code == 204
    assert (await client.get(f"/api/conversations/{cid}")).status_code == 404


async def test_unknown_conversation_404(client):
    assert (await client.get("/api/conversations/nope")).status_code == 404
    assert (await client.patch("/api/conversations/nope", json={"title": "x"})).status_code == 404
    assert (await client.delete("/api/conversations/nope")).status_code == 404
    assert (await client.post("/api/conversations/nope/chat", json={"content": "hi"})).status_code == 404


async def test_rename_rejects_empty(client):
    cid = await new_conv(client)
    assert (await client.patch(f"/api/conversations/{cid}", json={"title": ""})).status_code == 422
    assert (await client.patch(f"/api/conversations/{cid}", json={"title": "   "})).status_code == 422


async def test_chat_streams_saves_and_titles(client, llm):
    cid = await new_conv(client)
    r = await client.post(f"/api/conversations/{cid}/chat", json={"content": "hi"})
    assert r.headers["content-type"].startswith("text/event-stream")
    assert parse_sse(r.text) == llm.events + [{"type": "title", "title": "Fake title"}]
    got = (await client.get(f"/api/conversations/{cid}")).json()
    assert got["title"] == "Fake title"
    assert [(m["role"], m["content"]) for m in got["messages"]] == [("user", "hi"), ("assistant", "Hello world")]


async def test_chat_sends_full_history_and_model(client, llm):
    cid = await new_conv(client)
    await client.post(f"/api/conversations/{cid}/chat", json={"content": "one"})
    await client.post(f"/api/conversations/{cid}/chat", json={"content": "two", "model": "other"})
    assert llm.calls[0]["model"] == "test-model"
    assert llm.calls[1]["model"] == "other"
    assert llm.calls[1]["messages"] == [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "Hello world"},
        {"role": "user", "content": "two"},
    ]


async def test_title_only_generated_once(client, llm):
    cid = await new_conv(client)
    await client.post(f"/api/conversations/{cid}/chat", json={"content": "one"})
    llm.title = "Changed"
    r = await client.post(f"/api/conversations/{cid}/chat", json={"content": "two"})
    assert not any(e["type"] == "title" for e in parse_sse(r.text))
    assert (await client.get(f"/api/conversations/{cid}")).json()["title"] == "Fake title"


async def test_title_falls_back_to_user_text(client, llm):
    llm.title = None
    cid = await new_conv(client)
    await client.post(f"/api/conversations/{cid}/chat", json={"content": "x" * 100})
    assert (await client.get(f"/api/conversations/{cid}")).json()["title"] == "x" * 40


async def test_failed_reply_keeps_user_message_only(client, llm):
    llm.events = [{"type": "delta", "text": "par"}, {"type": "error", "message": "boom"}]
    cid = await new_conv(client)
    r = await client.post(f"/api/conversations/{cid}/chat", json={"content": "hi"})
    assert parse_sse(r.text)[-1] == {"type": "error", "message": "boom"}
    got = (await client.get(f"/api/conversations/{cid}")).json()
    assert [m["role"] for m in got["messages"]] == ["user"]
    assert got["title"] == "New chat"


async def test_chat_rejects_empty_content(client):
    cid = await new_conv(client)
    assert (await client.post(f"/api/conversations/{cid}/chat", json={"content": ""})).status_code == 422


async def test_chat_rejects_blank_and_oversized_content(client):
    cid = await new_conv(client)
    url = f"/api/conversations/{cid}/chat"
    assert (await client.post(url, json={"content": "   "})).status_code == 422
    assert (await client.post(url, json={"content": "\n\t "})).status_code == 422
    assert (await client.post(url, json={"content": "x" * 100_001})).status_code == 422


async def test_incomplete_reply_is_saved_and_flagged(client, llm):
    llm.events = [{"type": "delta", "text": "long"}, {"type": "done", "incomplete": "max_output_tokens"}]
    cid = await new_conv(client)
    await client.post(f"/api/conversations/{cid}/chat", json={"content": "hi"})
    last = (await client.get(f"/api/conversations/{cid}")).json()["messages"][-1]
    assert (last["content"], last["meta"]) == ("long", {"incomplete": "max_output_tokens"})
