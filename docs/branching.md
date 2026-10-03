# Versions of a message (branching)

Editing a message or regenerating a reply used to delete what came after it. Now the old text stays as another **version**, and a message that has more than one shows `‹ 2 / 3 ›` to move between them. What you see is always one path through the conversation.

## The model
- Every message has a `parent_id`: the message it follows (null for the first). A conversation is therefore a tree. `conversations.leaf_id` is the end of the path being shown; the path is the messages from the root to that leaf (`store.list_messages`, a recursive query, newest at the end).
- A message's **siblings** are the messages with the same parent, oldest first, itself included: the versions of an edited message (siblings under the same previous reply), or of a regenerated reply (siblings under the same user message). `list_messages` returns them as `siblings` (ids) with each message; the page shows the switcher when there are two or more.
- Migration v6 gives existing conversations a straight path: each message's parent is the one before it, and the leaf is the last. Nothing deletes a single message any more; deleting a conversation still takes all of them.
- No foreign key on `parent_id`: nothing removes single messages, and a conversation's messages go together. (`store.select_branch` and the import check what they point at.)

## What each action does
| Action | Endpoint | Effect |
|---|---|---|
| Send | `POST .../chat` | adds a user message after the leaf, then the reply under it |
| Regenerate / Retry | `POST .../regenerate` | moves the leaf to the last user message on the path (so the old reply is no longer shown) and adds a new reply under it; the old reply stays as a version |
| Edit | `POST .../edit {content, message_id?}` | adds a new user message with the same parent and attachments as `message_id` (default: the last user message on the path), then the reply. Any user message on the path can be edited, not only the last. What came after the old version stays with it |
| Switch version | `POST .../branch {message_id}` | shows the path through that message, then follows at every step the child remembered there (else the newest) to the end. Returns the conversation like `GET` |

Edit and Regenerate set the leaf **before** the reply streams, so a reply that fails leaves the conversation ending on your message, with Retry, as a failed send always did. The model only ever sees the path shown (`routes._history`), never other versions.

## The page
- Edit is on every message of yours now. Saving removes the messages below it from view, as before, and streams the new reply; the old path is one click away on the switcher.
- The turn's final `done` event carries `branch: {user: {id, siblings}, assistant: {id, siblings}}`, so a message streamed in this session gets its id and its versions without loading the conversation again. A reply that was stopped or failed has neither; Edit asks the server (`syncIds` in `chat.js`) the first time it needs one.
- Switching calls `.../branch`, then opens the conversation again, scrolled to that message.
- A message with versions keeps its action row visible (the others show it on hover), so `2 / 3` is never hidden.
- **Search** covers every version (the text indexes see all messages). A result in a version that is not showing opens the conversation, asks the server to show that version, and scrolls to the message (`openConversation` in `app.js`).

## Export and import
- The backup holds every version (`docs/backup.md`, format version 2): `parent` and `leaf` are positions in a chat's message list. Version 1 files import as one path. The export of one chat, and the Markdown files, are the path showing.
- The title, usage and compaction logic work on the path shown: a compaction item saved in a version is only used on paths that contain it.

## Limits and choices
- **Switching goes back to where you left.** Each message remembers which reply came after it the last time the path showing went through it (`messages.chosen_id`, migration v7), and switching to a version follows those, falling back to the newest reply where nothing is remembered. The path is remembered whenever it is left: when you switch (`select_branch`), when an edit or a regenerate starts a new version (`add_message` with another parent, `set_leaf`). So after reading reply 1 of 2, editing the message and coming back to the original, you see reply 1, not reply 2. Imported chats have no memory and start at the newest.
- **No way to delete a version**, and no way to start a new conversation from one. Deleting a conversation removes all of its versions.
- **Search results from versions you left** are still found, and a conversation's `search_chats` tool call can quote one.
- **A stopped reply is a version too.** Stopping a reply keeps its text; Retry or Regenerate then adds a second version beside it.
- **Not tried:** a conversation with thousands of messages in many versions (the path is one recursive query and the sibling lists one scan of the conversation's messages, both linear).

Tests: `tests/test_store.py` (the tree, switching, the migration), `tests/test_branching.py` (the endpoints), `tests/test_backup.py` (export, import, refused files), `tests/ui/test_branching_ui.py`, `tests/ui/test_a11y_ui.py`.
