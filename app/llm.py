"""The only module that imports openai. Normalizes SDK stream events into ours:

    {"type": "delta", "text": str}
    {"type": "done"}
    {"type": "error", "message": str}
"""
from collections.abc import AsyncIterator

import openai
from openai import AsyncOpenAI

Event = dict


class OpenAILLM:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        # Lazy: the SDK raises at construction when no key is set, which would break importing the app.
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.api_key or None)
        return self._client

    async def stream_reply(self, model: str, messages: list[dict]) -> AsyncIterator[Event]:
        try:
            stream = await self.client.responses.create(
                model=model, input=messages, store=False, stream=True
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
                        yield {"type": "error", "message": "response incomplete"}
                    case "error":
                        yield {"type": "error", "message": ev.message}
        except openai.OpenAIError as e:
            yield {"type": "error", "message": str(e)}

    async def generate_title(self, model: str, user_text: str, reply_text: str) -> str | None:
        """Short conversation title, or None on any API failure (titles are best-effort)."""
        try:
            r = await self.client.responses.create(
                model=model,
                instructions="Write a title of at most 6 words for this chat. Reply with the title only, no quotes or punctuation at the end.",
                input=f"User: {user_text[:1000]}\n\nAssistant: {reply_text[:1000]}",
                store=False,
            )
        except openai.OpenAIError:
            return None
        return r.output_text.strip().strip("\"'").strip() or None
