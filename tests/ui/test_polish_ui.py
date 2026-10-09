"""Details of how a conversation reads: the line under a reply, the disclosure marker, the spacing."""
import re

from playwright.sync_api import expect

from tests.ui.test_chat_ui import chat_menu, open_app, send


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


# ---- the new-chat screen ----

def seed(page, app_url, titles):
    """Chats that have a message (a reply and a title made from it), as every real chat has."""
    for title in titles:
        cid = page.request.post(f"{app_url}/api/conversations", data={}).json()["id"]
        page.request.post(f"{app_url}/api/conversations/{cid}/chat", data={"content": title})


def test_the_new_chat_screen_lists_the_latest_chats_and_nothing_when_there_are_none(page, app_url):
    open_app(page, app_url)
    expect(page.get_by_role("navigation", name="Recent chats")).to_be_hidden()
    seed(page, app_url, ["one", "two", "three", "four"])
    page.reload()
    recent = page.get_by_role("navigation", name="Recent chats")
    expect(recent.get_by_role("link")).to_have_text(
        [re.compile("^four"), re.compile("^three"), re.compile("^two")])  # newest first, three of them
    expect(recent.get_by_role("link").first.locator("time")).to_have_text("just now")
    expect(recent.get_by_role("heading", name="Pick up where you left off")).to_be_visible()
    recent.get_by_role("link", name="three").click()
    expect(page.locator("#title")).to_have_text("three")
    expect(recent).to_be_hidden()  # a conversation is open: the list is for the empty screen
    page.get_by_role("button", name="New chat").click()
    expect(recent.get_by_role("link")).to_have_count(3)


def test_the_recent_chats_do_not_include_archived_ones_or_follow_the_archive_view(page, app_url):
    open_app(page, app_url)
    seed(page, app_url, ["kept", "shelved"])
    shelved = next(c["id"] for c in page.request.get(f"{app_url}/api/conversations").json() if c["title"] == "shelved")
    page.request.patch(f"{app_url}/api/conversations/{shelved}", data={"archived": True})
    page.reload()
    recent = page.get_by_role("navigation", name="Recent chats")
    expect(recent.get_by_role("link")).to_have_text([re.compile("^kept")])
    page.get_by_role("button", name="Archived chats").click()
    expect(recent).to_be_hidden()  # the list is showing the archive: no "recent" to offer


# ---- the sidebar's width ----

def open_wide_sidebar(page, app_url):
    open_app(page, app_url)
    page.get_by_role("button", name="Show conversations").click()
    handle = page.get_by_role("separator", name="Sidebar width")
    expect(handle).to_be_visible()
    return handle


def sidebar_width(page):
    return page.locator("#sidebar").evaluate("e => Math.round(e.getBoundingClientRect().width)")


def test_the_sidebar_is_resized_with_the_keyboard_and_the_width_is_kept(page, app_url):
    handle = open_wide_sidebar(page, app_url)
    start = int(handle.get_attribute("aria-valuenow"))
    handle.focus()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    expect(handle).to_have_attribute("aria-valuenow", str(start + 32))
    assert sidebar_width(page) == start + 32
    page.keyboard.press("End")
    assert sidebar_width(page) == 480
    page.keyboard.press("Home")
    assert sidebar_width(page) == 224
    page.keyboard.press("ArrowRight")  # 240
    page.reload()
    page.get_by_role("button", name="Show conversations").click()
    assert sidebar_width(page) == 240  # kept in this browser


def test_the_sidebar_is_resized_by_dragging_its_edge_within_limits(page, app_url):
    handle = open_wide_sidebar(page, app_url)
    box = handle.bounding_box()
    y = box["y"] + 200
    page.mouse.move(box["x"] + box["width"] / 2, y)
    page.mouse.down()
    page.mouse.move(380, y)
    page.mouse.up()
    assert sidebar_width(page) == 380
    page.mouse.move(378, y)  # the edge, just inside the sidebar
    page.mouse.down()
    page.mouse.move(900, y)  # past the largest
    page.mouse.up()
    assert sidebar_width(page) == 480
    page.mouse.move(478, y)
    page.mouse.down()
    page.mouse.move(40, y)  # and the smallest
    page.mouse.up()
    assert sidebar_width(page) == 224


def test_only_the_open_wide_sidebar_has_a_resize_edge(page, app_url):
    open_app(page, app_url)
    expect(page.get_by_role("separator", name="Sidebar width")).to_be_hidden()  # the closed sidebar is a rail
    page.set_viewport_size({"width": 400, "height": 700})
    page.reload()
    page.get_by_role("button", name="Show conversations").first.click()
    expect(page.locator("#conversations")).to_be_visible()
    expect(page.get_by_role("separator", name="Sidebar width")).to_be_hidden()  # a drawer on a phone


def test_the_model_name_is_the_accent_and_readable_on_hover(page, app_url):
    open_app(page, app_url)
    color = lambda: page.locator("#model-name").evaluate("e => getComputedStyle(e).color")  # noqa: E731
    page.locator(".model-btn").evaluate("e => { e.style.transition = 'none' }")
    accent = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent')")
    assert accent  # defined
    resting = color()
    page.locator(".model-btn").hover()
    assert color() != resting  # on the hover background the accent is too faint for text, so it turns to the ink


