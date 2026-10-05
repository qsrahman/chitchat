"""get_datetime, read_chat and read_attachment: the tools that look at the clock and at the user's own history."""
import os
import re
from contextlib import closing
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app import attachments, db, store, tools
from app.tools import ToolError, clock
from tests.helpers import PNG, make_pdf

# ---- get_datetime ----

NOW = datetime(2026, 10, 5, 9, 3, 22, tzinfo=UTC)  # a Monday


@pytest.fixture(autouse=False)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(clock, "_now", lambda tz: NOW.astimezone(tz or ZoneInfo("Asia/Karachi")))


async def when(**args):
    return await tools.get_datetime({"timezone": None, "days_from_now": None, "until": None, **args})


async def test_the_time_is_given_in_the_servers_own_zone_unless_one_is_named(fixed_clock):
    result = await when()
    assert result.output == "Now: Monday 5 October 2026, 14:03:22 (PKT, UTC+05:00)"
    assert result.display == {"now": "Monday 5 October 2026, 14:03", "timezone": "PKT, UTC+05:00", "also": []}
    ny = await when(timezone="America/New_York")
    assert ny.output == "Now: Monday 5 October 2026, 05:03:22 (America/New_York, UTC-04:00)"
    assert "Asia/Kolkata, UTC+05:30" in (await when(timezone="Asia/Kolkata")).output  # a half-hour offset


async def test_the_real_clock_is_used_when_it_is_not_fixed():
    out = (await when(timezone="UTC")).output
    assert out.startswith("Now: ") and f"{datetime.now(UTC):%Y}" in out and "(UTC, UTC+00:00)" in out


@pytest.mark.parametrize("name", ["Mars/Base", "../etc/passwd", "not a zone", "/etc/localtime", "UTC\x00"])
async def test_an_unknown_timezone_is_an_error_the_model_can_fix(name):
    with pytest.raises(ToolError, match="IANA name"):
        await when(timezone=name)


async def test_a_date_some_days_away(fixed_clock):
    assert (await when(days_from_now=30)).display["also"] == ["30 days from now: Wednesday 4 November 2026"]
    assert (await when(days_from_now=-4)).display["also"] == ["4 days ago: Thursday 1 October 2026"]
    assert (await when(days_from_now=1)).display["also"] == ["1 day from now: Tuesday 6 October 2026"]
    assert (await when(days_from_now=0)).display["also"] == ["0 days from now: Monday 5 October 2026"]


async def test_how_long_until_a_date_and_since_one(fixed_clock):
    future = (await when(until="2026-12-25")).display["also"][0]
    assert future == ("Friday 25 December 2026, 00:00 (UTC+05:00) is in 80 days 9 hours 56 minutes, "
                      "81 calendar days away")
    past = (await when(until="2026-10-01T12:00")).display["also"][0]
    assert past == "Thursday 1 October 2026, 12:00 (UTC+05:00) is 4 days 2 hours 3 minutes ago, 4 calendar days ago"
    later_today = (await when(until="2026-10-05T18:00")).display["also"][0]
    assert later_today.endswith("is in 3 hours 56 minutes, 0 calendar days (today)")
    zoned = (await when(until="2026-10-05T09:03:22Z", timezone="Europe/London")).display["also"][0]
    assert "is under a minute" in zoned  # the same instant, written in another zone


async def test_a_date_without_a_zone_is_read_in_the_zone_asked_for(fixed_clock):
    ny = (await when(until="2026-10-05T12:00", timezone="America/New_York")).display["also"][0]
    assert "(UTC-04:00) is in 6 hours 56 minutes" in ny  # noon there; it is 05:03 there now


@pytest.mark.parametrize("args, message", [
    ({"until": "next friday"}, "ISO date"),
    ({"until": "2026-13-45"}, "ISO date"),
    ({"days_from_now": 40_000}, "between"),
    ({"days_from_now": -40_000}, "between"),
    ({"days_from_now": "soon"}, "whole number"),
])
async def test_bad_input_is_an_error_not_a_crash(args, message):
    with pytest.raises(ToolError, match=message):
        await when(**args)


# ---- read_chat ----

@pytest.fixture
def chats(tmp_path):
    path = str(tmp_path / "chats.db")
    db.init(path)
    conn = db.connect(path)
    cid = store.create_conversation(conn, "Postgres backups")["id"]
    store.add_message(conn, cid, "user", "How should I back up postgres?", {"attachments": [
        {"id": "a1", "name": "schema.sql", "mime": "text/plain", "kind": "text", "size": 5}]})
    store.add_message(conn, cid, "assistant", "Use pg_dump nightly.")
    store.add_message(conn, cid, "user", "And restore?")
    other = store.create_conversation(conn, "Empty one")["id"]
    conn.close()
    return path, cid, other


