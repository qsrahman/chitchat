"""Export everything and import it (app/backup.py)."""
import io
import json
import zipfile

import pytest

from app import db, store
from app.backup import MAX_CHATS
from tests.helpers import PNG, new_conv, parse_sse, upload

NO_EXTRAS = {"attachments": 0, "custom_instructions": False}  # what an import result says besides the counts
ITEM = {"id": "cmp_1", "type": "compaction", "encrypted_content": "opaque"}


async def say(client, cid, text):
    r = await client.post(f"/api/conversations/{cid}/chat", json={"content": text})
    assert r.status_code == 200
    return parse_sse(r.text)


async def make_chat(client, llm, title, *texts, reply="Noted.", settings=None):
    llm.title = title
    llm.events = [{"type": "delta", "text": reply}, {"type": "done"}]
    cid = (await client.post("/api/conversations", json={"settings": settings or {}})).json()["id"]
    for text in texts:
        await say(client, cid, text)
    return cid


async def export_json(client):
    r = await client.get("/api/export")
    assert r.status_code == 200
    return r


async def import_file(client, data, name="chats.json"):
    if not isinstance(data, bytes):
        data = json.dumps(data).encode()
    return await client.post("/api/import", files={"file": (name, data)})


# ---- export ----

async def test_export_all_is_one_json_file_with_every_conversation_and_message(client, llm):
    a = await make_chat(client, llm, "First chat", "hello one", "hello two")
    prefs = {"system_prompt": "Be brief", "tools": ["calculator"]}
    b = await make_chat(client, llm, "Second chat", "hi", settings=prefs)
    r = await export_json(client)
    assert r.headers["content-type"].startswith("application/json")
    disposition = r.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="chitchat-') and disposition.endswith('.json"')
    data = r.json()
    assert (data["format"], data["version"]) == ("chitchat-backup", 2) and data["exported_at"]
    assert [c["id"] for c in data["conversations"]] == [a, b]  # oldest first
    first, second_chat = data["conversations"]
    assert first["title"] == "First chat" and [m["content"] for m in first["messages"]] == [
        "hello one", "Noted.", "hello two", "Noted."]
    assert second_chat["settings"]["system_prompt"] == "Be brief" and second_chat["settings"]["tools"] == ["calculator"]
    assert first["messages"][0].keys() >= {"role", "content", "meta", "created_at", "parent"}


async def test_an_empty_export_is_valid(client):
    data = (await export_json(client)).json()
    assert data["conversations"] == []


async def test_the_export_never_contains_the_encrypted_compaction_item(client, llm):
    cid = await new_conv(client)
    llm.events = [{"type": "delta", "text": "ok"}, {"type": "compaction", "item": ITEM, "after_reply": True},
                  {"type": "done"}]
    await say(client, cid, "hi")
    text = (await export_json(client)).text
    assert "opaque" not in text and '"after_reply": true' in text


async def test_export_as_markdown_is_a_zip_with_one_file_per_chat(client, llm):
    await make_chat(client, llm, "Chat / one", "first question", reply="First **answer**")
    await make_chat(client, llm, "Chat / one", "second question", reply="Second answer")  # the same title, twice
    await make_chat(client, llm, "日本語", "hi")
    r = await client.get("/api/export", params={"format": "md"})
    assert r.headers["content-type"] == "application/zip" and r.headers["content-disposition"].endswith('.zip"')
    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        names = archive.namelist()
        assert len(names) == 3 and len(set(names)) == 3  # same title, different names
        assert all(n.endswith(".md") and "/" not in n and n.isascii() for n in names)
        body = archive.read(names[0]).decode()
    assert body.startswith("# Chat / one\n\n## You\n\nfirst question\n\n## Assistant\n\nFirst **answer**")


async def test_the_export_format_is_validated(client):
    assert (await client.get("/api/export", params={"format": "pdf"})).status_code == 422


# ---- the round trip ----

