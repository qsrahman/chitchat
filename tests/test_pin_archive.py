"""Pinned and archived chats (store.py, routes.py, backup.py)."""
import pytest

from tests.helpers import new_conv


async def titled(client, title):
    cid = await new_conv(client)
    await client.patch(f"/api/conversations/{cid}", json={"title": title})
    return cid


async def titles(client, **params):
    return [c["title"] for c in (await client.get("/api/conversations", params=params)).json()]


async def test_a_pinned_chat_goes_to_the_top_and_stays_there(client):
    old = await titled(client, "old")
    await titled(client, "middle")
    await titled(client, "new")
    r = await client.patch(f"/api/conversations/{old}", json={"pinned": True})
    assert r.status_code == 200 and r.json()["pinned"] == 1
    assert await titles(client) == ["old", "new", "middle"]
    await client.patch(f"/api/conversations/{old}", json={"pinned": False})
    assert await titles(client) == ["new", "middle", "old"]


async def test_an_archived_chat_leaves_the_list_and_shows_in_the_archive(client):
    keep = await titled(client, "keep")
    gone = await titled(client, "gone")
    await client.patch(f"/api/conversations/{gone}", json={"archived": True})
    assert await titles(client) == ["keep"]
    assert await titles(client, archived="true") == ["gone"]
    await client.patch(f"/api/conversations/{gone}", json={"archived": False})
    assert await titles(client) == ["gone", "keep"] and keep


async def test_an_archived_chat_can_still_be_opened_and_talked_in(client, llm):
    cid = await titled(client, "quiet")
    await client.patch(f"/api/conversations/{cid}", json={"archived": True})
    assert (await client.get(f"/api/conversations/{cid}")).status_code == 200
    assert (await client.post(f"/api/conversations/{cid}/chat", json={"content": "hi"})).status_code == 200
    assert await titles(client) == []  # talking in it does not bring it back to the list


async def test_pinning_and_archiving_can_change_with_a_title_in_one_request_and_nothing_else_is_touched(client):
    cid = await titled(client, "t")
    r = await client.patch(f"/api/conversations/{cid}", json={"title": "u", "pinned": True, "archived": True})
    assert (r.json()["title"], r.json()["pinned"], r.json()["archived"]) == ("u", 1, 1)
    r = await client.patch(f"/api/conversations/{cid}", json={"pinned": False})
    assert (r.json()["title"], r.json()["pinned"], r.json()["archived"]) == ("u", 0, 1)  # archived is left alone


@pytest.mark.parametrize("body", [{}, {"pinned": "maybe"}, {"archived": 5}, {"pinned": None, "archived": None}])
async def test_a_bad_change_is_refused(client, body):
    cid = await titled(client, "t")
    assert (await client.patch(f"/api/conversations/{cid}", json=body)).status_code == 422


async def test_pinning_an_unknown_chat_is_a_404(client):
    assert (await client.patch("/api/conversations/nope", json={"pinned": True})).status_code == 404


async def test_the_pages_of_the_list_respect_the_order_and_the_archive(client):
    ids = [await titled(client, f"c{i}") for i in range(6)]
    await client.patch(f"/api/conversations/{ids[0]}", json={"pinned": True})
    await client.patch(f"/api/conversations/{ids[5]}", json={"archived": True})
    first = await titles(client, limit=2)
    rest = await titles(client, limit=2, offset=2)
    last = await titles(client, limit=2, offset=4)
    assert first + rest + last == ["c0", "c4", "c3", "c2", "c1"]  # c5 is archived


async def test_search_finds_an_archived_chat(client):
    cid = await titled(client, "quokka facts")
    await client.patch(f"/api/conversations/{cid}", json={"archived": True})
    found = (await client.get("/api/search", params={"q": "quokka"})).json()
    assert [r["id"] for r in found] == [cid]


async def test_the_backup_keeps_pinned_and_archived_and_brings_them_back(client, second):
    a = await titled(client, "pinned one")
    b = await titled(client, "archived one")
    await titled(client, "plain one")
    await client.patch(f"/api/conversations/{a}", json={"pinned": True})
    await client.patch(f"/api/conversations/{b}", json={"archived": True})
    document = (await client.get("/api/export")).json()
    flags = {c["title"]: (c["pinned"], c["archived"]) for c in document["conversations"]}
    assert flags == {"pinned one": (True, False), "archived one": (False, True), "plain one": (False, False)}
    import json
    r = await second.post("/api/import", files={"file": ("b.json", json.dumps(document).encode())})
    assert r.json()["imported"] == 3
    assert [c["title"] for c in (await second.get("/api/conversations")).json()] == ["pinned one", "plain one"]
    assert [c["title"] for c in (await second.get("/api/conversations?archived=true")).json()] == ["archived one"]


async def test_the_one_chat_export_with_its_flags_still_imports(client, second):
    import json
    cid = await titled(client, "pinned")
    await client.patch(f"/api/conversations/{cid}", json={"pinned": True})
    one = (await client.get(f"/api/conversations/{cid}/export?format=json")).content  # pinned is 1 in it, not true
    assert (await second.post("/api/import", files={"file": ("b.json", one)})).status_code == 201
    assert json.loads(one)["pinned"] == 1
    assert [c["title"] for c in (await second.get("/api/conversations")).json()] == ["pinned"]
