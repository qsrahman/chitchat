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

# Each entry upgrades the schema by one version; PRAGMA user_version records how many ran.
MIGRATIONS = [SCHEMA, SETTINGS, ATTACHMENTS]


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
