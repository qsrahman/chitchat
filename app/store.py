"""Conversation/message persistence: plain functions over a sqlite3 connection."""
import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app import db, tools
from app.llm import ReasoningEffort

DEFAULT_TITLE = "New chat"
BULK_IMPORT = 200  # messages: from this many an import indexes them in one go (see import_conversations)

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
    conv = get_conversation(conn, cid)
    assert conv  # just inserted
    return conv


def get_conversation(conn: sqlite3.Connection, cid: str) -> dict | None:
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    return _conversation(row) if row else None


def list_conversations(conn: sqlite3.Connection, limit: int = -1, offset: int = 0,
                       archived: bool | None = False) -> list[dict]:
    """Pinned chats first, then newest first. By default the chats that are not archived; `archived=True` the archived
    ones, None all of them. `limit=-1` is SQLite's "no limit"."""
    where, args = ("", ()) if archived is None else ("WHERE archived = ?", (int(archived),))
    rows = conn.execute(
        f"SELECT * FROM conversations {where} ORDER BY pinned DESC, updated_at DESC, rowid DESC LIMIT ? OFFSET ?",
        (*args, limit, offset))
    return [_conversation(r) for r in rows]


def set_flags(conn: sqlite3.Connection, cid: str, pinned: bool | None = None,
              archived: bool | None = None) -> dict | None:
    """Pin or archive a chat (None leaves a flag as it is). Does not count as activity: the order by recency stays."""
    for column, value in (("pinned", pinned), ("archived", archived)):
        if value is not None:
            conn.execute(f"UPDATE conversations SET {column} = ? WHERE id = ?", (int(value), cid))
    conn.commit()
    return get_conversation(conn, cid)


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


# ---- messages: a tree, of which one path is shown ----
# Every message has a parent (None for the first). A conversation's `leaf_id` is the end of the path you see: the
# messages from the root to it. A message's `siblings` are the messages with the same parent (the versions of an
# edited message, or of a regenerated reply), oldest first, itself included.
LEAF = "leaf"  # add_message's default parent: the end of the path shown now


def add_message(conn: sqlite3.Connection, cid: str, role: str, content: str, meta: dict | None = None,
                parent_id: int | None | Literal["leaf"] = LEAF) -> dict:
    """Add a message after `parent_id` (default: the end of the path shown; None: a new first message) and make it
    the end of the path."""
    now = _now()
    row = conn.execute("SELECT leaf_id FROM conversations WHERE id = ?", (cid,)).fetchone()
    leaf = row["leaf_id"] if row else None
    if parent_id == LEAF:
        parent_id = leaf
    elif parent_id != leaf:  # a new version beside something: the path shown now is being left
        _remember_path(conn, cid)
    cur = conn.execute(
        "INSERT INTO messages (conversation_id, parent_id, role, content, meta, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (cid, parent_id, role, content, json.dumps(meta or {}), now),
    )
    conn.execute("UPDATE conversations SET updated_at = ?, leaf_id = ? WHERE id = ?", (now, cur.lastrowid, cid))
    conn.commit()
    return {"id": cur.lastrowid, "role": role, "content": content, "meta": meta or {}, "created_at": now,
            "parent_id": parent_id}


def list_messages(conn: sqlite3.Connection, cid: str) -> list[dict]:
    """The messages of the path shown, first to last, each with its `siblings` (ids) and `parent_id`."""
    rows = conn.execute(
        """WITH RECURSIVE path(id, parent_id, role, content, meta, created_at) AS (
               SELECT m.id, m.parent_id, m.role, m.content, m.meta, m.created_at
               FROM messages m JOIN conversations c ON c.leaf_id = m.id WHERE c.id = ?
               UNION ALL
               SELECT m.id, m.parent_id, m.role, m.content, m.meta, m.created_at
               FROM messages m JOIN path ON m.id = path.parent_id)
           SELECT * FROM path ORDER BY id""",
        (cid,),
    ).fetchall()  # a parent is always older than its child, so ordering by id is ordering by depth
    families: dict[int | None, list[int]] = {}
    for r in conn.execute("SELECT id, parent_id FROM messages WHERE conversation_id = ? ORDER BY id", (cid,)):
        families.setdefault(r["parent_id"], []).append(r["id"])
    return [{**dict(r), "meta": json.loads(r["meta"]), "siblings": families[r["parent_id"]]} for r in rows]


