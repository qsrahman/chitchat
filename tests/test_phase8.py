"""Compaction bookkeeping, search and export, through the API."""
import pytest

from tests.helpers import new_conv, parse_sse

ITEM = {"id": "cmp_1", "type": "compaction", "encrypted_content": "opaque"}


async def say(client, cid, text):
    r = await client.post(f"/api/conversations/{cid}/chat", json={"content": text})
    assert r.status_code == 200
    return parse_sse(r.text)


def reply(text, *extra):
    return [{"type": "delta", "text": text}, *extra, {"type": "done"}]


# ---- compaction ----

async def test_a_compaction_is_saved_and_the_browser_only_hears_that_it_happened(client, llm):
    cid = await new_conv(client)
    llm.events = reply("ok", {"type": "compaction", "item": ITEM, "after_reply": False})
    events = await say(client, cid, "hi")
    assert {"type": "compaction", "after_reply": False} in events
    assert "opaque" not in str(events)
    saved = (await client.get(f"/api/conversations/{cid}")).json()["messages"][-1]
    assert saved["meta"]["compaction"] == {"after_reply": False}  # no encrypted item for the browser


@pytest.mark.parametrize("after_reply, resent", [(True, []), (False, ["answer 1"])])
async def test_the_next_turn_starts_from_the_compaction_item(client, llm, after_reply, resent):
    cid = await new_conv(client)
    await say(client, cid, "first")  # plain reply, sent in full again later
    llm.events = reply("answer 1", {"type": "compaction", "item": ITEM, "after_reply": after_reply})
    await say(client, cid, "second")
    llm.events = reply("answer 2")
    await say(client, cid, "third")
    sent = llm.calls[-1]["messages"]
    assert sent[0] == {"compaction": ITEM}
    assert [m["content"] for m in sent[1:]] == [*resent, "third"]


async def test_the_whole_history_is_sent_again_once_the_compacted_reply_is_regenerated(client, llm):
    cid = await new_conv(client)
    await say(client, cid, "first")
    llm.events = reply("answer", {"type": "compaction", "item": ITEM, "after_reply": True})
    await say(client, cid, "second")
    llm.events = reply("again")
    await client.post(f"/api/conversations/{cid}/regenerate")
    sent = llm.calls[-1]["messages"]
    assert not any("compaction" in m for m in sent)
    assert [m["content"] for m in sent] == ["first", "Hello world", "second"]


async def test_a_conversation_without_compaction_sends_everything(client, llm):
    cid = await new_conv(client)
    await say(client, cid, "one")
    await say(client, cid, "two")
    assert [m["content"] for m in llm.calls[-1]["messages"]] == ["one", "Hello world", "two"]


# ---- search ----

async def titled(client, llm, title, *texts):
    cid = await new_conv(client)
    llm.title = title
    for t in texts:
        await say(client, cid, t)
    return cid


async def search(client, q):
    r = await client.get("/api/search", params={"q": q})
    assert r.status_code == 200
    return r.json()


async def test_search_finds_the_conversation_with_a_marked_snippet(client, llm):
    llm.events = reply("Use a mutex around the counter.")
    cid = await titled(client, llm, "Threads", "How do I share a counter?")
    llm.events = reply("Cats purr.")
    await titled(client, llm, "Other", "Tell me about cats")
    hits = await search(client, "mutex")
    assert [h["id"] for h in hits] == [cid]
    assert hits[0]["title"] == "Threads"
    assert "\x02mutex\x03" in hits[0]["snippet"]


async def test_search_matches_word_stems_and_prefixes(client, llm):
    llm.events = reply("Running tests")
    await titled(client, llm, "T", "go")
    assert len(await search(client, "run")) == 1  # prefix of the last word
    assert len(await search(client, "tests running")) == 1  # every word, any order; stemmed


async def test_search_lists_each_conversation_once(client, llm):
    llm.events = reply("python python python")
    await titled(client, llm, "T", "python one", "python two")
    assert len(await search(client, "python")) == 1


async def test_search_input_cannot_break_the_query_syntax(client, llm):
    llm.events = reply("plain text")
    await titled(client, llm, "T", "hello")
    for q in ['"', "AND", "a OR", "x*", "(", "NEAR(", "-", "col:", "'"]:
        assert isinstance(await search(client, q), list)
    assert await search(client, "!!!") == []


async def test_search_follows_edits_and_deletes(client, llm):
    llm.events = reply("zebra")
    cid = await titled(client, llm, "T", "hello")
    assert len(await search(client, "zebra")) == 1
    await client.post(f"/api/conversations/{cid}/edit", json={"content": "giraffe question"})
    assert len(await search(client, "giraffe")) == 1
    await client.delete(f"/api/conversations/{cid}")
    assert await search(client, "giraffe") == [] == await search(client, "zebra")


async def test_search_needs_a_query(client):
    assert (await client.get("/api/search")).status_code == 422
    assert (await client.get("/api/search", params={"q": ""})).status_code == 422


# ---- export ----

async def test_markdown_export(client, llm):
    llm.events = reply("Hello **there**")
    cid = await titled(client, llm, "My chat / 1", "hi")
    r = await client.get(f"/api/conversations/{cid}/export")
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.headers["content-disposition"] == 'attachment; filename="My-chat-1.md"'
    assert r.text == "# My chat / 1\n\n## You\n\nhi\n\n## Assistant (test-model)\n\nHello **there**\n"  # who answered


