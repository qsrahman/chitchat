import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated, Any, BinaryIO, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.sse import EventSourceResponse
from pydantic import BaseModel, Field, StringConstraints, model_validator

from app import attachments, backup, context, db, storage, store, tools
from app.llm import REASONING_EFFORTS, supports_reasoning
from app.store import ConversationSettings, Defaults, Instructions

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# Strip on the way in, so whitespace alone is neither a message nor a title.
Content = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100_000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(request.app.state.settings.db_path)) as conn:
        yield conn


Conn = Annotated[sqlite3.Connection, Depends(get_db)]


class ConversationUpdate(BaseModel):
    title: Title | None = None
    settings: ConversationSettings | None = None
    pinned: bool | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def _something_to_change(self):
        if all(v is None for v in (self.title, self.settings, self.pinned, self.archived)):
            raise ValueError("send a title, settings, pinned or archived")
        return self


class NewConversation(BaseModel):
    settings: ConversationSettings | None = None


class CustomInstructions(BaseModel):
    text: Instructions


Model = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class EditRequest(BaseModel):
    content: Content
    message_id: int | None = None  # the user message to rewrite (on the path shown); the last one by default
    model: Model | None = None  # for this reply only; the conversation's own model is not changed


class RegenerateRequest(BaseModel):
    model: Model | None = None  # for this reply only: "try again with another model"


class BranchRequest(BaseModel):
    message_id: int  # show the path through this message, one of a message's versions


class ChatRequest(BaseModel):
    content: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100_000)] = ""
    model: str | None = None
    attachments: list[str] = Field(default_factory=list, max_length=attachments.MAX_FILES)  # uploaded ids

    @model_validator(mode="after")
    def _something_to_send(self):
        if not self.content and not self.attachments:
            raise ValueError("send a message, an attachment, or both")
        return self


def _require(conn: sqlite3.Connection, cid: str) -> dict:
    conv = store.get_conversation(conn, cid)
    if not conv:
        raise HTTPException(404, "conversation not found")
    return conv


@router.get("/conversations")
def list_conversations(conn: Conn, limit: Annotated[int, Query(ge=1, le=500)] = 50,
                       offset: Annotated[int, Query(ge=0)] = 0, archived: bool = False):
    """Pinned chats first, then newest first: the chats that are not archived, or with `archived=true` the archived."""
    return store.list_conversations(conn, limit, offset, archived)


@router.post("/conversations", status_code=201)
def create_conversation(conn: Conn, body: NewConversation | None = None):
    if body and body.settings:
        settings = body.settings.model_dump()
    else:  # a chat made without settings starts with the tools chosen in Settings (the page sends its own, with them)
        settings = {**store.DEFAULT_SETTINGS, "tools": store.get_defaults(conn)["tools"]}
    return store.create_conversation(conn, settings=settings)


def _conversation(conn: sqlite3.Connection, cid: str) -> dict:
    """The conversation and the messages of the path shown, as GET /conversations/{cid} returns them."""
    conv = _require(conn, cid)
    return {**conv, "messages": [backup.public_message(m) for m in store.list_messages(conn, cid)]}


@router.get("/conversations/{cid}")
def get_conversation(cid: str, conn: Conn):
    return _conversation(conn, cid)


@router.post("/conversations/{cid}/branch")
def choose_branch(cid: str, body: BranchRequest, conn: Conn):
    """Switch to another version of a message: the conversation as it reads through that message, then on to the
    newest reply after it. Returns the conversation like GET does."""
    _require(conn, cid)
    if not store.select_branch(conn, cid, body.message_id):
        raise HTTPException(404, "message not found")
    return _conversation(conn, cid)


@router.get("/search")
def search(q: Annotated[str, Query(min_length=1, max_length=200)], conn: Conn):
    """Conversations whose messages match; `snippet` marks the matched words with STX/ETX characters."""
    return store.search_conversations(conn, q)


def _download(name: str) -> dict[str, str]:
    """The header that makes a browser save the answer under `name` instead of showing it."""
    return {"Content-Disposition": f'attachment; filename="{name}"'}


@router.get("/conversations/{cid}/export")
def export_conversation(cid: str, conn: Conn, format: Literal["md", "json"] = "md"):
    """The conversation as a Markdown or JSON download. Attachments are listed by name, not included."""
    conv = _require(conn, cid)
    messages = [backup.exported(m) for m in store.list_messages(conn, cid)]  # the path shown, not other versions
    if format == "md":
        body, media_type = backup.markdown(conv, messages), "text/markdown"
    else:
        body, media_type = json.dumps({**conv, "messages": messages}, indent=2, ensure_ascii=False), "application/json"
    return Response(body, media_type=f"{media_type}; charset=utf-8",
                    headers=_download(f'{backup.file_name(conv["title"])}.{format}'))


