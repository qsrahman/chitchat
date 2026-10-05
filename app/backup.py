"""Backing up and moving conversations: all of them out as one JSON file (which can be imported again) or a zip of
Markdown files, and a JSON file back in. See docs/backup.md.

Importing never overwrites. A conversation whose id is already here is skipped, so importing the same file twice
changes nothing; the rest are added, all together or not at all. What an export can't carry (attachment files,
OpenAI's encrypted compaction items) is dropped, and what is kept of a message's metadata is checked, because the
page renders it: a crafted file must not be able to break a conversation.

The export with files is a zip: `chats.json` (the same document) and `attachments/<id>` for every file. Importing it
brings the files back: each is read, classified from its bytes again (the zip's claims about it are not believed),
and stored under a new id.
"""
import io
import json
import re
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any, BinaryIO, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from app import attachments, store, tools
from app.store import MAX_INSTRUCTIONS, ConversationSettings

FORMAT = "chitchat-backup"
VERSION = 2  # 2: messages have a `parent` and conversations a `leaf` (versions of a message); 1 files import as a path
MAX_IMPORT_BYTES = 50_000_000
MAX_CHATS = 5_000
MAX_MESSAGES = 20_000  # per conversation
MAX_CONTENT = 1_000_000  # characters in one message
ARCHIVE_JSON = "chats.json"
ARCHIVE_FILES = "attachments/"
MAX_ARCHIVE_BYTES = 1_000_000_000  # an uploaded zip
MAX_ARCHIVE_FILES_BYTES = 2_000_000_000  # all the files in it, unpacked
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


def _line(text) -> str:
    """Text from the web or a model on one line, so it can't start a new block of the document."""
    return " ".join(str(text).split())


def _link(title, url) -> str:
    """A Markdown link, for web addresses only: a title or URL that came from the web is not to become anything else."""
    title, url = _line(title).replace("[", "(").replace("]", ")"), str(url)
    if not url.startswith(("http://", "https://")) or any(c in url for c in " ()<>\n"):
        return title
    return f"[{title}]({url})"


def _tool_notes(call: dict) -> list[str]:
    """What a tool the model used reads like in the export: the line the page shows, and the sources it found. Saved
    calls can come from an older version or an imported file, so a shape that is not as expected gives nothing."""
    if call.get("status") != "done":
        return []
    shown: Any = call.get("display")
    try:
        match call["name"]:
            case "web_search":
                lines = [f"*Searched the web for* “{_line(shown['query'])}”"]
                lines += [f"- {_link(r['title'], r['url'])}" for r in shown["results"]]
                return lines
            case "fetch_url":
                return [f"*Read* {_link(shown.get('title') or shown['url'], shown['url'])}"]
            case "search_chats":
                return [f"*Searched your chats for* “{_line(shown['query'])}”"]
            case "read_chat":
                return [f"*Read the chat* “{_line(shown['title'])}”"]
            case "read_attachment" if "name" in shown:
                return [f"*Read the file* “{_line(shown['name'])}”"]
            case "calculator":
                # as code, so the * and _ of a sum stay as typed
                worked = _line(f"{shown['expression']} = {shown['result']}").replace("`", "")
                return [f"*Calculated* `{worked}`"]
    except (KeyError, TypeError, AttributeError):
        pass
    return []


def markdown(conv: dict, messages: list[dict]) -> str:
    """The conversation to read: who said what, the model that answered, the files attached, and the tools used."""
    parts = [f"# {conv['title']}"]
    for m in messages:
        meta = m["meta"]
        who = "You" if m["role"] == "user" else f"Assistant ({meta['model']})" if meta.get("model") else "Assistant"
        parts.append(f"## {who}")
        if files := meta.get("attachments"):
            parts.append("*Attached: " + ", ".join(a["name"] for a in files) + "*")
        for call in meta.get("tools") or []:
            if notes := _tool_notes(call):
                parts.append("\n".join(notes))
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
    return {**{k: v for k, v in c.items() if k != "leaf_id"}, "pinned": bool(c["pinned"]),
            "archived": bool(c["archived"]), "leaf": leaf, "messages": messages}


