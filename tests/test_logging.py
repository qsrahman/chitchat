import logging
import re

import httpx
import openai

from app import logs
from app.config import Settings
from app.llm import OpenAILLM
from app.main import create_app
from tests.helpers import new_conv


async def chat(client, cid, text):
    return await client.post(f"/api/conversations/{cid}/chat", json={"content": text})


def lines(caplog):
    return [r.getMessage() for r in caplog.records]


async def test_every_response_carries_a_request_id_and_each_is_different(client):
    ids = {(await client.get("/healthz")).headers["x-request-id"] for _ in range(3)}
    assert len(ids) == 3 and all(re.fullmatch(r"[0-9a-f]{8}", i) for i in ids)


async def test_an_api_request_is_logged_with_its_id_but_static_files_and_healthz_are_not(client, caplog):
    caplog.set_level(logging.INFO, logger="app")
    await client.get("/healthz")
    await client.get("/")
    assert caplog.records == []
    r = await client.get("/api/conversations")
    [record] = caplog.records
    assert record.getMessage().startswith("GET /api/conversations -> 200 in ")
    assert record.request_id == r.headers["x-request-id"]


async def test_a_finished_reply_logs_its_outcome_without_what_was_said(client, caplog, llm):
    llm.events = [{"type": "delta", "text": "the answer is purple"},
                  {"type": "done", "usage": {"input_tokens": 12, "output_tokens": 5}}]
    caplog.set_level(logging.INFO, logger="app")
    cid = await new_conv(client)
    await chat(client, cid, "my secret question")
    [reply] = [m for m in lines(caplog) if m.startswith("reply ")]
    assert f"reply done: conversation {cid}, model test-model, 0 tool calls, 12 tokens in, 5 out" in reply
    assert "secret" not in "\n".join(lines(caplog)) and "purple" not in "\n".join(lines(caplog))


async def test_a_failed_reply_is_logged_as_an_error(client, caplog, llm):
    llm.events = [{"type": "error", "message": "boom, with sk-secret in it"}]
    caplog.set_level(logging.INFO, logger="app")
    cid = await new_conv(client)
    await chat(client, cid, "hi")
    assert any(m.startswith("reply error:") for m in lines(caplog))
    assert "sk-secret" not in "\n".join(lines(caplog))


async def test_a_provider_error_logs_its_class_and_status_not_its_message(caplog):
    def refuse(request):
        return httpx.Response(401, json={"error": {"message": "Incorrect API key provided: sk-abc"}})

    client = openai.AsyncOpenAI(api_key="x", base_url="http://x/v1", max_retries=0,
                                http_client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    llm = OpenAILLM(Settings(_env_file=None, default_system_prompt=""), client=client)
    caplog.set_level(logging.INFO, logger="app")
    events = [e async for e in llm.stream_reply("m", [{"role": "user", "content": "hi"}])]
    assert "sk-abc" in events[-1]["message"]  # the user is told
    assert lines(caplog) == ["model call failed: AuthenticationError 401"]  # the log is not


def test_setup_adds_one_handler_however_often_it_runs():
    before = len([h for h in logging.getLogger("app").handlers if getattr(h, "_chitchat", False)])
    for _ in range(3):
        logs.setup("INFO")
    after = len([h for h in logging.getLogger("app").handlers if getattr(h, "_chitchat", False)])
    assert after == max(before, 1)


def test_the_level_comes_from_settings(tmp_path):
    create_app(Settings(_env_file=None, db_path=str(tmp_path / "x.db"), attachments_dir=str(tmp_path / "f"),
                        log_level="warning"))
    assert logging.getLogger("app").level == logging.WARNING
    logs.setup("INFO")
