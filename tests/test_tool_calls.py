import asyncio

import pytest

from app.tools import Tool, ToolResult
from tests.helpers import new_conv, parse_sse


def fake_search(guidance="SEARCH GUIDANCE."):
    async def run(args):
        return ToolResult("text", {"query": "q", "results": []})

    return Tool("web_search", "Web search", "Search.", {"type": "object"}, run, guidance=guidance)


@pytest.fixture
def search_app(app):
    app.state.tools = {"web_search": fake_search()}
    return app


async def create(client, **settings):
    return (await client.post("/api/conversations", json={"settings": settings})).json()["id"]


async def chat(client, cid, text="hi"):
    return await client.post(f"/api/conversations/{cid}/chat", json={"content": text})


async def messages(client, cid):
    return (await client.get(f"/api/conversations/{cid}")).json()["messages"]


# ---- availability and settings ----

async def test_tools_that_need_no_key_are_listed_without_configuration(client):
    listed = (await client.get("/api/tools")).json()
    assert [t["name"] for t in listed] == ["calculator", "search_chats", "fetch_url"]  # web_search needs a key
    assert all(t["label"] and t["hint"] for t in listed)


async def test_configured_tools_are_listed(client, search_app):
    assert (await client.get("/api/tools")).json() == [{"name": "web_search", "label": "Web search", "hint": ""}]


async def test_a_new_conversation_has_no_tools_on(client):
    cid = await new_conv(client)
    assert (await client.get(f"/api/conversations/{cid}")).json()["settings"]["tools"] == []


async def test_tools_are_validated_and_deduplicated(client):
    assert (await client.post("/api/conversations", json={"settings": {"tools": ["rm_rf"]}})).status_code == 422
    assert (await client.post("/api/conversations", json={"settings": {"tools": "web_search"}})).status_code == 422
    cid = await create(client, tools=["web_search", "web_search"])
    assert (await client.get(f"/api/conversations/{cid}")).json()["settings"]["tools"] == ["web_search"]


async def test_a_tool_can_stay_saved_when_it_is_not_configured_any_more(client):
    # e.g. the Brave key was removed: saving other settings must still work
    cid = await create(client, tools=["web_search"])
    settings = {"tools": ["web_search"], "system_prompt": "x"}
    assert (await client.patch(f"/api/conversations/{cid}", json={"settings": settings})).status_code == 200


# ---- what the model gets ----

async def test_a_switched_on_tool_goes_to_the_model_with_its_guidance_and_the_call_limit(client, search_app, llm):
    await client.put("/api/custom-instructions", json={"text": "About me."})
    cid = await create(client, tools=["web_search"], system_prompt="Be brief.")
    await chat(client, cid)
    options = llm.calls[-1]["options"]
    assert list(options["tools"]) == ["web_search"] and options["max_tool_calls"] == 8
    assert options["instructions"] == "About me.\n\nBe brief.\n\nSEARCH GUIDANCE."


async def test_the_call_limit_is_configurable(client, search_app, llm):
    search_app.state.settings.max_tool_calls = 2
    await chat(client, await create(client, tools=["web_search"]))
    assert llm.calls[-1]["options"]["max_tool_calls"] == 2


async def test_a_tool_that_is_not_switched_on_is_not_offered(client, search_app, llm):
    await chat(client, await new_conv(client))
    assert "tools" not in llm.calls[-1]["options"] and llm.calls[-1]["options"]["instructions"] is None


async def test_a_switched_on_tool_that_is_not_configured_is_ignored(client, llm):
    r = await chat(client, await create(client, tools=["web_search"]))
    assert r.status_code == 200 and "tools" not in llm.calls[-1]["options"]


async def test_regenerate_and_edit_offer_the_tools_too(client, search_app, llm):
    cid = await create(client, tools=["web_search"])
    await chat(client, cid)
    await client.post(f"/api/conversations/{cid}/regenerate")
    assert "web_search" in llm.calls[-1]["options"]["tools"]
    await client.post(f"/api/conversations/{cid}/edit", json={"content": "again"})
    assert "web_search" in llm.calls[-1]["options"]["tools"]


# ---- what is saved and sent back to the browser ----

RESULTS = {"query": "python", "results": [{"title": "Python", "url": "https://python.org", "description": "d"}]}
RUN = {"type": "tool_call", "id": "c1", "name": "web_search", "status": "running", "arguments": {"query": "python"}}
DONE = {"type": "tool_call", "id": "c1", "name": "web_search", "status": "done",
        "arguments": {"query": "python"}, "display": RESULTS}