def _chunks(file: BinaryIO) -> Iterator[bytes]:
    with file:
        while chunk := file.read(1_000_000):
            yield chunk


@router.get("/export")
def export_everything(request: Request, conn: Conn, format: Literal["json", "md", "full"] = "json"):
    """Every conversation: one JSON file that /api/import takes back, a zip of Markdown files, or ("full") a zip
    with the JSON and the attachment files, which /api/import takes back too."""
    stamp = f"{datetime.now(UTC):%Y-%m-%d}"  # the day it was made, whichever way it is asked for
    if format == "full":
        archive = backup.export_archive(conn, request.app.state.settings.attachments_dir)
        return StreamingResponse(_chunks(archive), media_type="application/zip",
                                 headers=_download(f"chitchat-{stamp}-with-files.zip"))
    if format == "json":
        body, media_type, extension = backup.export_json(conn), "application/json", "json"
    else:
        body, media_type, extension = backup.export_zip(conn), "application/zip", "zip"
    return Response(body, media_type=media_type, headers=_download(f"chitchat-{stamp}.{extension}"))


def _too_large(limit: int) -> HTTPException:
    return HTTPException(413, f"That file is too large to import (over {limit // 1_000_000} MB).")


def _uploaded_size(file: UploadFile) -> int:
    """How many bytes were really uploaded: measured from the file the parser spooled, because what the client said
    the size was (file.size) is not filled in by every version of Starlette. Leaves it at the start."""
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)
    return size


@router.post("/import", status_code=201)
async def import_conversations(file: UploadFile, request: Request, conn: Conn):
    """Add the conversations in an exported file: the JSON, or the zip with files (all of them, or none if it isn't
    a valid export)."""
    is_zip = await file.read(4) == b"PK\x03\x04"
    await file.seek(0)
    try:
        if is_zip:
            if _uploaded_size(file) > backup.MAX_ARCHIVE_BYTES:
                raise _too_large(backup.MAX_ARCHIVE_BYTES)
            files_dir = request.app.state.settings.attachments_dir
            return await asyncio.to_thread(backup.import_archive, conn, file.file, files_dir)
        data = await file.read(backup.MAX_IMPORT_BYTES + 1)
        if len(data) > backup.MAX_IMPORT_BYTES:
            raise _too_large(backup.MAX_IMPORT_BYTES)
        return await asyncio.to_thread(backup.import_chats, conn, data)  # a big import takes seconds: not on the loop
    except backup.ImportRejected as e:
        raise HTTPException(422, str(e)) from e


@router.patch("/conversations/{cid}")
def update_conversation(cid: str, body: ConversationUpdate, conn: Conn):
    """Rename, replace the settings, pin or unpin, archive or unarchive: any of them."""
    _require(conn, cid)
    if body.pinned is not None or body.archived is not None:
        store.set_flags(conn, cid, body.pinned, body.archived)
    if body.title is not None:
        store.rename_conversation(conn, cid, body.title)
    if body.settings is not None:
        store.update_conversation_settings(conn, cid, body.settings.model_dump())
    return store.get_conversation(conn, cid)


@router.get("/defaults")
def get_defaults(conn: Conn):
    return store.get_defaults(conn)


@router.put("/defaults")
def put_defaults(body: Defaults, conn: Conn):
    """Change the defaults named in the body; the others stay. null puts one back to "not chosen" (for the tools that
    is: every tool but web search)."""
    return store.set_defaults(conn, body.model_dump(exclude_unset=True))


@router.get("/models")
async def list_models(request: Request, conn: Conn):
    """Models to offer in the picker: the default first (the one chosen in Settings, else the server's), then
    whatever the endpoint lists."""
    default = store.get_defaults(conn)["model"] or request.app.state.settings.openai_model
    ids = [default] + [m for m in await request.app.state.llm.list_models() if m != default]
    return {
        "default": default,
        "server_default": request.app.state.settings.openai_model,
        "efforts": REASONING_EFFORTS,
        "models": [{"id": m, "reasoning": supports_reasoning(m)} for m in ids],
    }