def all_messages(conn: sqlite3.Connection, cid: str) -> list[dict]:
    """Every message of the conversation, on the path shown or not, oldest first (for the backup)."""
    rows = conn.execute(
        "SELECT id, parent_id, role, content, meta, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
        (cid,),
    )
    return [{**dict(r), "meta": json.loads(r["meta"])} for r in rows]


def siblings_of(conn: sqlite3.Connection, cid: str, message_id: int) -> list[int]:
    row = conn.execute(
        "SELECT parent_id FROM messages WHERE id = ? AND conversation_id = ?", (message_id, cid)
    ).fetchone()
    if not row:
        return []
    ids = conn.execute(
        "SELECT id FROM messages WHERE conversation_id = ? AND parent_id IS ? ORDER BY id", (cid, row["parent_id"])
    )
    return [r["id"] for r in ids]


def _path_ids(conn: sqlite3.Connection, cid: str) -> list[int]:
    """The ids of the path shown, first to last."""
    rows = conn.execute(
        """WITH RECURSIVE path(id, parent_id) AS (
               SELECT m.id, m.parent_id FROM messages m JOIN conversations c ON c.leaf_id = m.id WHERE c.id = ?
               UNION ALL SELECT m.id, m.parent_id FROM messages m JOIN path ON m.id = path.parent_id)
           SELECT id FROM path ORDER BY id""", (cid,))
    return [r["id"] for r in rows]


def _remember_path(conn: sqlite3.Connection, cid: str) -> None:
    """Note, on each message of the path shown, which message came next on it (`chosen_id`): the path is about to be
    left, and this is how select_branch finds its way back. Not committed here."""
    shown = _path_ids(conn, cid)
    conn.executemany("UPDATE messages SET chosen_id = ? WHERE id = ?", [(b, a) for a, b in pairwise(shown)])


def select_branch(conn: sqlite3.Connection, cid: str, message_id: int) -> bool:
    """Show the path through `message_id`, continued to its end the way it was last shown: at each step the reply
    that was showing the last time the path was left (`chosen_id`), else the newest. Leaving the path shown now
    is remembered the same way, so coming back lands here. False if the message is not in this conversation."""
    if not conn.execute("SELECT 1 FROM messages WHERE id = ? AND conversation_id = ?", (message_id, cid)).fetchone():
        return False
    _remember_path(conn, cid)
    leaf = message_id
    while True:
        row = conn.execute(
            """SELECT COALESCE(
                   (SELECT c.id FROM messages c WHERE c.id = p.chosen_id AND c.parent_id = p.id),
                   (SELECT MAX(c.id) FROM messages c WHERE c.conversation_id = ? AND c.parent_id = p.id)) AS next
               FROM messages p WHERE p.id = ?""", (cid, leaf)).fetchone()
        if not row["next"]:
            break
        leaf = row["next"]
    conn.execute("UPDATE conversations SET leaf_id = ? WHERE id = ?", (leaf, cid))
    conn.commit()
    return True


def set_leaf(conn: sqlite3.Connection, cid: str, message_id: int) -> None:
    """Make `message_id` the end of the path shown (a reply is about to be added to it)."""
    _remember_path(conn, cid)
    conn.execute("UPDATE conversations SET leaf_id = ? WHERE id = ?", (message_id, cid))
    conn.commit()


