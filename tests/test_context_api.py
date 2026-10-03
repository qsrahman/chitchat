"""Trimming old turns on a custom endpoint, through the API."""
import pytest

from tests.helpers import new_conv, parse_sse

LOCAL = "http://localhost:11434/v1"
ITEM = {"id": "cmp_1", "type": "compaction", "encrypted_content": "opaque"}


@pytest.fixture
def local(app):
    """A custom endpoint with a tiny history budget: 100 tokens, 10 of them kept back for the reply."""
    s = app.state.settings
    s.openai_base_url, s.context_tokens, s.openai_max_output_tokens = LOCAL, 100, 10
    return s


async def say(client, cid, text):
    r = await client.post(f"/api/conversations/{cid}/chat", json={"content": text})
    assert r.status_code == 200
    return parse_sse(r.text)


def question(i):
    return f"question {i} ".ljust(60, ".")  # 20 tokens


async def stored(client, cid):
    return (await client.get(f"/api/conversations/{cid}")).json()["messages"]


async def test_a_long_chat_is_trimmed_for_the_model_but_kept_in_full(client, llm, local):
    cid = await new_conv(client)
    for i in range(6):
        await say(client, cid, question(i))
    sent = [m["content"] for m in llm.calls[-1]["messages"]]
    assert sent[-1] == question(5) and sent[0].startswith("question") and len(sent) < 11  # older ones are gone
    assert len(await stored(client, cid)) == 12  # nothing was deleted
    assert [m["content"] for m in (await stored(client, cid))[:1]] == [question(0)]


async def test_the_browser_is_told_how_many_were_left_out_and_it_is_saved_with_the_reply(client, llm, local):
    cid = await new_conv(client)
    for i in range(5):
        events = await say(client, cid, question(i))
    trimmed = [e for e in events if e["type"] == "context_trimmed"]
    before = 9  # four earlier pairs and the new question
    assert len(trimmed) == 1 and trimmed[0]["count"] == before - len(llm.calls[-1]["messages"])
    assert events[0] == trimmed[0]  # before the reply starts
    assert (await stored(client, cid))[-1]["meta"]["trimmed"] == trimmed[0]["count"]


async def test_nothing_is_said_when_nothing_was_left_out(client, llm, local):
    cid = await new_conv(client)
    events = await say(client, cid, "hi")
    assert all(e["type"] != "context_trimmed" for e in events)
    assert "trimmed" not in (await stored(client, cid))[-1]["meta"]


async def test_the_history_sent_starts_with_a_user_message(client, llm, local):
    cid = await new_conv(client)
    for i in range(8):
        await say(client, cid, question(i))
        assert llm.calls[-1]["messages"][0]["role"] == "user"


async def test_regenerating_trims_too(client, llm, local):
    cid = await new_conv(client)
    for i in range(6):
        await say(client, cid, question(i))
    r = await client.post(f"/api/conversations/{cid}/regenerate")
    assert parse_sse(r.text)[0]["type"] == "context_trimmed"
    assert len(llm.calls[-1]["messages"]) < 11


async def test_the_instructions_count_against_the_budget(client, llm, local):
    cid = await new_conv(client)
    for i in range(3):
        await say(client, cid, question(i))
    plain = len(llm.calls[-1]["messages"])
    await client.put("/api/custom-instructions", json={"text": "x" * 120})  # 40 tokens
    await say(client, cid, question(3))
    assert len(llm.calls[-1]["messages"]) < plain + 2  # a smaller share of history than the roomy case would allow


async def test_openai_itself_sends_everything(client, llm):
    cid = await new_conv(client)
    for i in range(6):
        await say(client, cid, question(i))
    assert len(llm.calls[-1]["messages"]) == 11


async def test_a_limit_of_zero_sends_everything_on_a_custom_endpoint(client, llm, local):
    local.context_tokens = 0
    cid = await new_conv(client)
    for i in range(6):
        await say(client, cid, question(i))
    assert len(llm.calls[-1]["messages"]) == 11


async def test_the_default_limit_on_a_custom_endpoint_is_roomy(client, llm, app):
    app.state.settings.openai_base_url = LOCAL
    cid = await new_conv(client)
    for i in range(6):
        await say(client, cid, question(i))
    assert len(llm.calls[-1]["messages"]) == 11  # 32,000 tokens: a short chat is untouched


async def test_a_huge_message_is_trimmed_against_the_default_limit(client, llm, app):
    app.state.settings.openai_base_url = LOCAL
    cid = await new_conv(client)
    for _ in range(4):
        await say(client, cid, "x" * 60_000)  # about 20,000 tokens each
    assert len(llm.calls[-1]["messages"]) < 7


# ---- an OpenAI compaction item is only ever sent to OpenAI ----

async def test_a_compaction_from_openai_is_not_sent_to_a_custom_endpoint(client, llm, app):
    cid = await new_conv(client)
    await say(client, cid, "first")
    llm.events = [{"type": "delta", "text": "ok"}, {"type": "compaction", "item": ITEM, "after_reply": True},
                  {"type": "done"}]
    await say(client, cid, "second")  # on OpenAI: this reply saved a compaction
    llm.events = [{"type": "delta", "text": "fine"}, {"type": "done"}]
    await say(client, cid, "third")
    assert llm.calls[-1]["messages"][0] == {"compaction": ITEM}  # still OpenAI: used

    app.state.settings.openai_base_url = LOCAL  # now the chat continues on a local model
    app.state.settings.context_tokens = 0
    await say(client, cid, "fourth")
    sent = llm.calls[-1]["messages"]
    assert not any("compaction" in m for m in sent)  # a local model couldn't read it
    assert [m["content"] for m in sent if m["role"] == "user"] == ["first", "second", "third", "fourth"]