@router.get("/tools")
def list_tools(request: Request):
    """The tools that can be switched on for a conversation (those that are configured)."""
    return [{"name": t.name, "label": t.label, "hint": t.hint} for t in request.app.state.tools.values()]


def _endpoint(base_url: str) -> str:
    """The endpoint as the Settings dialog shows it: its scheme and host, without a path or credentials. A port that
    isn't a number (a mistyped one) is left out rather than raise, since this only reads a setting."""
    parsed = urlsplit(base_url)
    port = None
    try:
        port = parsed.port
    except ValueError:
        pass
    if not parsed.hostname:
        return "custom"  # not a scheme and host we can name
    return f"{parsed.scheme}://{parsed.hostname}{f':{port}' if port else ''}"


@router.get("/config")
def server_config(request: Request, conn: Conn):
    """What the server is set up with, for the Settings dialog to show (read only: it comes from the environment or
    `.env`, and changing it means editing that and restarting). No secrets: a key is only reported as set or not,
    and the endpoint is its scheme and host, without a path or credentials."""
    s = request.app.state.settings
    return {
        "endpoint": _endpoint(s.openai_base_url) if s.openai_base_url else "OpenAI",
        "custom_endpoint": bool(s.openai_base_url),
        "model": s.openai_model,
        "chosen_model": store.get_defaults(conn)["model"],  # the default chosen in Settings, over `model`
        "title_model": s.title_model_for(store.get_defaults(conn)["model"] or s.openai_model),
        "web_search": bool(s.brave_api_key),
        "tools": [t.label for t in request.app.state.tools.values()],
        "compaction": s.compaction_enabled,
        "compact_threshold": s.compact_threshold,
        "history_tokens": s.history_tokens,
        "max_tool_calls": s.max_tool_calls,
        "max_output_tokens": s.openai_max_output_tokens,
        "pdf_input": s.openai_pdf_input,
        "reasoning_summaries": s.openai_reasoning_summaries,
        "log_level": s.log_level.upper(),
        "database": s.db_path,
        "attachments": s.attachments_dir,
        "default_instructions": s.default_system_prompt,
    }


@router.get("/storage")
def storage_overview(request: Request, conn: Conn):
    s = request.app.state.settings
    return storage.overview(conn, s.db_path, s.attachments_dir)


@router.post("/storage/clear-unused")
def clear_unused(request: Request, conn: Conn):
    """Delete files that nothing uses: uploads never sent with a message, and files no row names."""
    return storage.clear_unused(conn, request.app.state.settings.attachments_dir)


Days = Annotated[int, Query(ge=1, le=3650)]


@router.get("/storage/archived")
def archived_count(days: Days, conn: Conn):
    """How many archived chats have been untouched for `days` days: what the delete below would remove."""
    return {"count": storage.count_archived(conn, days)}


@router.delete("/storage/archived")
def delete_archived(days: Days, request: Request, conn: Conn):
    ids = storage.delete_archived(conn, request.app.state.settings.attachments_dir, days)
    return {"deleted": len(ids), "ids": ids}


@router.get("/attachments/limits")
def attachment_limits():
    return {"max_files": attachments.MAX_FILES}


@router.post("/attachments", status_code=201)
async def upload_attachment(file: UploadFile, request: Request, conn: Conn):
    """Store an upload and say what it is; it is sent later, by id, with a chat message."""
    settings = request.app.state.settings
    # Over the limit by one byte, so it can be seen to be over: what a client claims the size is says nothing.
    data = await file.read(max(attachments.LIMITS.values()) + 1)
    aid = uuid.uuid4().hex
    try:
        kind, mime = attachments.classify(data)
        attachments.save(settings.attachments_dir, aid, data)
        if kind == "pdf" and settings.openai_pdf_input == "text":
            attachments.pdf_text(settings.attachments_dir, aid)  # fail now if there is nothing to read
    except attachments.Rejected as e:
        attachments.delete_files(settings.attachments_dir, [aid])
        raise HTTPException(e.status, e.message) from e
    try:
        row = store.add_attachment(conn, aid, attachments.safe_name(file.filename), mime, kind, len(data))
    except BaseException:  # no row and no message pointing at the file: it would be one nothing ever deletes
        attachments.delete_files(settings.attachments_dir, [aid])
        raise
    return {k: row[k] for k in store.ATTACHMENT_FIELDS}