def import_conversations(conn: sqlite3.Connection, chats: list[dict]) -> dict:
    """Insert prepared conversations (id, title, settings, created_at, updated_at, leaf, and messages with role,
    content, meta, created_at and parent), all in one transaction: if anything fails, none are added. `parent` and
    `leaf` are positions in the list of messages (parent: an earlier one, or None); `attachments` (optional) are
    rows for files already on disk: id, name, mime, kind, size, created_at. One whose id is already here, or repeated
    in `chats`, is skipped. Returns {"imported", "skipped", "messages", "attachments"}."""
    imported = skipped = messages = files = 0
    bulk = sum(len(c["messages"]) for c in chats) >= BULK_IMPORT
    first_new = 0
    try:
        if bulk:
            # Indexing a message as it is inserted costs about 0.2 ms each, and one INSERT ... SELECT over all of
            # them costs a tenth of that (100,000 messages: 40 s against 4 s). The change is made inside the
            # transaction, so a failure rolls the trigger back with everything else.
            if not conn.in_transaction:
                conn.execute("BEGIN")
            first_new = conn.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()[0]
            conn.execute("DROP TRIGGER messages_fts_insert")
        for c in chats:
            if conn.execute("SELECT 1 FROM conversations WHERE id = ?", (c["id"],)).fetchone():
                skipped += 1
                continue
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at, settings, pinned, archived)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (c["id"], c["title"], c["created_at"], c["updated_at"], json.dumps(c["settings"]),
                 int(c.get("pinned", False)), int(c.get("archived", False))),
            )
            ids: list[int] = []
            for m in c["messages"]:
                cur = conn.execute(
                    "INSERT INTO messages (conversation_id, parent_id, role, content, meta, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (c["id"], None if m["parent"] is None else ids[m["parent"]], m["role"], m["content"],
                     json.dumps(m["meta"]), m["created_at"]),
                )
                ids.append(cur.lastrowid)  # pyright: ignore[reportArgumentType]
            if ids:
                conn.execute("UPDATE conversations SET leaf_id = ? WHERE id = ?", (ids[c["leaf"]], c["id"]))
            conn.executemany(
                "INSERT INTO attachments (id, conversation_id, name, mime, kind, size, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(a["id"], c["id"], a["name"], a["mime"], a["kind"], a["size"], a["created_at"])
                 for a in c.get("attachments", [])],
            )
            files += len(c.get("attachments", []))
            imported += 1
            messages += len(c["messages"])
        if bulk:
            conn.execute("INSERT INTO messages_fts(rowid, content) SELECT id, content FROM messages WHERE id > ?",
                         (first_new,))
            conn.execute(db.MESSAGES_FTS_INSERT_TRIGGER)  # one statement: executescript would commit
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"imported": imported, "skipped": skipped, "messages": messages, "attachments": files}


def search_conversations(
    conn: sqlite3.Connection, query: str, limit: int = 20, tokens: int = 12, exclude: str | None = None
) -> list[dict]:
    """Conversations whose title or a message matches every word of `query` (the last one as a prefix, so results
    follow the typing), those matching by title first. One row per conversation: id, title, updated_at, and
    title_marked (the title, with the control characters STX and ETX around matches); and, when a message matches,
    its message_id, role and a snippet marked the same way (otherwise message_id is None and snippet ""). `exclude`
    leaves one conversation out."""
    words = re.findall(r"\w+", query)  # only words reach FTS5's query syntax, so no input can break it
    if not words:
        return []
    match = " ".join(f'"{w}"' for w in words) + "*"
    skip, extra = ("AND c.id != ?", (exclude,)) if exclude else ("", ())
    by_title = conn.execute(
        f"""SELECT c.id, c.title, c.updated_at, highlight(conversations_fts, 0, char(2), char(3)) AS title_marked
            FROM conversations_fts JOIN conversations c ON c.rowid = conversations_fts.rowid
            WHERE conversations_fts MATCH ? {skip} ORDER BY rank LIMIT ?""",
        (match, *extra, limit),
    )
    by_message = conn.execute(
        f"""SELECT c.id, c.title, c.updated_at, m.id AS message_id, m.role,
                   snippet(messages_fts, 0, char(2), char(3), '…', ?) AS snippet
            FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid
            JOIN conversations c ON c.id = m.conversation_id
            WHERE messages_fts MATCH ? {skip} ORDER BY rank LIMIT ?""",
        (tokens, match, *extra, limit * 5),
    )
    found = {}
    for r in by_title:
        found[r["id"]] = {**dict(r), "message_id": None, "role": None, "snippet": ""}
    for r in by_message:  # in rank order, so the first row of a conversation is its best message
        row = found.setdefault(r["id"], {"id": r["id"], "title": r["title"], "updated_at": r["updated_at"],
                                         "title_marked": r["title"], "message_id": None, "role": None, "snippet": ""})
        if row["message_id"] is None:
            row.update(message_id=r["message_id"], role=r["role"], snippet=r["snippet"])
    return list(found.values())[:limit]


# ---- attachments (files live on disk, see attachments.py; these rows say what they are) ----
ATTACHMENT_FIELDS = ("id", "name", "mime", "kind", "size")  # what a message's meta keeps about each one


def add_attachment(conn: sqlite3.Connection, aid: str, name: str, mime: str, kind: str, size: int) -> dict:
    conn.execute(
        "INSERT INTO attachments (id, name, mime, kind, size, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (aid, name, mime, kind, size, _now()),
    )
    conn.commit()
    row = get_attachment(conn, aid)
    assert row  # just inserted
    return row


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