def test_a_chat_waiting_to_be_deleted_is_not_a_recent_chat_and_undo_opens_it_again(page, app_url):
    open_app(page, app_url)
    send(page, "goner")  # made in this session, so it is only in the list the page has refreshed
    saved(page)
    chat_menu(page).get_by_role("menuitem", name="Delete…").click()
    page.get_by_role("dialog").get_by_role("button", name="Delete").click()
    expect(page.get_by_role("status")).to_contain_text('Deleted "goner"')
    expect(page.get_by_role("heading", name="What are you working on?")).to_be_visible()
    expect(page.get_by_role("navigation", name="Recent chats")).to_be_hidden()  # nothing left to show
    page.get_by_role("button", name="Undo").click()
    expect(page.locator("#title")).to_have_text("goner")  # it is open again


# ---- the end of the conversation stays in view ----

SCROLLS = "() => { const e = document.getElementById('messages'); return e.scrollHeight > e.clientHeight }"
AT_THE_END = ("() => { const e = document.getElementById('messages'); "
              "return e.scrollHeight - e.scrollTop - e.clientHeight < 2 }")


def gap_below(page):
    """How far the end of the thread is below the bottom of the visible pane (0: the reader is at the end)."""
    return page.locator("#messages").evaluate("e => e.scrollHeight - e.scrollTop - e.clientHeight")


def test_a_reader_at_the_end_stays_there_when_the_message_box_grows(page, app_url):
    page.set_viewport_size({"width": 1100, "height": 520})
    open_app(page, app_url)
    send(page, "long answer please")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible(timeout=15000)
    page.wait_for_function(SCROLLS)
    assert gap_below(page) < 2
    page.get_by_label("Message", exact=True).fill("one\ntwo\nthree\nfour\nfive\nsix")  # the box grows by lines
    expect(page.locator(".composer")).to_have_class("composer is-multiline")
    page.wait_for_function(AT_THE_END)
    expect(page.locator(".msg.assistant .actions button").first).to_be_in_viewport()  # not covered by the box


def test_a_scroll_event_that_arrives_after_the_pane_shrank_does_not_unpin_a_reader_at_the_end(page, app_url):
    """The last scroll of a reply can be delivered late, after the message box grew: measured against the smaller
    pane the reader looks 100px from the end, "scrolled up", and the pane then stayed where it was. The event is
    sent in the same task as the growth, before the pane's resize is noticed, which is the order that went wrong."""
    page.set_viewport_size({"width": 1100, "height": 520})
    open_app(page, app_url)
    send(page, "long answer please")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible(timeout=15000)
    page.wait_for_function(SCROLLS)
    assert gap_below(page) < 2
    page.evaluate("""() => {
        const box = document.getElementById('input')
        box.value = 'one\\ntwo\\nthree\\nfour\\nfive\\nsix'
        box.dispatchEvent(new Event('input', { bubbles: true }))
        document.getElementById('messages').dispatchEvent(new Event('scroll'))  // the late one
    }""")
    expect(page.locator(".composer")).to_have_class("composer is-multiline")
    page.wait_for_function(AT_THE_END)
    expect(page.locator(".msg.assistant .actions button").first).to_be_in_viewport()


def test_a_scroll_event_after_the_content_grew_does_not_stop_a_reply_being_followed(page, app_url):
    """The same race with the content growing, not the pane: something taller than 80 px appears without a scroll
    (a late layout change, an image, a section opening) and a scroll event that was already on its way is measured
    after it. A reader who never touched the scrollbar must still be taken to the end as the reply goes on."""
    page.set_viewport_size({"width": 1100, "height": 520})
    open_app(page, app_url)
    send(page, "long answer please")
    expect(page.locator(".msg.assistant .body")).to_contain_text("Paragraph 20 of")
    page.evaluate("""() => {
        const grown = document.createElement('div')
        grown.style.height = '400px'
        document.getElementById('thread').append(grown)
        document.getElementById('messages').dispatchEvent(new Event('scroll'))  // the late one
        grown.remove()
    }""")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible(timeout=15000)  # the reply is done
    page.wait_for_function(AT_THE_END)


def test_a_reader_who_scrolled_up_is_left_where_they_are_when_the_box_grows(page, app_url):
    page.set_viewport_size({"width": 1100, "height": 520})
    open_app(page, app_url)
    send(page, "long answer please")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible(timeout=15000)
    page.locator("#messages").evaluate("e => { e.scrollTop = 0 }")
    expect(page.get_by_role("button", name="Jump to latest")).to_be_visible()
    page.get_by_label("Message", exact=True).fill("one\ntwo\nthree\nfour\nfive\nsix")
    expect(page.locator(".composer")).to_have_class("composer is-multiline")
    assert page.locator("#messages").evaluate("e => e.scrollTop") < 5  # still at the top


def test_after_a_failed_reply_retry_has_its_word(page, app_url):
    open_app(page, app_url)
    send(page, "fail now")
    expect(page.locator(".msg.error")).to_contain_text("simulated failure")
    retry = page.get_by_role("button", name="Retry")
    expect(retry).to_be_visible()
    expect(retry).to_have_text("Retry")  # the word beside the icon, and the same name
    retry.click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply")
    expect(page.get_by_role("button", name="Regenerate")).to_have_text("")  # a normal reply keeps the bare icon
