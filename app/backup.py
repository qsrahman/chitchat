"""Backing up and moving conversations: all of them out as one JSON file (which can be imported again) or a zip of
Markdown files, and a JSON file back in. See docs/backup.md.

Importing never overwrites. A conversation whose id is already here is skipped, so importing the same file twice
changes nothing; the rest are added, all together or not at all. What an export can't carry (attachment files,
OpenAI's encrypted compaction items) is dropped, and what is kept of a message's metadata is checked, because the
page renders it: a crafted file must not be able to break a conversation.
"""
import io
import json
import re
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from app import store, tools
from app.store import ConversationSettings

FORMAT = "chitchat-backup"
VERSION = 2  # 2: messages have a `parent` and conversations a `leaf` (versions of a message); 1 files import as a path
MAX_IMPORT_BYTES = 50_000_000
MAX_CHATS = 5_000
MAX_MESSAGES = 20_000  # per conversation
MAX_CONTENT = 1_000_000  # characters in one message
TOOL_KEYS = ("id", "name", "arguments", "status", "display", "error")
TOOL_STATUSES = {"done", "error", "stopped"}  # a call that is still "running" is never saved


class ImportRejected(Exception):
    """The file can't be imported; the message says why, in words for the person who chose it."""


# ---- out: shared with the one-conversation export in routes.py ----

def public_message(m: dict) -> dict:
    """A message for the browser or an export: OpenAI's encrypted compaction item is only for the model."""
    c = m["meta"].get("compaction")
    return {**m, "meta": {**m["meta"], "compaction": {"after_reply": c["after_reply"]}}} if c else m


def exported(m: dict) -> dict:
    """A message of the path shown, for the one-conversation export: without the tree bookkeeping."""
    return {k: v for k, v in public_message(m).items() if k not in ("siblings", "parent_id")}


def markdown(conv: dict, messages: list[dict]) -> str:
    parts = [f"# {conv['title']}"]
    for m in messages:
        parts.append("## " + ("You" if m["role"] == "user" else "Assistant"))
        if files := m["meta"].get("attachments"):
            parts.append("*Attached: " + ", ".join(a["name"] for a in files) + "*")
        parts.append(m["content"])
    return "\n\n".join(parts) + "\n"