async def test_what_is_exported_can_be_imported_into_a_fresh_database_unchanged(client, llm, second):
    await make_chat(client, llm, "Wombats", "where do wombats sleep?", "and what do they eat?",
                    settings={"system_prompt": "Be brief", "reasoning_effort": "low", "tools": ["calculator"]})
    await make_chat(client, llm, "Quokkas", "tell me about quokkas")
    exported = (await export_json(client)).json()
    r = await import_file(second, (await export_json(client)).content)
    assert r.status_code == 201 and r.json() == {"imported": 2, "skipped": 0, "messages": 6} | NO_EXTRAS
    again = (await export_json(second)).json()
    for before, after in zip(exported["conversations"], again["conversations"], strict=True):
        assert after["id"] == before["id"] and after["title"] == before["title"]
        assert after["settings"] == before["settings"]
        assert after["created_at"] == before["created_at"] and after["updated_at"] == before["updated_at"]
        assert [(m["role"], m["content"], m["created_at"]) for m in after["messages"]] == [
            (m["role"], m["content"], m["created_at"]) for m in before["messages"]]


async def test_importing_the_same_file_again_adds_nothing(client, llm, second):
    await make_chat(client, llm, "Wombats", "hello")
    data = (await export_json(client)).content
    assert (await import_file(second, data)).json()["imported"] == 1
    r = await import_file(second, data)
    assert r.json() == {"imported": 0, "skipped": 1, "messages": 0} | NO_EXTRAS
    assert len((await second.get("/api/conversations")).json()) == 1


async def test_a_chat_already_here_is_skipped_and_never_overwritten(client, llm):
    cid = await make_chat(client, llm, "Original", "my own words")
    data = json.loads((await export_json(client)).content)
    data["conversations"][0]["title"] = "Changed in the file"
    data["conversations"][0]["messages"][0]["content"] = "other words"
    r = await import_file(client, data)
    assert r.json()["skipped"] == 1
    conv = (await client.get(f"/api/conversations/{cid}")).json()
    assert conv["title"] == "Original" and conv["messages"][0]["content"] == "my own words"


async def test_imported_chats_are_searchable_by_title_and_by_message(client, llm, second):
    await make_chat(client, llm, "Aardvark facts", "where do platypuses live?")
    await import_file(second, (await export_json(client)).content)
    assert len((await second.get("/api/search", params={"q": "aardvark"})).json()) == 1  # by title
    assert len((await second.get("/api/search", params={"q": "platypuses"})).json()) == 1  # by message


async def test_an_imported_chat_can_be_opened_and_continued(client, llm, second):
    cid = await make_chat(client, llm, "Wombats", "where do wombats sleep?")
    await import_file(second, (await export_json(client)).content)
    conv = (await second.get(f"/api/conversations/{cid}")).json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    events = await say(second, cid, "and what do they eat?")
    assert events[-1]["type"] in ("done", "title")
    assert len((await second.get(f"/api/conversations/{cid}")).json()["messages"]) == 4


async def test_the_export_of_a_single_chat_can_be_imported_too(client, llm, second):
    cid = await make_chat(client, llm, "Just this one", "hello")
    single = (await client.get(f"/api/conversations/{cid}/export", params={"format": "json"})).content
    r = await import_file(second, single)
    assert r.status_code == 201 and r.json()["imported"] == 1
    assert (await second.get(f"/api/conversations/{cid}")).json()["title"] == "Just this one"


async def test_message_metadata_survives_the_round_trip(client, llm, second):
    cid = await new_conv(client)
    llm.events = [
        {"type": "reasoning_delta", "text": "thinking"}, {"type": "delta", "text": "answer"},
        {"type": "tool_call", "id": "c1", "name": "calculator", "status": "done", "arguments": {"expression": "1+1"},
         "display": {"expression": "1+1", "result": "2"}},
        {"type": "done", "usage": {"input_tokens": 5, "output_tokens": 7, "reasoning_tokens": 2}},
    ]
    await say(client, cid, "hi")
    before = (await client.get(f"/api/conversations/{cid}")).json()["messages"][-1]["meta"]
    await import_file(second, (await export_json(client)).content)
    after = (await second.get(f"/api/conversations/{cid}")).json()["messages"][-1]["meta"]
    assert after == before and after["reasoning"] == "thinking" and after["usage"]["output_tokens"] == 7
    assert after["tools"][0]["display"] == {"expression": "1+1", "result": "2"}


# ---- what an import will not carry ----

async def test_attachments_are_left_out_with_a_note_and_compaction_is_dropped(client, second):
    cid = await new_conv(client)
    aid = (await upload(client, "cat.png", PNG)).json()["id"]
    await client.post(f"/api/conversations/{cid}/chat", json={"content": "look", "attachments": [aid]})
    data = json.loads((await export_json(client)).content)
    data["conversations"][0]["messages"][1]["meta"]["compaction"] = {"after_reply": True}
    await import_file(second, data)
    messages = (await second.get(f"/api/conversations/{cid}")).json()["messages"]
    assert messages[0]["content"] == "look\n\n[Attached when this was sent, not included in the import: cat.png]"
    assert "attachments" not in messages[0]["meta"] and "compaction" not in messages[1]["meta"]


