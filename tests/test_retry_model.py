"""Trying a reply again with another model: the model is for that reply only, and each reply records which wrote it."""
import pytest

from tests.helpers import new_conv


async def chat(client, cid, text="hi", **extra):
    return await client.post(f"/api/conversations/{cid}/chat", json={"content": text, **extra})


async def messages(client, cid):
    return (await client.get(f"/api/conversations/{cid}")).json()["messages"]


async def test_every_reply_records_the_model_that_wrote_it(client, llm):
    cid = await new_conv(client)
    await chat(client, cid)
    await chat(client, cid, "again", model="other")
    replies = [m for m in await messages(client, cid) if m["role"] == "assistant"]
    assert [m["meta"]["model"] for m in replies] == ["test-model", "other"]
    assert "model" not in (await messages(client, cid))[0]["meta"]  # your messages have none


async def test_regenerating_with_a_model_uses_it_once_and_keeps_the_chats_own(client, llm):
    cid = await new_conv(client)
    await chat(client, cid)
    r = await client.post(f"/api/conversations/{cid}/regenerate", json={"model": "other-model"})
    assert r.status_code == 200 and llm.calls[-1]["model"] == "other-model"
    last = (await messages(client, cid))[-1]
    assert last["meta"]["model"] == "other-model" and len(last["siblings"]) == 2  # a version beside the first
    assert (await client.get(f"/api/conversations/{cid}")).json()["settings"]["model"] is None  # unchanged
    await client.post(f"/api/conversations/{cid}/regenerate")  # no body, as before: the chat's own model
    assert llm.calls[-1]["model"] == "test-model"


async def test_the_first_reply_keeps_its_own_model_after_another_is_tried(client, llm):
    cid = await new_conv(client)
    await chat(client, cid)
    old = (await messages(client, cid))[-1]
    await client.post(f"/api/conversations/{cid}/regenerate", json={"model": "other-model"})
    await client.post(f"/api/conversations/{cid}/branch", json={"message_id": old["id"]})
    assert (await messages(client, cid))[-1]["meta"]["model"] == "test-model"


@pytest.mark.parametrize("body", [{"model": ""}, {"model": "   "}, {"model": "x" * 201}, {"model": 5}])
async def test_a_bad_model_is_refused_before_anything_changes(client, llm, body):
    cid = await new_conv(client)
    await chat(client, cid)
    before = await messages(client, cid)
    assert (await client.post(f"/api/conversations/{cid}/regenerate", json=body)).status_code == 422
    assert (await client.post(f"/api/conversations/{cid}/edit", json={"content": "x", **body})).status_code == 422
    assert await messages(client, cid) == before


async def test_an_edit_can_name_a_model_too(client, llm):
    cid = await new_conv(client)
    await chat(client, cid)
    await client.post(f"/api/conversations/{cid}/edit", json={"content": "reworded", "model": "other-model"})
    assert llm.calls[-1]["model"] == "other-model"
    assert (await messages(client, cid))[-1]["meta"]["model"] == "other-model"


async def test_the_backup_keeps_which_model_wrote_a_reply_and_cleans_the_field(client, llm):
    from tests.test_backup import import_file
    cid = await new_conv(client)
    await chat(client, cid, model="other")
    document = (await client.get("/api/export")).json()
    reply = document["conversations"][0]["messages"][1]
    assert reply["meta"]["model"] == "other"
    junk = {"conversations": [{"id": "d" * 32, "title": "T", "messages": [
        {"role": "assistant", "content": "a", "meta": {"model": ["not", "text"]}},
        {"role": "assistant", "content": "b", "meta": {"model": "x" * 500}}]}]}
    await import_file(client, junk)
    got = (await messages(client, "d" * 32))
    assert "model" not in got[0]["meta"] and len(got[1]["meta"]["model"]) == 200
