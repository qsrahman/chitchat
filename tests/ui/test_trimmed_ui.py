"""The note under a reply when older messages were left out to fit a local model's context."""
from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, send
from tests.ui.test_search_ui import fake_turn

NOTE = "3 earlier messages were left out to fit the model's context."


def test_the_note_says_how_many_messages_were_left_out(page, app_url):
    open_app(page, app_url)
    fake_turn(page, {"type": "context_trimmed", "count": 3}, {"type": "delta", "text": "ok"}, {"type": "done"})
    send(page, "anything")
    expect(page.locator(".msg.assistant .body")).to_have_text("ok")
    expect(page.locator(".msg.assistant .note")).to_have_text(NOTE)


def test_one_message_reads_in_the_singular(page, app_url):
    open_app(page, app_url)
    fake_turn(page, {"type": "context_trimmed", "count": 1}, {"type": "delta", "text": "ok"}, {"type": "done"})
    send(page, "anything")
    expect(page.locator(".msg.assistant .note")).to_have_text(
        "1 earlier message was left out to fit the model's context.")


def test_the_note_survives_a_reload_and_sits_with_the_other_notes(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    conversation = page.evaluate("fetch('/api/conversations/' + location.hash.slice(1)).then((r) => r.json())")
    conversation["messages"][-1]["meta"] = {"trimmed": 3, "compaction": {"after_reply": True}}
    page.route("**/api/conversations/*", lambda route: route.fulfill(json=conversation)
               if route.request.method == "GET" else route.fallback())
    page.reload()
    expect(page.locator(".msg.assistant .note")).to_have_text(
        f"Earlier messages were compacted to save context. {NOTE}")