async def test_an_attachment_only_message_becomes_just_the_note(second):
    data = {"conversations": [{"title": "t", "messages": [
        {"role": "user", "content": "", "meta": {"attachments": [{"name": "a.pdf"}, {"name": "b.png"}]}}]}]}
    await import_file(second, data)
    [chat] = (await second.get("/api/conversations")).json()
    [message] = (await second.get(f"/api/conversations/{chat['id']}")).json()["messages"]
    assert message["content"] == "[Attached when this was sent, not included in the import: a.pdf, b.png]"


async def test_unknown_metadata_and_bad_shapes_are_dropped_not_stored(second):
    meta = {"reasoning": 5, "usage": {"input_tokens": "many", "output_tokens": 3, "evil": 1}, "stopped": "yes",
            "incomplete": 7, "trimmed": -2, "secret": "x", "tools": [
                {"id": "ok", "name": "calculator", "status": "done", "arguments": [1], "display": "x", "error": 5},
                {"id": "run", "name": "calculator", "status": "running"},  # never saved, so refused
                {"id": 3, "name": "x", "status": "done"}, "not a dict", {"name": "no id", "status": "done"}]}
    await import_file(second, {"conversations": [{"title": "t", "messages": [
        {"role": "assistant", "content": "x", "meta": meta}]}]})
    [chat] = (await second.get("/api/conversations")).json()
    stored = (await second.get(f"/api/conversations/{chat['id']}")).json()["messages"][0]["meta"]
    assert stored == {"usage": {"output_tokens": 3}, "tools": [{"id": "ok", "name": "calculator", "status": "done"}]}


async def test_more_than_fifty_tool_calls_are_cut(second):
    calls = [{"id": f"c{i}", "name": "calculator", "status": "done"} for i in range(80)]
    await import_file(second, {"conversations": [{"title": "t", "messages": [
        {"role": "assistant", "content": "x", "meta": {"tools": calls}}]}]})
    [chat] = (await second.get("/api/conversations")).json()
    assert len((await second.get(f"/api/conversations/{chat['id']}")).json()["messages"][0]["meta"]["tools"]) == 50


# ---- settings, titles, ids, timestamps ----

async def test_tools_this_version_does_not_have_are_dropped_and_bad_settings_give_defaults(second):
    data = {"conversations": [
        {"id": "a" * 32, "title": "one", "settings": {"tools": ["calculator", "rm_rf"], "system_prompt": "S"},
         "messages": []},
        {"id": "b" * 32, "title": "two", "settings": {"temperature": 99, "bogus": 1}, "messages": []},
        {"id": "c" * 32, "title": "three", "settings": {"tools": "nope"}, "messages": []},
    ]}
    assert (await import_file(second, data)).json()["imported"] == 3
    got = {}
    for c in "abc":
        got[c] = (await second.get(f"/api/conversations/{c * 32}")).json()["settings"]
    one, two, three = got["a"], got["b"], got["c"]
    assert one["tools"] == ["calculator"] and one["system_prompt"] == "S"
    assert two == store.DEFAULT_SETTINGS and three == store.DEFAULT_SETTINGS


@pytest.mark.parametrize("given, expected", [("  Padded  ", "Padded"), ("", "Imported chat"), ("   ", "Imported chat"),
                                             ("x" * 300, "x" * 200)])
async def test_titles_are_trimmed_cut_and_never_empty(second, given, expected):
    await import_file(second, {"conversations": [{"title": given, "messages": []}]})
    assert (await second.get("/api/conversations")).json()[0]["title"] == expected


@pytest.mark.parametrize("cid", [None, "", "short", "../../etc/passwd", "G" * 32, "a" * 31, 12345])
async def test_an_id_that_is_not_one_of_ours_gets_a_new_one(second, cid):
    data = {"conversations": [{"id": cid, "title": "t", "messages": []}]}
    if isinstance(cid, int):
        data["conversations"][0]["id"] = None
    await import_file(second, data)
    [chat] = (await second.get("/api/conversations")).json()
    assert chat["id"] != cid and len(chat["id"]) == 32 and set(chat["id"]) <= set("0123456789abcdef")


