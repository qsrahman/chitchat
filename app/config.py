from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from the environment or .env. Names match the OpenAI SDK's own variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_base_url: str | None = None
    openai_model: str = "gpt-5.5"
    openai_max_retries: int = 2
    openai_max_output_tokens: int | None = None
    openai_reasoning_summaries: bool = True  # ask reasoning models for a summary of their thinking
    # How a PDF reaches the model: "text" extracts its text here and sends that (works with any model); "file"
    # sends the PDF itself as an input_file, which OpenAI reads with page images but local servers often reject.
    openai_pdf_input: Literal["text", "file"] = "text"
    brave_api_key: str = ""  # enables the web_search tool (Brave Search API)
    max_tool_calls: int = 4  # per reply: each web search is billed by Brave
    db_path: str = "chitchat.db"
    attachments_dir: str = "attachments"
