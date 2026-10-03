"""Go back to a copy of the database that the app made before an upgrade (docs/round-6.md).

    uv run python scripts/restore_db.py                  # list the copies next to the database
    uv run python scripts/restore_db.py chitchat.db.bak-v6   # restore that one (asks first)

Stop the server first. Restoring never deletes anything: the database as it is now is moved aside to
`<db>.before-restore-<time>` (with its `-wal` and `-shm` files), the copy is checked, and then copied into place.
The restored database is at its old version; the app upgrades it again the next time it starts (and makes a fresh
copy of it first). The database is `DB_PATH` from `.env` unless `--db` says otherwise.
"""
import argparse
import re
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path


def find_copies(db_path: str) -> list[Path]:
    """The copies the app made of this database, newest version first."""
    path = Path(db_path)
    found = [(int(m.group(1)), p) for p in path.parent.glob(f"{path.name}.bak-v*")
             if (m := re.fullmatch(rf"{re.escape(path.name)}\.bak-v(\d+)", p.name))]
    return [p for _, p in sorted(found, reverse=True)]


def describe(path: Path) -> str:
    """What is in a database file, read without changing it: its schema version, chats, messages and size."""
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            chats = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    except sqlite3.DatabaseError as e:
        return f"not a usable database ({e})"
    return f"version {version}, {chats} chats, {messages} messages, {path.stat().st_size / 1e6:.1f} MB"


def check(copy: Path) -> int:
    """The schema version of a copy, if it is a sound database. Raises ValueError if not."""
    try:
        with closing(sqlite3.connect(f"{copy.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise ValueError(f"{copy.name} is damaged: {result}")
            conn.execute("SELECT COUNT(*) FROM conversations").fetchone()
            return conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.DatabaseError as e:
        raise ValueError(f"{copy.name} is not a usable database: {e}") from e


def restore(db_path: str, copy: Path, now: datetime | None = None) -> Path:
    """Put `copy` in place of the database. Returns where the old database went. Raises ValueError, and changes
    nothing, if the copy is not sound or is the database itself."""
    db = Path(db_path)
    if copy.resolve() == db.resolve():
        raise ValueError("that is the database itself")
    check(copy)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    aside = db.with_name(f"{db.name}.before-restore-{stamp}")
    for suffix in ("", "-wal", "-shm"):  # the database as it is now, moved and not deleted
        if (source := Path(str(db) + suffix)).exists():
            shutil.move(source, Path(str(aside) + suffix))
    with closing(sqlite3.connect(copy)) as source, closing(sqlite3.connect(db)) as target:
        source.backup(target)  # SQLite's own copy: a clean single file, whatever state the copy's journal is in
    return aside


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore a copy of the database made before an upgrade.")
    parser.add_argument("copy", nargs="?", help="the copy to restore (a path); leave out to list them")
    parser.add_argument("--db", help="the database (default: DB_PATH from .env, or chitchat.db)")
    parser.add_argument("--yes", action="store_true", help="do not ask first")
    args = parser.parse_args(argv)
    if args.db:
        db_path = args.db
    else:  # the project's own settings (.env), found by putting the project folder on the import path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from app.config import Settings
        db_path = Settings().db_path
    copies = find_copies(db_path)
    if not args.copy:
        print(f"{db_path}: {describe(Path(db_path)) if Path(db_path).exists() else 'not there'}")
        if not copies:
            print("no copies next to it (the app makes one before each upgrade)")
        for copy in copies:
            print(f"  {copy}: {describe(copy)}")
        return 0
    copy = Path(args.copy)
    if not copy.exists():
        print(f"{copy} does not exist", file=sys.stderr)
        return 1
    print(f"now:     {db_path}: {describe(Path(db_path)) if Path(db_path).exists() else 'not there'}")
    print(f"restore: {copy}: {describe(copy)}")
    print("The server must be stopped. The database as it is now is kept, moved aside.")
    if not args.yes and input("Restore it? Type yes: ").strip().lower() != "yes":
        print("Nothing changed.")
        return 1
    try:
        aside = restore(db_path, copy)
    except ValueError as e:
        print(f"Nothing changed: {e}", file=sys.stderr)
        return 1
    print(f"Restored. The database from before is {aside}. Start the server; it upgrades the restored one again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
