"""The defaults chosen in Settings: the model and thinking effort a chat uses when its own settings say "default",
and the tools a new chat starts with."""
import pytest

from app import store, tools
from tests.helpers import new_conv

# What nothing chosen means: no model or effort of its own, and every tool but web search on.
UNCHOSEN = {"model": None, "reasoning_effort": None, "tools": list(store.DEFAULT_TOOLS)}


async def chat(client, cid, **body):
    await client.post(f"/api/conversations/{cid}/chat", json={"content": "hi", **body})


async def test_every_tool_but_web_search_is_on_until_it_is_chosen(client):
    assert "web_search" not in store.DEFAULT_TOOLS
    assert set(store.DEFAULT_TOOLS) == set(tools.NAMES) - {"web_search"}  # a new tool is decided on, here, on purpose
    assert (await client.get("/api/defaults")).json() == UNCHOSEN


async def test_nothing_else_is_set_until_it_is_chosen(client):
    assert (await client.get("/api/defaults")).json() == UNCHOSEN


async def test_defaults_are_saved_and_read_back(client):
    body = {"model": "gpt-5-mini", "reasoning_effort": "low", "tools": ["calculator", "calculator"]}
    saved = (await client.put("/api/defaults", json=body)).json()
    assert saved == {"model": "gpt-5-mini", "reasoning_effort": "low", "tools": ["calculator"]}  # once each
    assert (await client.get("/api/defaults")).json() == saved
    nothing = {"model": None, "reasoning_effort": None, "tools": None}  # null puts each back to "not chosen"
    assert (await client.put("/api/defaults", json=nothing)).json() == UNCHOSEN


@pytest.mark.parametrize("body", [
    {"model": ""}, {"model": "x" * 201}, {"reasoning_effort": "extreme"}, {"tools": ["nope"]}, {"temperature": 1},
])
async def test_bad_defaults_are_refused(client, body):
    assert (await client.put("/api/defaults", json=body)).status_code == 422
    assert (await client.get("/api/defaults")).json() == UNCHOSEN


async def test_a_default_model_is_used_where_the_chat_has_none_and_the_chat_can_still_choose(client, llm):
    await client.put("/api/defaults", json={"model": "alpha"})
    cid = await new_conv(client)
    await chat(client, cid)
    assert llm.calls[-1]["model"] == "alpha"  # not the server's test-model
    await chat(client, cid, model="explicit")
    assert llm.calls[-1]["model"] == "explicit"
    own = (await client.post("/api/conversations", json={"settings": {"model": "own"}})).json()["id"]
    await chat(client, own)
    assert llm.calls[-1]["model"] == "own"


async def test_without_a_default_model_the_server_one_is_used(client, llm):
    await chat(client, await new_conv(client))
    assert llm.calls[-1]["model"] == "test-model"


async def test_the_model_list_leads_with_the_default_in_force(client, llm):
    llm.models = ["beta", "alpha"]
    assert (await client.get("/api/models")).json()["default"] == "test-model"
    await client.put("/api/defaults", json={"model": "alpha"})
    got = (await client.get("/api/models")).json()
    assert got["default"] == "alpha"
    assert [m["id"] for m in got["models"]] == ["alpha", "beta"]


async def test_a_default_effort_applies_to_reasoning_models_only_where_the_chat_sets_none(client, llm):
    await client.put("/api/defaults", json={"model": "gpt-5-mini", "reasoning_effort": "high"})
    cid = await new_conv(client)
    await chat(client, cid)
    assert llm.calls[-1]["options"]["reasoning_effort"] == "high"
    low = (await client.post("/api/conversations", json={"settings": {"reasoning_effort": "low"}})).json()["id"]
    await chat(client, low)
    assert llm.calls[-1]["options"]["reasoning_effort"] == "low"  # the chat's own choice wins
    other = (await client.post("/api/conversations", json={"settings": {"model": "llama3"}})).json()["id"]
    await chat(client, other)
    assert "reasoning_effort" not in llm.calls[-1]["options"]  # a model that has no such thing


async def test_a_default_that_no_longer_validates_is_ignored_not_fatal(client, app):
    from app import db, store

    with db.connect(app.state.settings.db_path) as conn:
        store.set_app_setting(conn, "defaults", '{"tools": ["a tool that was removed"]}')
    assert (await client.get("/api/defaults")).json() == UNCHOSEN


async def test_a_new_chat_starts_with_the_default_tools_unless_it_brings_its_own_settings(client):
    await client.put("/api/defaults", json={"tools": ["calculator"]})
    plain = (await client.post("/api/conversations")).json()
    assert plain["settings"]["tools"] == ["calculator"]
    own = (await client.post("/api/conversations", json={"settings": {"tools": []}})).json()
    assert own["settings"]["tools"] == []


async def test_a_new_chat_has_every_tool_but_web_search_on_and_switching_them_all_off_is_kept(client):
    fresh = (await client.post("/api/conversations")).json()["settings"]["tools"]
    assert fresh == list(store.DEFAULT_TOOLS) and "web_search" not in fresh
    await client.put("/api/defaults", json={"tools": []})  # someone who wants none
    assert (await client.post("/api/conversations")).json()["settings"]["tools"] == []
    assert (await client.get("/api/defaults")).json()["tools"] == []  # not put back to the default


async def test_only_what_is_sent_changes_the_rest_stays(client):
    await client.put("/api/defaults", json={"model": "alpha", "reasoning_effort": "low", "tools": ["calculator"]})
    after = (await client.put("/api/defaults", json={"reasoning_effort": "high"})).json()
    assert after == {"model": "alpha", "reasoning_effort": "high", "tools": ["calculator"]}
    assert (await client.put("/api/defaults", json={})).json() == after  # nothing named: nothing changes


async def test_changing_the_model_does_not_make_the_tools_a_choice(client, monkeypatch):
    await client.put("/api/defaults", json={"model": "alpha", "reasoning_effort": "high"})
    monkeypatch.setattr(store, "DEFAULT_TOOLS", ("calculator",))  # a later version with another default list
    assert (await client.get("/api/defaults")).json()["tools"] == ["calculator"]  # follows it: never frozen as a copy


async def test_a_record_saved_before_tools_were_on_by_default_does_not_hold_them_off(client, app):
    """Older versions wrote every field when one changed, so an empty list meant "never chosen" (this was someone's
    database: effort set in Settings, tools: [] written along with it)."""
    from contextlib import closing

    from app import db

    with closing(db.connect(app.state.settings.db_path)) as conn:
        store.set_app_setting(conn, "defaults", '{"model":null,"reasoning_effort":"medium","tools":[]}')
    got = (await client.get("/api/defaults")).json()
    assert got == {"model": None, "reasoning_effort": "medium", "tools": list(store.DEFAULT_TOOLS)}
    assert (await client.post("/api/conversations")).json()["settings"]["tools"] == list(store.DEFAULT_TOOLS)
    with closing(db.connect(app.state.settings.db_path)) as conn:
        store.set_app_setting(conn, "defaults", '{"model":null,"reasoning_effort":null,"tools":["calculator"]}')
    assert (await client.get("/api/defaults")).json()["tools"] == ["calculator"]  # a real choice from then is kept


async def test_none_chosen_now_is_kept_because_it_was_chosen(client):
    await client.put("/api/defaults", json={"tools": []})
    await client.put("/api/defaults", json={"model": "alpha"})  # saving something else does not undo it
    assert (await client.get("/api/defaults")).json()["tools"] == []