async def test_json_export_has_messages_and_no_encrypted_item(client, llm):
    llm.events = reply("ok", {"type": "compaction", "item": ITEM, "after_reply": True})
    cid = await titled(client, llm, "T", "hi")
    r = await client.get(f"/api/conversations/{cid}/export", params={"format": "json"})
    data = r.json()
    assert r.headers["content-disposition"] == 'attachment; filename="T.json"'
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    assert data["title"] == "T"
    assert "opaque" not in r.text


async def test_export_lists_attachment_names(client, llm):
    from tests.helpers import PNG, upload

    cid = await new_conv(client)
    aid = (await upload(client, "cat.png", PNG)).json()["id"]
    await client.post(f"/api/conversations/{cid}/chat", json={"content": "look", "attachments": [aid]})
    assert "*Attached: cat.png*" in (await client.get(f"/api/conversations/{cid}/export")).text


async def test_export_errors(client):
    assert (await client.get("/api/conversations/nope/export")).status_code == 404
    cid = await new_conv(client)
    assert (await client.get(f"/api/conversations/{cid}/export", params={"format": "pdf"})).status_code == 422


def test_migration_to_v4_indexes_existing_messages(tmp_path):
    from app import db, store

    path = str(tmp_path / "old.db")
    conn = db.connect(path)
    for script in db.MIGRATIONS[:3]:
        conn.executescript(script)
    conn.execute("PRAGMA user_version = 3")
    conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) VALUES ('c1', 'Old', 't', 't')")
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES ('c1', 'user', 'quokka', 't')"
    )
    conn.commit()
    conn.close()
    db.init(path)
    conn = db.connect(path)
    assert [r["id"] for r in store.search_conversations(conn, "quokka")] == ["c1"]
    conn.close()


async def test_markdown_export_says_what_the_tools_found(client, llm):
    llm.events = [
        {"type": "tool_call", "id": "a", "name": "web_search", "status": "done", "arguments": {"query": "rust"},
         "display": {"query": "rust\n# not a heading", "results": [
             {"title": "Rust [lang]\n- injected", "url": "https://www.rust-lang.org/", "description": "d"},
             {"title": "Bad link", "url": "javascript:alert(1)", "description": "d"},
             {"title": "Spaces", "url": "https://a.example/x y", "description": "d"}]}},
        {"type": "tool_call", "id": "b", "name": "fetch_url", "status": "done", "arguments": {},
         "display": {"url": "https://example.com/page", "title": "A page", "characters": 10}},
        {"type": "tool_call", "id": "c", "name": "calculator", "status": "done", "arguments": {},
         "display": {"expression": "2*3", "result": "6"}},
        {"type": "tool_call", "id": "d", "name": "search_chats", "status": "error", "arguments": {}, "error": "boom"},
        {"type": "tool_call", "id": "e", "name": "fetch_url", "status": "done", "arguments": {}, "display": "odd"},
        {"type": "delta", "text": "Answer"}, {"type": "done"},
    ]
    cid = await titled(client, llm, "Tools", "go")
    text = (await client.get(f"/api/conversations/{cid}/export")).text
    assert text == (
        "# Tools\n\n## You\n\ngo\n\n## Assistant (test-model)\n\n"
        "*Searched the web for* “rust # not a heading”\n"
        "- [Rust (lang) - injected](https://www.rust-lang.org/)\n"  # one line; the brackets cannot end the link
        "- Bad link\n"  # not a web address: the title, no link
        "- Spaces\n\n"
        "*Read* [A page](https://example.com/page)\n\n"
        "*Calculated* `2*3 = 6`\n\n"  # an outcome that failed, or whose details are not as expected, adds nothing
        "Answer\n"
    )


async def test_markdown_export_names_the_chats_and_files_the_model_read(client, llm):
    llm.events = [
        {"type": "tool_call", "id": "a", "name": "read_chat", "status": "done", "arguments": {},
         "display": {"id": "x", "title": "Plans\n# for May", "from": 1, "to": 3, "total": 3}},
        {"type": "tool_call", "id": "b", "name": "read_attachment", "status": "done", "arguments": {},
         "display": {"name": "notes.txt", "kind": "text", "characters": 5, "offset": 0, "total": 5}},
        {"type": "tool_call", "id": "c", "name": "read_attachment", "status": "done", "arguments": {},
         "display": {"files": ["notes.txt"]}},  # a listing names nothing worth a line
        {"type": "tool_call", "id": "d", "name": "get_datetime", "status": "done", "arguments": {},
         "display": {"now": "Monday", "timezone": "UTC", "also": []}},
        {"type": "delta", "text": "Answer"}, {"type": "done"},
    ]
    cid = await titled(client, llm, "Reads", "go")
    text = (await client.get(f"/api/conversations/{cid}/export")).text
    assert text == (
        "# Reads\n\n## You\n\ngo\n\n## Assistant (test-model)\n\n"
        "*Read the chat* “Plans # for May”\n\n*Read the file* “notes.txt”\n\nAnswer\n")
