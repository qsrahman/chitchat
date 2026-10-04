"""What the app keeps on disk, and clearing what is no longer needed (Settings, Data controls; docs/storage.md).

Two things can be removed, both on request and never on a timer: files nothing points to, and archived chats that
have not been touched for a while. Everything here is plain functions over a connection, like store.py."""
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import attachments, store

# Uploads are written to disk before their row is added, and a file is attached to a message a while after it is
# uploaded: anything younger than this may be on its way to being used.
GRACE = timedelta(hours=1)


def _size(file: Path) -> int:
    return file.stat().st_size if file.is_file() else 0


def _freed(directory: str, ids: list[str], strays: list[Path]) -> int:
    """The bytes of the files that go with these attachments (a PDF keeps its extracted text next to it), and of the
    files that no row names."""
    return (sum(_size(f) for a in ids for f in (attachments.path(directory, a),
                                                attachments.path(directory, a).with_suffix(".txt")))
            + sum(_size(f) for f in strays))


def _unsent(conn: sqlite3.Connection) -> list[str]:
    """Uploads that were never sent with a message (the page's own attach-then-send is covered by GRACE)."""
    cutoff = (datetime.now(UTC) - GRACE).isoformat()
    return [r["id"] for r in conn.execute(
        "SELECT id FROM attachments WHERE conversation_id IS NULL AND created_at < ?", (cutoff,))]


def _strays(conn: sqlite3.Connection, directory: str) -> list[Path]:
    """Files in the attachments folder that no row names: left behind by a crash or a copied folder. A file is
    `<id>`, and for a PDF also `<id>.txt` (its extracted text)."""
    folder = Path(directory)
    if not folder.is_dir():
        return []
    known = {r["id"] for r in conn.execute("SELECT id FROM attachments")}
    cutoff = (datetime.now(UTC) - GRACE).timestamp()
    return [f for f in folder.iterdir() if f.is_file() and f.stem not in known and f.stat().st_mtime < cutoff]


def _unused(conn: sqlite3.Connection, directory: str) -> tuple[list[str], list[Path]]:
    return _unsent(conn), _strays(conn, directory)


def overview(conn: sqlite3.Connection, db_path: str, directory: str) -> dict:
    """Sizes, for the Storage card. The database counts its write-ahead log, where recent changes still are."""
    unsent, strays = _unused(conn, directory)
    files = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes FROM attachments WHERE conversation_id IS NOT NULL"
    ).fetchone()
    chats = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(archived), 0) AS archived FROM conversations").fetchone()
    return {
        "database_bytes": _size(Path(db_path)) + _size(Path(f"{db_path}-wal")),
        "attachment_files": files["n"], "attachment_bytes": files["bytes"],
        "unused_files": len(unsent) + len(strays), "unused_bytes": _freed(directory, unsent, strays),
        "chats": chats["n"], "archived_chats": chats["archived"],
    }


def clear_unused(conn: sqlite3.Connection, directory: str) -> dict:
    """Delete the uploads that were never sent and the files no row names. Returns what went."""
    unsent, strays = _unused(conn, directory)
    freed = _freed(directory, unsent, strays)
    conn.executemany("DELETE FROM attachments WHERE id = ?", [(a,) for a in unsent])
    conn.commit()
    attachments.delete_files(directory, unsent)
    for f in strays:
        f.unlink(missing_ok=True)
    return {"files": len(unsent) + len(strays), "bytes": freed}


def _archived_before(conn: sqlite3.Connection, days: int) -> list[str]:
    """Archived chats whose last message is older than `days` (archiving does not count as activity)."""
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    return [r["id"] for r in conn.execute(
        "SELECT id FROM conversations WHERE archived = 1 AND updated_at < ?", (cutoff,))]


def count_archived(conn: sqlite3.Connection, days: int) -> int:
    return len(_archived_before(conn, days))


def delete_archived(conn: sqlite3.Connection, directory: str, days: int) -> list[str]:
    """Delete those chats, their attachment rows (cascade) and files, then give the freed pages back to the disk:
    SQLite keeps them in the file otherwise. All of them in one transaction, so a failure half way through leaves
    every chat that was there. Returns the ids, so the page can leave one that is open."""
    ids = _archived_before(conn, days)
    if not ids:
        return []
    files = [a for cid in ids for a in store.attachment_ids(conn, cid)]
    conn.executemany("DELETE FROM conversations WHERE id = ?", [(cid,) for cid in ids])
    conn.commit()
    attachments.delete_files(directory, files)
    conn.execute("VACUUM")  # not inside a transaction, or it does nothing
    return ids