async def test_tool_calls_stream_to_the_browser_and_are_saved_with_the_reply(client, search_app, llm):
    llm.events = [RUN, DONE, {"type": "delta", "text": "Answer"}, {"type": "done"}]
    cid = await create(client, tools=["web_search"])
    r = await chat(client, cid)
    assert [e["type"] for e in parse_sse(r.text)][:4] == ["tool_call", "tool_call", "delta", "done"]
    saved = (await messages(client, cid))[-1]["meta"]
    assert saved["tools"] == [{"id": "c1", "name": "web_search", "arguments": {"query": "python"},
                               "status": "done", "display": RESULTS}]


async def test_a_failed_call_is_saved_with_its_error(client, search_app, llm):
    failed = {"type": "tool_call", "id": "c1", "name": "web_search", "arguments": {"query": "q"},
              "status": "error", "error": "Search rate limit reached."}
    llm.events = [RUN, failed, {"type": "delta", "text": "Sorry."}, {"type": "done"}]
    cid = await create(client, tools=["web_search"])
    await chat(client, cid)
    tool = (await messages(client, cid))[-1]["meta"]["tools"][0]
    assert (tool["status"], tool["error"]) == ("error", "Search rate limit reached.")


async def test_several_calls_are_saved_in_order(client, search_app, llm):
    second = {**RUN, "id": "c2", "arguments": {"query": "two"}}
    llm.events = [RUN, DONE, second, {**second, "status": "done", "display": RESULTS},
                  {"type": "delta", "text": "x"}, {"type": "done"}]
    cid = await create(client, tools=["web_search"])
    await chat(client, cid)
    assert [t["id"] for t in (await messages(client, cid))[-1]["meta"]["tools"]] == ["c1", "c2"]


async def test_a_call_still_running_when_the_reply_is_stopped_is_saved_as_stopped(client, search_app, llm):
    llm.events = [{"type": "delta", "text": "Let me look"}, RUN, {"type": "hang"}]
    cid = await create(client, tools=["web_search"])
    task = asyncio.create_task(chat(client, cid))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    meta = (await messages(client, cid))[-1]["meta"]
    assert meta["stopped"] is True and [(t["id"], t["status"]) for t in meta["tools"]] == [("c1", "stopped")]


async def test_a_reply_without_tools_has_no_tools_in_its_meta(client, search_app):
    cid = await create(client, tools=["web_search"])
    await chat(client, cid)
    assert "tools" not in (await messages(client, cid))[-1]["meta"]


async def test_later_turns_get_only_the_text_not_the_tool_traffic(client, search_app, llm):
    llm.events = [RUN, DONE, {"type": "delta", "text": "See [Python](https://python.org)."}, {"type": "done"}]
    cid = await create(client, tools=["web_search"])
    await chat(client, cid)
    await chat(client, cid, "and then?")
    assert llm.calls[-1]["messages"][:2] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "See [Python](https://python.org)."},
    ]


# ---- the other tools through the API ----

async def test_the_new_tools_can_be_switched_on_and_off_per_conversation(client):
    cid = await create(client, tools=["calculator", "fetch_url"])
    assert (await client.get(f"/api/conversations/{cid}")).json()["settings"]["tools"] == ["calculator", "fetch_url"]


async def test_each_enabled_tool_adds_its_guidance_and_is_given_to_the_model(client, llm):
    cid = await create(client, tools=["calculator", "search_chats", "fetch_url"])
    await chat(client, cid)
    options = llm.calls[-1]["options"]
    assert list(options["tools"]) == ["calculator", "search_chats", "fetch_url"]
    for words in ("calculator tool", "search_chats tool", "fetch_url tool"):
        assert words in options["instructions"]


async def test_tools_that_are_off_are_not_offered(client, llm):
    cid = await create(client, tools=["calculator"])
    await chat(client, cid)
    assert list(llm.calls[-1]["options"]["tools"]) == ["calculator"]
    assert "fetch_url" not in llm.calls[-1]["options"]["instructions"]


async def test_the_registered_tools_really_run_through_the_tool_registry(app):
    t = app.state.tools
    assert (await t["calculator"].run({"expression": "6*7"})).display["result"] == "42"
    assert (await t["search_chats"].run({"query": "nothing"})).display["results"] == []