@router.get("/attachments/{aid}")
def get_attachment(aid: str, request: Request, conn: Conn):
    """Images show inline; everything else downloads. Served as the type we detected, never what was uploaded
    as, and sandboxed, so an uploaded file can't run script on this origin."""
    row = store.get_attachment(conn, aid)
    file = attachments.path(request.app.state.settings.attachments_dir, aid)
    if not row or not file.exists():
        raise HTTPException(404, "attachment not found")
    return FileResponse(
        file,
        media_type="text/plain; charset=utf-8" if row["kind"] == "text" else row["mime"],
        filename=row["name"],
        content_disposition_type="inline" if row["kind"] == "image" else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
    )


@router.get("/custom-instructions")
def get_custom_instructions(conn: Conn):
    return {"text": store.get_app_setting(conn, "custom_instructions")}


@router.put("/custom-instructions")
def put_custom_instructions(body: CustomInstructions, conn: Conn):
    store.set_app_setting(conn, "custom_instructions", body.text)
    return {"text": body.text}


@router.delete("/conversations/{cid}", status_code=204)
def delete_conversation(cid: str, request: Request, conn: Conn):
    _require(conn, cid)
    files = store.attachment_ids(conn, cid)
    store.delete_conversation(conn, cid)  # the attachment rows go with it (ON DELETE CASCADE)
    attachments.delete_files(request.app.state.settings.attachments_dir, files)


def _history(request: Request, conn: sqlite3.Connection, cid: str, loaded: list[dict] | None = None) -> list[dict]:
    """The conversation as llm.py takes it. Calls are stateless, so the files of the newest message that has any
    go again with every turn; those of older messages are replaced by a note (see docs/round-3.md). `loaded` is the
    path as it was read by the caller, so it is not read again for nothing."""
    settings = request.app.state.settings
    messages = loaded if loaded is not None else store.list_messages(conn, cid)
    head = []
    # The latest compaction stands for the turns before it (see docs/phase-8.md); the messages stay in the
    # database and the UI, but they are no longer sent. `after_reply`: it also covers the message it is saved on.
    for i, m in reversed(list(enumerate(messages))):
        if (c := m["meta"].get("compaction")) and settings.compaction_enabled:
            head, messages = [{"compaction": c["item"]}], messages[i + 1 if c["after_reply"] else i :]
            break
    history = head
    newest = max((i for i, m in enumerate(messages) if m["meta"].get("attachments")), default=-1)
    for i, m in enumerate(messages):
        item = {"role": m["role"], "content": m["content"]}
        if m["meta"].get("attachments"):
            item["attachments"] = [
                attachments.for_model(a, settings.attachments_dir, settings.openai_pdf_input) if i == newest
                else attachments.superseded(a)
                for a in m["meta"]["attachments"]
            ]
        history.append(item)
    return history


def _model_options(request: Request, conn: sqlite3.Connection, conv: dict, model: str) -> dict:
    """Keyword arguments for llm.stream_reply: instructions are the default prompt, custom instructions, the
    conversation's system prompt and the enabled tools' guidance, in that order (the stable part first)."""
    s = conv["settings"]
    # A saved setting for a tool that is not configured (right now) is ignored, not an error.
    enabled = {n: tools.bound_to(request.app.state.tools[n], conv["id"])
               for n in s["tools"] if n in request.app.state.tools}
    guidance = [t.guidance for t in enabled.values()]
    base = request.app.state.settings.default_system_prompt.replace("{date}", date.today().isoformat())
    parts = [base, store.get_app_setting(conn, "custom_instructions"), s["system_prompt"], *guidance]
    options: dict[str, Any] = {"instructions": "\n\n".join(filter(None, parts)) or None}
    if enabled:
        options["tools"] = enabled
        options["max_tool_calls"] = request.app.state.settings.max_tool_calls
    if supports_reasoning(model):
        options["reasoning_effort"] = s["reasoning_effort"] or store.get_defaults(conn)["reasoning_effort"]
    else:
        options["temperature"] = s["temperature"]
    return options


@dataclass
class Turn:
    """Everything needed to stream one reply. Built by a dependency, so a missing conversation or a
    bad request is a normal HTTP error: once a generator endpoint starts streaming, it is too late."""

    conn: sqlite3.Connection
    llm: Any
    title_model: str
    conv: dict
    history: list[dict]  # ends with the user message being answered
    reply_to: int  # that message's id: the reply is saved as its child
    model: str
    options: dict
    trimmed: int = 0  # how many older messages were left out to fit the model's context, see context.py


