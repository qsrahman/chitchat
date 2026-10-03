"""OpenAILLM through the real SDK, against an httpx mock transport: the request we send and the SSE
stream we parse are both the SDK's own, so only the wire format is faked."""
import base64
import json

import httpx
import pytest
from openai import AsyncOpenAI

from app.config import Settings
from app.llm import REASONING_EFFORTS, OpenAILLM, supports_reasoning
from app.tools import Tool, ToolError, ToolResult


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
    ("gpt-5.6-sol", True), ("gpt-6-luna", True), ("gpt-6.1-sol", True),
    ("gpt-4o", False), ("gpt-4.1", False), ("gpt-4.1-nano", False),
    ("gemma4:cloud", False), ("qwen3.5:9b", False), ("llama3", False),
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


def models_response(*models):
    """GET /models. Each model is an id, or an (id, created) pair."""
    data = [{"id": m, "object": "model", "created": 0, "owned_by": "x"} if isinstance(m, str)
            else {"id": m[0], "object": "model", "created": m[1], "owned_by": "x"} for m in models]
    return httpx.Response(200, json={"object": "list", "data": data})


async def listed(*models):
    return await make_llm(lambda r: models_response(*models)).list_models()


async def test_list_models_hides_what_a_text_chat_cannot_use():
    not_chat = [
        "text-embedding-3-small", "omni-moderation-latest", "babbage-002", "davinci-002", "gpt-3.5-turbo-instruct",
        "tts-1-hd", "gpt-4o-mini-tts", "whisper-1", "gpt-4o-transcribe", "gpt-4o-transcribe-diarize",
        "gpt-audio-mini", "gpt-realtime-2", "gpt-realtime-whisper", "gpt-live-1",
        "gpt-image-1", "chatgpt-image-latest", "sora-2", "gpt-4o-search-preview", "gpt-5-search-api",
    ]
    chat = [
        "gpt-5.5", "gpt-5.5-pro", "gpt-5.1-codex", "gpt-4.1-nano", "o3", "o1-pro", "chat-latest", "gpt-5-chat-latest",
    ]
    assert sorted(await listed(*not_chat, *chat)) == sorted(chat)


async def test_list_models_hides_dated_copies_only_when_the_alias_is_listed():
    got = await listed("gpt-4o", "gpt-4o-2024-08-06", "gpt-4-0613", "gpt-4", "gpt-9-2030-01-01", "o3", "o3-2025-04-16")
    assert sorted(got) == ["gpt-4", "gpt-4o", "gpt-9-2030-01-01", "o3"]  # gpt-9-... has no alias, so it stays


async def test_list_models_is_newest_first_and_alphabetical_on_ties():
    got = await listed(("gpt-4o", 100), ("gpt-6", 300), ("o3", 200), ("gpt-5", 200), ("zzz", 100))
    assert got == ["gpt-6", "gpt-5", "o3", "gpt-4o", "zzz"]


async def test_list_models_copes_with_servers_that_omit_created():
    bare = httpx.Response(200, json={"object": "list", "data": [
        {"id": "b-model", "object": "model", "owned_by": "x"}, {"id": "a-model", "object": "model", "owned_by": "x"}]})
    assert await make_llm(lambda r: bare).list_models() == ["a-model", "b-model"]


async def test_list_models_leaves_local_model_names_alone():
    local = ["gemma4:cloud", "gemma4:12b", "qwen2.5-coder:1.5b", "qwen3.5:9b-instruct", "llama3-instruct",
             "llama3.2-vision", "gpt-oss:20b", "ornith-1.5:9b", "minimax-m3:cloud"]
    assert sorted(await listed(*local, "nomic-embed-text:latest")) == sorted(local)  # only the embedding model goes


async def test_list_models_is_empty_when_listing_fails():
    assert await make_llm(lambda r: httpx.Response(404, json={"error": {"message": "no"}})).list_models() == []


def completed(usage=None):
    return {"type": "response.completed", "sequence_number": 9, "response": {"usage": usage} if usage else {}}


