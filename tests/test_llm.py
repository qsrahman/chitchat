"""OpenAILLM through the real SDK, against an httpx mock transport: the request we send and the SSE
stream we parse are both the SDK's own, so only the wire format is faked."""
import json

import httpx
import pytest
from openai import AsyncOpenAI

from app.config import Settings
from app.llm import REASONING_EFFORTS, OpenAILLM, supports_reasoning


def sse(*events: dict) -> bytes:
    """A Responses API event stream."""
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def delta(text: str) -> dict:
    return {"type": "response.output_text.delta", "delta": text, "item_id": "i", "output_index": 0,
            "content_index": 0, "sequence_number": 1}


def make_llm(handler, **settings):
    """An OpenAILLM whose SDK client sends every request to `handler(httpx.Request) -> httpx.Response`."""
    client = AsyncOpenAI(
        api_key="k", base_url="http://llm.test/v1", max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return OpenAILLM(Settings(_env_file=None, **settings), client)


def streaming(*events, requests=None):
    def handler(request):
        if requests is not None:
            requests.append(json.loads(request.content))
        return httpx.Response(200, content=sse(*events), headers={"content-type": "text/event-stream"})

    return handler


async def collect(llm, **kwargs):
    return [e async for e in llm.stream_reply("m", [{"role": "user", "content": "hi"}], **kwargs)]


@pytest.mark.parametrize("model,expected", [
    ("o3", True), ("o4-mini", True), ("gpt-5.5", True), ("gpt-5-mini", True), ("gpt-oss:20b", True),
    ("gpt-4o", False), ("gemma4:cloud", False), ("qwen3.5:9b", False), ("llama3", False),
])
def test_supports_reasoning(model, expected):
    assert supports_reasoning(model) is expected


def test_effort_levels_come_from_the_sdk():
    assert {"low", "medium", "high"} <= set(REASONING_EFFORTS)
    assert None not in REASONING_EFFORTS


async def test_only_set_options_are_sent():
    sent = []
    await collect(make_llm(streaming(requests=sent)))
    body = sent[0]
    assert body["model"] == "m" and body["store"] is False and body["stream"] is True
    assert body["input"] == [{"role": "user", "content": "hi"}]
    assert not {"instructions", "reasoning", "temperature"} & body.keys()
    assert not body.get("max_output_tokens")


async def test_options_are_mapped_to_request_fields():
    sent = []
    llm = make_llm(streaming(requests=sent), openai_max_output_tokens=500)
    await collect(llm, instructions="Be brief", reasoning_effort="low", temperature=0)
    body = sent[0]
    assert body["instructions"] == "Be brief"
    assert body["reasoning"] == {"effort": "low"}
    assert body["temperature"] == 0  # zero is a real value, not "unset"
    assert body["max_output_tokens"] == 500


async def test_stream_events_are_normalized():
    llm = make_llm(streaming(
        {"type": "response.created", "response": {}, "sequence_number": 0},
        delta("Hel"), delta("lo"),
        {"type": "response.completed", "response": {}, "sequence_number": 9},
    ))
    assert await collect(llm) == [
        {"type": "delta", "text": "Hel"}, {"type": "delta", "text": "lo"}, {"type": "done"},
    ]


async def test_incomplete_failed_and_error_events():
    incomplete = {"type": "response.incomplete", "sequence_number": 1,
                  "response": {"incomplete_details": {"reason": "max_output_tokens"}}}
    assert await collect(make_llm(streaming(incomplete))) == [{"type": "done", "incomplete": "max_output_tokens"}]
    failed = {"type": "response.failed", "sequence_number": 1, "response": {"error": {"code": "x", "message": "nope"}}}
    assert await collect(make_llm(streaming(failed))) == [{"type": "error", "message": "nope"}]
    error = {"type": "error", "message": "bad", "code": None, "param": None, "sequence_number": 1}
    assert await collect(make_llm(streaming(error))) == [{"type": "error", "message": "bad"}]


async def test_http_and_connection_errors_become_error_events():
    llm = make_llm(lambda request: httpx.Response(500, json={"error": {"message": "overloaded"}}))
    events = await collect(llm)
    assert [e["type"] for e in events] == ["error"] and "overloaded" in events[0]["message"]

    def refuse(request):
        raise httpx.ConnectError("refused")

    assert (await collect(make_llm(refuse)))[0]["type"] == "error"


def message_response(text: str) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "r", "object": "response", "created_at": 0, "model": "m", "status": "completed",
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        "output": [{"id": "m1", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": text, "annotations": []}]}],
    })


async def test_title_is_cleaned_up():
    llm = make_llm(lambda r: message_response('  "Sorting Lists in Python"  '))
    assert await llm.generate_title("m", "q", "a") == "Sorting Lists in Python"


async def test_title_is_none_when_the_call_fails_or_is_blank():
    failing = make_llm(lambda r: httpx.Response(500, json={"error": {"message": "x"}}))
    assert await failing.generate_title("m", "q", "a") is None
    assert await make_llm(lambda r: message_response("  ")).generate_title("m", "q", "a") is None


def models_response(*ids):
    return httpx.Response(200, json={"object": "list", "data": [
        {"id": i, "object": "model", "created": 0, "owned_by": "x"} for i in ids]})


async def test_list_models_hides_embedding_models_and_sorts():
    llm = make_llm(lambda r: models_response("qwen3.5:9b", "nomic-embed-text:latest", "gemma4:cloud"))
    assert await llm.list_models() == ["gemma4:cloud", "qwen3.5:9b"]


async def test_list_models_is_empty_when_listing_fails():
    assert await make_llm(lambda r: httpx.Response(404, json={"error": {"message": "no"}})).list_models() == []
