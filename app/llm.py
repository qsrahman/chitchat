"""The only module that imports openai. Normalizes SDK stream events into ours:

    {"type": "delta", "text": str}
    {"type": "reasoning_delta", "text": str}          # streamed reasoning summary
    {"type": "tool_call", "id", "name", "arguments", "status": "running" | "done" | "error",
        "display": {...} | "error": str}              # a tool the model called, see app/tools/
    {"type": "compaction", "item": {...}, "after_reply": bool}   # just before "done": OpenAI compacted the context,
                       # see docs/phase-8.md. `after_reply`: the item also covers this reply's text.
    {"type": "done"}   # plus "incomplete": reason (hit a limit) and "usage": {input_tokens, output_tokens,
                       # reasoning_tokens}, when there are any
    {"type": "error", "message": str}
"""
import asyncio
import base64
import json
import logging
import re
import time
import typing
from collections.abc import AsyncIterator
from pathlib import Path
from xml.sax.saxutils import quoteattr

import openai
from openai import AsyncOpenAI
from openai.types.responses import ResponseInputContentParam
from openai.types.shared import ReasoningEffort

from app.config import Settings
from app.tools import Tool, ToolError

MODELS_TTL = 300  # seconds to keep the model list
logger = logging.getLogger(__name__)

# The SDK's own list of effort levels (its type is Optional[Literal[...]]). Which of them a model accepts varies.
REASONING_EFFORTS: list[str] = list(typing.get_args(typing.get_args(ReasoningEffort)[0]))

# Which models take `reasoning.effort` (and reject `temperature`) can't be asked of the API, so go by name:
# OpenAI's o-series and gpt-5 and later, plus gpt-oss. Everything else is treated as a temperature model.
_REASONING = re.compile(r"^(o\d|gpt-[5-9]|gpt-oss)")

# What GET /models lists but a text chat can't use, as OpenAI names it: embeddings, moderation, speech and
# audio, image and video generation, completion-only models and search-only models. The word rules match whole
# hyphen-separated words, and "instruct" is only matched for OpenAI's own model, so a local model such as
# "llama3-instruct" or "llama3.2-vision" is left alone.
_NOT_CHAT = re.compile(
    r"embed|moderation|^(babbage|davinci)|^gpt-3\.5-turbo-instruct"
    r"|(^|-)(tts|whisper|transcribe|diarize|realtime|audio|live|image|sora)(-|$)"
    r"|search-(preview|api)"
)
# "gpt-4o-2024-08-06" is a dated copy of "gpt-4o"; it is hidden when the alias is listed too.
_SNAPSHOT = re.compile(r"^(?P<alias>.+)-(?:\d{4}-\d{2}-\d{2}|\d{4})$")


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
                parts.append({"type": "input_image", "image_url": _data_url(a), "detail": "auto"})
            case "file":
                parts.append({"type": "input_file", "filename": a["name"], "file_data": _data_url(a)})
            case _:
                name = quoteattr(a["name"])  # quoted and escaped: a file name is untrusted
                parts.append({"type": "input_text", "text": f"<file name={name}>\n{a['text']}\n</file>"})
    if message["content"]:
        parts.append({"type": "input_text", "text": message["content"]})
    return parts


def _inputs(messages: list[dict]) -> list[typing.Any]:
    # A {"compaction": item} entry stands for every earlier turn: it is sent as the item OpenAI gave us.
    return [m["compaction"] if "compaction" in m else {"role": m["role"], "content": _content(m)} for m in messages]


def _error_message(error: openai.OpenAIError) -> str:
    """The provider's own message, without the SDK's "Error code: 400 - {...}" wrapping."""
    body = getattr(error, "body", None)  # for API errors, the provider's error object
    message = (body.get("message") if isinstance(body, dict) else None) or getattr(error, "message", None) or str(error)
    try:  # some OpenAI-compatible servers nest a whole JSON error inside the message
        message = json.loads(message)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        pass
    return message


