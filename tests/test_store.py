import sqlite3
from contextlib import closing

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


def test_messages_form_a_path_and_each_new_one_follows_the_last(conn):
    c = store.create_conversation(conn)["id"]
    assert store.list_messages(conn, c) == []
    q1 = store.add_message(conn, c, "user", "q1")
    a1 = store.add_message(conn, c, "assistant", "a1")
    assert (q1["parent_id"], a1["parent_id"]) == (None, q1["id"])
    path = store.list_messages(conn, c)
    assert [(m["content"], m["parent_id"], m["siblings"]) for m in path] == [
        ("q1", None, [q1["id"]]), ("a1", q1["id"], [a1["id"]])]
    assert store.get_conversation(conn, c)["leaf_id"] == a1["id"]


def test_a_second_child_is_a_version_and_the_path_follows_the_newest(conn):
    c = store.create_conversation(conn)["id"]
    q1 = store.add_message(conn, c, "user", "q1")
    a1 = store.add_message(conn, c, "assistant", "a1")
    q2 = store.add_message(conn, c, "user", "q2")
    store.add_message(conn, c, "assistant", "a2")
    q2b = store.add_message(conn, c, "user", "q2 edited", parent_id=a1["id"])  # an edit of q2
    a2b = store.add_message(conn, c, "assistant", "a2 edited", parent_id=q2b["id"])
    path = store.list_messages(conn, c)
    assert [m["content"] for m in path] == ["q1", "a1", "q2 edited", "a2 edited"]
    assert path[2]["siblings"] == [q2["id"], q2b["id"]]
    assert path[0]["siblings"] == [q1["id"]]
    assert store.get_conversation(conn, c)["leaf_id"] == a2b["id"]
    assert [m["content"] for m in store.all_messages(conn, c)] == ["q1", "a1", "q2", "a2", "q2 edited", "a2 edited"]


def test_select_branch_shows_the_path_through_a_message_to_its_newest_end(conn):
    c = store.create_conversation(conn)["id"]
    store.add_message(conn, c, "user", "q")
    a1 = store.add_message(conn, c, "assistant", "first reply")
    store.add_message(conn, c, "user", "follow-up to the first")
    store.add_message(conn, c, "assistant", "answer to the follow-up")
    store.add_message(conn, c, "assistant", "second reply", parent_id=a1["parent_id"])
    assert [m["content"] for m in store.list_messages(conn, c)] == ["q", "second reply"]
    assert store.select_branch(conn, c, a1["id"])
    assert [m["content"] for m in store.list_messages(conn, c)] == [
        "q", "first reply", "follow-up to the first", "answer to the follow-up"]  # on to the newest end
    assert not store.select_branch(conn, c, 99999)
    other = store.create_conversation(conn)["id"]
    assert not store.select_branch(conn, other, a1["id"])  # not another conversation's message


def test_a_new_first_message_is_a_version_of_the_first_message(conn):
    c = store.create_conversation(conn)["id"]
    q = store.add_message(conn, c, "user", "q")
    q2 = store.add_message(conn, c, "user", "q reworded", parent_id=None)
    assert store.siblings_of(conn, c, q["id"]) == [q["id"], q2["id"]]
    assert [m["content"] for m in store.list_messages(conn, c)] == ["q reworded"]


def test_the_migration_makes_an_old_conversation_one_straight_path(tmp_path):
    path = str(tmp_path / "old.db")
    with closing(sqlite3.connect(path)) as raw:  # a database as it was before branching: five migrations
        for i, script in enumerate(db.MIGRATIONS[:5], 1):
            raw.executescript(script)
            raw.execute(f"PRAGMA user_version = {i}")
        raw.execute("INSERT INTO conversations (id, title, created_at, updated_at) VALUES ('c', 't', 'x', 'x')")
        raw.execute("INSERT INTO conversations (id, title, created_at, updated_at) VALUES ('empty', 't', 'x', 'x')")
        for role in ("user", "assistant", "user"):
            raw.execute("INSERT INTO messages (conversation_id, role, content, created_at) VALUES ('c', ?, ?, 'x')",
                        (role, role))
        raw.commit()
    db.init(path)
    with closing(db.connect(path)) as conn:
        assert [(m["role"], m["parent_id"]) for m in store.list_messages(conn, "c")] == [
            ("user", None), ("assistant", 1), ("user", 2)]
        assert store.get_conversation(conn, "c")["leaf_id"] == 3
        assert store.get_conversation(conn, "empty")["leaf_id"] is None
        assert store.list_messages(conn, "empty") == []
