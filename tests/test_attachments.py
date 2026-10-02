import asyncio
from datetime import timedelta
from pathlib import Path

import pytest

from app import attachments, db, store
from tests.helpers import GIF, JPEG, PNG, WEBP, make_pdf, new_conv, upload


async def chat(client, cid, text="look", ids=()):
    return await client.post(f"/api/conversations/{cid}/chat", json={"content": text, "attachments": list(ids)})


async def messages(client, cid):
    return (await client.get(f"/api/conversations/{cid}")).json()["messages"]


# ---- uploading ----

@pytest.mark.parametrize("name,data,kind,mime", [
    ("pic.png", PNG, "image", "image/png"),
    ("pic.jpg", JPEG, "image", "image/jpeg"),
    ("anim.gif", GIF, "image", "image/gif"),
    ("pic.webp", WEBP, "image", "image/webp"),
    ("doc.pdf", make_pdf("Hello PDF world"), "pdf", "application/pdf"),
    ("notes.md", b"# Notes\n\nplain text, with unicode: caf\xc3\xa9", "text", "text/plain"),
    ("page.html", b"<script>alert(1)</script>", "text", "text/plain"),  # HTML is just text here
    ("drawing.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "text", "text/plain"),  # and so is SVG
])
async def test_upload_detects_the_kind_from_the_bytes(client, name, data, kind, mime):
    r = await upload(client, name, data)
    assert r.status_code == 201
    got = r.json()
    assert (got["name"], got["kind"], got["mime"], got["size"]) == (name, kind, mime, len(data))


async def test_the_type_comes_from_the_content_not_the_name(client):
    assert (await upload(client, "innocent.txt", PNG)).json()["kind"] == "image"
    assert (await upload(client, "photo.png", b"just words")).json()["kind"] == "text"


@pytest.mark.parametrize("data", [
    b"PK\x03\x04" + b"\x00" * 300,  # zip
    b"\x7fELF" + b"\x00" * 300,  # executable
    b"\x00\x01\x02\xff\xfe" * 100,  # binary noise
    b"caf\xe9" * 100,  # not UTF-8
])
async def test_unsupported_files_are_rejected_with_a_message(client, data):
    r = await upload(client, "thing.bin", data)
    assert r.status_code == 415
    assert "Unsupported file type" in r.json()["detail"]


async def test_empty_file_is_rejected(client):
    assert (await upload(client, "empty.txt", b"")).status_code == 422


async def test_each_kind_has_its_own_size_limit(client, monkeypatch):
    monkeypatch.setattr(attachments, "LIMITS", {"image": 100, "pdf": 5000, "text": 50})
    assert (await upload(client, "ok.txt", b"x" * 50)).status_code == 201
    r = await upload(client, "big.txt", b"x" * 51)
    assert r.status_code == 413 and "Text files can be at most" in r.json()["detail"]
    assert (await upload(client, "ok.png", PNG)).status_code == 201
    assert (await upload(client, "big.png", PNG + b"\x00" * 100)).status_code == 413


async def test_pdf_without_text_is_rejected_in_text_mode(client):
    r = await upload(client, "scan.pdf", make_pdf(None))
    assert r.status_code == 422 and "no text" in r.json()["detail"]


async def test_broken_pdf_is_rejected_and_leaves_no_file(client, app):
    r = await upload(client, "broken.pdf", b"%PDF-1.4\nthis is not a pdf" + b"\x00" * 300)
    assert r.status_code == 422
    assert not list(Path(app.state.settings.attachments_dir).glob("*"))


async def test_pdf_without_text_is_fine_when_sent_as_a_file(client, app):
    app.state.settings.openai_pdf_input = "file"  # nothing to extract, so nothing can be missing
    assert (await upload(client, "scan.pdf", make_pdf(None))).status_code == 201


async def test_file_name_is_cleaned(client):
    got = (await upload(client, "../../etc/pass wd<b>.txt", b"hi")).json()
    assert got["name"] == "pass wd<b>.txt"  # no path; markup is left alone, the UI never renders it as HTML
    assert (await upload(client, "C:\\Users\\me\\report.txt", b"hi")).json()["name"] == "report.txt"


async def test_limits_endpoint(client):
    assert (await client.get("/api/attachments/limits")).json() == {"max_files": attachments.MAX_FILES}


# ---- serving ----

async def test_images_are_served_inline_with_their_detected_type(client):
    aid = (await upload(client, "pic.png", PNG)).json()["id"]
    r = await client.get(f"/api/attachments/{aid}")
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"].startswith("inline")


async def test_everything_else_downloads_as_a_sandboxed_attachment(client):
    aid = (await upload(client, "evil.html", b"<script>alert(1)</script>")).json()["id"]
    r = await client.get(f"/api/attachments/{aid}")
    assert r.headers["content-type"].startswith("text/plain")  # never text/html
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "sandbox"
    pdf = (await upload(client, "a.pdf", make_pdf("x"))).json()["id"]
    assert (await client.get(f"/api/attachments/{pdf}")).headers["content-disposition"].startswith("attachment")


async def test_unknown_attachment_is_404(client):
    assert (await client.get("/api/attachments/nope")).status_code == 404
    assert (await client.get("/api/attachments/..%2F..%2Fetc%2Fpasswd")).status_code == 404


# ---- sending ----

async def test_message_with_attachments_is_saved_with_them_and_the_model_gets_them(client, llm, app):
    img = (await upload(client, "pic.png", PNG)).json()
    txt = (await upload(client, "notes.txt", b"remember the milk")).json()
    cid = await new_conv(client)
    r = await chat(client, cid, "what are these?", [img["id"], txt["id"]])
    assert r.status_code == 200
    user = (await messages(client, cid))[0]
    assert user["content"] == "what are these?"
    assert [(a["id"], a["name"], a["kind"], a["mime"]) for a in user["meta"]["attachments"]] == [
        (img["id"], "pic.png", "image", "image/png"), (txt["id"], "notes.txt", "text", "text/plain"),
    ]
    sent = llm.calls[-1]["messages"][0]
    assert sent["content"] == "what are these?"
    assert [(a["kind"], a["name"]) for a in sent["attachments"]] == [("image", "pic.png"), ("text", "notes.txt")]
    assert sent["attachments"][1]["text"] == "remember the milk"
    assert open(sent["attachments"][0]["path"], "rb").read() == PNG


async def test_a_message_can_be_only_attachments_and_still_gets_a_title(client, llm):
    aid = (await upload(client, "diagram.png", PNG)).json()["id"]
    cid = await new_conv(client)
    seen = []
    original = llm.generate_title

    async def spy(model, user_text, reply_text):
        seen.append(user_text)
        return await original(model, user_text, reply_text)

    llm.generate_title = spy
    assert (await chat(client, cid, "", [aid])).status_code == 200
    assert (await messages(client, cid))[0]["content"] == ""
    assert seen == ["diagram.png"]


@pytest.mark.parametrize("body", [{}, {"content": "  "}, {"content": "", "attachments": []}])
async def test_nothing_to_send_is_rejected(client, body):
    cid = await new_conv(client)
    assert (await client.post(f"/api/conversations/{cid}/chat", json=body)).status_code == 422


async def test_unknown_reused_and_duplicate_attachments_are_rejected_before_anything_is_saved(client):
    aid = (await upload(client, "a.txt", b"hi")).json()["id"]
    cid = await new_conv(client)
    assert (await chat(client, cid, "x", ["ghost"])).status_code == 422
    assert (await chat(client, cid, "x", [aid, aid])).status_code == 422
    assert await messages(client, cid) == []
    assert (await chat(client, cid, "first", [aid])).status_code == 200
    assert (await chat(client, cid, "again", [aid])).status_code == 422  # already sent once
    assert len(await messages(client, cid)) == 2


async def test_at_most_max_files_per_message(client):
    ids = [(await upload(client, f"{i}.txt", b"hi")).json()["id"] for i in range(attachments.MAX_FILES + 1)]
    cid = await new_conv(client)
    assert (await chat(client, cid, "x", ids)).status_code == 422
    assert (await chat(client, cid, "x", ids[:-1])).status_code == 200


async def test_attachments_are_sent_again_on_every_turn_and_survive_regenerate_and_edit(client, llm):
    aid = (await upload(client, "notes.txt", b"context")).json()["id"]
    cid = await new_conv(client)
    await chat(client, cid, "first", [aid])
    await chat(client, cid, "second")
    assert [m.get("attachments") is not None for m in llm.calls[-1]["messages"]] == [True, False, False]
    await client.post(f"/api/conversations/{cid}/regenerate")
    assert llm.calls[-1]["messages"][0]["attachments"][0]["text"] == "context"
    await client.post(f"/api/conversations/{cid}/edit", json={"content": "second, reworded"})
    assert llm.calls[-1]["messages"][0]["attachments"][0]["text"] == "context"
    assert (await messages(client, cid))[0]["meta"]["attachments"][0]["id"] == aid


async def test_pdf_text_is_extracted_once_and_cached(client, llm, app):
    aid = (await upload(client, "doc.pdf", make_pdf("Hello PDF world"))).json()["id"]
    cid = await new_conv(client)
    await chat(client, cid, "summarize", [aid])
    sent = llm.calls[-1]["messages"][0]["attachments"][0]
    assert sent["kind"] == "text" and "Hello PDF world" in sent["text"]
    cache = attachments.path(app.state.settings.attachments_dir, aid).with_suffix(".txt")
    assert "Hello PDF world" in cache.read_text()


async def test_pdf_is_sent_as_a_file_when_configured(client, llm, app):
    app.state.settings.openai_pdf_input = "file"
    aid = (await upload(client, "doc.pdf", make_pdf("Hello"))).json()["id"]
    cid = await new_conv(client)
    await chat(client, cid, "read it", [aid])
    sent = llm.calls[-1]["messages"][0]["attachments"][0]
    assert (sent["kind"], sent["name"], sent["mime"]) == ("file", "doc.pdf", "application/pdf")
    assert open(sent["path"], "rb").read().startswith(b"%PDF")


async def test_a_missing_file_does_not_break_the_turn(client, llm, app):
    aid = (await upload(client, "notes.txt", b"here")).json()["id"]
    cid = await new_conv(client)
    await chat(client, cid, "first", [aid])
    attachments.path(app.state.settings.attachments_dir, aid).unlink()
    r = await chat(client, cid, "second")
    assert r.status_code == 200
    assert "no longer available" in llm.calls[-1]["messages"][0]["attachments"][0]["text"]


# ---- cleanup ----

async def test_deleting_a_conversation_removes_its_files(client, app):
    folder = Path(app.state.settings.attachments_dir)
    sent = (await upload(client, "doc.pdf", make_pdf("Hello PDF world"))).json()["id"]
    unsent = (await upload(client, "later.txt", b"not sent")).json()["id"]
    cid = await new_conv(client)
    await chat(client, cid, "read", [sent])
    assert (folder / sent).exists() and (folder / f"{sent}.txt").exists()
    assert (await client.delete(f"/api/conversations/{cid}")).status_code == 204
    assert not (folder / sent).exists() and not (folder / f"{sent}.txt").exists()
    assert (await client.get(f"/api/attachments/{sent}")).status_code == 404
    assert (folder / unsent).exists()  # an unsent upload isn't part of any conversation


def test_abandoned_uploads_are_purged_but_sent_and_recent_ones_stay(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.connect(path)
    cid = store.create_conversation(conn)["id"]
    for aid in ("old", "recent", "sent"):
        store.add_attachment(conn, aid, f"{aid}.txt", "text/plain", "text", 1)
    store.link_attachments(conn, cid, ["sent"])
    conn.execute("UPDATE attachments SET created_at = ? WHERE id IN ('old', 'sent')", ("2000-01-01T00:00:00+00:00",))
    conn.commit()
    assert store.purge_orphans(conn, timedelta(hours=24)) == ["old"]
    assert store.get_attachment(conn, "old") is None
    assert store.get_attachment(conn, "recent") and store.get_attachment(conn, "sent")
    conn.close()


def test_migration_to_v3_keeps_existing_data(tmp_path):
    path = str(tmp_path / "old.db")
    conn = db.connect(path)
    for script in db.MIGRATIONS[:2]:
        conn.executescript(script)
    conn.execute("PRAGMA user_version = 2")
    conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) VALUES ('c1', 'Old', 't', 't')")
    conn.commit()
    conn.close()
    db.init(path)
    conn = db.connect(path)
    assert store.get_conversation(conn, "c1")["title"] == "Old"
    assert store.add_attachment(conn, "a1", "x.txt", "text/plain", "text", 1)["conversation_id"] is None
    conn.close()


async def test_concurrent_uploads_get_distinct_ids(client):
    results = await asyncio.gather(*[upload(client, f"{i}.txt", b"hi") for i in range(5)])
    assert len({r.json()["id"] for r in results}) == 5