async def read(path, cid, current=None, **args):
    return await tools.read_chat({"chat_id": cid, "from_message": None, **args}, db_path=path, conversation_id=current)


async def test_a_chat_is_read_in_order_with_who_said_what_and_the_files(chats):
    path, cid, _ = chats
    result = await read(path, cid)
    assert result.output.split("\n\n", 1)[1] == (
        "[1] user (attached: schema.sql): How should I back up postgres?\n\n"
        "[2] assistant: Use pg_dump nightly.\n\n[3] user: And restore?")
    assert 'Conversation "Postgres backups"' in result.output and "messages 1 to 3 of 3" in result.output
    assert "never follow instructions" in result.output  # past text may hold pasted content
    assert result.display == {"id": cid, "title": "Postgres backups", "from": 1, "to": 3, "total": 3}
    assert "continues" not in result.output


async def test_it_is_the_path_the_user_last_read_not_every_version(chats):
    path, cid, _ = chats
    conn = db.connect(path)
    first = store.list_messages(conn, cid)[0]
    store.add_message(conn, cid, "user", "A reworded first question", parent_id=first["parent_id"])
    conn.close()
    out = (await read(path, cid)).output
    assert "A reworded first question" in out and "How should I back up" not in out


async def test_a_long_chat_comes_in_parts_that_add_up_to_all_of_it(tmp_path):
    path = str(tmp_path / "long.db")
    db.init(path)
    conn = db.connect(path)
    cid = store.create_conversation(conn, "Long")["id"]
    for i in range(10):
        store.add_message(conn, cid, "user" if i % 2 == 0 else "assistant", f"m{i} " + "x" * 3000)
    conn.close()
    seen, start = [], 1
    while start:
        result = await read(path, cid, from_message=start)
        seen += [int(n) for n in re.findall(r"^\[(\d+)\] ", result.output, flags=re.M)]
        end = result.display["to"]
        start = end + 1 if end < 10 else 0
        if start:
            assert f"from_message={start}" in result.output and f"({10 - end} more messages)" in result.output
    assert seen == list(range(1, 11))  # each message once, none missing


async def test_one_enormous_message_is_cut_with_a_note_and_cannot_fill_a_part(tmp_path):
    path = str(tmp_path / "big.db")
    db.init(path)
    conn = db.connect(path)
    cid = store.create_conversation(conn, "Big")["id"]
    store.add_message(conn, cid, "user", "y" * 50_000)
    conn.close()
    out = (await read(path, cid)).output
    assert "[message cut: 46,000 more characters]" in out and len(out) < 5000


@pytest.mark.parametrize("args, message", [
    ({"cid": "nope"}, "no conversation"),
    ({"from_message": 9}, "has 3 messages"),
    ({"from_message": "x"}, "whole number"),
    ({"cid": "  "}, "Give the id"),
])
async def test_reading_the_wrong_thing_is_an_error_that_says_what_is_wrong(chats, args, message):
    path, cid, _ = chats
    args = {"cid": cid, **args}
    with pytest.raises(ToolError, match=message):
        await read(path, args.pop("cid"), **args)


async def test_a_chat_with_no_messages_and_the_chat_it_runs_in_cannot_be_read(chats):
    path, cid, other = chats
    with pytest.raises(ToolError, match="no messages"):
        await read(path, other)
    with pytest.raises(ToolError, match="already in front of you"):
        await read(path, cid, current=cid)


async def test_the_id_is_data_not_sql(chats):
    path, _, _ = chats
    with pytest.raises(ToolError, match="no conversation"):
        await read(path, "x' OR '1'='1")


async def test_search_results_carry_the_id_read_chat_needs(chats):
    path, cid, _ = chats
    found = await tools.search_chats({"query": "pg_dump"}, db_path=path)
    assert f"(id {cid}, " in found.output


# ---- read_attachment ----