def _path(conn, c: dict) -> dict:
    """A conversation with the messages of the path shown (what a reader would see)."""
    return {**c, "messages": [public_message(m) for m in store.list_messages(conn, c["id"])]}


def _all(conn, build) -> list[dict]:
    """Every conversation, built with `_tree` or `_path`, oldest first."""
    return sorted((build(conn, c) for c in store.list_conversations(conn, archived=None)),
                  key=lambda c: c["created_at"])


def _document(conn) -> dict:
    return {"format": FORMAT, "version": VERSION, "exported_at": datetime.now(UTC).isoformat(),
            "custom_instructions": store.get_app_setting(conn, "custom_instructions"),
            "defaults": store.stored_defaults(conn),  # as chosen: tools null while they are the default
            "conversations": _all(conn, _tree)}


def export_json(conn) -> bytes:
    return json.dumps(_document(conn), indent=2, ensure_ascii=False).encode()


def export_archive(conn, files_dir: str) -> BinaryIO:
    """The JSON plus every attachment file it mentions, as a zip in a temporary file (rewound; the caller closes it:
    a library of images can be large, so it is not built in memory). A file that is gone from disk is left out and
    the import says so for that message."""
    document = _document(conn)
    ids = {a["id"] for c in document["conversations"] for m in c["messages"]
           for a in m["meta"].get("attachments", []) if isinstance(a.get("id"), str)}
    out = tempfile.TemporaryFile()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(ARCHIVE_JSON, json.dumps(document, indent=2, ensure_ascii=False))
        for aid in sorted(ids):
            source = attachments.path(files_dir, aid)
            if source.is_file():
                archive.write(source, ARCHIVE_FILES + aid)
    out.seek(0)
    return out


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
    pinned: bool = False  # lax on purpose: the one-chat export has them as 0 and 1
    archived: bool = False
    messages: list[_Message] = Field(max_length=MAX_MESSAGES)


class _Backup(BaseModel):
    model_config = ConfigDict(extra="ignore")
    conversations: list[_Chat] = Field(max_length=MAX_CHATS)
    custom_instructions: object = None  # text, or ignored
    defaults: object = None  # the defaults for new chats (store.Defaults), or ignored


def _parse(data: bytes) -> _Backup:
    try:
        raw = json.loads(data)
    except (ValueError, RecursionError) as e:  # UnicodeDecodeError is a ValueError
        raise ImportRejected("That file isn't JSON, so it isn't a ChitChat export.") from e
    if isinstance(raw, dict) and "conversations" not in raw and "messages" in raw:
        raw = {"conversations": [raw]}  # the export of one conversation
    elif isinstance(raw, list):
        raw = {"conversations": raw}
    try:
        return _Backup.model_validate(raw)
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