def summary_delta(text, part=0):
    return {"type": "response.reasoning_summary_text.delta", "delta": text, "summary_index": part, "item_id": "i",
            "output_index": 0, "sequence_number": 1}


USAGE = {"input_tokens": 77, "output_tokens": 43, "total_tokens": 120,
         "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 12}}


async def test_reasoning_summary_deltas_are_normalized_and_parts_are_separated():
    llm = make_llm(streaming(
        summary_delta("Check the", 0), summary_delta(" sum.", 0), summary_delta("Then divide.", 1),
        delta("42"), completed(),
    ))
    assert await collect(llm) == [
        {"type": "reasoning_delta", "text": "Check the"},
        {"type": "reasoning_delta", "text": " sum."},
        {"type": "reasoning_delta", "text": "\n\nThen divide."},
        {"type": "delta", "text": "42"},
        {"type": "done"},
    ]


async def test_usage_is_reported_on_done():
    events = await collect(make_llm(streaming(delta("x"), completed(USAGE))))
    assert events[-1] == {"type": "done", "usage": {"input_tokens": 77, "output_tokens": 43, "reasoning_tokens": 12}}


async def test_usage_without_token_details_counts_zero_reasoning_tokens():
    bare = {"input_tokens": 5, "output_tokens": 6, "total_tokens": 11}
    events = await collect(make_llm(streaming(completed(bare))))
    assert events[-1]["usage"] == {"input_tokens": 5, "output_tokens": 6, "reasoning_tokens": 0}


async def test_incomplete_reply_keeps_its_usage():
    incomplete = {"type": "response.incomplete", "sequence_number": 1,
                  "response": {"incomplete_details": {"reason": "max_output_tokens"}, "usage": USAGE}}
    done = (await collect(make_llm(streaming(incomplete))))[-1]
    assert done["incomplete"] == "max_output_tokens" and done["usage"]["output_tokens"] == 43


async def test_summaries_are_requested_only_from_reasoning_models():
    sent = []
    llm = make_llm(streaming(requests=sent))
    async for _ in llm.stream_reply("gpt-5-mini", [{"role": "user", "content": "hi"}]):
        pass
    assert sent[-1]["reasoning"] == {"summary": "auto"}
    async for _ in llm.stream_reply("gpt-5-mini", [{"role": "user", "content": "hi"}], reasoning_effort="low"):
        pass
    assert sent[-1]["reasoning"] == {"effort": "low", "summary": "auto"}
    async for _ in llm.stream_reply("gemma4:cloud", [{"role": "user", "content": "hi"}]):
        pass
    assert "reasoning" not in sent[-1]


async def test_summaries_can_be_switched_off():
    sent = []
    llm = make_llm(streaming(requests=sent), openai_reasoning_summaries=False)
    async for _ in llm.stream_reply("gpt-5-mini", [{"role": "user", "content": "hi"}], reasoning_effort="high"):
        pass
    assert sent[-1]["reasoning"] == {"effort": "high"}


# ---- attachments ----

def user_message(tmp_path, text="what is this?"):
    image, pdf = tmp_path / "pic", tmp_path / "doc"
    image.write_bytes(b"IMAGE-BYTES")
    pdf.write_bytes(b"PDF-BYTES")
    return {"role": "user", "content": text, "attachments": [
        {"kind": "image", "name": "pic.png", "mime": "image/png", "path": str(image)},
        {"kind": "file", "name": "doc.pdf", "mime": "application/pdf", "path": str(pdf)},
        {"kind": "text", "name": "notes.txt", "text": "remember the milk"},
    ]}


async def test_attachments_become_input_parts_before_the_text(tmp_path):
    sent = []
    llm = make_llm(streaming(requests=sent))
    plain = {"role": "assistant", "content": "an earlier reply"}
    async for _ in llm.stream_reply("m", [user_message(tmp_path), plain]):
        pass
    first, second = sent[0]["input"]
    assert second == {"role": "assistant", "content": "an earlier reply"}  # no attachments: plain text, as before
    assert first["content"] == [
        {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(b"IMAGE-BYTES").decode()},
        {"type": "input_file", "filename": "doc.pdf",
         "file_data": "data:application/pdf;base64," + base64.b64encode(b"PDF-BYTES").decode()},
        {"type": "input_text", "text": '<file name="notes.txt">\nremember the milk\n</file>'},
        {"type": "input_text", "text": "what is this?"},
    ]


async def test_a_message_of_only_attachments_has_no_empty_text_part(tmp_path):
    sent = []
    message = user_message(tmp_path, text="")
    async for _ in make_llm(streaming(requests=sent)).stream_reply("m", [message]):
        pass
    parts = sent[0]["input"][0]["content"]
    assert len(parts) == 3 and all(p["text"] for p in parts if p["type"] == "input_text")


async def test_a_file_name_cannot_break_out_of_its_tag():
    sent = []
    message = {"role": "user", "content": "", "attachments": [
        {"kind": "text", "name": 'a"><b>.txt', "text": "x"},
    ]}
    async for _ in make_llm(streaming(requests=sent)).stream_reply("m", [message]):
        pass
    assert sent[0]["input"][0]["content"][0]["text"] == "<file name='a\"&gt;&lt;b&gt;.txt'>\nx\n</file>"  # escaped


async def test_provider_errors_are_shown_without_the_sdk_wrapping_or_nested_json():
    nested = '{"error":{"code":400,"message":"Multimodal data provided, but model does not support multimodal."}}'
    llm = make_llm(lambda request: httpx.Response(400, json={"error": {"message": nested, "type": "invalid"}}))
    assert await collect(llm) == [
        {"type": "error", "message": "Multimodal data provided, but model does not support multimodal."}
    ]
    plain = make_llm(lambda request: httpx.Response(400, json={"error": {"message": "file inputs are not supported"}}))
    assert await collect(plain) == [{"type": "error", "message": "file inputs are not supported"}]


# ---- the tool loop ----


def call_item(name="web_search", arguments='{"query": "python", "freshness": null}', call_id="call_1"):
    item = {"type": "function_call", "id": f"fc_{call_id}", "call_id": call_id, "name": name,
            "arguments": arguments, "status": "completed"}
    return {"type": "response.output_item.done", "item": item, "output_index": 0, "sequence_number": 2}


def usage(i, o, r=0):
    return {"input_tokens": i, "output_tokens": o, "total_tokens": i + o,
            "output_tokens_details": {"reasoning_tokens": r}}


def rounds(*bodies, requests):
    """A handler that answers request n with the n-th event list; the request bodies are recorded."""
    answers = iter(bodies)

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=sse(*next(answers)), headers={"content-type": "text/event-stream"})

    return handler