def _make_turn(request: Request, conn: sqlite3.Connection, conv: dict, history: list[dict], reply_to: int,
               model: str | None = None):
    settings = request.app.state.settings
    default = store.get_defaults(conn)["model"] or settings.openai_model
    chosen: str = model or conv["settings"]["model"] or default
    options = _model_options(request, conn, conv, chosen)
    trimmed = 0
    if settings.history_tokens:  # room for the instructions and the reply, then as much history as fits
        instructions = context.estimate({"content": options.get("instructions")})
        reserve = instructions + (settings.openai_max_output_tokens or 2_000)
        history, trimmed = context.fit(history, settings.history_tokens - reserve)
    title_model = settings.title_model_for(default)
    return Turn(conn, request.app.state.llm, title_model, conv, history, reply_to, chosen, options, trimmed)


def _last_user(path: list[dict]) -> dict | None:
    return next((m for m in reversed(path) if m["role"] == "user"), None)


def chat_turn(cid: str, req: ChatRequest, request: Request, conn: Conn) -> Turn:
    conv = _require(conn, cid)
    files = store.pending_attachments(conn, req.attachments)
    if len(files) != len(req.attachments):
        raise HTTPException(422, "An attachment is unknown or was already sent. Attach the file again.")
    meta = {"attachments": [{k: f[k] for k in store.ATTACHMENT_FIELDS} for f in files]} if files else None
    user = store.add_message(conn, cid, "user", req.content, meta)
    store.link_attachments(conn, cid, req.attachments)
    return _make_turn(request, conn, conv, _history(request, conn, cid), user["id"], req.model)


def regenerate_turn(cid: str, request: Request, conn: Conn, req: RegenerateRequest | None = None) -> Turn:
    """A new reply to the last user message. The reply there was (if any) stays, as another version of it."""
    conv = _require(conn, cid)
    path = store.list_messages(conn, cid)
    user = _last_user(path)
    if not user:
        raise HTTPException(409, "no user message to reply to")
    # The path now ends at the message being answered, so the reply it replaces is not part of the history. (It
    # stays in the conversation as another version; see docs/branching.md.)
    answered = path[: path.index(user) + 1]
    store.set_leaf(conn, cid, user["id"])
    return _make_turn(request, conn, conv, _history(request, conn, cid, answered), user["id"],
                      req.model if req else None)


def edit_turn(cid: str, req: EditRequest, request: Request, conn: Conn) -> Turn:
    """Rewrite a user message as a new version of it (same place, same attachments) and reply to that. What came
    after the old version stays with it."""
    conv = _require(conn, cid)
    path = store.list_messages(conn, cid)
    if req.message_id is None:
        target = _last_user(path)
        if not target:
            raise HTTPException(409, "no user message to reply to")
    else:
        target = next((m for m in path if m["id"] == req.message_id and m["role"] == "user"), None)
        if not target:
            raise HTTPException(404, "that is not a user message of this conversation")
    files = target["meta"].get("attachments")
    user = store.add_message(conn, cid, "user", req.content, {"attachments": files} if files else None,
                             parent_id=target["parent_id"])
    # The path shown now ends at that new version, so the history is the old path up to where it was replaced,
    # with the new message where the old one was (it has the same attachments and the same parent).
    index = path.index(target)
    return _make_turn(request, conn, conv, _history(request, conn, cid, [*path[:index], user]), user["id"],
                      req.model)


def _tool_meta(calls: dict[str, dict], interrupted: str | None = None) -> list[dict]:
    """What a message keeps about the tools it called, for the UI to show again later."""
    keep = ("id", "name", "arguments", "status", "display", "error")
    metas = []
    for call in calls.values():
        meta = {k: call[k] for k in keep if k in call}
        if interrupted and call["status"] == "running":
            meta["status"] = interrupted
        metas.append(meta)
    return metas


