"""scripts/restore_db.py: going back to a copy made before an upgrade."""
import importlib.util
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from app import db
from tests.test_db_backup import old_database, version

spec = importlib.util.spec_from_file_location("restore_db", Path(__file__).parent.parent / "scripts" / "restore_db.py")
restore_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore_db)


@pytest.fixture
def upgraded(tmp_path):
    """A database that was upgraded from version 5 (so a copy exists), with a chat added after the upgrade."""
    path = str(tmp_path / "chats.db")
    old_database(path)
    db.init(path)
    with closing(db.connect(path)) as conn:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) VALUES ('new', 'after', 'x', 'x')")
        conn.commit()
    return path


def titles(path):
    with closing(sqlite3.connect(path)) as conn:
        return sorted(r[0] for r in conn.execute("SELECT title FROM conversations"))


def test_the_copies_are_found_newest_version_first_and_only_ours(tmp_path):
    path = str(tmp_path / "chats.db")
    for name in ("chats.db.bak-v3", "chats.db.bak-v10", "chats.db.bak-v2", "chats.db.bak-v2.keep", "other.db.bak-v9"):
        (tmp_path / name).write_bytes(b"x")
    assert [p.name for p in restore_db.find_copies(path)] == ["chats.db.bak-v10", "chats.db.bak-v3", "chats.db.bak-v2"]


def test_a_copy_is_described_without_being_changed(upgraded):
    copy = Path(upgraded + ".bak-v5")
    before = copy.read_bytes()
    assert restore_db.describe(copy).startswith("version 5, 1 chats, 2 messages")
    assert restore_db.describe(Path(upgraded)).startswith(f"version {len(db.MIGRATIONS)}, 2 chats")
    assert copy.read_bytes() == before


def test_restoring_puts_the_copy_in_place_and_keeps_the_database_it_replaced(upgraded):
    copy = Path(upgraded + ".bak-v5")
    aside = restore_db.restore(upgraded, copy, now=datetime(2026, 10, 4, 12, 30, 5))
    assert aside.name == "chats.db.before-restore-20261004-123005"
    assert titles(upgraded) == ["kept"] and version(upgraded) == 5  # back as it was, at its old version
    assert titles(aside) == ["after", "kept"] and version(aside) == len(db.MIGRATIONS)  # nothing was lost
    assert copy.exists()  # and the copy is still there


def test_the_restored_database_is_upgraded_again_when_the_app_starts(upgraded):
    restore_db.restore(upgraded, Path(upgraded + ".bak-v5"))
    db.init(upgraded)
    assert version(upgraded) == len(db.MIGRATIONS) and titles(upgraded) == ["kept"]


def test_the_write_ahead_log_of_the_old_database_is_moved_too(upgraded, tmp_path):
    hold = sqlite3.connect(upgraded)  # an open connection keeps the -wal and -shm files around
    hold.execute("PRAGMA journal_mode = WAL")
    hold.execute("INSERT INTO conversations (id, title, created_at, updated_at) VALUES ('wal', 'in the log', 'x', 'x')")
    hold.commit()
    try:
        assert Path(upgraded + "-wal").exists()
        aside = restore_db.restore(upgraded, Path(upgraded + ".bak-v5"), now=datetime(2026, 1, 1))
    finally:
        hold.close()
    assert "in the log" in titles(aside)  # what only the log held is in the moved database
    assert "in the log" not in titles(upgraded)


@pytest.mark.parametrize("content, why", [(b"this is not a database", "not sqlite"), (b"", "empty")])
def test_a_copy_that_is_not_a_database_is_refused_and_nothing_changes(upgraded, tmp_path, content, why):
    bad = tmp_path / "chats.db.bak-v1"
    bad.write_bytes(content)
    before = titles(upgraded)
    with pytest.raises(ValueError):
        restore_db.restore(upgraded, bad)
    assert titles(upgraded) == before and list(tmp_path.glob("*.before-restore-*")) == [], why


def test_the_database_cannot_be_restored_from_itself(upgraded):
    with pytest.raises(ValueError, match="itself"):
        restore_db.restore(upgraded, Path(upgraded))


def test_a_damaged_copy_is_refused(upgraded, tmp_path):
    damaged = tmp_path / "chats.db.bak-v4"
    data = bytearray(Path(upgraded + ".bak-v5").read_bytes())
    for i in range(4096 * 2, min(len(data), 4096 * 6)):
        data[i] = 0xAB  # trample the middle of the file
    damaged.write_bytes(bytes(data))
    with pytest.raises(ValueError):
        restore_db.restore(upgraded, damaged)
    assert "after" in titles(upgraded)


def test_the_command_lists_asks_and_restores(upgraded, capsys, monkeypatch):
    assert restore_db.main(["--db", upgraded]) == 0
    listing = capsys.readouterr().out
    assert "chats.db.bak-v5: version 5, 1 chats" in listing
    copy = upgraded + ".bak-v5"
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    assert restore_db.main(["--db", upgraded, copy]) == 1
    assert "Nothing changed." in capsys.readouterr().out and "after" in titles(upgraded)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    assert restore_db.main(["--db", upgraded, copy]) == 0
    assert "before-restore" in capsys.readouterr().out and titles(upgraded) == ["kept"]


def test_the_command_says_so_when_there_is_nothing_to_restore(tmp_path, capsys):
    path = str(tmp_path / "chats.db")
    db.init(path)
    assert restore_db.main(["--db", path]) == 0
    assert "no copies next to it" in capsys.readouterr().out
    assert restore_db.main(["--db", path, str(tmp_path / "missing")]) == 1
