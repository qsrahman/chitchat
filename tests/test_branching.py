"""Versions of a message: editing or regenerating adds a sibling instead of deleting what came after."""
import asyncio

import pytest

from tests.helpers import new_conv, parse_sse


async def chat(client, cid, text):
    return await client.post(f"/api/conversations/{cid}/chat", json={"content": text})


async def edit(client, cid, text, message_id=None):
    body = {"content": text, **({"message_id": message_id} if message_id is not None else {})}
    return await client.post(f"/api/conversations/{cid}/edit", json=body)


async def get(client, cid):
    return (await client.get(f"/api/conversations/{cid}")).json()


async def path(client, cid):
    return [(m["role"], m["content"]) for m in (await get(client, cid))["messages"]]


def reply(llm, text):
    llm.events = [{"type": "delta", "text": text}, {"type": "done"}]


@pytest.fixture
async def talk(client, llm):
    """A conversation of three exchanges: q1/a1, q2/a2, q3/a3."""
    cid = await new_conv(client)
    for n in (1, 2, 3):
        reply(llm, f"a{n}")
        await chat(client, cid, f"q{n}")
    return cid


# ---- editing ----

async def test_editing_the_last_message_adds_a_version_and_keeps_the_old_one(client, llm, talk):
    reply(llm, "a3 again")
    r = await edit(client, talk, "q3 reworded")
    assert await path(client, talk) == [("user", "q1"), ("assistant", "a1"), ("user", "q2"), ("assistant", "a2"),
                                        ("user", "q3 reworded"), ("assistant", "a3 again")]
    last_user = (await get(client, talk))["messages"][4]
    assert len(last_user["siblings"]) == 2  # q3 and the reworded one
    done = next(e for e in parse_sse(r.text) if e["type"] == "done")
    assert done["branch"]["user"] == {"id": last_user["id"], "siblings": last_user["siblings"]}
    assert llm.calls[-1]["messages"][-1] == {"role": "user", "content": "q3 reworded"}


async def test_editing_an_older_message_starts_a_new_path_from_there(client, llm, talk):
    first = (await get(client, talk))["messages"][2]  # q2
    reply(llm, "a2 new")
    await edit(client, talk, "q2 reworded", message_id=first["id"])
    assert await path(client, talk) == [("user", "q1"), ("assistant", "a1"), ("user", "q2 reworded"),
                                        ("assistant", "a2 new")]
    assert [m["content"] for m in llm.calls[-1]["messages"]] == ["q1", "a1", "q2 reworded"]  # q3 and a3 are not sent


async def test_the_old_path_is_still_there_and_can_be_shown_again(client, llm, talk):
    q2 = (await get(client, talk))["messages"][2]
    reply(llm, "a2 new")
    await edit(client, talk, "q2 reworded", message_id=q2["id"])
    shown = await client.post(f"/api/conversations/{talk}/branch", json={"message_id": q2["id"]})
    assert shown.status_code == 200
    assert [(m["role"], m["content"]) for m in shown.json()["messages"]] == [
        ("user", "q1"), ("assistant", "a1"), ("user", "q2"), ("assistant", "a2"), ("user", "q3"), ("assistant", "a3")]
    assert await path(client, talk) == [(m["role"], m["content"]) for m in shown.json()["messages"]]  # it was saved


async def test_an_edit_keeps_the_attachments_of_the_message(client, llm):
    from tests.helpers import PNG, upload
    aid = (await upload(client, "a.png", PNG)).json()["id"]
    cid = await new_conv(client)
    await client.post(f"/api/conversations/{cid}/chat", json={"content": "what is this", "attachments": [aid]})
    reply(llm, "a pixel")
    await edit(client, cid, "what is this, briefly")
    user = (await get(client, cid))["messages"][0]
    assert user["content"] == "what is this, briefly" and user["meta"]["attachments"][0]["id"] == aid
    assert llm.calls[-1]["messages"][0]["attachments"][0]["kind"] == "image"  # still sent to the model


async def test_editing_the_first_message_gives_it_a_sibling_at_the_root(client, llm, talk):
    q1 = (await get(client, talk))["messages"][0]
    reply(llm, "hello again")
    await edit(client, talk, "q1 reworded", message_id=q1["id"])
    messages = (await get(client, talk))["messages"]
    assert [m["content"] for m in messages] == ["q1 reworded", "hello again"]
    assert len(messages[0]["siblings"]) == 2


@pytest.mark.parametrize("message_id", [99999, "assistant"])
async def test_only_a_user_message_on_the_path_can_be_edited(client, llm, talk, message_id):
    if message_id == "assistant":
        message_id = (await get(client, talk))["messages"][1]["id"]
    assert (await edit(client, talk, "x", message_id=message_id)).status_code == 404
    assert await path(client, talk) == [("user", "q1"), ("assistant", "a1"), ("user", "q2"), ("assistant", "a2"),
                                        ("user", "q3"), ("assistant", "a3")]


async def test_a_message_that_is_off_the_path_cannot_be_edited(client, llm, talk):
    q3 = (await get(client, talk))["messages"][4]
    q2 = (await get(client, talk))["messages"][2]
    reply(llm, "new")
    await edit(client, talk, "q2 reworded", message_id=q2["id"])  # q3 is now on the other path
    assert (await edit(client, talk, "x", message_id=q3["id"])).status_code == 404


async def test_editing_with_nothing_to_edit_is_a_conflict_as_before(client):
    cid = await new_conv(client)
    assert (await edit(client, cid, "x")).status_code == 409


