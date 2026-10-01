import json
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    model: str | None = None


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    model = req.model or request.app.state.settings.default_model
    messages = [m.model_dump() for m in req.messages]

    async def body():
        async for event in request.app.state.llm.stream_reply(model, messages):
            yield sse(event)

    return StreamingResponse(body(), media_type="text/event-stream")