async def test_a_file_without_ids_imports_again_as_new_chats(second):
    data = {"conversations": [{"title": "no id", "messages": [{"role": "user", "content": "x"}]}]}
    await import_file(second, data)
    await import_file(second, data)  # nothing says it is the same chat, so it is another one
    assert len((await second.get("/api/conversations")).json()) == 2


async def test_timestamps_are_kept_normalized_and_defaulted(second):
    data = {"conversations": [{"title": "t", "created_at": "2024-03-01T10:00:00+05:00",
                               "updated_at": "not a date", "messages": [
                                   {"role": "user", "content": "a", "created_at": "2024-03-01T05:00:01"},
                                   {"role": "assistant", "content": "b"}]}]}
    await import_file(second, data)
    [chat] = (await second.get("/api/conversations")).json()
    assert chat["created_at"] == "2024-03-01T05:00:00+00:00" and chat["updated_at"] == chat["created_at"]
    messages = (await second.get(f"/api/conversations/{chat['id']}")).json()["messages"]
    assert [m["created_at"] for m in messages] == ["2024-03-01T05:00:01+00:00", "2024-03-01T05:00:00+00:00"]


async def test_the_order_of_messages_is_kept(second):
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(30)]
    await import_file(second, {"conversations": [{"title": "t", "messages": messages}]})
    [chat] = (await second.get("/api/conversations")).json()
    got = (await second.get(f"/api/conversations/{chat['id']}")).json()["messages"]
    assert [m["content"] for m in got] == [f"m{i}" for i in range(30)]


# ---- files that are not exports ----

@pytest.mark.parametrize("data, why", [
    (b"not json at all", "isn't JSON"),
    (b"\xff\xfe\x00 binary", "isn't JSON"),
    (b"", "isn't JSON"),
    (b"[[[[" * 20_000, "isn't JSON"),
    (b'"just a string"', "doesn't look like"),
    (b"42", "doesn't look like"),
    (b"null", "doesn't look like"),
    (b'{"conversations": "nope"}', "conversations"),
    (b'{"conversations": [{"title": "t"}]}', "messages"),
    (b'{"conversations": [{"title": "t", "messages": [{"role": "system", "content": "x"}]}]}', "role"),
    (b'{"conversations": [{"title": "t", "messages": [{"role": "user"}]}]}', "content"),
    (b'{"conversations": [{"title": "t", "messages": [{"role": "user", "content": 5}]}]}', "content"),
    (b'{"conversations": [{"title": "t", "messages": "x"}]}', "messages"),
])
async def test_a_file_that_is_not_an_export_is_refused_with_a_reason_and_nothing_is_added(second, data, why):
    r = await import_file(second, data)
    assert r.status_code == 422 and why in r.json()["detail"]
    assert (await second.get("/api/conversations")).json() == []


async def test_one_bad_conversation_refuses_the_whole_file(second):
    good = {"id": "a" * 32, "title": "good", "messages": [{"role": "user", "content": "x"}]}
    bad = {"title": "bad", "messages": [{"role": "robot", "content": "x"}]}
    r = await import_file(second, {"conversations": [good, bad, good]})
    assert r.status_code == 422 and "conversations.1.messages.0.role" in r.json()["detail"]
    assert (await second.get("/api/conversations")).json() == []  # not even the good ones


async def test_a_failure_while_writing_leaves_nothing_behind(second, monkeypatch):
    app = second._transport.app
    calls = []
    real = store.json.dumps

    def failing(obj, *a, **k):
        calls.append(1)
        if len(calls) > 3:
            raise RuntimeError("disk on fire")
        return real(obj, *a, **k)

    monkeypatch.setattr(store.json, "dumps", failing)
    one = [{"role": "user", "content": "x"}]
    data = {"conversations": [{"id": c * 32, "title": c, "messages": one} for c in "abc"]}
    with pytest.raises(RuntimeError):
        await import_file(second, data)
    monkeypatch.undo()
    assert (await second.get("/api/conversations")).json() == []
    assert app.state.settings.db_path


async def test_limits_on_the_number_of_chats_and_messages(second):
    too_many = {"conversations": [{"title": str(i), "messages": []} for i in range(MAX_CHATS + 1)]}
    assert (await import_file(second, too_many)).status_code == 422
    huge = "x" * 1_000_001
    r = await import_file(second, {"conversations": [{"title": "t", "messages": [{"role": "user", "content": huge}]}]})
    assert r.status_code == 422 and "content" in r.json()["detail"]


