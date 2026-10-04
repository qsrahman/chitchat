"""The backup with files: a zip of the chats and their attachments, and importing it (app/backup.py)."""
import io
import json
import zipfile
from pathlib import Path

import pytest

from tests.helpers import PNG, make_pdf, new_conv, upload

NOTES = b"plain text notes"


def zip_of(document, files=None):
    """A backup zip: chats.json and the given {member name: bytes}."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("chats.json", json.dumps(document))
        for name, data in (files or {}).items():
            archive.writestr(name, data)
    return out.getvalue()


async def import_zip(client, data, name="backup.zip"):
    return await client.post("/api/import", files={"file": (name, data)})


async def send(client, cid, text, ids=()):
    r = await client.post(f"/api/conversations/{cid}/chat", json={"content": text, "attachments": list(ids)})
    assert r.status_code == 200


async def conversation(client, cid):
    return (await client.get(f"/api/conversations/{cid}")).json()


def on_disk(app):
    folder = Path(app.state.settings.attachments_dir)
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def chat_with(attachment, cid="a" * 32, name="Pic", kind="image", mime="image/png", extra=None):
    """A one-message chat document whose message lists one attachment (id `attachment`)."""
    entry = {"id": attachment, "name": name, "mime": mime, "kind": kind, "size": 1, **(extra or {})}
    message = {"role": "user", "content": "look", "meta": {"attachments": [entry]}}
    return {"id": cid, "title": "T", "messages": [message]}


@pytest.fixture
async def with_files(client, llm):
    """A chat with a picture and a text file on one message, then that message edited (a second version that
    shares the files), and a PDF on a later message."""
    pic = (await upload(client, "cat.png", PNG)).json()["id"]
    notes = (await upload(client, "notes.txt", NOTES)).json()["id"]
    pdf = (await upload(client, "doc.pdf", make_pdf("Hello PDF world"))).json()["id"]
    cid = await new_conv(client)
    await send(client, cid, "look at these", [pic, notes])
    await client.post(f"/api/conversations/{cid}/edit", json={"content": "look at these, please"})
    await send(client, cid, "and this", [pdf])
    return cid, {"pic": pic, "notes": notes, "pdf": pdf}


# ---- export ----

async def test_the_full_export_is_a_zip_with_the_chats_and_every_file(client, app, with_files):
    cid, ids = with_files
    r = await client.get("/api/export", params={"format": "full"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].endswith('-with-files.zip"')
    archive = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(archive.namelist()) == sorted(["chats.json", *(f"attachments/{i}" for i in ids.values())])
    assert archive.read(f"attachments/{ids['pic']}") == PNG and archive.read(f"attachments/{ids['notes']}") == NOTES
    document = json.loads(archive.read("chats.json"))
    assert document["conversations"][0]["id"] == cid and "custom_instructions" in document


async def test_a_file_gone_from_disk_is_left_out_of_the_zip_not_an_error(client, app, with_files):
    _, ids = with_files
    (Path(app.state.settings.attachments_dir) / ids["pic"]).unlink()
    names = zipfile.ZipFile(io.BytesIO((await client.get("/api/export?format=full")).content)).namelist()
    assert f"attachments/{ids['pic']}" not in names and f"attachments/{ids['notes']}" in names


async def test_the_json_export_alone_still_has_no_files(client, with_files):
    r = await client.get("/api/export")
    assert r.content.lstrip().startswith(b"{")  # not a zip


# ---- import: the round trip ----

async def test_the_files_come_back_with_their_chats(client, second, llm, with_files):
    cid, _ = with_files
    archive = (await client.get("/api/export?format=full")).content
    r = await import_zip(second, archive)
    assert r.status_code == 201
    assert r.json() == {"imported": 1, "skipped": 0, "messages": 6, "attachments": 3, "custom_instructions": False,
                        "defaults": False}
    versions = {m["id"]: m for m in (await conversation(second, cid))["messages"]}
    first_message = next(iter(versions.values()))
    assert first_message["content"] == "look at these, please"  # the path that was showing
    files = first_message["meta"]["attachments"]
    assert [(f["name"], f["kind"], f["mime"]) for f in files] == [
        ("cat.png", "image", "image/png"), ("notes.txt", "text", "text/plain")]
    assert (await second.get(f"/api/attachments/{files[0]['id']}")).content == PNG
    assert (await second.get(f"/api/attachments/{files[1]['id']}")).content == NOTES


async def test_the_versions_of_a_message_share_the_one_restored_file(client, second, with_files):
    cid, _ = with_files
    await import_zip(second, (await client.get("/api/export?format=full")).content)
    mine = (await conversation(second, cid))["messages"][0]
    other = mine["siblings"][0]  # the version before the edit
    await second.post(f"/api/conversations/{cid}/branch", json={"message_id": other})
    old = (await conversation(second, cid))["messages"][0]
    assert old["content"] == "look at these"
    assert [a["id"] for a in old["meta"]["attachments"]] == [a["id"] for a in mine["meta"]["attachments"]]


async def test_restored_files_get_new_ids_and_are_what_the_model_is_sent(client, second, app, with_files):
    cid, ids = with_files
    await import_zip(second, (await client.get("/api/export?format=full")).content)
    llm = second.app.state.llm
    got = (await conversation(second, cid))["messages"]
    new_ids = {a["id"] for m in got for a in m["meta"].get("attachments", [])}
    assert new_ids and not new_ids & set(ids.values())  # never the old ids
    assert on_disk(second.app) == sorted(new_ids)  # exactly the files that came back
    await second.post(f"/api/conversations/{cid}/chat", json={"content": "what was in the pdf?"})
    sent = llm.calls[-1]["messages"]
    assert any("Hello PDF world" in a["text"] for m in sent for a in m.get("attachments", []) if a["kind"] == "text")


async def test_importing_the_same_zip_again_adds_no_files(client, second, with_files):
    archive = (await client.get("/api/export?format=full")).content
    await import_zip(second, archive)
    before = on_disk(second.app)
    r = await import_zip(second, archive)
    assert r.json()["skipped"] == 1 and r.json()["attachments"] == 0
    assert on_disk(second.app) == before  # nothing written for a chat that was skipped


async def test_deleting_an_imported_chat_removes_its_files(client, second, with_files):
    cid, _ = with_files
    await import_zip(second, (await client.get("/api/export?format=full")).content)
    assert on_disk(second.app)
    assert (await second.delete(f"/api/conversations/{cid}")).status_code == 204
    assert on_disk(second.app) == []


# ---- import: what is not believed ----

async def test_what_the_zip_says_about_a_file_is_ignored_the_bytes_decide(second):
    aid = "1" * 32
    document = {"conversations": [chat_with(aid, name="../../etc/passwd", kind="image", mime="image/png",
                                            extra={"size": 999999})]}
    r = await import_zip(second, zip_of(document, {f"attachments/{aid}": NOTES}))  # said to be an image: it is text
    assert r.json()["attachments"] == 1
    file = (await conversation(second, "a" * 32))["messages"][0]["meta"]["attachments"][0]
    assert (file["kind"], file["mime"], file["size"], file["name"]) == ("text", "text/plain", len(NOTES), "passwd")


@pytest.mark.parametrize("data, why", [
    (b"MZ\x00\x00 an executable", "an unsupported type"),
    (b"", "an empty file"),
    (PNG + b"\x00" * (11 * 1024 * 1024), "an image over its limit"),
])
async def test_a_file_that_is_not_acceptable_is_left_behind_with_a_note(second, data, why):
    aid = "2" * 32
    document = {"conversations": [chat_with(aid, name="bad.bin")]}
    r = await import_zip(second, zip_of(document, {f"attachments/{aid}": data}))
    assert r.status_code == 201 and r.json()["attachments"] == 0, why
    message = (await conversation(second, "a" * 32))["messages"][0]
    assert "attachments" not in message["meta"]
    assert "not included in the import: bad.bin" in message["content"]
    assert on_disk(second.app) == []


async def test_a_file_over_every_limit_is_refused_though_its_zip_is_tiny(second):
    aid = "3" * 32
    big = b"\x00" * (21 * 1024 * 1024)  # compresses to almost nothing, as a zip bomb would
    r = await import_zip(second, zip_of({"conversations": [chat_with(aid)]}, {f"attachments/{aid}": big}))
    assert r.status_code == 201 and r.json()["attachments"] == 0


async def test_only_files_named_by_a_message_in_the_zip_are_used(second):
    aid = "4" * 32
    extras = {"attachments/../escape.txt": b"nope", "attachments/" + "5" * 32: NOTES, "other/" + aid: NOTES}
    r = await import_zip(second, zip_of({"conversations": [chat_with(aid)]}, extras))
    assert r.json()["attachments"] == 0  # none of them is the file the message names
    folder = Path(second.app.state.settings.attachments_dir)
    assert on_disk(second.app) == [] and not (folder.parent / "escape.txt").exists()


@pytest.mark.parametrize("ref", [None, 5, ["x"], "../x", "not-hex"])
async def test_a_message_that_names_its_file_oddly_is_noted_not_a_crash(second, ref):
    document = {"conversations": [chat_with("x")]}
    document["conversations"][0]["messages"][0]["meta"]["attachments"][0]["id"] = ref
    r = await import_zip(second, zip_of(document))
    assert r.status_code == 201 and r.json()["attachments"] == 0


# ---- import: all or nothing ----

async def test_a_bad_chat_after_a_good_one_leaves_no_files_behind(second):
    aid = "6" * 32
    bad = {"id": "b" * 32, "title": "Bad", "leaf": 0, "messages": [{"role": "user", "content": "x", "parent": 3}]}
    r = await import_zip(second, zip_of({"conversations": [chat_with(aid), bad]}, {f"attachments/{aid}": PNG}))
    assert r.status_code == 422
    assert (await second.get("/api/conversations")).json() == [] and on_disk(second.app) == []


async def test_a_zip_over_the_size_limit_is_refused(second, monkeypatch):
    """Measured from what was really uploaded: what the client said the size was is not to be trusted (and the
    parser doesn't always fill it in at all)."""
    data = zip_of({"conversations": [{"title": "t", "messages": []}]})
    monkeypatch.setattr("app.backup.MAX_ARCHIVE_BYTES", len(data) - 1)
    assert (await import_zip(second, data)).status_code == 413
    monkeypatch.setattr("app.backup.MAX_ARCHIVE_BYTES", len(data))
    assert (await import_zip(second, data)).status_code == 201  # and exactly at the limit it is not


async def test_a_zip_that_is_not_a_backup_is_refused_in_words(second):
    assert (await import_zip(second, b"PK\x03\x04 not really a zip")).status_code == 422
    markdown = zip_of({}, {}).replace(b"chats.json", b"chats.jsno")  # a zip with another name inside
    r = await import_zip(second, markdown)
    assert r.status_code == 422 and "no chats.json" in r.json()["detail"]
    notes = io.BytesIO()
    with zipfile.ZipFile(notes, "w") as archive:
        archive.writestr("2026-01-01-title-abc.md", "# hello")
    r = await import_zip(second, notes.getvalue())
    assert r.status_code == 422 and "Markdown export" in r.json()["detail"]


# ---- custom instructions ----

async def test_the_custom_instructions_travel_with_the_backup(client, second):
    await client.put("/api/custom-instructions", json={"text": "Answer in French."})
    document = (await client.get("/api/export")).json()
    assert document["custom_instructions"] == "Answer in French."
    r = await second.post("/api/import", files={"file": ("b.json", json.dumps(document).encode())})
    assert r.json()["custom_instructions"] is True
    assert (await second.get("/api/custom-instructions")).json()["text"] == "Answer in French."


async def test_existing_instructions_are_never_overwritten_and_odd_ones_are_ignored(client, second):
    await second.put("/api/custom-instructions", json={"text": "Mine."})
    document = {"custom_instructions": "Theirs.", "conversations": []}
    r = await second.post("/api/import", files={"file": ("b.json", json.dumps(document).encode())})
    assert r.json()["custom_instructions"] is False
    assert (await second.get("/api/custom-instructions")).json()["text"] == "Mine."
    for odd in (["x"], 5, "x" * 10_001, "   "):
        r = await client.post("/api/import", files={"file": ("b.json", json.dumps(
            {"custom_instructions": odd, "conversations": []}).encode())})
        assert r.status_code == 201 and r.json()["custom_instructions"] is False


# ---- the defaults for new chats ----

async def test_the_defaults_for_new_chats_travel_with_the_backup(client, second):
    chosen = {"model": "gpt-5-mini", "reasoning_effort": "low", "tools": ["calculator"]}
    await client.put("/api/defaults", json=chosen)
    document = (await client.get("/api/export")).json()
    assert document["defaults"] == chosen
    r = await second.post("/api/import", files={"file": ("b.json", json.dumps(document).encode())})
    assert r.json()["defaults"] is True
    assert (await second.get("/api/defaults")).json() == chosen


async def test_existing_defaults_are_never_overwritten_and_odd_ones_are_ignored(client, second):
    await second.put("/api/defaults", json={"model": "mine"})
    theirs = {"model": "theirs", "reasoning_effort": None, "tools": []}
    r = await second.post("/api/import", files={"file": ("b.json", json.dumps(
        {"defaults": theirs, "conversations": []}).encode())})
    assert r.json()["defaults"] is False
    assert (await second.get("/api/defaults")).json()["model"] == "mine"
    odd_ones = ("x", 5, ["x"], {"model": 5}, {"reasoning_effort": "extreme"}, {"model": ""}, {},
                {"tools": "calculator"}, {"tools": ["no such tool"]})
    for odd in odd_ones:
        r = await client.post("/api/import", files={"file": ("b.json", json.dumps(
            {"defaults": odd, "conversations": []}).encode())})
        assert r.status_code == 201 and r.json()["defaults"] is False
    assert (await client.get("/api/defaults")).json() == {"model": None, "reasoning_effort": None, "tools": []}


async def test_tools_this_version_does_not_have_are_dropped_from_imported_defaults(client):
    document = {"defaults": {"model": "m", "tools": ["calculator", "retired_tool"]}, "conversations": []}
    r = await client.post("/api/import", files={"file": ("b.json", json.dumps(document).encode())})
    assert r.json()["defaults"] is True
    saved = (await client.get("/api/defaults")).json()
    assert saved == {"model": "m", "reasoning_effort": None, "tools": ["calculator"]}
