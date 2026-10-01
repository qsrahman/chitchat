"""OpenAILLM against a fake SDK client: what we send, and how stream events are normalized."""
from types import SimpleNamespace as NS

import openai
import pytest

from app.config import Settings
from app.llm import OpenAILLM, supports_reasoning


async def aiter(items):
    for i in items:
        yield i


def make_llm(events=(), models=(), max_output_tokens=None, raises=None):
    seen = {}

    async def create(**kwargs):
        seen.update(kwargs)
        if raises:
            raise raises
        return aiter(events)

    llm = OpenAILLM(Settings(openai_max_output_tokens=max_output_tokens))
    llm._client = NS(responses=NS(create=create), models=NS(list=lambda: aiter(NS(id=m) for m in models)))
    return llm, seen


async def collect(llm, **kwargs):
    return [e async for e in llm.stream_reply("m", [{"role": "user", "content": "hi"}], **kwargs)]


def ev(type_, **kw):
    return NS(type=type_, **kw)


@pytest.mark.parametrize("model,expected", [
    ("o3", True), ("o4-mini", True), ("gpt-5.5", True), ("gpt-5-mini", True), ("gpt-oss:20b", True),
    ("gpt-4o", False), ("gemma4:cloud", False), ("qwen3.5:9b", False), ("llama3", False),
])
def test_supports_reasoning(model, expected):
    assert supports_reasoning(model) is expected


async def test_only_set_options_are_sent():
    llm, seen = make_llm()
    await collect(llm)
    assert not {"instructions", "reasoning", "temperature"} & seen.keys()
    assert (seen["model"], seen["store"], seen["stream"]) == ("m", False, True)
    assert seen["max_output_tokens"] is None


async def test_options_are_mapped_to_sdk_arguments():
    llm, seen = make_llm(max_output_tokens=500)
    await collect(llm, instructions="Be brief", reasoning_effort="low", temperature=0)
    assert seen["instructions"] == "Be brief"
    assert seen["reasoning"] == {"effort": "low"}
    assert seen["temperature"] == 0  # zero is a real value, not "unset"
    assert seen["max_output_tokens"] == 500


async def test_stream_events_are_normalized():
    llm, _ = make_llm([
        ev("response.created"),
        ev("response.output_text.delta", delta="Hel"),
        ev("response.output_text.delta", delta="lo"),
        ev("response.completed"),
    ])
    assert await collect(llm) == [
        {"type": "delta", "text": "Hel"}, {"type": "delta", "text": "lo"}, {"type": "done"},
    ]


async def test_incomplete_failed_and_error_events():
    llm, _ = make_llm([ev("response.incomplete", response=NS(incomplete_details=NS(reason="max_output_tokens")))])
    assert await collect(llm) == [{"type": "done", "incomplete": "max_output_tokens"}]
    llm, _ = make_llm([ev("response.failed", response=NS(error=NS(message="nope")))])
    assert await collect(llm) == [{"type": "error", "message": "nope"}]
    llm, _ = make_llm([ev("error", message="bad")])
    assert await collect(llm) == [{"type": "error", "message": "bad"}]


async def test_sdk_errors_become_error_events():
    err = openai.APIConnectionError(request=NS(url="http://x"))
    llm, _ = make_llm(raises=err)
    assert (await collect(llm))[0]["type"] == "error"


async def test_list_models_hides_embedding_models_and_sorts():
    llm, _ = make_llm(models=["qwen3.5:9b", "nomic-embed-text:latest", "gemma4:cloud"])
    assert await llm.list_models() == ["gemma4:cloud", "qwen3.5:9b"]


async def test_list_models_is_empty_when_listing_fails():
    llm, _ = make_llm()

    def boom():
        raise openai.APIConnectionError(request=NS(url="http://x"))

    llm._client.models.list = boom
    assert await llm.list_models() == []
