"""The only module that imports openai. Normalizes SDK stream events into ours:

    {"type": "delta", "text": str}
    {"type": "reasoning_delta", "text": str}          # streamed reasoning summary
    {"type": "done"}   # plus "incomplete": reason (hit a limit) and "usage": {input_tokens, output_tokens,
                       # reasoning_tokens}, when there are any
    {"type": "error", "message": str}
"""
import asyncio
import base64
import json
import re
import typing
from collections.abc import AsyncIterator
from pathlib import Path
from xml.sax.saxutils import quoteattr

import openai
from openai import AsyncOpenAI
from openai.types.responses import ResponseInputContentParam
from openai.types.shared import ReasoningEffort

from app.config import Settings

Event = dict

# The SDK's own list of effort levels (its type is Optional[Literal[...]]). Which of them a model accepts varies.
REASONING_EFFORTS: list[str] = list(typing.get_args(typing.get_args(ReasoningEffort)[0]))

# Which models take `reasoning.effort` (and reject `temperature`) can't be asked of the API, so go by name:
# OpenAI's o-series and gpt-5 family, plus gpt-oss. Everything else is treated as a temperature model.
_REASONING = re.compile(r"^(o\d|gpt-5|gpt-oss)")


def supports_reasoning(model: str) -> bool:
    return bool(_REASONING.match(model))


def _data_url(attachment: dict) -> str:
    return f"data:{attachment['mime']};base64,{base64.b64encode(Path(attachment['path']).read_bytes()).decode()}"


def _content(message: dict) -> str | list[ResponseInputContentParam]:
    """A message's `content` for the API: plain text, or parts when it has attachments.

    attachments: [{"kind": "image" | "file", "name", "mime", "path"} | {"kind": "text", "name", "text"}]
    """
    if not message.get("attachments"):
        return message["content"]
    parts: list[ResponseInputContentParam] = []
    for a in message["attachments"]:
        match a["kind"]:
            case "image":
                parts.append({"type": "input_image", "image_url": _data_url(a)})
            case "file":
                parts.append({"type": "input_file", "filename": a["name"], "file_data": _data_url(a)})
            case _:
                name = quoteattr(a["name"])  # quoted and escaped: a file name is untrusted
                parts.append({"type": "input_text", "text": f"<file name={name}>\n{a['text']}\n</file>"})
    if message["content"]:
        parts.append({"type": "input_text", "text": message["content"]})
    return parts


def _inputs(messages: list[dict]) -> list[dict]:
    return [{"role": m["role"], "content": _content(m)} for m in messages]


def _error_message(error: openai.OpenAIError) -> str:
    """The provider's own message, without the SDK's "Error code: 400 - {...}" wrapping."""
    body = getattr(error, "body", None)  # for API errors, the provider's error object
    message = (body.get("message") if isinstance(body, dict) else None) or getattr(error, "message", None) or str(error)
    try:  # some OpenAI-compatible servers nest a whole JSON error inside the message
        message = json.loads(message)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        pass
    return message


def _usage(response) -> dict:
    """{"usage": {...}} from a finished response, or {} when the endpoint reports none."""
    u = response.usage
    if not u:
        return {}
    details = u.output_tokens_details
    return {"usage": {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "reasoning_tokens": (details.reasoning_tokens if details else 0) or 0,
    }}


class OpenAILLM:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        self.settings = settings
        self._client = client

    @property
    def client(self) -> AsyncOpenAI:
        # Lazy: the SDK raises at construction when no key is set, which would break importing the app.
        if self._client is None:
            s = self.settings
            self._client = AsyncOpenAI(
                api_key=s.openai_api_key or None, base_url=s.openai_base_url, max_retries=s.openai_max_retries
            )
        return self._client

    async def list_models(self) -> list[str]:
        """Model ids the endpoint offers, minus embedding models; [] if it can't be listed."""
        try:
            ids = [m.id async for m in self.client.models.list()]
        except openai.OpenAIError:
            return []
        return sorted(i for i in ids if "embed" not in i)

    async def stream_reply(
        self,
        model: str,
        messages: list[dict],
        instructions: str | None = None,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[Event]:
        # Only send what was set: a parameter the model doesn't know is an API error.
        extra = {}
        if instructions:
            extra["instructions"] = instructions
        reasoning = {}
        if reasoning_effort:
            reasoning["effort"] = reasoning_effort
        # Summaries are what the UI shows as "Reasoning". OpenAI refuses them for unverified organizations,
        # hence the switch; non-reasoning models would reject the whole `reasoning` parameter.
        if self.settings.openai_reasoning_summaries and supports_reasoning(model):
            reasoning["summary"] = "auto"
        if reasoning:
            extra["reasoning"] = reasoning
        if temperature is not None:
            extra["temperature"] = temperature
        try:
            stream = await self.client.responses.create(
                model=model,
                input=await asyncio.to_thread(_inputs, messages),  # reads attachment files
                store=False,
                stream=True,
                max_output_tokens=self.settings.openai_max_output_tokens,
                **extra,
            )
            part = None  # summary part index, so consecutive parts don't run together
            async for ev in stream:
                match ev.type:
                    case "response.output_text.delta":
                        yield {"type": "delta", "text": ev.delta}
                    case "response.reasoning_summary_text.delta":
                        gap = "\n\n" if part is not None and part != ev.summary_index else ""
                        part = ev.summary_index
                        yield {"type": "reasoning_delta", "text": gap + ev.delta}
                    case "response.completed":
                        yield {"type": "done", **_usage(ev.response)}
                    case "response.failed":
                        err = ev.response.error
                        yield {"type": "error", "message": err.message if err else "response failed"}
                    case "response.incomplete":
                        details = ev.response.incomplete_details
                        reason = details.reason if details else "unknown"
                        yield {"type": "done", "incomplete": reason, **_usage(ev.response)}
                    case "error":
                        yield {"type": "error", "message": ev.message}
        except openai.OpenAIError as e:
            yield {"type": "error", "message": _error_message(e)}

    async def generate_title(self, model: str, user_text: str, reply_text: str) -> str | None:
        """Short conversation title, or None on any API failure (titles are best-effort)."""
        try:
            r = await self.client.responses.create(
                model=model,
                instructions=(
                    "Write a title of at most 6 words for this chat. "
                    "Reply with the title only, no quotes or punctuation at the end."
                ),
                input=f"User: {user_text[:1000]}\n\nAssistant: {reply_text[:1000]}",
                store=False,
            )
        except openai.OpenAIError:
            return None
        return r.output_text.strip().strip("\"'").strip() or None
