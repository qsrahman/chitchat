"""Search finds a chat by its title as well as by what was said in it (migration v5, store.search_conversations)."""
import pytest

from app import db, store
from tests.helpers import new_conv, parse_sse

TITLE_ONLY = {"title": "Quokka care", "text": "How do I look after one?"}


async def say(client, cid, text):
    r = await client.post(f"/api/conversations/{cid}/chat", json={"content": text})
    assert r.status_code == 200
    return parse_sse(r.text)


async def search(client, q, **params):
    r = await client.get("/api/search", params={"q": q, **params})
    assert r.status_code == 200
    return r.json()


async def titled(client, llm, title, *texts, reply="Noted."):
    llm.title = title
    llm.events = [{"type": "delta", "text": reply}, {"type": "done"}]
    cid = await new_conv(client)
    for text in texts:
        await say(client, cid, text)
    return cid


async def test_a_chat_is_found_by_its_title_alone(client, llm):
    cid = await titled(client, llm, "Quokka care", "How do I look after one?")
    [hit] = await search(client, "quokka")
    assert hit["id"] == cid and hit["title"] == "Quokka care"
    assert hit["title_marked"] == "\x02Quokka\x03 care"
    assert hit["message_id"] is None and hit["snippet"] == "" and hit["role"] is None


async def test_a_chat_is_found_by_a_message_alone_and_its_title_is_unmarked(client, llm):
    cid = await titled(client, llm, "Gardening", "Where do wombats sleep?")
    [hit] = await search(client, "wombats")
    assert hit["id"] == cid and hit["title_marked"] == "Gardening"
    assert "\x02wombats\x03" in hit["snippet"] and hit["role"] == "user"
    messages = (await client.get(f"/api/conversations/{cid}")).json()["messages"]
    assert hit["message_id"] == messages[0]["id"]  # the id a page can scroll to


async def test_a_chat_matching_both_ways_comes_once_with_both(client, llm):
    cid = await titled(client, llm, "Wombat facts", "Tell me about a wombat")
    [hit] = await search(client, "wombat")
    assert hit["id"] == cid and hit["title_marked"] == "\x02Wombat\x03 facts"
    assert "\x02wombat\x03" in hit["snippet"] and hit["message_id"]


async def test_title_matches_come_before_matches_inside_chats(client, llm):
    inside = await titled(client, llm, "Gardening", "my llama escaped")
    by_title = await titled(client, llm, "Llama care", "unrelated question")
    assert [h["id"] for h in await search(client, "llama")] == [by_title, inside]


async def test_title_words_match_by_stem_and_prefix_like_messages_do(client, llm):
    cid = await titled(client, llm, "Running a marathon", "hello")
    assert [h["id"] for h in await search(client, "runs marath")] == [cid]


async def test_renaming_moves_the_chat_in_the_index(client, llm):
    cid = await titled(client, llm, "Old name", "hello")
    assert await search(client, "zebra") == []
    await client.patch(f"/api/conversations/{cid}", json={"title": "Zebra crossing"})
    assert [h["id"] for h in await search(client, "zebra")] == [cid]
    assert await search(client, "old") == []


async def test_deleting_a_chat_removes_its_title_from_the_index(client, llm):
    cid = await titled(client, llm, "Giraffe", "hello")
    assert len(await search(client, "giraffe")) == 1
    await client.delete(f"/api/conversations/{cid}")
    assert await search(client, "giraffe") == []


async def test_odd_input_cannot_break_the_title_query_either(client, llm):
    await titled(client, llm, "Plain title", "hello")
    for q in ['"', "AND", "x*", "(", "title:", "NEAR(", "-"]:
        assert isinstance(await search(client, q), list)


def test_the_migration_indexes_titles_that_already_exist(tmp_path):
    path = str(tmp_path / "old.db")
    conn = db.connect(path)
    for script in db.MIGRATIONS[:4]:
        conn.executescript(script)
    conn.execute("PRAGMA user_version = 4")
    conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) VALUES ('c1', 'Platypus', 't', 't')")
    conn.commit()
    conn.close()
    db.init(path)
    conn = db.connect(path)
    assert [r["id"] for r in store.search_conversations(conn, "platypus")] == ["c1"]
    conn.close()


def test_one_conversation_can_be_left_out(tmp_path):
    path = str(tmp_path / "x.db")
    db.init(path)
    conn = db.connect(path)
    a = store.create_conversation(conn, "Otter notes")["id"]
    b = store.create_conversation(conn, "More otter notes")["id"]
    assert {r["id"] for r in store.search_conversations(conn, "otter")} == {a, b}
    assert [r["id"] for r in store.search_conversations(conn, "otter", exclude=a)] == [b]
    conn.close()


@pytest.mark.parametrize("limit", [1, 2])
def test_the_limit_counts_conversations(tmp_path, limit):
    path = str(tmp_path / "x.db")
    db.init(path)
    conn = db.connect(path)
    for i in range(4):
        cid = store.create_conversation(conn, f"Heron {i}")["id"]
        store.add_message(conn, cid, "user", "heron heron")
    assert len(store.search_conversations(conn, "heron", limit=limit)) == limit
    conn.close()


async def test_the_chat_search_tool_reports_a_title_match_as_one(client, llm, app):
    from app import tools

    await titled(client, llm, "Quokka care", "How do I look after one?")
    result = await tools.search_chats({"query": "quokka"}, db_path=app.state.settings.db_path)
    assert 'the title matches' in result.output and "wrote:" not in result.output
    assert result.display["results"][0]["title"] == "Quokka care" and result.display["results"][0]["snippet"] == ""


# ---- the tool leaves out the chat it is running in ----

async def test_search_chats_leaves_out_the_conversation_it_runs_in(client, llm, app):
    from app import tools

    here = await titled(client, llm, "Quokka here", "quokka question")
    there = await titled(client, llm, "Quokka there", "another quokka question")
    path = app.state.settings.db_path
    both = await tools.search_chats({"query": "quokka"}, db_path=path)
    assert {r["id"] for r in both.display["results"]} == {here, there}
    others = await tools.search_chats({"query": "quokka"}, db_path=path, conversation_id=here)
    assert [r["id"] for r in others.display["results"]] == [there]


async def test_a_reply_gets_the_tool_bound_to_its_own_chat(client, llm):
    here = await titled(client, llm, "Quokka here", "quokka question")
    there = await titled(client, llm, "Quokka there", "another quokka question")
    r = await client.patch(f"/api/conversations/{here}", json={"settings": {"tools": ["search_chats", "calculator"]}})
    assert r.status_code == 200
    await say(client, here, "what did we say about quokkas?")
    tool = llm.calls[-1]["options"]["tools"]["search_chats"]
    found = await tool.run({"query": "quokka"})
    assert [r["id"] for r in found.display["results"]] == [there]  # not the chat it is running in
    assert (await llm.calls[-1]["options"]["tools"]["calculator"].run({"expression": "2+2"})).display["result"] == "4"


async def test_the_shared_tool_is_not_changed_by_binding(app):
    from app import tools

    shared = app.state.tools["search_chats"]
    bound = tools.bound_to(shared, "abc")
    assert bound is not shared and bound.run is not shared.run
    assert tools.bound_to(app.state.tools["calculator"], "abc") is app.state.tools["calculator"]  # not per-chat: as is


def test_the_description_tells_the_model_it_searches_other_chats(app):
    tool = app.state.tools["search_chats"]
    assert tool.per_chat and "OTHER" in tool.description and "other conversations" in tool.guidance