# ---- regenerating ----

async def test_regenerating_adds_a_version_of_the_reply_and_keeps_the_old_one(client, llm, talk):
    reply(llm, "a3 second try")
    r = await client.post(f"/api/conversations/{talk}/regenerate")
    messages = (await get(client, talk))["messages"]
    assert [m["content"] for m in messages][-2:] == ["q3", "a3 second try"]
    assert len(messages[-1]["siblings"]) == 2 and messages[-1]["siblings"][-1] == messages[-1]["id"]
    done = next(e for e in parse_sse(r.text) if e["type"] == "done")
    assert done["branch"]["assistant"] == {"id": messages[-1]["id"], "siblings": messages[-1]["siblings"]}
    assert [m["content"] for m in llm.calls[-1]["messages"]][-1] == "q3"  # the old reply is not in the history


async def test_the_old_reply_can_be_shown_again(client, llm, talk):
    old = (await get(client, talk))["messages"][-1]
    reply(llm, "a3 second try")
    await client.post(f"/api/conversations/{talk}/regenerate")
    await client.post(f"/api/conversations/{talk}/branch", json={"message_id": old["id"]})
    assert (await path(client, talk))[-1] == ("assistant", "a3")


async def test_retry_after_a_stopped_reply_adds_a_version_and_the_stopped_one_stays(client, llm):
    cid = await new_conv(client)
    llm.events = [{"type": "delta", "text": "par"}, {"type": "hang"}]
    task = asyncio.create_task(chat(client, cid, "hi"))
    await asyncio.wait_for(llm.hanging.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await path(client, cid) == [("user", "hi"), ("assistant", "par")]
    reply(llm, "whole answer")
    await client.post(f"/api/conversations/{cid}/regenerate")
    messages = (await get(client, cid))["messages"]
    assert [m["content"] for m in messages] == ["hi", "whole answer"] and len(messages[1]["siblings"]) == 2


async def test_a_failed_regenerate_leaves_the_conversation_ending_on_the_user_message(client, llm, talk):
    llm.events = [{"type": "error", "message": "boom"}]
    await client.post(f"/api/conversations/{talk}/regenerate")
    assert (await path(client, talk))[-1] == ("user", "q3")  # as a failed send always did: ready for Retry
    reply(llm, "worked")
    await client.post(f"/api/conversations/{talk}/regenerate")
    last = (await get(client, talk))["messages"][-1]
    assert last["content"] == "worked" and len(last["siblings"]) == 2  # the first a3 and this one


# ---- the new reply goes at the end of the path shown ----

async def test_sending_after_switching_continues_the_path_shown(client, llm, talk):
    q2 = (await get(client, talk))["messages"][2]
    reply(llm, "a2 new")
    await edit(client, talk, "q2 reworded", message_id=q2["id"])
    reply(llm, "a-next")
    await chat(client, talk, "and then?")
    assert await path(client, talk) == [("user", "q1"), ("assistant", "a1"), ("user", "q2 reworded"),
                                        ("assistant", "a2 new"), ("user", "and then?"), ("assistant", "a-next")]


async def test_choosing_a_branch_validates_the_message(client, talk):
    other = await new_conv(client)
    mine = (await get(client, talk))["messages"][0]["id"]
    assert (await client.post(f"/api/conversations/{talk}/branch", json={"message_id": 99999})).status_code == 404
    assert (await client.post(f"/api/conversations/{other}/branch", json={"message_id": mine})).status_code == 404
    assert (await client.post("/api/conversations/nope/branch", json={"message_id": mine})).status_code == 404
    assert (await client.post(f"/api/conversations/{talk}/branch", json={"message_id": "x"})).status_code == 422


# ---- what else sees the path ----

async def test_the_one_chat_export_is_the_path_shown_without_bookkeeping(client, llm, talk):
    q3 = (await get(client, talk))["messages"][4]
    reply(llm, "a3 again")
    await edit(client, talk, "q3 reworded", message_id=q3["id"])
    data = (await client.get(f"/api/conversations/{talk}/export?format=json")).json()
    assert [m["content"] for m in data["messages"]][-2:] == ["q3 reworded", "a3 again"]
    assert all(not ({"siblings", "parent_id"} & m.keys()) for m in data["messages"])
    markdown = (await client.get(f"/api/conversations/{talk}/export?format=md")).text
    assert "q3 reworded" in markdown and "\nq3\n" not in markdown


async def test_the_model_only_sees_the_path_shown(client, llm, talk):
    q2 = (await get(client, talk))["messages"][2]
    reply(llm, "a2 new")
    await edit(client, talk, "q2 reworded", message_id=q2["id"])
    reply(llm, "next")
    await chat(client, talk, "more")
    assert [m["content"] for m in llm.calls[-1]["messages"]] == ["q1", "a1", "q2 reworded", "a2 new", "more"]


async def test_search_finds_a_message_of_a_version_not_shown(client, llm, talk):
    q3 = (await get(client, talk))["messages"][4]
    reply(llm, "something else")
    await edit(client, talk, "wholly different", message_id=q3["id"])
    found = (await client.get("/api/search", params={"q": "q3"})).json()
    assert found and found[0]["message_id"] == q3["id"]  # the old version: the page switches to it when it opens
    await client.post(f"/api/conversations/{talk}/branch", json={"message_id": found[0]["message_id"]})
    assert (await path(client, talk))[-2:] == [("user", "q3"), ("assistant", "a3")]
