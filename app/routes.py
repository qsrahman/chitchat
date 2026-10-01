import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import closing
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.sse import EventSourceResponse
from pydantic import BaseModel, StringConstraints, model_validator

from app import db, store
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


class ChatRequest(EditRequest):
    model: str | None = None


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


@router.get("/conversations/{cid}")
def get_conversation(cid: str, conn: Conn):
    conv = _require(conn, cid)
    return {**conv, "messages": store.list_messages(conn, cid)}


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


@router.get("/custom-instructions")
def get_custom_instructions(conn: Conn):
    return {"text": store.get_app_setting(conn, "custom_instructions")}


@router.put("/custom-instructions")
def put_custom_instructions(body: CustomInstructions, conn: Conn):
    store.set_app_setting(conn, "custom_instructions", body.text)
    return {"text": body.text}


@router.delete("/conversations/{cid}", status_code=204)
def delete_conversation(cid: str, conn: Conn):
    _require(conn, cid)
    store.delete_conversation(conn, cid)


def _history(conn: sqlite3.Connection, cid: str) -> list[dict]:
    return [{"role": m["role"], "content": m["content"]} for m in store.list_messages(conn, cid)]


def _model_options(conn: sqlite3.Connection, conv: dict, model: str) -> dict:
    """Keyword arguments for llm.stream_reply from custom instructions + the conversation's settings."""
    s = conv["settings"]
    instructions = "\n\n".join(filter(None, [store.get_app_setting(conn, "custom_instructions"), s["system_prompt"]]))
    options = {"instructions": instructions or None}
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
    return Turn(conn, request.app.state.llm, default_model, conv, history, model, _model_options(conn, conv, model))


def _redo_last_user_turn(conn: sqlite3.Connection, cid: str, content: str | None = None) -> tuple[dict, list[dict]]:
    """Drop everything after the last user message (optionally rewriting it); return (conv, history)."""
    conv = _require(conn, cid)
    last = store.last_user_message(conn, cid)
    if not last:
        raise HTTPException(409, "no user message to reply to")
    if content is not None:
        store.update_message_content(conn, last["id"], content)
    store.delete_messages_after(conn, cid, last["id"])
    return conv, _history(conn, cid)


def chat_turn(cid: str, req: ChatRequest, request: Request, conn: Conn) -> Turn:
    conv = _require(conn, cid)
    store.add_message(conn, cid, "user", req.content)
    return _make_turn(request, conn, conv, _history(conn, cid), req.model)


def regenerate_turn(cid: str, request: Request, conn: Conn) -> Turn:
    conv, history = _redo_last_user_turn(conn, cid)
    return _make_turn(request, conn, conv, history)


def edit_turn(cid: str, req: EditRequest, request: Request, conn: Conn) -> Turn:
    conv, history = _redo_last_user_turn(conn, cid, req.content)
    return _make_turn(request, conn, conv, history)


async def _stream_turn(turn: Turn) -> AsyncIterator[dict]:
    """Stream the reply to turn.history and save it.

    Yields the events from llm.py, plus {"type": "title", "title": ...} after "done" when the
    conversation still has its default title. A reply that errors is not saved; a reply cut
    short (client disconnect = Stop) is saved with meta {"stopped": true}.
    """
    cid, conn = turn.conv["id"], turn.conn
    needs_title = turn.conv["title"] == store.DEFAULT_TITLE
    reply, finished = [], False
    try:
        async for event in turn.llm.stream_reply(turn.model, turn.history, **turn.options):
            if event["type"] == "delta":
                reply.append(event["text"])
            elif event["type"] == "done":
                text = "".join(reply)
                meta = {"incomplete": event["incomplete"]} if "incomplete" in event else None
                store.add_message(conn, cid, "assistant", text, meta)
                finished = True
                yield event
                if needs_title:
                    asked = turn.history[-1]["content"]
                    title = await turn.llm.generate_title(turn.default_model, asked, text) or asked[:40]
                    store.rename_conversation(conn, cid, title)
                    yield {"type": "title", "title": title}
                return
            elif event["type"] == "error":
                finished = True
            yield event
    finally:
        if not finished and reply:
            store.add_message(conn, cid, "assistant", "".join(reply), {"stopped": True})


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
