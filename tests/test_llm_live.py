import dataclasses
import os

import pytest

from app import tools
from app.config import Settings
from app.llm import OpenAILLM


@pytest.mark.live
async def test_live_stream_normalization():
    s = Settings()
    assert s.openai_api_key or os.environ.get("OPENAI_API_KEY"), "needs OPENAI_API_KEY"
    events = [e async for e in OpenAILLM(s).stream_reply(
        s.openai_model, [{"role": "user", "content": "Say hi in one word."}])]
    assert any(e["type"] == "delta" for e in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["usage"]["output_tokens"] > 0


@pytest.mark.live
async def test_live_generate_title():
    s = Settings()
    title = await OpenAILLM(s).generate_title(s.title_model_name, "How do I sort a list in Python?", "Use sorted().")
    assert title


@pytest.mark.live
async def test_live_list_models_returns_unique_chat_models():
    s = Settings()
    models = await OpenAILLM(s).list_models()
    assert models and len(models) == len(set(models))
    assert not any(w in m for m in models for w in ("embed", "whisper", "tts", "moderation"))


@pytest.mark.live
async def test_live_tool_loop_with_a_stand_in_search_tool():
    """The real API's function-call events and the stateless round trip, without needing a Brave key."""
    s = Settings()
    ran = []

    async def stand_in(args):
        ran.append(args)
        return tools.ToolResult(
            "1. Zorblax 9 is the current release of the Zorblax language\n   https://zorblax.example/releases",
            {"query": args["query"],
             "results": [{"title": "Zorblax releases", "url": "https://zorblax.example/releases"}]},
        )

    real = tools.build(Settings(_env_file=None, brave_api_key="unused"))["web_search"]
    tool = dataclasses.replace(real, run=stand_in)
    question = "What is the current release of the Zorblax programming language? Search first."
    messages = [{"role": "user", "content": question}]
    events = [e async for e in OpenAILLM(s).stream_reply(
        s.openai_model, messages, instructions=tool.guidance, tools={"web_search": tool})]
    assert ran, "the model never called the tool"
    assert [e["status"] for e in events if e["type"] == "tool_call"][:2] == ["running", "done"]
    assert "Zorblax 9" in "".join(e["text"] for e in events if e["type"] == "delta")
    assert events[-1]["type"] == "done" and events[-1]["usage"]["input_tokens"] > 0


@pytest.mark.live
async def test_live_brave_search():
    s = Settings()
    if not s.brave_api_key:
        pytest.skip("needs BRAVE_API_KEY")
    result = await tools.build(s)["web_search"].run({"query": "python programming language", "freshness": None})
    assert result.display["results"] and all(r["url"].startswith("http") for r in result.display["results"])
    assert result.output.startswith("Web search results")


@pytest.mark.live
async def test_live_compaction_round_trip():
    """A tiny threshold forces compaction; the compaction item then stands in for the earlier turns and the
    model still knows what they said."""
    # compaction is OpenAI's, whatever .env points at: its endpoint and a model it has
    s = Settings(compact_threshold=1000, openai_base_url=None, openai_model="gpt-5.5")
    llm = OpenAILLM(s)
    facts = " ".join(f"Fact {i}: the code word for item {i} is zeta{i * 7}." for i in range(150))
    history = [
        {"role": "user", "content": "Remember these facts. " + facts},
        {"role": "assistant", "content": "Noted."},
        {"role": "user", "content": "What is the code word for item 42? Answer with just the word."},
    ]
    events = [e async for e in llm.stream_reply(s.openai_model, history)]
    compaction = next(e for e in events if e["type"] == "compaction")
    assert compaction["item"]["type"] == "compaction" and compaction["item"]["encrypted_content"]
    follow_up = [{"compaction": compaction["item"]}, {"role": "user", "content": "And item 100?"}]
    answer = [e async for e in llm.stream_reply(s.openai_model, follow_up)]
    assert "zeta700" in "".join(e["text"] for e in answer if e["type"] == "delta")


@pytest.mark.live
async def test_live_model_uses_the_calculator_tool():
    s = Settings()
    calculator = tools.build(s)["calculator"]
    events = [e async for e in OpenAILLM(s).stream_reply(
        s.openai_model,
        [{"role": "user", "content": "Use the calculator: what is 123456789 * 987654321? Give just the number."}],
        tools={"calculator": calculator},
    )]
    calls = [e for e in events if e["type"] == "tool_call" and e["status"] == "done"]
    assert calls and calls[0]["display"]["result"] == str(123456789 * 987654321)
    assert str(123456789 * 987654321) in "".join(e["text"] for e in events if e["type"] == "delta").replace(",", "")


@pytest.mark.live
async def test_live_fetch_url_reads_a_real_page_through_the_pinned_connection():
    """Real DNS and TLS: the request goes to the resolved address with the name as SNI, and certificates verify."""
    result = await tools.fetch_url({"url": "https://example.com/"})
    assert "Example Domain" in result.output and result.display["title"] == "Example Domain"
    with pytest.raises(tools.ToolError, match="not a public website"):
        await tools.fetch_url({"url": "http://localhost/"})


@pytest.mark.live
async def test_live_fetch_url_reads_a_real_pdf_and_a_long_page_in_parts():
    pdf = await tools.fetch_url({"url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"})
    assert "Dummy PDF file" in pdf.output and pdf.display["title"] == "dummy.pdf"
    url = "https://docs.python.org/3/whatsnew/3.14.html"  # a long page: well over one part
    first = await tools.fetch_url({"url": url, "offset": None})
    assert first.display["truncated"] and f"offset={first.display['characters']}" in first.output
    second = await tools.fetch_url({"url": url, "offset": first.display["characters"]})
    assert second.display["offset"] == first.display["characters"] and second.display["total"] == first.display["total"]