def tool(run=None, name="web_search"):
    calls = []

    async def default(args):
        calls.append(args)
        shown = {"query": args.get("query"), "results": [{"title": "T", "url": "https://x.dev"}]}
        return ToolResult("RESULT TEXT", shown)

    async def counting(args):
        calls.append(args)
        return await run(args)

    return Tool(name=name, label="Web search", description="Search.", parameters={"type": "object"},
                run=counting if run else default), calls


async def events_of(llm, **kwargs):
    return [e async for e in llm.stream_reply("m", [{"role": "user", "content": "hi"}], **kwargs)]


async def test_one_tool_round_runs_the_tool_feeds_the_result_back_and_streams_the_answer():
    requests = []
    web, calls = tool()
    llm = make_llm(rounds(
        [call_item(), completed(usage(100, 10))],
        [delta("It is "), delta("3.14."), completed(usage(150, 20, 5))],
        requests=requests,
    ))
    events = await events_of(llm, tools={"web_search": web})
    assert events == [
        {"type": "tool_call", "id": "call_1", "name": "web_search", "status": "running",
         "arguments": {"query": "python", "freshness": None}},
        {"type": "tool_call", "id": "call_1", "name": "web_search", "status": "done",
         "arguments": {"query": "python", "freshness": None},
         "display": {"query": "python", "results": [{"title": "T", "url": "https://x.dev"}]}},
        {"type": "delta", "text": "It is "}, {"type": "delta", "text": "3.14."},
        {"type": "done", "usage": {"input_tokens": 250, "output_tokens": 30, "reasoning_tokens": 5}},  # both rounds
    ]
    assert calls == [{"query": "python", "freshness": None}]
    first, second = requests
    assert first["tools"] == [{"type": "function", "name": "web_search", "description": "Search.",
                               "parameters": {"type": "object"}, "strict": True}]
    assert second["input"][0] == {"role": "user", "content": "hi"}
    assert second["input"][1]["type"] == "function_call" and second["input"][1]["call_id"] == "call_1"
    assert second["input"][2] == {"type": "function_call_output", "call_id": "call_1", "output": "RESULT TEXT"}
    assert second["tools"] == first["tools"] and second["store"] is False


