"""Conversation/message persistence: plain functions over a sqlite3 connection."""
import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app import tools
from app.llm import ReasoningEffort

DEFAULT_TITLE = "New chat"

Instructions = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10_000)]  # may be empty = unset


class ConversationSettings(BaseModel):
    """Per-conversation settings. None / "" mean "use the default"."""

    model_config = ConfigDict(extra="forbid")

    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    system_prompt: Instructions = ""
    reasoning_effort: ReasoningEffort = None
    temperature: Annotated[float, Field(ge=0, le=2)] | None = None
    tools: list[str] = Field(default_factory=list)  # tool names switched on for this conversation (tools.NAMES)

    @field_validator("tools")
    @classmethod
    def _known_tools(cls, names: list[str]) -> list[str]:
        if unknown := set(names) - set(tools.NAMES):
            raise ValueError(f"unknown tool: {', '.join(sorted(unknown))}")
        return list(dict.fromkeys(names))


DEFAULT_SETTINGS = ConversationSettings().model_dump()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _conversation(row: sqlite3.Row) -> dict:
    return {**dict(row), "settings": {**DEFAULT_SETTINGS, **json.loads(row["settings"])}}


def create_conversation(conn: sqlite3.Connection, title: str = DEFAULT_TITLE, settings: dict | None = None) -> dict:
    cid, now = uuid.uuid4().hex, _now()
    conn.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at, settings) VALUES (?, ?, ?, ?, ?)",
        (cid, title, now, now, json.dumps(settings or {})),
    )
    conn.commit()
    return get_conversation(conn, cid)


def get_conversation(conn: sqlite3.Connection, cid: str) -> dict | None:
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    return _conversation(row) if row else None


def list_conversations(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM conversations ORDER BY updated_at DESC, rowid DESC")
    return [_conversation(r) for r in rows]


def rename_conversation(conn: sqlite3.Connection, cid: str, title: str) -> dict | None:
    conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, cid))
    conn.commit()
    return get_conversation(conn, cid)


def update_conversation_settings(conn: sqlite3.Connection, cid: str, settings: dict) -> dict | None:
    conn.execute("UPDATE conversations SET settings = ? WHERE id = ?", (json.dumps(settings), cid))
    conn.commit()
    return get_conversation(conn, cid)


def get_app_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_app_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


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
    rows = conn.execute(
        "SELECT id, role, content, meta, created_at FROM messages WHERE conversation_id = ? ORDER BY id", (cid,)
    )
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


def search_conversations(conn: sqlite3.Connection, query: str, limit: int = 20, tokens: int = 12) -> list[dict]:
    """Conversations with a message matching every word of `query` (the last one as a prefix, so results follow
    the typing), best match first. Each has a snippet where the control characters STX and ETX enclose matches."""
    words = re.findall(r"\w+", query)  # only words reach FTS5's query syntax, so no input can break it
    if not words:
        return []
    match = " ".join(f'"{w}"' for w in words) + "*"
    rows = conn.execute(
        """SELECT c.id, c.title, c.updated_at, m.role, snippet(messages_fts, 0, char(2), char(3), '…', ?) AS snippet
           FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid
           JOIN conversations c ON c.id = m.conversation_id
           WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?""",
        (tokens, match, limit * 5),
    )
    best = {}
    for r in rows:  # in rank order, so the first row of a conversation is its best message
        best.setdefault(r["id"], dict(r))
    return list(best.values())[:limit]


# ---- attachments (files live on disk, see attachments.py; these rows say what they are) ----
ATTACHMENT_FIELDS = ("id", "name", "mime", "kind", "size")  # what a message's meta keeps about each one


def add_attachment(conn: sqlite3.Connection, aid: str, name: str, mime: str, kind: str, size: int) -> dict:
    conn.execute(
        "INSERT INTO attachments (id, name, mime, kind, size, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (aid, name, mime, kind, size, _now()),
    )
    conn.commit()
    return get_attachment(conn, aid)


def get_attachment(conn: sqlite3.Connection, aid: str) -> dict | None:
    row = conn.execute("SELECT * FROM attachments WHERE id = ?", (aid,)).fetchone()
    return dict(row) if row else None


def pending_attachments(conn: sqlite3.Connection, ids: list[str]) -> list[dict]:
    """The uploaded-but-unsent attachments among `ids`, in that order; ids that don't qualify are left out."""
    rows = [get_attachment(conn, aid) for aid in dict.fromkeys(ids)]
    return [r for r in rows if r and r["conversation_id"] is None]


def link_attachments(conn: sqlite3.Connection, cid: str, ids: list[str]) -> None:
    conn.executemany("UPDATE attachments SET conversation_id = ? WHERE id = ?", [(cid, aid) for aid in ids])
    conn.commit()


def attachment_ids(conn: sqlite3.Connection, cid: str) -> list[str]:
    return [r["id"] for r in conn.execute("SELECT id FROM attachments WHERE conversation_id = ?", (cid,))]


def purge_orphans(conn: sqlite3.Connection, older_than: timedelta) -> list[str]:
    """Delete uploads that were never sent with a message; returns their ids so the files can go too."""
    cutoff = (datetime.now(UTC) - older_than).isoformat()
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM attachments WHERE conversation_id IS NULL AND created_at < ?", (cutoff,))]
    conn.executemany("DELETE FROM attachments WHERE id = ?", [(aid,) for aid in ids])
    conn.commit()
    return ids
