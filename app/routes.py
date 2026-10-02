import json
import re
import sqlite3
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import closing
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.sse import EventSourceResponse
from pydantic import BaseModel, Field, StringConstraints, model_validator

from app import attachments, db, store
from app.llm import REASONING_EFFORTS, supports_reasoning
from app.store import ConversationSettings, Instructions

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

    @model_validator(mode="after")
    def _something_to_change(self):
        if self.title is None and self.settings is None:
            raise ValueError("send a title, settings, or both")
        return self


class NewConversation(BaseModel):
    settings: ConversationSettings | None = None


class CustomInstructions(BaseModel):
    text: Instructions


class EditRequest(BaseModel):
    content: Content


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
def list_conversations(conn: Conn):
    return store.list_conversations(conn)


@router.post("/conversations", status_code=201)
def create_conversation(conn: Conn, body: NewConversation | None = None):
    settings = body.settings.model_dump() if body and body.settings else None
    return store.create_conversation(conn, settings=settings)


def _public(m: dict) -> dict:
    """A message for the browser or an export: OpenAI's encrypted compaction item is only for the model."""
    c = m["meta"].get("compaction")
    return {**m, "meta": {**m["meta"], "compaction": {"after_reply": c["after_reply"]}}} if c else m


@router.get("/conversations/{cid}")
def get_conversation(cid: str, conn: Conn):
    conv = _require(conn, cid)
    return {**conv, "messages": [_public(m) for m in store.list_messages(conn, cid)]}


@router.get("/search")
def search(q: Annotated[str, Query(min_length=1, max_length=200)], conn: Conn):
    """Conversations whose messages match; `snippet` marks the matched words with STX/ETX characters."""
    return store.search_conversations(conn, q)


def _markdown(conv: dict, messages: list[dict]) -> str:
    parts = [f"# {conv['title']}"]
    for m in messages:
        parts.append("## " + ("You" if m["role"] == "user" else "Assistant"))
        if files := m["meta"].get("attachments"):
            parts.append("*Attached: " + ", ".join(a["name"] for a in files) + "*")
        parts.append(m["content"])
    return "\n\n".join(parts) + "\n"


@router.get("/conversations/{cid}/export")
def export_conversation(cid: str, conn: Conn, format: Literal["md", "json"] = "md"):
    """The conversation as a Markdown or JSON download. Attachments are listed by name, not included."""
    conv = _require(conn, cid)
    messages = [_public(m) for m in store.list_messages(conn, cid)]
    if format == "md":
        body, media_type = _markdown(conv, messages), "text/markdown"
    else:
        body, media_type = json.dumps({**conv, "messages": messages}, indent=2, ensure_ascii=False), "application/json"
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", conv["title"]).strip("-") or "chat"
    return Response(
        body, media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.{format}"'},
    )


@router.patch("/conversations/{cid}")
def update_conversation(cid: str, body: ConversationUpdate, conn: Conn):
    """Rename and/or replace the conversation's settings."""
    _require(conn, cid)
    if body.title is not None:
        store.rename_conversation(conn, cid, body.title)
    if body.settings is not None:
        store.update_conversation_settings(conn, cid, body.settings.model_dump())
    return store.get_conversation(conn, cid)


@router.get("/models")
async def list_models(request: Request):
    """Models to offer in the picker: the configured default first, then whatever the endpoint lists."""
    default = request.app.state.settings.openai_model
    ids = [default] + [m for m in await request.app.state.llm.list_models() if m != default]
    return {
        "default": default,
        "efforts": REASONING_EFFORTS,
        "models": [{"id": m, "reasoning": supports_reasoning(m)} for m in ids],
    }


@router.get("/tools")
def list_tools(request: Request):
    """The tools that can be switched on for a conversation (those that are configured)."""
    return [{"name": t.name, "label": t.label} for t in request.app.state.tools.values()]


@router.get("/attachments/limits")
def attachment_limits():
    return {"max_files": attachments.MAX_FILES}


@router.post("/attachments", status_code=201)
async def upload_attachment(file: UploadFile, request: Request, conn: Conn):
    """Store an upload and say what it is; it is sent later, by id, with a chat message."""
    settings = request.app.state.settings
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
    name = (file.filename or "attachment").replace("\\", "/").rsplit("/", 1)[-1].strip()[:200] or "attachment"
    row = store.add_attachment(conn, aid, name, mime, kind, len(data))
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


def _history(request: Request, conn: sqlite3.Connection, cid: str) -> list[dict]:
    """The conversation as llm.py takes it. Earlier attachments are sent again each turn: calls are stateless."""
    settings = request.app.state.settings
    messages = store.list_messages(conn, cid)
    head = []
    # The latest compaction stands for the turns before it (see docs/phase-8.md); the messages stay in the
    # database and the UI, but they are no longer sent. `after_reply`: it also covers the message it is saved on.
    for i, m in reversed(list(enumerate(messages))):
        if c := m["meta"].get("compaction"):
            head, messages = [{"compaction": c["item"]}], messages[i + 1 if c["after_reply"] else i :]
            break
    history = head
    for m in messages:
        item = {"role": m["role"], "content": m["content"]}
        if m["meta"].get("attachments"):
            item["attachments"] = [
                attachments.for_model(a, settings.attachments_dir, settings.openai_pdf_input)
                for a in m["meta"]["attachments"]
            ]
        history.append(item)
    return history


