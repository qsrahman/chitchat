import pytest

from app import db, store
from tests.helpers import new_conv, parse_sse


async def patch(client, cid, body):
    return await client.patch(f"/api/conversations/{cid}", json=body)


async def chat(client, cid, text="hi"):
    return await client.post(f"/api/conversations/{cid}/chat", json={"content": text})


# ---- models ----

async def test_models_lists_default_first_with_reasoning_flags(client, llm):
    llm.models = ["gpt-5-mini", "llama3", "test-model", "o3"]
    got = (await client.get("/api/models")).json()
    assert got["default"] == "test-model"
    assert [(m["id"], m["reasoning"]) for m in got["models"]] == [
        ("test-model", False), ("gpt-5-mini", True), ("llama3", False), ("o3", True),
    ]


async def test_models_falls_back_to_the_default_when_the_endpoint_cannot_list(client, llm):
    llm.models = []
    got = (await client.get("/api/models")).json()
    assert [m["id"] for m in got["models"]] == ["test-model"]


# ---- conversation settings ----

async def test_new_conversation_has_default_settings(client):
    cid = await new_conv(client)
    assert (await client.get(f"/api/conversations/{cid}")).json()["settings"] == store.DEFAULT_SETTINGS


async def test_create_with_settings_and_replace_them(client):
    r = await client.post("/api/conversations", json={"settings": {"model": "m", "system_prompt": "  Be brief  "}})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert r.json()["settings"] == {**store.DEFAULT_SETTINGS, "model": "m", "system_prompt": "Be brief"}
    got = (await patch(client, cid, {"settings": {"reasoning_effort": "high"}})).json()
    assert got["settings"] == {**store.DEFAULT_SETTINGS, "reasoning_effort": "high"}  # replaced, not merged


async def test_patch_title_keeps_settings_and_settings_keep_title(client):
    cid = (await client.post("/api/conversations", json={"settings": {"model": "m"}})).json()["id"]
    assert (await patch(client, cid, {"title": "T"})).json()["settings"]["model"] == "m"
    got = (await patch(client, cid, {"settings": {"model": "n"}})).json()
    assert (got["title"], got["settings"]["model"]) == ("T", "n")


@pytest.mark.parametrize("body", [
    {},
    {"title": None},
    {"settings": {"reasoning_effort": "extreme"}},
    {"settings": {"temperature": 2.5}},
    {"settings": {"temperature": -0.1}},
    {"settings": {"unknown": 1}},
    {"settings": {"system_prompt": "x" * 10_001}},
    {"settings": {"model": ""}},
])
async def test_patch_validation(client, body):
    cid = await new_conv(client)
    assert (await patch(client, cid, body)).status_code == 422


async def test_settings_survive_migration_from_v1(tmp_path):
    path = str(tmp_path / "old.db")
    conn = db.connect(path)
    conn.executescript(db.MIGRATIONS[0])  # the phase 2 schema
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO conversations VALUES ('c1', 'Old chat', 't', 't')")
    conn.commit()
    conn.close()
    db.init(path)
    conn = db.connect(path)
    assert store.get_conversation(conn, "c1")["settings"] == store.DEFAULT_SETTINGS
    conn.close()


# ---- custom instructions ----

async def test_custom_instructions_roundtrip(client):
    assert (await client.get("/api/custom-instructions")).json() == {"text": ""}
    r = await client.put("/api/custom-instructions", json={"text": "  Call me Que  "})
    assert r.json() == {"text": "Call me Que"}
    assert (await client.get("/api/custom-instructions")).json() == {"text": "Call me Que"}
    await client.put("/api/custom-instructions", json={"text": ""})
    assert (await client.get("/api/custom-instructions")).json() == {"text": ""}


async def test_custom_instructions_validation(client):
    assert (await client.put("/api/custom-instructions", json={"text": "x" * 10_001})).status_code == 422
    assert (await client.put("/api/custom-instructions", json={})).status_code == 422


# ---- settings reach the model ----

async def test_turn_without_settings_sends_no_options(client, llm):
    await chat(client, await new_conv(client))
    assert llm.calls[-1]["model"] == "test-model"
    assert llm.calls[-1]["options"] == {"instructions": None, "temperature": None}


async def test_instructions_combine_custom_then_conversation(client, llm):
    await client.put("/api/custom-instructions", json={"text": "I am Que."})
    cid = (await client.post("/api/conversations", json={"settings": {"system_prompt": "Be brief."}})).json()["id"]
    await chat(client, cid)
    assert llm.calls[-1]["options"]["instructions"] == "I am Que.\n\nBe brief."
    await patch(client, cid, {"settings": {}})
    await chat(client, cid)
    assert llm.calls[-1]["options"]["instructions"] == "I am Que."


async def test_conversation_model_is_used_and_request_model_overrides_it(client, llm):
    cid = (await client.post("/api/conversations", json={"settings": {"model": "chosen"}})).json()["id"]
    await chat(client, cid)
    assert llm.calls[-1]["model"] == "chosen"
    await client.post(f"/api/conversations/{cid}/chat", json={"content": "x", "model": "explicit"})
    assert llm.calls[-1]["model"] == "explicit"


async def test_only_the_parameter_the_model_supports_is_sent(client, llm):
    both = {"reasoning_effort": "high", "temperature": 0.5}
    cid = (await client.post("/api/conversations", json={"settings": {**both, "model": "gpt-5-mini"}})).json()["id"]
    await chat(client, cid)
    assert llm.calls[-1]["options"] == {"instructions": None, "reasoning_effort": "high"}
    await patch(client, cid, {"settings": {**both, "model": "llama3"}})
    await chat(client, cid)
    assert llm.calls[-1]["options"] == {"instructions": None, "temperature": 0.5}


async def test_regenerate_and_edit_use_the_settings_too(client, llm):
    settings = {"model": "m", "system_prompt": "S"}
    cid = (await client.post("/api/conversations", json={"settings": settings})).json()["id"]
    await chat(client, cid)
    await client.post(f"/api/conversations/{cid}/regenerate")
    assert (llm.calls[-1]["model"], llm.calls[-1]["options"]["instructions"]) == ("m", "S")
    await client.post(f"/api/conversations/{cid}/edit", json={"content": "again"})
    assert (llm.calls[-1]["model"], llm.calls[-1]["options"]["instructions"]) == ("m", "S")


async def test_title_uses_the_default_model_not_the_chosen_one(client, llm):
    seen = []
    original = llm.generate_title

    async def spy(model, user_text, reply_text):
        seen.append(model)
        return await original(model, user_text, reply_text)

    llm.generate_title = spy
    cid = (await client.post("/api/conversations", json={"settings": {"model": "big-model"}})).json()["id"]
    r = await chat(client, cid)
    assert parse_sse(r.text)[-1]["type"] == "title"
    assert seen == ["test-model"]