def _usage(response) -> dict | None:
    """Token counts from a finished response, or None when the endpoint reports none."""
    u = response.usage
    if not u:
        return None
    details = u.output_tokens_details
    return {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "reasoning_tokens": (details.reasoning_tokens if details else 0) or 0,
    }


def _add_usage(total: dict | None, more: dict | None) -> dict | None:
    """Token counts summed over the rounds of one reply."""
    if not more:
        return total
    return {k: (total or {}).get(k, 0) + v for k, v in more.items()}


def _loads(arguments: str | None) -> dict:
    """The arguments of a function call for display; {} if the model sent something unusable."""
    try:
        parsed = json.loads(arguments or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_spec(tool: Tool) -> dict:
    return {"type": "function", "name": tool.name, "description": tool.description,
            "parameters": tool.parameters, "strict": True}


async def _run_tool(call, tools: dict[str, Tool], allowed: bool) -> tuple[str, dict]:
    """Run one function call. Returns (the text for the model, fields for the UI's tool_call event).

    A tool that fails must not fail the reply: the model is told, and may try something else.
    """
    tool = tools.get(call.name)
    try:
        arguments = json.loads(call.arguments or "{}")
        if not isinstance(arguments, dict):
            raise ValueError
    except ValueError:
        return "Error: the arguments were not a valid JSON object.", {"status": "error", "error": "Bad arguments."}
    fields = {"arguments": arguments}
    if tool is None:
        return f"Error: there is no tool called {call.name}.", {**fields, "status": "error", "error": "Unknown tool."}
    if not allowed:
        return ("Error: the tool call limit for this reply was reached. Answer with what you have.",
                {**fields, "status": "error", "error": "Tool call limit reached."})
    started = time.monotonic()
    try:
        result = await tool.run(arguments)
    except ToolError as e:
        # Not the message: it may quote a URL, and a URL can carry a token.
        logger.info("tool %s: error (%.0f ms)", call.name, (time.monotonic() - started) * 1000)
        return f"Error: {e}", {**fields, "status": "error", "error": str(e)}
    except Exception:  # tools are extension points: whatever one raises, the reply carries on
        logger.exception("tool %s failed", call.name)
        return "Error: the tool failed.", {**fields, "status": "error", "error": "The tool failed unexpectedly."}
    logger.info("tool %s: done (%.0f ms)", call.name, (time.monotonic() - started) * 1000)
    return result.output, {**fields, "status": "done", "display": result.display}


class OpenAILLM:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        self.settings = settings
        self._client = client
        self._models: tuple[float, list[str]] | None = None  # (when fetched, ids): see list_models
        self._listing = asyncio.Lock()  # so a page that opens several pickers makes one call, not one each

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
        """Chat models the endpoint offers, newest first; [] if it can't be listed. Remembered for MODELS_TTL
        seconds, since it is a remote call made whenever the page or the picker asks; a failure is not remembered."""
        if self._models and time.monotonic() - self._models[0] < MODELS_TTL:
            return self._models[1]
        async with self._listing:
            # Another caller may have fetched it while this one waited for its turn: the cache is checked again.
            if self._models and time.monotonic() - self._models[0] < MODELS_TTL:
                return self._models[1]
            try:
                models = [m async for m in self.client.models.list()]
            except openai.OpenAIError:
                return []
            listed = {m.id for m in models}

            def wanted(model) -> bool:
                snapshot = _SNAPSHOT.match(model.id)
                return not _NOT_CHAT.search(model.id) and not (snapshot and snapshot["alias"] in listed)

            ids = [m.id for m in sorted(filter(wanted, models),
                                        key=lambda m: (-(getattr(m, "created", 0) or 0), m.id))]
            self._models = (time.monotonic(), ids)
            return ids

    async def stream_reply(
        self,
        model: str,
        messages: list[dict],
        instructions: str | None = None,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        tools: dict[str, Tool] | None = None,
        max_tool_calls: int | None = None,
    ) -> AsyncIterator[dict]:
        """Stream a reply. With `tools`, loops: each round the model may call tools, whose results go back to it,
        until it answers. At most `max_tool_calls` calls run per reply (the server's limit unless one is passed);
        the loop is also bounded in rounds."""
        if max_tool_calls is None:
            max_tool_calls = self.settings.max_tool_calls
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
        if tools:
            extra["tools"] = [_tool_spec(t) for t in tools.values()]
            if supports_reasoning(model):  # calls are stateless, so reasoning items travel back to the model
                extra["include"] = ["reasoning.encrypted_content"]
        if self.settings.compaction_enabled:
            extra["context_management"] = [{"type": "compaction", "compact_threshold": self.settings.compact_threshold}]
        try:
            items = await asyncio.to_thread(_inputs, messages)  # reads attachment files
            usage, calls_run, break_before_text = None, 0, False
            compaction = None  # the last compaction item of the reply, and whether it came after the reply text
            for _ in range(max_tool_calls + 3 if tools else 1):
                stream = await self.client.responses.create(
                    model=model, input=items, store=False, stream=True,
                    max_output_tokens=self.settings.openai_max_output_tokens, **extra,
                )
                part = None  # summary part index, so consecutive parts don't run together
                output, calls, wrote = [], [], False
                async for ev in stream:
                    match ev.type:
                        case "response.output_text.delta":
                            if break_before_text:  # text from an earlier round, then a tool call: new paragraph
                                yield {"type": "delta", "text": "\n\n"}
                                break_before_text = False
                            wrote = True
                            yield {"type": "delta", "text": ev.delta}
                        case "response.reasoning_summary_text.delta":
                            gap = "\n\n" if part is not None and part != ev.summary_index else ""
                            part = ev.summary_index
                            yield {"type": "reasoning_delta", "text": gap + ev.delta}
                        case "response.output_item.done":
                            output.append(ev.item.model_dump(exclude_none=True))
                            if ev.item.type == "compaction":
                                compaction = {"item": output[-1], "after_reply": True}
                            elif ev.item.type == "message" and compaction:
                                compaction["after_reply"] = False  # the text came after it
                            if ev.item.type == "function_call":
                                calls.append(ev.item)
                        case "response.completed":
                            usage = _add_usage(usage, _usage(ev.response))
                        case "response.failed":
                            err = ev.response.error
                            yield {"type": "error", "message": err.message if err else "response failed"}
                            return
                        case "response.incomplete":
                            details = ev.response.incomplete_details
                            reason = details.reason if details else "unknown"
                            usage = _add_usage(usage, _usage(ev.response))
                            if compaction:
                                yield {"type": "compaction", **compaction}
                            yield {"type": "done", "incomplete": reason, **({"usage": usage} if usage else {})}
                            return
                        case "error":
                            yield {"type": "error", "message": ev.message}
                            return
                if not calls:
                    if compaction:
                        yield {"type": "compaction", **compaction}
                    yield {"type": "done", **({"usage": usage} if usage else {})}
                    return
                items += output
                break_before_text = wrote
                for call in calls:
                    calls_run += 1
                    yield {"type": "tool_call", "id": call.call_id, "name": call.name, "status": "running",
                           "arguments": _loads(call.arguments)}
                    text, fields = await _run_tool(call, tools or {}, allowed=calls_run <= max_tool_calls)
                    yield {"type": "tool_call", "id": call.call_id, "name": call.name, **fields}
                    items.append({"type": "function_call_output", "call_id": call.call_id, "output": text})
            yield {"type": "error", "message": "The model kept calling tools without answering."}
        except openai.OpenAIError as e:
            # The class and status only: the provider's message is shown to the user, not written to the log.
            logger.warning("model call failed: %s %s", type(e).__name__, getattr(e, "status_code", ""))
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
        except openai.OpenAIError as e:
            logger.warning("title generation failed: %s %s", type(e).__name__, getattr(e, "status_code", ""))
            return None
        return r.output_text.strip().strip("\"'").strip() or None
