"""GET /api/config: what the Settings dialog shows about the server, never a secret."""
import httpx

from app.config import Settings
from app.main import create_app
from tests.conftest import FakeLLM


async def config_for(tmp_path, **settings):
    app = create_app(Settings(_env_file=None, db_path=str(tmp_path / "c.db"), attachments_dir=str(tmp_path / "f"),
                              **settings))
    app.state.llm = FakeLLM()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x") as client:
        r = await client.get("/api/config")
    assert r.status_code == 200
    return r.json()


async def test_the_default_setup_is_openai_with_compaction_and_no_limit(tmp_path):
    c = await config_for(tmp_path, openai_api_key="sk-secret", default_system_prompt="Be kind. {date}")
    assert c["endpoint"] == "OpenAI" and c["custom_endpoint"] is False
    assert c["compaction"] is True and c["history_tokens"] == 0 and c["max_tool_calls"] == 8
    assert c["web_search"] is False and c["tools"] == ["Calculator", "Search chats", "Read web pages"]
    assert c["default_instructions"] == "Be kind. {date}" and c["pdf_input"] == "text"


async def test_a_custom_endpoint_shows_only_its_scheme_and_host_and_changes_the_context_rules(tmp_path):
    c = await config_for(tmp_path, openai_base_url="http://user:pass@localhost:11434/v1/secret/path?key=1")
    assert c["endpoint"] == "http://localhost:11434" and c["custom_endpoint"] is True
    assert c["compaction"] is False and c["history_tokens"] == 32_000  # trimmed, not compacted
    assert "pass" not in str(c) and "secret" not in str(c) and "key=1" not in str(c)


async def test_a_key_is_reported_as_set_or_not_and_never_shown(tmp_path):
    c = await config_for(tmp_path, openai_api_key="sk-very-secret", brave_api_key="BSA-also-secret")
    assert c["web_search"] is True and "Web search" in c["tools"]
    assert "secret" not in str(c) and not any("key" in k for k in c)


async def test_the_values_are_the_effective_ones(tmp_path):
    c = await config_for(tmp_path, openai_model="gpt-x", title_model="tiny", compact_threshold=5000,
                         context_tokens=12345, max_tool_calls=3, openai_pdf_input="file", log_level="warning",
                         openai_max_output_tokens=900)
    assert (c["model"], c["title_model"], c["compact_threshold"], c["history_tokens"]) == ("gpt-x", "tiny", 5000, 12345)
    assert (c["max_tool_calls"], c["pdf_input"], c["log_level"], c["max_output_tokens"]) == (3, "file", "WARNING", 900)
