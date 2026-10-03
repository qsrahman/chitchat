# Small improvements

A batch of four, each its own commit.

## 1. A small model for chat titles
Titles were written by the default model (`gpt-5.5`, a reasoning model) for six words. `TITLE_MODEL` now picks the model; empty means `gpt-5.4-nano` on OpenAI, or `OPENAI_MODEL` when `OPENAI_BASE_URL` is set, because a custom endpoint (Ollama) doesn't have OpenAI's model names and every title call would fail (`Settings.title_model_name`). Measured on one title: `gpt-5.5` 3.0 s, `gpt-5.4-nano` 1.1 s, `gpt-5.4-mini` 1.0 s. A title model that can't be reached still falls back to the first words of the message, as before. Tests: `tests/test_settings.py`.

## 2. The model list is cached for five minutes
`GET /api/models` listed models from the provider on every call: on page load, whenever the picker opens, and in the background when the settings dialog opens. That is a remote call each time. `OpenAILLM.list_models` now remembers a successful answer for `MODELS_TTL` (300 s). A failed listing is never remembered, and once the time is up a failing endpoint gives `[]` again (so the picker reports the problem) instead of an old list passing as current. The cache lives in the `OpenAILLM` object, so a restart or a changed `OPENAI_BASE_URL` starts fresh. Tests: `tests/test_llm.py`.

## 3. Right-to-left text
Urdu, Arabic and Hebrew now align and flow correctly, per block, without a setting:
- The message box, search box, title, rename field and the settings textareas have `dir="auto"`, so their direction follows the first strong character typed. Your sent messages, error lines, sidebar titles, search results and tool-call lines do too.
- Rendered replies get `dir="auto"` on the **outermost** text block (paragraph, heading, list, quote, table) in the sanitizer hook in `markdown.js`. An Arabic paragraph runs right to left while an English paragraph in the same reply stays left to right. Only outermost blocks, because the browser skips descendants that carry their own `dir` when it looks for the first strong character, so a list whose items each had `dir` found no text and stayed left to right (a bug caught by the tests).
- Code blocks are always `dir="ltr"`.
- Layout uses logical properties where text is concerned (`padding-inline-start`, `border-inline-start`, `text-align: start`), so list markers and the quote bar move to the right side of right-to-left text. A right-to-left block is placed at the right edge of the column with `:dir(rtl)`, because a narrow block is positioned by its container's direction, not its own.
- The chrome (sidebar, composer controls, the streaming edge) stays left to right: the interface language is English.
Not done: a right-to-left interface layout and KaTeX in right-to-left text beyond what the browser does. Tests: `tests/ui/test_rtl_ui.py`.