async def test_text_before_a_tool_call_is_separated_from_the_answer():
    requests = []
    web, _ = tool()
    llm = make_llm(rounds(
        [delta("Let me check."), call_item(), completed()], [delta("Done."), completed()], requests=requests))
    texts = [e["text"] for e in await events_of(llm, tools={"web_search": web}) if e["type"] == "delta"]
    assert "".join(texts) == "Let me check.\n\nDone."


async def test_reasoning_models_get_encrypted_reasoning_back_with_the_call():
    requests = []
    web, _ = tool()
    reasoning = {"type": "response.output_item.done", "output_index": 0, "sequence_number": 1,
                 "item": {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "ENC"}}
    llm = make_llm(rounds([reasoning, call_item(), completed()], [delta("ok"), completed()], requests=requests))
    async for _ in llm.stream_reply("gpt-5.5", [{"role": "user", "content": "hi"}], tools={"web_search": web}):
        pass
    assert requests[0]["include"] == ["reasoning.encrypted_content"]
    assert [i.get("type") for i in requests[1]["input"][1:]] == ["reasoning", "function_call", "function_call_output"]
    assert requests[1]["input"][1]["encrypted_content"] == "ENC"


async def test_other_models_do_not_ask_for_encrypted_reasoning():
    requests = []
    web, _ = tool()
    llm = make_llm(rounds([delta("ok"), completed()], requests=requests))
    await events_of(llm, tools={"web_search": web})
    assert "include" not in requests[0]


async def test_without_tools_there_is_one_request_and_no_tools_parameter():
    requests = []
    await events_of(make_llm(rounds([delta("hi"), completed()], requests=requests)))
    assert len(requests) == 1 and "tools" not in requests[0]


async def test_a_tool_error_is_reported_to_the_model_and_the_user_and_the_reply_carries_on():
    requests = []

    async def fails(args):
        raise ToolError("Search rate limit reached.")

    web, _ = tool(fails)
    llm = make_llm(rounds(
        [call_item(), completed()], [delta("Sorry, I couldn't search."), completed()], requests=requests))
    events = await events_of(llm, tools={"web_search": web})
    error = next(e for e in events if e["type"] == "tool_call" and e["status"] == "error")
    assert error["error"] == "Search rate limit reached."
    assert requests[1]["input"][-1]["output"] == "Error: Search rate limit reached."
    assert events[-1]["type"] == "done"


async def test_a_tool_that_crashes_does_not_crash_the_reply(caplog):
    async def boom(args):
        raise RuntimeError("secret internals")

    web, _ = tool(boom)
    requests = []
    llm = make_llm(rounds([call_item(), completed()], [delta("ok"), completed()], requests=requests))
    events = await events_of(llm, tools={"web_search": web})
    error = next(e for e in events if e.get("status") == "error")
    assert error["error"] == "The tool failed unexpectedly." and "secret" not in json.dumps(events)
    assert requests[1]["input"][-1]["output"] == "Error: the tool failed."
    assert "web_search failed" in caplog.text and events[-1]["type"] == "done"


