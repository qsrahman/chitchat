import pytest

from app import db, store


@pytest.fixture
def conn(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    c = db.connect(path)
    yield c
    c.close()


def test_init_is_idempotent(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    db.init(path)
    assert db.connect(path).execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


def test_conversation_crud(conn):
    c = store.create_conversation(conn)
    assert c["title"] == store.DEFAULT_TITLE
    assert store.rename_conversation(conn, c["id"], "Hi")["title"] == "Hi"
    assert [x["id"] for x in store.list_conversations(conn)] == [c["id"]]
    assert store.delete_conversation(conn, c["id"]) is True
    assert store.get_conversation(conn, c["id"]) is None
    assert store.delete_conversation(conn, c["id"]) is False


def test_messages_ordered_with_meta(conn):
    c = store.create_conversation(conn)
    store.add_message(conn, c["id"], "user", "q")
    store.add_message(conn, c["id"], "assistant", "a", {"k": 1})
    msgs = store.list_messages(conn, c["id"])
    assert [(m["role"], m["content"], m["meta"]) for m in msgs] == [("user", "q", {}), ("assistant", "a", {"k": 1})]


def test_list_orders_by_recent_activity(conn):
    a, b = store.create_conversation(conn), store.create_conversation(conn)
    assert [x["id"] for x in store.list_conversations(conn)] == [b["id"], a["id"]]
    store.add_message(conn, a["id"], "user", "bump")
    assert [x["id"] for x in store.list_conversations(conn)] == [a["id"], b["id"]]


def test_delete_cascades_messages(conn):
    c = store.create_conversation(conn)
    store.add_message(conn, c["id"], "user", "q")
    store.delete_conversation(conn, c["id"])
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
