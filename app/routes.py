import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app import db, store
from app.llm import supports_reasoning

router = APIRouter(prefix="/api")

# Strip on the way in, so whitespace alone is neither a message nor a title.
Content = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100_000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Instructions = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10_000)]  # may be empty = unset


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(request.app.state.settings.db_path)) as conn:
        yield conn


Conn = Annotated[sqlite3.Connection, Depends(get_db)]


class ConversationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    system_prompt: Instructions = ""
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    temperature: Annotated[float, Field(ge=0, le=2)] | None = None


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


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


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
    return {"default": default, "models": [{"id": m, "reasoning": supports_reasoning(m)} for m in ids]}


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


def _stream_turn(
    request: Request, conn: sqlite3.Connection, conv: dict, history: list[dict], model: str | None = None
) -> StreamingResponse:
    """Stream a reply to `history` (which ends with a user message) and save it.

    Emits SSE events from llm.py, plus {"type": "title", "title": ...} after "done" when the
    conversation still has its default title. A reply that errors is not saved; a reply cut
    short (client disconnect = Stop) is saved with meta {"stopped": true}.
    """
    cid = conv["id"]
    default_model = request.app.state.settings.openai_model
    model = model or conv["settings"]["model"] or default_model
    options = _model_options(conn, conv, model)
    needs_title = conv["title"] == store.DEFAULT_TITLE
    llm = request.app.state.llm
    db_path = request.app.state.settings.db_path

    async def body():
        reply, finished = [], False
        # Own connection: the dependency's one may be closed before the stream finishes.
        with closing(db.connect(db_path)) as conn:
            try:
                async for event in llm.stream_reply(model, history, **options):
                    if event["type"] == "delta":
                        reply.append(event["text"])
                    elif event["type"] == "done":
                        text = "".join(reply)
                        meta = {"incomplete": event["incomplete"]} if "incomplete" in event else None
                        store.add_message(conn, cid, "assistant", text, meta)
                        finished = True
                        yield sse(event)
                        if needs_title:
                            asked = history[-1]["content"]
                            title = await llm.generate_title(default_model, asked, text) or asked[:40]
                            store.rename_conversation(conn, cid, title)
                            yield sse({"type": "title", "title": title})
                        return
                    elif event["type"] == "error":
                        finished = True
                    yield sse(event)
            finally:
                if not finished and reply:
                    store.add_message(conn, cid, "assistant", "".join(reply), {"stopped": True})

    return StreamingResponse(body(), media_type="text/event-stream")


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


@router.post("/conversations/{cid}/chat")
async def chat(cid: str, req: ChatRequest, request: Request, conn: Conn):
    conv = _require(conn, cid)
    store.add_message(conn, cid, "user", req.content)
    return _stream_turn(request, conn, conv, _history(conn, cid), req.model)


@router.post("/conversations/{cid}/regenerate")
async def regenerate(cid: str, request: Request, conn: Conn):
    """New reply to the last user message. Also serves as retry after a failed or stopped reply."""
    conv, history = _redo_last_user_turn(conn, cid)
    return _stream_turn(request, conn, conv, history)


@router.post("/conversations/{cid}/edit")
async def edit(cid: str, req: EditRequest, request: Request, conn: Conn):
    """Rewrite the last user message and get a new reply (no branching: later messages are dropped)."""
    conv, history = _redo_last_user_turn(conn, cid, req.content)
    return _stream_turn(request, conn, conv, history)
