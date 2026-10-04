"""Details of how a conversation reads: the line under a reply, the disclosure marker, the spacing."""
from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, send


def saved(page, count=1):
    expect(page.locator(".msg.assistant")).to_have_count(count)
    expect(page.locator(".msg.assistant").last.locator(".actions button").first).to_be_visible()


def test_the_model_and_the_cost_come_after_the_buttons_as_one_group(page, app_url):
    open_app(page, app_url)
    send(page, "ponder this")
    saved(page)
    children = page.locator(".msg.assistant .actions").evaluate(
        "e => [...e.children].map((c) => c.className || c.getAttribute('aria-label'))")
    assert children[-1] == "reply-meta"  # last: the buttons (copy, regenerate, another model) are together before it
    assert all(c != "reply-meta" for c in children[:-1])
    meta = page.locator(".msg.assistant .reply-meta")
    expect(meta.locator(".model-tag")).to_have_text("scripted-default")
    expect(meta.locator(".usage-tag")).to_have_text("1.2K in · 567 out")


def test_a_reply_with_no_count_has_the_model_alone(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    saved(page)
    expect(page.locator(".reply-meta .model-tag")).to_have_text("scripted-default")
    expect(page.locator(".reply-meta .usage-tag")).to_have_count(0)


def test_the_reasoning_and_tool_disclosures_use_a_chevron_that_turns(page, app_url):
    open_app(page, app_url)
    send(page, "ponder this")
    saved(page)
    summary = page.locator(".reasoning summary")
    marker = """(e) => [getComputedStyle(e).listStyleType, getComputedStyle(e, '::before').rotate]"""
    closed = summary.evaluate(marker)
    assert closed[0] == "none"  # not the browser's triangle
    summary.click()
    page.wait_for_function("() => document.getAnimations().every((a) => !(a instanceof CSSTransition))")
    opened = summary.evaluate(marker)
    assert opened[1] != closed[1]  # it turned
    assert page.locator(".reasoning summary").evaluate("e => e.textContent") == "Reasoning"  # the label is untouched


def test_your_message_and_its_reply_sit_closer_than_a_reply_and_your_next_message(page, app_url):
    open_app(page, app_url)
    send(page, "first")
    saved(page, 1)
    send(page, "second")
    saved(page, 2)
    rects = page.evaluate("""() => {
        const top = (e) => e.getBoundingClientRect().top, bottom = (e) => e.getBoundingClientRect().bottom
        const [u1, u2] = [...document.querySelectorAll('.msg.user .body')]
        const [a1] = [...document.querySelectorAll('.msg.assistant .body')]
        return { within: top(a1) - bottom(u1), between: top(u2) - bottom(a1) }
    }""")
    assert rects["within"] < rects["between"], rects
