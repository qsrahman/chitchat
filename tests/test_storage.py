"""Settings, Data controls, Storage: what is kept, files nothing uses, and old archived chats."""
import os
from contextlib import closing
from pathlib import Path

from app import db
from tests.helpers import PNG, make_pdf, new_conv, upload

LONG_AGO = "2000-01-01T00:00:00+00:00"


def age(app, sql, *args):
    with closing(db.connect(app.state.settings.db_path)) as conn:
        conn.execute(sql, args)
        conn.commit()


def make_old(file: Path):
    os.utime(file, (0, 0))


async def say(client, cid, text="hi", ids=()):
    await client.post(f"/api/conversations/{cid}/chat", json={"content": text, "attachments": list(ids)})


async def archived_chat(client, app, text="old", ids=(), updated=LONG_AGO):
    cid = await new_conv(client)
    await say(client, cid, text, ids)
    await client.patch(f"/api/conversations/{cid}", json={"archived": True})
    age(app, "UPDATE conversations SET updated_at = ? WHERE id = ?", updated, cid)
    return cid


async def test_an_empty_app_has_nothing_to_report(client):
    got = (await client.get("/api/storage")).json()
    assert got["attachment_files"] == got["unused_files"] == got["chats"] == got["archived_chats"] == 0
    assert got["database_bytes"] > 0  # the file exists even when empty


async def test_the_overview_counts_chats_files_and_sizes(client, app):
    pic = (await upload(client, "a.png", PNG)).json()["id"]
    cid = await new_conv(client)
    await say(client, cid, "look", [pic])
    await archived_chat(client, app)
    got = (await client.get("/api/storage")).json()
    assert (got["chats"], got["archived_chats"]) == (2, 1)
    assert (got["attachment_files"], got["attachment_bytes"]) == (1, len(PNG))
    assert got["unused_files"] == 0


async def test_unused_files_are_unsent_uploads_and_files_no_row_names_but_only_once_they_are_old(client, app):
    folder = Path(app.state.settings.attachments_dir)
    fresh = (await upload(client, "fresh.txt", b"just uploaded")).json()["id"]  # being attached, perhaps
    old = (await upload(client, "old.txt", b"never sent")).json()["id"]
    age(app, "UPDATE attachments SET created_at = ? WHERE id = ?", LONG_AGO, old)
    stray = folder / ("f" * 32)
    stray.write_bytes(b"x" * 10)
    fresh_stray = folder / ("e" * 32)
    fresh_stray.write_bytes(b"y")
    make_old(stray)
    got = (await client.get("/api/storage")).json()
    assert (got["unused_files"], got["unused_bytes"]) == (2, len(b"never sent") + 10)

    cleared = (await client.post("/api/storage/clear-unused")).json()
    assert cleared == {"files": 2, "bytes": len(b"never sent") + 10}
    assert not (folder / old).exists() and not stray.exists()
    assert (folder / fresh).exists() and fresh_stray.exists()  # too new to be sure they are not wanted
    assert (await client.get(f"/api/attachments/{old}")).status_code == 404
    assert (await client.get(f"/api/attachments/{fresh}")).status_code == 200
    assert (await client.post("/api/storage/clear-unused")).json() == {"files": 0, "bytes": 0}


async def test_clearing_unused_files_never_touches_a_file_that_was_sent(client, app):
    folder = Path(app.state.settings.attachments_dir)
    sent = (await upload(client, "doc.pdf", make_pdf("Hello PDF world"))).json()["id"]
    cid = await new_conv(client)
    await say(client, cid, "read", [sent])
    for file in folder.iterdir():
        make_old(file)  # the file and the PDF's text next to it, both old and both in use
    age(app, "UPDATE attachments SET created_at = ?", LONG_AGO)
    assert (await client.post("/api/storage/clear-unused")).json() == {"files": 0, "bytes": 0}
    assert (folder / sent).exists() and (folder / f"{sent}.txt").exists()


async def test_archived_chats_are_counted_by_age_and_only_archived_ones(client, app):
    await archived_chat(client, app)  # long ago
    await archived_chat(client, app, updated="2999-01-01T00:00:00+00:00")  # newer than any cutoff
    live = await new_conv(client)
    await say(client, live)
    age(app, "UPDATE conversations SET updated_at = ? WHERE id = ?", LONG_AGO, live)  # old, but not archived
    assert (await client.get("/api/storage/archived", params={"days": 30})).json() == {"count": 1}


async def test_deleting_old_archived_chats_removes_them_their_files_and_nothing_else(client, app):
    folder = Path(app.state.settings.attachments_dir)
    pic = (await upload(client, "a.png", PNG)).json()["id"]
    gone = await archived_chat(client, app, "old", [pic])
    recent = await archived_chat(client, app, "recent", updated="2999-01-01T00:00:00+00:00")
    live = await new_conv(client)
    age(app, "UPDATE conversations SET updated_at = ? WHERE id = ?", LONG_AGO, live)
    r = (await client.delete("/api/storage/archived", params={"days": 30})).json()
    assert r == {"deleted": 1, "ids": [gone]}
    assert (await client.get(f"/api/conversations/{gone}")).status_code == 404
    assert not (folder / pic).exists()
    assert (await client.get(f"/api/conversations/{recent}")).status_code == 200
    assert (await client.get(f"/api/conversations/{live}")).status_code == 200
    assert (await client.delete("/api/storage/archived", params={"days": 30})).json() == {"deleted": 0, "ids": []}


async def test_the_search_index_forgets_a_deleted_chat(client, app):
    await archived_chat(client, app, "zebra crossing")
    assert (await client.get("/api/search", params={"q": "zebra"})).json()
    await client.delete("/api/storage/archived", params={"days": 1})
    assert (await client.get("/api/search", params={"q": "zebra"})).json() == []


async def test_the_database_file_gets_smaller_after_a_big_delete(client, app):
    cid = await new_conv(client)
    await say(client, cid, "x" * 90_000)
    await client.patch(f"/api/conversations/{cid}", json={"archived": True})
    age(app, "UPDATE conversations SET updated_at = ? WHERE id = ?", LONG_AGO, cid)
    with closing(db.connect(app.state.settings.db_path)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # the size is of the file, not of what waits in the log
    before = (await client.get("/api/storage")).json()["database_bytes"]
    await client.delete("/api/storage/archived", params={"days": 1})
    with closing(db.connect(app.state.settings.db_path)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert (await client.get("/api/storage")).json()["database_bytes"] < before


async def test_the_age_must_be_a_sensible_number_of_days(client):
    for days in (0, -1, 3651):
        assert (await client.get("/api/storage/archived", params={"days": days})).status_code == 422
        assert (await client.delete("/api/storage/archived", params={"days": days})).status_code == 422
    assert (await client.delete("/api/storage/archived")).status_code == 422
