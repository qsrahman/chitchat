# Round 3

Six changes made together, each its own commit.

## 1. Older attachments are not re-sent
Every call is stateless, so an image or PDF was sent again, in full, with every follow-up. Now `routes._history` sends the files of the **newest message that has attachments** and replaces those of older messages with a one-line note ("Attached earlier and not sent again. Ask the user to attach it again if you need it."), under the original file name. A follow-up about the picture you just attached works as before; attaching a new file makes the model forget the old one's contents (it still has its own earlier answers, which are in the text). The chat still shows every file. Tests: `tests/test_attachments.py`.
Trade-off: you can't ask the model to compare an old image with a new one without attaching the old one again. I picked this over "last N messages" because it needs no setting and the saving is the same in the common case.

## 2. Type checking with pyright
`uv run pyright` checks `app/` (basic mode; the tests are not checked) and is a step in `scripts/check.py` after ruff. The first run found 17 errors. Most were missing `None` checks or loose annotations, fixed with narrowing or an annotation. Two things were real:
- **Image parts lacked `detail`.** The SDK's type for an image input requires it; `llm._content` sent `{"type": "input_image", "image_url": ...}` without. The API treats a missing value as `"auto"`, so nothing was failing, and the code now says `"detail": "auto"`.
- **The calculator's `type(value) in (int, float)` guard** (which keeps `True` out) is now a class pattern plus `type(value) is not bool`, which pyright can follow.
Two `assert`s in `store.py` say that a row just inserted is there. Not done: the tests and the front end are not type-checked.
