import sqlite3
from contextlib import closing

SCHEMA = """
CREATE TABLE conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    meta            TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL
);
CREATE INDEX messages_by_conversation ON messages(conversation_id, id);
"""

# v2: per-conversation settings (JSON) and a small key/value table for app-wide settings.
SETTINGS = """
ALTER TABLE conversations ADD COLUMN settings TEXT NOT NULL DEFAULT '{}';
CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# v3: uploaded files. conversation_id stays NULL until the file is sent with a message, which is what lets the
# app tell abandoned uploads (to purge) from attached ones.
ATTACHMENTS = """
CREATE TABLE attachments (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    mime            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    size            INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX attachments_by_conversation ON attachments(conversation_id);
"""

# v4: full-text search over message text. An external-content FTS5 index (the text is not stored twice) that
# triggers keep in step with `messages`, which includes the cascade when a conversation is deleted.
SEARCH = """
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content, content='messages', content_rowid='id', tokenize='porter unicode61'
);
INSERT INTO messages_fts(rowid, content) SELECT id, content FROM messages;
CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER messages_fts_delete AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER messages_fts_update AFTER UPDATE OF content ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
"""

# v5: the same for conversation titles, so a search finds a chat by its name too. (SQLite keeps an implicit
# rowid on `conversations`, which is what the index points at.)
TITLE_SEARCH = """
CREATE VIRTUAL TABLE conversations_fts USING fts5(
    title, content='conversations', content_rowid='rowid', tokenize='porter unicode61'
);
INSERT INTO conversations_fts(rowid, title) SELECT rowid, title FROM conversations;
CREATE TRIGGER conversations_fts_insert AFTER INSERT ON conversations BEGIN
    INSERT INTO conversations_fts(rowid, title) VALUES (new.rowid, new.title);
END;
CREATE TRIGGER conversations_fts_delete AFTER DELETE ON conversations BEGIN
    INSERT INTO conversations_fts(conversations_fts, rowid, title) VALUES ('delete', old.rowid, old.title);
END;
CREATE TRIGGER conversations_fts_update AFTER UPDATE OF title ON conversations BEGIN
    INSERT INTO conversations_fts(conversations_fts, rowid, title) VALUES ('delete', old.rowid, old.title);
    INSERT INTO conversations_fts(rowid, title) VALUES (new.rowid, new.title);
END;
"""

# v6: branching. A message points at the message it answers (or, for a user message, follows), so a conversation is
# a tree and what you see is the path from its root to `leaf_id`. Editing or regenerating adds a sibling instead of
# deleting what came after. Existing conversations become one straight path: each message's parent is the message
# before it. (No foreign key: nothing deletes single messages, and a conversation takes all its messages with it.)
BRANCHING = """
ALTER TABLE messages ADD COLUMN parent_id INTEGER;
ALTER TABLE conversations ADD COLUMN leaf_id INTEGER;
UPDATE messages SET parent_id = (
    SELECT m2.id FROM messages m2 WHERE m2.conversation_id = messages.conversation_id AND m2.id < messages.id
    ORDER BY m2.id DESC LIMIT 1);
UPDATE conversations SET leaf_id = (SELECT MAX(id) FROM messages WHERE conversation_id = conversations.id);
CREATE INDEX messages_by_parent ON messages(conversation_id, parent_id);
"""

# Each entry upgrades the schema by one version; PRAGMA user_version records how many ran.
MIGRATIONS = [SCHEMA, SETTINGS, ATTACHMENTS, SEARCH, TITLE_SEARCH, BRANCHING]


def connect(path: str) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI may run a request's dependency and handler on different threads.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(path: str) -> None:
    with closing(connect(path)) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {i}")