def _clean_meta(meta: dict) -> tuple[dict, list[dict]]:
    """What of a message's metadata is kept, and its attachments as the file listed them (to restore or to name)."""
    kept = {}
    if isinstance(meta.get("reasoning"), str) and meta["reasoning"]:
        kept["reasoning"] = meta["reasoning"]
    if isinstance(meta.get("usage"), dict):
        usage = {k: meta["usage"][k] for k in ("input_tokens", "output_tokens", "reasoning_tokens")
                 if isinstance(meta["usage"].get(k), int) and not isinstance(meta["usage"][k], bool)}
        if usage:
            kept["usage"] = usage
    if isinstance(meta.get("tools"), list):
        calls = [{k: c[k] for k in store.TOOL_META_KEYS if k in c} for c in meta["tools"][:50]
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
    if isinstance(meta.get("model"), str) and meta["model"].strip():
        kept["model"] = meta["model"].strip()[:200]  # which model wrote the reply
    if meta.get("stopped") is True:
        kept["stopped"] = True
    if isinstance(meta.get("incomplete"), str):
        kept["incomplete"] = meta["incomplete"][:100]
    if isinstance(meta.get("trimmed"), int) and not isinstance(meta["trimmed"], bool) and meta["trimmed"] > 0:
        kept["trimmed"] = meta["trimmed"]
    files = meta["attachments"] if isinstance(meta.get("attachments"), list) else []
    return kept, [a for a in files if isinstance(a, dict) and isinstance(a.get("name"), str)][:attachments.MAX_FILES]


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


class _Files:
    """The attachment files of a zip being imported: reads each one once, checks it, stores it under a new id and
    remembers the rows to add. `written` is every file put on disk, to remove again if the import fails."""

    def __init__(self, archive: zipfile.ZipFile | None, files_dir: str | None):
        self.archive, self.dir = archive, files_dir
        self.names = set(archive.namelist()) if archive else set()
        self.written: list[str] = []
        self.total = 0

    def _read(self, old_id: object) -> bytes | None:
        if not (self.archive and isinstance(old_id, str) and re.fullmatch(r"[0-9a-f]{32}", old_id)):
            return None
        member = ARCHIVE_FILES + old_id
        if member not in self.names:
            return None
        limit = max(attachments.LIMITS.values())
        with self.archive.open(member) as f:  # never more than a file may be, whatever the zip says its size is
            data = f.read(limit + 1)
        return data if len(data) <= limit else None

    def restore(self, listed: list[dict], created: str, done: dict, rows: list[dict]) -> tuple[list[dict], list[str]]:
        """Bring back the attachments a message lists. Returns (what the message now has, names left behind).
        `done` maps an old id to what it became (versions of a message share their files), `rows` collects new rows."""
        kept, missing = [], []
        for a in listed:
            name = attachments.safe_name(a["name"])
            old = a.get("id")
            if isinstance(old, str) and old in done:
                kept.append(done[old])
                continue
            data = self._read(old)
            try:
                if data is None:
                    raise attachments.Rejected(404, "not in the file")
                kind, mime = attachments.classify(data)  # from the bytes: what the file says about itself is not used
            except attachments.Rejected:
                missing.append(name)
                continue
            self.total += len(data)
            if self.total > MAX_ARCHIVE_FILES_BYTES:
                raise ImportRejected(f"The files in that backup are over {MAX_ARCHIVE_FILES_BYTES // 1_000_000_000} GB "
                                     "together, which is more than this app imports.")
            new_id = uuid.uuid4().hex
            attachments.save(self.dir or "", new_id, data)
            self.written.append(new_id)
            row = {"id": new_id, "name": name, "mime": mime, "kind": kind, "size": len(data), "created_at": created}
            rows.append(row)
            done[old] = kept_entry = {k: row[k] for k in store.ATTACHMENT_FIELDS}
            kept.append(kept_entry)
        return kept, missing


def _prepare(chat: _Chat, now: str, files: _Files, taken: set[str]) -> dict:
    """The chat as store.import_conversations takes it. A chat whose id is in `taken` (already here, or earlier in
    the file) will be skipped, so its files are not brought in. Adds the chat's id to `taken`."""
    created = _when(chat.created_at, now)
    parents, leaf = _structure(chat)
    cid = chat.id if chat.id and re.fullmatch(r"[0-9a-f]{32}", chat.id) else uuid.uuid4().hex
    wanted = cid not in taken
    taken.add(cid)
    messages, rows, done = [], [], {}
    for m, parent in zip(chat.messages, parents, strict=True):
        meta, listed = _clean_meta(m.meta)
        kept, left_behind = files.restore(listed, created, done, rows) if wanted else ([], [a["name"] for a in listed])
        if kept:
            meta["attachments"] = kept
        content = m.content
        if left_behind:
            names = ", ".join(n[:200] for n in left_behind)
            note = f"[Attached when this was sent, not included in the import: {names}]"
            content = f"{content}\n\n{note}" if content else note
        messages.append({"role": m.role, "content": content, "meta": meta, "created_at": _when(m.created_at, created),
                         "parent": parent})
    return {"id": cid, "title": chat.title.strip()[:200] or "Imported chat", "settings": _settings(chat.settings),
            "created_at": created, "updated_at": _when(chat.updated_at, created), "leaf": leaf, "messages": messages,
            "attachments": rows, "pinned": chat.pinned, "archived": chat.archived}


def _import(conn, data: bytes, files: _Files) -> dict:
    now = datetime.now(UTC).isoformat()
    backup = _parse(data)
    taken = {r[0] for r in conn.execute("SELECT id FROM conversations")}
    try:
        result = store.import_conversations(conn, [_prepare(chat, now, files, taken) for chat in backup.conversations])
    except Exception:
        attachments.delete_files(files.dir or "", files.written)
        raise
    result["custom_instructions"] = _instructions(conn, backup.custom_instructions)
    result["defaults"] = _defaults(conn, backup.defaults)
    return result


def _defaults(conn, raw: object) -> bool:
    """Take the backup's defaults for new chats if it has some and none are chosen here (nothing is overwritten).
    Tools this version doesn't have are dropped, as in a chat's settings; anything else that doesn't fit is ignored."""
    if not isinstance(raw, dict) or store.defaults_chosen(conn):
        return False
    names = raw.get("tools")
    chosen = {"tools": [t for t in names if t in tools.NAMES]} if isinstance(names, list) else {}  # else the default
    try:
        defaults = store.Defaults.model_validate(
            {"model": raw.get("model"), "reasoning_effort": raw.get("reasoning_effort"), **chosen})
    except ValueError:
        return False
    if defaults == store.Defaults():
        return False
    store.set_defaults(conn, defaults.model_dump())
    return True


def _instructions(conn, text: object) -> bool:
    """Take the backup's custom instructions if it has some and there are none here (nothing is overwritten)."""
    if not (isinstance(text, str) and text.strip()) or len(text.strip()) > MAX_INSTRUCTIONS:
        return False
    if store.get_app_setting(conn, "custom_instructions"):
        return False
    store.set_app_setting(conn, "custom_instructions", text.strip())
    return True


def import_chats(conn, data: bytes) -> dict:
    """Add the conversations in an exported JSON file. Returns {"imported", "skipped" (already here), "messages",
    "attachments" (0: a JSON file has none), "custom_instructions" and "defaults" (taken or not)}. Raises
    ImportRejected, and changes nothing, if the file isn't a valid export."""
    return _import(conn, data, _Files(None, None))


def import_archive(conn, source: BinaryIO, files_dir: str) -> dict:
    """The same for the zip with files: the chats, and the attachment files that are in it."""
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile as e:
        raise ImportRejected("That file isn't a readable zip, so it isn't a ChitChat backup.") from e
    with archive:
        if ARCHIVE_JSON not in archive.namelist():
            raise ImportRejected(f"That zip has no {ARCHIVE_JSON}, so it isn't a ChitChat backup with files "
                                 "(the Markdown export is for reading and can't be imported).")
        if archive.getinfo(ARCHIVE_JSON).file_size > MAX_IMPORT_BYTES:
            raise ImportRejected(f"The chats in that backup are over {MAX_IMPORT_BYTES // 1_000_000} MB.")
        with archive.open(ARCHIVE_JSON) as f:
            data = f.read(MAX_IMPORT_BYTES + 1)
        if len(data) > MAX_IMPORT_BYTES:
            raise ImportRejected(f"The chats in that backup are over {MAX_IMPORT_BYTES // 1_000_000} MB.")
        return _import(conn, data, _Files(archive, files_dir))