async def test_a_file_over_the_size_limit_is_refused_before_it_is_parsed(second, monkeypatch):
    monkeypatch.setattr("app.backup.MAX_IMPORT_BYTES", 1000)
    r = await import_file(second, b"x" * 1500)
    assert r.status_code == 413 and "too large" in r.json()["detail"]


async def test_the_upload_must_be_a_file(second):
    assert (await second.post("/api/import")).status_code == 422
    assert (await second.post("/api/import", json={"conversations": []})).status_code == 422


async def test_a_list_of_chats_without_the_wrapper_is_accepted(second):
    r = await import_file(second, [{"title": "bare", "messages": []}])
    assert r.status_code == 201 and r.json()["imported"] == 1


async def test_hostile_text_is_stored_as_text_only(second):
    evil = "<script>window.__xss=1</script><img src=x onerror=alert(1)>"
    reply = {"role": "assistant", "content": evil}
    await import_file(second, {"conversations": [{"title": evil, "messages": [reply]}]})
    [chat] = (await second.get("/api/conversations")).json()
    assert chat["title"] == evil  # stored as it is; the page sets titles as text and sanitizes replies


async def test_migrations_are_current_after_an_import(second):
    app = second._transport.app
    assert db.connect(app.state.settings.db_path).execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


# ---- versions of a message (branching) ----

async def branched_chat(client, llm):
    """q1/a1, q2/a2, then q2 edited to 'q2 b' with the reply 'a2 b', so the path shown is q1 a1 'q2 b' 'a2 b'."""
    cid = await make_chat(client, llm, "Branched", "q1")
    llm.events = [{"type": "delta", "text": "a2"}, {"type": "done"}]
    await say(client, cid, "q2")
    q2 = (await client.get(f"/api/conversations/{cid}")).json()["messages"][2]
    llm.events = [{"type": "delta", "text": "a2 b"}, {"type": "done"}]
    await client.post(f"/api/conversations/{cid}/edit", json={"content": "q2 b", "message_id": q2["id"]})
    return cid


async def test_the_export_has_every_version_with_parents_and_the_leaf(client, llm):
    await branched_chat(client, llm)
    chat = (await export_json(client)).json()["conversations"][0]
    assert [m["content"] for m in chat["messages"]] == ["q1", "Noted.", "q2", "a2", "q2 b", "a2 b"]
    assert [m["parent"] for m in chat["messages"]] == [None, 0, 1, 2, 1, 4]
    assert chat["leaf"] == 5 and "leaf_id" not in chat and all("id" not in m for m in chat["messages"])


async def test_importing_an_export_with_versions_gives_the_same_tree_and_path(client, llm, second):
    cid = await branched_chat(client, llm)
    document = (await export_json(client)).json()
    r = await import_file(second, document)
    assert r.json() == {"imported": 1, "skipped": 0, "messages": 6} | NO_EXTRAS
    there = (await second.get(f"/api/conversations/{cid}")).json()["messages"]
    assert [m["content"] for m in there] == ["q1", "Noted.", "q2 b", "a2 b"]
    assert len(there[2]["siblings"]) == 2  # the other version came along
    old = (await second.get(f"/api/conversations/{cid}")).json()["messages"][2]["siblings"][0]
    shown = await second.post(f"/api/conversations/{cid}/branch", json={"message_id": old})
    assert [m["content"] for m in shown.json()["messages"]] == ["q1", "Noted.", "q2", "a2"]
    again = (await export_json(second)).json()["conversations"][0]
    assert [m["parent"] for m in again["messages"]] == [None, 0, 1, 2, 1, 4]  # and it exports the same


async def test_a_version_1_file_imports_as_a_straight_path(second):
    old = {"format": "chitchat-backup", "version": 1, "conversations": [{
        "id": "a" * 32, "title": "Old", "messages": [
            {"role": "user", "content": "q"}, {"role": "assistant", "content": "a"},
            {"role": "user", "content": "q2"}]}]}
    assert (await import_file(second, old)).json()["imported"] == 1
    messages = (await second.get(f"/api/conversations/{'a' * 32}")).json()["messages"]
    assert [m["content"] for m in messages] == ["q", "a", "q2"] and [len(m["siblings"]) for m in messages] == [1, 1, 1]


