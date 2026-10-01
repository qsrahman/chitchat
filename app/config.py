from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from the environment or .env. Names match the OpenAI SDK's own variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_base_url: str | None = None
    openai_model: str = "gpt-5.5"
    openai_max_retries: int = 2
    openai_max_output_tokens: int | None = None
    db_path: str = "chitchat.db"