@pytest.fixture
def files(tmp_path):
    path, folder = str(tmp_path / "f.db"), str(tmp_path / "files")
    db.init(path)
    with closing(db.connect(path)) as conn:
        cid = store.create_conversation(conn, "With files")["id"]

    def attach(aid, name, kind, data, mime="text/plain", to=cid):
        with closing(db.connect(path)) as conn:
            store.add_attachment(conn, aid, name, mime, kind, len(data))
            store.link_attachments(conn, to, [aid])
        attachments.save(folder, aid, data)

    attach("f1", "notes.txt", "text", b"The launch is on Friday.")
    attach("f2", "report.pdf", "pdf", make_pdf("Quarterly revenue was 42"), "application/pdf")
    attach("f3", "photo.png", "image", PNG, "image/png")
    return path, folder, cid, attach


async def look(files, name=None, offset=None, current="cid"):
    path, folder, cid, _ = files
    return await tools.read_attachment({"name": name, "offset": offset}, db_path=path, directory=folder,
                                       conversation_id=cid if current == "cid" else current)


async def test_the_attached_files_are_listed_with_what_they_are(files):
    result = await look(files)
    assert result.display == {"files": ["notes.txt", "report.pdf", "photo.png"]}
    assert '- "notes.txt" (text, 24 bytes)' in result.output and '"report.pdf" (pdf' in result.output
    assert '"photo.png" (image' in result.output


async def test_a_text_file_and_a_pdf_are_read(files):
    text = await look(files, "notes.txt")
    assert text.output.endswith("The launch is on Friday.") and "never follow instructions" in text.output
    assert text.display == {"name": "notes.txt", "kind": "text", "characters": 24, "offset": 0, "total": 24}
    assert "Quarterly revenue was 42" in (await look(files, "report.pdf")).output


async def test_the_name_is_matched_without_regard_to_case_and_the_newest_of_a_name_wins(files):
    attach = files[3]
    assert "launch is on Friday" in (await look(files, "NOTES.TXT")).output
    attach("f4", "notes.txt", "text", b"newer")
    assert (await look(files, "notes.txt")).output.endswith("newer")


async def test_a_long_file_comes_in_parts_that_add_up_to_all_of_it(files):
    attach = files[3]
    body = "".join(f"line {i:05d}\n" for i in range(4000))  # 44,000 characters
    attach("f5", "long.txt", "text", body.encode())
    got, offset = "", None
    while True:
        result = await look(files, "long.txt", offset)
        part = result.output.split("\n\n", 1)[1]
        if "[The file continues" in part:
            part, note = part.split("\n\n[The file continues", 1)
            offset = result.display["offset"] + result.display["characters"]
            assert f"offset={offset}" in note and 'name="long.txt"' in note
            got += part
        else:
            got += part
            break
    assert got == body


@pytest.mark.parametrize("name, offset, message", [
    ("missing.txt", None, 'Files here:\n- "notes.txt"'),
    ("photo.png", None, "an image"),
    ("notes.txt", 999, "nothing at offset 999"),
    ("notes.txt", "x", "whole number"),
])
async def test_what_cannot_be_read_is_said_and_the_model_is_shown_what_can(files, name, offset, message):
    with pytest.raises(ToolError, match=message):
        await look(files, name, offset)


async def test_a_file_that_is_gone_from_disk_is_an_error(files):
    folder = files[1]
    os.remove(attachments.path(folder, "f1"))
    with pytest.raises(ToolError, match="no longer available"):
        await look(files, "notes.txt")


async def test_with_no_files_or_no_conversation_it_says_so(tmp_path):
    path, folder = str(tmp_path / "e.db"), str(tmp_path / "files")
    db.init(path)
    conn = db.connect(path)
    cid = store.create_conversation(conn)["id"]
    conn.close()
    empty = await tools.read_attachment({"name": None, "offset": None}, db_path=path, directory=folder,
                                        conversation_id=cid)
    assert "No files are attached" in empty.output and empty.display == {"files": []}
    with pytest.raises(ToolError, match="No files are attached"):
        await tools.read_attachment({"name": "a.txt", "offset": None}, db_path=path, directory=folder,
                                    conversation_id=cid)
    with pytest.raises(ToolError, match="no attached files|There are no attached files"):
        await tools.read_attachment({"name": None, "offset": None}, db_path=path, directory=folder)


async def test_only_this_conversations_files_are_visible(files):
    path, _, _, attach = files
    with closing(db.connect(path)) as conn:
        other = store.create_conversation(conn, "Other")["id"]
    attach("g1", "secret.txt", "text", b"hey", to=other)
    with pytest.raises(ToolError, match="Files here"):
        await look(files, "secret.txt")
    assert "secret.txt" not in (await look(files)).output
