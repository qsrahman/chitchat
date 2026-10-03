# Round 3

Six changes made together, each its own commit.

## 1. Older attachments are not re-sent
Every call is stateless, so an image or PDF was sent again, in full, with every follow-up. Now `routes._history` sends the files of the **newest message that has attachments** and replaces those of older messages with a one-line note ("Attached earlier and not sent again. Ask the user to attach it again if you need it."), under the original file name. A follow-up about the picture you just attached works as before; attaching a new file makes the model forget the old one's contents (it still has its own earlier answers, which are in the text). The chat still shows every file. Tests: `tests/test_attachments.py`.
Trade-off: you can't ask the model to compare an old image with a new one without attaching the old one again. I picked this over "last N messages" because it needs no setting and the saving is the same in the common case.
