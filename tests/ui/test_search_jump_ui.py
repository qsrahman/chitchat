"""Search finds chats by title, and a result for a message opens the chat at that message."""
import re

from playwright.sync_api import expect

from tests.ui.test_chat_ui import conv_id, open_app, open_sidebar, row_action, send


def search_box(page):
    return page.get_by_role("searchbox", name="Search conversations")


def finished(page):
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible(timeout=15_000)


def long_chat_then_another(page, app_url):
    """A chat whose first message is far above the end (the reply is long), then a different chat."""
    open_app(page, app_url)
    send(page, "needle zebrafish long answer")
    finished(page)
    first = conv_id(page)
    page.get_by_role("button", name="New chat").click()
    send(page, "an unrelated chat")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #")
    return first


def in_view(page, locator):
    box = locator.bounding_box()
    viewport = page.locator("#messages").bounding_box()
    top, bottom = viewport["y"] - 1, viewport["y"] + viewport["height"] + 1
    return box is not None and box["y"] >= top and box["y"] + box["height"] <= bottom


def test_a_chat_is_found_by_its_title_with_the_match_highlighted(page, app_url):
    open_app(page, app_url)
    send(page, "tell me about quokkas")  # the scripted model titles a chat with its first words
    expect(page.locator("#title")).to_have_text("tell me about quokkas")  # titled: saved, and searchable
    open_sidebar(page)
    search_box(page).fill("tell")
    result = page.locator(".result")
    expect(result).to_have_count(1)
    expect(result.locator("strong mark")).to_have_text("tell")  # in the title
    expect(result.locator("strong")).to_have_text("tell me about quokkas")


def test_a_message_result_shows_the_title_and_the_snippet_with_marks_in_both(page, app_url):
    open_app(page, app_url)
    send(page, "my wombat question")
    finished(page)  # the reply is saved (the placeholder shows at once, before the message reaches the server)
    open_sidebar(page)
    search_box(page).fill("wombat")
    expect(page.locator(".result strong mark")).to_have_text("wombat")
    expect(page.locator(".result span mark").first).to_have_text("wombat")


def test_a_title_only_match_has_no_snippet(page, app_url):
    open_app(page, app_url)
    send(page, "kangaroo facts")
    expect(page.locator("#title")).to_have_text("kangaroo facts")  # titled: saved, and searchable
    open_sidebar(page)
    row_action(page, "kangaroo facts", "Rename…")
    page.get_by_label("Conversation title").fill("Marsupial notes")
    page.get_by_role("button", name="Save").click()
    search_box(page).fill("marsupial")
    expect(page.locator(".result strong mark")).to_have_text("Marsupial")
    expect(page.locator(".result span")).to_have_count(0)


def test_a_message_result_opens_that_chat_scrolled_to_the_message_and_lights_it(page, app_url):
    long_chat_then_another(page, app_url)
    open_sidebar(page)
    search_box(page).fill("needle")
    page.locator(".result").click()
    target = page.locator(".msg.user .body", has_text="needle zebrafish")
    expect(target).to_be_visible()
    expect(page.locator(".msg.is-found")).to_have_count(1)
    assert in_view(page, target)  # not left at the end of the long reply
    assert page.evaluate("""() => { const m = document.querySelector('#messages');
                           return m.scrollTop + m.clientHeight < m.scrollHeight - 200; }""")  # not at the end
    page.wait_for_function("() => document.querySelectorAll('.msg.is-found').length === 0", timeout=6000)  # it fades


def test_a_result_for_the_chat_already_open_scrolls_there_without_reloading_the_page(page, app_url):
    open_app(page, app_url)
    send(page, "needle zebrafish long answer")
    finished(page)
    page.evaluate("window.__same = true")  # a reload would lose this
    url = page.url
    open_sidebar(page)
    search_box(page).fill("needle")
    page.locator(".result").click()
    expect(page.locator(".msg.is-found")).to_have_count(1)
    assert in_view(page, page.locator(".msg.user .body", has_text="needle zebrafish"))
    assert page.url == url and page.evaluate("window.__same") is True


def test_a_title_match_opens_the_chat_at_the_end_as_usual(page, app_url):
    long_chat_then_another(page, app_url)
    open_sidebar(page)
    page.locator(".conv").nth(1).get_by_role("button", name=re.compile("^Actions for")).click()  # the older, long chat
    page.get_by_role("menuitem", name="Rename…").click()
    page.get_by_label("Conversation title").fill("Aardvark archive")
    page.get_by_role("button", name="Save").click()
    search_box(page).fill("aardvark")
    expect(page.locator(".result strong")).to_have_text("Aardvark archive")
    expect(page.locator(".result span")).to_have_count(0)  # by title only: nothing inside it to point at
    page.locator(".result").click()
    expect(page.locator(".msg.user .body", has_text="needle zebrafish")).to_have_count(1)
    expect(page.locator(".msg.is-found")).to_have_count(0)
    page.wait_for_function("""() => { const m = document.querySelector('#messages');
                                     return m.scrollTop + m.clientHeight >= m.scrollHeight - 5; }""")  # at the end


def test_the_highlight_is_not_there_after_a_reload(page, app_url):
    long_chat_then_another(page, app_url)
    open_sidebar(page)
    search_box(page).fill("needle")
    page.locator(".result").click()
    expect(page.locator(".msg.is-found")).to_have_count(1)
    page.reload()
    expect(page.locator(".msg.user .body", has_text="needle zebrafish")).to_be_visible()
    expect(page.locator(".msg.is-found")).to_have_count(0)