@pytest.mark.parametrize("arguments", ["not json", "[1, 2]", '"text"'])
async def test_bad_arguments_never_reach_the_tool(arguments):
    web, calls = tool()
    requests = []
    llm = make_llm(rounds(
        [call_item(arguments=arguments), completed()], [delta("ok"), completed()], requests=requests))
    events = await events_of(llm, tools={"web_search": web})
    assert calls == [] and next(e for e in events if e.get("status") == "error")["error"] == "Bad arguments."
    assert "valid JSON object" in requests[1]["input"][-1]["output"]


async def test_an_unknown_tool_is_an_error_not_a_crash():
    web, calls = tool()
    requests = []
    llm = make_llm(rounds(
        [call_item(name="launch_missiles"), completed()], [delta("ok"), completed()], requests=requests))
    events = await events_of(llm, tools={"web_search": web})
    assert calls == [] and any(e.get("error") == "Unknown tool." for e in events)
    assert "no tool called launch_missiles" in requests[1]["input"][-1]["output"]


async def test_calls_beyond_the_limit_are_not_run():
    web, calls = tool()
    requests = []
    llm = make_llm(rounds(
        [call_item(call_id="a"), call_item(call_id="b"), call_item(call_id="c"), completed()],
        [delta("ok"), completed()], requests=requests))
    events = await events_of(llm, tools={"web_search": web}, max_tool_calls=2)
    assert len(calls) == 2  # the third was refused
    outcomes = [(e["id"], e["status"]) for e in events if e["type"] == "tool_call" and e["status"] != "running"]
    assert outcomes == [("a", "done"), ("b", "done"), ("c", "error")]
    assert "limit" in requests[1]["input"][-1]["output"]


async def test_a_model_that_never_stops_calling_tools_is_cut_off():
    web, calls = tool()
    requests = []
    llm = make_llm(rounds(*[[call_item(call_id=f"c{i}"), completed()] for i in range(10)], requests=requests))
    events = await events_of(llm, tools={"web_search": web}, max_tool_calls=1)
    assert events[-1] == {"type": "error", "message": "The model kept calling tools without answering."}
    assert len(requests) == 4 and len(calls) == 1  # max_tool_calls + 3 rounds, and only one search was really run


async def test_an_error_event_in_a_later_round_ends_the_reply():
    web, _ = tool()
    llm = make_llm(rounds([call_item(), completed()],
                          [{"type": "error", "message": "boom", "code": None, "param": None, "sequence_number": 1}],
                          requests=[]))
    events = await events_of(llm, tools={"web_search": web})
    assert events[-1] == {"type": "error", "message": "boom"}


async def test_an_incomplete_later_round_still_reports_the_total_usage():
    web, _ = tool()
    incomplete = {"type": "response.incomplete", "sequence_number": 1, "response": {
        "incomplete_details": {"reason": "max_output_tokens"}, "usage": usage(50, 8)}}
    llm = make_llm(rounds([call_item(), completed(usage(100, 10))], [delta("part"), incomplete], requests=[]))
    done = (await events_of(llm, tools={"web_search": web}))[-1]
    assert done == {"type": "done", "incomplete": "max_output_tokens",
                    "usage": {"input_tokens": 150, "output_tokens": 18, "reasoning_tokens": 0}}


async def test_several_calls_in_one_round_all_get_their_outputs_in_order():
    web, calls = tool()
    requests = []
    llm = make_llm(rounds(
        [call_item(call_id="a", arguments='{"query": "one", "freshness": null}'),
         call_item(call_id="b", arguments='{"query": "two", "freshness": null}'), completed()],
        [delta("ok"), completed()], requests=requests))
    await events_of(llm, tools={"web_search": web})
    assert [c["query"] for c in calls] == ["one", "two"]
    tail = requests[1]["input"][1:]
    kinds = [i["type"] for i in tail]
    assert kinds.count("function_call") == 2 and kinds.count("function_call_output") == 2
    assert {i["call_id"] for i in tail if i["type"] == "function_call_output"} == {"a", "b"}


