"""A copy of the database is made before it is upgraded (app/db.py)."""
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app import db


def old_database(path, upgrades=5):
    """A database as it was `upgrades` migrations in, with one chat of two messages."""
    with closing(sqlite3.connect(path)) as raw:
        for i, script in enumerate(db.MIGRATIONS[:upgrades], 1):
            raw.executescript(script)
            raw.execute(f"PRAGMA user_version = {i}")
        raw.execute("INSERT INTO conversations (id, title, created_at, updated_at) VALUES ('c', 'kept', 'x', 'x')")
        for role in ("user", "assistant"):
            raw.execute("INSERT INTO messages (conversation_id, role, content, created_at) VALUES ('c', ?, ?, 'x')",
                        (role, f"{role} text"))
        raw.commit()


def version(path):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def test_upgrading_a_database_leaves_a_copy_as_it_was(tmp_path, caplog):
    path = str(tmp_path / "chats.db")
    old_database(path)
    caplog.set_level(logging.INFO, logger="app")
    db.init(path)
    copy = Path(f"{path}.bak-v5")
    assert copy.exists()
    assert version(copy) == 5 and version(path) == len(db.MIGRATIONS)
    with closing(sqlite3.connect(copy)) as conn:  # the copy has the chats, and not the new columns
        texts = [r[0] for r in conn.execute("SELECT content FROM messages ORDER BY id")]
        assert texts == ["user text", "assistant text"]
        assert "parent_id" not in [r[1] for r in conn.execute("PRAGMA table_info(messages)")]
    assert "backed up the database" in caplog.text


def test_the_copy_includes_what_was_still_in_the_write_ahead_log(tmp_path):
    path = str(tmp_path / "chats.db")
    old_database(path)
    conn = sqlite3.connect(path)  # kept open so the log is not folded into the file when this connection closes
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES ('c', 'user', 'in the log', 'x')")
    conn.commit()
    try:
        db.init(path)
    finally:
        conn.close()
    with closing(sqlite3.connect(f"{path}.bak-v5")) as copy:
        assert copy.execute("SELECT COUNT(*) FROM messages WHERE content = 'in the log'").fetchone()[0] == 1


def test_no_copy_for_a_new_database_or_one_that_is_up_to_date(tmp_path):
    path = str(tmp_path / "chats.db")
    db.init(path)  # new: nothing to lose
    db.init(path)  # current: nothing to change
    assert list(tmp_path.glob("*.bak-*")) == []


def test_each_upgrade_is_named_by_the_version_it_started_from(tmp_path):
    path = str(tmp_path / "chats.db")
    old_database(path, upgrades=3)
    db.init(path)
    assert (tmp_path / "chats.db.bak-v3").exists()


def test_a_copy_that_exists_is_not_overwritten(tmp_path):
    """It is from an earlier, failed try at this upgrade: the better copy."""
    path = str(tmp_path / "chats.db")
    old_database(path)
    Path(f"{path}.bak-v5").write_bytes(b"the first copy")
    db.init(path)
    assert Path(f"{path}.bak-v5").read_bytes() == b"the first copy"
    assert version(path) == len(db.MIGRATIONS)  # and the upgrade still ran


def test_only_the_copies_of_the_most_recent_versions_are_kept(tmp_path):
    path = str(tmp_path / "chats.db")
    for v in (1, 2, 3):
        (tmp_path / f"chats.db.bak-v{v}").write_bytes(b"old")
    unrelated = [tmp_path / "chats.db.bak-v2.keep", tmp_path / "other.db.bak-v1", tmp_path / "chats.db.bak-vx"]
    for f in unrelated:
        f.write_bytes(b"mine")
    old_database(path, upgrades=5)
    db.init(path)  # makes bak-v5, then prunes
    assert sorted(p.name for p in tmp_path.glob("chats.db.bak-v*") if p.name[-1].isdigit()) == [
        "chats.db.bak-v3", "chats.db.bak-v5"]
    assert all(f.exists() for f in unrelated)  # nothing that is not ours is touched


def test_nothing_is_pruned_when_nothing_is_upgraded(tmp_path):
    path = str(tmp_path / "chats.db")
    db.init(path)
    for v in (1, 2, 3):
        (tmp_path / f"chats.db.bak-v{v}").write_bytes(b"old")
    db.init(path)
    assert len(list(tmp_path.glob("chats.db.bak-v*"))) == 3


BROKEN = "CREATE TABLE half (id TEXT);\nCREATE TABLE broken (id TEXT, id TEXT);"


def test_a_step_that_fails_half_way_leaves_the_version_it_started_from(tmp_path, monkeypatch):
    """So the next start runs that step again, on the schema it was meant to change, instead of on half of one."""
    path = str(tmp_path / "chats.db")
    monkeypatch.setattr(db, "MIGRATIONS", [db.SCHEMA, BROKEN, db.SETTINGS])
    with pytest.raises(sqlite3.OperationalError):
        db.init(path)
    with closing(db.connect(path)) as conn:
        assert version(path) == 1
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'half'").fetchone()

    monkeypatch.setattr(db, "MIGRATIONS", [db.SCHEMA, db.SETTINGS])  # the step, fixed, applies as it should
    db.init(path)
    with closing(db.connect(path)) as conn:
        assert version(path) == 2 and conn.execute("SELECT settings FROM conversations").fetchall() == []
