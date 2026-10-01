import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import db, store

router = APIRouter(prefix="/api")


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(request.app.state.settings.db_path)) as conn:
        yield conn


Conn = Annotated[sqlite3.Connection, Depends(get_db)]


class TitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatRequest(BaseModel):
    content: str = Field(min_length=1)
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
def create_conversation(conn: Conn):
    return store.create_conversation(conn)


@router.get("/conversations/{cid}")
def get_conversation(cid: str, conn: Conn):
    conv = _require(conn, cid)
    return {**conv, "messages": store.list_messages(conn, cid)}


@router.patch("/conversations/{cid}")
def rename_conversation(cid: str, body: TitleUpdate, conn: Conn):
    _require(conn, cid)
    return store.rename_conversation(conn, cid, body.title.strip())


@router.delete("/conversations/{cid}", status_code=204)
def delete_conversation(cid: str, conn: Conn):
    _require(conn, cid)
    store.delete_conversation(conn, cid)


@router.post("/conversations/{cid}/chat")
async def chat(cid: str, req: ChatRequest, request: Request, conn: Conn):
    """Save the user message, stream the reply, save it when complete.

    Emits SSE events from llm.py, plus {"type": "title", "title": ...} after "done"
    when this was the conversation's first exchange. A failed or interrupted reply is not saved.
    """
    conv = _require(conn, cid)
    store.add_message(conn, cid, "user", req.content)
    history = [{"role": m["role"], "content": m["content"]} for m in store.list_messages(conn, cid)]
    needs_title = conv["title"] == store.DEFAULT_TITLE
    model = req.model or request.app.state.settings.default_model
    llm = request.app.state.llm
    db_path = request.app.state.settings.db_path

    async def body():
        reply = []
        # Own connection: the dependency's one may be closed before the stream finishes.
        with closing(db.connect(db_path)) as conn:
            async for event in llm.stream_reply(model, history):
                if event["type"] == "delta":
                    reply.append(event["text"])
                elif event["type"] == "done":
                    text = "".join(reply)
                    store.add_message(conn, cid, "assistant", text)
                    yield sse(event)
                    if needs_title:
                        title = await llm.generate_title(model, req.content, text) or req.content[:40]
                        store.rename_conversation(conn, cid, title)
                        yield sse({"type": "title", "title": title})
                    return
                yield sse(event)

    return StreamingResponse(body(), media_type="text/event-stream")