def file_name(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-") or "chat"


def _tree(conn, c: dict) -> dict:
    """A conversation with all its messages, every version: each names its `parent` and the conversation its `leaf`,
    as positions in the list (ids are only meaningful in this database)."""
    rows = store.all_messages(conn, c["id"])
    position = {m["id"]: i for i, m in enumerate(rows)}
    messages = [{"role": m["role"], "content": m["content"], "meta": public_message(m)["meta"],
                 "created_at": m["created_at"], "parent": position.get(m["parent_id"])} for m in rows]
    leaf = position.get(c["leaf_id"], len(rows) - 1) if rows else None
    return {**{k: v for k, v in c.items() if k != "leaf_id"}, "leaf": leaf, "messages": messages}


def _path(conn, c: dict) -> dict:
    """A conversation with the messages of the path shown (what a reader would see)."""
    return {**c, "messages": [public_message(m) for m in store.list_messages(conn, c["id"])]}


def _all(conn, build) -> list[dict]:
    """Every conversation, built with `_tree` or `_path`, oldest first."""
    return sorted((build(conn, c) for c in store.list_conversations(conn)), key=lambda c: c["created_at"])


def export_json(conn) -> bytes:
    document = {"format": FORMAT, "version": VERSION, "exported_at": datetime.now(UTC).isoformat(),
                "conversations": _all(conn, _tree)}
    return json.dumps(document, indent=2, ensure_ascii=False).encode()


def export_zip(conn) -> bytes:
    """One Markdown file per conversation, named by date, title and the start of its id (so names never repeat)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for chat in _all(conn, _path):
            name = f"{chat['created_at'][:10]}-{file_name(chat['title'])[:80]}-{chat['id'][:8]}.md"
            archive.writestr(name, markdown(chat, chat["messages"]))
    return buffer.getvalue()


# ---- in ----

class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_CONTENT)
    meta: dict = Field(default_factory=dict)
    created_at: str | None = None
    parent: StrictInt | None = None  # position of the message this follows; only read when the chat has a `leaf`


class _Chat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    title: str = ""
    settings: dict = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    leaf: StrictInt | None = None  # position of the last message of the path shown; its presence means versions
    messages: list[_Message] = Field(max_length=MAX_MESSAGES)


class _Backup(BaseModel):
    model_config = ConfigDict(extra="ignore")
    conversations: list[_Chat] = Field(max_length=MAX_CHATS)


def _parse(data: bytes) -> list[_Chat]:
    try:
        raw = json.loads(data)
    except (ValueError, RecursionError) as e:  # UnicodeDecodeError is a ValueError
        raise ImportRejected("That file isn't JSON, so it isn't a ChitChat export.") from e
    if isinstance(raw, dict) and "conversations" not in raw and "messages" in raw:
        raw = {"conversations": [raw]}  # the export of one conversation
    elif isinstance(raw, list):
        raw = {"conversations": raw}
    try:
        return _Backup.model_validate(raw).conversations
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise ImportRejected(f"That doesn't look like a ChitChat export ({where}: {first['msg']}).") from e


def _when(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return fallback
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC).isoformat()


def _clean_meta(meta: dict) -> tuple[dict, list[str]]:
    """What of a message's metadata is kept, and the names of the attachments that were left behind."""
    kept = {}
    if isinstance(meta.get("reasoning"), str) and meta["reasoning"]:
        kept["reasoning"] = meta["reasoning"]
    if isinstance(meta.get("usage"), dict):
        usage = {k: meta["usage"][k] for k in ("input_tokens", "output_tokens", "reasoning_tokens")
                 if isinstance(meta["usage"].get(k), int) and not isinstance(meta["usage"][k], bool)}
        if usage:
            kept["usage"] = usage
    if isinstance(meta.get("tools"), list):
        calls = [{k: c[k] for k in TOOL_KEYS if k in c} for c in meta["tools"][:50]
                 if isinstance(c, dict) and isinstance(c.get("id"), str) and isinstance(c.get("name"), str)
                 and c.get("status") in TOOL_STATUSES]
        for call in calls:  # arguments and display are objects, or absent
            for key in ("arguments", "display"):
                if key in call and not isinstance(call[key], dict):
                    del call[key]
            if "error" in call and not isinstance(call["error"], str):
                del call["error"]
        if calls:
            kept["tools"] = calls
    if meta.get("stopped") is True:
        kept["stopped"] = True
    if isinstance(meta.get("incomplete"), str):
        kept["incomplete"] = meta["incomplete"][:100]
    if isinstance(meta.get("trimmed"), int) and not isinstance(meta["trimmed"], bool) and meta["trimmed"] > 0:
        kept["trimmed"] = meta["trimmed"]
    files = meta["attachments"] if isinstance(meta.get("attachments"), list) else []
    names = [a["name"][:200] for a in files if isinstance(a, dict) and isinstance(a.get("name"), str)][:10]
    return kept, names


def _settings(raw: dict) -> dict:
    """The conversation's settings if they are valid; tools this version doesn't have are dropped, and settings that
    are still wrong give the defaults rather than a refused import."""
    if isinstance(raw.get("tools"), list):
        raw = {**raw, "tools": [t for t in raw["tools"] if t in tools.NAMES]}
    try:
        return ConversationSettings.model_validate(raw).model_dump()
    except ValidationError:
        return {}


def _structure(chat: _Chat) -> tuple[list[int | None], int | None]:
    """Each message's parent and the leaf, as positions. A file without `leaf` (version 1, or a one-chat export) is a
    straight path: each message follows the one before it. With `leaf`, the file says, and is checked: a parent
    must come earlier in the list, which also rules out loops."""
    count = len(chat.messages)
    if "leaf" not in chat.model_fields_set:
        return [None if i == 0 else i - 1 for i in range(count)], (count - 1 if count else None)
    parents = []
    for i, m in enumerate(chat.messages):
        if m.parent is not None and not 0 <= m.parent < i:
            raise ImportRejected(f"That file has a message ({i + 1} of \"{chat.title[:40]}\") that follows a message "
                                 "that does not come before it, so it can't be imported.")
        parents.append(m.parent)
    leaf = chat.leaf if chat.leaf is not None else (count - 1 if count else None)
    if leaf is not None and not 0 <= leaf < count:
        raise ImportRejected(f"That file says the chat \"{chat.title[:40]}\" ends at a message that is not there.")
    return parents, leaf


def _prepare(chat: _Chat, now: str) -> dict:
    created = _when(chat.created_at, now)
    parents, leaf = _structure(chat)
    messages = []
    for m, parent in zip(chat.messages, parents, strict=True):
        meta, left_behind = _clean_meta(m.meta)
        content = m.content
        if left_behind:
            note = f"[Attached when this was sent, not included in the import: {', '.join(left_behind)}]"
            content = f"{content}\n\n{note}" if content else note
        messages.append({"role": m.role, "content": content, "meta": meta, "created_at": _when(m.created_at, created),
                         "parent": parent})
    cid = chat.id if chat.id and re.fullmatch(r"[0-9a-f]{32}", chat.id) else uuid.uuid4().hex
    return {"id": cid, "title": chat.title.strip()[:200] or "Imported chat", "settings": _settings(chat.settings),
            "created_at": created, "updated_at": _when(chat.updated_at, created), "leaf": leaf, "messages": messages}


def import_chats(conn, data: bytes) -> dict:
    """Add the conversations in an exported file. Returns {"imported", "skipped" (already here), "messages"} counts.
    Raises ImportRejected, and changes nothing, if the file isn't a valid export."""
    now = datetime.now(UTC).isoformat()
    return store.import_conversations(conn, [_prepare(chat, now) for chat in _parse(data)])
