# Phase 4: settings

## What you can set
- **Per conversation** (Chat settings, the sliders button in the top bar): model, system prompt, and either reasoning effort or temperature. Stored as JSON in `conversations.settings`. The button gets a dot when anything differs from the defaults. Settings chosen on an empty "New chat" are sent when the chat is created by the first message.
- **Global** (Custom instructions, sidebar footer): one text, stored in the `app_settings` key/value table. It is sent with every conversation, before the conversation's own system prompt (joined by a blank line, as the Responses API `instructions`).
- Changes apply from the next message. Regenerate, edit and retry use the current settings.

## API
- `GET /api/models` -> `{default, models: [{id, reasoning}]}`. The configured `OPENAI_MODEL` comes first, then whatever the endpoint's `/models` lists (embedding models hidden). If the endpoint can't list models, only the default is offered.
- `POST /api/conversations` takes an optional `{settings}`. `PATCH /api/conversations/{id}` takes `{title?, settings?}` (at least one); `settings` replaces the whole object.
- `GET/PUT /api/custom-instructions` -> `{text}`.
- Validation: `reasoning_effort` is `low|medium|high`, `temperature` 0 to 2, prompts and instructions up to 10,000 characters, unknown keys rejected.

## Design notes
- **Which parameter applies:** the API can't be asked whether a model takes `reasoning.effort` or `temperature`, so `llm.supports_reasoning()` goes by name (`o<digit>`, `gpt-5*`, `gpt-oss*` are reasoning models). The server sends only the parameter that applies, so a stale setting never reaches a model that would reject it. The settings dialog shows the matching control, and both for a model that is no longer listed.
- Titles are generated with the default model, not the one chosen for the chat.
- Schema migration v2 adds the `settings` column and `app_settings` table; existing conversations get the defaults (tested from a v1 database).
- `tests/test_llm.py` covers `OpenAILLM` offline against a fake SDK client (what is sent, event normalization, model listing).
