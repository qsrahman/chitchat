from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, send


def copy_button(page, message):
    return message.locator(".actions").get_by_role("button", name="Copy", exact=True)


def clipboard(page):
    return page.evaluate("navigator.clipboard.readText()")


def test_every_message_has_its_own_copy_button_that_copies_only_that_message(page, app_url):
    open_app(page, app_url)
    send(page, "first question")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    send(page, "second question")
    expect(page.locator(".msg.assistant").nth(1)).to_contain_text("Reply #2")
    expect(page.locator(".msg.assistant").nth(1).locator(".actions button").first).to_be_visible()  # saved
    users, replies = page.locator(".msg.user"), page.locator(".msg.assistant")
    expect(page.locator(".msg .actions").get_by_role("button", name="Copy", exact=True)).to_have_count(4)

    copy_button(page, users.nth(0)).click()
    assert clipboard(page) == "first question"
    copy_button(page, replies.nth(0)).click()
    assert clipboard(page) == "Reply #1 to **first question**"  # the raw markdown, not the second reply too
    copy_button(page, users.nth(1)).click()
    assert clipboard(page) == "second question"
    copy_button(page, replies.nth(1)).click()
    assert clipboard(page) == "Reply #2 to **second question**"


def test_copy_on_your_message_confirms_like_the_others(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    user = page.locator(".msg.user")
    copy_button(page, user).click()
    expect(user.locator(".actions").get_by_role("button", name="Copied", exact=True)).to_be_visible()
    expect(copy_button(page, user)).to_be_visible()


def test_copy_keeps_the_text_exactly_including_line_breaks(page, app_url):
    open_app(page, app_url)
    page.get_by_label("Message", exact=True).fill("line one")
    page.keyboard.press("Shift+Enter")
    page.keyboard.type("line two")
    page.keyboard.press("Enter")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    copy_button(page, page.locator(".msg.user")).click()
    assert clipboard(page) == "line one\nline two"


def test_copy_is_still_there_after_a_reload(page, app_url):
    open_app(page, app_url)
    send(page, "remember me")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    page.reload()
    expect(page.locator(".msg.user")).to_be_visible()
    copy_button(page, page.locator(".msg.user")).click()
    assert clipboard(page) == "remember me"


def test_a_message_with_only_an_attachment_has_no_copy_button(page, app_url):
    from tests.helpers import PNG

    open_app(page, app_url)
    page.locator("#file-input").set_input_files({"name": "cat.png", "mimeType": "image/png", "buffer": PNG})
    expect(page.locator(".chip")).to_have_count(1)
    expect(page.locator("#send")).to_be_enabled(timeout=10_000)
    page.locator("#send").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    expect(copy_button(page, page.locator(".msg.user"))).to_have_count(0)
    expect(copy_button(page, page.locator(".msg.assistant"))).to_have_count(1)
