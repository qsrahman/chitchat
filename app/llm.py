"""The only module that imports openai. Normalizes SDK stream events into ours:

    {"type": "delta", "text": str}
    {"type": "done"}                      # "incomplete": reason, when the reply hit a limit
    {"type": "error", "message": str}
"""
import re
import typing
from collections.abc import AsyncIterator

import openai
from openai import AsyncOpenAI
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
        if reasoning_effort:
            extra["reasoning"] = {"effort": reasoning_effort}
        if temperature is not None:
            extra["temperature"] = temperature
        try:
            stream = await self.client.responses.create(
                model=model,
                input=messages,
                store=False,
                stream=True,
                max_output_tokens=self.settings.openai_max_output_tokens,
                **extra,
            )
            async for ev in stream:
                match ev.type:
                    case "response.output_text.delta":
                        yield {"type": "delta", "text": ev.delta}
                    case "response.completed":
                        yield {"type": "done"}
                    case "response.failed":
                        err = ev.response.error
                        yield {"type": "error", "message": err.message if err else "response failed"}
                    case "response.incomplete":
                        details = ev.response.incomplete_details
                        yield {"type": "done", "incomplete": details.reason if details else "unknown"}
                    case "error":
                        yield {"type": "error", "message": ev.message}
        except openai.OpenAIError as e:
            yield {"type": "error", "message": str(e)}

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
