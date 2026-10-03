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


OPENAI_TITLE_MODEL = "gpt-5.4-nano"
CUSTOM_ENDPOINT_CONTEXT = 32_000  # a common size for local models; raise it with CONTEXT_TOKENS if yours is larger


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
    # Without compaction (a custom endpoint), the most history to send, in tokens, estimated: older turns are left
    # out beyond it. Unset = 32,000 on a custom endpoint and no limit on OpenAI; 0 = no limit. See context.py.
    context_tokens: int | None = None
    title_model: str = ""  # writes the chat titles; empty = a small default, see title_model_name
    brave_api_key: str = ""  # enables the web_search tool (Brave Search API)
    max_tool_calls: int = 4  # per reply: each web search is billed by Brave
    db_path: str = "chitchat.db"
    attachments_dir: str = "attachments"

    @property
    def title_model_name(self) -> str:
        """Titles are six words, so a small model does: the TITLE_MODEL setting, else a small OpenAI model, or the
        main model on a custom endpoint, which wouldn't have OpenAI's model names."""
        return self.title_model or (self.openai_model if self.openai_base_url else OPENAI_TITLE_MODEL)

    @property
    def compaction_enabled(self) -> bool:
        """Compaction is OpenAI's: a custom endpoint ignores the request, or can't read the item it returns."""
        return bool(self.compact_threshold) and not self.openai_base_url

    @property
    def history_tokens(self) -> int:
        """The token budget for conversation history; 0 means send all of it."""
        if self.context_tokens is not None:
            return self.context_tokens
        return CUSTOM_ENDPOINT_CONTEXT if self.openai_base_url else 0