@pytest.mark.parametrize("parents, leaf, why", [
    ([None, 1], 1, "follows itself"),
    ([None, 2, 0], 2, "follows a later one"),
    ([None, -1], 1, "negative"),
    ([None, "0"], 1, "not a number"),
    ([None, 0], 5, "the leaf is not there"),
])
async def test_a_file_whose_versions_do_not_make_a_tree_is_refused_and_nothing_is_added(second, parents, leaf, why):
    messages = [{"role": "user", "content": f"m{i}", "parent": p} for i, p in enumerate(parents)]
    document = {"conversations": [{"id": "b" * 32, "title": "Bad", "leaf": leaf, "messages": messages}]}
    r = await import_file(second, document)
    assert r.status_code == 422, why
    assert (await second.get("/api/conversations")).json() == []


async def test_the_markdown_zip_has_the_path_shown_only(client, llm):
    await branched_chat(client, llm)
    archive = zipfile.ZipFile(io.BytesIO((await client.get("/api/export?format=md")).content))
    text = archive.read(archive.namelist()[0]).decode()
    assert "q2 b" in text and "a2 b" in text and "\nq2\n" not in text


async def test_a_leaf_of_null_means_the_last_message(second):
    document = {"conversations": [{"id": "c" * 32, "title": "T", "leaf": None, "messages": [
        {"role": "user", "content": "q", "parent": None}, {"role": "assistant", "content": "a", "parent": 0},
        {"role": "assistant", "content": "a2", "parent": 0}]}]}
    await import_file(second, document)
    messages = (await second.get(f"/api/conversations/{'c' * 32}")).json()["messages"]
    assert [m["content"] for m in messages] == ["q", "a2"]


# ---- a big import is indexed in one go ----

def big_document(chats, per_chat, word="zebrafish"):
    return {"conversations": [{"id": f"{i:032x}", "title": f"chat {i}", "messages": [
        {"role": "user" if j % 2 == 0 else "assistant", "content": f"{word} number {i} message {j}"}
        for j in range(per_chat)]} for i in range(chats)]}


def fts_count(conn_or_app, word):
    from contextlib import closing
    path = conn_or_app.state.settings.db_path
    with closing(db.connect(path)) as conn:
        return (conn.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH ?", (word,)).fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'messages_fts_insert'").fetchone()[0])


async def test_a_big_import_is_searchable_and_the_index_matches_the_messages_exactly(second):
    r = await import_file(second, big_document(30, 20))  # 600 messages: over the bulk threshold
    assert r.json()["messages"] == 600
    indexed, messages, trigger = fts_count(second.app, "zebrafish")
    assert (indexed, messages, trigger) == (600, 600, 1)  # none missing, none twice, trigger back in place
    found = (await second.get("/api/search", params={"q": "message 7"})).json()
    assert len(found) == 20  # one per chat, up to the search's limit


async def test_what_was_there_before_a_big_import_is_not_indexed_twice(second):
    second.app.state.llm.events = [{"type": "delta", "text": "zebrafish already here"}, {"type": "done"}]
    cid = await new_conv(second)
    await second.post(f"/api/conversations/{cid}/chat", json={"content": "zebrafish first"})
    assert fts_count(second.app, "zebrafish")[:2] == (2, 2)
    await import_file(second, big_document(30, 20))
    assert fts_count(second.app, "zebrafish")[:2] == (602, 602)  # each message once


async def test_messages_sent_after_a_big_import_are_indexed_too(second):
    await import_file(second, big_document(30, 20))
    cid = await new_conv(second)
    await second.post(f"/api/conversations/{cid}/chat", json={"content": "a unique word: quokkaboo"})
    assert fts_count(second.app, "quokkaboo")[0] == 1


async def test_a_big_import_that_fails_leaves_the_index_and_its_trigger_as_they_were(second):
    document = big_document(30, 20)
    document["conversations"][-1]["leaf"] = 99  # the last chat is refused, after all the others were inserted
    r = await import_file(second, document)
    assert r.status_code == 422
    assert fts_count(second.app, "zebrafish") == (0, 0, 1)  # nothing, and the trigger is still there


async def test_importing_a_big_file_again_adds_and_indexes_nothing(second):
    document = big_document(30, 20)
    await import_file(second, document)
    r = await import_file(second, document)
    assert r.json()["skipped"] == 30 and r.json()["messages"] == 0
    assert fts_count(second.app, "zebrafish") == (600, 600, 1)
