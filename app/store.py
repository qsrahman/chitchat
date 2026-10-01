"""Conversation/message persistence: plain functions over a sqlite3 connection."""
import json
import sqlite3
import uuid
from datetime import UTC, datetime

DEFAULT_TITLE = "New chat"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_conversation(conn: sqlite3.Connection, title: str = DEFAULT_TITLE) -> dict:
    cid, now = uuid.uuid4().hex, _now()
    conn.execute("INSERT INTO conversations VALUES (?, ?, ?, ?)", (cid, title, now, now))
    conn.commit()
    return get_conversation(conn, cid)


def get_conversation(conn: sqlite3.Connection, cid: str) -> dict | None:
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    return dict(row) if row else None


def list_conversations(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM conversations ORDER BY updated_at DESC, rowid DESC")
    return [dict(r) for r in rows]


def rename_conversation(conn: sqlite3.Connection, cid: str, title: str) -> dict | None:
    conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, cid))
    conn.commit()
    return get_conversation(conn, cid)


def delete_conversation(conn: sqlite3.Connection, cid: str) -> bool:
    cur = conn.execute("DELETE FROM conversations WHERE id = ?", (cid,))
    conn.commit()
    return cur.rowcount > 0


def add_message(conn: sqlite3.Connection, cid: str, role: str, content: str, meta: dict | None = None) -> dict:
    now = _now()
    cur = conn.execute(
        "INSERT INTO messages (conversation_id, role, content, meta, created_at) VALUES (?, ?, ?, ?, ?)",
        (cid, role, content, json.dumps(meta or {}), now),
    )
    conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, cid))
    conn.commit()
    return {"id": cur.lastrowid, "role": role, "content": content, "meta": meta or {}, "created_at": now}


def list_messages(conn: sqlite3.Connection, cid: str) -> list[dict]:
    rows = conn.execute("SELECT id, role, content, meta, created_at FROM messages WHERE conversation_id = ? ORDER BY id", (cid,))
    return [{**dict(r), "meta": json.loads(r["meta"])} for r in rows]


def last_user_message(conn: sqlite3.Connection, cid: str) -> dict | None:
    row = conn.execute(
        "SELECT id, content FROM messages WHERE conversation_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1", (cid,)
    ).fetchone()
    return dict(row) if row else None


def update_message_content(conn: sqlite3.Connection, message_id: int, content: str) -> None:
    conn.execute("UPDATE messages SET content = ? WHERE id = ?", (content, message_id))
    conn.commit()


def delete_messages_after(conn: sqlite3.Connection, cid: str, message_id: int) -> None:
    conn.execute("DELETE FROM messages WHERE conversation_id = ? AND id > ?", (cid, message_id))
    conn.commit()
