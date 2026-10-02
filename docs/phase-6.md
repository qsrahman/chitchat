# Phase 6: attachments

Images, PDFs and text files, attached to a user message.

## Flow
1. **Upload on select.** Choosing, dropping or pasting files uploads each one right away (`POST /api/attachments`, multipart). The server stores the bytes under `ATTACHMENTS_DIR/<id>`, records a row in `attachments` and answers `{id, name, mime, kind, size}`. The composer shows a chip per file (thumbnail for images), with a remove button, and Send waits until uploads finish.
2. **Send by id.** `POST /api/conversations/{id}/chat` takes `{content?, attachments: [ids]}`. The ids are checked before anything is saved (unknown, already sent or duplicated gives 422; at most 5 per message), then linked to the conversation and copied into the user message's `meta.attachments` for display. A message may be attachments only; its title then comes from the file names.
3. **Every turn re-sends them.** Calls are stateless, so earlier attachments go to the model again with each new turn (context management in phase 8 can trim this). Regenerate and edit keep a message's attachments; edit changes only its text.

## What is accepted
Decided from the file's bytes (the `filetype` package), never the file name or the client's content type:

| Kind | Types | Limit | What the model gets |
|---|---|---|---|
| image | PNG, JPEG, GIF, WebP | 10 MB | `input_image` (data URL) |
| text | any UTF-8 text without NUL bytes (code, markdown, CSV, HTML, SVG...) | 256 KB | `input_text` wrapped in `<file name="...">`, name escaped |
| pdf | PDF | 20 MB | its extracted text as `input_text` (default), or the PDF itself as `input_file` |

Anything else is refused with 415 and a message that the chip shows. Extracted PDF text and text files are capped at 200,000 characters.

### PDFs: `OPENAI_PDF_INPUT`
- `text` (default): the text is extracted with `pypdf` when the file is uploaded and cached next to it (`<id>.txt`). Works with every model and endpoint. A PDF with no text (scans) or a password is refused at upload, with the reason.
- `file`: the PDF goes to the API as `input_file`. OpenAI reads the text and the page images, but local servers often refuse it (Ollama answered "file inputs are not currently supported"). Verified against OpenAI.

### Images and models
Whether a model accepts images can't be asked of the API, so the attach button is never disabled. Local models differ (`gemma4` and `qwen3.5` read images on Ollama; `gpt-oss` refuses). A refusal is shown as the provider's own message, and you can switch model in the header and Retry. `llm.py` now reports `error.body.message` instead of the SDK's wrapped "Error code: 400 - {...}" text, and unwraps JSON nested inside it.

## Storage and safety
- `attachments(id, conversation_id NULL until sent, name, mime, kind, size, created_at)`. Deleting a conversation deletes its rows (cascade) and its files. Uploads never sent with a message are purged at startup after 24 hours.
- `GET /api/attachments/{id}` serves the file as the type we detected (text always as `text/plain`, never HTML or SVG), images inline and everything else as a download, with `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`.
- File names lose any path, are limited to 200 characters, and are only ever shown as text.
- Not applied: scanning uploads for malware, and OCR for scanned PDFs.

## UI
Paperclip button, drag and drop anywhere on the page (an overlay shows while dragging files), paste for screenshots, chips with errors ("Unsupported file type...", "You can attach up to 5 files."), and tiles in the sent message (image thumbnails open full size in a new tab; other files download). Switching conversation clears unsent chips. Drafts do not include attachments.

Tests: `tests/test_attachments.py` (upload, serving, sending, cleanup, migration), `tests/test_llm.py` (input parts, error messages), `tests/ui/test_attachments_ui.py`.
