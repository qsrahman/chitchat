# Small improvements

A batch of four, each its own commit.

## 1. A small model for chat titles
Titles were written by the default model (`gpt-5.5`, a reasoning model) for six words. `TITLE_MODEL` now picks the model; empty means `gpt-5.4-nano` on OpenAI, or `OPENAI_MODEL` when `OPENAI_BASE_URL` is set, because a custom endpoint (Ollama) doesn't have OpenAI's model names and every title call would fail (`Settings.title_model_name`). Measured on one title: `gpt-5.5` 3.0 s, `gpt-5.4-nano` 1.1 s, `gpt-5.4-mini` 1.0 s. A title model that can't be reached still falls back to the first words of the message, as before. Tests: `tests/test_settings.py`.

## 2. The model list is cached for five minutes
`GET /api/models` listed models from the provider on every call: on page load, whenever the picker opens, and in the background when the settings dialog opens. That is a remote call each time. `OpenAILLM.list_models` now remembers a successful answer for `MODELS_TTL` (300 s). A failed listing is never remembered, and once the time is up a failing endpoint gives `[]` again (so the picker reports the problem) instead of an old list passing as current. The cache lives in the `OpenAILLM` object, so a restart or a changed `OPENAI_BASE_URL` starts fresh. Tests: `tests/test_llm.py`.