def _model_options(request: Request, conn: sqlite3.Connection, conv: dict, model: str) -> dict:
    """Keyword arguments for llm.stream_reply from custom instructions + the conversation's settings."""
    s = conv["settings"]
    # A saved setting for a tool that is not configured (right now) is ignored, not an error.
    enabled = {n: request.app.state.tools[n] for n in s["tools"] if n in request.app.state.tools}
    guidance = [t.guidance for t in enabled.values()]
    parts = [store.get_app_setting(conn, "custom_instructions"), s["system_prompt"], *guidance]
    options = {"instructions": "\n\n".join(filter(None, parts)) or None}
    if enabled:
        options["tools"] = enabled
        options["max_tool_calls"] = request.app.state.settings.max_tool_calls
    if supports_reasoning(model):
        options["reasoning_effort"] = s["reasoning_effort"]
    else:
        options["temperature"] = s["temperature"]
    return options


@dataclass
class Turn:
    """Everything needed to stream one reply. Built by a dependency, so a missing conversation or a
    bad request is a normal HTTP error: once a generator endpoint starts streaming, it is too late."""

    conn: sqlite3.Connection
    llm: Any
    default_model: str
    conv: dict
    history: list[dict]  # ends with the user message being answered
    model: str
    options: dict


def _make_turn(request: Request, conn: sqlite3.Connection, conv: dict, history: list[dict], model: str | None = None):
    default_model = request.app.state.settings.openai_model
    model = model or conv["settings"]["model"] or default_model
    return Turn(
        conn, request.app.state.llm, default_model, conv, history, model, _model_options(request, conn, conv, model)
    )


def _redo_last_user_turn(
    request: Request, conn: sqlite3.Connection, cid: str, content: str | None = None
) -> tuple[dict, list[dict]]:
    """Drop everything after the last user message (optionally rewriting it); return (conv, history)."""
    conv = _require(conn, cid)
    last = store.last_user_message(conn, cid)
    if not last:
        raise HTTPException(409, "no user message to reply to")
    if content is not None:
        store.update_message_content(conn, last["id"], content)
    store.delete_messages_after(conn, cid, last["id"])
    return conv, _history(request, conn, cid)


def chat_turn(cid: str, req: ChatRequest, request: Request, conn: Conn) -> Turn:
    conv = _require(conn, cid)
    files = store.pending_attachments(conn, req.attachments)
    if len(files) != len(req.attachments):
        raise HTTPException(422, "An attachment is unknown or was already sent. Attach the file again.")
    meta = {"attachments": [{k: f[k] for k in store.ATTACHMENT_FIELDS} for f in files]} if files else None
    store.add_message(conn, cid, "user", req.content, meta)
    store.link_attachments(conn, cid, req.attachments)
    return _make_turn(request, conn, conv, _history(request, conn, cid), req.model)


def regenerate_turn(cid: str, request: Request, conn: Conn) -> Turn:
    conv, history = _redo_last_user_turn(request, conn, cid)
    return _make_turn(request, conn, conv, history)


def edit_turn(cid: str, req: EditRequest, request: Request, conn: Conn) -> Turn:
    conv, history = _redo_last_user_turn(request, conn, cid, req.content)
    return _make_turn(request, conn, conv, history)


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
    short (client disconnect = Stop) is saved with meta {"stopped": true}. The message's meta also
    keeps the reasoning summary and token usage when there are any.
    """
    cid, conn = turn.conv["id"], turn.conn
    needs_title = turn.conv["title"] == store.DEFAULT_TITLE
    reply, reasoning, tool_calls, compaction, finished = [], [], {}, None, False
    try:
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
                meta = {k: event[k] for k in ("incomplete", "usage") if k in event}
                if reasoning:
                    meta["reasoning"] = "".join(reasoning)
                if tool_calls:
                    meta["tools"] = _tool_meta(tool_calls)
                if compaction:
                    meta["compaction"] = {"item": compaction["item"], "after_reply": compaction["after_reply"]}
                store.add_message(conn, cid, "assistant", text, meta)
                finished = True
                yield event
                if needs_title:
                    last = turn.history[-1]
                    asked = last["content"] or ", ".join(a["name"] for a in last.get("attachments", []))
                    title = await turn.llm.generate_title(turn.default_model, asked, text) or asked[:40]
                    store.rename_conversation(conn, cid, title)
                    yield {"type": "title", "title": title}
                return
            elif event["type"] == "error":
                finished = True
            yield event
    finally:
        if not finished and reply:
            meta = {"stopped": True, **({"reasoning": "".join(reasoning)} if reasoning else {})}
            if tool_calls:
                meta["tools"] = _tool_meta(tool_calls, interrupted="stopped")
            store.add_message(conn, cid, "assistant", "".join(reply), meta)


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
    """Rewrite the last user message and get a new reply (no branching: later messages are dropped)."""
    async for event in _stream_turn(turn):
        yield event
