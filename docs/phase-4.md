# Phase 4: settings

## What you can set
- **Per conversation** (Chat settings, the sliders button in the top bar): model, system prompt, and either reasoning effort or temperature. Stored as JSON in `conversations.settings`. The button gets a dot when anything differs from the defaults. Settings chosen on an empty "New chat" are sent when the chat is created by the first message.
- **Global** (Custom instructions, sidebar footer): one text, stored in the `app_settings` key/value table. It is sent with every conversation, before the conversation's own system prompt (joined by a blank line, as the Responses API `instructions`).
- Changes apply from the next message. Regenerate, edit and retry use the current settings.

## API
- `GET /api/models` -> `{default, models: [{id, reasoning}]}`. The configured `OPENAI_MODEL` comes first, then the chat models the endpoint's `/models` lists, newest first (see "Model list" below). If the endpoint can't list models, only the default is offered.
- `POST /api/conversations` takes an optional `{settings}`. `PATCH /api/conversations/{id}` takes `{title?, settings?}` (at least one); `settings` replaces the whole object.
- `GET/PUT /api/custom-instructions` -> `{text}`.
- Validation: `reasoning_effort` is the SDK's own `ReasoningEffort` type (the API also serves the list as `efforts`, which builds the dropdown), `temperature` 0 to 2, prompts and instructions up to 10,000 characters, unknown keys rejected.

## Design notes
- **Which parameter applies:** the API can't be asked whether a model takes `reasoning.effort` or `temperature`, so `llm.supports_reasoning()` goes by name (`o<digit>`, `gpt-5*`, `gpt-oss*` are reasoning models). The server sends only the parameter that applies, so a stale setting never reaches a model that would reject it. The settings dialog shows the matching control, and both for a model that is no longer listed.
- Titles are generated with the default model, not the one chosen for the chat.
- Schema migration v2 adds the `settings` column and `app_settings` table; existing conversations get the defaults (tested from a v1 database).
- `tests/test_llm.py` covers `OpenAILLM` offline against a fake SDK client (what is sent, event normalization, model listing).

## Model list
OpenAI's `/models` returns everything it serves (133 ids on the account this was tested with). `llm.list_models()` narrows that to what a text chat can use (45 there), newest first by the `created` timestamp:
- **Hidden as not chat:** embeddings, moderation, speech and audio (`tts`, `whisper`, `transcribe`, `audio`, `realtime`, `live`), image and video generation (`image`, `sora`), completion-only models (`babbage`, `davinci`, `gpt-3.5-turbo-instruct`) and search-only models (`search-preview`, `search-api`). The word rules match whole hyphen-separated words, and `instruct` is only matched for OpenAI's own model, so local models like `llama3-instruct`, `qwen3.5:9b-instruct` and `llama3.2-vision` stay.
- **Hidden as duplicates:** a dated copy such as `gpt-4o-2024-08-06` is hidden when its alias (`gpt-4o`) is listed. One without a listed alias stays.
- **Kept:** `*-pro`, `*-codex`, `chat-latest` and the like, which answer through the Responses API.
- The rules are name-based, as with `supports_reasoning`: a model that is hidden by mistake can still be the default through `OPENAI_MODEL`, and one that is shown but unsuitable fails with the provider's own message.
- **Reasoning models** are now `o<digit>`, `gpt-5` and later (`gpt-[5-9]`) and `gpt-oss`. The `gpt-6*` and `gpt-5.6*` models reject `temperature` and take reasoning effort, which the old `gpt-5` pattern missed.