async def _stream_turn(turn: Turn) -> AsyncIterator[dict]:
    """Stream the reply to turn.history and save it.

    Yields the events from llm.py, plus {"type": "title", "title": ...} after "done" when the
    conversation still has its default title. A reply that errors is not saved; a reply cut
    short by the client hanging up (Stop) is saved with meta {"stopped": true}; a reply cut short by something
    breaking is not saved, because that is not something the reader asked for. The message's meta also keeps the
    reasoning summary and token usage when there are any. A reply is saved as a child of the user message it answers
    (`turn.reply_to`), which is how an edit or a regeneration becomes another version.
    """
    cid, conn = turn.conv["id"], turn.conn
    needs_title = turn.conv["title"] == store.DEFAULT_TITLE
    reply, reasoning, tool_calls, compaction, finished = [], [], {}, None, False
    outcome, usage, started = "stopped", {}, time.monotonic()
    stopped_by_client = False
    try:
        if turn.trimmed:
            yield {"type": "context_trimmed", "count": turn.trimmed}
        async for event in turn.llm.stream_reply(turn.model, turn.history, **turn.options):
            if event["type"] == "delta":
                reply.append(event["text"])
            elif event["type"] == "reasoning_delta":
                reasoning.append(event["text"])
            elif event["type"] == "tool_call":
                tool_calls[event["id"]] = event  # the last event for an id is its outcome
            elif event["type"] == "compaction":
                compaction = event  # kept for the next turns; the browser only hears that it happened
                event = {"type": "compaction", "after_reply": event["after_reply"]}
            elif event["type"] == "done":
                text = "".join(reply)
                meta = {"model": turn.model, **{k: event[k] for k in ("incomplete", "usage") if k in event}}
                if reasoning:
                    meta["reasoning"] = "".join(reasoning)
                if tool_calls:
                    meta["tools"] = _tool_meta(tool_calls)
                if turn.trimmed:
                    meta["trimmed"] = turn.trimmed
                if compaction:
                    meta["compaction"] = {"item": compaction["item"], "after_reply": compaction["after_reply"]}
                saved = store.add_message(conn, cid, "assistant", text, meta, parent_id=turn.reply_to)
                finished, outcome, usage = True, "done", event.get("usage") or {}
                # Where the two messages now stand among their versions, so the page can offer "2 / 3" on them
                # without loading the conversation again.
                yield {**event, "model": turn.model, "branch": {
                    "user": {"id": turn.reply_to, "siblings": store.siblings_of(conn, cid, turn.reply_to)},
                    "assistant": {"id": saved["id"], "siblings": store.siblings_of(conn, cid, saved["id"])}}}
                if needs_title:
                    last = turn.history[-1]
                    asked = last["content"] or ", ".join(a["name"] for a in last.get("attachments", []))
                    title = await turn.llm.generate_title(turn.title_model, asked, text) or asked[:40]
                    store.rename_conversation(conn, cid, title)
                    yield {"type": "title", "title": title}
                return
            elif event["type"] == "error":
                finished, outcome = True, "error"
            yield event
    except (asyncio.CancelledError, GeneratorExit):
        stopped_by_client = True  # the client hung up: that is Stop, and what it saw is worth keeping
        raise
    except Exception:
        logger.exception("reply failed: conversation %s, model %s", cid, turn.model)
        outcome = "error"  # something broke, which is not Stop: nothing is saved, so a retry starts clean
        raise
    finally:
        logger.info("reply %s: conversation %s, model %s, %d tool calls, %s tokens in, %s out, %.1f s", outcome, cid,
                    turn.model, len(tool_calls), usage.get("input_tokens", "?"), usage.get("output_tokens", "?"),
                    time.monotonic() - started)
        if stopped_by_client and not finished and reply:
            meta = {"stopped": True, "model": turn.model, **({"reasoning": "".join(reasoning)} if reasoning else {})}
            if turn.trimmed:
                meta["trimmed"] = turn.trimmed
            if tool_calls:
                meta["tools"] = _tool_meta(tool_calls, interrupted="stopped")
            store.add_message(conn, cid, "assistant", "".join(reply), meta, parent_id=turn.reply_to)


# Server-sent events over POST: FastAPI frames each yielded dict as `data: {json}` and adds keepalive pings.
@router.post("/conversations/{cid}/chat", response_class=EventSourceResponse)
async def chat(turn: Annotated[Turn, Depends(chat_turn)]) -> AsyncIterator[dict]:
    async for event in _stream_turn(turn):
        yield event


@router.post("/conversations/{cid}/regenerate", response_class=EventSourceResponse)
async def regenerate(turn: Annotated[Turn, Depends(regenerate_turn)]) -> AsyncIterator[dict]:
    """New reply to the last user message. Also serves as retry after a failed or stopped reply."""
    async for event in _stream_turn(turn):
        yield event


@router.post("/conversations/{cid}/edit", response_class=EventSourceResponse)
async def edit(turn: Annotated[Turn, Depends(edit_turn)]) -> AsyncIterator[dict]:
    """Rewrite a user message as a new version of it and get a new reply to that. What came after the old version
    stays with it, so the old path is still there to show again (see docs/branching.md)."""
    async for event in _stream_turn(turn):
        yield event
