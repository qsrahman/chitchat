from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# The built-in system prompt, sent before custom instructions and the conversation's own prompt. It holds what the
# model can't know or guess: today's date and how replies are displayed. It sets no persona or style
# (see docs/default-prompt.md). {date} is replaced when a request is made.
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant in a chat app. Answer directly and accurately, and say so when you are unsure.\n"
    "Replies are shown as Markdown. Write math with \\( ... \\) inline and \\[ ... \\] for display, put code in "
    "fenced blocks with a language, and don't use Markdown images.\n"
    "Today's date is {date}."
)


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
    # Server-side compaction: once a request's context passes this many tokens, OpenAI replaces the older turns
    # with an opaque summary item. 0 turns it off. Servers that don't implement it ignore the parameter.
    compact_threshold: int = 150_000
    default_system_prompt: str = DEFAULT_SYSTEM_PROMPT  # empty = none; {date} becomes today's date
    brave_api_key: str = ""  # enables the web_search tool (Brave Search API)
    max_tool_calls: int = 4  # per reply: each web search is billed by Brave
    db_path: str = "chitchat.db"
    attachments_dir: str = "attachments"