# ---- compaction ----

def item_done(item):
    return {"type": "response.output_item.done", "item": item, "output_index": 0, "sequence_number": 2}


COMPACTION = {"id": "cmp_1", "type": "compaction", "encrypted_content": "opaque"}
MESSAGE = {"id": "msg_1", "type": "message", "role": "assistant", "status": "completed", "content": []}


async def test_compaction_is_requested_when_a_threshold_is_set():
    requests = []
    llm = make_llm(streaming(delta("a"), completed(), requests=requests), compact_threshold=1000)
    await collect(llm)
    assert requests[0]["context_management"] == [{"type": "compaction", "compact_threshold": 1000}]
    assert requests[0]["store"] is False


async def test_compaction_is_not_requested_when_the_threshold_is_zero():
    requests = []
    await collect(make_llm(streaming(delta("a"), completed(), requests=requests), compact_threshold=0))
    assert "context_management" not in requests[0]


async def test_a_compaction_before_the_reply_text_is_reported_as_not_covering_it():
    llm = make_llm(streaming(item_done(COMPACTION), delta("a"), item_done(MESSAGE), completed()))
    events = await collect(llm)
    assert events[-2:] == [{"type": "compaction", "item": COMPACTION, "after_reply": False}, {"type": "done"}]


async def test_the_last_compaction_wins_and_one_after_the_reply_covers_it():
    later = {**COMPACTION, "id": "cmp_2"}
    llm = make_llm(streaming(item_done(COMPACTION), delta("a"), item_done(MESSAGE), item_done(later), completed()))
    events = await collect(llm)
    assert events[-2] == {"type": "compaction", "item": later, "after_reply": True}


async def test_no_compaction_event_without_a_compaction_item():
    events = await collect(make_llm(streaming(delta("a"), item_done(MESSAGE), completed())))
    assert all(e["type"] != "compaction" for e in events)


async def test_a_stored_compaction_item_is_sent_as_it_is_in_place_of_earlier_turns():
    requests = []
    llm = make_llm(streaming(delta("a"), completed(), requests=requests))
    messages = [{"compaction": COMPACTION}, {"role": "user", "content": "next"}]
    [e async for e in llm.stream_reply("m", messages)]
    assert requests[0]["input"] == [COMPACTION, {"role": "user", "content": "next"}]


# ---- the model list is remembered briefly ----

def counting_models_llm(*models, fail_after=None):
    requests = []

    def handler(request):
        requests.append(request)
        if fail_after is not None and len(requests) > fail_after:
            return httpx.Response(500, json={"error": {"message": "down"}})
        return models_response(*models)

    return make_llm(handler), requests


async def test_the_model_list_is_fetched_once_within_the_ttl(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("app.llm.time.monotonic", lambda: clock[0])
    llm, requests = counting_models_llm(("a-model", 1))
    assert await llm.list_models() == ["a-model"]
    clock[0] += 299
    assert await llm.list_models() == ["a-model"]
    assert len(requests) == 1


async def test_the_model_list_is_fetched_again_after_the_ttl(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("app.llm.time.monotonic", lambda: clock[0])
    llm, requests = counting_models_llm(("a-model", 1))
    await llm.list_models()
    clock[0] += 301
    await llm.list_models()
    assert len(requests) == 2


async def test_a_failed_listing_is_not_remembered(monkeypatch):
    llm, requests = counting_models_llm(("a-model", 1), fail_after=0)
    assert await llm.list_models() == [] and await llm.list_models() == []
    assert len(requests) == 2  # tried again, not served from a cache of nothing


async def test_when_a_refresh_fails_the_old_list_is_not_served_as_if_new(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("app.llm.time.monotonic", lambda: clock[0])
    llm, requests = counting_models_llm(("a-model", 1), fail_after=1)
    assert await llm.list_models() == ["a-model"]
    clock[0] += 400
    assert await llm.list_models() == []  # the endpoint is down now, and the picker should say so
